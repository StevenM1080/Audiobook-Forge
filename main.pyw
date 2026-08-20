from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from mutagen.mp3 import MP3
from PySide6.QtCore import QObject, QThread, Qt, Signal
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
    QSplitter,
    QVBoxLayout,
    QWidget,
)

AUDIO_EXTENSIONS = {".mp3"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class DropList(QListWidget):
    files_dropped = Signal(list)

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
        audio_paths = [path for path in paths if path.suffix.lower() in AUDIO_EXTENSIONS]
        if audio_paths:
            self.files_dropped.emit(audio_paths)
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

    def __init__(self, files: list[Path], output: Path, title: str, author: str, cover: Path | None) -> None:
        super().__init__()
        self.files = files
        self.output = output
        self.title = title
        self.author = author
        self.cover = cover

    @staticmethod
    def _ffmpeg_path() -> str | None:
        return shutil.which("ffmpeg") or str(Path.home() / ".spotdl" / "ffmpeg.exe")

    @staticmethod
    def _duration(path: Path) -> float:
        return float(MP3(path).info.length)

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
        ffmpeg = self._ffmpeg_path()
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
                for index, path in enumerate(self.files):
                    durations.append(self._duration(path))
                    self.progress.emit(10 + int((index + 1) / len(self.files) * 30), f"Reading chapter {index + 1} of {len(self.files)}")

                timestamp = 0
                chapters = [";FFMETADATA1", f"title={self._metadata_value(self.title)}", f"artist={self._metadata_value(self.author)}", f"album={self._metadata_value(self.title)}"]
                for index, (path, duration) in enumerate(zip(self.files, durations)):
                    start = timestamp
                    timestamp += max(1, round(duration * 1000))
                    chapters.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={timestamp}", f"title={self._metadata_value(path.stem)}"])
                metadata_file.write_text("\n".join(chapters), encoding="utf-8")
                total_duration = sum(durations)

                command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]
                if self.cover:
                    command += ["-i", str(self.cover)]
                command += ["-i", str(metadata_file), "-map", "0:a:0"]
                if self.cover:
                    command += ["-map", "1:v:0"]
                command += ["-map_metadata", "-1", "-map_metadata", "2" if self.cover else "1", "-map_chapters", "2" if self.cover else "1", "-c:a", "aac", "-b:a", "96k", "-nostats", "-progress", "pipe:1"]
                if self.cover:
                    command += ["-c:v", "mjpeg", "-disposition:v:0", "attached_pic"]
                command += [str(self.output)]

                total_label = self._format_time(total_duration)
                self.progress.emit(45, f"Processed audio: 00:00:00 / {total_label}")
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if process.stdout:
                    for line in process.stdout:
                        if line.startswith("out_time_ms=") and total_duration:
                            elapsed = int(line.split("=", 1)[1]) / 1_000_000
                            percent = 45 + int(min(50, elapsed / total_duration * 50))
                            self.progress.emit(percent, f"Processed audio: {self._format_time(elapsed)} / {total_label}")
                if process.wait() != 0:
                    raise RuntimeError("ffmpeg could not create the M4B file.")
                self.progress.emit(100, "Audiobook ready")
                self.finished.emit(self.output)
        except Exception as error:
            self.failed.emit(str(error))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.files: list[Path] = []
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
        self.file_list.files_dropped.connect(self.add_files)
        left_layout.addWidget(self.file_list)
        hint = QLabel("Drop MP3 files here. Drag rows to reorder.")
        hint.setObjectName("hint")
        left_layout.addWidget(hint)
        row = QHBoxLayout()
        add_button = QPushButton("+  Add MP3s")
        add_button.clicked.connect(self.browse_audio)
        clear_button = QPushButton("Clear")
        clear_button.setObjectName("quietButton")
        clear_button.clicked.connect(self.clear_files)
        row.addWidget(add_button)
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
        details.addWidget(QLabel("Cover image"), 2, 0, Qt.AlignmentFlag.AlignTop)
        cover_row = QVBoxLayout()
        self.cover_drop = CoverDrop()
        cover_row.addWidget(self.cover_drop)
        cover_button = QPushButton("Browse image")
        cover_button.clicked.connect(self.browse_cover)
        cover_row.addWidget(cover_button)
        details.addLayout(cover_row, 2, 1)
        details.addWidget(QLabel("Export to"), 3, 0)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose an output .m4b file")
        output_button = QPushButton("Browse")
        output_button.clicked.connect(self.browse_output)
        output_row.addWidget(self.output_edit)
        output_row.addWidget(output_button)
        details.addLayout(output_row, 3, 1)
        details.setColumnStretch(1, 1)
        splitter.addWidget(right)
        splitter.setSizes([470, 380])

        footer = QHBoxLayout()
        self.status_label = QLabel("Ready when you are.")
        self.status_label.setObjectName("status")
        footer.addWidget(self.status_label, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(180)
        footer.addWidget(self.progress)
        self.convert_button = QPushButton("MAKE M4B  →")
        self.convert_button.setObjectName("convertButton")
        self.convert_button.clicked.connect(self.convert)
        footer.addWidget(self.convert_button)
        outer.addLayout(footer)

        self.setStyleSheet(STYLESHEET)

    def browse_audio(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose MP3 files", "", "MP3 audio (*.mp3)")
        self.add_files([Path(path) for path in paths])

    def add_files(self, paths: list[Path]) -> None:
        existing = set(self.files)
        for path in paths:
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS and path not in existing:
                self.files.append(path)
                item = QListWidgetItem(f"{len(self.files):02d}   {path.stem}")
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.file_list.addItem(item)
                existing.add(path)
        self._refresh_count()

    def clear_files(self) -> None:
        self.files.clear()
        self.file_list.clear()
        self._refresh_count()

    def _refresh_count(self) -> None:
        self.count_label.setText(f"{len(self.files)} CHAPTERS")

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
        self.files = [self.file_list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.file_list.count())]
        if not self.files:
            QMessageBox.warning(self, "No chapters", "Drop at least one MP3 file before exporting.")
            return
        if not self.title_edit.text().strip() or not self.author_edit.text().strip():
            QMessageBox.warning(self, "Missing details", "Add a title and author before exporting.")
            return
        output = Path(self.output_edit.text().strip()) if self.output_edit.text().strip() else self.files[0].with_name(f"{self.title_edit.text().strip()}.m4b")
        self.output_edit.setText(str(output))
        self.convert_button.setEnabled(False)
        self.progress.setValue(0)
        self.thread = QThread(self)
        self.worker = ConversionWorker(self.files, output, self.title_edit.text().strip(), self.author_edit.text().strip(), self.cover)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(lambda value, message: (self.progress.setValue(value), self.status_label.setText(message)))
        self.worker.finished.connect(self.conversion_finished)
        self.worker.failed.connect(self.conversion_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._conversion_thread_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _conversion_thread_finished(self) -> None:
        self.worker = None
        self.thread = None

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
