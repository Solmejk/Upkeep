"""Showcases: named, ordered selections of collection cards shown on the
Home screen. Stored in paths.SHOWCASES_PATH (user data, not cache):

    [{"id": "...", "name": "Favourites", "cards": [card ref, ...],
      "gapless": false, "per_row": 0, "flippable": false, "default": false}, ...]

gapless: cards edge to edge (panoramas); per_row: fixed cards per row
(0 = fill the width); flippable: has a Flip button (showcases saved before
this setting existed count as flippable); default: shown at launch (at
most one).

A card ref identifies one owned version — printing + finish (+ the
copy's language) — and keeps the name and Scryfall ID so the card still
shows if that copy later leaves the collection.
"""

import uuid

import cache_io
import paths
from languages import entry_language
from printing import entry_printing_key, printing_key


def load() -> list[dict]:
    return cache_io.read_json(paths.SHOWCASES_PATH) or []


def save(showcases: list[dict]):
    cache_io.write_json(paths.SHOWCASES_PATH, showcases, indent=2)


def new_showcase(name: str) -> dict:
    return {"id": uuid.uuid4().hex[:12], "name": name, "cards": [], "gapless": False, "per_row": 0,
            "flippable": False, "default": False}


def card_ref(entry: dict) -> dict:
    """A collection entry -> the ref stored in a showcase."""
    card = entry["card"]
    finish = entry_printing_key(entry)[2]
    return {
        "name": card["name"],
        "set": card.get("set", ""),
        "cn": card.get("cn", ""),
        "finish": finish,
        "language": entry_language(entry),
        "scryfall_id": card.get("scryfall_id", ""),
    }


def ref_key(ref: dict) -> tuple:
    """(set, cn, finish) — one showcase holds each version once."""
    return printing_key(ref["set"], ref["cn"], ref["finish"] == "foil", ref["finish"])[:3]


def entry_for_ref(ref: dict, collection_entries: list):
    """The collection entry for a ref's version (any language), or None
    if it's no longer in the collection."""
    key = ref_key(ref)
    return next((e for e in collection_entries if entry_printing_key(e)[:3] == key), None)
