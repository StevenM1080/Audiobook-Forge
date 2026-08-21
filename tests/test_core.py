from pathlib import Path

from audiobook_forge.models import estimate_output_bytes, natural_sort_key
import importlib.util


def _load_main():
    spec = importlib.util.spec_from_file_location("audiobook_forge_main", Path(__file__).parents[1] / "main.pyw")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ConversionWorker = _load_main().ConversionWorker


def test_natural_sort_key_orders_numbers_numerically() -> None:
    paths = [Path("Chapter 10.mp3"), Path("Chapter 2.mp3"), Path("Chapter 1.mp3")]
    assert [path.name for path in sorted(paths, key=natural_sort_key)] == [
        "Chapter 1.mp3",
        "Chapter 2.mp3",
        "Chapter 10.mp3",
    ]


def test_metadata_escaping() -> None:
    value = r"a=b;c#d\\e\nf"
    escaped = ConversionWorker._metadata_value(value)
    assert escaped == r"a\\=b\\;c\\#d\\\\e\\nf"


def test_output_estimate() -> None:
    assert estimate_output_bytes(10, 96) == 120_000
