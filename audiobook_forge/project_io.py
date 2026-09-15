from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import DEFAULT_OUTPUT_TEMPLATE, Book, BookMetadata, Chapter


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
    _write_payload(path, payload)


def save_batch_project(
    path: Path,
    books: list[Book],
    destination_root: Path | None,
    output_template: str = DEFAULT_OUTPUT_TEMPLATE,
) -> None:
    """Persist a version 2 multi-book project."""

    if not path.parent.exists():
        raise ValueError(f"Project folder does not exist: {path.parent}")
    payload = {
        "version": 2,
        "books": [
            {
                "id": book.book_id,
                "source_name": book.source_name,
                "chapters": [_chapter_payload(chapter) for chapter in book.chapters],
                "metadata": book.metadata.__dict__,
                "cover": str(book.cover.resolve()) if book.cover else "",
                "bitrate": book.bitrate,
                "channel_mode": book.channel_mode,
            }
            for book in books
        ],
        "destination_root": str(destination_root.resolve()) if destination_root else "",
        "output_template": output_template,
    }
    _write_payload(path, payload)


def _chapter_payload(chapter: Chapter) -> dict[str, object]:
    return {
        "path": str(chapter.path.resolve()),
        "title": chapter.title,
        "duration": chapter.duration,
        "track_number": chapter.track_number,
        "channels": chapter.channels,
        "sample_rate": chapter.sample_rate,
    }


def _write_payload(path: Path, payload: dict[str, object]) -> None:
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
    if type(payload.get("version")) is not int or payload.get("version") not in {1, 2}:
        raise ValueError("Unsupported Audiobook Forge project version.")

    if payload.get("version") == 2:
        _validate_batch_payload(payload)
        return payload

    _validate_legacy_payload(payload)
    return payload


def _validate_legacy_payload(payload: dict) -> None:
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
    if payload.get("channel_mode", "Auto") not in {
        "Auto",
        "Preserve source",
        "Force mono",
        "Force stereo",
    }:
        raise ValueError("The project has an unsupported channel mode.")


def _validate_batch_payload(payload: dict) -> None:
    books = payload.get("books")
    destination_root = payload.get("destination_root", "")
    output_template = payload.get("output_template", DEFAULT_OUTPUT_TEMPLATE)
    if (
        not isinstance(books, list)
        or not isinstance(destination_root, str)
        or not isinstance(output_template, str)
    ):
        raise ValueError("The project is missing valid books or destination root.")
    for index, book in enumerate(books, start=1):
        if not isinstance(book, dict):
            raise ValueError(f"Book {index} is not a valid object.")
        if not isinstance(book.get("id", ""), str) or not isinstance(book.get("source_name", ""), str):
            raise ValueError(f"Book {index} is missing a valid identifier or source name.")
        chapters = book.get("chapters")
        metadata = book.get("metadata")
        if not isinstance(chapters, list) or not isinstance(metadata, dict):
            raise ValueError(f"Book {index} is missing valid chapters or metadata.")
        _validate_chapters(chapters, f"Book {index}")
        _validate_metadata(metadata, f"Book {index}")
        if not isinstance(book.get("cover", ""), str):
            raise ValueError(f"Book {index} has an invalid cover path.")
        if book.get("bitrate", 96) not in {64, 96, 128, 160}:
            raise ValueError(f"Book {index} has an unsupported bitrate.")
        if book.get("channel_mode", "Auto") not in {
            "Auto",
            "Preserve source",
            "Force mono",
            "Force stereo",
        }:
            raise ValueError(f"Book {index} has an unsupported channel mode.")


def _validate_chapters(chapters: list, label: str) -> None:
    for index, chapter in enumerate(chapters, start=1):
        if not isinstance(chapter, dict):
            raise ValueError(f"{label} chapter {index} is not a valid object.")
        if not isinstance(chapter.get("path"), str) or not isinstance(chapter.get("title"), str):
            raise ValueError(f"{label} chapter {index} is missing a valid path or title.")
        try:
            duration = float(chapter.get("duration"))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} chapter {index} has an invalid duration.") from error
        if duration <= 0:
            raise ValueError(f"{label} chapter {index} has an invalid duration.")
        for key in ("track_number", "channels", "sample_rate"):
            value = chapter.get(key)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{label} chapter {index} has an invalid {key} value.")


def _validate_metadata(metadata: dict, label: str) -> None:
    for key, value in metadata.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"{label} contains invalid metadata values.")
