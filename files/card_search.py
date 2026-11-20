"""Scryfall-style card search over the app's own data: collection entries
and deck cards (both carry Moxfield's full card object under "card",
plus per-copy fields like quantity/isFoil/finish next to it).

    pred = compile_query('t:creature c:g mv<=3 -o:"draw a card"')
    matches = [entry for entry in entries if pred(entry)]

Supported syntax (see ui/search_help.py for the user-facing guide):
- bare words / "quoted phrases": name contains; !"Exact Name"
- key + operator + value, operators : = != < <= > >=
- implicit AND between terms, `or`, `and`, `-` to negate, ( ) to group
- /regex/ values for the text filters (name, o:, t:, ft:, a:)

compile_query raises SearchError with a human-readable message for
anything it can't parse, so the UI can show it next to the search box.
"""

import re
from functools import cached_property

from card_fields import front_type
from languages import language_name
from models import artist_proofs


class SearchError(ValueError):
    """A query couldn't be parsed. str(error) is shown to the user."""


# ---------------------------------------------------------------- values

COLOR_NAMES = {
    "white": "w", "blue": "u", "black": "b", "red": "r", "green": "g",
    # guilds
    "azorius": "wu", "dimir": "ub", "rakdos": "br", "gruul": "rg", "selesnya": "gw",
    "orzhov": "wb", "izzet": "ur", "golgari": "bg", "boros": "rw", "simic": "gu",
    # shards
    "bant": "gwu", "esper": "wub", "grixis": "ubr", "jund": "brg", "naya": "rgw",
    # wedges
    "abzan": "wbg", "jeskai": "urw", "sultai": "bgu", "mardu": "rwb", "temur": "gur",
}

RARITY_ORDER = ["common", "uncommon", "rare", "mythic", "special", "bonus"]
RARITY_ALIASES = {"c": "common", "u": "uncommon", "r": "rare", "m": "mythic", "s": "special", "b": "bonus"}

FORMATS = {
    "standard", "future", "historic", "timeless", "gladiator", "pioneer", "modern",
    "legacy", "pauper", "vintage", "penny", "commander", "oathbreaker",
    "standardbrawl", "brawl", "competitivebrawl", "alchemy", "paupercommander",
    "duel", "oldschool", "premodern", "predh",
}
FORMAT_ALIASES = {"edh": "commander", "pdh": "paupercommander"}

PERMANENT_TYPES = ("artifact", "creature", "enchantment", "land", "planeswalker", "battle")
DFC_LAYOUTS = {"transform", "modal_dfc", "meld", "reversible_card"}

# Filters Scryfall has but this data can't answer — explained, not "unknown".
UNAVAILABLE = {
    "kw": "keywords", "keyword": "keywords", "produces": "produced mana",
    "wm": "watermarks", "watermark": "watermarks", "game": "game availability",
}


class _Value:
    """A parsed filter value. kind: "plain", "quoted", or "regex"."""

    def __init__(self, text: str, kind: str):
        self.text = text
        self.kind = kind
        self.regex = None
        if kind == "regex":
            try:
                self.regex = re.compile(text, re.IGNORECASE | re.MULTILINE)
            except re.error as e:
                raise SearchError(f"Invalid regex /{text}/: {e}")

    def matches_text(self, haystack: str) -> bool:
        """Case-insensitive contains (or regex search) on `haystack`."""
        if self.regex is not None:
            return bool(self.regex.search(haystack))
        return self.text.lower() in haystack.lower()


# ------------------------------------------------------------- card view

class _CardView:
    """Normalized, lazily computed fields for one entry. Handles both the
    collection/new-deck shape ({"card": {...}, "quantity", "isFoil", ...})
    and old flat deck cards (name/set/cn/type_line at the top level), and
    merges double-faced cards' per-face fields (whose top-level oracle
    text, colors, power etc. are empty)."""

    def __init__(self, entry: dict):
        self.entry = entry
        self.card = entry.get("card") or entry
        self.faces = self.card.get("card_faces") or []

    def _gather(self, field) -> list:
        """Non-empty values of `field` from the card and each face."""
        values = [self.card.get(field)] + [f.get(field) for f in self.faces]
        return [v for v in values if v not in (None, "")]

    @cached_property
    def name(self) -> str:
        return self.card.get("name", "")

    @cached_property
    def names(self) -> list[str]:
        return [self.name] + [f.get("name", "") for f in self.faces]

    @cached_property
    def type_line(self) -> str:
        return self.card.get("type_line", "")

    @cached_property
    def front_type(self) -> str:
        return front_type(self.card).lower()

    @cached_property
    def oracle(self) -> str:
        return "\n".join(self._gather("oracle_text"))

    @cached_property
    def flavor(self) -> str:
        return "\n".join(self._gather("flavor_text"))

    @cached_property
    def mana_symbols(self) -> list[str]:
        costs = self._gather("mana_cost")
        return [s.upper() for cost in costs[:1] for s in re.findall(r"\{([^}]+)\}", cost)] if costs else []

    @cached_property
    def colors(self) -> set:
        result = set()
        for colors in self._gather("colors"):
            result.update(c.lower() for c in colors)
        return result

    @cached_property
    def identity(self) -> set:
        return {c.lower() for c in self.card.get("color_identity") or []}

    def numbers(self, field) -> list[float]:
        """Numeric values of `field` across card + faces ("*" etc. skipped)."""
        result = []
        for v in self._gather(field):
            try:
                result.append(float(v))
            except (TypeError, ValueError):
                pass
        return result

    @cached_property
    def custom_flags(self) -> set:
        """is:proof / is:altered / is:signed flags for this printing."""
        return artist_proofs.flags_for(self.card.get("set", ""), self.card.get("cn", ""))

    @cached_property
    def is_foil(self) -> bool:
        finish = str(self.entry.get("finish", "")).lower()
        return bool(self.entry.get("isFoil")) or finish in ("foil", "etched")

    def price(self, currency: str):
        """Price in `currency` (usd/eur/tix) — the foil price for foil
        copies when there is one. Falls back to an old flat deck card's
        "price" (EUR)."""
        prices = self.card.get("prices") or {}
        if self.is_foil and prices.get(f"{currency}_foil"):
            return prices[f"{currency}_foil"]
        if prices.get(currency) is not None:
            return prices[currency]
        if currency == "eur" and "price" in self.entry:
            return self.entry["price"]
        return None

    @cached_property
    def language(self) -> set:
        """Language codes + names of the copy (or copies) — the printing's
        own "lang" (always English for Moxfield data) only if the entry
        doesn't say which language its copies are."""
        codes = set()
        entry_lang = self.entry.get("language")
        if isinstance(entry_lang, dict):  # collection entries: {"code", "name"}
            codes.add(str(entry_lang.get("code", "")).lower())
        elif isinstance(entry_lang, str) and entry_lang:  # deck cards: a code
            codes.add(entry_lang.lower())
        # the Collection screen merges a printing's copies in different
        # languages into one entry, and a deck card can use copies in
        # several — code -> copies
        codes.update(str(code).lower() for code in self.entry.get("languages") or {})
        codes.discard("")
        if not codes:
            codes.add(str(self.card.get("lang") or "en").lower())
        return codes | {language_name(code).lower() for code in codes}


# ------------------------------------------------------------- tokenizer

_KEY_RE = re.compile(r"([A-Za-z]+)(!=|<=|>=|:|=|<|>)")


def _read_value(text: str, i: int):
    """Reads one value starting at text[i]: "quoted", /regex/, or a plain
    run up to whitespace or ')'. Returns (_Value, next_index)."""
    if i < len(text) and text[i] == '"':
        end = text.find('"', i + 1)
        if end == -1:
            raise SearchError("Missing closing quote (\")")
        return _Value(text[i + 1:end], "quoted"), end + 1
    if i < len(text) and text[i] == "/":
        j = i + 1
        while j < len(text) and not (text[j] == "/" and text[j - 1] != "\\"):
            j += 1
        if j >= len(text):
            raise SearchError("Missing closing / for regex")
        return _Value(text[i + 1:j], "regex"), j + 1
    j = i
    while j < len(text) and not text[j].isspace() and text[j] not in "()":
        j += 1
    return _Value(text[i:j], "plain"), j


def _tokenize(text: str) -> list[tuple]:
    """Splits a query into tokens: ("(",), (")",), ("-",), ("or",),
    ("and",), ("term", key, op, _Value), ("name", exact, _Value)."""
    tokens = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append((ch,))
            i += 1
        elif ch == "-" and i + 1 < len(text) and not text[i + 1].isspace():
            tokens.append(("-",))
            i += 1
        else:
            exact = ch == "!"
            if exact:
                i += 1
            match = None if exact else _KEY_RE.match(text, i)
            if match:
                key, op = match.group(1).lower(), match.group(2)
                value, i = _read_value(text, match.end())
                if not value.text:
                    raise SearchError(f"'{key}{op}' needs a value")
                tokens.append(("term", key, op, value))
            else:
                value, i = _read_value(text, i)
                if not value.text:
                    raise SearchError("Unexpected character" if not exact else "'!' needs a name after it")
                if value.kind == "plain" and value.text.lower() in ("or", "and"):
                    tokens.append((value.text.lower(),))
                else:
                    tokens.append(("name", exact, value))
    return tokens


# ---------------------------------------------------------------- parser

def compile_query(text: str, context: dict | None = None):
    """Compiles a search query into a predicate: entry dict -> bool. An
    empty/blank query matches everything. Raises SearchError.

    context: app-specific answers the card data alone can't give, supplied
    by the screen doing the search — {"is": {name: entry -> bool}} for the
    CONTEXT_CHECKS is: filters (is:used, is:unique)."""
    tokens = _tokenize(text)
    if not tokens:
        return lambda entry: True
    parser = _Parser(tokens, context or {})
    pred = parser.parse_or()
    if parser.pos < len(tokens):
        raise SearchError("Unmatched ')'")
    return lambda entry: pred(_CardView(entry))


class _Parser:
    """Recursive descent: or_expr := and_expr ("or" and_expr)*;
    and_expr := unary+ (implicit AND; "and" allowed);
    unary := "-" unary | "(" or_expr ")" | term."""

    def __init__(self, tokens, context: dict):
        self.tokens = tokens
        self.context = context
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos][0] if self.pos < len(self.tokens) else None

    def parse_or(self):
        parts = [self.parse_and()]
        while self._peek() == "or":
            self.pos += 1
            parts.append(self.parse_and())
        if len(parts) == 1:
            return parts[0]
        return lambda v: any(p(v) for p in parts)

    def parse_and(self):
        parts = []
        while self._peek() not in (None, ")", "or"):
            if self._peek() == "and":
                self.pos += 1
                continue
            parts.append(self.parse_unary())
        if not parts:
            raise SearchError("Expected a search term" + (" after 'or'" if self.pos else ""))
        if len(parts) == 1:
            return parts[0]
        return lambda v: all(p(v) for p in parts)

    def parse_unary(self):
        token = self.tokens[self.pos]
        self.pos += 1
        if token[0] == "-":
            if self._peek() is None:
                raise SearchError("'-' needs a term after it")
            inner = self.parse_unary()
            return lambda v: not inner(v)
        if token[0] == "(":
            inner = self.parse_or()
            if self._peek() != ")":
                raise SearchError("Missing closing ')'")
            self.pos += 1
            return inner
        if token[0] == ")":
            raise SearchError("Unmatched ')'")
        if token[0] == "name":
            return _name_filter(token[1], token[2])
        _, key, op, value = token
        return _build_filter(key, op, value, self.context)


# --------------------------------------------------------------- filters

def _name_filter(exact: bool, value: _Value):
    if exact:
        target = value.text.lower()
        return lambda v: any(n.lower() == target for n in v.names)
    return lambda v: value.matches_text(v.name)


def _compare(actual, op: str, target) -> bool:
    if op in (":", "="):
        return actual == target
    if op == "!=":
        return actual != target
    if op == "<":
        return actual < target
    if op == "<=":
        return actual <= target
    if op == ">":
        return actual > target
    return actual >= target


def _number(key: str, value: _Value) -> float:
    try:
        return float(value.text)
    except ValueError:
        raise SearchError(f"'{key}' needs a number, got '{value.text}'")


def _only_ops(key, op, allowed=(":", "=", "!=")):
    if op not in allowed:
        raise SearchError(f"'{key}' doesn't support '{op}' — use {' or '.join(allowed)}")


def _build_filter(key: str, op: str, value: _Value, context: dict):
    """Returns a predicate (_CardView -> bool) for one key/op/value term."""
    if key in UNAVAILABLE:
        raise SearchError(f"'{key}:' isn't available — Moxfield doesn't provide {UNAVAILABLE[key]}")

    # "!=" is the negation of "=" for every filter
    if op == "!=" and key not in ("c", "color", "colors", "id", "identity", "ci", "commander"):
        inner = _build_filter(key, "=", value, context)
        return lambda v: not inner(v)

    # --- text
    if key in ("name", "n"):
        _only_ops(key, op)
        return lambda v: any(value.matches_text(n) for n in v.names)
    if key in ("o", "oracle", "text"):
        _only_ops(key, op)
        if value.kind != "regex" and "~" in value.text:
            return lambda v: _Value(value.text.replace("~", v.name), "plain").matches_text(v.oracle)
        return lambda v: value.matches_text(v.oracle)
    if key in ("t", "type"):
        _only_ops(key, op)
        return lambda v: value.matches_text(v.type_line)
    if key in ("ft", "flavor"):
        _only_ops(key, op)
        return lambda v: value.matches_text(v.flavor)
    if key in ("a", "artist"):
        _only_ops(key, op)
        return lambda v: value.matches_text(v.card.get("artist", ""))

    # --- mana cost
    if key in ("m", "mana"):
        _only_ops(key, op, (":", "="))
        wanted = _parse_mana(value.text)
        if op == "=":
            return lambda v: sorted(v.mana_symbols) == sorted(wanted)
        return lambda v: _multiset_contains(v.mana_symbols, wanted)

    # --- numbers
    if key in ("mv", "cmc", "manavalue"):
        if value.text.lower() in ("even", "odd"):
            _only_ops(key, op, (":", "="))
            parity = 0 if value.text.lower() == "even" else 1
            return lambda v: v.card.get("cmc") is not None and int(v.card["cmc"]) % 2 == parity
        target = _number(key, value)
        return lambda v: v.card.get("cmc") is not None and _compare(float(v.card["cmc"]), op, target)
    for keys, field in ((("pow", "power"), "power"), (("tou", "toughness"), "toughness"),
                        (("loy", "loyalty"), "loyalty")):
        if key in keys:
            target = _number(key, value)
            return lambda v, f=field: any(_compare(n, op, target) for n in v.numbers(f))
    if key in ("usd", "eur", "tix"):
        target = _number(key, value)
        return lambda v: (p := v.price(key)) is not None and _compare(float(p), op, target)
    if key in ("qty", "quantity"):
        target = _number(key, value)
        return lambda v: _compare(v.entry.get("quantity", 1), op, target)
    if key == "year":
        target = _number(key, value)
        return lambda v: (d := v.card.get("released_at")) and _compare(int(d[:4]), op, target)

    # --- colors
    if key in ("c", "color", "colors", "id", "identity", "ci", "commander"):
        return _color_filter(key, op, value)

    # --- rarity
    if key in ("r", "rarity"):
        target = RARITY_ALIASES.get(value.text.lower(), value.text.lower())
        if target not in RARITY_ORDER:
            raise SearchError(f"Unknown rarity '{value.text}' — use common, uncommon, rare or mythic")
        rank = RARITY_ORDER.index(target)
        return lambda v: (r := v.card.get("rarity")) in RARITY_ORDER and _compare(RARITY_ORDER.index(r), op, rank)

    # --- printing
    if key in ("s", "set", "e", "edition"):
        _only_ops(key, op, (":", "="))
        return lambda v: str(v.card.get("set", "")).lower() == value.text.lower()
    if key in ("cn", "number"):
        if value.text.isdigit() and op not in (":", "="):
            target = int(value.text)
            return lambda v: str(v.card.get("cn", "")).isdigit() and _compare(int(v.card["cn"]), op, target)
        _only_ops(key, op, (":", "="))
        return lambda v: str(v.card.get("cn", "")).lower() == value.text.lower()
    if key in ("lang", "language"):
        _only_ops(key, op, (":", "="))
        return lambda v: value.text.lower() in v.language
    if key == "border":
        _only_ops(key, op, (":", "="))
        return lambda v: str(v.card.get("border_color", "")).lower() == value.text.lower()
    if key == "frame":
        _only_ops(key, op, (":", "="))
        target = value.text.lower()
        return lambda v: (str(v.card.get("frame", "")).lower() == target
                          or target in [str(e).lower() for e in v.card.get("frame_effects") or []])

    # --- legality
    if key in ("f", "format", "legal", "banned", "restricted"):
        _only_ops(key, op, (":", "="))
        fmt = FORMAT_ALIASES.get(value.text.lower(), value.text.lower())
        if fmt not in FORMATS:
            raise SearchError(f"Unknown format '{value.text}'")
        allowed = {"banned": ("banned",), "restricted": ("restricted",)}.get(key, ("legal", "restricted"))
        return lambda v: (v.card.get("legalities") or {}).get(fmt) in allowed

    # --- is: / not:
    if key in ("is", "not"):
        _only_ops(key, op, (":", "="))
        check = _is_check(value.text.lower(), context)
        if key == "not":
            return lambda v: not check(v)
        return check

    raise SearchError(f"Unknown filter '{key}:' — see Settings → Search syntax")


def _parse_mana(text: str) -> list[str]:
    """"{2}{G}{G}", "2GG" or "{G/U}" -> ["2", "G", "G"] / ["G/U"]."""
    symbols = re.findall(r"\{([^}]+)\}|(\d+)|([A-Za-z])", text)
    result = [(braced or digits or letter).upper() for braced, digits, letter in symbols]
    if not result:
        raise SearchError(f"Couldn't read mana cost '{text}'")
    return result


def _multiset_contains(have: list, want: list) -> bool:
    pool = list(have)
    for symbol in want:
        if symbol not in pool:
            return False
        pool.remove(symbol)
    return True


def _color_filter(key: str, op: str, value: _Value):
    is_identity = key in ("id", "identity", "ci", "commander")
    field = "identity" if is_identity else "colors"
    text = value.text.lower()

    if text.isdigit():  # number of colors, e.g. c>=2
        target = int(text)
        return lambda v: _compare(len(getattr(v, field)), op, target)
    if text in ("m", "multicolor"):
        _only_ops(key, op, (":", "="))
        return lambda v: len(getattr(v, field)) >= 2
    if text in ("c", "colorless"):
        target = set()
        if op == ":":
            op = "="
    else:
        letters = COLOR_NAMES.get(text, text)
        if not letters or any(ch not in "wubrg" for ch in letters):
            raise SearchError(f"Unknown color '{value.text}' — use letters like wubrg, or a name like 'azorius'")
        target = set(letters)

    if op == ":":
        # c:rg = at least red and green; id:rg = fits in a red-green deck
        op = "<=" if is_identity else ">="
    if op == "!=":
        return lambda v: getattr(v, field) != target
    return lambda v: _compare_sets(getattr(v, field), op, target)


def _compare_sets(actual: set, op: str, target: set) -> bool:
    if op == "=":
        return actual == target
    if op == ">=":
        return actual >= target
    if op == "<=":
        return actual <= target
    if op == ">":
        return actual > target
    return actual < target


# is: filters that need the user's decks / collection — the screen doing
# the search supplies them (compile_query's context); where it doesn't,
# the filter explains where it works.
CONTEXT_CHECKS = {
    "used": "'is:used' works in the Collection and Deck Maker searches",
    "unique": "'is:unique' works in the Collection, deck and Deck Maker searches",
}


def _is_check(what: str, context: dict):
    """Predicate for is:<what> / not:<what>."""
    checks = {
        "foil": lambda v: v.is_foil,
        "nonfoil": lambda v: not v.is_foil,
        "etched": lambda v: str(v.entry.get("finish", "")).lower() == "etched",
        # special copies — ticked in Settings → Custom card images (per
        # printing); altered also counts Moxfield's own "altered" mark
        "proof": lambda v: "proof" in v.custom_flags,
        "signed": lambda v: "signed" in v.custom_flags,
        "altered": lambda v: "altered" in v.custom_flags or bool(v.entry.get("isAlter")),
        "alter": lambda v: "altered" in v.custom_flags or bool(v.entry.get("isAlter")),
        "proxy": lambda v: bool(v.entry.get("isProxy")),
        "reserved": lambda v: bool(v.card.get("reserved")),
        "reprint": lambda v: bool(v.card.get("reprint")),
        "digital": lambda v: bool(v.card.get("digital")),
        "commander": lambda v: ("legendary" in v.front_type and "creature" in v.front_type)
                               or "can be your commander" in v.oracle.lower(),
        "spell": lambda v: "land" not in v.front_type,
        "permanent": lambda v: any(t in v.front_type for t in PERMANENT_TYPES),
        "historic": lambda v: any(t in v.front_type for t in ("legendary", "artifact", "saga")),
        "vanilla": lambda v: "creature" in v.front_type and not v.oracle.strip(),
        "dfc": lambda v: v.card.get("layout") in DFC_LAYOUTS,
        "mdfc": lambda v: v.card.get("layout") == "modal_dfc",
        "transform": lambda v: v.card.get("layout") == "transform",
        "split": lambda v: v.card.get("layout") == "split",
        "adventure": lambda v: v.card.get("layout") == "adventure",
        "flip": lambda v: v.card.get("layout") == "flip",
        "meld": lambda v: v.card.get("layout") == "meld",
        "multicolor": lambda v: len(v.colors) >= 2,
        "colorless": lambda v: not v.colors,
    }
    if what in CONTEXT_CHECKS:
        check = context.get("is", {}).get(what)
        if check is None:
            raise SearchError(CONTEXT_CHECKS[what])
        return lambda v: check(v.entry)
    if what not in checks:
        raise SearchError(f"Unknown 'is:{what}' — supported: {', '.join(sorted([*checks, *CONTEXT_CHECKS]))}")
    return checks[what]
