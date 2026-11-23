"""BasicLandsDialog: set how many of each basic land a Deck Maker draft
runs — one − / count / + row per basic the commander can use, and what
the deck's total would come to (it may go over 100 while building). Used
by DeckMakerScreen; the counts are only applied if the dialog is accepted.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QDialogButtonBox,
)

from models.deck_draft import DECK_SIZE

MAX_PER_LAND = 99


class BasicLandsDialog(QDialog):
    def __init__(self, parent, allowed: list[str], current: dict, other_cards: int):
        """allowed: basic land names to offer (in display order).
        current: name -> count already in the deck. other_cards: the deck's
        cards apart from these basics (commander included), for the total."""
        super().__init__(parent)
        self.setWindowTitle("Add basic lands")
        self.setMinimumWidth(340)
        self._other_cards = other_cards

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel("Basic lands")
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)

        hint = QLabel("These don't need to be in your collection.")
        hint.setObjectName("settingsDescription")
        layout.addWidget(hint)

        self._spins = {}
        for name in allowed:
            row = QHBoxLayout()
            label = QLabel(name)
            label.setObjectName("settingsLabel")
            row.addWidget(label)
            row.addStretch()

            spin = QSpinBox()
            spin.setObjectName("basicLandCount")
            spin.setRange(0, MAX_PER_LAND)
            spin.setValue(current.get(name, 0))
            # own − / + buttons below; the spin box's arrows are hidden in the
            # stylesheet (basicLandCount) — not with NoButtons, see style.qss
            spin.setFixedWidth(56)
            spin.valueChanged.connect(self._update_total)

            minus = QPushButton("−")
            minus.setObjectName("stepButton")
            minus.setFixedWidth(36)
            minus.setAutoRepeat(True)
            minus.clicked.connect(spin.stepDown)
            plus = QPushButton("+")
            plus.setObjectName("stepButton")
            plus.setFixedWidth(36)
            plus.setAutoRepeat(True)
            plus.clicked.connect(spin.stepUp)

            row.addWidget(minus)
            row.addWidget(spin)
            row.addWidget(plus)
            layout.addLayout(row)
            self._spins[name] = spin

        self._total_label = QLabel()
        self._total_label.setObjectName("settingsDescription")
        layout.addWidget(self._total_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_total()

    def counts(self) -> dict:
        """name -> chosen count (zeros included)."""
        return {name: spin.value() for name, spin in self._spins.items()}

    def _update_total(self):
        """Updates the total line: basics chosen, and the deck's total."""
        total = sum(spin.value() for spin in self._spins.values())
        self._total_label.setText(
            f"{total} basic lands · deck would be {self._other_cards + total} / {DECK_SIZE}"
        )
