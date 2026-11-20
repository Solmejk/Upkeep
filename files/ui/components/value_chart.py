"""ValueChart: line chart of a € value over time — the collection's total
on the Collection screen (models.value_history), and one printing's price
in the card popup (models.price_history). Hand-painted like ColorPie: a single orange
series, recessive grid, x spaced by real dates, and a hover crosshair +
tooltip with the date, value, card count and change from the point
before.
"""

import math
from datetime import date

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath, QFontMetrics
from PySide6.QtWidgets import QWidget
from ui import theme

LINE_COLOR = QColor(theme.ACCENT)   # app accent
SURFACE = QColor(theme.PAGE_BG)      # page background (marker ring)
GRID_COLOR = QColor(theme.BORDER)
CROSSHAIR_COLOR = QColor(theme.FAINT)
TEXT_PRIMARY = QColor(theme.TEXT)
TEXT_MUTED = QColor(theme.MUTED)
TOOLTIP_BG = QColor(theme.SURFACE)

PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 64, 16, 34, 24
MARKER_D = 8          # marker diameter
MAX_MARKERS = 40      # more points than this: markers only on hover


def _nice_step(span: float, ticks: int = 4) -> float:
    """A round tick step (1/2/5 × 10^n) giving about `ticks` gridlines."""
    raw = span / max(ticks, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * magnitude:
            return m * magnitude
    return 10 * magnitude


def _euro(value: float, decimals: int = 0) -> str:
    return f"€{value:,.{decimals}f}"


class ValueChart(QWidget):
    def __init__(self, parent=None, title: str = "Collection value",
                 empty_text: str = "No value history yet — refresh the collection to add the first point.",
                 money: bool = True, by_index: bool = False):
        """money: values are € (axis "€1,200", tooltip with % change); False
        for plain numbers like Elo ("1,516", change without %). by_index:
        space points evenly, one step each (e.g. one per game, several on a
        day) instead of by date. Points may carry "label" (tooltip title /
        x labels instead of the date) and "detail" (an extra tooltip line)."""
        super().__init__(parent)
        self._money = money
        self._by_index = by_index
        self._title = title
        self._empty_text = empty_text
        self._points = []  # [{"date", "value", "cards"?}], oldest first
        self._hover = None  # index of the hovered point
        self.setMouseTracking(True)
        self.setMinimumSize(280, 160)

    def setHistory(self, points: list):
        self._points = list(points)
        self._hover = None
        self.update()

    # ----------------------------------------------------------- geometry
    def _plot_rect(self) -> QRectF:
        return QRectF(PAD_LEFT, PAD_TOP, self.width() - PAD_LEFT - PAD_RIGHT,
                      self.height() - PAD_TOP - PAD_BOTTOM)

    def _y_range(self):
        values = [p["value"] for p in self._points]
        lo, hi = min(values), max(values)
        if hi - lo < 1e-9:  # flat line: give it some room (proportional — cards can cost €0.05)
            pad = abs(hi) * 0.2 or 0.01
            lo, hi = lo - pad, hi + pad
        step = _nice_step(hi - lo)
        lo = max(math.floor(lo / step) * step, 0.0)  # € values are never negative
        return lo, math.ceil(hi / step) * step, step

    def _positions(self) -> list:
        """Each point's pixel position — x by real date (gaps show), or one
        even step per point (by_index); y by value."""
        rect = self._plot_rect()
        if self._by_index:
            days = list(range(len(self._points)))
        else:
            days = [date.fromisoformat(p["date"]).toordinal() for p in self._points]
        d0, d1 = days[0], days[-1]
        lo, hi, _ = self._y_range()
        out = []
        for d, p in zip(days, self._points):
            x = rect.center().x() if d1 == d0 else rect.left() + (d - d0) / (d1 - d0) * rect.width()
            y = rect.bottom() - (p["value"] - lo) / (hi - lo) * rect.height()
            out.append(QPointF(x, y))
        return out

    # ------------------------------------------------------------ painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint_title(painter)

        if not self._points:
            self._paint_message(painter, self._empty_text)
            painter.end()
            return

        rect = self._plot_rect()
        lo, hi, step = self._y_range()
        self._paint_grid(painter, rect, lo, hi, step)
        pos = self._positions()
        self._paint_x_labels(painter, rect, pos)

        # The line
        if len(pos) > 1:
            path = QPainterPath(pos[0])
            for pt in pos[1:]:
                path.lineTo(pt)
            painter.setPen(QPen(LINE_COLOR, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        # Markers (all when few, else only the hovered / last one)
        show_all = len(pos) <= MAX_MARKERS
        for i, pt in enumerate(pos):
            if show_all or i == self._hover or i == len(pos) - 1:
                self._paint_marker(painter, pt, big=i == self._hover)

        if len(pos) == 1:
            painter.setPen(TEXT_MUTED)
            painter.drawText(QRectF(rect.left(), pos[0].y() + 10, rect.width(), 20),
                             Qt.AlignHCenter | Qt.AlignTop, "Each refresh adds a point")

        if self._hover is not None:
            self._paint_hover(painter, rect, pos[self._hover], self._hover)
        painter.end()

    def _paint_title(self, painter):
        painter.setPen(TEXT_MUTED)
        title = self._title
        if self._points:
            title += f" · {plural_points(len(self._points))}"
        painter.drawText(QRectF(PAD_LEFT, 4, self.width() - PAD_LEFT, 20),
                         Qt.AlignLeft | Qt.AlignVCenter, title)

    def _paint_message(self, painter, text):
        painter.setPen(TEXT_MUTED)
        painter.drawText(self._plot_rect(), Qt.AlignCenter | Qt.TextWordWrap, text)

    def _paint_grid(self, painter, rect, lo, hi, step):
        decimals = 0 if step >= 1 else 2
        v = lo
        while v <= hi + step / 2:
            y = rect.bottom() - (v - lo) / (hi - lo) * rect.height()
            painter.setPen(QPen(GRID_COLOR, 1))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(TEXT_MUTED)
            painter.drawText(QRectF(0, y - 8, PAD_LEFT - 8, 16),
                             Qt.AlignRight | Qt.AlignVCenter, self._fmt(v, decimals))
            v += step

    def _paint_x_labels(self, painter, rect, pos):
        """First and last date (one label for a single point), skipping
        the last if it would overlap the first."""
        painter.setPen(TEXT_MUTED)
        fm = QFontMetrics(painter.font())
        y = rect.bottom() + 4
        first = self._points[0]["date"]
        if self._by_index:  # e.g. "Start" … "Game 12"
            first = self._points[0].get("label", first)
        if len(pos) == 1:
            painter.drawText(QRectF(pos[0].x() - 50, y, 100, 18), Qt.AlignHCenter, first)
            return
        painter.drawText(QRectF(rect.left(), y, 100, 18), Qt.AlignLeft, first)
        last = self._points[-1]["date"]
        if self._by_index:
            last = self._points[-1].get("label", last).split(" · ")[0]
        if rect.width() > 2 * fm.horizontalAdvance(last) + 20:
            painter.drawText(QRectF(rect.right() - 100, y, 100, 18), Qt.AlignRight, last)

    def _paint_marker(self, painter, pt, big=False):
        d = MARKER_D + (4 if big else 0)
        painter.setPen(QPen(SURFACE, 2))  # surface ring
        painter.setBrush(LINE_COLOR)
        painter.drawEllipse(pt, d / 2, d / 2)

    def _paint_hover(self, painter, rect, pt, i):
        painter.setPen(QPen(CROSSHAIR_COLOR, 1, Qt.DashLine))
        painter.drawLine(QPointF(pt.x(), rect.top()), QPointF(pt.x(), rect.bottom()))
        self._paint_marker(painter, pt, big=True)

        p = self._points[i]
        lines = [p.get("label", p["date"]), self._fmt(p["value"], 2)]
        if p.get("detail"):
            lines.append(p["detail"])
        if "cards" in p:
            lines.append(f"{p['cards']:,} cards")
        if i > 0:
            prev = self._points[i - 1]["value"]
            diff = p["value"] - prev
            sign = "+" if diff >= 0 else "−"
            pct = f" ({sign}{abs(diff) / prev * 100:.1f}%)" if prev and self._money else ""
            since = "the start" if self._by_index and i == 1 else (
                "the last game" if self._by_index else self._points[i - 1]["date"])
            lines.append(f"{sign}{self._fmt(abs(diff), 2)}{pct} since {since}")

        fm = QFontMetrics(painter.font())
        w = max(fm.horizontalAdvance(t) for t in lines) + 20
        h = fm.height() * len(lines) + 12
        x = pt.x() + 12 if pt.x() + 12 + w <= self.width() else pt.x() - 12 - w
        y = min(max(pt.y() - h / 2, 0), self.height() - h)
        box = QRectF(x, y, w, h)
        painter.setPen(QPen(GRID_COLOR, 1))
        painter.setBrush(TOOLTIP_BG)
        painter.drawRoundedRect(box, 6, 6)
        for n, text in enumerate(lines):
            painter.setPen(TEXT_PRIMARY if n == 1 else TEXT_MUTED)  # value stands out
            painter.drawText(QRectF(x + 10, y + 6 + n * fm.height(), w - 20, fm.height()),
                             Qt.AlignLeft | Qt.AlignVCenter, text)

    def _fmt(self, value: float, decimals: int) -> str:
        """€ amounts, or plain whole numbers (Elo)."""
        return _euro(value, decimals) if self._money else f"{value:,.0f}"

    # --------------------------------------------------------------- hover
    def mouseMoveEvent(self, event):
        """Hover snaps to the nearest point by x (a big hit area, not just
        the dot)."""
        if not self._points:
            return
        x = event.position().x()
        pos = self._positions()
        nearest = min(range(len(pos)), key=lambda i: abs(pos[i].x() - x))
        if nearest != self._hover:
            self._hover = nearest
            self.update()

    def leaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self.update()


def plural_points(n: int) -> str:
    return f"{n} point" if n == 1 else f"{n} points"
