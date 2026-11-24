"""Card copy languages: reading which language a copy is in, and display
names for the language codes (Scryfall / Moxfield codes).

Only the collection records the language of each copy (entry
"language": {"code", "name"}). Moxfield deck data has no language — those
cards count as English (their printing's "lang"). Deck files that store
a card's "language" (decks built in the old Deck Maker) use that.
"""

DEFAULT_LANGUAGE = "en"

LANGUAGE_NAMES = {
    "en": "English", "ja": "Japanese", "fr": "French", "de": "German",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "ru": "Russian",
    "ko": "Korean", "zhs": "Chinese (Simplified)", "zht": "Chinese (Traditional)",
    "he": "Hebrew", "la": "Latin", "grc": "Ancient Greek", "ar": "Arabic",
    "sa": "Sanskrit", "ph": "Phyrexian",
}


def entry_language(entry: dict) -> str:
    """Language code of a collection entry's copy (also DeckDraft cards,
    which are copies of collection entries)."""
    language = entry.get("language")
    if isinstance(language, dict) and language.get("code"):
        return language["code"].lower()
    if isinstance(language, str) and language:
        return language.lower()
    return str((entry.get("card") or {}).get("lang") or DEFAULT_LANGUAGE).lower()


def deck_card_language(card: dict) -> str:
    """Language code of a saved deck's card (models.deck.Deck.cards):
    stored in the deck file if any, else the printing's "lang" (Moxfield
    decks don't record it), else English."""
    if card.get("language"):
        return str(card["language"]).lower()
    return str((card.get("card") or {}).get("lang") or DEFAULT_LANGUAGE).lower()


def language_name(code: str) -> str:
    """"ja" -> "Japanese" (unknown codes are shown as-is, upper-cased)."""
    code = str(code or DEFAULT_LANGUAGE).lower()
    return LANGUAGE_NAMES.get(code, code.upper())
