from pathlib import Path
import xml.etree.ElementTree as ET

from audiobook_forge.metadata import (
    GoogleBooksProvider,
    LibraryOfCongressProvider,
    MetadataFinder,
    MetadataResult,
    OpenLibraryProvider,
)


def test_google_books_result_is_normalized() -> None:
    result = GoogleBooksProvider.clean_result(
        {
            "id": "volume-1",
            "volumeInfo": {
                "title": "Among the Imposters",
                "subtitle": "Shadow Children",
                "authors": ["Margaret Peterson Haddix"],
                "publisher": "Simon & Schuster",
                "publishedDate": "2002-05-01",
                "description": "A description.",
                "industryIdentifiers": [
                    {"type": "ISBN_10", "identifier": "0689839087"},
                    {"type": "ISBN_13", "identifier": "9780689839085"},
                ],
                "categories": ["Juvenile Fiction"],
                "averageRating": 4.2,
                "language": "en",
                "imageLinks": {"thumbnail": "http://books.google.com/cover.jpg"},
            },
        }
    )

    assert result.title == "Among the Imposters"
    assert result.author == "Margaret Peterson Haddix"
    assert result.published_year == "2002"
    assert result.isbn == "9780689839085"
    assert result.cover_url == "https://books.google.com/cover.jpg"
    assert result.source == "Google Books"


def test_open_library_result_is_normalized() -> None:
    result = OpenLibraryProvider.clean_result(
        {
            "key": "/works/OL123W",
            "title": "Among the Imposters",
            "author_name": ["Margaret Peterson Haddix"],
            "first_publish_year": 2002,
            "publisher": ["Simon Pulse"],
            "isbn": ["9780689839085", "0689839087"],
            "cover_i": 12345,
            "subject": ["Young adult fiction"],
            "language": ["eng"],
            "ratings_average": 4.0,
        }
    )

    assert result.title == "Among the Imposters"
    assert result.author == "Margaret Peterson Haddix"
    assert result.isbn == "9780689839085"
    assert result.cover_url == "https://covers.openlibrary.org/b/id/12345-L.jpg"
    assert result.source == "Open Library"


def test_open_library_isbn_falls_back_to_direct_edition_lookup() -> None:
    provider = OpenLibraryProvider()
    calls: list[str] = []

    def fake_get_json(url: str) -> dict:
        calls.append(url)
        if "/search.json" in url:
            return {"docs": []}
        return {
            "key": "/books/OL7729576M",
            "title": "Among the Imposters",
            "subtitle": "Shadow Children #2",
            "publish_date": "October 1, 2002",
            "isbn_13": ["9780689839085"],
            "publishers": ["Aladdin"],
            "covers": [436086],
            "subjects": ["Juvenile Fiction"],
            "languages": [{"key": "/languages/eng"}],
        }

    provider._get_json = fake_get_json  # type: ignore[method-assign]
    results = provider.search(isbn="978-0-689-83908-5")

    assert results[0].title == "Among the Imposters"
    assert results[0].published_year == "2002"
    assert results[0].isbn == "9780689839085"
    assert any("/isbn/9780689839085.json" in url for url in calls)


def test_library_of_congress_result_is_normalized() -> None:
    record = ET.fromstring(
        """
        <mods xmlns="http://www.loc.gov/mods/v3">
          <titleInfo><title>Among the Imposters</title><subTitle>Shadow Children #2</subTitle></titleInfo>
          <name type="personal" usage="primary"><namePart>Haddix, Margaret Peterson.</namePart></name>
          <originInfo><agent><namePart>Simon &amp; Schuster</namePart></agent><dateIssued>2002</dateIssued></originInfo>
          <language><languageTerm>eng</languageTerm></language>
          <abstract>Luke enters boarding school under an assumed name.</abstract>
          <subject><topic>Science fiction</topic></subject>
          <relatedItem type="series"><titleInfo><title>Shadow Children</title><partNumber>bk. 2</partNumber></titleInfo></relatedItem>
          <identifier type="isbn">9780689839085</identifier>
          <recordInfo><recordIdentifier>17722609</recordIdentifier></recordInfo>
        </mods>
        """
    )

    result = LibraryOfCongressProvider.clean_result(record)

    assert result.title == "Among the Imposters"
    assert result.subtitle == "Shadow Children #2"
    assert result.author == "Margaret Peterson Haddix"
    assert result.series_name == "Shadow Children"
    assert result.series_number == "bk. 2"
    assert result.isbn == "9780689839085"
    assert result.source == "Library of Congress"


def test_finder_rejects_wrong_author_false_positive() -> None:
    class StubProvider:
        def __init__(self, results: list[MetadataResult]) -> None:
            self.results = results

        def search(self, *_args) -> list[MetadataResult]:
            return self.results

    correct = MetadataResult(
        title="Among the Imposters",
        author="Margaret Peterson Haddix",
        source="Google Books",
        source_id="google:correct",
    )
    wrong = MetadataResult(
        title="The Imposter Among Us",
        author="Alexander Gui",
        source="Google Books",
        source_id="google:wrong",
    )

    results = MetadataFinder(
        google=StubProvider([wrong, correct]),
        open_library=StubProvider([]),
        library_of_congress=StubProvider([]),
    ).search("Among the Imposters", "Margaret Peterson Haddix")

    assert [result.title for result in results] == ["Among the Imposters"]


def test_finder_merges_matching_results_from_both_sources() -> None:
    google = MetadataResult(
        title="A Book",
        author="An Author",
        description="Description from Google",
        source="Google Books",
        source_id="google:book",
    )
    open_library = MetadataResult(
        title="A Book",
        author="An Author",
        isbn="9780000000000",
        source="Open Library",
        source_id="openlibrary:/works/OL1W",
    )

    results = MetadataFinder(
        google=type("Stub", (), {"search": lambda self, *_args: [google]})(),
        open_library=type("Stub", (), {"search": lambda self, *_args: [open_library]})(),
        library_of_congress=type("Stub", (), {"search": lambda self, *_args: []})(),
    ).search("A Book", "An Author")

    assert len(results) == 1
    assert results[0].description == "Description from Google"
    assert results[0].isbn == "9780000000000"
    assert results[0].source == "Google Books + Open Library"


def test_finder_deduplicates_source_names_when_merging_editions() -> None:
    first = MetadataResult(title="A Book", author="An Author", source="Open Library")
    second = MetadataResult(
        title="A Book",
        author="An Author",
        source="Library of Congress",
    )
    third = MetadataResult(
        title="A Book",
        author="An Author",
        source="Library of Congress",
    )

    results = MetadataFinder(
        google=type("Stub", (), {"search": lambda self, *_args: [first]})(),
        open_library=type("Stub", (), {"search": lambda self, *_args: [second]})(),
        library_of_congress=type("Stub", (), {"search": lambda self, *_args: [third]})(),
    ).search("A Book", "An Author")

    assert results[0].source == "Open Library + Library of Congress"


def test_finder_filters_wrong_isbn_results_but_keeps_identifierless_matches() -> None:
    class StubProvider:
        def __init__(self, results: list[MetadataResult]) -> None:
            self.results = results

        def search(self, *_args) -> list[MetadataResult]:
            return self.results

    correct = MetadataResult(title="Correct book", isbn="9780000000000", source="Google Books")
    wrong = MetadataResult(title="Wrong book", isbn="9780000000001", source="Open Library")
    no_identifier = MetadataResult(title="Edition without ISBN", source="Library of Congress")

    results = MetadataFinder(
        google=StubProvider([correct]),
        open_library=StubProvider([wrong]),
        library_of_congress=StubProvider([no_identifier]),
    ).search(isbn="978-0-000-00000-0")

    assert [result.title for result in results] == ["Correct book", "Edition without ISBN"]
