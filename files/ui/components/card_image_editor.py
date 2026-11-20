"""CardImageEditorDialog: "Edit card" — give one printing your own front
and / or back image (an artist proof, a signed or altered card...). Three
columns: the original card on the left, a preview of front and back as
they'll look in the middle, and the buttons on the right. Nothing changes
until Save (models.artist_proofs.update).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QFrame, QCheckBox,
)

import scryfall
from card_search import DFC_LAYOUTS
from image_cache import get_image_path, get_original_image_path
from models import artist_proofs

ORIGINAL_WIDTH, ORIGINAL_HEIGHT = 250, 349
PREVIEW_WIDTH, PREVIEW_HEIGHT = 220, 307
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"


class CardImageEditorDialog(QDialog):
    def __init__(self, parent, card: dict):
        """card: the printing's Moxfield card object (name, set, cn,
        scryfall_id, layout) — from the collection."""
        super().__init__(parent)
        self._card = card
        self._printing = {"set": card.get("set", ""), "cn": card.get("cn", "")}
        existing = artist_proofs.proof_for(card.get("set", ""), card.get("cn", "")) or {}
        self._existing = {side: artist_proofs.image_path(existing, side) for side in ("front", "back")}
        self._pending = {"front": artist_proofs.KEEP, "back": artist_proofs.KEEP}  # file path / CLEAR / KEEP
        self._initial_flags = {flag: bool(existing.get(flag)) for flag in artist_proofs.FLAGS}

        self.setWindowTitle(f"Edit card — {card['name']}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)

        title = QLabel(card["name"])
        title.setObjectName("settingsSectionTitle")
        layout.addWidget(title)
        subtitle = QLabel(
            f"{card.get('set', '').upper()} #{card.get('cn', '')} · your own images replace this printing's "
            "normal image everywhere; the back shows when a showcase is flipped."
        )
        subtitle.setObjectName("settingsDescription")
        layout.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(28)

        # Original
        original_col = QVBoxLayout()
        original_col.addWidget(_heading("Original"))
        original = QLabel()
        original.setFixedSize(ORIGINAL_WIDTH, ORIGINAL_HEIGHT)
        original.setAlignment(Qt.AlignCenter)
        _show(original, get_original_image_path(
            scryfall.image_url(card.get("scryfall_id", "")), scryfall.card_image_cache_name(self._printing)))
        original_col.addWidget(original)
        original_col.addStretch()
        body.addLayout(original_col)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet("color: #2d2d2d;")
        body.addWidget(divider)

        # Preview: front + back as they'll look
        preview_col = QVBoxLayout()
        preview_col.addWidget(_heading("Preview"))
        sides = QHBoxLayout()
        sides.setSpacing(16)
        self._preview = {}
        self._preview_note = {}
        for side in ("front", "back"):
            col = QVBoxLayout()
            image = QLabel()
            image.setFixedSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
            image.setAlignment(Qt.AlignCenter)
            col.addWidget(image)
            note = QLabel()
            note.setObjectName("settingsDescription")
            note.setAlignment(Qt.AlignCenter)
            col.addWidget(note)
            sides.addLayout(col)
            self._preview[side] = image
            self._preview_note[side] = note
        preview_col.addLayout(sides)
        preview_col.addStretch()
        body.addLayout(preview_col)

        # Buttons
        buttons = QVBoxLayout()
        buttons.setSpacing(8)
        buttons.addSpacing(26)
        self._buttons = {}
        for side in ("front", "back"):
            change = QPushButton(f"Change {side}…")
            change.clicked.connect(lambda _=False, s=side: self._choose(s))
            buttons.addWidget(change)
        buttons.addSpacing(12)
        for side in ("front", "back"):
            reset = QPushButton(f"Reset {side}")
            reset.setObjectName("backButton")
            reset.setToolTip(f"Back to the normal {side}")
            reset.clicked.connect(lambda _=False, s=side: self._reset(s))
            buttons.addWidget(reset)
            self._buttons[side] = reset
        # What kind of special copy it is — searchable as is:proof etc.
        buttons.addSpacing(18)
        buttons.addWidget(_heading("This card is:"))
        self._flag_boxes = {}
        for flag, label in artist_proofs.FLAGS.items():
            box = QCheckBox(label)
            box.setChecked(self._initial_flags[flag])
            box.setToolTip(f"Find it with is:{flag}")
            buttons.addWidget(box)
            self._flag_boxes[flag] = box
        buttons.addStretch()
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("backButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        body.addLayout(buttons)

        layout.addLayout(body)
        self._refresh_preview()

    # ----------------------------------------------------------- state

    def _current(self, side: str):
        """(image path, is_custom) for a side, counting unsaved changes."""
        pending = self._pending[side]
        if pending is artist_proofs.CLEAR:
            return self._default(side), False
        if pending is not artist_proofs.KEEP:
            return pending, True
        if self._existing[side] is not None:
            return self._existing[side], True
        return self._default(side), False

    def _default(self, side: str):
        """The normal image for a side: the card's front, or for the back a
        double-faced card's back face, else the Magic card back."""
        card = self._card
        if side == "front":
            return get_original_image_path(scryfall.image_url(card.get("scryfall_id", "")),
                                           scryfall.card_image_cache_name(self._printing))
        if card.get("layout") in DFC_LAYOUTS:
            return get_original_image_path(scryfall.back_image_url(card.get("scryfall_id", "")),
                                           scryfall.back_cache_name(self._printing))
        return get_image_path(scryfall.MAGIC_BACK_URL, scryfall.MAGIC_BACK_CACHE_NAME)

    def _refresh_preview(self):
        for side in ("front", "back"):
            path, custom = self._current(side)
            _show(self._preview[side], path, PREVIEW_WIDTH, PREVIEW_HEIGHT)
            changed = self._pending[side] is not artist_proofs.KEEP
            self._preview_note[side].setText(
                f"{side.capitalize()} · {'your image' if custom else 'normal'}" + (" · not saved" if changed else "")
            )
            self._buttons[side].setEnabled(custom)

    # --------------------------------------------------------- actions

    def _choose(self, side: str):
        path, _ = QFileDialog.getOpenFileName(self, f"{side.capitalize()} image for {self._card['name']}", "", IMAGE_FILTER)
        if path:
            self._pending[side] = path
            self._refresh_preview()

    def _reset(self, side: str):
        self._pending[side] = artist_proofs.CLEAR if self._existing[side] is not None else artist_proofs.KEEP
        self._refresh_preview()

    def _save(self):
        flags = {flag: box.isChecked() for flag, box in self._flag_boxes.items()}
        images_changed = any(action is not artist_proofs.KEEP for action in self._pending.values())
        if images_changed or flags != self._initial_flags:
            artist_proofs.update(self._card["name"], self._printing["set"], self._printing["cn"],
                                 front=self._pending["front"], back=self._pending["back"], flags=flags)
            self.accept()
        else:
            self.reject()  # nothing changed


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("chartTitle")
    return label


def _show(label: QLabel, path, width: int = ORIGINAL_WIDTH, height: int = ORIGINAL_HEIGHT):
    pixmap = QPixmap(str(path)) if path else QPixmap()
    if pixmap.isNull():
        label.setText("No image")
        label.setStyleSheet("border: 1px dashed #444444; border-radius: 8px; color: #888888;")
    else:
        label.setStyleSheet("")
        label.setPixmap(pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
