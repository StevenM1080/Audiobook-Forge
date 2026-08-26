from __future__ import annotations

import re
from pathlib import Path

from mutagen import File

from .models import Chapter, SUPPORTED_AUDIO_EXTENSIONS


def probe_audio(path: Path) -> Chapter:
    try:
        audio = File(path, easy=True)
        if audio is None or audio.info is None or not getattr(audio.info, "length", None):
            raise ValueError("the file has no readable audio duration")
        tags = audio.tags or {}
        title = _first_tag(tags, "title") or path.stem
        track_number = _track_number(_first_tag(tags, "tracknumber"))
        channels = _positive_int(getattr(audio.info, "channels", None))
        sample_rate = _positive_int(getattr(audio.info, "sample_rate", None))
        return Chapter(
            path=path.resolve(),
            title=title,
            duration=float(audio.info.length),
            track_number=track_number,
            channels=channels,
            sample_rate=sample_rate,
        )
    except Exception as error:
        raise ValueError(f"Could not read {path}: {error}") from error


def common_tags(chapters: list[Chapter]) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    for chapter in chapters:
        try:
            audio = File(chapter.path, easy=True)
        except Exception:
            return {}
        for key in ("album", "albumartist", "artist", "composer", "date", "genre"):
            value = _first_tag(audio.tags if audio else None, key)
            if value:
                values.setdefault(key, []).append(value)
    return {key: entries[0] for key, entries in values.items() if len(entries) == len(chapters) and len(set(entries)) == 1}


def supported_audio_files(folder: Path) -> list[Path]:
    return [path for path in folder.iterdir() if path.is_file() and path.suffix.casefold() in SUPPORTED_AUDIO_EXTENSIONS]


def _first_tag(tags: object, key: str) -> str:
    value = tags.get(key) if hasattr(tags, "get") else None
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value) if value else ""


def _track_number(value: str) -> int | None:
    match = re.match(r"\s*(\d+)", value)
    return int(match.group(1)) if match else None


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
