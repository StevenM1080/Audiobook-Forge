"""Metadata lookup using the public Google Books and Open Library APIs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 20
MAX_COVER_BYTES = 10 * 1024 * 1024


class MetadataLookupError(RuntimeError):
    """Raised when a metadata service cannot be reached or parsed."""


@dataclass(frozen=True)
class MetadataResult:
    title: str = ""
    subtitle: str = ""
    author: str = ""
    narrator: str = ""
    series_name: str = ""
    series_number: str = ""
    publisher: str = ""
    published_year: str = ""
    description: str = ""
    cover_url: str = ""
    isbn: str = ""
    genres: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    language: str = ""
    rating: str = ""
    source: str = ""
    source_id: str = ""
    match_confidence: float | None = None


class GoogleBooksProvider:
    """Search Google Books volumes without requiring an API key."""

    endpoint = "https://www.googleapis.com/books/v1/volumes"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS

    def search(self, title: str = "", author: str = "", isbn: str = "") -> list[MetadataResult]:
        title = _bounded_text(title)
        author = _bounded_text(author)
        isbn = _bounded_text(isbn)
        if isbn:
            query = f"isbn:{isbn}"
        else:
            terms = []
            if title:
                terms.append(f'intitle:"{title}"')
            if author:
                terms.append(f'inauthor:"{author}"')
            query = " ".join(terms)
        if not query:
            return []

        url = f"{self.endpoint}?{urlencode({'q': query, 'maxResults': '10', 'printType': 'books'})}"
        payload = self._get_json(url)
        results = []
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            if isinstance(item, dict):
                result = self.clean_result(item)
                if result.title:
                    results.append(result)
        return results

    def _get_json(self, url: str) -> dict:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "AudiobookForge/1.0 metadata lookup",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            raise MetadataLookupError(f"Google Books request failed: {error}") from error
        if not isinstance(payload, dict):
            raise MetadataLookupError("Google Books returned an invalid response.")
        return payload

    @staticmethod
    def clean_result(item: dict) -> MetadataResult:
        info = item.get("volumeInfo")
        if not isinstance(info, dict):
            return MetadataResult()
        identifiers = info.get("industryIdentifiers") or []
        isbn13 = ""
        isbn10 = ""
        for identifier in identifiers:
            if not isinstance(identifier, dict):
                continue
            value = str(identifier.get("identifier") or "").strip()
            if identifier.get("type") == "ISBN_13" and not isbn13:
                isbn13 = value
            elif identifier.get("type") == "ISBN_10" and not isbn10:
                isbn10 = value

        image_links = info.get("imageLinks") or {}
        cover_url = ""
        if isinstance(image_links, dict):
            for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
                if image_links.get(key):
                    cover_url = str(image_links[key]).replace("http://", "https://", 1)
                    break

        authors = _string_list(info.get("authors"))
        categories = _string_list(info.get("categories"))
        published = str(info.get("publishedDate") or "").strip()
        language = str(info.get("language") or "").strip()
        return MetadataResult(
            title=str(info.get("title") or "").strip(),
            subtitle=str(info.get("subtitle") or "").strip(),
            author=", ".join(authors),
            publisher=str(info.get("publisher") or "").strip(),
            published_year=published[:4] if published else "",
            description=str(info.get("description") or "").strip(),
            cover_url=cover_url,
            isbn=isbn13 or isbn10,
            genres=tuple(categories),
            language=language,
            rating=_format_rating(info.get("averageRating")),
            source="Google Books",
            source_id=f"google:{str(item.get('id') or '').strip()}",
        )


class OpenLibraryProvider:
    """Search Open Library editions for identifiers, subjects, and covers."""

    endpoint = "https://openlibrary.org/search.json"

    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS

    def search(self, title: str = "", author: str = "", isbn: str = "") -> list[MetadataResult]:
        title = _bounded_text(title)
        author = _bounded_text(author)
        isbn = _bounded_text(isbn)
        if not title and not author and not isbn:
            return []

        query: dict[str, str] = {
            "limit": "10",
            "fields": "key,title,subtitle,author_name,first_publish_year,publisher,isbn,cover_i,subject,language,ratings_average",
        }
        if isbn:
            query["isbn"] = isbn
        else:
            if title:
                query["title"] = title
            if author:
                query["author"] = author
        url = f"{self.endpoint}?{urlencode(query)}"
        payload = self._get_json(url)
        results = []
        for item in payload.get("docs", []) if isinstance(payload, dict) else []:
            if isinstance(item, dict):
                result = self.clean_result(item)
                if result.title:
                    results.append(result)
        return results

    def _get_json(self, url: str) -> dict:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "AudiobookForge/1.0 (metadata lookup)",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            raise MetadataLookupError(f"Open Library request failed: {error}") from error
        if not isinstance(payload, dict):
            raise MetadataLookupError("Open Library returned an invalid response.")
        return payload

    @staticmethod
    def clean_result(item: dict) -> MetadataResult:
        cover_id = item.get("cover_i")
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else ""
        authors = _string_list(item.get("author_name"))
        publishers = _string_list(item.get("publisher"))
        isbns = _string_list(item.get("isbn"))
        languages = _string_list(item.get("language"))
        subjects = _string_list(item.get("subject"))
        published_year = str(item.get("first_publish_year") or "").strip()
        return MetadataResult(
            title=str(item.get("title") or "").strip(),
            subtitle=str(item.get("subtitle") or "").strip(),
            author=", ".join(authors),
            publisher=publishers[0] if publishers else "",
            published_year=published_year[:4],
            cover_url=cover_url,
            isbn=_preferred_isbn(isbns),
            genres=tuple(subjects[:12]),
            language=languages[0] if languages else "",
            rating=_format_rating(item.get("ratings_average")),
            source="Open Library",
            source_id=f"openlibrary:{str(item.get('key') or '').strip()}",
        )


class MetadataFinder:
    """Combine and validate Google Books and Open Library matches."""

    def __init__(
        self,
        google: GoogleBooksProvider | None = None,
        open_library: OpenLibraryProvider | None = None,
    ) -> None:
        self.google = google or GoogleBooksProvider()
        self.open_library = open_library or OpenLibraryProvider()

    def search(
        self,
        title: str = "",
        author: str = "",
        isbn: str = "",
        max_results: int = 20,
    ) -> list[MetadataResult]:
        title = _bounded_text(title)
        author = _bounded_text(author)
        isbn = _bounded_text(isbn)
        if not title and not author and not isbn:
            return []

        providers = (self.google, self.open_library)
        results_by_provider: dict[object, list[MetadataResult]] = {}
        errors: list[Exception] = []
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="metadata") as executor:
            futures = {executor.submit(provider.search, title, author, isbn): provider for provider in providers}
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    results_by_provider[provider] = future.result()
                except MetadataLookupError as error:
                    errors.append(error)

        candidates = []
        for provider in providers:
            candidates.extend(results_by_provider.get(provider, []))
        if not candidates and len(errors) == len(providers):
            raise MetadataLookupError("Neither Google Books nor Open Library could be reached.") from errors[0]

        filtered = [
            result
            for result in candidates
            if isbn or self._is_plausible_match(result, title, author)
        ]
        merged = self._merge_results(filtered)
        scored = [
            replace(
                result,
                match_confidence=1.0 if isbn else self._match_confidence(result, title, author),
            )
            for result in merged
        ]
        scored.sort(
            key=lambda result: (
                -(result.match_confidence if result.match_confidence is not None else 0),
                result.title.casefold(),
                result.source.casefold(),
            )
        )
        return scored[: max(1, max_results)]

    @classmethod
    def _is_plausible_match(cls, result: MetadataResult, title: str, author: str) -> bool:
        title_score = _title_similarity(title, result.title, result.subtitle)
        if title and title_score < 0.55:
            return False
        if author and _author_similarity(author, result.author) < 0.55:
            return False
        return bool(result.title)

    @classmethod
    def _match_confidence(cls, result: MetadataResult, title: str, author: str) -> float:
        title_score = _title_similarity(title, result.title, result.subtitle) if title else 1.0
        if author:
            return max(0.0, min(1.0, 0.65 * title_score + 0.35 * _author_similarity(author, result.author)))
        return title_score

    @staticmethod
    def _merge_results(results: list[MetadataResult]) -> list[MetadataResult]:
        merged: list[MetadataResult] = []
        for result in results:
            match = next(
                (
                    existing
                    for existing in merged
                    if _title_similarity(existing.title, result.title, existing.subtitle) >= 0.85
                    and (
                        not existing.author
                        or not result.author
                        or _author_similarity(existing.author, result.author) >= 0.80
                    )
                ),
                None,
            )
            if match is None:
                merged.append(result)
                continue
            index = merged.index(match)
            merged[index] = replace(
                match,
                subtitle=match.subtitle or result.subtitle,
                author=match.author or result.author,
                publisher=match.publisher or result.publisher,
                published_year=match.published_year or result.published_year,
                description=match.description or result.description,
                cover_url=match.cover_url or result.cover_url,
                isbn=match.isbn or result.isbn,
                genres=match.genres or result.genres,
                tags=match.tags or result.tags,
                language=match.language or result.language,
                rating=match.rating or result.rating,
                source=" + ".join(dict.fromkeys(filter(None, (match.source, result.source)))),
                source_id=match.source_id or result.source_id,
            )
        return merged


def download_cover(url: str, destination_directory: Path, source_id: str = "") -> Path:
    """Download a selected cover without overwriting an existing local file."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MetadataLookupError("The metadata service returned an invalid cover URL.")

    suffix = Path(parsed.path).suffix.casefold()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    identity = re.sub(r"[^a-z0-9-]+", "-", source_id.strip().casefold()).strip("-")
    identity = identity or hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    destination_directory = destination_directory.resolve()
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / f"audiobook-forge-cover-{identity}{suffix}"
    if destination.is_file():
        return destination

    request = Request(url, headers={"User-Agent": "AudiobookForge/1.0 cover download"})
    temporary_path: Path | None = None
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            content_length = response.headers.get("Content-Length") if response.headers else None
            if content_length:
                try:
                    if int(content_length) > MAX_COVER_BYTES:
                        raise MetadataLookupError("The cover image is larger than the 10 MB safety limit.")
                except ValueError:
                    pass
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination_directory,
                prefix=".audiobook-forge-cover-",
                suffix=suffix,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                total = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_COVER_BYTES:
                        raise MetadataLookupError("The cover image is larger than the 10 MB safety limit.")
                    temporary.write(chunk)
                temporary.flush()
        if not temporary_path or temporary_path.stat().st_size == 0:
            raise MetadataLookupError("The metadata service returned an empty cover image.")
        temporary_path.replace(destination)
        temporary_path = None
        return destination
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise MetadataLookupError(f"Cover download failed: {error}") from error
    finally:
        if temporary_path and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _bounded_text(value: object, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _preferred_isbn(values: list[str]) -> str:
    for value in values:
        digits = re.sub(r"[^0-9Xx]", "", value)
        if len(digits) == 13:
            return value
    for value in values:
        digits = re.sub(r"[^0-9Xx]", "", value)
        if len(digits) == 10:
            return value
    return ""


def _format_rating(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value).strip()


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _title_similarity(query: str, title: str, subtitle: str = "") -> float:
    query_normalized = _normalized(query)
    candidate_normalized = _normalized(f"{title} {subtitle}".strip())
    if not query_normalized or not candidate_normalized:
        return 0.0
    query_tokens = set(query_normalized.split())
    candidate_tokens = set(candidate_normalized.split())
    overlap = len(query_tokens & candidate_tokens) / len(query_tokens)
    sequence = SequenceMatcher(None, query_normalized, candidate_normalized).ratio()
    return 0.55 * sequence + 0.45 * overlap


def _author_similarity(query: str, author: str) -> float:
    query_normalized = _normalized(query)
    if not query_normalized:
        return 1.0
    candidates = [part.strip() for part in re.split(r",|\band\b|&", author, flags=re.IGNORECASE) if part.strip()]
    return max((_title_similarity(query_normalized, candidate) for candidate in candidates), default=0.0)
