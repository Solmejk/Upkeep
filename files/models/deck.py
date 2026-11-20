"""Deck: one Moxfield deck's cards, commanders, and metadata, plus its
local active/archived flag (persisted separately — see deck_state.py).
Used both for the current user's own decks and for ad-hoc decks fetched
by URL (the Availability screen's "checked" deck).
"""

import requests
import cache_io
import moxfield
import paths
import scryfall
from models.deck_state import is_active, set_active

# Where a deck comes from — stored as "source" in every deck file. Plain
# text values (not numbers), so the files stay self-explanatory and a new
# import site is just a new value here. Files written before this field
# existed are Moxfield decks.
SOURCE_MOXFIELD = "moxfield"
SOURCE_LOCAL = "local"  # built in the Deck Maker

# Bumped whenever _trim_raw_deck's output gains data older cached decks
# lack; a cached deck with an older version is flagged `outdated` so the
# app re-fetches it. 2: each card keeps Moxfield's full card object.
# 3: every deck file carries its "source" (SOURCE_*).
CACHE_VERSION = 5  # 4: tokens, 5: token ids (default printings)

class Deck:
    def __init__(self, deck_id, name, source=SOURCE_MOXFIELD):
        """deck_id: the Moxfield public ID (or a Deck Maker deck's local
        ID). name: display name — used as a placeholder until load()
        overwrites it with the file's own name (callers that only have an
        ID, like the availability check, pass ""). source: SOURCE_*.
        Starts with no cards — call load() to populate."""
        self._deck_id = deck_id
        self._name = name
        self._source = source
        self._cards = []
        self._total_cards = 0
        self._commanders = []
        self._value = 0
        self._active = is_active(self._deck_id)
        self._format = ""
        self._outdated = False

    @property
    def cards(self):
        """Card dicts: flat name/set/cn/quantity/price/image_url/type_line
        (what the screens use), plus "card" — Moxfield's full card object
        (oracle text, cmc, colors, legalities, ...; same shape as a
        collection entry's "card") — and the entry's isFoil/finish."""
        return self._cards

    @property
    def outdated(self):
        """True if the last load() read a cache file written in an older
        format (see CACHE_VERSION) — it still works for display, but
        should be re-fetched with load(force=True)."""
        return self._outdated

    @property
    def format(self):
        return self._format

    @property
    def deck_id(self):
        return self._deck_id

    @property
    def source(self):
        """Where the deck comes from: SOURCE_MOXFIELD, SOURCE_LOCAL, ..."""
        return self._source

    @property
    def is_imported(self) -> bool:
        """True for decks imported from a website, False for decks built
        in the Deck Maker."""
        return self._source != SOURCE_LOCAL

    @property
    def value(self):
        return self._value

    @property
    def total_cards(self):
        return self._total_cards

    @property
    def name(self):
        return self._name

    @property
    def tokens(self):
        """Tokens / emblems the deck's cards make (Moxfield decks only —
        see _trim_tokens): flat name/set/cn/image_url/type_line/price
        dicts plus "made_by" (names of the deck cards that create it)."""
        return getattr(self, "_tokens", [])

    @property
    def commanders(self):
        """Subset of `cards` that are commanders (also present in the
        main `cards` list, not a separate pool)."""
        return self._commanders

    @property
    def active(self):
        """Whether this deck counts as "in use" for availability
        checks — archived decks don't tie up their cards. Persisted via
        deck_state.py, keyed by deck_id."""
        return self._active

    def set_active(self, value: bool):
        """Updates the active/archived flag, in memory and on disk
        (deck_state.py). value: the new active state."""
        self._active = value
        set_active(self._deck_id, value)

    def load(self, force=False):
        """Populates name/format/commanders/cards/total_cards/author/value.
        force: False reads the cached decks/<id>.json if present (leaves
        the deck empty if not cached yet); True fetches the full decklist
        from Moxfield, trims it down (_trim_raw_deck), and overwrites the
        cache."""
        if self._source == SOURCE_LOCAL:
            # Deck Maker decks live only on disk — nothing to fetch
            path = paths.local_deck_path(self._deck_id)
            force = False
        else:
            path = paths.deck_cache_path(self._deck_id)

        if not force:
            data = cache_io.read_json(path)
            if data is None:
                return
        else:
            response = requests.get(moxfield.deck_api_url(self._deck_id), timeout=10)
            response.raise_for_status()
            data = self._trim_raw_deck(response.json())
            cache_io.write_json(path, data)

        self._name = data["name"]
        self._format = data.get("format", "")
        self._commanders = data["commanders"]
        self._cards = data["cards"]
        self._tokens = data.get("tokens", [])  # Moxfield decks (cache v4+) only
        self._total_cards = data["total_cards"]
        self._value = data["value"]
        self._source = data.get("source", SOURCE_MOXFIELD)
        # only website imports can be re-fetched in the current format
        self._outdated = self._source != SOURCE_LOCAL and data.get("cache_version", 1) < CACHE_VERSION

    @staticmethod
    def _trim_raw_deck(raw: dict) -> dict:
        """Reduces Moxfield's full deck API response to the deck's cards
        plus a little metadata. Each card keeps Moxfield's full card
        object (under "card", for searching) alongside the flat fields
        the screens use. raw: the parsed JSON from the deck-all endpoint
        (mainboard/commanders boards only — sideboard/maybeboard/etc. are
        ignored). Returns a dict with cache_version/name/format/
        commanders/cards/total_cards/author/value, ready for
        cache_io.write_json()."""
        cards = []
        commanders = []
        total_value = 0

        for board_name, board in raw["boards"].items():
            if board_name not in ("mainboard", "commanders"):
                continue
            for entry in board["cards"].values():
                card = entry["card"]
                price = card.get("prices", {}).get("eur") or 0
                card_data = {
                    "name": card["name"],
                    "set": card["set"],
                    "cn": card["cn"],
                    "quantity": entry["quantity"],
                    "price": price,
                    "image_url": scryfall.image_url(card["scryfall_id"]),
                    "type_line": card["type_line"],
                    "isFoil": entry.get("isFoil", False),
                    "finish": entry.get("finish", ""),
                    "card": card,
                }
                if board_name == "commanders":
                    commanders.append(card_data)
                cards.append(card_data)
                total_value += price * entry["quantity"]

        return {
            "cache_version": CACHE_VERSION,
            "source": SOURCE_MOXFIELD,
            "name": raw["name"],
            "format": raw.get("format", ""),
            "commanders": commanders,
            "cards": cards,
            "total_cards": sum(c["quantity"] for c in cards),
            "author": raw.get("createdByUser", {}).get("userName", ""),
            "value": round(total_value, 2),
            "tokens": Deck._trim_tokens(raw),
        }

    @staticmethod
    def _trim_tokens(raw: dict) -> list:
        """The deck's tokens from Moxfield's "tokens" list, which also holds
        related non-tokens: the deck's own cards, Alchemy versions,
        checklist cards and game helpers (type line just "Card"). Keeps
        real tokens / emblems made by a mainboard or commander card
        ("tokensToCards" maps each to its makers), one per Moxfield card,
        sorted by name."""
        makers_by_uid = {}  # uniqueCardId -> card name, mainboard + commanders
        for board_name in ("mainboard", "commanders"):
            for entry in raw["boards"].get(board_name, {}).get("cards", {}).values():
                makers_by_uid[entry["card"].get("uniqueCardId")] = entry["card"]["name"]

        tokens, seen = [], set()
        for t in raw.get("tokens") or []:
            front_type = t.get("type_line", "").split("//")[0].strip()
            uid = t.get("uniqueCardId")
            if not t.get("isToken") or front_type == "Card" or uid in seen:
                continue
            makers = sorted({makers_by_uid[u] for u in raw.get("tokensToCards", {}).get(uid, [])
                             if u in makers_by_uid})
            if not makers:  # only made by sideboard / maybeboard cards
                continue
            seen.add(uid)
            name = t["name"]
            if t.get("power") is not None and t.get("toughness") is not None:
                name = f"{name} {t['power']}/{t['toughness']}"  # tells two "Vampire" tokens apart
            tokens.append({
                "name": name,
                "set": t.get("set", ""),
                "cn": t.get("cn", ""),
                "quantity": 1,
                "price": (t.get("prices") or {}).get("eur") or 0,
                "image_url": scryfall.image_url(t.get("scryfall_id", "")),
                "type_line": t.get("type_line", ""),
                "oracle_text": t.get("oracle_text", ""),
                "layout": t.get("layout", ""),
                "made_by": makers,
                "uid": uid,  # Moxfield's id for the token itself (any printing) — see models.token_printings
                "scryfall_id": t.get("scryfall_id", ""),
            })
        tokens.sort(key=lambda t: t["name"])
        return tokens
