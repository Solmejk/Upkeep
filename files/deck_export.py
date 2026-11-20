"""Decklist text for importing a deck into Moxfield (New Deck → Import,
or Bulk Edit), keeping each card's exact printing and finish:

    1 Cosmic Spider-Man (SPM) 127

    1 Sol Ring (C21) 263
    1 Lightning Bolt (2X2) 117 *F*
    10 Mountain

Commander(s) first, then a blank line, then the rest — the layout of
Moxfield's own text export. "(SET) number" selects the printing, *F* /
*E* mark foil / etched copies. Basic lands added outside the collection
have no particular printing, so they're plain "<qty> <name>" lines.
"""


def moxfield_text(deck) -> str:
    """The import text for a loaded models.deck.Deck."""
    commander_names = {c["name"] for c in deck.commanders}
    commanders = [card_line(c) for c in deck.cards if c["name"] in commander_names]
    others = [card_line(c) for c in deck.cards if c["name"] not in commander_names]
    if not commanders:
        return "\n".join(others)
    return "\n".join(commanders) + "\n\n" + "\n".join(others)


def card_line(card: dict) -> str:
    """One deck card (models.deck.Deck.cards shape) as an import line."""
    line = f"{card['quantity']} {card['name']}"
    set_code = card.get("set", "")
    if not set_code or set_code == "basic":  # basic land added outside the collection
        return line
    line += f" ({set_code.upper()}) {card.get('cn', '')}".rstrip()
    finish = str(card.get("finish") or "").lower()
    if finish == "etched":
        line += " *E*"
    elif card.get("isFoil") or finish == "foil":
        line += " *F*"
    return line
