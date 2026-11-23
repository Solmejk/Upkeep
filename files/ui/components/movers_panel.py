"""MoversPanel: the collection's biggest risers and fallers since the
previous price update (models.price_history.movers), next to the value
chart on the Collection screen — two groups side by side: by value (the
biggest change in €) and by percentage (cards worth €1+), each a riser
and a faller with a card image and the change in green / red underneath.
Clicking a card opens its popup.
"""

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QBoxLayout, QWidget, QVBoxLayout, QHBoxLayout, QLabel

import scryfall
from models.price_history import PERCENT_MIN_EUR
from ui.components.image_tile import ImageTile
from ui import theme

RISE_COLOR = theme.WIN
FALL_COLOR = theme.LOSS
TEXT_MUTED = theme.MUTED
IMG_W, IMG_H = 112, 156  # card proportions
COLUMN_W = 128  # a little wider than the image, so "−€12.40 (−16%)" fits
GROUP_GAP = 28  # between the "By value" and "By percentage" groups


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

    def __init__(self, result, parent=None):
        """result: models.price_history.movers(...), or None when there
        aren't two price days yet."""
        super().__init__(parent)
        self._groups = None  # the two groups' layout (set_stacked), once there are movers
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        title = QLabel("Biggest movers")
        title.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        outer.addWidget(title)

        if result is None:
            note = _muted("Shown after the next price update — it compares two price days.")
            note.setFixedWidth(2 * COLUMN_W + 16)
            outer.addWidget(note)
            outer.addStretch()
            return

        title.setText(f"Biggest movers since {result['previous_day']}")
        self._groups = QBoxLayout(QBoxLayout.LeftToRight)
        self._groups.setSpacing(GROUP_GAP)
        self._groups.addWidget(self._group("By value", result["by_value"]))
        self._groups.addWidget(self._group(f"By percentage (cards €{PERCENT_MIN_EUR:.0f}+)", result["by_percent"]))
        self._groups.addStretch()
        outer.addLayout(self._groups)
        outer.addStretch()

    def set_stacked(self, stacked: bool):
        """Narrow windows: the two groups one above the other (half as
        wide, twice as tall) instead of side by side."""
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
