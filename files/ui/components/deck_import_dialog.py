"""DeckImportDialog: "Import deck" on the Decks screen — paste (or load) a
decklist in Moxfield's text format and save it as a Deck Maker (local)
deck. Parsing (deck_import.parse) is local and live, so the dialog shows
what it understood while you type; Import then looks the cards up on
Scryfall in the background (deck_import.resolve) and saves the deck
(models.local_decks.save_imported).
"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QComboBox, QFileDialog, QMessageBox,
)

import deck_import
from card_fields import plural
from models import local_decks
from ui.background import run_in_background

PLACEHOLDER = """Paste a decklist (Moxfield's export works as-is), e.g.

1 Edgar Markov (INR) 491

1 Sol Ring (C21) 263
1 Lightning Bolt (2X2) 117 *F*
1 Bloodline Keeper
30 Swamp

Cards with only a name get their newest printing."""
NO_COMMANDER = "No commander"


class DeckImportDialog(QDialog):
    def __init__(self, parent, username: str):
        super().__init__(parent)
        self._username = username
        self._parsed = None
        self._bg_tasks = []  # keeps the background task alive — see ui/background.py
        self.deck_id = None  # set once the deck is saved
        self.setWindowTitle("Import deck")
        self.resize(640, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        name_label = QLabel("Deck name")
        name_label.setObjectName("settingsLabel")
        layout.addWidget(name_label)
        self._name = QLineEdit()
        self._name.setObjectName("searchInput")
        self._name.setPlaceholderText("e.g. Vampires")
        self._name.textChanged.connect(self._update_state)
        layout.addWidget(self._name)

        list_row = QHBoxLayout()
        list_label = QLabel("Decklist")
        list_label.setObjectName("settingsLabel")
        list_row.addWidget(list_label)
        list_row.addStretch()
        file_btn = QPushButton("Load from file…")
        file_btn.setObjectName("backButton")
        file_btn.clicked.connect(self._load_file)
        list_row.addWidget(file_btn)
        layout.addLayout(list_row)

        self._text = QPlainTextEdit()
        self._text.setObjectName("syncLogText")
        self._text.setPlaceholderText(PLACEHOLDER)
        self._text.textChanged.connect(lambda: self._parse_timer.start())
        layout.addWidget(self._text, 1)
        self._parse_timer = QTimer(self, singleShot=True, interval=300)  # parse once typing pauses
        self._parse_timer.timeout.connect(self._reparse)

        self._summary = QLabel()
        self._summary.setObjectName("settingsDescription")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        commander_row = QHBoxLayout()
        self._commander_label = QLabel("Commander:")
        self._commander_label.setObjectName("settingsLabel")
        commander_row.addWidget(self._commander_label)
        self._commander = QComboBox()
        self._commander.setMinimumWidth(300)
        commander_row.addWidget(self._commander)
        commander_row.addStretch()
        layout.addLayout(commander_row)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("backButton")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        self._import_btn = QPushButton("Import")
        self._import_btn.clicked.connect(self._on_import)
        buttons.addWidget(self._import_btn)
        layout.addLayout(buttons)

        self._reparse()

    # ------------------------------------------------------------ input
    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Decklist file", "", "Text files (*.txt);;All files (*)")
        if not path:
            return
        self._text.setPlainText(Path(path).read_text(encoding="utf-8", errors="replace"))
        if not self._name.text().strip():
            self._name.setText(Path(path).stem)

    def _reparse(self):
        """Parses the text and shows what was understood. When no
        commander was found, offers the cards as commander choices."""
        self._parsed = deck_import.parse(self._text.toPlainText())
        commanders, cards = self._parsed["commanders"], self._parsed["cards"]
        count = sum(l["qty"] for l in commanders + cards)

        parts = []
        if commanders:
            parts.append("Commander: " + " + ".join(l["name"] for l in commanders))
        if count:
            parts.append(plural(count, "card") + " in total")
        if self._parsed["unreadable"]:
            parts.append(f"{plural(len(self._parsed['unreadable']), 'line')} not understood "
                         f"(skipped): {', '.join(self._parsed['unreadable'][:3])}"
                         + ("…" if len(self._parsed["unreadable"]) > 3 else ""))
        self._summary.setText(" · ".join(parts))

        # Commander choice only when the list doesn't say
        choose = bool(cards) and not commanders
        self._commander_label.setVisible(choose)
        self._commander.setVisible(choose)
        if choose:
            previous = self._commander.currentText()
            self._commander.blockSignals(True)
            self._commander.clear()
            self._commander.addItem(NO_COMMANDER)
            for name in dict.fromkeys(l["name"] for l in cards):
                self._commander.addItem(name)
            index = self._commander.findText(previous)
            self._commander.setCurrentIndex(max(index, 0))
            self._commander.blockSignals(False)
        self._update_state()

    def _update_state(self):
        has_cards = bool(self._parsed and (self._parsed["commanders"] or self._parsed["cards"]))
        self._import_btn.setEnabled(has_cards and bool(self._name.text().strip()))

    # ----------------------------------------------------------- import
    def _on_import(self):
        commanders = list(self._parsed["commanders"])
        cards = list(self._parsed["cards"])
        chosen = self._commander.currentText() if self._commander.isVisible() else NO_COMMANDER
        if chosen != NO_COMMANDER:  # move the chosen card into the commander slot
            line = next(l for l in cards if l["name"] == chosen)
            cards.remove(line)
            commanders.append(line)

        self._import_btn.setEnabled(False)
        self._import_btn.setText("Looking up cards…")
        name = self._name.text().strip()
        run_in_background(
            lambda: self._import(name, commanders, cards),
            self._bg_tasks, on_finished=self._on_imported, on_failed=self._on_failed,
        )

    def _import(self, name: str, commanders: list, cards: list):
        """Background: Scryfall lookups + saving. Returns (deck_id, missing)."""
        resolved, missing = deck_import.resolve(commanders + cards)
        commander_ids = {id(l) for l in commanders}
        deck_commanders = [deck_import.deck_card(l, c) for l, c in resolved if id(l) in commander_ids]
        deck_cards = [deck_import.deck_card(l, c) for l, c in resolved if id(l) not in commander_ids]
        if not deck_commanders and not deck_cards:
            raise RuntimeError("None of the cards were found on Scryfall.")
        return local_decks.save_imported(name, self._username, deck_commanders, deck_cards), missing

    def _on_imported(self, result):
        self.deck_id, missing = result
        if missing:
            QMessageBox.warning(
                self, "Imported — some cards not found",
                "The deck was saved without these cards (check their spelling):\n\n    "
                + "\n    ".join(missing))
        self.accept()

    def _on_failed(self, message: str):
        self._import_btn.setText("Import")
        self._update_state()
        QMessageBox.warning(self, "Import failed", message)
