"""TokenPrintingDialog: "Set default printing" for a token — every paper
printing of it from Scryfall in a card grid; clicking one saves it as the
token's default (models.token_printings), shown for that token in every
deck. The deck's own printing is marked "(deck)". Opened from the card
popup of a deck's token.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

import scryfall
from card_fields import plural
from models import token_printings
from ui.background import run_in_background
from ui.components.card_grid_view import CardGridView


class TokenPrintingDialog(QDialog):
    def __init__(self, parent, token: dict):
        """token: a deck token (models.deck.Deck.tokens), as shown — its
        "uid" keys the saved choice, its scryfall_id finds the printings."""
        super().__init__(parent)
        self._token = token_printings.deck_printing(token)
        self._printings = []
        self._bg_tasks = []  # keeps the background task alive — see ui/background.py
        self.setWindowTitle(f"Default printing — {self._token['name']}")
        self.resize(1000, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self._status = QLabel("Loading printings from Scryfall…")
        self._status.setObjectName("settingsDescription")
        layout.addWidget(self._status)

        self._grid = CardGridView()
        self._grid.entry_clicked.connect(self._on_picked)
        layout.addWidget(self._grid, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("backButton")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        run_in_background(
            lambda: scryfall.all_paper_printings(token.get("scryfall_id") or self._token["scryfall_id"]),
            self._bg_tasks, on_finished=self._on_loaded, on_failed=self._on_failed,
        )

    def _on_loaded(self, printings: list):
        """Fills the grid — captioned by set and number, since every tile
        has the same name; the deck's own printing is marked "(deck)"."""
        self._printings = printings
        entries = []
        for p in printings:
            caption = f"{p['set'].upper()} #{p['collector_number']}"
            if p["id"] == self._token.get("scryfall_id"):
                caption += " (deck)"
            entries.append({
                "quantity": 1,
                "printing": p,
                "card": {
                    "name": caption,
                    "set": p["set"],
                    "cn": p["collector_number"],
                    "scryfall_id": p["id"],
                },
            })
        self._grid.setCardData(entries)
        self._status.setText(
            f"{plural(len(printings), 'printing')} of {self._token['name']} — click one to use it "
            "for this token in every deck." if printings else "Scryfall has no paper printings of this token.")

    def _on_failed(self, message: str):
        self._status.setText(f"Couldn't load printings from Scryfall: {message}")

    def _on_picked(self, entry: dict):
        """Saves the clicked printing — or, for the deck's own printing,
        removes the default (so each deck shows what it lists again)."""
        printing = entry["printing"]
        is_deck_printing = printing["id"] == self._token.get("scryfall_id")
        token_printings.set_default(self._token["uid"], None if is_deck_printing else printing)
        self.accept()
