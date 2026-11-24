"""Printing keys: identify one exact owned version of a card — printing
(set + collector number) + finish (nonfoil / foil / etched) + language —
the same way for collection entries and deck cards. Used wherever copies
are matched up: availability, deck languages, showcases,
the Collection and Purchases screens.
"""

from languages import DEFAULT_LANGUAGE, deck_card_language, entry_language


def printing_key(set_code: str, cn: str, is_foil: bool, finish: str, language: str = DEFAULT_LANGUAGE) -> tuple:
    """(set, cn, finish, language) — see the module docstring. Works for
    collection entries and deck cards alike (entry_printing_key /
    deck_card_printing_key)."""
    finish = str(finish or "").lower()
    if finish != "etched":
        finish = "foil" if is_foil or finish == "foil" else "nonfoil"
    return (str(set_code).lower(), str(cn), finish, str(language or DEFAULT_LANGUAGE).lower())


def entry_printing_key(entry: dict) -> tuple:
    """printing_key of a collection entry (or a DeckDraft card)."""
    card = entry["card"]
    return printing_key(card.get("set", ""), card.get("cn", ""), entry.get("isFoil"), entry.get("finish"),
                        entry_language(entry))


def deck_card_printing_key(card: dict) -> tuple:
    """printing_key of a saved deck's card (models.deck.Deck.cards — flat
    set/cn/isFoil/finish; decks cached before finish was stored count as
    nonfoil; Moxfield decks don't record language, so English — see
    languages.deck_card_language)."""
    return printing_key(card.get("set", ""), card.get("cn", ""), card.get("isFoil"), card.get("finish"),
                        deck_card_language(card))
