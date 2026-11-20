"""Decks built in the Deck Maker: saved as JSON in paths.LOCAL_DECKS_DIR,
in the same format as cached Moxfield decks (see Deck._trim_raw_deck),
with "source": "local" — so Deck.load(), the Decks/DeckDetail screens,
and the availability checks treat them like any other deck.
"""

import uuid
from urllib.parse import quote

import cache_io
import paths
import scryfall
from languages import entry_language
from models.deck import CACHE_VERSION, SOURCE_LOCAL, Deck

# Basic lands added outside the collection have no Scryfall ID —
# Scryfall's named-card endpoint redirects to the image instead.
BASIC_LAND_IMAGE_URL = "https://api.scryfall.com/cards/named?format=image&version=normal&exact={}"


def new_deck_id() -> str:
    return f"local-{uuid.uuid4().hex[:12]}"


def load_stubs(username: str) -> list[Deck]:
    """Deck stubs (id + name; contents load via Deck.load()) for the
    saved Deck Maker decks belonging to `username`."""
    if not paths.LOCAL_DECKS_DIR.exists():
        return []
    stubs = []
    for path in sorted(paths.LOCAL_DECKS_DIR.glob("*.json")):
        data = cache_io.read_json(path)
        if data and data.get("author", "").lower() == username.lower():
            stubs.append(Deck(path.stem, data["name"], source=SOURCE_LOCAL))
    return stubs


def delete(deck_id: str):
    """Deletes a saved Deck Maker deck's file (no-op if it's already gone)."""
    paths.local_deck_path(deck_id).unlink(missing_ok=True)


def draft_deck_cards(draft) -> list[dict]:
    """A DeckDraft's cards in deck file shape (Deck.cards): the commander
    first, then the other cards, then the basic lands."""
    cards = [_deck_card(draft.commander)] + [_deck_card(c) for c in draft.cards]
    cards += [_basic_land_card(land, count) for land, count in draft.basic_lands.items()]
    return cards


def save_draft(draft, name: str, username: str, deck_id: str | None = None) -> str:
    """Writes `draft` (a DeckDraft) as a deck file. deck_id: the ID of a
    previous save of this draft to overwrite, or None for a new deck.
    Returns the deck ID."""
    deck_id = deck_id or new_deck_id()
    cards = draft_deck_cards(draft)
    commander = cards[0]
    data = {
        "cache_version": CACHE_VERSION,
        "source": SOURCE_LOCAL,
        "name": name,
        "format": "commander",
        "commanders": [commander],
        "cards": cards,
        "total_cards": sum(c["quantity"] for c in cards),
        "author": username,
        "value": round(sum(c["price"] * c["quantity"] for c in cards), 2),
    }
    cache_io.write_json(paths.local_deck_path(deck_id), data)
    return deck_id


def save_imported(name: str, username: str, commanders: list, cards: list) -> str:
    """Writes an imported decklist (deck_import.py) as a new deck file.
    commanders / cards: deck file cards (commanders not repeated in
    cards). A deck without a commander gets no format. Returns the ID."""
    deck_id = new_deck_id()
    all_cards = commanders + cards
    data = {
        "cache_version": CACHE_VERSION,
        "source": SOURCE_LOCAL,
        "name": name,
        "format": "commander" if commanders else "",
        "commanders": commanders,
        "cards": all_cards,
        "total_cards": sum(c["quantity"] for c in all_cards),
        "author": username,
        "value": round(sum(c["price"] * c["quantity"] for c in all_cards), 2),
    }
    cache_io.write_json(paths.local_deck_path(deck_id), data)
    return deck_id


def set_commander(deck_id: str, card_name: str):
    """Makes one of a saved deck's cards its commander (e.g. a decklist
    imported without a commander section): moved to the front of the deck
    and listed as the commander; the deck becomes a Commander deck."""
    path = paths.local_deck_path(deck_id)
    data = cache_io.read_json(path)
    card = next(c for c in data["cards"] if c["name"] == card_name)
    data["cards"].remove(card)
    data["cards"].insert(0, card)
    data["commanders"] = [card]
    data["format"] = "commander"
    cache_io.write_json(path, data)


def commander_candidates(cards: list) -> list:
    """Names of the deck's cards that can lead a Commander deck: legendary
    creatures / planeswalkers, and cards that say "can be your commander"
    (falls back to every card if none qualify)."""
    names = []
    for c in cards:
        type_line = c.get("type_line", "").split("//")[0]
        oracle = (c.get("card") or {}).get("oracle_text", "") or ""
        if ("Legendary" in type_line and ("Creature" in type_line or "Planeswalker" in type_line))                 or "can be your commander" in oracle:
            names.append(c["name"])
    return names or [c["name"] for c in cards]


def _deck_card(entry: dict) -> dict:
    """A DeckDraft card (collection entry shape) -> a deck file card, the
    same shape Deck._trim_raw_deck produces."""
    card = entry["card"]
    return {
        "name": card["name"],
        "set": card.get("set", ""),
        "cn": card.get("cn", ""),
        "quantity": entry["quantity"],
        "price": card.get("prices", {}).get("eur") or 0,
        "image_url": scryfall.image_url(card.get("scryfall_id", "")),
        "type_line": card.get("type_line", ""),
        "isFoil": entry.get("isFoil", False),
        "finish": entry.get("finish", ""),
        "language": entry_language(entry),  # Moxfield deck files don't have this
        "card": card,
    }


def _basic_land_card(name: str, quantity: int) -> dict:
    """A basic land added outside the collection -> a deck file card.
    set "basic" / cn <name> gives it the image cache name card_basic_<name>."""
    return {
        "name": name,
        "set": "basic",
        "cn": name,
        "quantity": quantity,
        "price": 0,
        "image_url": BASIC_LAND_IMAGE_URL.format(quote(name)),
        "type_line": f"Basic Land — {name}",
        "isFoil": False,
        "finish": "",
        "card": {"name": name, "type_line": f"Basic Land — {name}", "color_identity": [], "cmc": 0},
    }
