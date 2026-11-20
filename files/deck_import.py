"""Importing a decklist in Moxfield's text format as a Deck Maker (local)
deck — the reverse of deck_export.py. Accepted lines:

    1 Sol Ring (C21) 263        exact printing
    1 Lightning Bolt (2X2) 117 *F*   ... foil (*E* = etched)
    1 Sol Ring                  name only -> the newest regular paper printing
    10 Mountain
    1x Sol Ring                 "1x" works too
    1 Sol Ring (CMM) 410 #!Ramp #!Cost reducer   Moxfield tags are ignored
    1 Jidoor, Aristocratic Capital / Overture    "/" or "//" between faces

Sections: Moxfield's own export puts the commander(s) first, then a
blank line, then the rest; headers like "Commander", "Deck",
"Sideboard:" are understood too. Sideboard / maybeboard / considering /
tokens sections are left out.

Printings are looked up on Scryfall in batches (75 exact printings or 15
names per request, through the shared rate limiter).
"""

import re
from datetime import date


import scryfall
from cardmarket import moxfield_card

LINE_RE = re.compile(
    r"^(?P<qty>\d+)x?\s+(?P<name>.+?)"
    r"(?:\s+\((?P<set>[A-Za-z0-9]{2,6})\)(?:\s+(?P<cn>[^\s*]+))?)?"
    r"(?P<flags>(?:\s+\*[A-Za-z]+\*)*)\s*$"
)
COMMANDER_HEADERS = {"commander", "commanders"}
MAIN_HEADERS = {"deck", "main", "mainboard", "main deck"}
SKIPPED_HEADERS = {"sideboard", "maybeboard", "considering", "tokens", "companion", "attractions",
                   "stickers", "planes", "schemes"}
NAME_BATCH = 15


def parse(text: str) -> dict:
    """{"commanders": [line], "cards": [line], "unreadable": [str]} — a line
    is {"qty", "name", "set", "cn", "foil", "etched"}. Without section
    headers, a first block of 1-2 lines followed by a blank line is taken
    as the commander(s) (Moxfield's export layout)."""
    blocks, current = [], []  # blank-line separated groups of (section, line)
    section, has_headers = "main", False
    unreadable = []
    for raw in text.splitlines():
        line = raw.strip()
        header = line.rstrip(":").strip().lower()
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        if header in COMMANDER_HEADERS | MAIN_HEADERS | SKIPPED_HEADERS:
            # only Commander / Deck headers mean the list marks its sections
            # itself — a lone "Sideboard:" doesn't (Moxfield's export has one)
            has_headers = has_headers or header not in SKIPPED_HEADERS
            if current:  # a header also ends the block before it
                blocks.append(current)
                current = []
            section = ("commander" if header in COMMANDER_HEADERS else
                       "main" if header in MAIN_HEADERS else "skip")
            continue
        if line.startswith(("//", "#")):  # comments
            continue
        line = re.sub(r"\s+#.*$", "", line)  # Moxfield tags ("#!Ramp", "#!Cost reducer", ...)
        m = LINE_RE.match(line)
        if not m:
            unreadable.append(line)
            continue
        flags = m.group("flags").upper()
        current.append((section, {
            "qty": int(m.group("qty")),
            "name": re.sub(r"\s+/{1,2}\s+", " // ", m.group("name").strip()),  # "A / B" -> "A // B"
            "set": (m.group("set") or "").lower(),
            "cn": m.group("cn") or "",
            "foil": "*F*" in flags,
            "etched": "*E*" in flags,
        }))
    if current:
        blocks.append(current)

    if not has_headers and len(blocks) >= 2 and len(blocks[0]) <= 2:
        blocks[0] = [("commander", l) for _, l in blocks[0]]  # Moxfield export layout
    lines = [pair for block in blocks for pair in block]
    return {
        "commanders": [l for s, l in lines if s == "commander"],
        "cards": [l for s, l in lines if s == "main"],
        "unreadable": unreadable,
    }


def _norm(name: str) -> str:
    return name.lower().strip()


def _matches(name: str, card: dict) -> bool:
    """Full name or front face — not a back face ("Lightning Bolt" must not
    match "Emeritus of Conflict // Lightning Bolt")."""
    full = _norm(card["name"])
    return _norm(name) in (full, full.split(" // ")[0])


# "Newest printing" means the newest normal one a player would pick:
# released, paper, not The List's reprint sheet (numbers like "INR-97"),
# not Art Series / other memorabilia (art cards without rules text), not
# serialized — and sold in the finish asked for (non-foil unless *F*).
NEWEST_FILTER = ("game:paper date<={today} -set:plst -st:memorabilia -layout:art_series "
                 "-is:serialized is:{finish}")


def _newest(names: list, foil: bool = False) -> dict:
    """{name: newest printing} (see NEWEST_FILTER) — regular printings
    first, then promos too for names only printed as promos, then without
    the finish filter as a last resort."""
    found = {}
    base = NEWEST_FILTER.format(today=date.today().isoformat(), finish="foil" if foil else "nonfoil")
    for extra in ("-is:promo", "", None):
        query_filter = (f"{base} {extra}" if extra is not None
                        else f"game:paper date<={date.today()} -st:memorabilia")
        todo = [n for n in dict.fromkeys(names) if n not in found]
        for i in range(0, len(todo), NAME_BATCH):
            batch = todo[i:i + NAME_BATCH]
            clauses = " or ".join(f'!"{n}"' for n in batch)
            for card in scryfall.search(f"({clauses}) {query_filter} prefer:newest"):
                for n in batch:
                    if n not in found and _matches(n, card):
                        found[n] = card
    return found


def resolve(lines: list) -> tuple[list, list]:
    """Scryfall card for each line: its exact printing when "(SET) number"
    is given (falling back to the name if that printing doesn't exist),
    else the newest printing. Returns ([(line, card)], [names not found])."""
    exact = [l for l in lines if l["set"] and l["cn"]]
    by_printing = {}
    if exact:
        ids = list({(l["set"], l["cn"]): {"set": l["set"], "collector_number": l["cn"]}
                    for l in exact}.values())
        for card in scryfall.cards_collection(ids):
            by_printing[(card["set"], card["collector_number"].lower())] = card

    resolved, by_name_lines = [], []
    for l in lines:
        card = by_printing.get((l["set"], l["cn"].lower())) if l["set"] and l["cn"] else None
        if card and _matches(l["name"], card):
            resolved.append((l, card))
        else:
            by_name_lines.append(l)

    newest = {**_newest([l["name"] for l in by_name_lines if not l["foil"] and not l["etched"]]),
              **_newest([l["name"] for l in by_name_lines if l["foil"] or l["etched"]], foil=True)}
    missing = []
    for l in by_name_lines:
        if l["name"] in newest:
            resolved.append((l, newest[l["name"]]))
        else:
            missing.append(l["name"])
    order = {id(l): i for i, l in enumerate(lines)}  # keep the list's order
    resolved.sort(key=lambda pair: order[id(pair[0])])
    return resolved, missing


def deck_card(line: dict, sc: dict) -> dict:
    """A resolved line -> a deck file card (models.deck.Deck.cards shape)."""
    card = moxfield_card(sc)
    finish = "etched" if line["etched"] else "foil" if line["foil"] else "nonFoil"
    prices = card["prices"]
    price = (prices.get("eur_foil") if finish != "nonFoil" else None) or prices.get("eur") or 0
    return {
        "name": card["name"],
        "set": card["set"],
        "cn": card["cn"],
        "quantity": line["qty"],
        "price": price,
        "image_url": scryfall.image_url(card["scryfall_id"]),
        "type_line": card["type_line"],
        "isFoil": finish != "nonFoil",
        "finish": finish,
        "language": "en",
        "card": card,
    }
