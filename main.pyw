from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
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

from audiobook_forge.media import probe_audio, supported_audio_files
from audiobook_forge.models import Chapter, SUPPORTED_AUDIO_EXTENSIONS, natural_sort_key

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
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        event.acceptProposedAction()

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

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                self.set_path(path)
                event.acceptProposedAction()
                return


class ConversionWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(Path)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, chapters: list[Chapter], output: Path, metadata: dict[str, str], cover: Path | None, bitrate: int, channel_mode: str, ffmpeg_path: str | None) -> None:
        super().__init__()
        self.chapters = chapters
        self.files = [chapter.path for chapter in chapters]
        self.output = output
        self.metadata = metadata
        self.cover = cover
        self.bitrate = bitrate
        self.channel_mode = channel_mode
        self.ffmpeg_path = ffmpeg_path
        self.process: subprocess.Popen[str] | None = None
        self.cancel_requested = False

    def cancel(self) -> None:
        self.cancel_requested = True
        if self.process and self.process.poll() is None:
            self.process.terminate()

    @staticmethod
    def _ffmpeg_path(configured: str | None = None) -> str | None:
        bundled = Path(sys.argv[0]).resolve().with_name("ffmpeg.exe")
        candidates = [Path(configured)] if configured else []
        system_path = shutil.which("ffmpeg")
        candidates.extend([bundled, Path(system_path) if system_path else Path()])
        candidates.append(Path.home() / ".spotdl" / "ffmpeg.exe")
        return next((str(path) for path in candidates if path and path.exists()), None)

    @staticmethod
    def _metadata_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", "\\n")

    @staticmethod
    def _concat_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "/").replace("'", "'\\''")

    @staticmethod
    def _format_time(seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        return f"{total_seconds // 3600:02d}:{total_seconds % 3600 // 60:02d}:{total_seconds % 60:02d}"

    def run(self) -> None:
        ffmpeg = self._ffmpeg_path(self.ffmpeg_path)
        if not ffmpeg or not Path(ffmpeg).exists():
            self.failed.emit("ffmpeg was not found. Install ffmpeg and add it to PATH.")
            return

        try:
            with tempfile.TemporaryDirectory(prefix="freedom_m4b_") as temp_dir:
                temp = Path(temp_dir)
                concat_file = temp / "inputs.txt"
                metadata_file = temp / "chapters.txt"
                durations: list[float] = []
                concat_file.write_text("\n".join(f"file '{self._concat_path(path)}'" for path in self.files), encoding="utf-8")
                for index, chapter in enumerate(self.chapters):
                    if self.cancel_requested:
                        self.cancelled.emit()
                        return
                    durations.append(chapter.duration)
                    self.progress.emit(10 + int((index + 1) / len(self.files) * 30), f"Reading chapter {index + 1} of {len(self.files)}")

                timestamp = 0
                chapters = [";FFMETADATA1"]
                for key, value in self.metadata.items():
                    if value:
                        chapters.append(f"{key}={self._metadata_value(value)}")
                for index, (chapter, duration) in enumerate(zip(self.chapters, durations)):
                    start = timestamp
                    timestamp += max(1, round(duration * 1000))
                    chapters.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={timestamp}", f"title={self._metadata_value(chapter.title)}"])
                metadata_file.write_text("\n".join(chapters), encoding="utf-8")
                total_duration = sum(durations)

                command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]
                if self.cover:
                    command += ["-i", str(self.cover)]
                command += ["-i", str(metadata_file), "-map", "0:a:0"]
                if self.cover:
                    command += ["-map", "1:v:0"]
                command += ["-map_metadata", "-1", "-map_metadata", "2" if self.cover else "1", "-map_chapters", "2" if self.cover else "1", "-c:a", "aac", "-b:a", f"{self.bitrate}k"]
                if self.channel_mode == "Force mono":
                    command += ["-ac", "1"]
                elif self.channel_mode == "Force stereo":
                    command += ["-ac", "2"]
                command += ["-nostats", "-progress", "pipe:1"]
                if self.cover:
                    command += ["-c:v", "mjpeg", "-disposition:v:0", "attached_pic"]
                command += [str(self.output)]

                total_label = self._format_time(total_duration)
                self.progress.emit(45, f"Processed audio: 00:00:00 / {total_label}")
                self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                diagnostics: list[str] = []
                if self.process.stdout:
                    for line in self.process.stdout:
                        diagnostics.append(line.rstrip())
                        del diagnostics[:-40]
                        if self.cancel_requested:
                            self.process.terminate()
                            break
                        if line.startswith("out_time_ms=") and total_duration:
                            elapsed = int(line.split("=", 1)[1]) / 1_000_000
                            percent = 45 + int(min(50, elapsed / total_duration * 50))
                            self.progress.emit(percent, f"Processed audio: {self._format_time(elapsed)} / {total_label}")
                exit_code = self.process.wait()
                self.process = None
                if self.cancel_requested:
                    self.output.unlink(missing_ok=True)
                    self.cancelled.emit()
                    return
                if exit_code != 0:
                    detail = "\n".join(line for line in diagnostics if line and not line.startswith(("frame=", "out_", "progress=")))
                    raise RuntimeError(f"FFmpeg failed with exit code {exit_code}.\n\n{detail[-4000:]}")
                if not self.output.exists() or self.output.stat().st_size == 0:
                    raise RuntimeError("FFmpeg finished but the output file was empty.")
                self.progress.emit(100, "Audiobook ready")
                self.finished.emit(self.output)
        except Exception as error:
            self.output.unlink(missing_ok=True)
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("AudiobookForge", "AudiobookForge")
        self.chapters: list[Chapter] = []
        self.cover: Path | None = None
        self.thread: QThread | None = None
        self.worker: ConversionWorker | None = None
        self.setWindowTitle("Freedom / Audiobook Forge")
        self.setMinimumSize(920, 640)
        self._build_ui()

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

        intro = QLabel("Turn a folder of MP3s into one polished, chapterized M4B.")
        intro.setObjectName("intro")
        outer.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        left = QGroupBox("CHAPTERS")
        left_layout = QVBoxLayout(left)
        self.file_list = DropList()
        self.file_list.paths_dropped.connect(self.add_paths)
        self.file_list.itemChanged.connect(self._chapter_title_changed)
        self.file_list.model().rowsMoved.connect(lambda *_: self._sync_chapters_from_list())
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
        row.addStretch()
        row.addWidget(clear_button)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        right = QGroupBox("BOOK DETAILS")
        details = QGridLayout(right)
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
        splitter.addWidget(right)
        splitter.setSizes([470, 380])

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

    def browse_audio(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose audio files", "", "Audio (*.mp3 *.m4a *.aac *.flac *.wav *.ogg)")
        self.add_paths([Path(path) for path in paths])

    def browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose audiobook folder")
        if path:
            self.add_paths([Path(path)])

    def add_paths(self, paths: list[Path]) -> None:
        files = []
        for path in paths:
            files.extend(supported_audio_files(path) if path.is_dir() else [path])
        existing = {chapter.path for chapter in self.chapters}
        imported: list[Chapter] = []
        for path in sorted(files, key=natural_sort_key):
            if path in existing:
                continue
            try:
                chapter = probe_audio(path)
            except ValueError as error:
                QMessageBox.warning(self, "Could not read audio", str(error))
                continue
            self.chapters.append(chapter)
            imported.append(chapter)
            existing.add(path)
        self._render_chapters()
        if imported and not self.title_edit.text().strip():
            self.title_edit.setText(self._common_tag(imported, "album"))

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
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            duration = float(item.data(Qt.ItemDataRole.UserRole + 1) or 0)
            title = item.data(Qt.ItemDataRole.UserRole + 2) or item.text()
            item.setText(f"{index + 1:02d}   {title}   {self._format_time(duration)}")

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

    def _chapter_title_changed(self, item: QListWidgetItem) -> None:
        title = item.text().split("   ", 1)[-1].rsplit("   ", 1)[0].strip()
        item.setData(Qt.ItemDataRole.UserRole + 2, title)
        self._sync_chapters_from_list()

    @staticmethod
    def _format_time(seconds: float) -> str:
        total_seconds = max(0, int(seconds))
        return f"{total_seconds // 3600:02d}:{total_seconds % 3600 // 60:02d}:{total_seconds % 60:02d}"

    @staticmethod
    def _common_tag(chapters: list[Chapter], key: str) -> str:
        return ""

    def _refresh_count(self) -> None:
        self.count_label.setText(f"{len(self.chapters)} CHAPTERS")
        total = sum(chapter.duration for chapter in self.chapters)
        bitrate = [64, 96, 128, 160][self.quality_combo.currentIndex()] if hasattr(self, "quality_combo") else 96
        self.runtime_label.setText(f"Runtime: {self._format_time(total)}  |  Estimated output: ~{total * bitrate * 1000 / 8 / 1_000_000:.0f} MB")

    def browse_cover(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose cover image", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if path:
            self.cover = Path(path)
            self.cover_drop.set_path(self.cover)

    def browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export audiobook", "audiobook.m4b", "M4B audiobook (*.m4b)")
        if path:
            self.output_edit.setText(path)

    def convert(self) -> None:
        self._sync_chapters_from_list()
        if not self.chapters:
            QMessageBox.warning(self, "No chapters", "Drop at least one MP3 file before exporting.")
            return
        if not self.title_edit.text().strip() or not self.author_edit.text().strip():
            QMessageBox.warning(self, "Missing details", "Add a title and author before exporting.")
            return
        output = Path(self.output_edit.text().strip()) if self.output_edit.text().strip() else self.chapters[0].path.with_name(f"{self.title_edit.text().strip()}.m4b")
        if output.exists():
            choice = QMessageBox.question(self, "Output already exists", f"Replace this file?\n{output}", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes:
                return
        self.output_edit.setText(str(output))
        self.convert_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setValue(0)
        self.thread = QThread(self)
        metadata = {key: edit.text().strip() for key, edit in self.metadata_edits.items()}
        metadata["album"] = metadata.get("title", "")
        bitrate = [64, 96, 128, 160][self.quality_combo.currentIndex()]
        self.worker = ConversionWorker(
            self.chapters,
            output,
            metadata,
            self.cover,
            bitrate,
            self.channel_combo.currentText(),
            self.settings.value("ffmpeg_path", "") or None,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda value, message: (self.progress.setValue(value), self.status_label.setText(message)))
        self.worker.finished.connect(self.conversion_finished)
        self.worker.failed.connect(self.conversion_failed)
        self.worker.cancelled.connect(self.conversion_cancelled)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._conversion_thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def cancel_conversion(self) -> None:
        if self.worker:
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling export...")
            self.worker.cancel()

    def _conversion_thread_finished(self) -> None:
        self.worker = None
        self.thread = None
        self.cancel_button.setEnabled(False)

    def closeEvent(self, event) -> None:
        if self.thread and self.thread.isRunning():
            QMessageBox.warning(self, "Export in progress", "Wait for the audiobook export to finish before closing.")
            event.ignore()
            return
        event.accept()

    def conversion_finished(self, output: Path) -> None:
        self.convert_button.setEnabled(True)
        self.status_label.setText(f"Saved to {output.name}")
        QMessageBox.information(self, "Audiobook ready", f"Created:\n{output}")

    def conversion_failed(self, message: str) -> None:
        self.convert_button.setEnabled(True)
        self.progress.setValue(0)
        self.status_label.setText("Export failed")
        QMessageBox.critical(self, "Could not export", message)

    def conversion_cancelled(self) -> None:
        self.convert_button.setEnabled(True)
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
