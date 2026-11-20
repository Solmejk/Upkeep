"""DecksScreen: a wrapping grid of deck tiles (commander art + name),
with active/archived and commander-format toggles, and a search by deck
name. Clicking a tile opens DeckDetailScreen (wired up in MainWindow).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QPushButton, QMenu, QLineEdit,
)

from app import MTGApp
from ui.flow_layout import FlowLayout
from ui.layout_utils import clear_layout
from ui.components.image_tile import ImageTile
import scryfall
from card_sort import name_key
from models.deck import SOURCE_MOXFIELD
from card_fields import plural
from ui.components.toggle_switch import ToggleSwitch


# Caption badge per deck source: (letter, color) shown before the deck
# name. Decks built in the Deck Maker (SOURCE_LOCAL) get none; a new import
# site gets its own entry here.
SOURCE_BADGES = {
    SOURCE_MOXFIELD: ("M", "#9b59b6"),  # purple, like the foil tint's
}

TILE_WIDTH = 220
TILE_HEIGHT = 310


class DecksScreen(QWidget):
    """Grid of clickable deck tiles, with active/format filters."""

    deck_selected = Signal(object)  # emitted with a models.deck.Deck on click
    delete_requested = Signal(object)  # emitted with a Deck via a tile's right-click menu (local decks only)
    refresh_requested = Signal()    # emitted when "Refresh decks" is clicked
    deck_imported = Signal(str)     # a decklist was imported as a local deck (its id)

    def __init__(self, app: MTGApp):
        """Builds the screen and its (initially both-on) filters, then
        does the first grid build from `app.decks`."""
        super().__init__()
        self.app = app
        self._active_only = True
        self._commander_only = True
        self._name_filter = ""  # deck name search (name_key form), "" = all

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Top bar: title + filter toggles
        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(40, 30, 40, 20)
        top_layout.setSpacing(20)

        header = QLabel("Decks")
        header.setObjectName("screenTitle")
        top_layout.addWidget(header)
        top_layout.addStretch()

        # Filter: Active only
        active_label = QLabel("Active only")
        active_label.setObjectName("filterLabel")
        top_layout.addWidget(active_label)

        self._active_toggle = ToggleSwitch(checked=True)
        self._active_toggle.toggled.connect(self._on_active_toggled)
        top_layout.addWidget(self._active_toggle)

        # Filter: Commander only
        commander_label = QLabel("Commander only")
        commander_label.setObjectName("filterLabel")
        top_layout.addWidget(commander_label)

        self._commander_toggle = ToggleSwitch(checked=True)
        self._commander_toggle.toggled.connect(self._on_commander_toggled)
        top_layout.addWidget(self._commander_toggle)

        self._import_btn = QPushButton("Import deck")
        self._import_btn.setToolTip("Paste a decklist (Moxfield format) to add it as a Deck Maker deck")
        self._import_btn.setEnabled(app.is_logged_in)  # local decks are saved per user
        self._import_btn.clicked.connect(self._on_import_clicked)
        top_layout.addWidget(self._import_btn)

        self._refresh_btn = QPushButton("Refresh decks")
        self._refresh_btn.setEnabled(app.is_logged_in)
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        top_layout.addWidget(self._refresh_btn)

        outer.addWidget(top_bar)

        # Search by deck name (plain text — not the card search syntax)
        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(40, 0, 40, 16)
        search_layout.setSpacing(0)
        search_layout.addStretch()
        self._result_count = QLabel()
        self._result_count.setObjectName("resultCount")
        search_layout.addWidget(self._result_count)
        self._search = QLineEdit()
        self._search.setObjectName("searchInput")
        self._search.setPlaceholderText("Search decks by name…")
        self._search.setFixedWidth(340)
        self._search.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self._search)
        outer.addWidget(search_row)

        # Scrollable grid
        scroll = QScrollArea()
        scroll.setObjectName("decksScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._grid_container = QWidget()
        self._flow = FlowLayout(self._grid_container, margin=0, spacing=20)
        self._grid_container.setContentsMargins(40, 0, 40, 40)

        scroll.setWidget(self._grid_container)
        outer.addWidget(scroll, 1)

        self._rebuild_grid()

    def set_refresh_enabled(self, enabled: bool):
        """Toggles the refresh button between its normal and
        "Refreshing…" (disabled) states — called by MainWindow around
        the background Moxfield fetch."""
        self._refresh_btn.setEnabled(enabled)
        self._refresh_btn.setText("Refresh decks" if enabled else "Refreshing…")

    def _on_search_changed(self, text: str):
        """Slot for the name search box: re-filters the grid to decks whose
        name contains `text` (case- and accent-insensitive)."""
        self._name_filter = name_key(text.strip())
        self._rebuild_grid()

    def _on_active_toggled(self, value: bool):
        """Slot for the "Active only" toggle: updates the filter and
        rebuilds the grid. value: the toggle's new checked state."""
        self._active_only = value
        self._rebuild_grid()

    def _on_commander_toggled(self, value: bool):
        """Slot for the "Commander only" toggle: updates the filter and
        rebuilds the grid. value: the toggle's new checked state."""
        self._commander_only = value
        self._rebuild_grid()

    def _filtered_decks(self):
        """Yields decks from self.app.decks matching the current name
        search and active/commander-only filters."""
        for deck in self.app.decks:
            if self._name_filter and self._name_filter not in name_key(deck.name):
                continue
            if self._active_only and not deck.active:
                continue
            if self._commander_only and deck.format != "commander":
                continue
            yield deck

    def _rebuild_grid(self):
        """Clears and rebuilds the tile grid from _filtered_decks(). Note
        that a deck's `format` is only known once its contents have
        loaded — MainWindow's background deck-content load calls this
        again once that data is available, which is why decks can appear
        to "pop in" shortly after the app starts."""
        clear_layout(self._flow)

        # Add tiles for filtered decks
        shown = 0
        for deck in self._filtered_decks():
            shown += 1
            commander_url = self._commander_url(deck)
            tile = ImageTile(
                image_url=commander_url,
                # the commander card's own cache name — shared with the card's
                # other images, and artist proofs apply (models.artist_proofs)
                cache_name=scryfall.card_image_cache_name(deck.commanders[0]) if deck.commanders else f"commander_{deck.deck_id}",
                caption=deck.name,
                caption_badge=SOURCE_BADGES.get(deck.source),
                payload=deck,
                width=TILE_WIDTH,
                height=TILE_HEIGHT,
                radius=12,
            )
            tile.clicked.connect(self.deck_selected.emit)
            if not deck.is_imported:  # only Deck Maker decks can be deleted
                tile.setContextMenuPolicy(Qt.CustomContextMenu)
                tile.customContextMenuRequested.connect(
                    lambda pos, t=tile: self._show_tile_menu(t, pos)
                )
            tile.load_image()
            self._flow.addWidget(tile)

        self._result_count.setText(plural(shown, "deck") if self._name_filter else "")

    def _on_import_clicked(self):
        """Import deck: the paste dialog; announces the new deck once saved."""
        from ui.components.deck_import_dialog import DeckImportDialog
        dialog = DeckImportDialog(self, self.app.username)
        if dialog.exec() and dialog.deck_id:
            self.deck_imported.emit(dialog.deck_id)

    def _show_tile_menu(self, tile, pos):
        """Right-click on a Deck Maker deck's tile: a "Delete deck" menu."""
        menu = QMenu(self)
        delete_action = menu.addAction("Delete deck")
        delete_action.triggered.connect(lambda: self.delete_requested.emit(tile.payload))
        menu.exec(tile.mapToGlobal(pos))

    def _commander_url(self, deck) -> str:
        """The deck's commander art URL for its tile, or "" if the deck
        has no commander data loaded yet."""
        if deck.commanders and "image_url" in deck.commanders[0]:
            return deck.commanders[0]["image_url"]
        return ""
