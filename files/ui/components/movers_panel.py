"""MoversPanel: the collection's biggest riser and faller since the
previous price update (models.price_history.movers), next to the value
chart on the Collection screen — a small card image each, with the
change in green / red underneath. Clicking a card opens its popup.
"""

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

import scryfall
from ui.components.image_tile import ImageTile

RISE_COLOR = "#4caf50"  # same green as "free" on the Availability screen
FALL_COLOR = "#d9534f"  # same red as "unowned"
TEXT_MUTED = "#888888"
IMG_W, IMG_H = 96, 134  # card proportions
COLUMN_W = 124  # wider than the image, so "−€12.40 (−16%)" fits


def _change_text(old: float, new: float) -> str:
    diff = new - old
    sign = "+" if diff >= 0 else "−"
    pct = f" ({sign}{abs(diff) / old * 100:.0f}%)" if old else ""
    return f"{sign}€{abs(diff):,.2f}{pct}"


class MoversPanel(QWidget):
    tile_clicked = Signal(dict)  # the mover's collection tile (merged entry)

    def __init__(self, result, parent=None):
        """result: models.price_history.movers(...) — (riser, faller,
        previous_day), or None when there aren't two price days yet."""
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        title = QLabel("Biggest movers")
        title.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent;")
        outer.addWidget(title)

        if result is None:
            note = QLabel("Shown after the next price update — it compares two price days.")
            note.setWordWrap(True)
            note.setFixedWidth(2 * COLUMN_W + 16)
            note.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
            outer.addWidget(note)
            outer.addStretch()
            return

        riser, faller, prev_day = result
        title.setText(f"Biggest movers since {prev_day}")
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self._column(riser, RISE_COLOR, "No card went up"))
        row.addWidget(self._column(faller, FALL_COLOR, "No card went down"))
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch()

    def _column(self, mover, color: str, none_text: str) -> QWidget:
        """One mover: card image (+ name caption), then the change."""
        column = QWidget()
        column.setMinimumWidth(COLUMN_W)  # grows if the change text needs more
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        if mover is None:
            label = QLabel(none_text)
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; background: transparent;")
            layout.addWidget(label)
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
