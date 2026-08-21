from __future__ import annotations

import json
from pathlib import Path

from .models import BookMetadata, Chapter


def save_project(path: Path, chapters: list[Chapter], metadata: BookMetadata, cover: Path | None, output: Path | None, bitrate: int, channel_mode: str) -> None:
    payload = {
        "version": 1,
        "chapters": [{"path": str(chapter.path), "title": chapter.title, "duration": chapter.duration, "track_number": chapter.track_number} for chapter in chapters],
        "metadata": metadata.__dict__,
        "cover": str(cover) if cover else "",
        "output": str(output) if output else "",
        "bitrate": bitrate,
        "channel_mode": channel_mode,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_project(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("Unsupported Audiobook Forge project version.")
    return payload
