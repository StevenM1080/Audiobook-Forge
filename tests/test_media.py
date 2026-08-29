from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from audiobook_forge import media
from audiobook_forge.media import common_tags, find_cover, probe_audio, supported_audio_files
from audiobook_forge.models import Chapter


def test_probe_audio_reads_track_and_stream_properties(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "chapter.mp3"
    source.write_bytes(b"audio")
    fake_audio = SimpleNamespace(
        info=SimpleNamespace(length=12.5, channels=2, sample_rate=48000),
        tags={"title": ["Opening"], "tracknumber": ["7/12"]},
    )
    monkeypatch.setattr(media, "File", lambda *_args, **_kwargs: fake_audio)

    chapter = probe_audio(source)

    assert chapter.path == source.resolve()
    assert chapter.title == "Opening"
    assert chapter.track_number == 7
    assert chapter.channels == 2
    assert chapter.sample_rate == 48000


def test_probe_audio_reports_the_unreadable_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "broken.mp3"

    def unreadable(*_args, **_kwargs):
        raise RuntimeError("broken tags")

    monkeypatch.setattr(media, "File", unreadable)

    with pytest.raises(ValueError, match=r"broken\.mp3.*broken tags"):
        probe_audio(source)


def test_folder_discovery_is_supported_and_non_recursive(tmp_path: Path) -> None:
    (tmp_path / "one.MP3").write_bytes(b"audio")
    (tmp_path / "two.flac").write_bytes(b"audio")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "three.mp3").write_bytes(b"audio")

    assert {path.name for path in supported_audio_files(tmp_path)} == {
        "one.MP3",
        "two.flac",
    }


def test_common_tags_falls_back_cleanly_when_a_file_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def moved(*_args, **_kwargs):
        raise OSError("file moved")

    monkeypatch.setattr(media, "File", moved)

    assert common_tags([Chapter(Path("missing.mp3"), "Missing", 1.0)]) == {}


def test_find_cover_prefers_cover_named_image_in_input_folder(tmp_path: Path) -> None:
    (tmp_path / "art.png").write_bytes(b"image")
    cover = tmp_path / "Cover.jpg"
    cover.write_bytes(b"image")

    assert find_cover(tmp_path) == cover.resolve()


def test_find_cover_falls_back_to_an_arbitrarily_named_image(tmp_path: Path) -> None:
    artwork = tmp_path / "My Book Artwork.png"
    artwork.write_bytes(b"image")

    assert find_cover(tmp_path) == artwork.resolve()


def test_find_cover_supports_a_cover_subfolder_and_missing_is_empty(tmp_path: Path) -> None:
    cover_folder = tmp_path / "Cover"
    cover_folder.mkdir()
    cover = cover_folder / "front.webp"
    cover.write_bytes(b"image")

    assert find_cover(tmp_path) == cover.resolve()
    assert find_cover(tmp_path / "missing") is None
