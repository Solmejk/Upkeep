"""DeckDraft: a deck being built in the Deck Maker. Cards come from the
user's collection. Each deck card is a copy of the collection entry it
was added from with "quantity" set to the copies in the deck — the same
shape as collection entries, so card_search predicates work on both.
Copies are tracked per printing (set + collector number + finish +
language, see printing_key), since that's what the collection owns.

Basic lands are the exception: they're added in any quantity outside the
collection (most collections don't track basics), and kept separately
as name -> count in `basic_lands`.
"""

from card_fields import front_type
from languages import DEFAULT_LANGUAGE, deck_card_language, entry_language

DECK_SIZE = 100  # commander format: commander + 99 — the target, not a cap:
                 # a draft may go over while options are being gathered

COLORS = "WUBRG"
BASIC_LANDS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
COLORLESS_BASIC = "Wastes"


def printing_key(set_code: str, cn: str, is_foil: bool, finish: str, language: str = DEFAULT_LANGUAGE) -> tuple:
    """Identifies one exact owned version of a card: printing + finish
    (nonfoil / foil / etched) + language. Works for collection entries
    and deck cards alike — see entry_printing_key / deck_card_printing_key.
    Returns (set, cn, finish, language)."""
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


def is_unlimited(card: dict) -> bool:
    """True for cards a commander deck may hold more than one copy of:
    basic lands and "A deck can have any number of cards named ..."."""
    type_line = front_type(card)
    oracle = card.get("oracle_text") or ""
    is_basic_land = "Basic" in type_line and "Land" in type_line  # incl. "Basic Snow Land"
    return is_basic_land or "any number of cards named" in oracle


class DeckDraft:
    def __init__(self, commander: dict):
        """commander: the collection entry chosen as commander."""
        self.commander = commander
        self.cards = []  # deck cards (see module docstring), commander excluded
        self.basic_lands = {}  # basic land name -> count (outside the collection)
        self.name = commander["card"]["name"]
        self.deck_id = None  # set once saved (models.local_decks) — later saves overwrite it

    @property
    def color_identity(self) -> list[str]:
        """The commander's color identity in WUBRG order (empty =
        colorless) — every other card must fit inside it."""
        return _identity(self.commander["card"])

    @property
    def card_count(self) -> int:
        """Cards in the deck so far, commander and basic lands included."""
        return 1 + sum(c["quantity"] for c in self.cards) + sum(self.basic_lands.values())

    @property
    def allowed_basics(self) -> list[str]:
        """Basic land names this commander can use: one per color in its
        identity, or Wastes for a colorless commander."""
        identity = self.color_identity
        if not identity:
            return [COLORLESS_BASIC]
        return [BASIC_LANDS[c] for c in identity]

    def set_basic_lands(self, counts: dict):
        """Replaces the basic land counts. counts: name -> count; names
        not in allowed_basics and zero counts are ignored."""
        allowed = self.allowed_basics
        self.basic_lands = {name: n for name, n in counts.items() if name in allowed and n > 0}

    def quantity_of(self, name: str) -> int:
        """Copies of the card named `name` in the deck (commander excluded)."""
        return sum(c["quantity"] for c in self.cards if c["card"]["name"] == name)

    def quantity_of_printing(self, entry: dict) -> int:
        """Copies of `entry`'s exact printing + finish in the deck."""
        key = entry_printing_key(entry)
        return sum(c["quantity"] for c in self.cards if entry_printing_key(c) == key)

    def can_add(self, entry: dict) -> str | None:
        """Why one more copy of the collection entry `entry` can't be
        added, or None if it can. One copy per card name, except basic
        lands / "any number" cards — those up to the copies owned of that
        exact printing (entry["quantity"])."""
        card = entry["card"]
        if card["name"] == self.commander["card"]["name"]:
            return f"{card['name']} is your commander."
        if not set(_identity(card)) <= set(self.color_identity):
            return f"{card['name']} is outside your commander's color identity."
        if self.quantity_of(card["name"]) and not is_unlimited(card):
            return f"{card['name']} is already in the deck (one copy per card)."
        owned = entry["quantity"]
        if self.quantity_of_printing(entry) >= owned:
            return f"All {owned} of this {card['name']} are already in the deck."
        return None

    def add(self, entry: dict) -> str | None:
        """Adds one copy of `entry`. Returns an error message instead if
        it can't be added (see can_add)."""
        error = self.can_add(entry)
        if error:
            return error
        key = entry_printing_key(entry)
        for deck_card in self.cards:
            if entry_printing_key(deck_card) == key:
                deck_card["quantity"] += 1
                return None
        self.cards.append({**entry, "quantity": 1})
        return None

    def remove(self, name: str, printing: tuple | None = None):
        """Removes one copy of the card named `name` — of the exact
        printing key `printing` if given, else of the most recently added
        printing of it."""
        if name in self.basic_lands and printing is None:
            self.basic_lands[name] -= 1
            if self.basic_lands[name] <= 0:
                del self.basic_lands[name]
            return
        for deck_card in reversed(self.cards):
            if deck_card["card"]["name"] == name and printing in (None, entry_printing_key(deck_card)):
                deck_card["quantity"] -= 1
                if deck_card["quantity"] <= 0:
                    self.cards.remove(deck_card)
                return

    def set_commander(self, commander: dict) -> list[str]:
        """Swaps the commander, dropping cards (and basic lands) that no
        longer fit its color identity, or that are the new commander.
        Returns the names of the dropped cards."""
        if self.name == self.commander["card"]["name"]:  # still the default name
            self.name = commander["card"]["name"]
        self.commander = commander
        identity = set(self.color_identity)
        kept, dropped = [], []
        for deck_card in self.cards:
            fits = set(_identity(deck_card["card"])) <= identity
            if fits and deck_card["card"]["name"] != commander["card"]["name"]:
                kept.append(deck_card)
            else:
                dropped.append(deck_card["card"]["name"])
        self.cards = kept
        for name, count in list(self.basic_lands.items()):
            if name not in self.allowed_basics:
                del self.basic_lands[name]
                dropped.append(f"{name} (x{count})")
        return dropped


def _identity(card: dict) -> list[str]:
    identity = {c.upper() for c in card.get("color_identity") or []}
    return [c for c in COLORS if c in identity]
