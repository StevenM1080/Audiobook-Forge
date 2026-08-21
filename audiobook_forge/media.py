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
        return Chapter(path=path, title=title, duration=float(audio.info.length), track_number=track_number)
    except Exception as error:
        raise ValueError(f"Could not read {path}: {error}") from error


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
