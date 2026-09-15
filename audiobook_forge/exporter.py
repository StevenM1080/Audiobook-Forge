from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from array import array
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from mutagen import File

from .cover import normalize_cover
from .models import Book, BookMetadata, Chapter, book_output_path, title_with_subtitle


ProgressCallback = Callable[[int, str], None]
BookFinishedCallback = Callable[[int, Book, Path], None]
BookProgressCallback = Callable[[int, Book, int, str], None]
ChannelModeResolvedCallback = Callable[[int], None]

AUTO_STEREO_SAMPLE_SECONDS = 20
AUTO_STEREO_SAMPLE_RATE = 16000
AUTO_STEREO_DIFFERENCE_THRESHOLD = 0.05
MINIMUM_UNBOUNDED_CHAPTER_FFMPEG = (5, 0, 0)


class ExportCancelled(Exception):
    """Raised internally when an audiobook export is cancelled."""


def metadata_value(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        normalized.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", "\\n")
    )


def metadata_for_book(metadata: BookMetadata) -> dict[str, str]:
    """Map application metadata to the common FFmpeg/MP4 tag names."""

    full_title = title_with_subtitle(metadata.title, metadata.subtitle)
    values = {
        "title": full_title,
        "artist": metadata.author.strip(),
        "album_artist": metadata.author.strip(),
        "album": full_title,
        "composer": metadata.narrator.strip(),
        "grouping": metadata.series.strip(),
        "series_number": metadata.series_number.strip(),
        "date": metadata.year.strip(),
        "genre": metadata.genre.strip(),
        "comment": metadata.description.strip(),
        "publisher": metadata.publisher.strip(),
        "language": metadata.language.strip(),
    }
    return {key: value for key, value in values.items() if value}


def concat_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "'\\''")


def format_time(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    return (
        f"{total_seconds // 3600:02d}:"
        f"{total_seconds % 3600 // 60:02d}:"
        f"{total_seconds % 60:02d}"
    )


def _tool_candidates(
    name: str,
    configured: str | None = None,
    *,
    app_path: Path | None = None,
    sibling_directories: Sequence[Path] = (),
) -> list[Path]:
    executable_name = f"{name}.exe" if os.name == "nt" else name
    application = (app_path or Path(sys.argv[0])).resolve()
    candidates: list[Path] = [application.parent / executable_name]
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(directory / executable_name for directory in sibling_directories)
    system_path = shutil.which(name)
    if system_path:
        candidates.append(Path(system_path))
    if os.name == "nt":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates.extend(
            Path(directory) / "Jellyfin" / "Server" / executable_name
            for directory in (program_files, program_files_x86)
        )
    candidates.append(Path.home() / ".spotdl" / executable_name)
    return candidates


def discover_tool(
    name: str,
    configured: str | None = None,
    *,
    app_path: Path | None = None,
    sibling_directories: Sequence[Path] = (),
) -> Path | None:
    candidates = _tool_candidates(
        name,
        configured,
        app_path=app_path,
        sibling_directories=sibling_directories,
    )

    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate.resolve()
    return None


def _tool_version(path: Path) -> tuple[int, ...] | None:
    try:
        result = subprocess.run(
            [str(path), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"ffmpeg version (\d+(?:\.\d+){0,2})", result.stdout)
    if not match:
        return None
    try:
        parts = tuple(int(part) for part in match.group(1).split("."))
        return parts + (0,) * (3 - len(parts))
    except ValueError:
        return None


def _chapter_safe_ffmpeg(
    current: Path,
    configured: str | None,
    *,
    app_path: Path | None = None,
) -> Path:
    candidates = [current]
    candidates.extend(
        _tool_candidates("ffmpeg", configured, app_path=app_path)
    )
    seen: set[str] = set()
    compatible: list[tuple[tuple[int, ...], Path]] = []
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key in seen or not candidate.is_file():
            continue
        seen.add(key)
        version = _tool_version(candidate)
        if version is not None and version >= MINIMUM_UNBOUNDED_CHAPTER_FFMPEG:
            compatible.append((version, candidate.resolve()))
    if compatible:
        return max(compatible, key=lambda item: item[0])[1]
    version = _tool_version(current)
    version_label = ".".join(str(part) for part in version) if version else "unknown"
    raise RuntimeError(
        "This book has more than 255 chapters, but the available FFmpeg "
        f"build ({version_label}) cannot write the required QuickTime chapter track. "
        "Choose FFmpeg 5.0 or newer from Tools > Choose FFmpeg."
    )


def target_channel_count(
    chapters: Sequence[Chapter],
    channel_mode: str,
    *,
    ffmpeg: Path | None = None,
    auto_channel_count: int | None = None,
    should_cancel: Callable[[], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    if channel_mode == "Force mono":
        return 1
    if channel_mode == "Force stereo":
        return 2
    if channel_mode == "Auto":
        if auto_channel_count in {1, 2}:
            return auto_channel_count
        candidates = [chapter for chapter in chapters if chapter.channels != 1]
        if not candidates:
            return 1
        if ffmpeg is None:
            return 2
        for index, chapter in enumerate(candidates, start=1):
            if should_cancel:
                should_cancel()
            if progress:
                progress(index - 1, len(candidates))
            if chapter.channels and chapter.channels > 2:
                return 2
            stereo = detect_meaningful_stereo(
                chapter.path,
                ffmpeg,
                should_cancel=should_cancel,
            )
            if stereo is None or stereo:
                return 2
        if progress:
            progress(len(candidates), len(candidates))
        return 1
    # Keep the old mode readable for projects created before Auto existed.
    known_channels = [chapter.channels for chapter in chapters if chapter.channels]
    if known_channels and all(channels == 1 for channels in known_channels):
        return 1
    return 2


def detect_meaningful_stereo(
    source: Path,
    ffmpeg: Path,
    *,
    should_cancel: Callable[[], None] | None = None,
) -> bool | None:
    """Return whether a short decoded sample contains meaningful stereo.

    ``None`` means the sample could not be analyzed. Callers should treat that
    as stereo so Auto remains conservative when a source or decoder is faulty.
    """

    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-t",
        str(AUTO_STEREO_SAMPLE_SECONDS),
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "2",
        "-ar",
        str(AUTO_STEREO_SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
    ]
    if should_cancel:
        should_cancel()
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=AUTO_STEREO_SAMPLE_SECONDS + 10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if should_cancel:
        should_cancel()
    if result.returncode != 0:
        return None

    raw = result.stdout
    frame_bytes = 4
    if len(raw) < frame_bytes:
        return None
    samples = array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % frame_bytes])
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) < 2:
        return None

    total_energy = 0.0
    difference_energy = 0.0
    for left, right in zip(samples[0::2], samples[1::2]):
        total_energy += float(left * left + right * right)
        difference = left - right
        difference_energy += float(difference * difference)
    if total_energy <= 0:
        return False

    normalized_difference = math.sqrt(difference_energy / (2 * total_energy))
    return normalized_difference >= AUTO_STEREO_DIFFERENCE_THRESHOLD


def target_sample_rate(chapters: Sequence[Chapter]) -> int:
    known_rates = [chapter.sample_rate for chapter in chapters if chapter.sample_rate]
    if not known_rates:
        return 44100
    highest_rate = min(max(known_rates), 48000)
    for standard_rate in (22050, 24000, 32000, 44100, 48000):
        if highest_rate <= standard_rate:
            return standard_rate
    return 48000


def build_normalize_command(
    ffmpeg: Path,
    source: Path,
    destination: Path,
    bitrate: int,
    channels: int,
    sample_rate: int = 44100,
) -> list[str]:
    return [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        "-vn",
        "-sn",
        "-dn",
        "-c:a",
        "aac",
        "-b:a",
        f"{bitrate}k",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-nostats",
        "-progress",
        "pipe:1",
        str(destination),
    ]


def build_mux_command(
    ffmpeg: Path,
    concat_file: Path,
    metadata_file: Path,
    destination: Path,
    cover: Path | None,
    *,
    use_quicktime_chapters: bool = False,
) -> list[str]:
    command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
    ]
    if cover:
        command += ["-i", str(cover)]
    command += ["-i", str(metadata_file), "-map", "0:a:0"]
    if cover:
        command += ["-map", "1:v:0"]
    metadata_input = "2" if cover else "1"
    command += [
        "-map_metadata",
        metadata_input,
        "-map_chapters",
        metadata_input,
        "-c:a",
        "copy",
    ]
    if cover:
        command += [
            "-c:v",
            "mjpeg",
            "-disposition:v:0",
            "attached_pic",
            "-metadata:s:v:0",
            "title=Cover",
            "-metadata:s:v:0",
            "comment=Cover (front)",
        ]
    command += [
        "-movflags",
        "+faststart+disable_chpl" if use_quicktime_chapters else "+faststart",
        "-nostats",
        "-progress",
        "pipe:1",
        str(destination),
    ]
    return command


def write_metadata_file(
    destination: Path,
    chapters: Sequence[Chapter],
    durations: Sequence[float],
    metadata: Mapping[str, str],
) -> None:
    lines = [";FFMETADATA1"]
    for key, value in metadata.items():
        if value:
            lines.append(f"{key}={metadata_value(value)}")

    elapsed = 0.0
    previous_end = 0
    for chapter, duration in zip(chapters, durations, strict=True):
        start = previous_end
        elapsed += max(0.001, duration)
        end = max(start + 1, round(elapsed * 1000))
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start}",
                f"END={end}",
                f"title={metadata_value(chapter.title)}",
            ]
        )
        previous_end = end
    destination.write_text("\n".join(lines), encoding="utf-8")


def validate_output(
    output: Path,
    expected_duration: float,
    expected_chapters: int,
    ffprobe: Path | None,
    expect_cover: bool,
    expected_titles: Sequence[str] | None = None,
) -> None:
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("FFmpeg finished but the output file was empty.")

    tolerance = max(0.5, expected_duration * 0.01)
    if ffprobe:
        check = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-show_chapters",
                "-of",
                "json",
                str(output),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if check.returncode != 0:
            raise RuntimeError(f"Output validation failed:\n{check.stderr[-2000:]}")
        try:
            report = json.loads(check.stdout)
            actual_duration = float(report.get("format", {}).get("duration", 0))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Output validation returned an invalid report: {error}") from error

        chapters = report.get("chapters", [])
        streams = report.get("streams", [])
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if not audio_streams:
            raise RuntimeError("Output validation failed: no audio stream was found.")
        if len(chapters) != expected_chapters:
            raise RuntimeError(
                "Output validation failed: "
                f"expected {expected_chapters} chapters, found {len(chapters)}."
            )
        previous_end = 0.0
        for index, chapter in enumerate(chapters, start=1):
            try:
                start = float(chapter["start_time"])
                end = float(chapter["end_time"])
            except (KeyError, TypeError, ValueError) as error:
                raise RuntimeError(
                    f"Output validation failed: chapter {index} has invalid boundaries."
                ) from error
            if end <= start:
                raise RuntimeError(
                    f"Output validation failed: chapter {index} has an invalid duration."
                )
            if abs(start - previous_end) > 0.1:
                raise RuntimeError(
                    f"Output validation failed: a gap or overlap starts at chapter {index}."
                )
            previous_end = end
        if chapters and abs(previous_end - expected_duration) > tolerance:
            raise RuntimeError(
                "Output validation failed: chapter boundaries do not cover the full audiobook."
            )
        if expected_titles is not None:
            actual_titles = [
                {
                    str(key).casefold(): str(value)
                    for key, value in chapter.get("tags", {}).items()
                }.get("title", "")
                for chapter in chapters
            ]
            if actual_titles != list(expected_titles):
                raise RuntimeError("Output validation failed: chapter titles were not preserved.")
        if expect_cover:
            cover_streams = [
                stream
                for stream in streams
                if stream.get("codec_type") == "video"
                and stream.get("disposition", {}).get("attached_pic") == 1
            ]
            if not cover_streams:
                raise RuntimeError("Output validation failed: the cover image was not embedded.")
    else:
        try:
            audio = File(output)
            actual_duration = float(audio.info.length) if audio and audio.info else 0.0
        except Exception as error:
            raise RuntimeError(f"Could not validate the output duration: {error}") from error
        chapters = getattr(audio, "chapters", None)
        if chapters is None or len(chapters) != expected_chapters:
            actual_chapters = len(chapters) if chapters is not None else 0
            raise RuntimeError(
                "Output validation failed: "
                f"expected {expected_chapters} chapters, found {actual_chapters}."
            )
        chapter_starts = [float(chapter.start) for chapter in chapters]
        if chapter_starts and (
            abs(chapter_starts[0]) > 0.1
            or any(
                later <= earlier
                for earlier, later in zip(chapter_starts, chapter_starts[1:])
            )
        ):
            raise RuntimeError("Output validation failed: chapter starts are invalid.")
        if expect_cover and not (getattr(audio, "tags", None) or {}).get("covr"):
            raise RuntimeError("Output validation failed: the cover image was not embedded.")
        if expected_titles is not None:
            actual_titles = [str(chapter.title) for chapter in chapters]
            if actual_titles != list(expected_titles):
                raise RuntimeError("Output validation failed: chapter titles were not preserved.")

    if actual_duration <= 0:
        raise RuntimeError("Output validation failed: the audiobook has no readable duration.")
    if abs(actual_duration - expected_duration) > tolerance:
        raise RuntimeError(
            "Output validation failed: "
            f"expected about {format_time(expected_duration)}, "
            f"but found {format_time(actual_duration)} "
            f"({actual_duration:.2f}s instead of {expected_duration:.2f}s)."
        )


class ExportEngine:
    def __init__(
        self,
        chapters: Sequence[Chapter],
        output: Path,
        metadata: Mapping[str, str],
        cover: Path | None,
        bitrate: int,
        channel_mode: str,
        ffmpeg_path: str | None,
        ffprobe_path: str | None,
        progress: ProgressCallback | None = None,
        channel_mode_resolved: ChannelModeResolvedCallback | None = None,
        auto_channel_count: int | None = None,
    ) -> None:
        self.chapters = tuple(chapters)
        self.output = output
        self.metadata = dict(metadata)
        self.cover = cover
        self.bitrate = bitrate
        self.channel_mode = channel_mode
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.progress = progress or (lambda _value, _message: None)
        self.channel_mode_resolved = channel_mode_resolved
        self.auto_channel_count = auto_channel_count
        self._cancel_event = threading.Event()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def cancel(self) -> None:
        self._cancel_event.set()
        with self._process_lock:
            process = self._process
        if process and process.poll() is None:
            process.terminate()

    def run(self) -> Path:
        self._validate_inputs()
        ffmpeg = discover_tool("ffmpeg", self.ffmpeg_path)
        if not ffmpeg:
            raise RuntimeError(
                "FFmpeg was not found. Choose it from Tools > Choose FFmpeg, "
                "install it on PATH, or place it beside the application."
            )
        use_quicktime_chapters = len(self.chapters) > 255
        if use_quicktime_chapters:
            ffmpeg = _chapter_safe_ffmpeg(ffmpeg, self.ffmpeg_path)
        ffprobe = discover_tool(
            "ffprobe",
            self.ffprobe_path,
            sibling_directories=(ffmpeg.parent,),
        )

        self.output.parent.mkdir(parents=True, exist_ok=True)
        total_source_duration = sum(chapter.duration for chapter in self.chapters)
        total_label = format_time(total_source_duration)
        self.progress(2, "Preparing export")
        channels = target_channel_count(
            self.chapters,
            self.channel_mode,
            ffmpeg=ffmpeg,
            auto_channel_count=self.auto_channel_count,
            should_cancel=self._raise_if_cancelled,
            progress=lambda completed, total: self.progress(
                2 + int(2 * completed / total) if total else 2,
                "Analyzing channel content",
            ),
        )
        if self.channel_mode == "Auto" and self.channel_mode_resolved:
            self.channel_mode_resolved(channels)
        sample_rate = target_sample_rate(self.chapters)

        with tempfile.TemporaryDirectory(
            prefix=".audiobook-forge-", dir=self.output.parent
        ) as temp_dir:
            temp = Path(temp_dir)
            segment_paths: list[Path] = []
            encoded_durations: list[float] = []
            processed_source_duration = 0.0

            for index, chapter in enumerate(self.chapters):
                self._raise_if_cancelled()
                segment = temp / f"chapter-{index + 1:05d}.m4a"
                chapter_start = processed_source_duration
                chapter_span = 83 * chapter.duration / total_source_duration

                def chapter_progress(elapsed: float, *, start: float = chapter_start, span: float = chapter_span) -> None:
                    local_ratio = min(1.0, elapsed / chapter.duration) if chapter.duration else 1.0
                    overall_elapsed = min(total_source_duration, start + min(elapsed, chapter.duration))
                    self.progress(
                        min(88, 5 + int(83 * start / total_source_duration + span * local_ratio)),
                        f"Processed audio: {format_time(overall_elapsed)} / {total_label}",
                    )

                self.progress(
                    5 + int(83 * chapter_start / total_source_duration),
                    f"Encoding chapter {index + 1} of {len(self.chapters)}",
                )
                self._run_process(
                    build_normalize_command(
                        ffmpeg,
                        chapter.path,
                        segment,
                        self.bitrate,
                        channels,
                        sample_rate,
                    ),
                    chapter_progress,
                )
                segment_duration = self._media_duration(segment)
                segment_paths.append(segment)
                encoded_durations.append(segment_duration)
                processed_source_duration += chapter.duration

            self._raise_if_cancelled()
            concat_file = temp / "inputs.txt"
            concat_file.write_text(
                "\n".join(f"file '{concat_path(path)}'" for path in segment_paths),
                encoding="utf-8",
            )
            metadata_file = temp / "chapters.txt"
            write_metadata_file(
                metadata_file, self.chapters, encoded_durations, self.metadata
            )
            normalized_cover = (
                normalize_cover(self.cover, temp / "cover.jpg") if self.cover else None
            )
            staged_output = temp / "audiobook.m4b"
            self.progress(90, "Assembling audiobook")
            self._run_process(
                build_mux_command(
                    ffmpeg,
                    concat_file,
                    metadata_file,
                    staged_output,
                    normalized_cover,
                    use_quicktime_chapters=use_quicktime_chapters,
                )
            )

            self._raise_if_cancelled()
            expected_duration = sum(encoded_durations)
            self.progress(97, "Validating audiobook")
            validate_output(
                staged_output,
                expected_duration,
                len(self.chapters),
                ffprobe,
                normalized_cover is not None,
                [chapter.title for chapter in self.chapters],
            )
            self._raise_if_cancelled()
            os.replace(staged_output, self.output)

        self.progress(100, "Audiobook ready")
        return self.output

    def _validate_inputs(self) -> None:
        if not self.chapters:
            raise ValueError("At least one chapter is required.")
        missing = [str(chapter.path) for chapter in self.chapters if not chapter.path.is_file()]
        if missing:
            preview = "\n".join(missing[:5])
            suffix = f"\n…and {len(missing) - 5} more" if len(missing) > 5 else ""
            raise ValueError(f"Source audio files are missing:\n{preview}{suffix}")
        resolved_output = self.output.resolve()
        if any(chapter.path.resolve() == resolved_output for chapter in self.chapters):
            raise ValueError("The output file cannot replace one of the source audio files.")
        if self.cover and not self.cover.is_file():
            raise ValueError(f"Cover image was not found: {self.cover}")
        if not self.output.parent.exists():
            raise ValueError(f"Output folder does not exist: {self.output.parent}")
        if self.bitrate not in {64, 96, 128, 160}:
            raise ValueError(f"Unsupported bitrate: {self.bitrate} kbps")
        if self.channel_mode not in {"Auto", "Preserve source", "Force mono", "Force stereo"}:
            raise ValueError(f"Unsupported channel mode: {self.channel_mode}")

    def _run_process(
        self,
        command: Sequence[str],
        progress: Callable[[float], None] | None = None,
    ) -> None:
        self._raise_if_cancelled()
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        with self._process_lock:
            self._process = process
        diagnostics: list[str] = []
        try:
            output_stream = process.stdout
            if output_stream:
                for line in output_stream:
                    text = line.rstrip()
                    diagnostics.append(text)
                    del diagnostics[:-60]
                    if self._cancel_event.is_set():
                        process.terminate()
                        break
                    if progress and text.startswith(("out_time_us=", "out_time_ms=")):
                        try:
                            progress(int(text.split("=", 1)[1]) / 1_000_000)
                        except ValueError:
                            pass
            exit_code = process.wait()
        except BaseException:
            if process.poll() is None:
                process.terminate()
                process.wait()
            raise
        finally:
            if process.stdout:
                process.stdout.close()
            with self._process_lock:
                if self._process is process:
                    self._process = None

        self._raise_if_cancelled()
        if exit_code != 0:
            detail = "\n".join(
                line
                for line in diagnostics
                if line and not line.startswith(("frame=", "out_", "progress="))
            )
            raise RuntimeError(
                f"FFmpeg failed with exit code {exit_code}.\n\n{detail[-4000:]}"
            )

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise ExportCancelled

    @staticmethod
    def _media_duration(path: Path) -> float:
        try:
            audio = File(path)
            duration = float(audio.info.length) if audio and audio.info else 0.0
        except Exception as error:
            raise RuntimeError(f"Could not read encoded chapter {path.name}: {error}") from error
        if duration <= 0:
            raise RuntimeError(f"Encoded chapter {path.name} has no readable duration.")
        return duration


class BatchExportEngine:
    """Export books one at a time, committing each validated output immediately."""

    def __init__(
        self,
        books: Sequence[Book],
        destination_root: Path,
        ffmpeg_path: str | None,
        ffprobe_path: str | None,
        progress: ProgressCallback | None = None,
        book_finished: BookFinishedCallback | None = None,
        channel_mode_resolved: Callable[[int, Book, int], None] | None = None,
        book_progress: BookProgressCallback | None = None,
        output_template: str | None = None,
    ) -> None:
        self.books = tuple(books)
        self.destination_root = destination_root
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.progress = progress or (lambda _value, _message: None)
        self.book_finished = book_finished or (lambda _index, _book, _output: None)
        self.channel_mode_resolved = channel_mode_resolved
        self.book_progress = book_progress or (lambda _index, _book, _value, _message: None)
        self.output_template = output_template
        self.completed: list[Path] = []
        self._cancel_event = threading.Event()
        self._current_engine: ExportEngine | None = None

    def cancel(self) -> None:
        self._cancel_event.set()
        if self._current_engine:
            self._current_engine.cancel()

    def run(self) -> list[Path]:
        if not self.books:
            raise ValueError("At least one book is required.")
        self.destination_root = self.destination_root.expanduser().resolve()
        if not self.destination_root.exists():
            raise ValueError(f"Destination folder does not exist: {self.destination_root}")
        if not self.destination_root.is_dir():
            raise ValueError(f"Destination is not a folder: {self.destination_root}")

        total_books = len(self.books)
        for index, book in enumerate(self.books):
            self._raise_if_cancelled()
            output = book_output_path(
                self.destination_root,
                book.metadata,
                self.output_template,
                book.source_name,
            )
            created_directories = self._ensure_output_parent(output.parent)

            def update_book_progress(value: int, message: str, *, book_index: int = index) -> None:
                self.book_progress(book_index, book, value, message)
                overall = int(((book_index + min(100, max(0, value)) / 100) / total_books) * 100)
                self.progress(overall, f"Book {book_index + 1} of {total_books}: {message}")

            engine = ExportEngine(
                book.chapters,
                output,
                metadata_for_book(book.metadata),
                book.cover,
                book.bitrate,
                book.channel_mode,
                self.ffmpeg_path,
                self.ffprobe_path,
                update_book_progress,
                channel_mode_resolved=(
                    lambda channels, book_index=index, current_book=book: self.channel_mode_resolved(
                        book_index, current_book, channels
                    )
                    if self.channel_mode_resolved
                    else None
                ),
                auto_channel_count=book.auto_channel_count,
            )
            self._current_engine = engine
            try:
                completed_output = engine.run()
            except BaseException:
                self._remove_empty_directories(created_directories)
                raise
            finally:
                self._current_engine = None

            self.completed.append(completed_output)
            self.book_finished(index, book, completed_output)
            self.progress(
                int(((index + 1) / total_books) * 100),
                f"Saved book {index + 1} of {total_books}: {completed_output.name}",
            )
        return list(self.completed)

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise ExportCancelled

    @staticmethod
    def _ensure_output_parent(path: Path) -> list[Path]:
        missing: list[Path] = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        path.mkdir(parents=True, exist_ok=True)
        return missing

    @staticmethod
    def _remove_empty_directories(directories: Sequence[Path]) -> None:
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                pass
