"""TokenPrinterScreen (an app on the Other Apps page): pick a Moxfield
deck, choose how many copies of each of its tokens to print (default 2),
and save a print-ready Word document — see token_print.py. Uses your
default token printings (models.token_printings).
"""

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl, QEvent
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox,
    QScrollArea, QFrame, QFileDialog, QMessageBox, QSizePolicy,
)

import cache_io
import paths
import scryfall
import token_print
from card_fields import plural
from models import token_printings
from ui.components.section_card import back_button
from ui.background import run_in_background
from ui.components.image_tile import ImageTile
from ui.components.token_sheet_preview import TokenSheetPreview

DEFAULT_COPIES = 2
THUMB_W, THUMB_H = 100, 140
SETTINGS_PATH = paths.DATA_DIR / "token_printer.json"  # remembers the last save folder


class TokenPrinterScreen(QWidget):
    back_requested = Signal()  # Back button (to the Other Apps page)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._decks = []
        self._rows = []  # [(token, spinbox)] for the selected deck
        self._bg_tasks = []  # keeps background tasks alive — see ui/background.py

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.setSpacing(14)

        top_bar = QHBoxLayout()
        back_btn = back_button(self.back_requested.emit)
        top_bar.addWidget(back_btn)
        top_bar.addStretch()
        outer.addLayout(top_bar)

        title = QLabel("Token Printer")
        title.setObjectName("screenTitle")
        outer.addWidget(title)

        description = QLabel(
            "Pick a deck and how many of each token to print. The document has the tokens at real "
            "card size, two per row — print at 100% scale (\"actual size\"), then cut them out.")
        description.setObjectName("settingsDescription")
        description.setWordWrap(True)
        description.setMaximumWidth(700)
        outer.addWidget(description)

        # Left: deck + tokens + create button. Right: page preview.
        content = QHBoxLayout()
        content.setSpacing(32)
        left = QVBoxLayout()
        left.setSpacing(14)
        left_box = QWidget()
        left_box.setLayout(left)
        left.setContentsMargins(0, 0, 0, 0)
        left_box.setMinimumWidth(480)
        left_box.setMaximumWidth(700)
        content.addWidget(left_box, 1)
        outer.addLayout(content, 1)

        deck_row = QHBoxLayout()
        deck_label = QLabel("Deck:")
        deck_label.setObjectName("settingsLabel")
        deck_row.addWidget(deck_label)
        self._deck_combo = QComboBox()
        self._deck_combo.setMinimumWidth(320)
        self._deck_combo.currentIndexChanged.connect(self._on_deck_changed)
        deck_row.addWidget(self._deck_combo)
        deck_row.addStretch()
        left.addLayout(deck_row)

        # Token rows (scrollable)
        scroll = QScrollArea()
        scroll.setObjectName("decksScroll")  # transparent, borderless
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(700)
        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        scroll.setWidget(self._list)
        left.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        self._summary = QLabel()
        self._summary.setObjectName("settingsLabel")
        bottom.addWidget(self._summary)
        bottom.addStretch()
        self._create_btn = QPushButton("Create document…")
        self._create_btn.clicked.connect(self._on_create)
        bottom.addWidget(self._create_btn)
        bottom_box = QWidget()
        bottom_box.setLayout(bottom)
        bottom_box.setMaximumWidth(700)
        bottom.setContentsMargins(0, 0, 0, 0)
        left.addWidget(bottom_box)

        right = QVBoxLayout()
        right.setSpacing(8)
        preview_title = QLabel("Preview")
        preview_title.setObjectName("settingsSectionTitle")
        right.addWidget(preview_title)
        self._preview = TokenSheetPreview()
        preview_scroll = QScrollArea()
        preview_scroll.setObjectName("decksScroll")  # transparent, borderless
        preview_scroll.setWidget(self._preview)
        preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        preview_scroll.setMinimumWidth(320)
        # the pages fill the preview column's width (within the preview's limits)
        self._preview_viewport = preview_scroll.viewport()
        self._preview_viewport.installEventFilter(self)
        right.addWidget(preview_scroll, 1)
        content.addLayout(right, 1)

    def eventFilter(self, obj, event):
        """Preview column resized: scale the pages to its width. Checks the
        event type first and compares against the stored viewport rather
        than asking Qt for it: while the app shuts down this still runs,
        with the scroll area already deleted."""
        if event.type() == QEvent.Resize and obj is self._preview_viewport:
            self._preview.set_page_width(event.size().width() - 4)
        return False  # never swallows the event

    # ------------------------------------------------------------ decks
    def showEvent(self, event):
        """Re-lists the decks each time the page opens (login / refresh
        may have changed them), keeping the selected deck if it's still
        there."""
        super().showEvent(event)
        current = self._deck_combo.currentText()
        self._decks = sorted((d for d in self.app.decks if d.is_imported), key=lambda d: d.name.lower())
        self._deck_combo.blockSignals(True)
        self._deck_combo.clear()
        self._deck_combo.addItem("Choose a deck…")
        for deck in self._decks:
            self._deck_combo.addItem(deck.name)
        index = self._deck_combo.findText(current)
        self._deck_combo.setCurrentIndex(max(index, 0))
        self._deck_combo.blockSignals(False)
        self._on_deck_changed(self._deck_combo.currentIndex())

    def _on_deck_changed(self, index: int):
        """Lists the chosen deck's tokens with a copies box each."""
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows = []

        deck = self._decks[index - 1] if 0 < index <= len(self._decks) else None
        if deck is None:
            self._show_note("Moxfield decks only — Deck Maker decks have no token list.")
            self._update_summary()
            return
        if not deck.cards:
            deck.load()
        tokens = [token_printings.apply(t) for t in deck.tokens]
        if not tokens:
            self._show_note("This deck doesn't make any tokens." if deck.cards else
                            "This deck hasn't loaded yet — try again in a moment.")
            self._update_summary()
            return

        for token in tokens:
            self._list_layout.addWidget(self._token_row(token))
        self._list_layout.addStretch()
        self._update_summary()

    def _show_note(self, text: str):
        note = QLabel(text)
        note.setObjectName("settingsDescription")
        note.setWordWrap(True)
        self._list_layout.addWidget(note)
        self._list_layout.addStretch()

    def _token_row(self, token: dict) -> QWidget:
        """One token: thumbnail, name + what makes it, copies box."""
        row = QFrame()
        row.setObjectName("settingsSection")
        # its own height only — with few tokens, the empty space goes below
        # the list (its stretch) instead of making each row tall
        row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 14, 8)
        layout.setSpacing(14)

        thumb = ImageTile(token["image_url"], scryfall.card_image_cache_name(token), "", token,
                          width=THUMB_W, height=THUMB_H, radius=4)
        for caption in thumb.findChildren(QLabel, "imageTileCaption"):
            caption.hide()  # the name is beside it — no empty caption space under the image
        thumb.request_image_load()
        layout.addWidget(thumb)

        text = QVBoxLayout()  # centred beside the image (stretch above and below)
        text.setSpacing(4)
        text.addStretch()
        name = QLabel(token["name"])
        name.setObjectName("settingsLabel")
        text.addWidget(name)
        made_by = QLabel("Made by: " + ", ".join(token.get("made_by", [])))
        made_by.setObjectName("settingsDescription")
        made_by.setWordWrap(True)
        text.addWidget(made_by)
        text.addStretch()
        layout.addLayout(text, 1)

        # − [n] + — same stepper as the basic lands dialog (Qt's own spin
        # arrows are tiny)
        copies = QSpinBox()
        copies.setObjectName("basicLandCount")
        copies.setRange(0, 30)
        copies.setValue(DEFAULT_COPIES)
        # its own arrows are hidden in the stylesheet (basicLandCount) — not
        # with NoButtons, which squashes the number from Qt 6.12 (style.qss)
        copies.setFixedWidth(56)
        copies.valueChanged.connect(self._update_summary)
        stepper = QHBoxLayout()
        stepper.setSpacing(4)
        for text, step in (("−", copies.stepDown), ("+", copies.stepUp)):
            btn = QPushButton(text)
            btn.setObjectName("stepButton")
            btn.setFixedWidth(36)
            btn.setAutoRepeat(True)
            btn.clicked.connect(step)
            if text == "+":
                stepper.addWidget(copies)
            stepper.addWidget(btn)
        layout.addLayout(stepper)

        self._rows.append((token, copies))
        return row

    def _update_summary(self):
        total = sum(spin.value() for _, spin in self._rows)
        self._preview.set_items([(token, spin.value()) for token, spin in self._rows])
        pages = self._preview.page_count()
        self._summary.setText(f"{plural(total, 'token')} · about {plural(pages, 'page')}" if total else "")
        self._create_btn.setEnabled(total > 0)

    # --------------------------------------------------------- document
    def _on_create(self):
        deck_name = self._deck_combo.currentText()
        settings = cache_io.read_json(SETTINGS_PATH) or {}
        folder = settings.get("last_folder") or str(Path.home() / "Documents")
        safe_name = "".join(c for c in deck_name if c not in '<>:"/\\|?*').strip()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save token sheet", os.path.join(folder, f"{safe_name} tokens.docx"),
            "Word documents (*.docx)")
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"
        cache_io.write_json(SETTINGS_PATH, {**settings, "last_folder": str(Path(path).parent)}, indent=1)

        jobs = [(token, spin.value()) for token, spin in self._rows]
        self._create_btn.setEnabled(False)
        self._create_btn.setText("Creating…")
        self._pending_path = Path(path)
        run_in_background(
            lambda: token_print.build_document(jobs, Path(path)),
            self._bg_tasks, on_finished=self._on_created, on_failed=self._on_failed,
        )

    def _reset_button(self):
        self._create_btn.setText("Create document…")
        self._update_summary()

    def _on_created(self, count: int):
        self._reset_button()
        path = self._pending_path
        reply = QMessageBox.question(
            self, "Token sheet saved",
            f"Saved {plural(count, 'token')} to:\n{path}\n\nOpen it now?")
        if reply == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _on_failed(self, message: str):
        self._reset_button()
        QMessageBox.warning(self, "Couldn't create the document", message)
