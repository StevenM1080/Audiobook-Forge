from pathlib import Path

import pytest

from audiobook_forge.models import BookMetadata, Chapter
from audiobook_forge.project_io import load_project, save_project


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
