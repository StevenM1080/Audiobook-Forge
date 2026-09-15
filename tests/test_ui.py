from __future__ import annotations

import importlib.util
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QDragEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView, QLineEdit, QListWidgetItem, QMainWindow

from audiobook_forge.models import Book, BookMetadata, Chapter


def _load_main():
    spec = importlib.util.spec_from_file_location(
        "audiobook_forge_main_ui", Path(__file__).parents[1] / "main.pyw"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _window(module, tmp_path: Path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return module.MainWindow(settings)


def test_internal_chapter_drag_is_accepted(app: QApplication) -> None:
    module = _load_main()
    widget = module.DropList()
    item = QListWidgetItem("Chapter")
    widget.addItem(item)
    mime = widget.mimeData([item])
    event = QDragEnterEvent(
        QPoint(5, 5),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    widget.dragEnterEvent(event)

    assert event.isAccepted()


def test_cover_drop_updates_export_state_and_new_project_clears_it(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"not-an-image")

    window.cover_drop.set_path(cover)
    assert window.cover == cover.resolve()

    window.new_project()
    assert window.cover is None
    assert window.cover_drop.path is None


def test_layout_uses_content_minimums_instead_of_a_fixed_window_size(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    assert window.minimumWidth() == 0
    assert window.minimumHeight() == 0

    window.resize(920, 640)
    window.show()
    app.processEvents()

    assert window.output_edit.minimumWidth() >= 180
    header = window.file_tree.header()
    for index in range(4):
        assert header.sectionResizeMode(index) == QHeaderView.ResizeMode.Interactive
    assert header.stretchLastSection()
    assert header.length() == header.viewport().width()
    assert header.sectionSize(module.DURATION_COLUMN) > 100
    assert header.sectionSize(module.PROGRESS_COLUMN) >= 140
    assert window.details_group.width() >= 390
    assert window.output_edit.width() >= window.output_edit.minimumWidth()
    assert window.details_group.height() >= window.details_group.minimumSizeHint().height()
    assert window.chapter_group.width() >= window.chapter_group.minimumSizeHint().width()
    window.close()


def test_books_have_individual_progress_and_extended_selection(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    first = Book(
        chapters=[Chapter(tmp_path / "one.mp3", "One", 1.0)],
        metadata=BookMetadata(title="First", author="Author"),
    )
    second = Book(
        chapters=[Chapter(tmp_path / "two.mp3", "Two", 1.0)],
        metadata=BookMetadata(title="Second", author="Author"),
    )
    window.books = [first, second]
    window.selected_book_id = first.book_id
    window._render_books(first.book_id)

    assert window.file_tree.selectionMode() == module.QTreeWidget.SelectionMode.ExtendedSelection
    window.output_structure_combo.setCurrentIndex(window.output_structure_combo.findText("Flat files"))
    assert window.output_template_edit.text() == "{title}.m4b"
    progress_bar = window.file_tree.itemWidget(window.file_tree.topLevelItem(0), module.PROGRESS_COLUMN)
    assert isinstance(progress_bar, module.QProgressBar)
    window.update_book_progress(first.book_id, 42, "Encoding")
    assert progress_bar.value() == 42
    assert progress_bar.toolTip() == "Encoding"

    window.file_tree.topLevelItem(0).setSelected(True)
    window.file_tree.topLevelItem(1).setSelected(True)
    window.remove_selected()
    assert window.books == []
    window.close()


def test_metadata_dialog_starts_search_when_opened(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    calls: list[bool] = []
    monkeypatch.setattr(module.MetadataSearchDialog, "search", lambda _dialog: calls.append(True))

    dialog = module.MetadataSearchDialog(None, "Book", "Author", "")
    app.processEvents()

    assert calls == [True]
    dialog.close()


def test_number_header_aligns_with_indented_chapter_numbers(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    window.chapters = [Chapter(tmp_path / "01.mp3", "Opening", 1.0)]
    window._render_chapters()

    number_alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    assert window.file_tree.headerItem().textAlignment(module.NUMBER_COLUMN) == number_alignment
    assert window.file_tree.topLevelItem(0).textAlignment(module.NUMBER_COLUMN) == number_alignment
    assert window.file_tree.columnWidth(module.NUMBER_COLUMN) >= (
        window.file_tree.indentation()
        + 16
        + window.file_tree.fontMetrics().horizontalAdvance("00")
    )
    window.close()


def test_chapter_title_editor_uses_the_full_row_height(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    window.chapters = [Chapter(tmp_path / "01.mp3", "Opening", 1.0)]
    window._render_chapters()
    book_item = window.file_tree.topLevelItem(0)
    book_item.setExpanded(True)
    app.processEvents()
    chapter_item = book_item.child(0)

    window.file_tree.editItem(chapter_item, module.TITLE_COLUMN)
    app.processEvents()
    editor = window.file_tree.findChildren(QLineEdit)[0]

    assert editor.height() == window.file_tree.visualItemRect(chapter_item).height()
    assert editor.height() >= editor.fontMetrics().height() + 2
    window.close()


def test_chapter_title_source_can_switch_between_embedded_title_and_filename(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    chapter_path = tmp_path / "Chapter 1 - Preface.mp3"
    window.chapters = [Chapter(chapter_path, "- 01/16", 1.0)]
    window._render_chapters()

    window.chapter_title_combo.setCurrentIndex(module.CHAPTER_TITLE_SOURCE_FILENAME)
    assert window.chapters[0].title == "Chapter 1 - Preface"
    assert window.file_tree.topLevelItem(0).child(0).text(module.TITLE_COLUMN) == "Chapter 1 - Preface"

    window.chapter_title_combo.setCurrentIndex(module.CHAPTER_TITLE_SOURCE_EMBEDDED)
    assert window.chapters[0].title == "- 01/16"
    window.close()


def test_channel_mode_replaces_preserve_source_with_auto(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)

    assert [window.channel_combo.itemText(index) for index in range(window.channel_combo.count())] == [
        "Auto",
        "Force mono",
        "Force stereo",
    ]
    assert window._default_channel_mode() == "Auto"
    window.close()


def test_auto_channel_label_reflects_resolved_layout_without_changing_mode(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    window.chapters = [Chapter(tmp_path / "01.mp3", "Chapter", 1.0)]
    window._render_chapters()
    book_id = window.books[0].book_id

    window._channel_mode_resolved(book_id, 1)
    assert window.channel_combo.itemText(0) == "Auto (mono)"
    assert window.channel_combo.currentData() == "Auto"
    window._commit_current_book()
    assert window.books[0].channel_mode == "Auto"

    window._channel_mode_resolved(book_id, 2)
    assert window.channel_combo.itemText(0) == "Auto (stereo)"
    window.close()


def test_import_resolves_auto_channel_layout_before_export(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    source = tmp_path / "Chapter 1.mp3"
    source.write_bytes(b"audio")
    monkeypatch.setattr(
        module,
        "probe_audio",
        lambda path: Chapter(path.resolve(), "Chapter", 1.0, channels=2),
    )
    monkeypatch.setattr(module, "common_tags", lambda _chapters: {})
    monkeypatch.setattr(module, "discover_tool", lambda *_args, **_kwargs: Path("ffmpeg"))
    monkeypatch.setattr(
        module,
        "target_channel_count",
        lambda chapters, mode, **_kwargs: 1 if mode == "Auto" and chapters else 2,
    )

    window.add_paths([source])

    assert window.books[0].auto_channel_count == 1
    assert window._auto_channel_results[window.books[0].book_id] == 1
    assert window.channel_combo.itemText(0) == "Auto (mono)"
    assert window.channel_combo.currentData() == "Auto"
    window.close()


def test_filename_title_source_applies_to_new_imports(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    source = tmp_path / "Chapter 2 - The Selish System.mp3"
    source.write_bytes(b"audio")
    monkeypatch.setattr(
        module,
        "probe_audio",
        lambda path: Chapter(path.resolve(), "- 02/16", 1.0),
    )
    monkeypatch.setattr(module, "common_tags", lambda _chapters: {})
    window.chapter_title_combo.setCurrentIndex(module.CHAPTER_TITLE_SOURCE_FILENAME)

    window.add_paths([source])

    assert window.books[0].chapters[0].title == "Chapter 2 - The Selish System"
    window.close()


def test_window_geometry_preference_is_ignored(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    saved_window = QMainWindow()
    saved_window.resize(120, 120)
    settings.setValue("window_geometry", saved_window.saveGeometry())

    window = module.MainWindow(settings)

    assert not settings.contains("window_geometry")
    assert window.width() > 120 or window.height() > 120
    window.close()


def test_window_opens_centered_on_available_screen(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    window.show()
    app.processEvents()
    QTest.qWait(150)
    app.processEvents()
    available = app.primaryScreen().availableGeometry()

    assert window.frameGeometry().center() == available.center()
    window.close()


def test_manual_order_survives_an_addition(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    first = tmp_path / "02.mp3"
    second = tmp_path / "01.mp3"
    added = tmp_path / "03.mp3"
    for path in (first, second, added):
        path.write_bytes(b"audio")
    window.chapters = [
        Chapter(first.resolve(), "Second", 1.0),
        Chapter(second.resolve(), "First", 1.0),
    ]
    window._render_chapters()
    window.sort_combo.setCurrentIndex(2)
    monkeypatch.setattr(
        module,
        "probe_audio",
        lambda path: Chapter(path.resolve(), path.stem, 1.0),
    )
    monkeypatch.setattr(module, "common_tags", lambda _chapters: {})

    window.add_paths([added])

    assert [chapter.path for chapter in window.chapters] == [
        first.resolve(),
        second.resolve(),
        added.resolve(),
    ]
    assert window.sort_combo.currentIndex() == 2


def test_natural_sort_reorders_the_complete_chapter_list(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    chapter_two = tmp_path / "Chapter 2.mp3"
    chapter_one = tmp_path / "Chapter 1.mp3"
    chapter_two.write_bytes(b"audio")
    chapter_one.write_bytes(b"audio")
    window.chapters = [Chapter(chapter_two.resolve(), "Two", 1.0)]
    window._render_chapters()
    monkeypatch.setattr(
        module,
        "probe_audio",
        lambda path: Chapter(path.resolve(), path.stem, 1.0),
    )
    monkeypatch.setattr(module, "common_tags", lambda _chapters: {})

    window.add_paths([chapter_one])

    assert [chapter.path for chapter in window.chapters] == [
        chapter_one.resolve(),
        chapter_two.resolve(),
    ]


def test_track_number_sort_places_untagged_chapters_last(
    app: QApplication, tmp_path: Path
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    window.chapters = [
        Chapter(Path("untagged.mp3"), "Untagged", 1.0),
        Chapter(Path("track-2.mp3"), "Two", 1.0, track_number=2),
        Chapter(Path("track-1.mp3"), "One", 1.0, track_number=1),
    ]
    window._render_chapters()

    window.sort_combo.setCurrentIndex(1)

    assert [chapter.track_number for chapter in window.chapters] == [1, 2, None]


def test_folder_import_creates_collapsible_books_and_switches_metadata(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    first_folder = tmp_path / "First Book"
    second_folder = tmp_path / "Second Book"
    first_folder.mkdir()
    second_folder.mkdir()
    for folder in (first_folder, second_folder):
        (folder / "01.mp3").write_bytes(b"audio")
    monkeypatch.setattr(module, "probe_audio", lambda path: Chapter(path.resolve(), path.stem, 1.0))
    monkeypatch.setattr(module, "common_tags", lambda _chapters: {})

    window.add_paths([first_folder, second_folder])

    assert len(window.books) == 2
    assert window.file_tree.topLevelItemCount() == 2
    first_item = window.file_tree.topLevelItem(0)
    second_item = window.file_tree.topLevelItem(1)
    assert first_item.text(0) == ""
    assert first_item.text(1) == "First Book"
    assert first_item.text(2) == "00:00:01"
    assert first_item.childCount() == 1
    first_item.setExpanded(True)
    first_item.child(0).setText(1, "Edited chapter")
    app.processEvents()
    assert window.books[0].chapters[0].title == "Edited chapter"
    first_item.setExpanded(False)
    assert not first_item.isExpanded()

    window.file_tree.setCurrentItem(first_item)
    app.processEvents()
    window.author_edit.setText("Author One")
    window.title_edit.setText("Edited First")
    window.metadata_edits["series_number"].setText("3")
    assert first_item.text(0) == "3"
    window.file_tree.setCurrentItem(second_item)
    app.processEvents()

    assert window.books[0].metadata.title == "Edited First"
    assert window.books[0].metadata.author == "Author One"
    assert window.title_edit.text() == "Second Book"
    window.close()


def test_numbered_folder_populates_series_number_without_number_in_title(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    source_folder = tmp_path / "1 Among The Hidden"
    source_folder.mkdir()
    chapter = source_folder / "01.mp3"
    chapter.write_bytes(b"audio")
    monkeypatch.setattr(module, "probe_audio", lambda path: Chapter(path.resolve(), path.stem, 1.0))
    monkeypatch.setattr(module, "common_tags", lambda _chapters: {})

    window.add_paths([source_folder])

    book = window.books[0]
    assert book.metadata.series_number == "1"
    assert book.metadata.title == "Among The Hidden"
    assert window.metadata_edits["series_number"].text() == "1"
    assert window.title_edit.text() == "Among The Hidden"
    assert window.file_tree.topLevelItem(0).text(0) == "1"
    assert window.file_tree.topLevelItem(0).text(1) == "Among The Hidden"
    window.close()


def test_loose_files_added_together_form_one_book(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    files = [tmp_path / "01.mp3", tmp_path / "02.mp3"]
    for path in files:
        path.write_bytes(b"audio")
    monkeypatch.setattr(module, "probe_audio", lambda path: Chapter(path.resolve(), path.stem, 1.0))
    monkeypatch.setattr(module, "common_tags", lambda _chapters: {})

    window.add_paths(files)

    assert len(window.books) == 1
    assert [chapter.path for chapter in window.books[0].chapters] == [path.resolve() for path in files]
    window.close()


def test_folder_cover_is_autopopulated_without_missing_cover_warning(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    source_folder = tmp_path / "Book"
    source_folder.mkdir()
    (source_folder / "01.mp3").write_bytes(b"audio")
    cover = source_folder / "Cover.png"
    cover.write_bytes(b"image")
    monkeypatch.setattr(module, "probe_audio", lambda path: Chapter(path.resolve(), path.stem, 1.0))
    monkeypatch.setattr(module, "common_tags", lambda _chapters: {})

    window.add_paths([source_folder])

    assert window.books[0].cover == cover.resolve()
    assert window.cover_drop.path == cover.resolve()
    window.close()


def test_metadata_search_applies_result_and_downloaded_cover(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_main()
    window = _window(module, tmp_path)
    source = tmp_path / "01.mp3"
    source.write_bytes(b"audio")
    window.chapters = [Chapter(source, "Imported title", 60.0)]
    window._render_chapters()
    cover = tmp_path / "downloaded-cover.jpg"
    cover.write_bytes(b"image")

    result = module.MetadataResult(
        title="Matched title",
        subtitle="A subtitle",
        author="Matched author",
        narrator="Matched narrator",
        publisher="Matched publisher",
        published_year="2024",
        description="A description",
        cover_url="https://example.test/cover.jpg",
        isbn="9780000000000",
        genres=("Fantasy",),
        tags=("Magic",),
        series_name="A series",
        series_number="2",
        language="English",
        rating="4.5",
        source="Google Books",
        source_id="google:test",
    )

    class FakeDialog:
        selected_result = result

        def __init__(self, *_args) -> None:
            pass

        def exec(self):
            return module.QDialog.DialogCode.Accepted

    monkeypatch.setattr(module, "MetadataSearchDialog", FakeDialog)
    monkeypatch.setattr(module, "download_cover", lambda *_args: cover)

    window.search_metadata()

    metadata = window.books[0].metadata
    assert metadata.title == "Matched title"
    assert metadata.author == "Matched author"
    assert metadata.narrator == "Matched narrator"
    assert metadata.series == "A series"
    assert metadata.series_number == "2"
    assert metadata.genre == "Fantasy"
    assert metadata.description == "A description"
    assert metadata.isbn == "9780000000000"
    assert window.books[0].cover == cover
    window.close()
