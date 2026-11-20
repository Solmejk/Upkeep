"""Sorting collection entries (Collection screen's Sort menu) with a fixed
tie-break order, so different versions of a card always line up the same
way: name, then release date (oldest printing first), then collector
number, then nonfoil → foil → etched.
"""

import re
import unicodedata

from card_fields import is_land

SORT_NAME = "name"
SORT_PRICE_DESC = "price_desc"
SORT_PRICE_ASC = "price_asc"
SORT_COLOR = "color"
SORT_LABELS = {  # mode -> Sort menu label, in menu order
    SORT_NAME: "Name",
    SORT_PRICE_DESC: "Price high-low",
    SORT_PRICE_ASC: "Price low-high",
    SORT_COLOR: "Color",
}

COLOR_ORDER = "WUBRG"
FINISH_ORDER = {"nonfoil": 0, "foil": 1, "etched": 2}


def name_key(name: str) -> str:
    """Case- and accent-insensitive sort key ("Éomer" sorts with E)."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def sort_entries(entries: list, mode: str) -> list:
    """Collection entries sorted per a SORT_LABELS mode (new list)."""
    by_version = sorted(entries, key=_version_key)  # the tie-break order
    if mode == SORT_NAME:
        return by_version
    if mode == SORT_COLOR:
        return sorted(by_version, key=_color_group)  # stable: ties keep version order
    # price: an unknown price counts as 0 — it's shown as €0.00, so it
    # sorts with the cheapest cards (first low-high, last high-low)
    return sorted(by_version, key=lambda e: copy_price(e) or 0, reverse=mode == SORT_PRICE_DESC)


def copy_price(entry: dict):
    """EUR price of the copy — the foil price for foil / etched copies
    when there is one; None if unknown."""
    prices = entry["card"].get("prices") or {}
    if _finish(entry) != "nonfoil" and prices.get("eur_foil"):
        return prices["eur_foil"]
    return prices.get("eur")


def _finish(entry: dict) -> str:
    finish = str(entry.get("finish") or "").lower()
    if finish == "etched":
        return "etched"
    return "foil" if entry.get("isFoil") or finish == "foil" else "nonfoil"


def _version_key(entry: dict) -> tuple:
    card = entry["card"]
    cn = str(card.get("cn", ""))
    digits = re.match(r"\d+", cn)
    return (
        name_key(card["name"]),
        card.get("released_at", ""),
        int(digits.group()) if digits else 0,
        cn,
        FINISH_ORDER[_finish(entry)],
    )


def _color_group(entry: dict) -> int:
    """W, U, B, R, G (0-4), multicolored (5), colorless (6), lands (7).
    Double-faced cards: colors from both faces, land by the front face."""
    card = entry["card"]
    if is_land(card):
        return 7
    colors = set(card.get("colors") or [])
    for face in card.get("card_faces") or []:
        colors.update(face.get("colors") or [])
    colors = {c.upper() for c in colors}
    if len(colors) > 1:
        return 5
    if len(colors) == 1:
        return COLOR_ORDER.index(colors.pop())
    return 6
