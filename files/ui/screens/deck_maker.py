"""DeckMakerScreen: build new commander decks from cards in the
collection. Three pages in a stack:

1. Start — "Create new deck".
2. Choose commander — the collection's commander-eligible cards
   (legendary creatures etc., see card_search's is:commander), browsable
   or searchable with the usual Scryfall-syntax box. Clicking one picks it.
3. Build deck — the commander and deck list on the left; on the right a
   search over the collection showing only cards that can still go in
   the deck (commander-legal, inside the commander's color identity,
   not already in it — see DeckDraft.can_add) and match the search.
   Clicking a result adds it. "Show card images" swaps the results for
   the deck shown as card images, each with a Remove button; the deck
   list also removes on double-click / right-click.
"""

from urllib.parse import quote

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
    QMessageBox, QListWidget, QListWidgetItem, QMenu, QScrollArea, QCheckBox,
    QInputDialog, QSizePolicy,
)

import card_search
from card_fields import face_field, plural
from card_sort import name_key
import scryfall
from app import MTGApp
from models import deck_languages, local_decks
from models.deck_draft import DeckDraft, DECK_SIZE
from printing import entry_printing_key, deck_card_printing_key
from models.local_decks import BASIC_LAND_IMAGE_URL
from ui.components.section_card import back_button
from ui.screens.availability import STATUS_COLORS
import availability
from ui.card_type import group_cards
from ui.components.basic_lands_dialog import BasicLandsDialog
from ui.components.card_section import quantity_caption
from ui.components.color_pie import COLOR_SWATCHES
from ui.components.deck_stats_row import DeckStatsRow
from ui.components.sort_button import build_sort_button
from ui.flow_layout import FlowLayout
from ui.components.card_grid_view import CardGridView
from ui.components.image_tile import ImageTile
from ui.components.search_box import ERROR_COLOR, SearchBox
from ui.layout_utils import clear_layout
from ui import theme

# Commander-eligible and legal in the commander format.
_IS_COMMANDER = card_search.compile_query("is:commander f:commander")
_IS_COMMANDER_LEGAL = card_search.compile_query("f:commander")
_IS_LAND = card_search.compile_query("t:land")  # the "Exclude lands" checkbox = -t:land

COLOR_NAMES = {code: name for code, (_, name) in COLOR_SWATCHES.items()}  # "W" -> "White", ...
ACCENT = theme.ACCENT
OVER_COLOR = ERROR_COLOR  # card counter over 100 (it is amber normally)
USED_COLOR = STATUS_COLORS[availability.USED]  # same yellow as the Availability screen
NAME_ROLE = Qt.UserRole  # deck list items: the card name (None for headers)
CARD_WIDTH = 280  # adding cards + deck image view: double the Collection grid's 140
DECK_VIEW_TILE_WIDTH = CARD_WIDTH
DECK_VIEW_TILE_HEIGHT = 392



# Sort menu — same button and "<field> high-low / low-high" style as the
# Availability screen's (ui.components.sort_button).
SORT_NAME = "name"
SORT_LABELS = {  # mode -> menu label, in menu order
    SORT_NAME: "Name",
    "cmc_asc": "Mana value low-high",
    "cmc_desc": "Mana value high-low",
    "power_desc": "Power high-low",
    "power_asc": "Power low-high",
    "toughness_desc": "Toughness high-low",
    "toughness_asc": "Toughness low-high",
}


def _card_number(card: dict, field: str):
    """`field` of a Moxfield card object as a number, or None if it has
    none (non-creatures, "*" power...). Double-faced cards keep these on
    their faces — the front face is used."""
    try:
        return float(face_field(card, field))
    except (TypeError, ValueError):
        return None


def _sorted_results(entries: list, mode: str) -> list:
    """Sorts collection entries per a SORT_LABELS mode ("<field>_asc" /
    "<field>_desc", or SORT_NAME). Ties are by name; cards without a
    value for the field (non-creatures, "*" power...) go last either way."""
    by_name = sorted(entries, key=lambda e: name_key(e["card"]["name"]))
    if mode == SORT_NAME:
        return by_name
    field, direction = mode.rsplit("_", 1)
    with_value = [e for e in by_name if _card_number(e["card"], field) is not None]
    without_value = [e for e in by_name if _card_number(e["card"], field) is None]
    # stable sort (also with reverse=True): equal values stay in name order
    with_value.sort(key=lambda e: _card_number(e["card"], field), reverse=direction == "desc")
    return with_value + without_value


def _view_card(card: dict, quantity: int, printing: tuple | None = None) -> dict:
    """A Moxfield card object -> the flat dict the deck image view (and
    group_cards / quantity_caption / the card info popout) work with.
    printing: the deck card's printing key — Remove takes out that exact
    version, and it decides the "used elsewhere" tint and the price."""
    prices = card.get("prices") or {}
    is_foil = printing is not None and printing[2] in ("foil", "etched")
    language = printing[3] if printing is not None else (card.get("lang") or "en")
    price = (prices.get("eur_foil") if is_foil else None) or prices.get("eur") or 0
    return {
        "printing": printing,
        "name": card["name"],
        "set": card.get("set", ""),
        "cn": card.get("cn", ""),
        "type_line": card.get("type_line", ""),
        "quantity": quantity,
        "price": price,
        "language": language,
        "image_url": scryfall.image_url(card.get("scryfall_id", "")),
    }


def _basic_land_view_card(name: str, quantity: int) -> dict:
    """Same as _view_card, for a basic land added outside the collection."""
    return {
        "name": name,
        "set": "basic",  # -> image cache name "card_basic_<name>"
        "cn": name,
        "type_line": "Basic Land",
        "quantity": quantity,
        "image_url": BASIC_LAND_IMAGE_URL.format(quote(name)),
    }


class DeckMakerScreen(QWidget):
    card_clicked = Signal(dict)  # card info popout payload (see _show_card_info)
    deck_saved = Signal()  # a deck was written to disk — MainWindow reloads the deck lists

    def __init__(self, app: MTGApp):
        """Builds the three pages; starts on the Start page."""
        super().__init__()
        self.app = app
        self.draft = None  # DeckDraft being built, or None
        self._commander_search = None  # predicate from the commander page's search box
        self._card_search = None  # predicate from the build page's search box

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pages = QStackedWidget()
        layout.addWidget(self._pages)

        self._start_page = self._build_start_page()
        self._commander_page = self._build_commander_page()
        self._build_page = self._build_build_page()
        for page in (self._start_page, self._commander_page, self._build_page):
            self._pages.addWidget(page)

        self.reload_collection()

    def reload_collection(self):
        """Re-reads everything derived from app.collection — called by
        MainWindow after a refresh/login/cache-clear instead of
        rebuilding this screen, so a draft in progress isn't lost."""
        cards = self.app.collection.cards

        # One result per owned version (printing + finish), so a free foil
        # isn't hidden behind a non-foil that's used elsewhere.
        self._addable_pool = [e for e in cards if _IS_COMMANDER_LEGAL(e)]
        self._owned_by_printing = {}  # printing key -> copies owned
        for entry in cards:
            key = entry_printing_key(entry)
            self._owned_by_printing[key] = self._owned_by_printing.get(key, 0) + entry["quantity"]

        self._commander_candidates = [e for e in cards if _IS_COMMANDER(e)]
        self._commander_grid.setCardData(self._commander_candidates)
        self._apply_commander_search()
        if self.draft:
            self._refresh_results()

    # ------------------------------------------------------------ pages

    def _build_start_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(16)

        title = QLabel("Deck Maker")
        title.setObjectName("screenTitle")
        outer.addWidget(title)

        description = QLabel(
            "Build a new Commander deck from cards in your collection. "
            "You start by choosing the commander."
        )
        description.setObjectName("settingsDescription")
        description.setWordWrap(True)
        outer.addWidget(description)

        button_row = QHBoxLayout()
        create_btn = QPushButton("Create new deck")
        create_btn.clicked.connect(self._start_new_deck)
        button_row.addWidget(create_btn)
        button_row.addStretch()
        outer.addLayout(button_row)

        outer.addStretch()
        return page

    def _build_commander_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(40, 30, 40, 10)
        back_btn = back_button(self._on_commander_back)
        top_bar.addWidget(back_btn)
        top_bar.addStretch()
        outer.addLayout(top_bar)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(40, 0, 40, 10)
        title = QLabel("Choose your commander")
        title.setObjectName("screenTitle")
        header_layout.addWidget(title)
        hint = QLabel("Legendary creatures and other cards that can be your commander, from your collection. Click one to pick it.")
        hint.setObjectName("settingsDescription")
        hint.setWordWrap(True)
        header_layout.addWidget(hint)
        outer.addWidget(header)

        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(40, 0, 40, 16)
        search_layout.addStretch()
        self._commander_search_box = SearchBox("Search commanders… e.g. id<=esper",
                                               context_fn=self._search_context)
        self._commander_search_box.search_changed.connect(self._on_commander_search_changed)
        search_layout.addWidget(self._commander_search_box)
        outer.addWidget(search_row)

        self._commander_grid = CardGridView(cell_width=CARD_WIDTH)
        self._commander_grid.setContentsMargins(40, 0, 40, 40)
        self._commander_grid.entry_clicked.connect(self._on_commander_picked)
        outer.addWidget(self._commander_grid, 1)

        return page

    def _build_build_page(self) -> QWidget:
        """The Build deck page's fixed chrome; the draft-specific parts
        are filled in by _refresh_draft_view / _refresh_results."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(40, 30, 40, 40)
        outer.setSpacing(12)

        top_bar = QHBoxLayout()
        change_btn = QPushButton("← Change commander")
        change_btn.setObjectName("backButton")
        change_btn.clicked.connect(lambda: self._pages.setCurrentWidget(self._commander_page))
        top_bar.addWidget(change_btn)
        top_bar.addStretch()
        save_btn = QPushButton("Save deck")
        save_btn.clicked.connect(self._save_draft)
        top_bar.addWidget(save_btn)
        top_bar.addSpacing(8)
        self._discard_btn = QPushButton("Discard deck")
        self._discard_btn.setObjectName("backButton")
        self._discard_btn.clicked.connect(self._discard_draft)
        top_bar.addWidget(self._discard_btn)
        outer.addLayout(top_bar)

        header = QHBoxLayout()
        self._draft_title = QLabel()
        self._draft_title.setObjectName("screenTitle")
        header.addWidget(self._draft_title)
        header.addStretch()
        self._draft_count = QLabel()
        self._draft_count.setObjectName("deckDetailValue")
        header.addWidget(self._draft_count)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(30)

        # Left: commander + deck list
        left = QWidget()
        left.setFixedWidth(300)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self._commander_slot = QVBoxLayout()  # holds the commander's ImageTile
        self._commander_slot.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(self._commander_slot)

        self._identity_label = QLabel()
        self._identity_label.setObjectName("settingsLabel")
        left_layout.addWidget(self._identity_label)

        self._view_toggle = QPushButton("Show card images")
        self._view_toggle.clicked.connect(self._toggle_deck_view)
        left_layout.addWidget(self._view_toggle)

        self._deck_list = QListWidget()
        self._deck_list.setObjectName("deckList")
        self._deck_list.setToolTip("Double-click or right-click a card to remove one copy")
        self._deck_list.itemDoubleClicked.connect(self._on_deck_item_double_clicked)
        self._deck_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._deck_list.customContextMenuRequested.connect(self._on_deck_list_menu)
        left_layout.addWidget(self._deck_list, 1)

        list_hint = QLabel("Double-click or right-click a card to remove it.")
        list_hint.setObjectName("settingsDescription")
        left_layout.addWidget(list_hint)

        body.addWidget(left)

        # Right: feedback/search row, then either the results grid (adding
        # cards) or the deck as card images — see _toggle_deck_view
        right = QVBoxLayout()
        right.setSpacing(8)

        # The search box is two lines tall (result count above the field),
        # so everything else lines up with the bottom of the field.
        search_row = QHBoxLayout()
        basics_btn = QPushButton("Add basic lands")
        basics_btn.clicked.connect(self._edit_basic_lands)
        search_row.addWidget(basics_btn, 0, Qt.AlignBottom)
        search_row.addSpacing(12)
        self._feedback = QLabel()
        self._feedback.setObjectName("resultCount")
        # takes whatever width is free — a long message mustn't widen the
        # page (the full text is in the tooltip)
        self._feedback.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        search_row.addWidget(self._feedback, 1, Qt.AlignBottom)
        search_row.addStretch()

        self._exclude_lands = QCheckBox("Exclude lands")
        self._exclude_lands.setToolTip("Hide lands from the results — same as adding -t:land to the search")
        self._exclude_lands.toggled.connect(lambda _: self._refresh_results(keep_scroll=False))
        search_row.addWidget(self._exclude_lands, 0, Qt.AlignBottom)
        search_row.addSpacing(12)

        self._card_search_box = SearchBox(
            "Add cards… name, or e.g. t:creature mv<=3", width=380, status_above=True,
            context_fn=self._search_context,
        )
        self._card_search_box.search_changed.connect(self._on_card_search_changed)
        search_row.addWidget(self._card_search_box, 0, Qt.AlignBottom)

        self._sort_mode = SORT_NAME
        self._sort_btn = build_sort_button(SORT_LABELS, self._sort_mode, self._on_sort_changed)
        search_row.addSpacing(8)
        search_row.addWidget(self._sort_btn, 0, Qt.AlignBottom)
        right.addLayout(search_row)

        self._right_stack = QStackedWidget()

        self._used_elsewhere = {}  # see _compute_used_elsewhere
        self._results_grid = CardGridView(cell_width=CARD_WIDTH, tint_fn=self._result_tint)
        self._results_grid.entry_clicked.connect(self._on_result_clicked)
        self._right_stack.addWidget(self._results_grid)

        self._deck_view = QScrollArea()
        self._deck_view.setObjectName("decksScroll")
        self._deck_view.setWidgetResizable(True)
        self._deck_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        deck_view_container = QWidget()
        self._deck_sections = QVBoxLayout(deck_view_container)
        self._deck_sections.setContentsMargins(0, 0, 0, 0)
        self._deck_sections.setSpacing(24)
        self._deck_sections.setAlignment(Qt.AlignTop)
        self._deck_view.setWidget(deck_view_container)
        self._right_stack.addWidget(self._deck_view)

        right.addWidget(self._right_stack, 1)

        body.addLayout(right, 1)
        outer.addLayout(body, 1)
        return page

    # ---------------------------------------------------- commander page

    def _start_new_deck(self):
        """Start page → Choose commander, for a fresh draft."""
        self.draft = None
        self._commander_search_box.clear()
        self._commander_search = None
        self._apply_commander_search()
        self._pages.setCurrentWidget(self._commander_page)

    def _on_commander_back(self):
        """Back from Choose commander: to the draft if one is in
        progress (i.e. we came from "Change commander"), else to Start."""
        self._pages.setCurrentWidget(self._build_page if self.draft else self._start_page)

    def _on_commander_search_changed(self, predicate):
        self._commander_search = predicate
        self._apply_commander_search()

    def _apply_commander_search(self):
        """Filters the commander grid by its search (if any) and shows
        how many commanders match."""
        self._commander_grid.setFilter(self._commander_search)
        count = self._commander_grid.filtered_count()
        self._commander_search_box.set_result_text(plural(count, "commander"))

    def open_draft(self, draft: DeckDraft, left_out: list[str]) -> bool:
        """Opens `draft` (from models.deck_editing — an existing deck, or a
        copy of one) on the build page. Asks first if another draft is open.
        left_out: cards that couldn't be added, shown in a message. Returns
        False if the user kept the current draft instead."""
        if self.draft is not None:
            reply = QMessageBox.question(
                self, "Replace deck",
                f"You're working on \"{self.draft.name}\" in the Deck Maker. "
                f"Open \"{draft.name}\" instead? Unsaved changes are lost.",
            )
            if reply != QMessageBox.Yes:
                return False
        self.draft = draft
        self._card_search_box.clear()
        self._card_search = None
        self._show_deck_view(False)
        self._refresh_draft_view()
        self._refresh_results(keep_scroll=False)
        self._pages.setCurrentWidget(self._build_page)
        if draft.deck_id:
            self._set_feedback(f"Editing \"{draft.name}\" — Save deck updates it")
        else:
            self._set_feedback(f"Editing a copy — Save deck creates \"{draft.name}\" as your own deck")
        if left_out:
            QMessageBox.information(
                self, "Some cards left out",
                f"{plural(len(left_out), 'card')} couldn't be added — the Deck Maker only uses "
                "cards from your collection:\n\n" + "\n".join(left_out),
            )
        return True

    def _on_commander_picked(self, entry: dict):
        """Commander grid click: starts a new draft with `entry` as
        commander, or swaps the commander of the draft in progress
        (dropping cards outside the new color identity)."""
        if self.draft is None:
            self.draft = DeckDraft(entry)
            self._card_search_box.clear()
            self._card_search = None
            self._set_feedback("")
            self._show_deck_view(False)
            self._refresh_draft_view()
            self._refresh_results(keep_scroll=False)
        else:
            dropped = self.draft.set_commander(entry)
            if dropped:
                QMessageBox.information(
                    self, "Cards removed",
                    f"Removed {plural(len(dropped), 'card')} outside "
                    f"{entry['card']['name']}'s color identity:\n\n" + "\n".join(sorted(dropped)),
                )
            self._refresh_draft_view()
            self._refresh_results(keep_scroll=False)
        self._pages.setCurrentWidget(self._build_page)

    # ------------------------------------------------------- build page

    def _refresh_draft_view(self):
        """Updates the title, card count, commander tile, identity, and
        deck list from self.draft."""
        draft = self.draft
        card = draft.commander["card"]

        if draft.deck_id:
            self._draft_title.setText(f"Deck: {draft.name}")
            self._discard_btn.setText("Close deck")
        else:
            self._draft_title.setText(f"New deck: {draft.name}")
            self._discard_btn.setText("Discard deck")
        self._set_card_count(draft.card_count)

        clear_layout(self._commander_slot)
        self._used_elsewhere = self._compute_used_elsewhere()
        commander_key = entry_printing_key(draft.commander)
        tile = ImageTile(
            image_url=scryfall.image_url(card.get("scryfall_id", "")),
            cache_name=scryfall.card_image_cache_name(card),
            caption="Commander",
            payload=_view_card(card, 1, commander_key),
            width=200,
            height=279,
            radius=12,
            status_color=USED_COLOR if self._used_info_for_key(commander_key) else None,
        )
        tile.clicked.connect(self._show_card_info)
        tile.load_image()
        self._commander_slot.addWidget(tile, 0, Qt.AlignHCenter)

        identity = draft.color_identity
        identity_text = ", ".join(COLOR_NAMES[c] for c in identity) if identity else "Colorless"
        self._identity_label.setText(f"Color identity: {identity_text}")

        self._refresh_deck_list()
        if self._right_stack.currentWidget() is self._deck_view:
            self._rebuild_deck_view()

    def _set_card_count(self, count: int):
        """The "N / 100" counter: "100 / 100 ✓" when it's exactly right,
        and red "105 / 100 · 5 to cut" over (going over is allowed while
        gathering options)."""
        if count > DECK_SIZE:
            self._draft_count.setText(f"{count} / {DECK_SIZE} · {count - DECK_SIZE} to cut")
            self._draft_count.setStyleSheet(f"color: {OVER_COLOR};")
        else:
            self._draft_count.setText(f"{count} / {DECK_SIZE}" + (" ✓" if count == DECK_SIZE else ""))
            self._draft_count.setStyleSheet("")

    def _refresh_deck_list(self):
        """Rebuilds the deck list: commander first, then the other cards
        grouped by type (same buckets as the deck detail screen)."""
        draft = self.draft
        self._deck_list.clear()

        commander_name = draft.commander["card"]["name"]
        by_name = {}  # one line per card name, even with several printings
        for c in draft.cards:
            name = c["card"]["name"]
            line = by_name.setdefault(name, {"name": name, "type_line": c["card"].get("type_line", ""), "quantity": 0})
            line["quantity"] += c["quantity"]
        flat = [{"name": commander_name, "type_line": "", "quantity": 1}] + list(by_name.values()) + [
            {"name": name, "type_line": "Basic Land", "quantity": count}
            for name, count in draft.basic_lands.items()
        ]
        for bucket, cards in group_cards(flat, {commander_name}).items():
            total = sum(c["quantity"] for c in cards)
            header = QListWidgetItem(f"{bucket} ({total})")
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(QColor(ACCENT))
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self._deck_list.addItem(header)
            for c in sorted(cards, key=lambda c: c["name"]):
                item = QListWidgetItem(f"{c['quantity']}  {c['name']}")
                if bucket != "Commander":
                    item.setData(NAME_ROLE, c["name"])
                self._deck_list.addItem(item)

    def _on_card_search_changed(self, predicate):
        self._card_search = predicate
        self._refresh_results(keep_scroll=False)

    def _refresh_results(self, keep_scroll: bool = True):
        """Shows the collection cards that can still be added to the
        deck (see DeckDraft.can_add) and match the search, one per owned
        printing + finish — tinted yellow where every copy of that exact
        version is already in other active decks (see _used_elsewhere).
        keep_scroll: stay at the same scroll position (after adding or
        removing a card) instead of jumping back to the top."""
        draft = self.draft
        search = self._card_search
        exclude_lands = self._exclude_lands.isChecked()
        self._used_elsewhere = self._compute_used_elsewhere()
        results = [
            e for e in self._addable_pool
            if (search is None or search(e))
            and not (exclude_lands and _IS_LAND(e))
            and draft.can_add(e) is None
        ]
        results = _sorted_results(results, self._sort_mode)
        scrollbar = self._results_grid.verticalScrollBar()
        position = scrollbar.value()
        self._results_grid.setCardData(results)
        if keep_scroll:
            scrollbar.setValue(position)
        self._card_search_box.set_result_text(plural(len(results), "card"))

    def _on_sort_changed(self, mode: str):
        """Sort menu pick: re-sorts the results (back to the top)."""
        self._sort_mode = mode
        self._refresh_results(keep_scroll=False)

    def _compute_used_elsewhere(self) -> dict:
        """printing key -> {"copies": n, "decks": [names]} for every exact
        card version (printing + finish) in the user's active decks —
        archived decks don't tie up cards, same as the Availability check."""
        used = {}
        own_deck_id = self.draft.deck_id if self.draft else None
        for deck in self.app.decks:
            if not deck.active or deck.deck_id == own_deck_id:  # not "elsewhere"
                continue
            for card in deck.cards:
                # per language of the copies used (confirmed for Moxfield decks)
                for language, copies in deck_languages.language_split(deck, card).items():
                    key = deck_card_printing_key(card)[:3] + (language,)
                    info = used.setdefault(key, {"copies": 0, "decks": []})
                    info["copies"] += copies
                    if deck.name not in info["decks"]:
                        info["decks"].append(deck.name)
        return used

    def _search_context(self) -> dict:
        """card_search context: is:used — the exact copy (printing +
        finish + language) has no free copy, same as the yellow tint and
        never counting the deck being edited; is:unique — exactly one copy
        of the card owned in total."""
        self._used_elsewhere = self._compute_used_elsewhere()
        return {"is": {
            "used": lambda entry: self._used_info(entry) is not None,
            "unique": availability.unique_check(self.app.collection.cards),
        }}

    def _used_info(self, entry: dict):
        """The _used_elsewhere info for `entry`'s exact version if no
        copy of it is free (all owned copies are in other active decks),
        else None."""
        return self._used_info_for_key(entry_printing_key(entry))

    def _used_info_for_key(self, key: tuple | None):
        """_used_info, by printing key (None — e.g. a basic land added
        outside the collection — is never used elsewhere)."""
        info = self._used_elsewhere.get(key) if key is not None else None
        if info and info["copies"] >= self._owned_by_printing.get(key, 0):
            return info
        return None

    def _result_tint(self, entry: dict):
        """Results grid tint_fn: the Availability screen's "Used
        elsewhere" yellow for versions with no free copy."""
        return USED_COLOR if self._used_info(entry) else None

    def _on_result_clicked(self, entry: dict):
        """Results grid click: adds one copy of the card to the deck."""
        used = self._used_info(entry)
        error = self.draft.add(entry)
        if error:
            self._set_feedback(error, error=True)
            return
        message = f"Added {entry['card']['name']}"
        if used:
            message += f" — this copy is also in {', '.join(used['decks'])}"
        self._set_feedback(message)
        self._refresh_draft_view()
        self._refresh_results()

    def _show_card_info(self, card: dict):
        """Deck image view / commander click: opens the shared card info
        popout — owned printings of the card, and the other active decks
        using this exact copy (printing + finish, like the "used
        elsewhere" tint; never this deck's own saved version)."""
        name = card["name"]
        printing = card.get("printing")  # None: basic land added outside the collection
        if printing is None:
            used_in = []
        else:
            set_code, cn, finish, language = printing
            copy = {"set": set_code, "cn": cn, "isFoil": finish == "foil", "finish": finish, "language": language}
            used_in = availability.used_in_decks_by_printing(
                self.app.decks, copy, exclude_deck_id=self.draft.deck_id if self.draft else None,
            )
        self.card_clicked.emit({
            **card,
            "owned_printings": availability.owned_printings(self.app.collection, name),
            "used_in_decks": used_in,
        })

    def forget_saved_deck(self, deck_id: str):
        """A saved deck was deleted: if it's the one open here, the draft
        stays open but becomes unsaved (saving makes a new deck)."""
        if self.draft and self.draft.deck_id == deck_id:
            self.draft.deck_id = None
            self._refresh_draft_view()
            self._set_feedback("The saved copy of this deck was deleted — it's unsaved now")

    def reload_images(self):
        """Reloads card images (artist proofs changed)."""
        self._commander_grid.reload_images()
        self._results_grid.reload_images()
        if self.draft:
            self._refresh_draft_view()

    def refresh_usage(self):
        """Re-checks which cards are used in other decks — called by
        MainWindow once deck contents finish loading in the background."""
        if self.draft and self._right_stack.currentWidget() is self._results_grid:
            self._refresh_results()

    def _on_deck_item_double_clicked(self, item: QListWidgetItem):
        """Deck list double-click: removes one copy of that card (the
        commander and headers aren't removable this way)."""
        name = item.data(NAME_ROLE)
        if name:
            self._remove_card(name)

    def _on_deck_list_menu(self, pos):
        """Deck list right-click: a "Remove one copy" menu for that card."""
        item = self._deck_list.itemAt(pos)
        name = item.data(NAME_ROLE) if item else None
        if not name:
            return
        menu = QMenu(self)
        remove_action = menu.addAction(f"Remove one copy of {name}")
        if menu.exec(self._deck_list.viewport().mapToGlobal(pos)) == remove_action:
            self._remove_card(name)

    def _remove_card(self, name: str, printing: tuple | None = None):
        """Removes one copy of the card named `name` from the deck — of
        that exact printing key, if given (the deck image view's Remove)."""
        self.draft.remove(name, printing)
        self._set_feedback(f"Removed {name}")
        self._refresh_draft_view()
        self._refresh_results()

    # ------------------------------------------------- deck image view

    def _toggle_deck_view(self):
        """Swaps the right side between adding cards (search + results)
        and the deck shown as card images with Remove buttons."""
        showing_deck = self._right_stack.currentWidget() is self._deck_view
        self._show_deck_view(not showing_deck)

    def _show_deck_view(self, show: bool):
        self._right_stack.setCurrentWidget(self._deck_view if show else self._results_grid)
        for widget in (self._card_search_box, self._sort_btn, self._exclude_lands):
            widget.setVisible(not show)
        self._view_toggle.setText("Back to adding cards" if show else "Show card images")
        if show:
            self._rebuild_deck_view(keep_scroll=False)

    def _rebuild_deck_view(self, keep_scroll: bool = True):
        """Rebuilds the deck image view: commander, then the other cards
        grouped by type, each with a Remove button (one copy per click).
        keep_scroll: stay at the same scroll position (after a removal)."""
        draft = self.draft
        scrollbar = self._deck_view.verticalScrollBar()
        position = scrollbar.value()
        clear_layout(self._deck_sections)
        self._used_elsewhere = self._compute_used_elsewhere()

        # same stats as the deck detail screen, for the deck as it'd be saved
        stats = DeckStatsRow(show_average=True)
        stats.set_cards(local_decks.draft_deck_cards(draft), draft.color_identity)
        self._deck_sections.addWidget(stats)

        commander_name = draft.commander["card"]["name"]
        cards = [_view_card(draft.commander["card"], 1, entry_printing_key(draft.commander))]
        cards += [_view_card(c["card"], c["quantity"], entry_printing_key(c)) for c in draft.cards]
        cards += [_basic_land_view_card(name, count) for name, count in draft.basic_lands.items()]

        for bucket, bucket_cards in group_cards(cards, {commander_name}).items():
            section = QWidget()
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(10)
            total = sum(c["quantity"] for c in bucket_cards)
            header = QLabel(f"{bucket} ({total})")
            header.setObjectName("deckSectionHeader")
            section_layout.addWidget(header)

            grid = QWidget()
            flow = FlowLayout(grid, margin=0, spacing=16)
            for card in sorted(bucket_cards, key=lambda c: c["name"]):
                flow.addWidget(self._deck_view_cell(card, removable=bucket != "Commander"))
            section_layout.addWidget(grid)
            self._deck_sections.addWidget(section)

        if keep_scroll:
            # after the new content is laid out, or the value gets clamped
            QTimer.singleShot(0, lambda: scrollbar.setValue(position))

    def _deck_view_cell(self, card: dict, removable: bool) -> QWidget:
        """One card in the deck image view: its image + "Nx name"
        caption (yellow-tinted if that exact version has no free copy, as
        in the results), and a Remove button unless it's the commander.
        Clicking the image opens the card info popout."""
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        tile = ImageTile(
            image_url=card["image_url"],
            cache_name=scryfall.card_image_cache_name(card),
            caption=quantity_caption(card),
            payload=card,
            width=DECK_VIEW_TILE_WIDTH,
            height=DECK_VIEW_TILE_HEIGHT,
            radius=12,
            status_color=USED_COLOR if self._used_info_for_key(card.get("printing")) else None,
        )
        tile.clicked.connect(self._show_card_info)
        tile.load_image()
        layout.addWidget(tile)
        if removable:
            remove_btn = QPushButton("Remove")
            remove_btn.setObjectName("removeButton")
            remove_btn.clicked.connect(
                lambda _=False, name=card["name"], key=card.get("printing"): self._remove_card(name, key)
            )
            layout.addWidget(remove_btn)
        return cell

    def _edit_basic_lands(self):
        """"Add basic lands" button: opens BasicLandsDialog for the
        commander's basics and applies the counts if accepted."""
        draft = self.draft
        other_cards = draft.card_count - sum(draft.basic_lands.values())
        dialog = BasicLandsDialog(self, draft.allowed_basics, draft.basic_lands, other_cards)
        if dialog.exec() != BasicLandsDialog.Accepted:
            return
        draft.set_basic_lands(dialog.counts())
        total = sum(draft.basic_lands.values())
        self._set_feedback(f"{plural(total, 'basic land')} in the deck")
        self._refresh_draft_view()
        self._refresh_results()

    def _set_feedback(self, text: str, error: bool = False):
        """Shows `text` left of the search box — red for errors."""
        self._feedback.setStyleSheet(f"color: {ERROR_COLOR};" if error else "")
        self._feedback.setText(text)
        self._feedback.setToolTip(text)

    def _save_draft(self):
        """"Save deck": writes the draft as a deck (models.local_decks) —
        asking for a name the first time; later saves overwrite it."""
        draft = self.draft
        username = self.app.username
        if not username:
            QMessageBox.information(self, "Not logged in", "Log in first via the sidebar avatar.")
            return
        name = draft.name
        if not draft.deck_id:
            name, ok = QInputDialog.getText(self, "Save deck", "Deck name:", text=draft.name)
            name = name.strip()
            if not ok or not name:
                return
        draft.deck_id = local_decks.save_draft(draft, name, username, draft.deck_id)
        draft.name = name
        self._set_feedback(f"Saved \"{name}\" ({draft.card_count} / {DECK_SIZE} cards)")
        self._refresh_draft_view()
        self.deck_saved.emit()

    def _discard_draft(self):
        """Drops the draft in progress (after confirming) and returns to
        the Start page. A saved deck stays saved — only changes since the
        last save are lost."""
        if self.draft.deck_id:
            title = "Close deck"
            question = (f"Close \"{self.draft.name}\"? The saved deck is kept; "
                        "changes since your last save are lost.")
        else:
            title = "Discard deck"
            question = f"Discard the new deck \"{self.draft.name}\"?"
        reply = QMessageBox.question(self, title, question)
        if reply != QMessageBox.Yes:
            return
        self.draft = None
        self._pages.setCurrentWidget(self._start_page)
