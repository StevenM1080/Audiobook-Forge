from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from string import Formatter
from uuid import uuid4


SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"}
DEFAULT_OUTPUT_TEMPLATE = "{author}/{series}/{book}/{title}.m4b"


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
    subtitle: str = ""
    publisher: str = ""
    description: str = ""
    isbn: str = ""
    language: str = ""
    tags: str = ""
    rating: str = ""


def title_with_subtitle(title: str, subtitle: str) -> str:
    """Return a title that keeps a meaningful subtitle visible."""

    title = title.strip()
    subtitle = subtitle.strip()
    if not title:
        return subtitle
    if not subtitle or subtitle.casefold() in title.casefold():
        return title
    return f"{title}: {subtitle}"


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
        return (
            title_with_subtitle(self.metadata.title, self.metadata.subtitle)
            or self.source_name.strip()
            or "Untitled book"
        )


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


def _render_output_template(
    template: str,
    metadata: BookMetadata,
    source_name: str = "",
) -> list[str]:
    author = safe_folder_name(metadata.author, "Unknown Author")
    full_title = title_with_subtitle(metadata.title, metadata.subtitle)
    title = safe_folder_name(full_title, "Untitled Book")
    series = metadata.series.strip()
    series_value = safe_folder_name(series, "") if series else ""
    series_number = metadata.series_number.strip()
    if series_number.isdigit():
        series_number = f"{int(series_number):02d}"
    else:
        series_number = ""
    book = f"{series_number} - {title}" if series_number else title
    values = {
        "author": author,
        "series": series_value,
        "series_number": series_number,
        "book": safe_folder_name(book, "Untitled Book"),
        "title": safe_output_stem(full_title or title),
        "narrator": safe_folder_name(metadata.narrator, "") if metadata.narrator.strip() else "",
        "year": metadata.year.strip(),
        "source": safe_folder_name(source_name, "") if source_name.strip() else "",
    }
    fields: list[str] = []
    formatter = Formatter()
    try:
        for literal, field_name, format_spec, conversion in formatter.parse(template):
            fields.append(literal)
            if field_name is None:
                continue
            key = field_name.casefold()
            if key not in values:
                supported = ", ".join(sorted(values))
                raise ValueError(f"Unknown output template field {{{field_name}}}. Use: {supported}.")
            if format_spec or conversion:
                raise ValueError("Output template fields cannot use format specs or conversions.")
            fields.append(values[key])
    except ValueError:
        raise
    rendered = "".join(fields).strip()
    components = [component.strip() for component in re.split(r"[\\/]+", rendered) if component.strip()]
    if not components:
        raise ValueError("The output template must produce a file path.")
    return components


def book_output_path(
    destination_root: Path,
    metadata: BookMetadata,
    template: str | None = None,
    source_name: str = "",
) -> Path:
    """Build a sanitized output path from the selected template."""

    selected_template = template.strip() if template and template.strip() else DEFAULT_OUTPUT_TEMPLATE
    components = _render_output_template(selected_template, metadata, source_name)
    filename = components.pop()
    suffix = Path(filename).suffix
    stem = filename[: -len(suffix)] if suffix else filename
    safe_filename = f"{safe_output_stem(stem)}.m4b"
    folders = [safe_folder_name(component, "Folder") for component in components]
    return destination_root.joinpath(*folders, safe_filename)
