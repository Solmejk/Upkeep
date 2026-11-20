"""LanguageCheckDialog: for a Moxfield deck, asks which language of copy
the deck uses for each card whose exact printing + finish the collection
owns in another language or in several (see models.deck_languages).
A dropdown per card, or a count per language for cards the deck runs
several copies of. Opened from DeckDetailScreen's warning line.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QSpinBox,
    QScrollArea, QWidget, QDialogButtonBox,
)

from languages import DEFAULT_LANGUAGE, language_name
from ui.components.search_box import ERROR_COLOR


class LanguageCheckDialog(QDialog):
    def __init__(self, parent, deck_name: str, conflicts: list[dict]):
        """conflicts: models.deck_languages.conflicts(...) results."""
        super().__init__(parent)
        self.setWindowTitle("Confirm card languages")
        self.setMinimumSize(640, 420)
        self._conflicts = conflicts
        self._inputs = []  # per conflict: QComboBox, or {language: QSpinBox}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        title = QLabel(f"Card languages in \"{deck_name}\"")
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)

        hint = QLabel(
            "Moxfield doesn't record which language of card a deck uses. You own these "
            "printings in another language, or in several — which copies are in this deck?"
        )
        hint.setObjectName("settingsDescription")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        rows = QWidget()
        grid = QGridLayout(rows)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        for row, conflict in enumerate(conflicts):
            card, owned = conflict["card"], conflict["owned"]
            finish = str(card.get("finish") or "").lower()
            finish_text = "etched" if finish == "etched" else "foil" if card.get("isFoil") or finish == "foil" else ""
            name = QLabel(f"{card['quantity']}x {card['name']}")
            name.setObjectName("settingsLabel")
            details = QLabel(
                f"{card.get('set', '').upper()} #{card.get('cn', '')}{' · ' + finish_text if finish_text else ''}"
                f"  ·  you own {_owned_text(owned)}"
            )
            details.setObjectName("settingsDescription")
            label_box = QVBoxLayout()
            label_box.setSpacing(0)
            label_box.addWidget(name)
            label_box.addWidget(details)
            grid.addLayout(label_box, row, 0)

            current = conflict["answer"] or {_default_language(owned): card["quantity"]}
            if card["quantity"] == 1:
                combo = QComboBox()
                combo.setObjectName("sortCombo")
                for language in owned:
                    combo.addItem(language_name(language), language)
                combo.setCurrentIndex(max(0, combo.findData(next(iter(current)))))
                grid.addWidget(combo, row, 1, Qt.AlignRight)
                self._inputs.append(combo)
            else:
                spins = {}
                spin_row = QHBoxLayout()
                for language in owned:
                    spin = QSpinBox()
                    spin.setRange(0, card["quantity"])
                    spin.setValue(current.get(language, 0))
                    spin_row.addWidget(QLabel(language_name(language)))
                    spin_row.addWidget(spin)
                    spins[language] = spin
                grid.addLayout(spin_row, row, 1, Qt.AlignRight)
                self._inputs.append(spins)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(rows)
        layout.addWidget(scroll, 1)

        self._error = QLabel()
        self._error.setStyleSheet(f"color: {ERROR_COLOR};")
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def answers(self) -> list[tuple[dict, dict]]:
        """(deck card, {language: copies}) per conflict, as chosen."""
        result = []
        for conflict, widget in zip(self._conflicts, self._inputs):
            if isinstance(widget, QComboBox):
                split = {widget.currentData(): 1}
            else:
                split = {language: spin.value() for language, spin in widget.items()}
            result.append((conflict["card"], split))
        return result

    def _on_save(self):
        """Save button: accepts unless a count row doesn't add up."""
        for card, split in self.answers():
            if sum(split.values()) != card["quantity"]:
                self._error.setText(
                    f"{card['name']}: the counts must add up to {card['quantity']} "
                    f"(they add up to {sum(split.values())})."
                )
                return
        self.accept()


def _owned_text(owned: dict) -> str:
    return ", ".join(f"{n}x {language_name(language)}" for language, n in owned.items())


def _default_language(owned: dict) -> str:
    """Preselected answer for an unconfirmed card: English if owned
    (what Moxfield assumes), else the first owned language."""
    return DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in owned else next(iter(owned))
