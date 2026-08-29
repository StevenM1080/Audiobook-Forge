from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QComboBox,
    QStyledItemDelegate,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from audiobook_forge.exporter import (
    BatchExportEngine,
    ExportCancelled,
    ExportEngine,
    discover_tool,
    format_time,
    metadata_value,
    target_channel_count,
)
from audiobook_forge.media import IMAGE_EXTENSIONS, common_tags, find_cover, probe_audio, supported_audio_files
from audiobook_forge.models import (
    BookMetadata,
    Book,
    Chapter,
    SUPPORTED_AUDIO_EXTENSIONS,
    estimate_output_bytes,
    book_output_path,
    natural_sort_key,
    split_leading_series_number,
)
from audiobook_forge.project_io import load_project, save_batch_project

AUDIO_EXTENSIONS = SUPPORTED_AUDIO_EXTENSIONS
class DropList(QListWidget):
    paths_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setSpacing(4)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        elif event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        elif event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        audio_paths = [path for path in paths if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS]
        folders = [path for path in paths if path.is_dir()]
        if audio_paths or folders:
            self.paths_dropped.emit(audio_paths + folders)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class TreeTitleDelegate(QStyledItemDelegate):
    """Keep the inline title editor inside the complete tree row."""

    def updateEditorGeometry(self, editor, option, index) -> None:
        row_rect = None
        view = self.parent()
        if isinstance(view, QTreeWidget):
            candidate = view.visualRect(index)
            if candidate.isValid():
                row_rect = candidate

        editor_rect = option.rect
        if row_rect is not None:
            editor_rect.setTop(row_rect.top())
            editor_rect.setBottom(row_rect.bottom())
        editor.setGeometry(editor_rect)


BOOK_ROLE = Qt.ItemDataRole.UserRole
NUMBER_COLUMN = 0
TITLE_COLUMN = 1
DURATION_COLUMN = 2
CHAPTER_TITLE_SOURCE_EMBEDDED = 0
CHAPTER_TITLE_SOURCE_FILENAME = 1
CHAPTER_PATH_ROLE = Qt.ItemDataRole.UserRole + 1
CHAPTER_TITLE_ROLE = Qt.ItemDataRole.UserRole + 2
CHAPTER_DURATION_ROLE = Qt.ItemDataRole.UserRole + 3


class DropTree(QTreeWidget):
    paths_dropped = Signal(list)
    structure_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.setColumnCount(3)
        self.setHeaderLabels(["#", "Title", "Duration"])
        self.setHeaderHidden(False)
        header = self.header()
        header.setSectionsMovable(False)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(NUMBER_COLUMN, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(TITLE_COLUMN, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(DURATION_COLUMN, QHeaderView.ResizeMode.Interactive)
        self.setIndentation(18)
        self.setAlternatingRowColors(False)
        self.setUniformRowHeights(True)
        # The tree branch and the chapter number share the first section. Give
        # the number enough room after the branch indent and align it with the
        # matching header edge so the expand control does not look like '#'.
        header_item = self.headerItem()
        header_item.setTextAlignment(
            NUMBER_COLUMN,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self.setColumnWidth(NUMBER_COLUMN, 76)
        self.setColumnWidth(TITLE_COLUMN, 380)
        self.setColumnWidth(DURATION_COLUMN, 100)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        elif event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            target = self.itemAt(event.position().toPoint())
            target_book = target.parent() if target and target.parent() else target
            for source in self.selectedItems():
                source_book = source.parent()
                if source_book is None and target is not None and target.parent() is not None:
                    event.ignore()
                    return
                if source_book is not None and target_book is not source_book:
                    event.ignore()
                    return
                if source_book is not None and target is source_book:
                    event.ignore()
                    return
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
            audio_paths = [path for path in paths if path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS]
            folders = [path for path in paths if path.is_dir()]
            if audio_paths or folders:
                self.paths_dropped.emit(audio_paths + folders)
                event.acceptProposedAction()
            else:
                event.ignore()
            return

        if event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist"):
            target = self.itemAt(event.position().toPoint())
            target_book = target.parent() if target and target.parent() else target
            for source in self.selectedItems():
                source_book = source.parent()
                if source_book is None and target is not None and target.parent() is not None:
                    event.ignore()
                    return
                if source_book is not None and target_book is not source_book:
                    event.ignore()
                    return
                if source_book is not None and target is source_book:
                    event.ignore()
                    return
            event.setDropAction(Qt.DropAction.MoveAction)
            super().dropEvent(event)
            self.structure_changed.emit()
            return
        super().dropEvent(event)


class CoverDrop(QFrame):
    path_changed = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self.path: Path | None = None
        self.setAcceptDrops(True)
        self.setObjectName("coverDrop")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview = QLabel("DROP COVER ART\nOR BROWSE")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("coverPreview")
        layout.addWidget(self.preview)

    def set_path(self, path: Path) -> None:
        self.path = path
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.preview.setPixmap(pixmap.scaled(170, 170, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.setText(path.name)
        self.path_changed.emit(path)

    def clear(self) -> None:
        self.path = None
        self.preview.clear()
        self.preview.setText("DROP COVER ART\nOR BROWSE")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            Path(url.toLocalFile()).is_file()
            and Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                self.set_path(path)
                event.acceptProposedAction()
                return


class ConversionWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(Path)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, chapters: list[Chapter], output: Path, metadata: dict[str, str], cover: Path | None, bitrate: int, channel_mode: str, ffmpeg_path: str | None, ffprobe_path: str | None) -> None:
        super().__init__()
        self.engine = ExportEngine(
            chapters,
            output,
            metadata,
            cover,
            bitrate,
            channel_mode,
            ffmpeg_path,
            ffprobe_path,
            self.progress.emit,
        )

    def cancel(self) -> None:
        self.engine.cancel()

    @staticmethod
    def _metadata_value(value: str) -> str:
        return metadata_value(value)

    def run(self) -> None:
        try:
            output = self.engine.run()
        except ExportCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.finished.emit(output)


class BatchConversionWorker(QObject):
    progress = Signal(int, str)
    book_finished = Signal(str, str)
    channel_mode_resolved = Signal(str, int)
    finished = Signal(list)
    failed = Signal(str, int)
    cancelled = Signal(int)

    def __init__(self, books: list[Book], destination_root: Path, ffmpeg_path: str | None, ffprobe_path: str | None) -> None:
        super().__init__()
        self.engine = BatchExportEngine(
            books,
            destination_root,
            ffmpeg_path,
            ffprobe_path,
            self.progress.emit,
            lambda _index, book, output: self.book_finished.emit(book.book_id, str(output)),
            lambda _index, book, channels: self.channel_mode_resolved.emit(book.book_id, channels),
        )

    def cancel(self) -> None:
        self.engine.cancel()

    def run(self) -> None:
        try:
            outputs = self.engine.run()
        except ExportCancelled:
            self.cancelled.emit(len(self.engine.completed))
        except Exception as error:
            self.failed.emit(str(error), len(self.engine.completed))
        else:
            self.finished.emit([str(output) for output in outputs])


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings if settings is not None else QSettings("AudiobookForge", "AudiobookForge")
        self.books: list[Book] = []
        self.selected_book_id: str | None = None
        self.destination_root: Path | None = None
        self._pending_cover: Path | None = None
        self._embedded_chapter_titles: dict[Path, str] = {}
        self._use_filename_titles = False
        self._auto_channel_results: dict[str, int] = {}
        self._loading_book = False
        self._legacy_chapters_assignment = False
        self.thread: QThread | None = None
        self.worker: BatchConversionWorker | None = None
        self.project_path: Path | None = None
        self.busy_actions = []
        self.setWindowTitle("Audiobook Forge")
        self._build_ui()
        self._build_menu()
        self._restore_settings()

    def _center_on_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        if not self.isMaximized() and not self.isFullScreen():
            self.adjustSize()
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._center_on_screen)
        # Qt may apply the final platform frame size after the first queued
        # callback. Recenter once that post-show sizing pass has completed.
        QTimer.singleShot(100, self._center_on_screen)

    @property
    def chapters(self) -> list[Chapter]:
        """Compatibility view for older callers that used the single-book API."""

        if len(self.books) == 1:
            return self.books[0].chapters
        return [chapter for book in self.books for chapter in book.chapters]

    @chapters.setter
    def chapters(self, chapters: list[Chapter]) -> None:
        self._auto_channel_results.clear()
        if not self.books:
            self.books = [Book(chapters=list(chapters), source_name="Imported book")]
            self.selected_book_id = self.books[0].book_id
        elif len(self.books) == 1:
            self.books[0].chapters = list(chapters)
            self.books[0].auto_channel_count = None
        else:
            self.books = [Book(chapters=list(chapters), source_name="Imported book")]
            self.selected_book_id = self.books[0].book_id
        self._legacy_chapters_assignment = True

    @property
    def cover(self) -> Path | None:
        book = self._selected_book()
        return book.cover if book else self._pending_cover

    @cover.setter
    def cover(self, path: Path | None) -> None:
        book = self._selected_book()
        if book:
            book.cover = path
        else:
            self._pending_cover = path

    def _restore_settings(self) -> None:
        # Geometry is intentionally session-local. Remove the legacy value so
        # older squished layouts cannot be resurrected by a future migration.
        self.settings.remove("window_geometry")
        try:
            bitrate_index = int(self.settings.value("bitrate_index", 1))
        except (TypeError, ValueError):
            bitrate_index = 1
        self.quality_combo.setCurrentIndex(bitrate_index if bitrate_index in range(4) else 1)
        channel_mode = self._normalize_channel_mode(self.settings.value("channel_mode", "Auto"))
        self.channel_combo.setCurrentIndex(self.channel_combo.findData(channel_mode))
        try:
            title_source = int(self.settings.value("chapter_title_source", CHAPTER_TITLE_SOURCE_EMBEDDED))
        except (TypeError, ValueError):
            title_source = CHAPTER_TITLE_SOURCE_EMBEDDED
        if title_source not in {CHAPTER_TITLE_SOURCE_EMBEDDED, CHAPTER_TITLE_SOURCE_FILENAME}:
            title_source = CHAPTER_TITLE_SOURCE_EMBEDDED
        self._use_filename_titles = title_source == CHAPTER_TITLE_SOURCE_FILENAME
        self.chapter_title_combo.blockSignals(True)
        self.chapter_title_combo.setCurrentIndex(title_source)
        self.chapter_title_combo.blockSignals(False)

    def _build_menu(self) -> None:
        project_menu = self.menuBar().addMenu("Project")
        self.busy_actions.extend(
            [
                project_menu.addAction("New Project", self.new_project),
                project_menu.addAction("Open Project...", self.open_project),
                project_menu.addAction("Save Project", self.save_project),
                project_menu.addAction("Save Project As...", self.save_project_as),
            ]
        )
        tools_menu = self.menuBar().addMenu("Tools")
        self.busy_actions.extend(
            [
                tools_menu.addAction("Choose FFmpeg...", self.choose_ffmpeg),
                tools_menu.addAction("Choose FFprobe...", self.choose_ffprobe),
            ]
        )

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(36, 30, 36, 28)
        outer.setSpacing(18)

        header = QHBoxLayout()
        brand = QLabel("AUDIOBOOK FORGE")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch()
        self.count_label = QLabel("0 BOOKS  ·  0 CHAPTERS")
        self.count_label.setObjectName("countLabel")
        header.addWidget(self.count_label)
        outer.addLayout(header)

        intro = QLabel("Turn folders of audio tracks into a batch of polished, chapterized M4Bs.")
        intro.setObjectName("intro")
        outer.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        self.chapter_group = QGroupBox("BOOKS")
        left_layout = QVBoxLayout(self.chapter_group)
        self.file_tree = DropTree()
        self.file_list = self.file_tree
        self.file_tree.setItemDelegateForColumn(TITLE_COLUMN, TreeTitleDelegate(self.file_tree))
        self.file_tree.paths_dropped.connect(self.add_paths)
        self.file_tree.itemChanged.connect(self._tree_item_changed)
        self.file_tree.itemSelectionChanged.connect(self._tree_selection_changed)
        self.file_tree.structure_changed.connect(self._tree_structure_changed)
        left_layout.addWidget(self.file_tree)
        hint = QLabel("Drop folders or audio files. Expand a book and double-click chapter titles to edit.")
        hint.setObjectName("hint")
        left_layout.addWidget(hint)
        row = QHBoxLayout()
        add_button = QPushButton("+  Add files")
        add_button.clicked.connect(self.browse_audio)
        folder_button = QPushButton("Add folder")
        folder_button.clicked.connect(self.browse_folder)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self.remove_selected)
        clear_button = QPushButton("Clear")
        clear_button.setObjectName("quietButton")
        clear_button.clicked.connect(self.clear_files)
        row.addWidget(add_button)
        row.addWidget(folder_button)
        row.addWidget(remove_button)
        row.addWidget(QLabel("Titles:"))
        self.chapter_title_combo = QComboBox()
        self.chapter_title_combo.addItem("Embedded title", CHAPTER_TITLE_SOURCE_EMBEDDED)
        self.chapter_title_combo.addItem("File name", CHAPTER_TITLE_SOURCE_FILENAME)
        self.chapter_title_combo.setToolTip(
            "Choose whether chapter titles come from embedded audio tags or source file names."
        )
        self.chapter_title_combo.currentIndexChanged.connect(self._chapter_title_source_changed)
        row.addWidget(self.chapter_title_combo)
        row.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Natural filename", "Track number", "Manual order"])
        self.sort_combo.currentIndexChanged.connect(self.apply_sort)
        row.addWidget(self.sort_combo)
        row.addStretch()
        row.addWidget(clear_button)
        left_layout.addLayout(row)
        splitter.addWidget(self.chapter_group)

        self.details_group = QGroupBox("BOOK DETAILS")
        details = QGridLayout(self.details_group)
        details.setVerticalSpacing(12)
        details.addWidget(QLabel("Title"), 0, 0)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("The book title")
        details.addWidget(self.title_edit, 0, 1)
        details.addWidget(QLabel("Author"), 1, 0)
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("Author name")
        details.addWidget(self.author_edit, 1, 1)
        self.metadata_edits: dict[str, QLineEdit] = {"title": self.title_edit, "artist": self.author_edit}
        for row, key, label, placeholder in [
            (2, "composer", "Narrator", "Narrator name"),
            (3, "grouping", "Series", "Series name"),
            (4, "series_number", "Series no.", "Optional"),
            (5, "date", "Year", "YYYY"),
            (6, "genre", "Genre", "Optional"),
        ]:
            details.addWidget(QLabel(label), row, 0)
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            self.metadata_edits[key] = edit
            details.addWidget(edit, row, 1)
        details.addWidget(QLabel("Cover image"), 7, 0, Qt.AlignmentFlag.AlignTop)
        cover_row = QVBoxLayout()
        self.cover_drop = CoverDrop()
        self.cover_drop.path_changed.connect(self._cover_changed)
        cover_row.addWidget(self.cover_drop)
        cover_button = QPushButton("Browse image")
        cover_button.clicked.connect(self.browse_cover)
        cover_row.addWidget(cover_button)
        details.addLayout(cover_row, 7, 1)
        details.addWidget(QLabel("Destination"), 8, 0)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose a batch destination folder")
        output_button = QPushButton("Browse")
        output_button.clicked.connect(self.browse_output)
        output_row.addWidget(self.output_edit)
        output_row.addWidget(output_button)
        details.addLayout(output_row, 8, 1)
        self.output_edit.textChanged.connect(self._destination_changed)
        self.output_preview = QLabel("Output path appears here after a book is selected.")
        self.output_preview.setWordWrap(True)
        self.output_preview.setObjectName("hint")
        details.addWidget(self.output_preview, 9, 0, 1, 2)
        details.addWidget(QLabel("Quality"), 10, 0)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["64 kbps  Small", "96 kbps  Standard", "128 kbps  High", "160 kbps  Very High"])
        self.quality_combo.setCurrentIndex(1)
        details.addWidget(self.quality_combo, 10, 1)
        self.quality_combo.currentIndexChanged.connect(self._book_settings_changed)
        details.addWidget(QLabel("Channels"), 11, 0)
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("Auto", "Auto")
        self.channel_combo.addItem("Force mono", "Force mono")
        self.channel_combo.addItem("Force stereo", "Force stereo")
        details.addWidget(self.channel_combo, 11, 1)
        self.channel_combo.currentTextChanged.connect(self._book_settings_changed)
        details.setColumnStretch(1, 1)
        splitter.addWidget(self.details_group)
        splitter.setSizes([620, 400])

        footer = QHBoxLayout()
        self.status_label = QLabel("Ready when you are.")
        self.status_label.setObjectName("status")
        footer.addWidget(self.status_label, 1)
        self.runtime_label = QLabel("Runtime: 00:00:00  |  Estimated output: ~0 MB")
        self.runtime_label.setObjectName("status")
        footer.addWidget(self.runtime_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(180)
        footer.addWidget(self.progress)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("quietButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_conversion)
        footer.addWidget(self.cancel_button)
        self.convert_button = QPushButton("MAKE ALL M4Bs  →")
        self.convert_button.setObjectName("convertButton")
        self.convert_button.clicked.connect(self.convert)
        footer.addWidget(self.convert_button)
        outer.addLayout(footer)

        self.setStyleSheet(STYLESHEET)
        # Keep the complete output hint readable and let the details column
        # establish its usable width from the content rather than the window.
        output_hint_width = self.output_edit.fontMetrics().horizontalAdvance(
            self.output_edit.placeholderText()
        ) + 32
        self.output_edit.setMinimumWidth(output_hint_width)
        for edit in self.metadata_edits.values():
            edit.textChanged.connect(self._book_form_changed)

    def browse_audio(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose audio files", self.settings.value("input_directory", ""), "Audio (*.mp3 *.m4a *.aac *.flac *.wav *.ogg)")
        if paths:
            self.settings.setValue("input_directory", str(Path(paths[0]).parent))
            self.add_paths([Path(path) for path in paths])

    def browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose audiobook folder")
        if path:
            self.settings.setValue("input_directory", path)
            self.add_paths([Path(path)])

    def add_paths(self, paths: list[Path]) -> None:
        self._commit_current_book()
        self._sync_tree()
        groups: list[tuple[Path | None, list[Path]]] = []
        loose_files: list[Path] = []
        for path in paths:
            if path.is_dir():
                groups.append((path, sorted(supported_audio_files(path), key=natural_sort_key)))
            elif path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS:
                loose_files.append(path)
        if loose_files:
            groups.append((None, sorted(loose_files, key=natural_sort_key)))

        existing = {chapter.path for book in self.books for chapter in book.chapters}
        new_books: list[Book] = []
        legacy_target = (
            self.books[0]
            if self._legacy_chapters_assignment and len(self.books) == 1 and not any(source for source, _files in groups)
            else None
        )
        for source, files in groups:
            imported: list[Chapter] = []
            for path in files:
                resolved_path = path.resolve()
                if resolved_path in existing:
                    continue
                try:
                    chapter = probe_audio(resolved_path)
                except ValueError as error:
                    QMessageBox.warning(self, "Could not read audio", str(error))
                    continue
                self._remember_chapter_title(chapter)
                imported.append(chapter)
                existing.add(resolved_path)
            if not imported:
                if files:
                    QMessageBox.warning(
                        self,
                        "No audio tracks found",
                        f"No readable supported audio files were found in {source or 'the selected files'}.",
                    )
                continue
            if legacy_target is not None:
                legacy_target.chapters.extend(imported)
                self._sort_book(legacy_target)
                self._resolve_auto_channels(legacy_target)
                continue
            book = self._book_from_import(imported, source)
            self._resolve_auto_channels(book)
            new_books.append(book)

        self._legacy_chapters_assignment = False
        self.books.extend(new_books)
        self._render_books(new_books[-1].book_id if new_books else self.selected_book_id)

    def _book_from_import(self, chapters: list[Chapter], source: Path | None) -> Book:
        tags = common_tags(chapters)
        source_name = source.name if source else self._loose_group_name(chapters)
        folder_series_number, folder_title = split_leading_series_number(source.name) if source else ("", "")
        tagged_title = tags.get("album", "").strip()
        title = tagged_title or folder_title or source_name
        if folder_series_number:
            _, title_without_number = split_leading_series_number(title)
            if title_without_number != title:
                title = title_without_number
        cover_source = source or self._common_parent(chapters)
        metadata = BookMetadata(
            title=title,
            author=tags.get("albumartist", "") or tags.get("artist", ""),
            narrator=tags.get("composer", ""),
            series_number=folder_series_number,
            year=tags.get("date", ""),
            genre=tags.get("genre", ""),
        )
        book = Book(
            chapters=chapters,
            metadata=metadata,
            cover=find_cover(cover_source) if cover_source else None,
            bitrate=self._default_bitrate(),
            channel_mode=self._default_channel_mode(),
            source_name=source_name,
        )
        self._sort_book(book)
        return book

    @staticmethod
    def _common_parent(chapters: list[Chapter]) -> Path | None:
        parents = {chapter.path.parent for chapter in chapters}
        return next(iter(parents)) if len(parents) == 1 else None

    @staticmethod
    def _loose_group_name(chapters: list[Chapter]) -> str:
        parents = {chapter.path.parent for chapter in chapters}
        if len(parents) == 1:
            return next(iter(parents)).name
        return "Untitled book"

    def _default_bitrate(self) -> int:
        try:
            index = int(self.settings.value("bitrate_index", 1))
        except (TypeError, ValueError):
            index = 1
        return [64, 96, 128, 160][index if index in range(4) else 1]

    def _default_channel_mode(self) -> str:
        return self._normalize_channel_mode(self.settings.value("channel_mode", "Auto"))

    def _resolve_auto_channels(self, book: Book) -> None:
        """Resolve and cache Auto's channel choice while importing the book."""

        ffmpeg = discover_tool(
            "ffmpeg",
            self.settings.value("ffmpeg_path", "") or None,
        )
        book.auto_channel_count = target_channel_count(
            book.chapters,
            "Auto",
            ffmpeg=ffmpeg,
        )
        self._auto_channel_results[book.book_id] = book.auto_channel_count

    @staticmethod
    def _normalize_channel_mode(value: object) -> str:
        mode = str(value)
        if mode == "Preserve source":
            return "Auto"
        return mode if mode in {"Auto", "Force mono", "Force stereo"} else "Auto"

    def _sort_book(self, book: Book) -> None:
        if self.sort_combo.currentIndex() == 0:
            book.chapters.sort(key=lambda chapter: natural_sort_key(chapter.path))
        elif self.sort_combo.currentIndex() == 1:
            book.chapters.sort(key=lambda chapter: (chapter.track_number is None, chapter.track_number or 0, natural_sort_key(chapter.path)))

    def _remember_chapter_title(self, chapter: Chapter) -> None:
        self._embedded_chapter_titles.setdefault(chapter.path, chapter.title)
        if self._use_filename_titles:
            chapter.title = chapter.path.stem

    def _chapter_title_source_changed(self, index: int) -> None:
        use_filename_titles = index == CHAPTER_TITLE_SOURCE_FILENAME
        if use_filename_titles == self._use_filename_titles:
            return
        self._commit_current_book()
        self._sync_tree()
        self._use_filename_titles = use_filename_titles
        for book in self.books:
            for chapter in book.chapters:
                if use_filename_titles:
                    self._embedded_chapter_titles.setdefault(chapter.path, chapter.title)
                    chapter.title = chapter.path.stem
                else:
                    chapter.title = self._embedded_chapter_titles.get(chapter.path, chapter.title)
        self.settings.setValue("chapter_title_source", index)
        self._render_books(self.selected_book_id)

    def clear_files(self) -> None:
        self.books.clear()
        self.selected_book_id = None
        self._pending_cover = None
        self._embedded_chapter_titles.clear()
        self._auto_channel_results.clear()
        self.file_tree.clear()
        self._clear_form()
        self._refresh_count()

    def remove_selected(self) -> None:
        self._commit_current_book()
        selected_items = self.file_tree.selectedItems()
        if not selected_items:
            return
        remove_book_ids: set[str] = set()
        remove_chapters: dict[str, set[Path]] = {}
        for item in selected_items:
            book_item = item.parent() or item
            book_id = str(book_item.data(0, BOOK_ROLE) or "")
            if item.parent() is None:
                remove_book_ids.add(book_id)
            else:
                remove_chapters.setdefault(book_id, set()).add(Path(item.data(1, CHAPTER_PATH_ROLE)))
        remaining: list[Book] = []
        for book in self.books:
            if book.book_id in remove_book_ids:
                continue
            paths = remove_chapters.get(book.book_id, set())
            book.chapters = [chapter for chapter in book.chapters if chapter.path not in paths]
            if book.chapters:
                remaining.append(book)
        self.books = remaining
        for book in self.books:
            book.auto_channel_count = None
        self._auto_channel_results.clear()
        self.selected_book_id = self.books[0].book_id if self.books else None
        self._render_books(self.selected_book_id)

    def _render_books(self, preferred_book_id: str | None = None) -> None:
        expanded = {
            str(self.file_tree.topLevelItem(index).data(0, BOOK_ROLE))
            for index in range(self.file_tree.topLevelItemCount())
            if self.file_tree.topLevelItem(index).isExpanded()
        }
        target_id = preferred_book_id if any(book.book_id == preferred_book_id for book in self.books) else self.selected_book_id
        self.file_tree.blockSignals(True)
        self.file_tree.clear()
        selected_item: QTreeWidgetItem | None = None
        for book in self.books:
            book_item = QTreeWidgetItem()
            book_item.setText(NUMBER_COLUMN, book.metadata.series_number.strip())
            book_item.setText(TITLE_COLUMN, book.display_title)
            book_item.setText(DURATION_COLUMN, self._format_time(sum(chapter.duration for chapter in book.chapters)))
            book_item.setTextAlignment(
                NUMBER_COLUMN,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            book_item.setData(0, BOOK_ROLE, book.book_id)
            book_item.setFlags(book_item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
            book_font = book_item.font(0)
            book_font.setBold(True)
            book_item.setFont(0, book_font)
            book_item.setFont(NUMBER_COLUMN, book_font)
            book_item.setFont(TITLE_COLUMN, book_font)
            book_item.setFont(DURATION_COLUMN, book_font)
            self.file_tree.addTopLevelItem(book_item)
            for index, chapter in enumerate(book.chapters, start=1):
                chapter_item = QTreeWidgetItem(book_item)
                chapter_item.setText(NUMBER_COLUMN, f"{index:02d}")
                chapter_item.setText(TITLE_COLUMN, chapter.title)
                chapter_item.setText(DURATION_COLUMN, self._format_time(chapter.duration))
                chapter_item.setTextAlignment(
                    NUMBER_COLUMN,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                )
                chapter_item.setData(TITLE_COLUMN, CHAPTER_PATH_ROLE, str(chapter.path))
                chapter_item.setData(TITLE_COLUMN, CHAPTER_TITLE_ROLE, chapter.title)
                chapter_item.setData(TITLE_COLUMN, CHAPTER_DURATION_ROLE, chapter.duration)
                chapter_item.setFlags(chapter_item.flags() | Qt.ItemFlag.ItemIsEditable)
            book_item.setExpanded(book.book_id in expanded)
            if book.book_id == target_id:
                selected_item = book_item
        self.file_tree.blockSignals(False)
        self.selected_book_id = target_id if selected_item else (self.books[0].book_id if self.books else None)
        if selected_item:
            self.file_tree.setCurrentItem(selected_item)
        elif self.books:
            self.file_tree.setCurrentItem(self.file_tree.topLevelItem(0))
        else:
            self._clear_form()
        if self.books:
            self._load_selected_book()
        self._refresh_count()

    def _render_chapters(self) -> None:
        """Compatibility alias for the previous single-book UI."""

        self._render_books(self.selected_book_id)

    def _renumber_rows(self) -> None:
        self._render_books(self.selected_book_id)

    def _sync_chapters_from_list(self) -> None:
        self._sync_tree()

    def _sync_tree(self) -> None:
        books_by_id = {book.book_id: book for book in self.books}
        ordered: list[Book] = []
        for index in range(self.file_tree.topLevelItemCount()):
            book_item = self.file_tree.topLevelItem(index)
            book_id = str(book_item.data(0, BOOK_ROLE) or "")
            book = books_by_id.get(book_id)
            if book is None:
                continue
            chapters_by_path = {chapter.path: chapter for chapter in book.chapters}
            ordered_chapters: list[Chapter] = []
            for child_index in range(book_item.childCount()):
                child = book_item.child(child_index)
                path = Path(str(child.data(TITLE_COLUMN, CHAPTER_PATH_ROLE)))
                chapter = chapters_by_path.get(path)
                if chapter is None:
                    continue
                chapter.title = str(child.data(TITLE_COLUMN, CHAPTER_TITLE_ROLE) or child.text(TITLE_COLUMN)).strip()
                if not self._use_filename_titles:
                    self._embedded_chapter_titles[chapter.path] = chapter.title
                ordered_chapters.append(chapter)
            book.chapters = ordered_chapters
            ordered.append(book)
        self.books = ordered
        self._refresh_count()

    def _tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._loading_book or item.parent() is None or column != TITLE_COLUMN:
            return
        previous = self.file_tree.blockSignals(True)
        item.setData(TITLE_COLUMN, CHAPTER_TITLE_ROLE, item.text(TITLE_COLUMN).strip())
        self.file_tree.blockSignals(previous)
        self._sync_tree()

    def _tree_structure_changed(self) -> None:
        self._sync_tree()
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(2)
        self.sort_combo.blockSignals(False)

    def _manual_reorder(self, *_args) -> None:
        self._tree_structure_changed()

    def _chapter_title_changed(self, item: QListWidgetItem) -> None:
        self._tree_item_changed(item, TITLE_COLUMN)

    def apply_sort(self, index: int) -> None:
        self._commit_current_book()
        self._sync_tree()
        if index in (0, 1):
            for book in self.books:
                self._sort_book(book)
        self._render_books(self.selected_book_id)

    def _selected_book(self) -> Book | None:
        if self.selected_book_id is None:
            return None
        return next((book for book in self.books if book.book_id == self.selected_book_id), None)

    @staticmethod
    def _book_id_for_item(item: QTreeWidgetItem | None) -> str | None:
        if item is None:
            return None
        book_item = item.parent() or item
        value = book_item.data(0, BOOK_ROLE)
        return str(value) if value else None

    def _tree_selection_changed(self) -> None:
        item = self.file_tree.currentItem()
        book_id = self._book_id_for_item(item)
        if book_id == self.selected_book_id:
            return
        self._commit_current_book()
        self.selected_book_id = book_id
        self._load_selected_book()

    def _load_selected_book(self) -> None:
        book = self._selected_book()
        self._loading_book = True
        try:
            if book is None:
                self._clear_form()
                return
            values = {
                "title": book.metadata.title,
                "artist": book.metadata.author,
                "composer": book.metadata.narrator,
                "grouping": book.metadata.series,
                "series_number": book.metadata.series_number,
                "date": book.metadata.year,
                "genre": book.metadata.genre,
            }
            for key, edit in self.metadata_edits.items():
                edit.setText(values.get(key, ""))
            self.cover_drop.clear()
            if book.cover:
                self.cover_drop.set_path(book.cover)
            self.quality_combo.setCurrentIndex({64: 0, 96: 1, 128: 2, 160: 3}.get(book.bitrate, 1))
            self._update_auto_channel_label(
                self._auto_channel_results.get(book.book_id, book.auto_channel_count)
            )
            channel_mode = self._normalize_channel_mode(book.channel_mode)
            self.channel_combo.setCurrentIndex(self.channel_combo.findData(channel_mode))
        finally:
            self._loading_book = False
        self._refresh_output_preview()

    def _clear_form(self) -> None:
        self._loading_book = True
        try:
            for edit in self.metadata_edits.values():
                edit.clear()
            self.cover_drop.clear()
            self.quality_combo.setCurrentIndex(1)
            self._update_auto_channel_label(None)
            self.channel_combo.setCurrentIndex(self.channel_combo.findData("Auto"))
        finally:
            self._loading_book = False
        self._refresh_output_preview()

    def _commit_current_book(self) -> None:
        book = self._selected_book()
        if book is None or self._loading_book:
            return
        book.metadata = BookMetadata(
            title=self.title_edit.text().strip(),
            author=self.author_edit.text().strip(),
            narrator=self.metadata_edits["composer"].text().strip(),
            series=self.metadata_edits["grouping"].text().strip(),
            series_number=self.metadata_edits["series_number"].text().strip(),
            year=self.metadata_edits["date"].text().strip(),
            genre=self.metadata_edits["genre"].text().strip(),
        )
        book.cover = self.cover_drop.path.resolve() if self.cover_drop.path else None
        book.bitrate = [64, 96, 128, 160][self.quality_combo.currentIndex()]
        book.channel_mode = self._normalize_channel_mode(self.channel_combo.currentData())

    def _book_form_changed(self, *_args) -> None:
        if self._loading_book:
            return
        self._commit_current_book()
        self._update_book_item()
        self._refresh_output_preview()
        self._refresh_count()

    def _book_settings_changed(self, *_args) -> None:
        self._book_form_changed()

    def _update_auto_channel_label(self, channels: int | None) -> None:
        label = {
            1: "Auto (mono)",
            2: "Auto (stereo)",
        }.get(channels, "Auto")
        previous = self.channel_combo.blockSignals(True)
        self.channel_combo.setItemText(0, label)
        self.channel_combo.blockSignals(previous)

    def _channel_mode_resolved(self, book_id: str, channels: int) -> None:
        if channels not in {1, 2}:
            return
        self._auto_channel_results[book_id] = channels
        for book in self.books:
            if book.book_id == book_id:
                book.auto_channel_count = channels
                break
        if book_id == self.selected_book_id:
            self._update_auto_channel_label(channels)

    def _update_book_item(self) -> None:
        book = self._selected_book()
        if book is None:
            return
        for index in range(self.file_tree.topLevelItemCount()):
            item = self.file_tree.topLevelItem(index)
            if item.data(0, BOOK_ROLE) == book.book_id:
                self.file_tree.blockSignals(True)
                item.setText(NUMBER_COLUMN, book.metadata.series_number.strip())
                item.setText(TITLE_COLUMN, book.display_title)
                self.file_tree.blockSignals(False)
                return

    @staticmethod
    def _format_time(seconds: float) -> str:
        return format_time(seconds)

    def _refresh_count(self) -> None:
        chapter_count = sum(len(book.chapters) for book in self.books)
        self.count_label.setText(f"{len(self.books)} BOOKS  ·  {chapter_count} CHAPTERS")
        total = sum(chapter.duration for book in self.books for chapter in book.chapters)
        estimate = sum(
            estimate_output_bytes(sum(chapter.duration for chapter in book.chapters), book.bitrate)
            for book in self.books
        )
        self.runtime_label.setText(f"Runtime: {self._format_time(total)}  |  Estimated output: ~{estimate / 1_000_000:.0f} MB")

    def _cover_changed(self, path: Path) -> None:
        if self._loading_book:
            return
        self.cover = path.resolve()
        self._refresh_output_preview()

    def browse_cover(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose cover image", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if path:
            self.cover_drop.set_path(Path(path).resolve())

    def choose_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose ffmpeg executable", "", "FFmpeg executable (ffmpeg.exe)")
        if path:
            self.settings.setValue("ffmpeg_path", path)

    def choose_ffprobe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose ffprobe executable", "", "FFprobe executable (ffprobe.exe)")
        if path:
            self.settings.setValue("ffprobe_path", path)

    def _refresh_output_preview(self) -> None:
        book = self._selected_book()
        if book is None:
            self.output_preview.setText("Output path appears here after a book is selected.")
            return
        root_text = self.output_edit.text().strip()
        if not root_text:
            self.output_preview.setText("Choose a destination folder to preview this book's output path.")
            return
        self.output_preview.setText(str(book_output_path(Path(root_text).expanduser(), book.metadata)))

    def _destination_changed(self, value: str) -> None:
        self.destination_root = Path(value).expanduser().resolve() if value.strip() else None
        self._refresh_output_preview()

    def new_project(self) -> None:
        self.clear_files()
        self.output_edit.clear()
        self.destination_root = None
        self.project_path = None

    def save_project(self) -> None:
        if self.project_path is None:
            self.save_project_as()
            return
        self._write_project(self.project_path)

    def save_project_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Audiobook Forge project", "audiobook-project.json", "Audiobook Forge project (*.json)")
        if path:
            project_path = Path(path)
            if self._write_project(project_path):
                self.project_path = project_path

    def _write_project(self, path: Path) -> bool:
        self._commit_current_book()
        self._sync_tree()
        destination = Path(self.output_edit.text().strip()).expanduser() if self.output_edit.text().strip() else None
        try:
            save_batch_project(path, self.books, destination)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Could not save project", str(error))
            return False
        self.status_label.setText(f"Saved project {path.name}")
        return True

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Audiobook Forge project", "", "Audiobook Forge project (*.json)")
        if not path:
            return
        try:
            project_path = Path(path)
            payload = load_project(project_path)

            def project_file(saved_path: str) -> Path:
                candidate = Path(saved_path).expanduser()
                if not candidate.is_absolute():
                    candidate = project_path.parent / candidate
                return candidate.resolve()

            if payload["version"] == 1:
                saved_metadata = payload.get("metadata", {})
                loaded_chapters = [self._chapter_from_payload(item, project_file) for item in payload["chapters"]]
                legacy_metadata = BookMetadata(
                    title=saved_metadata.get("title", ""),
                    author=saved_metadata.get("author", ""),
                    narrator=saved_metadata.get("narrator", ""),
                    series=saved_metadata.get("series", ""),
                    series_number=saved_metadata.get("series_number", ""),
                    year=saved_metadata.get("year", ""),
                    genre=saved_metadata.get("genre", ""),
                )
                legacy_cover = project_file(payload["cover"]) if payload.get("cover") else None
                source_name = legacy_metadata.title or (loaded_chapters[0].path.parent.name if loaded_chapters else "Imported book")
                loaded_books = [
                    Book(
                        chapters=loaded_chapters,
                        metadata=legacy_metadata,
                        cover=legacy_cover,
                        bitrate=payload.get("bitrate", 96),
                        channel_mode=self._normalize_channel_mode(payload.get("channel_mode", "Auto")),
                        source_name=source_name,
                    )
                ]
                legacy_output = project_file(payload["output"]) if payload.get("output") else None
                loaded_destination = legacy_output.parent if legacy_output else None
            else:
                loaded_books = []
                for item in payload["books"]:
                    metadata = item.get("metadata", {})
                    loaded_books.append(
                        Book(
                            chapters=[self._chapter_from_payload(chapter, project_file) for chapter in item["chapters"]],
                            metadata=BookMetadata(
                                title=metadata.get("title", ""),
                                author=metadata.get("author", ""),
                                narrator=metadata.get("narrator", ""),
                                series=metadata.get("series", ""),
                                series_number=metadata.get("series_number", ""),
                                year=metadata.get("year", ""),
                                genre=metadata.get("genre", ""),
                            ),
                            cover=project_file(item["cover"]) if item.get("cover") else None,
                            bitrate=item.get("bitrate", 96),
                            channel_mode=self._normalize_channel_mode(item.get("channel_mode", "Auto")),
                            source_name=item.get("source_name", ""),
                            book_id=item.get("id") or Book().book_id,
                        )
                    )
                loaded_destination = project_file(payload["destination_root"]) if payload.get("destination_root") else None
        except (OSError, KeyError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could not open project", str(error))
            return

        self.books = loaded_books
        self._embedded_chapter_titles.clear()
        self._auto_channel_results.clear()
        for book in self.books:
            for chapter in book.chapters:
                self._remember_chapter_title(chapter)
        self.selected_book_id = self.books[0].book_id if self.books else None
        self.destination_root = loaded_destination
        self.output_edit.setText(str(loaded_destination) if loaded_destination else "")
        self._render_books(self.selected_book_id)
        self.project_path = Path(path)
        missing = [chapter.path for book in self.books for chapter in book.chapters if not chapter.path.is_file()]
        if missing:
            preview = "\n".join(str(item) for item in missing[:5])
            suffix = f"\n…and {len(missing) - 5} more" if len(missing) > 5 else ""
            QMessageBox.warning(
                self,
                "Missing source files",
                "This project references audio files that could not be found:\n"
                f"{preview}{suffix}\n\nRelocate or re-add them before exporting.",
            )

    @staticmethod
    def _chapter_from_payload(item: dict, project_file) -> Chapter:
        return Chapter(
            project_file(item["path"]),
            item["title"],
            float(item["duration"]),
            item.get("track_number"),
            item.get("channels"),
            item.get("sample_rate"),
        )

    def browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose batch destination folder", self.settings.value("output_directory", ""))
        if path:
            self.output_edit.setText(path)
            self.destination_root = Path(path).resolve()
            self.settings.setValue("output_directory", path)
            self._refresh_output_preview()

    def convert(self) -> None:
        self._commit_current_book()
        self._sync_tree()
        if not self.books:
            QMessageBox.warning(self, "No books", "Drop at least one audiobook folder or audio group before exporting.")
            return
        incomplete = [book.display_title for book in self.books if not book.metadata.title.strip() or not book.metadata.author.strip()]
        if incomplete:
            QMessageBox.warning(self, "Missing details", "Add a title and author for every book before exporting.\n\n" + "\n".join(incomplete[:8]))
            return
        missing = [chapter.path for book in self.books for chapter in book.chapters if not chapter.path.is_file()]
        if missing:
            QMessageBox.warning(
                self,
                "Missing source files",
                "One or more source audio files could not be found. "
                "Re-add them or open a corrected project before exporting.",
            )
            return
        missing_covers = [book.cover for book in self.books if book.cover and not book.cover.is_file()]
        if missing_covers:
            QMessageBox.warning(
                self,
                "Missing cover image",
                "One or more selected cover images could not be found. Choose them again or remove them before exporting.",
            )
            return
        if not self.output_edit.text().strip():
            QMessageBox.warning(self, "Missing destination", "Choose a batch destination folder before exporting.")
            return
        destination = Path(self.output_edit.text().strip()).expanduser().resolve()
        if not destination.exists() or not destination.is_dir():
            QMessageBox.warning(self, "Missing destination folder", f"The destination folder does not exist:\n{destination}")
            return
        estimate = sum(
            estimate_output_bytes(sum(chapter.duration for chapter in book.chapters), book.bitrate)
            for book in self.books
        )
        workspace_estimate = int(estimate * 2.2)
        try:
            free_space = shutil.disk_usage(destination).free
        except OSError:
            free_space = workspace_estimate
        if free_space < workspace_estimate:
            choice = QMessageBox.warning(self, "Low disk space", f"The destination may not have enough free space for the output and temporary encoding files.\nEstimated output: {estimate / 1_000_000:.0f} MB", QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if choice != QMessageBox.StandardButton.Ok:
                return
        self._set_exporting(True)
        self.progress.setValue(0)
        books = deepcopy(self.books)
        thread = QThread(self)
        worker = BatchConversionWorker(
            books,
            destination,
            self.settings.value("ffmpeg_path", "") or None,
            self.settings.value("ffprobe_path", "") or None,
        )
        self.thread = thread
        self.worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.update_progress)
        worker.channel_mode_resolved.connect(self._channel_mode_resolved)
        worker.book_finished.connect(self.book_conversion_finished)
        worker.finished.connect(self.conversion_finished)
        worker.failed.connect(self.conversion_failed)
        worker.cancelled.connect(self.conversion_cancelled)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._conversion_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def update_progress(self, value: int, message: str) -> None:
        self.progress.setValue(value)
        self.status_label.setText(message)

    def _set_exporting(self, exporting: bool) -> None:
        self.chapter_group.setEnabled(not exporting)
        self.details_group.setEnabled(not exporting)
        for action in self.busy_actions:
            action.setEnabled(not exporting)
        self.convert_button.setEnabled(not exporting)
        self.cancel_button.setEnabled(exporting)

    def cancel_conversion(self) -> None:
        if self.worker:
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling export...")
            self.worker.cancel()

    def _conversion_thread_finished(self) -> None:
        self.worker = None
        self.thread = None
        self._set_exporting(False)

    def closeEvent(self, event) -> None:
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Export in progress", "Wait for the audiobook export to finish before closing.")
            event.ignore()
            return
        self.settings.setValue("bitrate_index", self.quality_combo.currentIndex())
        self.settings.setValue("channel_mode", self.channel_combo.currentText())
        self.settings.setValue(
            "chapter_title_source",
            CHAPTER_TITLE_SOURCE_FILENAME if self._use_filename_titles else CHAPTER_TITLE_SOURCE_EMBEDDED,
        )
        event.accept()

    def book_conversion_finished(self, book_id: str, output: str) -> None:
        book = next((item for item in self.books if item.book_id == book_id), None)
        title = book.display_title if book else Path(output).stem
        self.status_label.setText(f"Saved {title} to {output}")

    def conversion_finished(self, outputs: list) -> None:
        self.progress.setValue(100)
        self.status_label.setText(f"Saved {len(outputs)} audiobook{'' if len(outputs) == 1 else 's'}")
        QMessageBox.information(self, "Audiobooks ready", f"Created {len(outputs)} audiobook{'' if len(outputs) == 1 else 's'} in:\n{self.output_edit.text()}")

    def conversion_failed(self, message: str, completed: int) -> None:
        self.progress.setValue(0)
        self.status_label.setText(f"Export stopped after {completed} completed book{'' if completed == 1 else 's'}")
        QMessageBox.critical(self, "Could not export batch", message)

    def conversion_cancelled(self, completed: int) -> None:
        self.progress.setValue(0)
        self.status_label.setText(f"Export cancelled after {completed} completed book{'' if completed == 1 else 's'}")


STYLESHEET = """
* { font-family: 'Segoe UI'; font-size: 13px; color: #e8e2d8; }
QMainWindow, #root { background: #151719; }
#brand { color: #d7ff5f; font-size: 14px; font-weight: 700; letter-spacing: 2px; }
#countLabel { color: #8d928c; font-size: 11px; letter-spacing: 1px; }
#intro { color: #aaa9a3; font-size: 19px; }
QGroupBox { border: 1px solid #343936; border-radius: 8px; margin-top: 12px; padding: 18px; font-weight: 700; color: #d7ff5f; letter-spacing: 1px; }
QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 6px; }
QListWidget, QTreeWidget { border: 1px dashed #4c5549; border-radius: 6px; background: #1b1e1c; padding: 8px; }
QHeaderView::section { background: #202621; color: #9da49a; border: none; border-bottom: 1px solid #343936; padding: 6px 8px; }
QListWidget::item, QTreeWidget::item { padding: 8px; border-radius: 4px; color: #d4d5cd; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #344126; color: #f3ffd4; }
QLineEdit { background: #202321; border: 1px solid #414840; border-radius: 4px; padding: 10px; selection-background-color: #718d2c; }
QTreeWidget QLineEdit { padding: 0 6px; }
QLineEdit:focus { border: 1px solid #a7cf44; }
QPushButton { background: #2a302b; border: 1px solid #4a5449; border-radius: 4px; padding: 10px 14px; font-weight: 600; }
QPushButton:hover { background: #374234; border-color: #a7cf44; }
QPushButton:disabled { color: #666b65; }
#quietButton { color: #a3a69f; background: transparent; border-color: transparent; }
#convertButton { background: #d7ff5f; color: #18200e; border: none; padding: 12px 20px; font-weight: 800; }
#convertButton:hover { background: #e5ff91; }
#coverDrop { min-height: 170px; border: 1px dashed #4c5549; border-radius: 6px; background: #1b1e1c; }
#coverPreview { color: #7d847a; font-size: 11px; letter-spacing: 1px; }
#hint, #status { color: #7e857c; }
QProgressBar { border: none; background: #292e2a; height: 5px; border-radius: 2px; }
QProgressBar::chunk { background: #d7ff5f; border-radius: 2px; }
QSplitter::handle { background: #343936; width: 1px; }
"""


def main() -> None:
    app = QApplication([])
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
