"""ShowcasePickerDialog: pick collection cards to add to a showcase — the
collection grid (one tile per printing + finish) with the usual search
box; each click adds that card to the end of the showcase. Opened from
the Home screen's showcase panel.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

import availability
import card_sort
from card_fields import plural
from models import showcases
from ui.components.card_grid_view import CardGridView
from ui.components.search_box import ERROR_COLOR, SearchBox
from ui.screens.collection import merge_languages


class ShowcasePickerDialog(QDialog):
    def __init__(self, parent, app, showcase: dict):
        """showcase: the showcase dict being added to — its "cards" list is
        appended to as cards are clicked (the caller saves afterwards)."""
        super().__init__(parent)
        self.app = app
        self._showcase = showcase
        self.added = 0
        self.setWindowTitle(f"Add cards to \"{showcase['name']}\"")
        self.resize(1180, 780)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel(f"Add cards to \"{showcase['name']}\"")
        title.setObjectName("settingsSectionTitle")
        top.addWidget(title)
        top.addSpacing(16)
        self._feedback = QLabel("Click cards to add them to the end of the showcase.")
        self._feedback.setObjectName("resultCount")
        top.addWidget(self._feedback, 1)
        self._search = SearchBox("Search your collection… e.g. r:mythic", context_fn=self._search_context)
        self._search.search_changed.connect(self._grid_filter)
        top.addWidget(self._search)
        layout.addLayout(top)

        self._grid = CardGridView()
        self._grid.setCardData(card_sort.sort_entries(merge_languages(app.collection.cards), card_sort.SORT_NAME))
        self._grid.entry_clicked.connect(self._on_card_clicked)
        layout.addWidget(self._grid, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        done = QPushButton("Done")
        done.clicked.connect(self.accept)
        bottom.addWidget(done)
        layout.addLayout(bottom)

    def _search_context(self) -> dict:
        return {"is": {"unique": availability.unique_check(self.app.collection.cards)}}

    def _grid_filter(self, predicate):
        self._grid.setFilter(predicate)
        if predicate is not None:
            self._search.set_result_text(plural(self._grid.filtered_count(), "result"))

    def _on_card_clicked(self, entry: dict):
        """Adds the clicked version to the showcase (once per showcase)."""
        ref = showcases.card_ref(entry)
        if any(showcases.ref_key(r) == showcases.ref_key(ref) for r in self._showcase["cards"]):
            self._feedback.setStyleSheet(f"color: {ERROR_COLOR};")
            self._feedback.setText(f"{ref['name']} is already in this showcase")
            return
        self._showcase["cards"].append(ref)
        self.added += 1
        self._feedback.setStyleSheet("")
        self._feedback.setText(f"Added {ref['name']} · {len(self._showcase['cards'])} cards in the showcase")
