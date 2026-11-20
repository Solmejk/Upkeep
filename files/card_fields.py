"""Small shared helpers for reading cards, used by search, sorting, deck
stats and the deck rules — so they all agree on what "the front face" or
"a land" is. Work on Moxfield card objects and on deck cards alike (both
have "type_line").

Double-faced cards (transform, MDFC, adventure, …) list both faces in
their type line ("Sorcery // Land") and keep text / cost / power on each
face under "card_faces", with the top-level field empty.
"""


def front_type(card: dict) -> str:
    """Type line of the card's front face ("Sorcery // Land" -> "Sorcery")."""
    return card.get("type_line", "").split("//")[0]


def is_land(card: dict) -> bool:
    """True if the front face is a land (so an MDFC spell with a land
    back counts as a spell, and a land with a spell back as a land)."""
    return "Land" in front_type(card)


def face_field(card: dict, field: str):
    """`field` of a card object — of its front face if the top-level value
    is empty (double-faced cards). None if neither has it."""
    value = card.get(field)
    if value in (None, "") and card.get("card_faces"):
        value = card["card_faces"][0].get(field)
    return value


def plural(count: int, word: str, plural_word: str | None = None) -> str:
    """"1 card" / "3 cards" (plural_word for irregular plurals,
    e.g. plural(n, "match", "matches"))."""
    return f"{count} {word if count == 1 else plural_word or word + 's'}"
