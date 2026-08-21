from pathlib import Path

from audiobook_forge.models import BookMetadata, Chapter
from audiobook_forge.project_io import load_project, save_project


def test_project_round_trip(tmp_path: Path) -> None:
    project = tmp_path / "book.json"
    chapters = [Chapter(Path("Chapter 1.mp3"), "Opening", 12.5, 1)]
    metadata = BookMetadata(title="Book", author="Author", narrator="Narrator")
    save_project(project, chapters, metadata, Path("cover.jpg"), Path("book.m4b"), 96, "Preserve source")
    payload = load_project(project)
    assert payload["chapters"][0]["title"] == "Opening"
    assert payload["metadata"]["narrator"] == "Narrator"
    assert payload["bitrate"] == 96
