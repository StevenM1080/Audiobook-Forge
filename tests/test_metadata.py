from pathlib import Path

from audiobook_forge.metadata import (
    GoogleBooksProvider,
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
    ).search("A Book", "An Author")

    assert len(results) == 1
    assert results[0].description == "Description from Google"
    assert results[0].isbn == "9780000000000"
    assert results[0].source == "Google Books + Open Library"
