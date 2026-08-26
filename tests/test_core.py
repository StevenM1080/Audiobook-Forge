from pathlib import Path

from audiobook_forge.exporter import metadata_value
from audiobook_forge.models import estimate_output_bytes, natural_sort_key, safe_output_stem


def test_natural_sort_key_orders_numbers_numerically() -> None:
    paths = [Path("Chapter 10.mp3"), Path("Chapter 2.mp3"), Path("Chapter 1.mp3")]
    assert [path.name for path in sorted(paths, key=natural_sort_key)] == [
        "Chapter 1.mp3",
        "Chapter 2.mp3",
        "Chapter 10.mp3",
    ]


def test_metadata_escaping() -> None:
    value = "a=b;c#d\\e\r\nf"
    escaped = metadata_value(value)
    assert escaped == "a\\=b\\;c\\#d\\\\e\\nf"


def test_output_estimate() -> None:
    assert estimate_output_bytes(10, 96) == 120_000


def test_safe_output_stem_removes_windows_filename_characters() -> None:
    assert safe_output_stem('Book: Part 1 / "Final"') == "Book- Part 1 - -Final-"
    assert safe_output_stem("CON") == "CON-audiobook"
