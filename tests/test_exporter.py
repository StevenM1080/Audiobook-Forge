from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiobook_forge import exporter
from audiobook_forge.exporter import (
    BatchExportEngine,
    ExportCancelled,
    ExportEngine,
    build_mux_command,
    build_normalize_command,
    detect_meaningful_stereo,
    discover_tool,
    target_channel_count,
    target_sample_rate,
    validate_output,
    write_metadata_file,
)
from audiobook_forge.media import probe_audio
from audiobook_forge.models import Book, BookMetadata, Chapter
from mutagen.mp4 import MP4


def test_bundled_tool_is_discovered_before_other_candidates(tmp_path: Path) -> None:
    executable_name = "ffmpeg.exe" if exporter.os.name == "nt" else "ffmpeg"
    bundled = tmp_path / executable_name
    bundled.write_bytes(b"tool")
    configured = tmp_path / f"configured-{executable_name}"
    configured.write_bytes(b"tool")

    assert discover_tool(
        "ffmpeg", str(configured), app_path=tmp_path / "AudiobookForge.exe"
    ) == bundled.resolve()


def test_missing_configured_tool_falls_back_to_a_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable_name = "ffprobe.exe" if exporter.os.name == "nt" else "ffprobe"
    sibling = tmp_path / "tools" / executable_name
    sibling.parent.mkdir()
    sibling.write_bytes(b"tool")
    monkeypatch.setattr(exporter.shutil, "which", lambda _name: None)

    assert discover_tool(
        "ffprobe",
        str(tmp_path / "missing" / executable_name),
        app_path=tmp_path / "app" / "AudiobookForge.exe",
        sibling_directories=(sibling.parent,),
    ) == sibling.resolve()


def test_chapter_safe_ffmpeg_selects_a_newer_available_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_ffmpeg = tmp_path / "old-ffmpeg.exe"
    new_ffmpeg = tmp_path / "new-ffmpeg.exe"
    old_ffmpeg.write_bytes(b"tool")
    new_ffmpeg.write_bytes(b"tool")
    versions = {old_ffmpeg: (4, 4, 0), new_ffmpeg: (7, 1, 4)}
    monkeypatch.setattr(
        exporter,
        "_tool_candidates",
        lambda *_args, **_kwargs: [old_ffmpeg, new_ffmpeg],
    )
    monkeypatch.setattr(exporter, "_tool_version", lambda path: versions[path])

    assert exporter._chapter_safe_ffmpeg(old_ffmpeg, None) == new_ffmpeg.resolve()


def test_normalize_command_makes_streams_compatible(tmp_path: Path) -> None:
    command = build_normalize_command(
        Path("ffmpeg"), Path("source.wav"), tmp_path / "chapter.m4a", 128, 2
    )
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-ar") + 1] == "44100"
    assert command[command.index("-ac") + 1] == "2"
    assert command[command.index("-b:a") + 1] == "128k"


def test_mux_command_copies_normalized_audio_and_embeds_cover(tmp_path: Path) -> None:
    command = build_mux_command(
        Path("ffmpeg"),
        tmp_path / "inputs.txt",
        tmp_path / "metadata.txt",
        tmp_path / "book.m4b",
        tmp_path / "cover.jpg",
    )
    assert command[command.index("-c:a") + 1] == "copy"
    assert "attached_pic" in command
    assert command[command.index("-map_chapters") + 1] == "2"
    assert "-1" not in command


def test_mux_command_uses_quicktime_chapters_when_requested(tmp_path: Path) -> None:
    command = build_mux_command(
        Path("ffmpeg"),
        tmp_path / "inputs.txt",
        tmp_path / "metadata.txt",
        tmp_path / "book.m4b",
        None,
        use_quicktime_chapters=True,
    )

    assert command[command.index("-movflags") + 1] == "+faststart+disable_chpl"


def test_metadata_boundaries_use_cumulative_rounding(tmp_path: Path) -> None:
    destination = tmp_path / "metadata.txt"
    chapters = [
        Chapter(Path("a.mp3"), "A", 0.0),
        Chapter(Path("b.mp3"), "B", 0.0),
        Chapter(Path("c.mp3"), "C", 0.0),
    ]
    write_metadata_file(destination, chapters, [0.3334, 0.3334, 0.3334], {})
    text = destination.read_text(encoding="utf-8")
    assert "START=0\nEND=333" in text
    assert "START=333\nEND=667" in text
    assert "START=667\nEND=1000" in text


def test_output_validation_rejects_truncated_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MediaInfo:
        length = 1.0

    class Media:
        info = MediaInfo()
        chapters = [SimpleNamespace(start=0.0), SimpleNamespace(start=1.0)]
        tags = {}

    output = tmp_path / "book.m4b"
    output.write_bytes(b"not-empty")
    monkeypatch.setattr(exporter, "File", lambda _path: Media())

    with pytest.raises(RuntimeError, match="2.00s"):
        validate_output(output, 2.0, 2, None, False)


def test_ffprobe_validation_rejects_chapter_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "book.m4b"
    output.write_bytes(b"not-empty")
    ffprobe = tmp_path / "ffprobe.exe"
    ffprobe.write_bytes(b"tool")
    report = {
        "format": {"duration": "2.0"},
        "streams": [{"codec_type": "audio"}],
        "chapters": [
            {"start_time": "0.0", "end_time": "1.0"},
            {"start_time": "1.25", "end_time": "2.0"},
        ],
    }

    class Result:
        returncode = 0
        stdout = json.dumps(report)
        stderr = ""

    monkeypatch.setattr(exporter.subprocess, "run", lambda *_args, **_kwargs: Result())

    with pytest.raises(RuntimeError, match="gap or overlap"):
        validate_output(output, 2.0, 2, ffprobe, False)


def test_fallback_validation_rejects_missing_chapter_titles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = SimpleNamespace(
        info=SimpleNamespace(length=2.0),
        chapters=[
            SimpleNamespace(start=0.0, title=""),
            SimpleNamespace(start=1.0, title=""),
        ],
        tags={},
    )
    output = tmp_path / "book.m4b"
    output.write_bytes(b"not-empty")
    monkeypatch.setattr(exporter, "File", lambda _path: media)

    with pytest.raises(RuntimeError, match="titles"):
        validate_output(output, 2.0, 2, None, False, ["One", "Two"])


def test_preflight_failure_preserves_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source")
    output = tmp_path / "existing.m4b"
    output.write_bytes(b"original")
    engine = ExportEngine(
        [Chapter(source, "Chapter", 1.0)],
        output,
        {"title": "Book"},
        tmp_path / "missing-cover.jpg",
        96,
        "Preserve source",
        None,
        None,
    )

    with pytest.raises(ValueError, match="Cover image was not found"):
        engine.run()
    assert output.read_bytes() == b"original"


def test_export_cannot_replace_a_source_file(tmp_path: Path) -> None:
    source = tmp_path / "source.m4b"
    source.write_bytes(b"source")
    engine = ExportEngine(
        [Chapter(source, "Chapter", 1.0)],
        source,
        {"title": "Book"},
        None,
        96,
        "Preserve source",
        None,
        None,
    )

    with pytest.raises(ValueError, match="cannot replace"):
        engine.run()
    assert source.read_bytes() == b"source"


def test_cancelled_export_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp3"
    source.write_bytes(b"source")
    output = tmp_path / "existing.m4b"
    output.write_bytes(b"original")
    engine = ExportEngine(
        [Chapter(source, "Chapter", 1.0)],
        output,
        {"title": "Book"},
        None,
        96,
        "Preserve source",
        None,
        None,
    )
    monkeypatch.setattr(exporter, "discover_tool", lambda *_args, **_kwargs: Path("ffmpeg"))

    engine.cancel()
    with pytest.raises(ExportCancelled):
        engine.run()
    assert output.read_bytes() == b"original"


def test_validation_failure_preserves_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = discover_tool("ffmpeg", app_path=tmp_path / "app.pyw")
    if not ffmpeg:
        pytest.skip("FFmpeg is not available for the staged-output safety test")
    source = tmp_path / "source.mp3"
    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=0.1",
            "-c:a",
            "libmp3lame",
            str(source),
        ],
        check=True,
    )
    output = tmp_path / "existing.m4b"
    output.write_bytes(b"original")

    def reject_output(*_args, **_kwargs) -> None:
        raise RuntimeError("invalid output")

    monkeypatch.setattr(exporter, "validate_output", reject_output)
    engine = ExportEngine(
        [probe_audio(source)],
        output,
        {"title": "Book"},
        None,
        96,
        "Preserve source",
        str(ffmpeg),
        None,
    )

    with pytest.raises(RuntimeError, match="invalid output"):
        engine.run()
    assert output.read_bytes() == b"original"


def test_preserve_source_selects_one_consistent_channel_layout() -> None:
    mono = Chapter(Path("mono.mp3"), "Mono", 1.0, channels=1)
    stereo = Chapter(Path("stereo.mp3"), "Stereo", 1.0, channels=2)
    assert target_channel_count([mono], "Preserve source") == 1
    assert target_channel_count([mono, stereo], "Preserve source") == 2


def test_auto_detects_centered_and_meaningful_stereo_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centered = b"".join(struct.pack("<hh", 10000, 10000) for _ in range(256))
    stereo = b"".join(struct.pack("<hh", 10000, -10000) for _ in range(256))
    samples = iter([centered, stereo])

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=next(samples), stderr=b"")

    monkeypatch.setattr(exporter.subprocess, "run", fake_run)
    source = tmp_path / "sample.mp3"

    assert detect_meaningful_stereo(source, Path("ffmpeg")) is False
    assert detect_meaningful_stereo(source, Path("ffmpeg")) is True


def test_auto_channel_mode_uses_content_analysis_for_stereo_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    centered = Chapter(Path("centered.mp3"), "Centered", 1.0, channels=2)
    meaningful = Chapter(Path("meaningful.mp3"), "Meaningful", 1.0, channels=2)
    monkeypatch.setattr(
        exporter,
        "detect_meaningful_stereo",
        lambda source, _ffmpeg, **_kwargs: source.name == "meaningful.mp3",
    )

    assert target_channel_count([centered], "Auto", ffmpeg=Path("ffmpeg")) == 1
    assert target_channel_count([centered, meaningful], "Auto", ffmpeg=Path("ffmpeg")) == 2


def test_cached_auto_channel_count_skips_content_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chapter = Chapter(Path("chapter.mp3"), "Chapter", 1.0, channels=2)

    def should_not_analyze(*_args, **_kwargs):
        raise AssertionError("Auto analysis should not run for a cached result")

    monkeypatch.setattr(exporter, "detect_meaningful_stereo", should_not_analyze)

    assert (
        target_channel_count(
            [chapter],
            "Auto",
            ffmpeg=Path("ffmpeg"),
            auto_channel_count=1,
        )
        == 1
    )


def test_sample_rate_is_preserved_or_normalized_to_a_standard_rate() -> None:
    low = Chapter(Path("low.mp3"), "Low", 1.0, sample_rate=22050)
    cd = Chapter(Path("cd.mp3"), "CD", 1.0, sample_rate=44100)
    high = Chapter(Path("high.wav"), "High", 1.0, sample_rate=96000)
    assert target_sample_rate([low]) == 22050
    assert target_sample_rate([low, cd]) == 44100
    assert target_sample_rate([high]) == 48000


def test_mixed_format_export_keeps_all_audio(tmp_path: Path) -> None:
    ffmpeg = discover_tool("ffmpeg", app_path=tmp_path / "app.pyw")
    if not ffmpeg:
        pytest.skip("FFmpeg is not available for the end-to-end export test")

    mp3 = tmp_path / "01.mp3"
    wav = tmp_path / "02.wav"
    cover = tmp_path / "cover.png"
    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            str(mp3),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:duration=1",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ],
        check=True,
    )
    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x24",
            "-frames:v",
            "1",
            str(cover),
        ],
        check=True,
    )
    output = tmp_path / "book.m4b"
    engine = ExportEngine(
        [probe_audio(mp3), probe_audio(wav)],
        output,
        {
            "title": "Book",
            "artist": "Author",
            "album_artist": "Author",
            "album": "Book",
        },
        cover,
        96,
        "Preserve source",
        str(ffmpeg),
        None,
    )

    engine.run()
    rendered = exporter.File(output)
    assert rendered is not None and rendered.info is not None
    assert 1.8 < float(rendered.info.length) < 2.3
    mp4 = MP4(output)
    assert mp4.chapters is not None and len(mp4.chapters) == 2
    assert [chapter.title for chapter in mp4.chapters] == ["01", "02"]
    assert float(mp4.chapters[0].start) == pytest.approx(0.0, abs=0.01)
    assert float(mp4.chapters[1].start) == pytest.approx(1.0, abs=0.15)
    assert len(mp4.tags.get("covr", [])) == 1
    assert mp4.tags.get("\xa9nam") == ["Book"]
    assert mp4.tags.get("\xa9ART") == ["Author"]
    assert mp4.tags.get("aART") == ["Author"]
    assert mp4.tags.get("\xa9alb") == ["Book"]


def test_batch_export_commits_each_book_before_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "output"
    destination.mkdir()
    first = Book(
        chapters=[Chapter(tmp_path / "one.mp3", "One", 1.0)],
        metadata=BookMetadata(title="First", author="Author"),
    )
    second = Book(
        chapters=[Chapter(tmp_path / "two.mp3", "Two", 1.0)],
        metadata=BookMetadata(title="Second", author="Author"),
    )
    seen_before_second: list[bool] = []

    class FakeEngine:
        calls = 0

        def __init__(self, chapters, output, *_args, **_kwargs) -> None:
            self.output = output
            self.chapters = chapters

        def run(self) -> Path:
            FakeEngine.calls += 1
            if FakeEngine.calls == 2:
                seen_before_second.append((destination / "Author" / "First" / "First.m4b").is_file())
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_bytes(b"completed")
            return self.output

        def cancel(self) -> None:
            pass

    monkeypatch.setattr(exporter, "ExportEngine", FakeEngine)

    outputs = BatchExportEngine([first, second], destination, None, None).run()

    assert seen_before_second == [True]
    assert outputs == [
        destination / "Author" / "First" / "First.m4b",
        destination / "Author" / "Second" / "Second.m4b",
    ]


@pytest.mark.parametrize("exception", [ExportCancelled, RuntimeError])
def test_batch_export_stops_after_current_book_and_preserves_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exception: type[Exception]
) -> None:
    destination = tmp_path / "output"
    destination.mkdir()
    books = [
        Book(
            chapters=[Chapter(tmp_path / f"{index}.mp3", str(index), 1.0)],
            metadata=BookMetadata(title=f"Book {index}", author="Author"),
        )
        for index in range(1, 4)
    ]

    class FakeEngine:
        calls = 0

        def __init__(self, chapters, output, *_args, **_kwargs) -> None:
            self.output = output

        def run(self) -> Path:
            FakeEngine.calls += 1
            if FakeEngine.calls == 2:
                raise exception("stopped") if exception is RuntimeError else exception()
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_bytes(b"completed")
            return self.output

        def cancel(self) -> None:
            pass

    monkeypatch.setattr(exporter, "ExportEngine", FakeEngine)
    engine = BatchExportEngine(books, destination, None, None)

    with pytest.raises(exception):
        engine.run()

    assert engine.completed == [destination / "Author" / "Book 1" / "Book 1.m4b"]
    assert engine.completed[0].is_file()
    assert not (destination / "Author" / "Book 2").exists()
    assert not (destination / "Author" / "Book 3" / "Book 3.m4b").exists()
