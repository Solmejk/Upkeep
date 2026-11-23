"""MoversPanel: the collection's biggest risers and fallers
(models.price_history.movers), next to the value chart on the Collection
screen. A dropdown picks the period — since the last price update, the
last week / month / year, or all time — and two groups sit side by side:
by value (the biggest change in €) and by percentage (cards worth €1+),
each a riser and a faller with a card image and the change in green / red
underneath. Clicking a card opens its popup.
"""

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QBoxLayout, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import scryfall
from models import price_history
from models.price_history import PERCENT_MIN_EUR, PERIODS
from ui.components.image_tile import ImageTile
from ui import theme

RISE_COLOR = theme.WIN
FALL_COLOR = theme.LOSS
TEXT_MUTED = theme.MUTED
IMG_W, IMG_H = 140, 196  # card proportions
COLUMN_W = 150  # a little wider than the image, so "−€12.40 (−16%)" fits
GROUP_GAP = 28  # between the "By value" and "By percentage" groups

_session_period = "last"  # the period picked this session (the screen is rebuilt on refreshes)


def _change_text(old: float, new: float) -> str:
    diff = new - old
    sign = "+" if diff >= 0 else "−"
    pct = f" ({sign}{abs(diff) / old * 100:.0f}%)" if old else ""
    return f"{sign}€{abs(diff):,.2f}{pct}"


def _muted(text: str, size: int = 12) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: {size}px; background: transparent;")
    return label


class MoversPanel(QWidget):
    tile_clicked = Signal(dict)  # the mover's collection tile (merged entry)

    def __init__(self, tiles: list, parent=None):
        """tiles: the collection's merged entries (one per printing +
        finish) — ranked for the chosen period by price_history.movers."""
        super().__init__(parent)
        self._tiles = tiles
        self._stacked = False
        self._groups = None  # the two groups' layout (set_stacked), once there are movers

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(10)
        self._title = QLabel("Biggest movers")
        self._title.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        header.addWidget(self._title)
        self._period = QComboBox()
        self._period.setObjectName("sortCombo")
        for key, (label, _) in PERIODS.items():
            self._period.addItem(label, key)
        self._period.setCurrentIndex(max(0, self._period.findData(_session_period)))
        self._period.currentIndexChanged.connect(self._on_period_changed)
        header.addWidget(self._period)
        header.addStretch()
        outer.addLayout(header)

        self._content = QWidget()
        outer.addWidget(self._content)
        outer.addStretch()
        self._show_period()

    def _on_period_changed(self):
        global _session_period
        _session_period = self._period.currentData()
        self._show_period()

    def _show_period(self):
        """(Re)builds the two groups for the selected period."""
        result = price_history.movers(self._tiles, self._period.currentData())
        old = self._content
        self._content = QWidget()
        self.layout().replaceWidget(old, self._content)
        old.hide()  # gone at once — the app's dark widget background would cover the header until deleted
        old.deleteLater()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, 0, 0, 0)
        self._groups = None

        self._period.setVisible(result is not None)
        if result is None:
            self._title.setText("Biggest movers")
            note = _muted("Shown after the next price update — it compares two price days.")
            note.setFixedWidth(2 * COLUMN_W + 16)
            layout.addWidget(note)
            return

        self._title.setText(f"Biggest movers since {result['previous_day']}")
        self._groups = QBoxLayout(QBoxLayout.LeftToRight)
        self._groups.addWidget(self._group("By value", result["by_value"]))
        self._groups.addWidget(self._group(f"By percentage (cards €{PERCENT_MIN_EUR:.0f}+)", result["by_percent"]))
        self._groups.addStretch()
        layout.addLayout(self._groups)
        self.set_stacked(self._stacked)

    def minimumSizeHint(self):
        """As narrow as the stacked layout (one group's width): the panel
        can always stack, so side by side must never set the screen's —
        and so the window's — minimum width."""
        hint = super().minimumSizeHint()
        groups = [self._groups.itemAt(i).widget() for i in range(self._groups.count())] if self._groups else []
        widths = [g.minimumSizeHint().width() for g in groups if g is not None]
        if widths and not self._stacked:
            hint.setWidth(min(hint.width(), max(widths, default=hint.width())))
        return hint

    def set_stacked(self, stacked: bool):
        """Narrow windows: the two groups one above the other (half as
        wide, twice as tall) instead of side by side."""
        self._stacked = stacked
        if self._groups is not None:
            self._groups.setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
            self._groups.setSpacing(10 if stacked else GROUP_GAP)

    def _group(self, heading: str, movers) -> QWidget:
        """A heading over one ranking's riser and faller."""
        riser, faller = movers
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(_muted(heading))
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._column(riser, RISE_COLOR, "No card went up"))
        row.addWidget(self._column(faller, FALL_COLOR, "No card went down"))
        layout.addLayout(row)
        return group

    def _column(self, mover, color: str, none_text: str) -> QWidget:
        """One mover: card image (+ name caption), then the change."""
        column = QWidget()
        column.setMinimumWidth(COLUMN_W)  # grows if the change text needs more
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        if mover is None:
            layout.addWidget(_muted(none_text))
            layout.addStretch()
            return column

        tile_entry, old, new = mover
        card = tile_entry["card"]
        tile = ImageTile(
            scryfall.image_url(card.get("scryfall_id", "")),
            scryfall.card_image_cache_name(card),
            card["name"], tile_entry, width=IMG_W, height=IMG_H, radius=6,
        )
        tile.setToolTip(f"{card['name']}: €{old:,.2f} → €{new:,.2f}")
        tile.clicked.connect(self.tile_clicked.emit)
        tile.request_image_load()
        layout.addWidget(tile, alignment=Qt.AlignHCenter)

        change = QLabel(html.escape(_change_text(old, new)))
        change.setAlignment(Qt.AlignCenter)
        change.setStyleSheet(f"color: {color}; font-weight: bold; background: transparent;")
        layout.addWidget(change)
        return column
