from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
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
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from audiobook_forge.exporter import ExportCancelled, ExportEngine, format_time, metadata_value
from audiobook_forge.media import common_tags, probe_audio, supported_audio_files
from audiobook_forge.models import (
    BookMetadata,
    Chapter,
    SUPPORTED_AUDIO_EXTENSIONS,
    estimate_output_bytes,
    natural_sort_key,
    safe_output_stem,
)
from audiobook_forge.project_io import load_project, save_project

AUDIO_EXTENSIONS = SUPPORTED_AUDIO_EXTENSIONS
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


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


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings if settings is not None else QSettings("AudiobookForge", "AudiobookForge")
        self.chapters: list[Chapter] = []
        self.cover: Path | None = None
        self.thread: QThread | None = None
        self.worker: ConversionWorker | None = None
        self.project_path: Path | None = None
        self.busy_actions = []
        self.setWindowTitle("Audiobook Forge")
        self._build_ui()
        self._build_menu()
        self._restore_settings()

    def _restore_settings(self) -> None:
        # Geometry is intentionally session-local. Remove the legacy value so
        # older squished layouts cannot be resurrected by a future migration.
        self.settings.remove("window_geometry")
        try:
            bitrate_index = int(self.settings.value("bitrate_index", 1))
        except (TypeError, ValueError):
            bitrate_index = 1
        self.quality_combo.setCurrentIndex(bitrate_index if bitrate_index in range(4) else 1)
        self.channel_combo.setCurrentText(self.settings.value("channel_mode", "Preserve source"))

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
        self.count_label = QLabel("0 CHAPTERS")
        self.count_label.setObjectName("countLabel")
        header.addWidget(self.count_label)
        outer.addLayout(header)

        intro = QLabel("Turn a folder of audio tracks into one polished, chapterized M4B.")
        intro.setObjectName("intro")
        outer.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        self.chapter_group = QGroupBox("CHAPTERS")
        left_layout = QVBoxLayout(self.chapter_group)
        self.file_list = DropList()
        self.file_list.paths_dropped.connect(self.add_paths)
        self.file_list.itemChanged.connect(self._chapter_title_changed)
        self.file_list.model().rowsMoved.connect(self._manual_reorder)
        left_layout.addWidget(self.file_list)
        hint = QLabel("Drop audio files or a folder. Double-click titles to edit.")
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
        details.addWidget(QLabel("Export to"), 8, 0)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose an output .m4b file")
        output_button = QPushButton("Browse")
        output_button.clicked.connect(self.browse_output)
        output_row.addWidget(self.output_edit)
        output_row.addWidget(output_button)
        details.addLayout(output_row, 8, 1)
        details.addWidget(QLabel("Quality"), 9, 0)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["64 kbps  Small", "96 kbps  Standard", "128 kbps  High", "160 kbps  Very High"])
        self.quality_combo.setCurrentIndex(1)
        details.addWidget(self.quality_combo, 9, 1)
        self.quality_combo.currentIndexChanged.connect(self._refresh_count)
        details.addWidget(QLabel("Channels"), 10, 0)
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Preserve source", "Force mono", "Force stereo"])
        details.addWidget(self.channel_combo, 10, 1)
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
        self.convert_button = QPushButton("MAKE M4B  →")
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
        self._sync_chapters_from_list()
        files = []
        for path in paths:
            if path.is_dir():
                files.extend(supported_audio_files(path))
            elif path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS:
                files.append(path)
        existing = {chapter.path for chapter in self.chapters}
        imported: list[Chapter] = []
        for path in sorted(files, key=natural_sort_key):
            resolved_path = path.resolve()
            if resolved_path in existing:
                continue
            try:
                chapter = probe_audio(resolved_path)
            except ValueError as error:
                QMessageBox.warning(self, "Could not read audio", str(error))
                continue
            self.chapters.append(chapter)
            imported.append(chapter)
            existing.add(resolved_path)
        if self.sort_combo.currentIndex() == 0:
            self.chapters.sort(key=lambda chapter: natural_sort_key(chapter.path))
        elif self.sort_combo.currentIndex() == 1:
            self.chapters.sort(
                key=lambda chapter: (
                    chapter.track_number is None,
                    chapter.track_number or 0,
                    natural_sort_key(chapter.path),
                )
            )
        self._render_chapters()
        if imported:
            tags = common_tags(imported)
            candidates = {
                "title": tags.get("album", ""),
                "author": tags.get("albumartist", tags.get("artist", "")),
                "composer": tags.get("composer", ""),
                "date": tags.get("date", ""),
                "genre": tags.get("genre", ""),
            }
            edits = {"title": self.title_edit, "author": self.author_edit, "composer": self.metadata_edits["composer"], "date": self.metadata_edits["date"], "genre": self.metadata_edits["genre"]}
            for key, value in candidates.items():
                if value and not edits[key].text().strip():
                    edits[key].setText(value)

    def clear_files(self) -> None:
        self.chapters.clear()
        self.file_list.clear()
        self._refresh_count()

    def remove_selected(self) -> None:
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.file_list.selectedItems()}
        self.chapters = [chapter for chapter in self.chapters if chapter.path not in selected]
        self._render_chapters()

    def _render_chapters(self) -> None:
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for chapter in self.chapters:
            item = QListWidgetItem()
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setText(chapter.title)
            item.setData(Qt.ItemDataRole.UserRole, chapter.path)
            item.setData(Qt.ItemDataRole.UserRole + 1, chapter.duration)
            item.setData(Qt.ItemDataRole.UserRole + 2, chapter.title)
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)
        self._renumber_rows()
        self._refresh_count()

    def _renumber_rows(self) -> None:
        previous = self.file_list.blockSignals(True)
        try:
            for index in range(self.file_list.count()):
                item = self.file_list.item(index)
                duration = float(item.data(Qt.ItemDataRole.UserRole + 1) or 0)
                title = item.data(Qt.ItemDataRole.UserRole + 2) or item.text()
                item.setText(f"{index + 1:02d}   {title}   {self._format_time(duration)}")
        finally:
            self.file_list.blockSignals(previous)

    def _sync_chapters_from_list(self) -> None:
        chapters_by_path = {chapter.path: chapter for chapter in self.chapters}
        ordered = []
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            path = item.data(Qt.ItemDataRole.UserRole)
            chapter = chapters_by_path[path]
            chapter.title = str(item.data(Qt.ItemDataRole.UserRole + 2) or item.text()).strip()
            ordered.append(chapter)
        self.chapters = ordered
        self._renumber_rows()
        self._refresh_count()

    def apply_sort(self, index: int) -> None:
        self._sync_chapters_from_list()
        if index == 0:
            self.chapters.sort(key=lambda chapter: natural_sort_key(chapter.path))
        elif index == 1:
            self.chapters.sort(key=lambda chapter: (chapter.track_number is None, chapter.track_number or 0, natural_sort_key(chapter.path)))
        self._render_chapters()

    def _manual_reorder(self, *_args) -> None:
        self._sync_chapters_from_list()
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(2)
        self.sort_combo.blockSignals(False)

    def _chapter_title_changed(self, item: QListWidgetItem) -> None:
        title = item.text().split("   ", 1)[-1].rsplit("   ", 1)[0].strip()
        item.setData(Qt.ItemDataRole.UserRole + 2, title)
        self._sync_chapters_from_list()

    @staticmethod
    def _format_time(seconds: float) -> str:
        return format_time(seconds)

    def _refresh_count(self) -> None:
        self.count_label.setText(f"{len(self.chapters)} CHAPTERS")
        total = sum(chapter.duration for chapter in self.chapters)
        bitrate = [64, 96, 128, 160][self.quality_combo.currentIndex()] if hasattr(self, "quality_combo") else 96
        estimate = estimate_output_bytes(total, bitrate)
        self.runtime_label.setText(f"Runtime: {self._format_time(total)}  |  Estimated output: ~{estimate / 1_000_000:.0f} MB")

    def _cover_changed(self, path: Path) -> None:
        self.cover = path.resolve()

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

    def new_project(self) -> None:
        self.clear_files()
        for edit in self.metadata_edits.values():
            edit.clear()
        self.cover = None
        self.cover_drop.clear()
        self.output_edit.clear()
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
        self._sync_chapters_from_list()
        metadata = BookMetadata(
            title=self.title_edit.text().strip(),
            author=self.author_edit.text().strip(),
            narrator=self.metadata_edits["composer"].text().strip(),
            series=self.metadata_edits["grouping"].text().strip(),
            series_number=self.metadata_edits["series_number"].text().strip(),
            year=self.metadata_edits["date"].text().strip(),
            genre=self.metadata_edits["genre"].text().strip(),
        )
        bitrate = [64, 96, 128, 160][self.quality_combo.currentIndex()]
        try:
            save_project(
                path,
                self.chapters,
                metadata,
                self.cover,
                Path(self.output_edit.text()) if self.output_edit.text() else None,
                bitrate,
                self.channel_combo.currentText(),
            )
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
            saved_metadata = payload.get("metadata", {})

            def project_file(saved_path: str) -> Path:
                candidate = Path(saved_path).expanduser()
                if not candidate.is_absolute():
                    candidate = project_path.parent / candidate
                return candidate.resolve()

            loaded_chapters = [
                Chapter(
                    project_file(item["path"]),
                    item["title"],
                    float(item["duration"]),
                    item.get("track_number"),
                    item.get("channels"),
                    item.get("sample_rate"),
                )
                for item in payload["chapters"]
            ]
            loaded_cover = project_file(payload["cover"]) if payload.get("cover") else None
            loaded_output = str(project_file(payload["output"])) if payload.get("output") else ""
            loaded_bitrate = {64: 0, 96: 1, 128: 2, 160: 3}.get(
                payload.get("bitrate", 96), 1
            )
            loaded_channel_mode = payload.get("channel_mode", "Preserve source")
        except (OSError, KeyError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "Could not open project", str(error))
            return

        self.chapters = loaded_chapters
        self._render_chapters()
        try:
            self.title_edit.setText(saved_metadata.get("title", ""))
            self.author_edit.setText(saved_metadata.get("author", ""))
            for key, metadata_key in {"composer": "narrator", "grouping": "series", "series_number": "series_number", "date": "year", "genre": "genre"}.items():
                self.metadata_edits[key].setText(saved_metadata.get(metadata_key, ""))
        except (AttributeError, TypeError) as error:
            QMessageBox.critical(self, "Could not open project", str(error))
            return
        self.cover = loaded_cover
        if self.cover and self.cover.is_file():
            self.cover_drop.set_path(self.cover)
        else:
            self.cover_drop.clear()
        self.output_edit.setText(loaded_output)
        self.quality_combo.setCurrentIndex(loaded_bitrate)
        self.channel_combo.setCurrentText(loaded_channel_mode)
        self.project_path = Path(path)
        missing = [chapter.path for chapter in self.chapters if not chapter.path.is_file()]
        if missing:
            preview = "\n".join(str(item) for item in missing[:5])
            suffix = f"\n…and {len(missing) - 5} more" if len(missing) > 5 else ""
            QMessageBox.warning(
                self,
                "Missing source files",
                "This project references audio files that could not be found:\n"
                f"{preview}{suffix}\n\nRelocate or re-add them before exporting.",
            )

    def browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export audiobook", self.settings.value("output_directory", "audiobook.m4b"), "M4B audiobook (*.m4b)")
        if path:
            self.output_edit.setText(path)
            self.settings.setValue("output_directory", str(Path(path).parent))

    def convert(self) -> None:
        self._sync_chapters_from_list()
        if not self.chapters:
            QMessageBox.warning(self, "No chapters", "Drop at least one audio file before exporting.")
            return
        if not self.title_edit.text().strip() or not self.author_edit.text().strip():
            QMessageBox.warning(self, "Missing details", "Add a title and author before exporting.")
            return
        missing = [chapter.path for chapter in self.chapters if not chapter.path.is_file()]
        if missing:
            QMessageBox.warning(
                self,
                "Missing source files",
                "One or more source audio files could not be found. "
                "Re-add them or open a corrected project before exporting.",
            )
            return
        if self.cover and not self.cover.is_file():
            QMessageBox.warning(
                self,
                "Missing cover image",
                "The selected cover image could not be found. Choose it again or start a new project.",
            )
            return
        output = (
            Path(self.output_edit.text().strip()).expanduser()
            if self.output_edit.text().strip()
            else self.chapters[0].path.with_name(
                f"{safe_output_stem(self.title_edit.text())}.m4b"
            )
        )
        if not output.suffix:
            output = output.with_suffix(".m4b")
        elif output.suffix.casefold() != ".m4b":
            QMessageBox.warning(
                self,
                "Invalid output type",
                "Audiobook Forge exports .m4b files. Choose a filename ending in .m4b.",
            )
            return
        if not output.parent.exists():
            QMessageBox.warning(
                self,
                "Missing output folder",
                f"The output folder does not exist:\n{output.parent}",
            )
            return
        output = output.resolve()
        if output.exists():
            choice = QMessageBox.question(self, "Output already exists", f"Replace this file?\n{output}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                return
        bitrate = [64, 96, 128, 160][self.quality_combo.currentIndex()]
        estimate = estimate_output_bytes(sum(chapter.duration for chapter in self.chapters), bitrate)
        workspace_estimate = int(estimate * 2.2)
        try:
            free_space = shutil.disk_usage(output.parent.resolve()).free
        except OSError:
            free_space = workspace_estimate
        if free_space < workspace_estimate:
            choice = QMessageBox.warning(self, "Low disk space", f"The destination may not have enough free space for the output and temporary encoding files.\nEstimated output: {estimate / 1_000_000:.0f} MB", QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            if choice != QMessageBox.StandardButton.Ok:
                return
        self.output_edit.setText(str(output))
        self._set_exporting(True)
        self.progress.setValue(0)
        chapters = [
            Chapter(
                chapter.path,
                chapter.title,
                chapter.duration,
                chapter.track_number,
                chapter.channels,
                chapter.sample_rate,
            )
            for chapter in self.chapters
        ]
        thread = QThread(self)
        metadata = {key: edit.text().strip() for key, edit in self.metadata_edits.items()}
        metadata["album"] = metadata.get("title", "")
        metadata["album_artist"] = metadata.get("artist", "")
        worker = ConversionWorker(
            chapters,
            output,
            metadata,
            self.cover,
            bitrate,
            self.channel_combo.currentText(),
            self.settings.value("ffmpeg_path", "") or None,
            self.settings.value("ffprobe_path", "") or None,
        )
        self.thread = thread
        self.worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.update_progress)
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
        event.accept()

    def conversion_finished(self, output: Path) -> None:
        self.status_label.setText(f"Saved to {output.name}")
        QMessageBox.information(self, "Audiobook ready", f"Created:\n{output}")

    def conversion_failed(self, message: str) -> None:
        self.progress.setValue(0)
        self.status_label.setText("Export failed")
        QMessageBox.critical(self, "Could not export", message)

    def conversion_cancelled(self) -> None:
        self.progress.setValue(0)
        self.status_label.setText("Export cancelled")


STYLESHEET = """
* { font-family: 'Segoe UI'; font-size: 13px; color: #e8e2d8; }
QMainWindow, #root { background: #151719; }
#brand { color: #d7ff5f; font-size: 14px; font-weight: 700; letter-spacing: 2px; }
#countLabel { color: #8d928c; font-size: 11px; letter-spacing: 1px; }
#intro { color: #aaa9a3; font-size: 19px; }
QGroupBox { border: 1px solid #343936; border-radius: 8px; margin-top: 12px; padding: 18px; font-weight: 700; color: #d7ff5f; letter-spacing: 1px; }
QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 6px; }
QListWidget { border: 1px dashed #4c5549; border-radius: 6px; background: #1b1e1c; padding: 8px; }
QListWidget::item { padding: 10px 8px; border-radius: 4px; color: #d4d5cd; }
QListWidget::item:selected { background: #344126; color: #f3ffd4; }
QLineEdit { background: #202321; border: 1px solid #414840; border-radius: 4px; padding: 10px; selection-background-color: #718d2c; }
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
