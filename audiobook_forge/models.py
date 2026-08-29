from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from uuid import uuid4


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"}


@dataclass
class Chapter:
    path: Path
    title: str
    duration: float
    track_number: int | None = None
    channels: int | None = None
    sample_rate: int | None = None


@dataclass
class BookMetadata:
    title: str = ""
    author: str = ""
    narrator: str = ""
    series: str = ""
    series_number: str = ""
    year: str = ""
    genre: str = ""


@dataclass
class Book:
    """One audiobook in a batch project."""

    chapters: list[Chapter] = field(default_factory=list)
    metadata: BookMetadata = field(default_factory=BookMetadata)
    cover: Path | None = None
    bitrate: int = 96
    channel_mode: str = "Auto"
    source_name: str = ""
    book_id: str = field(default_factory=lambda: uuid4().hex)
    # Cached result of the content-based Auto channel analysis. This is kept
    # out of project files because it must be recomputed when sources change.
    auto_channel_count: int | None = None

    @property
    def display_title(self) -> str:
        return self.metadata.title.strip() or self.source_name.strip() or "Untitled book"


def split_leading_series_number(value: str) -> tuple[str, str]:
    """Split a leading folder number from its title when both are present."""

    match = re.match(r"^\s*(\d+)(?:\s*[-_.:)]\s*|\s+)(\S.*)\s*$", value)
    if not match:
        return "", value.strip()
    return match.group(1), match.group(2).strip()


def natural_sort_key(path: Path) -> list[object]:
    parts: list[object] = []
    for part in re.split(r"(\d+)", path.name.casefold()):
        if not part:
            continue
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part)
    return parts


def estimate_output_bytes(duration: float, bitrate_kbps: int) -> int:
    return max(0, int(duration * bitrate_kbps * 1000 / 8))


def safe_output_stem(title: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("-" if character in invalid else character for character in title)
    cleaned = " ".join(cleaned.split()).rstrip(". ")
    if not cleaned:
        return "audiobook"
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
    return f"{cleaned}-audiobook" if cleaned.upper() in reserved else cleaned


def safe_folder_name(value: str, fallback: str) -> str:
    """Return a Windows-safe, non-empty folder component."""

    invalid = '<>:"/\\|?*'
    cleaned = "".join("-" if character in invalid else character for character in value)
    cleaned = " ".join(cleaned.split()).rstrip(". ")
    if not cleaned:
        cleaned = fallback
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
    return f"{cleaned}-folder" if cleaned.upper() in reserved else cleaned


def book_output_path(destination_root: Path, metadata: BookMetadata) -> Path:
    """Build the deterministic nested destination for one book."""

    author = safe_folder_name(metadata.author, "Unknown Author")
    title = safe_folder_name(metadata.title, "Untitled Book")
    components = [destination_root, author]
    if metadata.series.strip():
        components.append(safe_folder_name(metadata.series, "Series"))

    series_number = metadata.series_number.strip()
    if series_number.isdigit():
        series_number = f"{int(series_number):02d}"
    book_folder = f"{series_number} - {title}" if series_number else title
    components.append(safe_folder_name(book_folder, "Untitled Book"))
    return Path(*components) / f"{safe_output_stem(metadata.title or title)}.m4b"
