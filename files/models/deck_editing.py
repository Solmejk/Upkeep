"""Turning a saved deck back into a DeckDraft for the Deck Maker: "Edit
deck" for Deck Maker decks (saving overwrites them), "Edit a copy" for
website imports (an unsaved new deck).

The Deck Maker only uses cards from the collection, so each deck card is
matched to an owned copy — the same printing + finish + language first
(confirmed languages for Moxfield decks, see models.deck_languages), then
the same printing in another language, then any owned version of the
card. Basic lands that aren't in the collection become the draft's basic
land counts. Cards with no owned copy (or that break the deck rules)
are reported back as left out.
"""

from models import deck_languages
from models.deck_draft import BASIC_LANDS, COLORLESS_BASIC, DeckDraft, deck_card_printing_key, entry_printing_key

BASIC_LAND_NAMES = set(BASIC_LANDS.values()) | {COLORLESS_BASIC}


class EditError(Exception):
    """The deck can't be opened in the Deck Maker; str() says why."""


def draft_from_deck(deck, collection_entries: list, copy: bool) -> tuple[DeckDraft, list[str]]:
    """Builds a DeckDraft from a loaded models.deck.Deck. copy: True for
    "Edit a copy" (new unsaved deck named "<name> (copy)"), False to edit
    the deck itself (saving overwrites it). Returns (draft, left_out) —
    left_out: "<name> — <reason>" lines for cards that couldn't be added.
    Raises EditError if the commander isn't in the collection."""
    by_key, by_printing, by_name = {}, {}, {}
    for entry in collection_entries:
        by_key.setdefault(entry_printing_key(entry), []).append(entry)
        by_printing.setdefault(entry_printing_key(entry)[:3], []).append(entry)
        by_name.setdefault(entry["card"]["name"], []).append(entry)

    def candidates(card: dict, language: str) -> list:
        """Owned copies for one copy of a deck card, best match first."""
        printing = deck_card_printing_key(card)[:3]
        ordered = by_key.get(printing + (language,), []) + by_printing.get(printing, []) + by_name.get(card["name"], [])
        unique = []
        for entry in ordered:
            if not any(entry is seen for seen in unique):
                unique.append(entry)
        return unique

    commander_names = [c["name"] for c in deck.commanders]
    if not commander_names:
        raise EditError(f"\"{deck.name}\" has no commander.")
    commander_card = next(c for c in deck.cards if c["name"] == commander_names[0])
    commander_language = next(iter(deck_languages.language_split(deck, commander_card)))
    commander_entries = candidates(commander_card, commander_language)
    if not commander_entries:
        raise EditError(
            f"The commander, {commander_card['name']}, isn't in your collection — "
            "the Deck Maker only uses cards you own."
        )

    draft = DeckDraft(commander_entries[0])
    draft.name = f"{deck.name} (copy)" if copy else deck.name
    draft.deck_id = None if copy else deck.deck_id

    left_out = []
    basics = {}
    commander_skipped = False
    for card in deck.cards:
        split = deck_languages.language_split(deck, card)
        for language, copies in split.items():
            for _ in range(copies):
                if card["name"] == commander_card["name"] and not commander_skipped:
                    commander_skipped = True  # that copy is the draft's commander
                    continue
                if card.get("set") == "basic":  # basic land added outside the collection
                    basics[card["name"]] = basics.get(card["name"], 0) + 1
                    continue
                error = "not in your collection"
                for entry in candidates(card, language):
                    error = draft.add(entry)
                    if error is None:
                        break
                if error is None:
                    continue
                if card["name"] in BASIC_LAND_NAMES:  # not owned (or all used): an outside basic
                    basics[card["name"]] = basics.get(card["name"], 0) + 1
                else:
                    left_out.append(f"{card['name']} — {error}")

    allowed = draft.allowed_basics
    for name, count in basics.items():
        if name not in allowed:
            left_out.append(f"{count}x {name} — outside the commander's colors")
    draft.set_basic_lands(basics)
    return draft, _merge_duplicates(left_out)


def _merge_duplicates(lines: list[str]) -> list[str]:
    """["Sol Ring — x", "Sol Ring — x"] -> ["2x Sol Ring — x"]."""
    counts = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    return [line if n == 1 else f"{n}x {line}" for line, n in counts.items()]
