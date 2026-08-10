"""Recolors flat-color icon assets (black-on-transparent PNGs) at load
time. Qt Style Sheets have no CSS filter/invert equivalent, so tinting has
to happen in code — this paints over the icon's alpha mask with a solid
color via SourceIn compositing, leaving its shape untouched.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


def tinted_pixmap(path: Path, color: QColor | str, size: int = 16) -> QPixmap:
    """Loads the PNG at `path`, scales it to `size`x`size`, and replaces
    its opaque pixels with `color` (alpha shape preserved)."""
    source = QPixmap(str(path))
    source = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    result = QPixmap(source.size())
    result.fill(Qt.transparent)

    painter = QPainter(result)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(result.rect(), QColor(color))
    painter.end()

    return result


def tinted_icon(path: Path, color: QColor | str, size: int = 16) -> QIcon:
    """tinted_pixmap(), wrapped as a QIcon for setIcon()."""
    return QIcon(tinted_pixmap(path, color, size))
