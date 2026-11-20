"""DeckExportModal: popout opened from a Deck Maker deck's Export button
(DeckDetailScreen). Shows the deck as Moxfield import text (see
deck_export.py) — exact printings and foiling kept — with a one-click
copy to clipboard. Same look as the Availability screen's ExportModal.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
)

import deck_export
from ui.components.overlay_modal import OverlayModal

MODAL_WIDTH = 520
MODAL_HEIGHT = 600


class DeckExportModal(OverlayModal):
    """Call show_export(deck) to populate and display it. See OverlayModal
    for dismissal/resize behavior (outside-click, Esc, close button)."""

    def __init__(self, parent=None):
        super().__init__(parent)

        content = QWidget()
        content.setObjectName("cardModalContent")  # reuse CardModal's box styling
        content.setFixedWidth(MODAL_WIDTH)
        content.setFixedHeight(MODAL_HEIGHT)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        self._title = QLabel("Export to Moxfield")
        self._title.setObjectName("cardModalName")
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)

        hint = QLabel(
            "In Moxfield: create a new deck, choose Import (or Bulk Edit) and paste. "
            "Set, collector number and foiling pick the exact cards."
        )
        hint.setObjectName("cardModalMeta")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

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

    def show_export(self, deck):
        """Fills in `deck`'s (a loaded models.deck.Deck) import text and
        shows the popout."""
        self._title.setText(f"Export \"{deck.name}\" to Moxfield")
        self._text.setPlainText(deck_export.moxfield_text(deck))
        self._count_label.setText(f"{deck.total_cards} cards")
        self._copy_btn.setText("Copy to Clipboard")
        self._show_overlay()

    def _copy(self):
        """Copies the import text to the system clipboard."""
        QGuiApplication.clipboard().setText(self._text.toPlainText())
        self._copy_btn.setText("Copied!")
