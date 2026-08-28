from pathlib import Path

from audiobook_forge.exporter import metadata_value
from audiobook_forge.models import (
    BookMetadata,
    book_output_path,
    estimate_output_bytes,
    natural_sort_key,
    safe_output_stem,
    split_leading_series_number,
)


def test_natural_sort_key_orders_numbers_numerically() -> None:
    paths = [Path("Chapter 10.mp3"), Path("Chapter 2.mp3"), Path("Chapter 1.mp3")]
    assert [path.name for path in sorted(paths, key=natural_sort_key)] == [
        "Chapter 1.mp3",
        "Chapter 2.mp3",
        "Chapter 10.mp3",
    ]


def test_split_leading_series_number_from_folder_title() -> None:
    assert split_leading_series_number("1 Among The Hidden") == ("1", "Among The Hidden")
    assert split_leading_series_number("02 - The Next Book") == ("02", "The Next Book")
    assert split_leading_series_number("A Book") == ("", "A Book")


def test_metadata_escaping() -> None:
    value = "a=b;c#d\\e\r\nf"
    escaped = metadata_value(value)
    assert escaped == "a\\=b\\;c\\#d\\\\e\\nf"


def test_output_estimate() -> None:
    assert estimate_output_bytes(10, 96) == 120_000


def test_safe_output_stem_removes_windows_filename_characters() -> None:
    assert safe_output_stem('Book: Part 1 / "Final"') == "Book- Part 1 - -Final-"
    assert safe_output_stem("CON") == "CON-audiobook"


def test_book_output_path_reuses_author_and_series_folders(tmp_path: Path) -> None:
    metadata = BookMetadata(title="The First Book", author="An Author", series="A Series", series_number="1")

    output = book_output_path(tmp_path, metadata)

    assert output == tmp_path / "An Author" / "A Series" / "01 - The First Book" / "The First Book.m4b"


def test_book_output_path_sanitizes_folder_components(tmp_path: Path) -> None:
    metadata = BookMetadata(title="Book", author="Author: Name", series_number="2")

    output = book_output_path(tmp_path, metadata)

    assert output.parent == tmp_path / "Author- Name" / "02 - Book"
