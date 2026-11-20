"""CardPickerDialog: pick one card from the collection — the collection
grid (one tile per printing + finish) with the usual search box; clicking
a card picks it and closes. Used to choose which printing an artist proof
belongs to.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

import availability
import card_sort
from card_fields import plural
from ui.components.card_grid_view import CardGridView
from ui.components.search_box import SearchBox
from ui.screens.collection import merge_languages


class CardPickerDialog(QDialog):
    def __init__(self, parent, app, title: str, hint: str = "Click a card to pick it."):
        super().__init__(parent)
        self.app = app
        self.picked = None  # the clicked collection entry
        self.setWindowTitle(title)
        self.resize(1180, 780)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("settingsSectionTitle")
        top.addWidget(heading)
        top.addSpacing(16)
        hint_label = QLabel(hint)
        hint_label.setObjectName("resultCount")
        top.addWidget(hint_label, 1)
        self._search = SearchBox("Search your collection…", context_fn=self._search_context)
        self._search.search_changed.connect(self._on_search)
        top.addWidget(self._search)
        layout.addLayout(top)

        self._grid = CardGridView()
        self._grid.setCardData(card_sort.sort_entries(merge_languages(app.collection.cards), card_sort.SORT_NAME))
        self._grid.entry_clicked.connect(self._on_pick)
        layout.addWidget(self._grid, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("backButton")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        layout.addLayout(bottom)

    def _search_context(self) -> dict:
        return {"is": {"unique": availability.unique_check(self.app.collection.cards)}}

    def _on_search(self, predicate):
        self._grid.setFilter(predicate)
        if predicate is not None:
            self._search.set_result_text(plural(self._grid.filtered_count(), "result"))

    def _on_pick(self, entry: dict):
        self.picked = entry
        self.accept()
