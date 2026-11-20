"""Which language of copy each Moxfield deck card uses. Moxfield decks
don't record language (their cards count as English), but the collection
does — so when a deck card's exact printing + finish is owned in another
language, or in several, the user confirms which copies the deck uses
(DeckDetailScreen's warning → LanguageCheckDialog).

Answers are stored per deck in paths.DECK_LANGUAGES_PATH (user data, not
cache): {deck_id: {"set|cn|finish": {language: copies}}}.
"""

import cache_io
import paths
from languages import DEFAULT_LANGUAGE, deck_card_language, entry_language
from models.deck import SOURCE_MOXFIELD
from printing import deck_card_printing_key, entry_printing_key


def _load() -> dict:
    return cache_io.read_json(paths.DECK_LANGUAGES_PATH) or {}


def _printing_id(card: dict) -> str:
    """"set|cn|finish" of a deck card — its printing key without language."""
    return "|".join(deck_card_printing_key(card)[:3])


def language_split(deck, card: dict) -> dict:
    """{language: copies} for a deck card: the user's confirmed answer for
    a Moxfield deck if there is a valid one, else all copies in the card's
    recorded language (Deck Maker decks) or English (Moxfield)."""
    if deck.source == SOURCE_MOXFIELD:
        answer = _load().get(deck.deck_id, {}).get(_printing_id(card))
        if answer and sum(answer.values()) == card["quantity"]:
            return dict(answer)
    return {deck_card_language(card): card["quantity"]}


def conflicts(deck, collection_entries: list) -> list[dict]:
    """The deck's cards whose exact printing + finish the collection owns
    in a language other than English, or in several languages — only for
    Moxfield decks, which don't record language. Each: {"card", "owned":
    {language: copies}, "answer": {language: copies} or None (unconfirmed
    or no longer valid)}."""
    if deck.source != SOURCE_MOXFIELD:
        return []
    owned_by_printing = {}
    for entry in collection_entries:
        printing = "|".join(entry_printing_key(entry)[:3])
        owned = owned_by_printing.setdefault(printing, {})
        language = entry_language(entry)
        owned[language] = owned.get(language, 0) + entry["quantity"]

    answers = _load().get(deck.deck_id, {})
    result = []
    for card in deck.cards:
        printing = _printing_id(card)
        owned = owned_by_printing.get(printing)
        if not owned or set(owned) == {DEFAULT_LANGUAGE}:
            continue
        answer = answers.get(printing)
        valid = (answer and sum(answer.values()) == card["quantity"]
                 and all(language in owned for language in answer))
        result.append({"card": card, "owned": owned, "answer": answer if valid else None})
    return result


def save_answers(deck_id: str, answers: list[tuple[dict, dict]]):
    """Stores confirmed languages for a deck. answers: (deck card,
    {language: copies}) pairs; other cards' stored answers are kept."""
    data = _load()
    deck_answers = data.setdefault(deck_id, {})
    for card, split in answers:
        deck_answers[_printing_id(card)] = {lang: n for lang, n in split.items() if n > 0}
    cache_io.write_json(paths.DECK_LANGUAGES_PATH, data, indent=2)
