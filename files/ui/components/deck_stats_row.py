"""DeckStatsRow: a deck's statistics side by side — mana curve, color
balance pie, mana production pie (each titled underneath), optionally
with the "Avg. mana value (nonland)" line above. Shown on the deck detail
screen; the numbers come from
deck_stats. Call set_cards() with models.deck.Deck.cards-shaped cards.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

import deck_stats
from ui.components.color_pie import ColorLegend, ColorPie
from ui.components.mana_curve import ManaCurveChart

PIE_SIZE = 100
LEGEND_WIDTH = 150  # fits "Colorless: 100 (100%)"


class DeckStatsRow(QWidget):
    def __init__(self, show_average: bool = False, parent=None):
        """show_average: include the average mana value line above the
        charts (the deck detail screen shows it in its header instead)."""
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        self._average_label = None
        if show_average:
            self._average_label = QLabel()
            self._average_label.setObjectName("settingsLabel")
            outer.addWidget(self._average_label)

        charts = QHBoxLayout()
        charts.setSpacing(48)
        self._charts = charts

        self._mana_curve = ManaCurveChart()
        charts.addWidget(self._mana_curve, 0, Qt.AlignBottom)

        block, self._balance_pie, self._balance_legend, _ = _pie_block("Color balance")
        charts.addWidget(block, 0, Qt.AlignBottom)
        block, self._production_pie, self._production_legend, self._production_title = _pie_block("Mana production")
        charts.addWidget(block, 0, Qt.AlignBottom)

        charts.addStretch()
        outer.addLayout(charts)

    def insert_first(self, widget: QWidget):
        """Adds a chart before the others, at the far left (the deck page's
        Game Tracker Elo — see DeckEloBlock)."""
        self._charts.insertWidget(0, widget, 0, Qt.AlignBottom)

    def set_cards(self, cards: list, identity: list[str]):
        """Fills every chart from `cards`. identity: the commander's color
        identity (mana production only counts those colors + colorless)."""
        if self._average_label is not None:
            self._average_label.setText(average_text(cards))
        self._mana_curve.set_counts(deck_stats.mana_curve(cards))

        balance = deck_stats.color_balance(cards)
        self._balance_pie.setCounts(balance)
        self._balance_legend.setCounts(_nonzero(balance))

        production, land_sources, other_sources = deck_stats.mana_production(cards, identity)
        self._production_pie.setCounts(production)
        self._production_legend.setCounts(_nonzero(production))
        self._production_title.setText(f"Mana production · {land_sources} lands + {other_sources} ramp")


def average_text(cards: list) -> str:
    """"Avg. mana value (nonland): 2.71" ("—" if unknown)."""
    average = deck_stats.average_mana_value(cards)
    return f"Avg. mana value (nonland): {average:.2f}" if average is not None else "Avg. mana value (nonland): —"


def _nonzero(counts: dict) -> dict:
    """Legend entries: just the colors that occur."""
    return {color: n for color, n in counts.items() if n}


def _pie_block(title: str):
    """A color doughnut (same as the Collection screen's) + legend with
    percentages, `title` underneath. Returns (block, pie, legend, title_label)."""
    block = QWidget()
    layout = QVBoxLayout(block)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)

    row = QHBoxLayout()
    row.setSpacing(12)
    pie = ColorPie()
    pie.setMinimumSize(0, 0)
    pie.setFixedSize(PIE_SIZE, PIE_SIZE)
    row.addWidget(pie)
    legend = ColorLegend(show_percent=True)
    legend.setFixedSize(LEGEND_WIDTH, 6 * 20)  # room for all six colors (20px per line)
    row.addWidget(legend)
    layout.addLayout(row)

    title_label = QLabel(title)
    title_label.setObjectName("chartTitle")
    title_label.setAlignment(Qt.AlignHCenter)
    layout.addWidget(title_label)
    return block, pie, legend, title_label
