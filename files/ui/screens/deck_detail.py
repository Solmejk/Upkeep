"""DeckDetailScreen: full-page view of a single deck's contents, opened
from DecksScreen. Shows the deck's name/value, an active/archived toggle,
and its cards grouped by type in a scrollable grid (via
ui.components.card_section).
"""

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
)

import availability
import deck_stats
from card_fields import plural
from models import deck_languages
from models import token_printings
from ui.components.section_card import back_button
from ui.components.card_section import build_card_section, rebuild_card_sections, quantity_caption
from ui.components.deck_stats_row import DeckStatsRow, average_text
from ui.components.deck_elo_block import DeckEloBlock
from ui.theme import elo_color
from ui.components.language_check_dialog import LanguageCheckDialog
from ui.components.search_box import SearchBox
from ui.components.toggle_switch import ToggleSwitch
from ui.components.sticky_page import StickyHeaderPage


class DeckDetailScreen(QWidget):
    """Detail view for a single deck. Call show_deck(deck) to swap
    content — the same instance is reused for whichever deck was clicked
    in DecksScreen (see MainWindow._open_deck_detail)."""

    back_requested = Signal()  # emitted when the Back button is clicked
    card_clicked = Signal(dict)  # emitted with a card dict when a tile is clicked
    tracker_deck_clicked = Signal(object)  # the Elo block was clicked — the deck's Game Tracker popout

    def __init__(self, app=None):
        """Builds the (initially empty) screen chrome — back button,
        name/value header, active/archived toggle, and the scrollable
        section container. Populated later by show_deck(). app: the
        MTGApp, for checking deck cards against the collection."""
        super().__init__()
        self.app = app
        self.deck = None
        self._search_predicate = None  # card filter from the search box, or None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # everything above the card sections: stays put in a big window,
        # scrolls away otherwise (StickyHeaderPage, added at the end)
        top = QWidget()
        top_part = QVBoxLayout(top)
        top_part.setContentsMargins(0, 0, 0, 0)
        top_part.setSpacing(0)

        # Top bar (back button)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(40, 30, 40, 10)

        back_btn = back_button(self.back_requested.emit)
        top_bar.addWidget(back_btn)
        top_bar.addStretch()

        # Card search within this deck (Scryfall syntax)
        self._search = SearchBox("Search this deck… e.g. t:creature mv<=2", context_fn=self._search_context)
        self._search.search_changed.connect(self._on_search_changed)
        top_bar.addWidget(self._search)
        top_part.addLayout(top_bar)

        # Header (name + value on left, active toggle on right)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(40, 0, 40, 20)
        header_layout.setSpacing(20)

        # Left column: title stacked over value
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        self.title_label = QLabel()
        self.title_label.setObjectName("screenTitle")
        self.title_label.setTextFormat(Qt.RichText)  # name + Game Tracker Elo (see show_deck)
        left_layout.addWidget(self.title_label)

        self.value_label = QLabel()
        self.value_label.setObjectName("deckDetailValue")
        left_layout.addWidget(self.value_label)

        self._avg_mv_label = QLabel()
        self._avg_mv_label.setObjectName("settingsLabel")
        left_layout.addWidget(self._avg_mv_label)

        # Moxfield decks: cards whose printing is owned in another / several
        # languages — click to confirm which copies the deck uses
        self._language_btn = QPushButton()
        self._language_btn.setObjectName("languageWarning")
        self._language_btn.setCursor(Qt.PointingHandCursor)
        self._language_btn.clicked.connect(self._open_language_check)
        left_layout.addWidget(self._language_btn, 0, Qt.AlignLeft)

        header_layout.addWidget(left_column)
        header_layout.addStretch()

        # Right: active label + toggle
        toggle_row = QWidget()
        toggle_layout = QHBoxLayout(toggle_row)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(8)

        self.active_label = QLabel("Active")
        self.active_label.setObjectName("activeLabel")
        toggle_layout.addWidget(self.active_label)

        self.active_toggle = ToggleSwitch()
        self.active_toggle.toggled.connect(self._toggle_active)
        toggle_layout.addWidget(self.active_toggle)

        header_layout.addWidget(toggle_row)

        top_part.addWidget(header)

        # Stats row: mana curve, color balance, mana production
        self._stats_row = DeckStatsRow()
        self._stats_row.setContentsMargins(40, 0, 40, 24)
        self._elo_block = DeckEloBlock()  # Game Tracker Elo, first in the stats row
        self._elo_block.clicked.connect(self.tracker_deck_clicked.emit)
        self._stats_row.insert_first(self._elo_block)
        top_part.addWidget(self._stats_row)

        # Scrollable card sections
        scroll = QScrollArea()
        scroll.setObjectName("decksScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._sections_container = QWidget()
        self._sections_layout = QVBoxLayout(self._sections_container)
        self._sections_layout.setContentsMargins(40, 0, 40, 40)
        self._sections_layout.setSpacing(24)
        self._sections_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self._sections_container)
        self._page = StickyHeaderPage(top, scroll)
        outer.addWidget(self._page, 1)

    def show_deck(self, deck):
        """Swaps the screen to show `deck`: updates the header/toggle and
        rebuilds the card grid. `deck` is a models.deck.Deck with its
        contents already loaded (callers load it first if needed)."""
        self.deck = deck
        self._search.clear()
        self._search_predicate = None
        self._page.verticalScrollBar().setValue(0)  # a new deck starts at the top (header showing)
        self.title_label.setText(deck.name)
        self.value_label.setText(f"€{deck.value:.2f}")
        self._avg_mv_label.setText(average_text(deck.cards))
        commander_names = {c["name"] for c in deck.commanders}
        self._stats_row.set_cards(deck.cards, deck_stats.commander_identity(deck.cards, commander_names))
        tracker_stats = self._elo_block.show_deck(self.app, deck)
        # the title: "Deck name  1522 Elo" (just the name without recorded games)
        if tracker_stats is None:
            self.title_label.setText(html.escape(deck.name))
        else:
            self.title_label.setText(
                f"{html.escape(deck.name)}&nbsp;&nbsp;"
                f"<span style='color:{elo_color(tracker_stats.elo)}'>{tracker_stats.elo:.0f}</span>"
                f"<span style='color:#888888; font-size:14px; font-weight:normal'> Elo</span>")
        self._display_cards = self._cards_with_languages()
        self._refresh_language_warning()
        self._refresh_active_button()
        self.rebuild_sections()

    def _search_context(self) -> dict:
        """card_search context: is:unique — the collection holds exactly
        one copy of the card (is:used isn't meaningful here: every card in
        a deck is in a deck)."""
        if not self.app:
            return {}
        return {"is": {"unique": availability.unique_check(self.app.collection.cards)}}

    def _cards_with_languages(self) -> list:
        """The deck's cards as shown (tiles, card popup, search), each with
        the language of the copies it uses: the confirmed answer for
        Moxfield decks (see models.deck_languages), the stored language for
        (older) local decks. A card using copies in several languages gets
        "languages" {code: copies} instead (the popup shows the breakdown)."""
        cards = []
        for card in self.deck.cards:
            split = deck_languages.language_split(self.deck, card)
            if len(split) == 1:
                cards.append({**card, "language": next(iter(split))})
            else:
                cards.append({**card, "languages": split})
        return cards

    def _language_conflicts(self) -> list:
        if not self.deck or not self.app:
            return []
        return deck_languages.conflicts(self.deck, self.app.collection.cards)

    def _refresh_language_warning(self):
        """Shows "⚠ N cards need a language check" while any card's
        language is unconfirmed; once all are, a quiet "Card languages
        confirmed" (still clickable, to change answers); hidden if the
        deck has no such cards."""
        conflicts = self._language_conflicts()
        unconfirmed = sum(1 for c in conflicts if c["answer"] is None)
        if not conflicts:
            self._language_btn.hide()
            return
        if unconfirmed:
            self._language_btn.setText(
                f"⚠  {plural(unconfirmed, 'card')} need{'s' if unconfirmed == 1 else ''} a language check"
            )
            self._language_btn.setProperty("confirmed", False)
        else:
            self._language_btn.setText("✓  Card languages confirmed")
            self._language_btn.setProperty("confirmed", True)
        self._language_btn.style().unpolish(self._language_btn)  # re-apply [confirmed] style
        self._language_btn.style().polish(self._language_btn)
        self._language_btn.show()

    def _open_language_check(self):
        """Warning click: asks which language of copy the deck uses for
        each conflicting card, and stores the answers."""
        conflicts = self._language_conflicts()
        if not conflicts:
            return
        dialog = LanguageCheckDialog(self, self.deck.name, conflicts)
        if dialog.exec() != LanguageCheckDialog.Accepted:
            return
        deck_languages.save_answers(self.deck.deck_id, dialog.answers())
        self._refresh_language_warning()
        self._display_cards = self._cards_with_languages()
        self.rebuild_sections()  # tiles/popups/search use the new languages


    def _refresh_active_button(self):
        """Syncs the active/archived toggle and label to self.deck's
        current state, without re-triggering _toggle_active (blocked
        signals) since this is a display update, not a user action."""
        self.active_toggle.blockSignals(True)
        self.active_toggle.setChecked(self.deck.active)
        self.active_toggle.blockSignals(False)
        self.active_label.setText("Active" if self.deck.active else "Archived")

    def _toggle_active(self, is_active: bool):
        """Slot for the active/archived toggle: persists the change on
        the deck (Deck.set_active writes it to deck_states.json) and
        updates the label. is_active: the toggle's new checked state."""
        if not self.deck:
            return
        self.deck.set_active(is_active)
        self.active_label.setText("Active" if is_active else "Archived")

    def _on_search_changed(self, predicate):
        """Slot for SearchBox.search_changed: re-filters the deck's cards
        (None shows them all)."""
        self._search_predicate = predicate
        if self.deck:
            self.rebuild_sections()

    def rebuild_sections(self):
        """Rebuilds the type-grouped card grid for the current deck —
        only cards matching the search, if there is one. Its commanders
        form their own bucket; the rest are grouped by type."""
        cards = self._display_cards
        if self._search_predicate is not None:
            cards = [c for c in cards if self._search_predicate(c)]
            total = sum(c["quantity"] for c in cards)
            self._search.set_result_text(plural(total, "card"))
        commander_names = {c["name"] for c in self.deck.commanders}
        rebuild_card_sections(
            self._sections_layout,
            cards,
            commander_names,
            caption_fn=quantity_caption,
            on_click=self.card_clicked.emit,
        )
        # Tokens the deck makes (Moxfield decks), below the cards — hidden
        # while searching, since the search is over the deck's cards
        tokens = [token_printings.apply(t) for t in self.deck.tokens]  # your default printings
        if tokens and self._search_predicate is None:
            self._sections_layout.addWidget(build_card_section(
                "Tokens", len(tokens), tokens, lambda t: t["name"], self.card_clicked.emit))
