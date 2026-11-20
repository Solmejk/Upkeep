"""Copy-text export popouts.

    TextExportModal — the shared popout: a title, an optional hint, an
                      optional row of controls, a line count, a read-only
                      text box and Copy to Clipboard / Close.
    ExportModal     — the Availability Checker's Export: checked cards as
                      '<qty> <name> (<SET>)' lines (the format Cardmarket's
                      wantlist search accepts), filterable by status.
    DeckExportModal — a Deck Maker deck's Export: the deck as Moxfield import
                      text (deck_export.py) — exact printings and foiling kept.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QPlainTextEdit,
)

import availability
import deck_export
from card_fields import plural
from ui.components.overlay_modal import OverlayModal


class TextExportModal(OverlayModal):
    """The shared popout. Subclasses add their controls to self.controls
    and fill the text with set_text(); see OverlayModal for dismissal
    (outside-click, Esc, Close)."""

    def __init__(self, parent, title: str, hint: str = "", width: int = 500, height: int = 580):
        super().__init__(parent)
        content = QWidget()
        content.setObjectName("cardModalContent")  # reuse CardModal's box styling
        content.setFixedWidth(width)
        content.setFixedHeight(height)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        self._title = QLabel(title)
        self._title.setObjectName("cardModalName")
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("cardModalMeta")
            hint_label.setAlignment(Qt.AlignCenter)
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)

        self.controls = QHBoxLayout()  # subclasses' extra controls (empty by default)
        self.controls.setSpacing(16)
        layout.addLayout(self.controls)

        self._count_label = QLabel()
        self._count_label.setObjectName("cardModalMeta")
        self._count_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._count_label)

        self._text = QPlainTextEdit()
        self._text.setObjectName("exportText")
        self._text.setReadOnly(True)
        layout.addWidget(self._text, 1)

        button_row = QHBoxLayout()
        self._copy_btn = QPushButton("Copy to Clipboard")
        self._copy_btn.clicked.connect(self._copy)
        button_row.addWidget(self._copy_btn)
        button_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("backButton")
        close_btn.clicked.connect(self._dismiss)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._init_overlay(content)

    def set_text(self, text: str, count_text: str):
        """The text to copy and the line under the title (e.g. "12 lines")."""
        self._text.setPlainText(text)
        self._count_label.setText(count_text)
        self._copy_btn.setText("Copy to Clipboard")
        self._copy_btn.setEnabled(bool(text))

    def _copy(self):
        """Copies the text box's contents to the system clipboard."""
        QGuiApplication.clipboard().setText(self._text.toPlainText())
        self._copy_btn.setText("Copied!")


STATUS_LABELS = {
    availability.FREE: "Free",
    availability.USED: "Used elsewhere",
    availability.UNOWNED: "Not owned",
}
DEFAULT_INCLUDED = {availability.USED, availability.UNOWNED}


class ExportModal(TextExportModal):
    """The Availability Checker's export. Call show_export(results)."""

    def __init__(self, parent=None):
        super().__init__(parent, "Export Cards", width=480, height=560)
        self._results = []
        self.controls.addStretch()
        self._checks = {}
        for status in (availability.FREE, availability.USED, availability.UNOWNED):
            checkbox = QCheckBox(STATUS_LABELS[status])
            checkbox.setChecked(status in DEFAULT_INCLUDED)
            checkbox.stateChanged.connect(self._refresh_text)
            self.controls.addWidget(checkbox)
            self._checks[status] = checkbox
        self.controls.addStretch()

    def show_export(self, results: list[dict]):
        """Shows the export for `results` (the list check_availability()
        produced for the grid). The checkboxes re-filter it afterwards."""
        self._results = results
        self._refresh_text()
        self._show_overlay()

    def _refresh_text(self, *_args):
        """Rebuilds the text from self._results, keeping rows whose status
        is checked. *_args absorbs QCheckBox.stateChanged's int."""
        active = {status for status, checkbox in self._checks.items() if checkbox.isChecked()}
        lines = []
        for r in self._results:
            if r["status"] not in active:
                continue
            if r["status"] == availability.FREE:
                # Already owned — the deck's quantity and its own printing
                quantity = r.get("quantity", 1)
                set_code = r.get("set", "")
            else:
                # Needs buying — how many, from the cheapest printing
                quantity = r["missing"]
                set_code = r.get("cheapest_set") or r.get("set", "")
            if quantity <= 0:
                continue
            lines.append(f"{quantity} {r['name']} ({set_code.upper()})")
        self.set_text("\n".join(lines), plural(len(lines), "line"))


class DeckExportModal(TextExportModal):
    """A Deck Maker deck's export to Moxfield. Call show_export(deck)."""

    def __init__(self, parent=None):
        super().__init__(
            parent, "Export to Moxfield",
            hint="In Moxfield: create a new deck, choose Import (or Bulk Edit) and paste. "
                 "Set, collector number and foiling pick the exact cards.",
            width=520, height=600)

    def show_export(self, deck):
        """Shows `deck`'s (a loaded models.deck.Deck) import text."""
        self._title.setText(f"Export \"{deck.name}\" to Moxfield")
        self.set_text(deck_export.moxfield_text(deck), f"{deck.total_cards} cards")
        self._show_overlay()
