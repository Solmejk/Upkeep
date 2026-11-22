"""CommanderPage: the Deck Maker's "Choose your commander" page — the
collection's commander-eligible cards (legendary creatures etc., see
card_search's is:commander), browsable or searchable with the usual
Scryfall-syntax box. Clicking one emits `picked`.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from card_fields import plural
from ui.components.card_grid_view import CardGridView
from ui.components.search_box import SearchBox
from ui.components.section_card import back_button

from .helpers import CARD_WIDTH, CardUsage


class CommanderPage(QWidget):
    picked = Signal(dict)       # a commander was clicked (its collection entry)
    back_requested = Signal()   # the Back button

    def __init__(self, usage: CardUsage):
        super().__init__()
        self._search = None  # predicate from the search box

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(40, 30, 40, 10)
        top_bar.addWidget(back_button(self.back_requested.emit))
        top_bar.addStretch()
        outer.addLayout(top_bar)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(40, 0, 40, 10)
        title = QLabel("Choose your commander")
        title.setObjectName("screenTitle")
        header_layout.addWidget(title)
        hint = QLabel("Legendary creatures and other cards that can be your commander, from your "
                      "collection. Click one to pick it.")
        hint.setObjectName("settingsDescription")
        hint.setWordWrap(True)
        header_layout.addWidget(hint)
        outer.addWidget(header)

        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(40, 0, 40, 16)
        search_layout.addStretch()
        self._search_box = SearchBox("Search commanders… e.g. id<=esper", context_fn=usage.search_context)
        self._search_box.search_changed.connect(self._on_search_changed)
        search_layout.addWidget(self._search_box)
        outer.addWidget(search_row)

        self._grid = CardGridView(cell_width=CARD_WIDTH)
        self._grid.setContentsMargins(40, 0, 40, 40)
        self._grid.entry_clicked.connect(self.picked.emit)
        outer.addWidget(self._grid, 1)

    def set_candidates(self, entries: list):
        """The commanders to choose from (keeps the current search)."""
        self._grid.setCardData(entries)
        self._apply_search()

    def reset_search(self):
        """Clears the search (for a fresh deck)."""
        self._search_box.clear()
        self._search = None
        self._apply_search()

    def reload_images(self):
        self._grid.reload_images()

    def _on_search_changed(self, predicate):
        self._search = predicate
        self._apply_search()

    def _apply_search(self):
        """Filters the grid by the search (if any) and shows the count."""
        self._grid.setFilter(self._search)
        self._search_box.set_result_text(plural(self._grid.filtered_count(), "commander"))
