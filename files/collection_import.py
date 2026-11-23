"""Importing your collection from Moxfield's CSV export — the backup for
when Moxfield's API can't be reached (moxfield.com → Collection → Export →
CSV, while logged in). The file holds what only Moxfield knows — how many
of which printing, foil, language, condition — and everything else comes
from Scryfall: each row's card is looked up by set + collector number
(then set + name, then name) through scryfall.cards_collection, 75 per
request.

The result is saved exactly where a Moxfield collection refresh saves
(models/collection.py's cache file, same entry shape), so every screen
reads it as usual, and prices then update from Scryfall (sync.py).

The CSV's columns (Moxfield writes them all quoted):
    Count, Tradelist Count, Name, Edition, Condition, Language, Foil,
    Tags, Last Modified, Collector Number, Alter, Proxy, Purchase Price
"""

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

import cache_io
import paths
import scryfall
from cardmarket import moxfield_card

REQUIRED = ("Count", "Name", "Edition", "Collector Number")

LANGUAGES = {  # Moxfield's language names -> the app's (Scryfall's) codes
    "english": "en", "german": "de", "french": "fr", "italian": "it", "spanish": "es",
    "portuguese": "pt", "japanese": "ja", "korean": "ko", "russian": "ru",
    "chinese simplified": "zhs", "simplified chinese": "zhs",
    "chinese traditional": "zht", "traditional chinese": "zht",
    "hebrew": "he", "latin": "la", "ancient greek": "grc", "arabic": "ar",
    "sanskrit": "sa", "phyrexian": "ph", "quenya": "qya",
}
CONDITIONS = {  # Moxfield's condition names -> the entry codes Moxfield's API uses
    "mint": "mint", "near mint": "nearMint", "lightly played": "lightlyPlayed",
    "good (lightly played)": "lightlyPlayed", "played": "moderatelyPlayed",
    "moderately played": "moderatelyPlayed", "heavily played": "heavilyPlayed",
    "damaged": "damaged",
}


def _key(text: str) -> str:
    return " ".join((text or "").lower().split())


def _name_key(name: str) -> str:
    """Card names compared loosely: case, spacing and "/" vs "//"."""
    return re.sub(r"\s*/+\s*", " // ", _key(name))


def parse(text: str) -> list[dict]:
    """The CSV's rows as {"quantity", "name", "set", "cn", "finish",
    "language", "condition", "alter", "proxy", "purchase_price"}. Raises
    ValueError if it isn't a Moxfield collection export."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError("This doesn't look like a Moxfield collection export "
                         f"(missing column{'s' if len(missing) > 1 else ''}: {', '.join(missing)}).")
    rows = []
    for raw in reader:
        try:
            quantity = int((raw.get("Count") or "0").strip())
        except ValueError:
            continue
        name = (raw.get("Name") or "").strip()
        if quantity <= 0 or not name:
            continue
        foil = _key(raw.get("Foil"))
        try:
            price = float((raw.get("Purchase Price") or "").strip() or 0)
        except ValueError:
            price = 0.0
        rows.append({
            "quantity": quantity,
            "name": name,
            "set": _key(raw.get("Edition")),
            "cn": (raw.get("Collector Number") or "").strip(),
            "finish": "etched" if foil == "etched" else "foil" if foil == "foil" else "nonFoil",
            "language": LANGUAGES.get(_key(raw.get("Language")), "en"),
            "condition": CONDITIONS.get(_key(raw.get("Condition")), "nearMint"),
            "alter": _key(raw.get("Alter")) == "true",
            "proxy": _key(raw.get("Proxy")) == "true",
            "purchase_price": price,
        })
    return rows


def resolve(rows: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """Looks every row's card up on Scryfall. Returns ([(row, scryfall
    card)], [rows not found]). Three rounds, each only for what's still
    missing: set + collector number, then set + name, then name alone
    (Scryfall's current default printing)."""
    found, todo = [], list(rows)
    rounds = (
        (lambda r: {"set": r["set"], "collector_number": r["cn"]} if r["set"] and r["cn"] else None,
         lambda r, sc: sc.get("set") == r["set"] and sc.get("collector_number", "").lower() == r["cn"].lower()),
        (lambda r: {"name": r["name"], "set": r["set"]} if r["set"] else None,
         lambda r, sc: sc.get("set") == r["set"] and _matches(r["name"], sc)),
        (lambda r: {"name": r["name"]},
         lambda r, sc: _matches(r["name"], sc)),
    )
    for make_identifier, matches in rounds:
        asked = [(r, make_identifier(r)) for r in todo]
        identifiers = [ident for _, ident in asked if ident]
        if not identifiers:
            continue
        # one request per distinct identifier (a printing can be on several rows)
        unique = list({tuple(sorted(i.items())): i for i in identifiers}.values())
        cards = scryfall.cards_collection(unique)
        still = []
        for row, ident in asked:
            card = next((sc for sc in cards if matches(row, sc)), None) if ident else None
            if card is None:
                still.append(row)
            else:
                found.append((row, card))
        todo = still
        if not todo:
            break
    return found, todo


def _matches(name: str, sc: dict) -> bool:
    """A row's name against a Scryfall card: the full name or any face's."""
    wanted = _name_key(name)
    names = [sc.get("name", "")] + [f.get("name", "") for f in sc.get("card_faces") or []]
    return any(_name_key(n) == wanted for n in names) or _name_key(sc.get("name", "")).startswith(wanted + " //")


def entry(row: dict, sc: dict, number: int) -> dict:
    """One collection entry, in the shape Moxfield's API returns (what
    models/collection.py and every screen read)."""
    card = moxfield_card(sc)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": f"csv{number}",
        "quantity": row["quantity"],
        "condition": row["condition"],
        "game": "paper",
        "finish": row["finish"],
        "isFoil": row["finish"] == "foil",
        "isAlter": row["alter"],
        "isProxy": row["proxy"],
        "purchasePrice": row["purchase_price"],
        "createdAtUtc": now,
        "lastUpdatedAtUtc": now,
        "rarity": card.get("rarity", ""),
        "language": {"code": row["language"], "name": _language_name(row["language"])},
        "card": card,
    }


def _language_name(code: str) -> str:
    return next((name.title() for name, c in LANGUAGES.items() if c == code), code)


def import_file(path: Path, collection_id: str) -> tuple[str, list[dict]]:
    """Reads the CSV, looks the cards up and saves them as the collection
    (replacing the cached one). Returns (summary, rows not found)."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    rows = parse(text)
    if not rows:
        raise ValueError("The file has no cards in it.")
    found, missing = resolve(rows)
    entries = [entry(row, sc, n) for n, (row, sc) in enumerate(found, start=1)]
    total = sum(e["quantity"] for e in entries)
    cache_io.write_json(paths.collection_cache_path(collection_id), {
        "totalOverall": total,
        "data": entries,
        "source": "moxfield-csv",
        "importedFrom": Path(path).name,
    })
    summary = f"{total} cards ({len(entries)} unique) from {Path(path).name}"
    if missing:
        summary += f", {len(missing)} row{'s' if len(missing) != 1 else ''} not found on Scryfall"
    return summary, missing
