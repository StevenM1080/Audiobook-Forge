from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import BookMetadata, Chapter


def save_project(path: Path, chapters: list[Chapter], metadata: BookMetadata, cover: Path | None, output: Path | None, bitrate: int, channel_mode: str) -> None:
    if not path.parent.exists():
        raise ValueError(f"Project folder does not exist: {path.parent}")
    payload = {
        "version": 1,
        "chapters": [
            {
                "path": str(chapter.path.resolve()),
                "title": chapter.title,
                "duration": chapter.duration,
                "track_number": chapter.track_number,
                "channels": chapter.channels,
                "sample_rate": chapter.sample_rate,
            }
            for chapter in chapters
        ],
        "metadata": metadata.__dict__,
        "cover": str(cover.resolve()) if cover else "",
        "output": str(output.resolve()) if output else "",
        "bitrate": bitrate,
        "channel_mode": channel_mode,
    }
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(json.dumps(payload, indent=2, ensure_ascii=False))
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def load_project(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The project must contain a JSON object.")
    if type(payload.get("version")) is not int or payload.get("version") != 1:
        raise ValueError("Unsupported Audiobook Forge project version.")
    chapters = payload.get("chapters")
    metadata = payload.get("metadata")
    if not isinstance(chapters, list) or not isinstance(metadata, dict):
        raise ValueError("The project is missing valid chapters or metadata.")
    for index, chapter in enumerate(chapters, start=1):
        if not isinstance(chapter, dict):
            raise ValueError(f"Chapter {index} is not a valid object.")
        if not isinstance(chapter.get("path"), str) or not isinstance(chapter.get("title"), str):
            raise ValueError(f"Chapter {index} is missing a valid path or title.")
        try:
            duration = float(chapter.get("duration"))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Chapter {index} has an invalid duration.") from error
        if duration <= 0:
            raise ValueError(f"Chapter {index} has an invalid duration.")
        for key in ("track_number", "channels", "sample_rate"):
            value = chapter.get(key)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"Chapter {index} has an invalid {key} value.")
    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("The project contains invalid metadata values.")
    for key in ("cover", "output"):
        if not isinstance(payload.get(key, ""), str):
            raise ValueError(f"The project has an invalid {key} path.")
    if payload.get("bitrate", 96) not in {64, 96, 128, 160}:
        raise ValueError("The project has an unsupported bitrate.")
    if payload.get("channel_mode", "Preserve source") not in {
        "Preserve source",
        "Force mono",
        "Force stereo",
    }:
        raise ValueError("The project has an unsupported channel mode.")
    return payload
