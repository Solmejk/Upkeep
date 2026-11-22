"""Deck Maker shared pieces: the card filters, constants, result sorting,
the flat card dicts the deck image view works with, and CardUsage —
which exact copies are already tied up in your other active decks.
"""

from urllib.parse import quote

from PySide6.QtCore import Qt

import availability
import card_search
import scryfall
from card_fields import face_field
from card_sort import name_key
from models import deck_languages
from models.local_decks import BASIC_LAND_IMAGE_URL
from printing import deck_card_printing_key, entry_printing_key
from ui import theme
from ui.components.color_pie import COLOR_SWATCHES
from ui.components.search_box import ERROR_COLOR
from ui.screens.availability import STATUS_COLORS

# Commander-eligible and legal in the commander format.
IS_COMMANDER = card_search.compile_query("is:commander f:commander")
IS_COMMANDER_LEGAL = card_search.compile_query("f:commander")
IS_LAND = card_search.compile_query("t:land")  # the "Exclude lands" checkbox = -t:land

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


def card_number(card: dict, field: str):
    """`field` of a Moxfield card object as a number, or None if it has
    none (non-creatures, "*" power...). Double-faced cards keep these on
    their faces — the front face is used."""
    try:
        return float(face_field(card, field))
    except (TypeError, ValueError):
        return None


def sorted_results(entries: list, mode: str) -> list:
    """Sorts collection entries per a SORT_LABELS mode ("<field>_asc" /
    "<field>_desc", or SORT_NAME). Ties are by name; cards without a
    value for the field (non-creatures, "*" power...) go last either way."""
    by_name = sorted(entries, key=lambda e: name_key(e["card"]["name"]))
    if mode == SORT_NAME:
        return by_name
    field, direction = mode.rsplit("_", 1)
    with_value = [e for e in by_name if card_number(e["card"], field) is not None]
    without_value = [e for e in by_name if card_number(e["card"], field) is None]
    # stable sort (also with reverse=True): equal values stay in name order
    with_value.sort(key=lambda e: card_number(e["card"], field), reverse=direction == "desc")
    return with_value + without_value


def view_card(card: dict, quantity: int, printing: tuple | None = None) -> dict:
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


def basic_land_view_card(name: str, quantity: int) -> dict:
    """Same as view_card, for a basic land added outside the collection."""
    return {
        "name": name,
        "set": "basic",  # -> image cache name "card_basic_<name>"
        "cn": name,
        "type_line": "Basic Land",
        "quantity": quantity,
        "image_url": BASIC_LAND_IMAGE_URL.format(quote(name)),
    }


class CardUsage:
    """Which exact copies (printing + finish + language) are tied up in the
    user's other active decks — never counting the deck being edited —
    for the yellow "used elsewhere" tint and the is:used search. Shared by
    the commander and build pages.

    own_deck_id: a function returning the id of the deck being edited
    (None for a new one) — its own cards aren't "elsewhere"."""

    def __init__(self, app, own_deck_id):
        self.app = app
        self._own_deck_id = own_deck_id
        self.owned_by_printing = {}  # printing key -> copies owned
        self.used = {}               # printing key -> {"copies": n, "decks": [names]}

    def reload_collection(self):
        """Re-counts the owned copies per printing (after a refresh etc.)."""
        self.owned_by_printing = {}
        for entry in self.app.collection.cards:
            key = entry_printing_key(entry)
            self.owned_by_printing[key] = self.owned_by_printing.get(key, 0) + entry["quantity"]

    def refresh(self):
        """Re-reads which copies the active decks use — archived decks don't
        tie up cards, same as the Availability check."""
        used = {}
        own_deck_id = self._own_deck_id()
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
        self.used = used

    def info(self, entry: dict):
        """The usage info for `entry`'s exact version if no copy of it is
        free (all owned copies are in other active decks), else None."""
        return self.info_for_key(entry_printing_key(entry))

    def info_for_key(self, key: tuple | None):
        """info(), by printing key (None — e.g. a basic land added outside
        the collection — is never used elsewhere)."""
        info = self.used.get(key) if key is not None else None
        if info and info["copies"] >= self.owned_by_printing.get(key, 0):
            return info
        return None

    def search_context(self) -> dict:
        """card_search context: is:used — the exact copy has no free copy
        (same as the yellow tint); is:unique — exactly one copy of the
        card owned in total."""
        self.refresh()
        return {"is": {
            "used": lambda entry: self.info(entry) is not None,
            "unique": availability.unique_check(self.app.collection.cards),
        }}
