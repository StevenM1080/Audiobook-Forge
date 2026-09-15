from pathlib import Path

import pytest

from audiobook_forge.models import Book, BookMetadata, Chapter
from audiobook_forge.project_io import load_project, save_batch_project, save_project


def test_project_round_trip(tmp_path: Path) -> None:
    project = tmp_path / "book.json"
    chapters = [Chapter(Path("Chapter 1.mp3"), "Opening", 12.5, 1)]
    metadata = BookMetadata(title="Book", author="Author", narrator="Narrator")
    save_project(project, chapters, metadata, Path("cover.jpg"), Path("book.m4b"), 96, "Preserve source")
    payload = load_project(project)
    assert payload["chapters"][0]["title"] == "Opening"
    assert Path(payload["chapters"][0]["path"]).is_absolute()
    assert payload["metadata"]["narrator"] == "Narrator"
    assert payload["bitrate"] == 96


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        '{"version": 1, "chapters": {}, "metadata": {}}',
        '{"version": 1, "chapters": [{"path": "a.mp3"}], "metadata": {}}',
        '{"version": 1, "chapters": [{"path": "a.mp3", "title": "A", "duration": 1, "channels": "two"}], "metadata": {}}',
        '{"version": 1, "chapters": [], "metadata": {"title": 123}}',
        '{"version": 99, "chapters": [], "metadata": {}}',
    ],
)
def test_project_loader_rejects_invalid_schemas(tmp_path: Path, payload: str) -> None:
    project = tmp_path / "invalid.json"
    project.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(project)


def test_batch_project_round_trip(tmp_path: Path) -> None:
    project = tmp_path / "batch.json"
    source = tmp_path / "chapter.mp3"
    cover = tmp_path / "cover.jpg"
    books = [
        Book(
            chapters=[Chapter(source, "Opening", 12.5, 1)],
            metadata=BookMetadata(title="Book", author="Author", series="Series"),
            cover=cover,
            bitrate=128,
            channel_mode="Force stereo",
            source_name="Source folder",
            book_id="book-id",
        )
    ]

    save_batch_project(project, books, tmp_path / "output", "{author}/{title}.m4b")
    payload = load_project(project)

    assert payload["version"] == 2
    assert payload["destination_root"] == str((tmp_path / "output").resolve())
    assert payload["output_template"] == "{author}/{title}.m4b"
    assert payload["books"][0]["id"] == "book-id"
    assert payload["books"][0]["metadata"]["series"] == "Series"
    assert payload["books"][0]["bitrate"] == 128
