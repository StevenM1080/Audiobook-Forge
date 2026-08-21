from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter


def normalize_cover(source: Path, destination: Path, maximum: int = 1200) -> Path:
    image = QImage(str(source))
    if image.isNull():
        raise ValueError(f"Could not read cover image: {source}")
    scale = min(1.0, maximum / max(image.width(), image.height()))
    scaled = image.scaled(max(1, int(image.width() * scale)), max(1, int(image.height() * scale)), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    size = max(scaled.width(), scaled.height())
    canvas = QImage(size, size, QImage.Format.Format_RGB32)
    canvas.fill(QColor("black"))
    painter = QPainter(canvas)
    painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    if not canvas.save(str(destination), "JPG", 92):
        raise ValueError(f"Could not create normalized cover: {destination}")
    return destination
