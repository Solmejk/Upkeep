"""ManaCurveChart: a deck's mana curve as a small bar chart — one bar per
mana value (0 … 7+), bar height = how many nonland cards have it. Shown in
the deck detail header (see deck_stats.mana_curve for the counting).

One series, so one color and no legend (the title under it names it); counts and
axis labels are in text colors, not the bar color; 4px rounded bar tops
anchored square to the baseline; 2px gaps; hover shows a tooltip.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPainterPath, QFont
from PySide6.QtWidgets import QWidget, QToolTip

from card_fields import plural

BAR_COLOR = QColor("#e8a838")        # app accent
BAR_HOVER_COLOR = QColor("#f5c46a")  # same as the accent buttons' hover
TEXT_COLOR = QColor("#e8e8e8")
MUTED_COLOR = QColor("#888888")
BASELINE_COLOR = QColor("#2d2d2d")

BAR_RADIUS = 4
BAR_GAP = 2
MAX_BAR_WIDTH = 28
COUNT_HEIGHT = 14   # room above the tallest bar for its count
AXIS_HEIGHT = 16    # mana value labels below the baseline
TITLE_HEIGHT = 18   # title, under the axis labels


class ManaCurveChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._counts = []   # cards per mana value; last bucket is "N+"
        self._hovered = None
        self.setMouseTracking(True)
        self.setFixedSize(280, 120)

    def set_counts(self, counts: list[int]):
        """counts[i] = nonland cards with mana value i; the last entry
        collects everything at or above its index (labelled "N+")."""
        self._counts = list(counts)
        self._hovered = None
        self.update()

    # ---------------------------------------------------------- geometry

    def _baseline(self) -> float:
        return self.height() - TITLE_HEIGHT - AXIS_HEIGHT

    def _label(self, i: int) -> str:
        return f"{i}+" if i == len(self._counts) - 1 else str(i)

    def _bar_rects(self) -> list[QRectF]:
        """One rect per bucket (zero-height for empty buckets), bars
        centred in equal-width slots across the widget."""
        n = len(self._counts)
        if not n:
            return []
        top = COUNT_HEIGHT
        baseline = self._baseline()
        slot = self.width() / n
        bar_width = min(MAX_BAR_WIDTH, slot - BAR_GAP)
        peak = max(self._counts) or 1
        rects = []
        for i, count in enumerate(self._counts):
            height = (baseline - top) * count / peak
            x = i * slot + (slot - bar_width) / 2
            rects.append(QRectF(x, baseline - height, bar_width, height))
        return rects

    # ----------------------------------------------------------- painting

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        title_font = QFont(self.font())
        title_font.setPointSize(9)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(TEXT_COLOR)
        painter.drawText(QRectF(0, self.height() - TITLE_HEIGHT, self.width(), TITLE_HEIGHT),
                         Qt.AlignHCenter | Qt.AlignBottom, "Mana curve")

        baseline = self._baseline()
        painter.setPen(BASELINE_COLOR)
        painter.drawLine(QPointF(0, baseline), QPointF(self.width(), baseline))

        small = QFont(self.font())
        small.setPointSize(8)
        painter.setFont(small)
        slot = self.width() / max(1, len(self._counts))
        for i, (count, rect) in enumerate(zip(self._counts, self._bar_rects())):
            if count:
                painter.setPen(Qt.NoPen)
                painter.setBrush(BAR_HOVER_COLOR if i == self._hovered else BAR_COLOR)
                painter.drawPath(_rounded_top_bar(rect, BAR_RADIUS))
                painter.setPen(TEXT_COLOR)
                painter.drawText(QRectF(i * slot, rect.top() - COUNT_HEIGHT, slot, COUNT_HEIGHT),
                                 Qt.AlignHCenter | Qt.AlignBottom, str(count))
            painter.setPen(MUTED_COLOR)
            painter.drawText(QRectF(i * slot, baseline + 2, slot, AXIS_HEIGHT - 2),
                             Qt.AlignHCenter | Qt.AlignTop, self._label(i))
        painter.end()

    # ------------------------------------------------------------- hover

    def mouseMoveEvent(self, event):
        """Hover anywhere in a bar's column (bigger than the bar itself):
        lighten the bar and show its count as a tooltip."""
        n = len(self._counts)
        if not n:
            return
        i = min(n - 1, max(0, int(event.position().x() / (self.width() / n))))
        if i != self._hovered:
            self._hovered = i
            self.update()
        count = self._counts[i]
        value = f"mana value {self._label(i)}"
        QToolTip.showText(event.globalPosition().toPoint(),
                          f"{plural(count, 'card')} with {value}", self)

    def leaveEvent(self, event):
        self._hovered = None
        QToolTip.hideText()
        self.update()


def _rounded_top_bar(rect: QRectF, radius: float) -> QPainterPath:
    """A bar with rounded top corners and a square bottom on the baseline."""
    r = min(radius, rect.width() / 2, rect.height())
    path = QPainterPath()
    path.moveTo(rect.left(), rect.bottom())
    path.lineTo(rect.left(), rect.top() + r)
    path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
    path.lineTo(rect.right() - r, rect.top())
    path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
    path.lineTo(rect.right(), rect.bottom())
    path.closeSubpath()
    return path
