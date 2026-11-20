"""Deck statistics for the deck detail screen: mana values and curve,
color balance (mana symbols in costs), and mana production (lands +
mana-producing permanents). Works on models.deck.Deck.cards — each card's
full Moxfield card object is under "card"; copies count individually. For
double-faced cards the front face decides land / nonland.
"""

import re

from card_fields import face_field, front_type, is_land

CURVE_MAX = 7  # the curve's last bar collects mana value 7 and above

COLORS = "WUBRG"
COLOR_KEYS = "WUBRGC"  # pie order: the five colors, then colorless
LAND_TYPE_COLORS = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}
PERMANENT_TYPES = ("Artifact", "Creature", "Enchantment", "Planeswalker", "Battle")


def nonland_mana_values(cards: list[dict]) -> list[tuple[float, int]]:
    """(mana value, copies) for each nonland deck card whose mana value is
    known (decks cached before full card data was stored have none)."""
    values = []
    for card in cards:
        if is_land(card):
            continue
        cmc = (card.get("card") or {}).get("cmc")
        if cmc is None:
            continue
        values.append((float(cmc), card["quantity"]))
    return values


def average_mana_value(cards: list[dict]) -> float | None:
    """Average mana value of the nonland cards, per copy; None if unknown."""
    values = nonland_mana_values(cards)
    copies = sum(q for _, q in values)
    if not copies:
        return None
    return sum(cmc * q for cmc, q in values) / copies


def mana_curve(cards: list[dict]) -> list[int]:
    """Nonland card counts per mana value 0 … CURVE_MAX (last = CURVE_MAX+)."""
    counts = [0] * (CURVE_MAX + 1)
    for cmc, quantity in nonland_mana_values(cards):
        counts[min(int(cmc), CURVE_MAX)] += quantity
    return counts


def color_balance(cards: list[dict]) -> dict:
    """Colored mana symbols in the nonland cards' mana costs, per copy:
    {"W": n, ..., "C": n}. Hybrid symbols count toward each of their
    colors, Phyrexian ones toward their color; generic / X don't count."""
    counts = dict.fromkeys(COLOR_KEYS, 0)
    for card in cards:
        if is_land(card):
            continue
        for symbol in re.findall(r"\{([^}]+)\}", _front_face_field(card, "mana_cost")):
            for part in symbol.upper().split("/"):
                if part in counts:
                    counts[part] += card["quantity"]
    return counts


def mana_production(cards: list[dict], identity: list[str]) -> tuple[dict, int, int]:
    """Which colors the deck's mana sources make: lands, plus permanents
    that tap for mana (rocks, dorks, ...). Returns ({"W": n, ..., "C": n},
    land sources, other sources) — a source counts once per color it can
    make, per copy. identity: the commander's colors, for "any basic land"
    fetches and "your commander's color identity" producers.

    Moxfield has no produced-mana data, so it's read from each card's
    text: "Add {G}" / "Add one mana of any color" clauses, basic land types
    in the type line (dual lands), and the land types fetch lands search
    for. One-shot spells (rituals, land-search sorceries) aren't sources."""
    counts = dict.fromkeys(COLOR_KEYS, 0)
    land_sources = other_sources = 0
    for card in cards:
        card_type = front_type(card)
        land = is_land(card)
        if not land and not any(t in card_type for t in PERMANENT_TYPES):
            continue
        produced = _produced_colors(card, card_type, land, identity)
        if not produced:
            continue
        for color in produced:
            counts[color] += card["quantity"]
        if land:
            land_sources += card["quantity"]
        else:
            other_sources += card["quantity"]
    return counts, land_sources, other_sources


def _produced_colors(card: dict, card_type: str, land: bool, identity: list[str]) -> set:
    text = _front_face_field(card, "oracle_text")
    colors = set()
    for clause in re.findall(r"\badd ([^.]*)", text, re.IGNORECASE):
        lowered = clause.lower()
        colors.update(s for s in re.findall(r"\{([WUBRGC])\}", clause.upper()))
        if "any color" in lowered or "any one color" in lowered or "any type" in lowered \
                or "combination of colors" in lowered:
            colors.update(COLORS)
        if "color identity" in lowered or "chosen color" in lowered:
            colors.update(identity)
    if land:
        subtypes = card_type.split("—")[1] if "—" in card_type else ""
        colors.update(c for land_type, c in LAND_TYPE_COLORS.items() if land_type in subtypes)
        search = re.search(r"search your library for (?:an? |up to \w+ )?(.+?) cards?", text, re.IGNORECASE)
        if search:
            wanted = search.group(1)
            colors.update(c for land_type, c in LAND_TYPE_COLORS.items() if land_type in wanted)
            if "basic land" in wanted.lower():
                colors.update(identity)
        if card.get("name") == "Wastes":
            colors.add("C")
    # Only the commander's colors (and colorless) matter in the deck — and
    # "any color" sources like Command Tower / Arcane Signet can't make
    # anything else anyway.
    return {c for c in colors if c in identity or c == "C"}


def _front_face_field(card: dict, field: str) -> str:
    """`field` of a deck card's full card object (front face for
    double-faced cards); "" if missing."""
    return face_field(card.get("card") or {}, field) or ""


def commander_identity(cards: list[dict], commander_names: set) -> list[str]:
    """Combined color identity of the commander(s), from their full card
    objects among `cards` (all five colors if unknown)."""
    identity = set()
    for name in commander_names:
        card = next((c.get("card") for c in cards if c["name"] == name), None)
        if not card:
            return list(COLORS)
        identity.update(c.upper() for c in card.get("color_identity") or [])
    return [c for c in COLORS if c in identity]
