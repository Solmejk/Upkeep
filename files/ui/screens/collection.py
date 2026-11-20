"""CollectionScreen: stats header (totals, value, rarity/color breakdown)
plus a searchable, virtualized grid of every card in the collection —
see ui.components.card_grid_view for the grid itself.
"""

from PySide6.QtCore import Signal, QPoint
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

import availability
import card_sort
from card_fields import plural
from ui.components.sort_button import build_sort_button
from languages import entry_language
from models.deck_draft import deck_card_printing_key, entry_printing_key
from app import MTGApp
from models import price_history, value_history
from ui.components.card_grid_view import CardGridView
from ui.components.color_pie import ColorPie, ColorLegend
from ui.components.value_chart import ValueChart
from ui.components.movers_panel import MoversPanel
from ui.components.card_grid_view import entry_payload
from ui.components.search_box import SearchBox

def merge_languages(entries: list) -> list:
    """Collection entries -> one entry per printing + finish, copies in
    different languages combined: quantity summed, and "languages"
    {code: copies} added (e.g. 1 English + 1 French Surveyor's Scope ->
    one "2x" tile). Entries are copied, not modified."""
    merged = {}
    for entry in entries:
        key = entry_printing_key(entry)[:3]  # set, cn, finish — not language
        language = entry_language(entry)
        if key not in merged:
            merged[key] = {**entry, "quantity": 0, "languages": {}}
        target = merged[key]
        target["quantity"] += entry["quantity"]
        target["languages"][language] = target["languages"].get(language, 0) + entry["quantity"]
    return list(merged.values())


class CollectionScreen(QWidget):
    """Collection stats + virtualized searchable card grid."""

    card_clicked = Signal(dict)  # emitted with a flat card payload dict on click
    refresh_requested = Signal() # emitted when "Refresh collection" is clicked
    entry_menu_requested = Signal(dict, QPoint)  # right-click on a tile (merged entry, position)

    def __init__(self, app: MTGApp, cards: list | None = None, title: str = "Collection",
                 refreshable: bool = True, extra_stats: str = ""):
        """Builds and populates the screen from `app.collection` — rebuilt
        from scratch (not updated in place) whenever the underlying data
        changes, see MainWindow._rebuild_data_screens.

        Also shows other card lists in collection-entry shape (an imported
        purchase — see ui.screens.purchases): cards replaces the
        collection, title the header, refreshable=False hides the Moxfield
        refresh button, extra_stats (HTML) is appended to the stats text."""
        super().__init__()
        self.app = app
        self._cards = app.collection.cards if cards is None else cards
        self._extra_stats = extra_stats

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header: title + refresh button
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(40, 30, 40, 10)

        header = QLabel(title)
        header.setObjectName("screenTitle")
        header_layout.addWidget(header)
        header_layout.addStretch()

        self._refresh_btn = QPushButton("Refresh collection")
        self._refresh_btn.setEnabled(app.is_logged_in)
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        self._refresh_btn.setVisible(refreshable)
        header_layout.addWidget(self._refresh_btn)
        self._header_layout = header_layout  # embedders may add buttons (see PurchasesScreen)

        outer.addWidget(header_row)

        # Stats column: text on top, pie + legend below
        stats_column = QWidget()
        stats_layout = QVBoxLayout(stats_column)
        stats_layout.setContentsMargins(40, 0, 40, 20)
        stats_layout.setSpacing(16)

        self._stats_label = QLabel()
        self._stats_label.setObjectName("collectionStats")
        self._stats_label.setWordWrap(True)
        stats_layout.addWidget(self._stats_label)

        # Pie + legend side-by-side
        chart_block = QWidget()
        chart_layout = QHBoxLayout(chart_block)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(12)

        self._color_pie = ColorPie()
        self._color_pie.setFixedSize(160, 160)
        chart_layout.addWidget(self._color_pie)

        self._color_legend = ColorLegend()
        self._color_legend.setFixedWidth(120)
        chart_layout.addWidget(self._color_legend)

        # Value over time — only for the real collection (a purchase has
        # no history); one point per price update, see models.value_history
        if cards is None and app.is_logged_in:
            value_history.seed_if_empty(app.username, self._cards)
            price_history.record_saved_prices()  # no-op unless there's a new price day
            chart_layout.addSpacing(8)  # the chart has its own left padding (axis labels)
            self._value_chart = ValueChart()
            self._value_chart.setFixedHeight(180)
            self._value_chart.setMaximumWidth(640)
            self._value_chart.setHistory(value_history.load(app.username))
            chart_layout.addWidget(self._value_chart, 1)

            # Biggest riser / faller since the previous price day
            chart_layout.addSpacing(16)
            movers = MoversPanel(price_history.movers(merge_languages(self._cards)))
            movers.tile_clicked.connect(lambda tile: self._on_card_clicked(entry_payload(tile)))
            chart_layout.addWidget(movers)
            # leftover width goes to the right edge, not into gaps between the charts
            chart_layout.addStretch()
        else:
            chart_layout.addStretch()  # keep pie + legend left-aligned

        stats_layout.addWidget(chart_block)
        outer.addWidget(stats_column)

        # Search bar — right-aligned (Scryfall syntax, see card_search)
        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(40, 0, 40, 16)

        search_layout.addStretch()

        self._search = SearchBox("Search… e.g. t:creature c:g mv<=3", context_fn=self._search_context)
        self._search.search_changed.connect(self._on_search_changed)
        search_layout.addWidget(self._search)

        # Sort — same button as the Availability screen / Deck Maker
        self._sort_mode = card_sort.SORT_NAME
        self._sort_btn = build_sort_button(card_sort.SORT_LABELS, self._sort_mode, self._on_sort_changed)
        search_layout.addSpacing(8)
        search_layout.addWidget(self._sort_btn)

        outer.addWidget(search_row)

        # Card grid (virtualized)
        self._grid = CardGridView()
        self._grid.setContentsMargins(40, 0, 40, 40)
        self._merged_cards = merge_languages(self._cards)  # one tile per printing + finish
        self._search_predicate = None
        self._grid.setCardData(card_sort.sort_entries(self._merged_cards, self._sort_mode))
        self._grid.card_clicked.connect(self._on_card_clicked)
        self._grid.entry_menu_requested.connect(self.entry_menu_requested.emit)
        outer.addWidget(self._grid, 1)

        self._render_stats()

    def set_cards(self, cards: list, extra_stats: str | None = None):
        """Replaces the shown cards in place (e.g. a card removed from a
        purchase), keeping the search, sort and scroll position."""
        self._cards = cards
        if extra_stats is not None:
            self._extra_stats = extra_stats
        scroll = self._grid.verticalScrollBar().value()
        self._merged_cards = merge_languages(cards)
        self._grid.setCardData(card_sort.sort_entries(self._merged_cards, self._sort_mode))
        self._grid.setFilter(self._search_predicate)
        self._render_stats()
        self._grid.verticalScrollBar().setValue(scroll)

    def set_refresh_enabled(self, enabled: bool):
        """Toggles the refresh button between its normal and
        "Refreshing…" (disabled) states — called by MainWindow around
        the background Moxfield fetch."""
        self._refresh_btn.setEnabled(enabled)
        self._refresh_btn.setText("Refresh collection" if enabled else "Refreshing…")

    def _on_card_clicked(self, card: dict):
        """Slot for the grid's card_clicked: adds the "used in decks"
        breakdown before re-emitting for CardModal to display — for this
        exact printing + finish, per language of the copies owned (the
        Availability screen, checking a decklist, goes by name)."""
        used_in = []
        for language in card.get("languages") or {card.get("language", "en"): card["quantity"]}:
            for use in availability.used_in_decks_by_printing(self.app.decks, {**card, "language": language}):
                used_in.append({**use, "language": language})
        self.card_clicked.emit({**card, "used_in_decks": used_in})

    def _search_context(self) -> dict:
        """card_search context: is:used — a tile (one printing + finish,
        all languages) is used when every copy of it is in an active deck
        (confirmed card languages and all, see models.deck_languages); and
        is:unique — exactly one copy of the card owned in total."""
        used = {}  # (set, cn, finish) -> copies in active decks
        for deck in self.app.decks:
            if not deck.active:
                continue
            for card in deck.cards:
                key = deck_card_printing_key(card)[:3]
                used[key] = used.get(key, 0) + card["quantity"]
        return {"is": {
            "used": lambda entry: used.get(entry_printing_key(entry)[:3], 0) >= entry["quantity"],
            "unique": availability.unique_check(self.app.collection.cards),
        }}

    def _on_sort_changed(self, mode: str):
        """Sort menu pick: re-sorts the grid (keeping the current search)."""
        self._sort_mode = mode
        self._grid.setCardData(card_sort.sort_entries(self._merged_cards, mode))
        self._grid.setFilter(self._search_predicate)

    def _on_search_changed(self, predicate):
        """Slot for SearchBox.search_changed: filters the grid (None =
        show everything) and shows the result count. SearchBox only
        emits once typing pauses, so a fast typist doesn't queue image
        fetches for intermediate results."""
        self._search_predicate = predicate
        self._grid.setFilter(predicate)
        if predicate is None:
            return
        showing = self._grid.filtered_count()
        self._search.set_result_text(plural(showing, "result"))

    def _render_stats(self):
        """Computes and displays the stats header (total/unique cards,
        total value, rarity breakdown) and feeds the color-pie/legend
        from the full (unfiltered) collection."""
        cards = self._cards
        total_cards = sum(c["quantity"] for c in cards)
        different_cards = len({c["card"]["name"] for c in cards})  # by name
        versions = len(self._merged_cards)  # printing + finish = tiles in the grid

        total_value = value_history.collection_value(cards)  # foil price for foils

        rarity_counts = {"common": 0, "uncommon": 0, "rare": 0, "mythic": 0}
        for entry in cards:
            rarity = entry["card"].get("rarity", "")
            if rarity in rarity_counts:
                rarity_counts[rarity] += entry["quantity"]

        color_counts = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
        for entry in cards:
            colors = entry["card"].get("colors", [])
            qty = entry["quantity"]
            if not colors:
                color_counts["C"] += qty
            else:
                for c in colors:
                    if c in color_counts:
                        color_counts[c] += qty

        text = (
            f"<b>{total_cards}</b> cards · <b>{different_cards}</b> different cards · "
            f"<b>{versions}</b> versions<br>"
            f"<b>€{total_value:,.2f}</b><br><br>"
            f"Common: {rarity_counts['common']} · "
            f"Uncommon: {rarity_counts['uncommon']} · "
            f"Rare: {rarity_counts['rare']} · "
            f"Mythic: {rarity_counts['mythic']}"
        )
        self._stats_label.setText(text + self._extra_stats)

        self._color_pie.setCounts(color_counts)
        self._color_legend.setCounts(color_counts)
