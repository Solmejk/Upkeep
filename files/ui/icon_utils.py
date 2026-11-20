"""Recolors flat-color icon assets (black-on-transparent PNGs) at load
time. Qt Style Sheets have no CSS filter/invert equivalent, so tinting has
to happen in code — this paints over the icon's alpha mask with a solid
color via SourceIn compositing, leaving its shape untouched.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QPen, QPainterPath
from ui import theme


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


def check_icon(color: QColor | str = theme.WIN, size: int = 18) -> QIcon:
    """A drawn checkmark (no asset needed) — e.g. a received purchase.
    color=None gives an empty icon of the same size, so rows with and
    without a check stay aligned."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    if color is not None:
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), size * 0.16, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath(QPointF(size * 0.18, size * 0.52))
        path.lineTo(size * 0.42, size * 0.76)
        path.lineTo(size * 0.84, size * 0.26)
        painter.drawPath(path)
        painter.end()
    return QIcon(pixmap)
