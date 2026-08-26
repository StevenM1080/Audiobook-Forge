from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


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
