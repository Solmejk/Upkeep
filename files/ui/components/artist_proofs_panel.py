"""ArtistProofsPanel: Settings → Custom card images — your edited cards
(artist proofs, signed or altered cards) as a grid of small tiles; click
one to change it, or "Edit card" to pick another card from the collection.
Both open CardImageEditorDialog (see models.artist_proofs).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea

import scryfall
from card_fields import plural
from models import artist_proofs
from ui.components.card_image_editor import CardImageEditorDialog
from ui.components.card_picker import CardPickerDialog
from ui.components.image_tile import ImageTile
from ui.flow_layout import FlowLayout
from ui.layout_utils import clear_layout

TILE_WIDTH = 140
TILE_HEIGHT = 196


class ArtistProofsPanel(QWidget):
    proofs_changed = Signal()  # custom images added / changed / removed — images should reload

    def __init__(self, app):
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        description = QLabel(
            "Artist proofs, signed or altered cards — give a printing your own front and / or back image, "
            "and mark what it is (find them with is:proof, is:altered, is:signed). The front replaces "
            "that card's normal image everywhere; the back shows when a showcase is flipped."
        )
        description.setObjectName("settingsDescription")
        description.setWordWrap(True)
        top.addWidget(description, 1)
        edit_btn = QPushButton("Edit card")
        edit_btn.clicked.connect(self._edit_new)
        top.addWidget(edit_btn, 0, Qt.AlignTop)
        layout.addLayout(top)

        self._count = QLabel()
        self._count.setObjectName("resultCount")
        layout.addWidget(self._count)

        scroll = QScrollArea()
        scroll.setObjectName("decksScroll")
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._flow = FlowLayout(container, margin=0, spacing=16)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        self.refresh()

    def refresh(self):
        """Rebuilds the tiles from the custom image index."""
        clear_layout(self._flow)
        edited = sorted(artist_proofs.load().values(), key=lambda p: p["name"].lower())
        self._count.setText(
            f"{plural(len(edited), 'edited card')} · click one to change it" if edited
            else "No edited cards yet — use Edit card to pick one from your collection."
        )
        for proof in edited:
            card = self._collection_card(proof["set"], proof["cn"]) or {
                "name": proof["name"], "set": proof["set"], "cn": proof["cn"]}
            details = [s for s in ("front", "back") if proof.get(s)]
            details += [label.lower() for flag, label in artist_proofs.FLAGS.items() if proof.get(flag)]
            tile = ImageTile(
                image_url=scryfall.image_url(card.get("scryfall_id", "")),
                cache_name=scryfall.card_image_cache_name(card),  # shows the custom front, if any
                caption=" · ".join([proof["name"], *details]),
                payload=card,
                width=TILE_WIDTH,
                height=TILE_HEIGHT,
                radius=10,
            )
            tile.clicked.connect(self._edit)
            tile.load_image()
            self._flow.addWidget(tile)

    def _collection_card(self, set_code: str, cn: str):
        for entry in self.app.collection.cards:
            card = entry["card"]
            if str(card.get("set", "")).lower() == set_code and str(card.get("cn", "")) == str(cn):
                return card
        return None

    def _edit_new(self):
        """Edit card: pick a printing from the collection, then edit it."""
        picker = CardPickerDialog(self, self.app, "Edit card", "Click the card you want to give your own images.")
        if picker.exec() == CardPickerDialog.Accepted and picker.picked is not None:
            self._edit(picker.picked["card"])

    def _edit(self, card: dict):
        if CardImageEditorDialog(self, card).exec() == CardImageEditorDialog.Accepted:
            self.refresh()
            self.proofs_changed.emit()
