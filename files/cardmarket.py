"""Cardmarket purchase PDF -> a purchase "collection" (+ Moxfield export).

Formerly the standalone cardmarket_to_moxfield.py script. Steps:
  1. extract_text()   — the PDF's text (pdftotext if installed, else pdfplumber)
  2. parse_purchase() — order header (number, seller, date, totals) + one
                        dict per card line
  3. resolve_entries() — looks every line up on Scryfall and builds entries
                        in the same shape as Moxfield collection entries,
                        so the Collection screen / card grid / search /
                        card modal all work on a purchase unchanged
  4. moxfield_csv() / moxfield_list() — Moxfield import files

import_purchase() runs 1-3 (plus an automatic cross-check against the
shipment CSV Cardmarket offers, if it's next to the PDF) and returns the
purchase dict that models.purchases saves.
"""

import csv
import io
import re
import subprocess
from datetime import datetime
from pathlib import Path

import scryfall

# ---------------------------------------------------------------- settings
# Cardmarket condition -> (Moxfield CSV condition, Moxfield API condition)
CONDITION = {
    "MT": ("Mint", "mint"),
    "NM": ("Near Mint", "nearMint"),
    "EX": ("Lightly Played", "lightlyPlayed"),
    "GD": ("Played", "moderatelyPlayed"),
    "LP": ("Played", "moderatelyPlayed"),
    "PL": ("Heavily Played", "heavilyPlayed"),
    "PO": ("Damaged", "damaged"),
}
# Cardmarket language -> (Moxfield CSV name, Scryfall / app language code)
LANGUAGE = {
    "EN": ("English", "en"), "DE": ("German", "de"), "FR": ("French", "fr"),
    "IT": ("Italian", "it"), "ES": ("Spanish", "es"), "PT": ("Portuguese", "pt"),
    "JP": ("Japanese", "ja"), "KO": ("Korean", "ko"), "RU": ("Russian", "ru"),
    "S-CHN": ("Chinese Simplified", "zhs"), "T-CHN": ("Chinese Traditional", "zht"),
}
RARITY = {"C": "common", "U": "uncommon", "R": "rare", "M": "mythic", "L": "common",
          "T": "common", "S": "special", "P": "special", "B": "bonus"}
# Cardmarket set codes that differ from Scryfall/Moxfield codes.
SET_FIX = {
    "TP": "tmp",   # Tempest
}
# Cardmarket "reprint" sets (The List, Mystery Booster, ...). The collector
# number printed is the ORIGINAL set's, so only the name is trusted.
NAME_ONLY_SETS = {"ZNL", "MYS", "IBS", "PLST", "LIST", "SLX"}
# ---------------------------------------------------------------------------

LANG_RE = "|".join(sorted(map(re.escape, LANGUAGE), key=len, reverse=True))
COND_RE = "|".join(CONDITION)
LINE_RE = re.compile(
    rf"^(?P<qty>\d+)\s+(?P<name>.+?)\s+(?:(?P<num>[0-9]+[a-z]?)\s+)?"
    rf"(?P<lang>{LANG_RE})\s+(?P<cond>{COND_RE})\s+(?P<set>[A-Z0-9]{{2,6}})\s+"
    rf"(?P<rarity>[CURMLTSPB])\b(?P<rest>.*?)\s*(?P<price>\d+,\d{{2}})\s*EUR\s*$"
)


class CardmarketError(Exception):
    """A purchase PDF couldn't be read / isn't a Cardmarket purchase."""


# ------------------------------------------------------------- reading

def extract_text(pdf: Path) -> str:
    """The PDF's text, one line per printed line. pdftotext -raw if it's
    installed (poppler), else pdfplumber — x_tolerance=1, since its
    default glues words together ("TidalFlats")."""
    try:
        return subprocess.run(["pdftotext", "-raw", str(pdf), "-"],
                              capture_output=True, text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    try:
        import pdfplumber
    except ImportError:
        raise CardmarketError("Reading PDFs needs pdfplumber: run  pip install pdfplumber")
    with pdfplumber.open(pdf) as doc:
        return "\n".join(p.extract_text(x_tolerance=1) or "" for p in doc.pages)


def _euro(text: str) -> float:
    """"1.234,56" -> 1234.56"""
    return float(text.replace(".", "").replace(",", "."))


def _header_value(text: str, pattern: str):
    m = re.search(pattern, text, re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_purchase(text: str) -> dict:
    """Parses a purchase PDF's text: {"order_id", "seller", "date"
    (ISO, paid date if shown, else sent date), "article_value",
    "shipping", "total" (floats, EUR, None if missing), "lines": [card
    line dicts], "skipped": [lines that looked like cards but didn't
    parse]}."""
    lines, skipped = [], []
    in_singles = False
    for line in text.splitlines():
        line = line.strip()
        if line.endswith("Singles:"):
            in_singles = True
            continue
        if not in_singles or not line:
            continue
        if line.startswith("Shipment History"):
            break
        m = LINE_RE.match(line)
        if not m:
            if re.match(r"^\d+\s", line):
                skipped.append(line)
            continue
        d = m.groupdict()
        name = re.sub(r"\s*\(V\.\d+\)$", "", d["name"]).strip()
        name = re.sub(r"\s*/{1,2}\s*", " // ", name)
        lines.append({
            "qty": int(d["qty"]),
            "name": name,
            "number": d["num"] or "",
            "cm_set": d["set"],
            "cm_condition": d["cond"],
            "cm_language": d["lang"],
            "rarity": RARITY.get(d["rarity"], ""),
            "foil": d["rest"].strip().lower().startswith("foil"),
            "price": _euro(d["price"]),
        })

    date = None
    for label in ("Paid", "Sent"):
        raw = _header_value(text, rf"{label}:\s*(\d{{2}}\.\d{{2}}\.\d{{4}})")
        if raw:
            date = datetime.strptime(raw, "%d.%m.%Y").date().isoformat()
            break

    def money(label):
        raw = _header_value(text, rf"^{label}\s+([\d.,]+)\s*EUR")
        return _euro(raw) if raw else None

    return {
        "order_id": _header_value(text, r"Purchase\s*#\s*(\d+)"),
        "seller": _header_value(text, r"Seller\s*-\s*(\S+)"),
        "date": date,
        "article_value": money("Article\\s*Value"),
        "shipping": money("Shipping"),
        "total": money("Total"),
        "lines": lines,
        "skipped": skipped,
    }


def cardmarket_set_and_number(cm_set: str, num: str):
    """Best-guess Scryfall (set, collector number) from Cardmarket's.
    "" for either when Cardmarket's can't be trusted."""
    if cm_set in NAME_ONLY_SETS:
        return "", ""
    if cm_set in SET_FIX:
        return SET_FIX[cm_set], num
    if cm_set.startswith("X") and len(cm_set) == 4:   # Cardmarket "extras" (XKHM -> khm)
        return cm_set[1:].lower(), num
    if cm_set.startswith("P") and len(cm_set) == 4:   # promos: numbering differs, drop it
        return cm_set.lower(), ""
    return cm_set.lower(), num


# ------------------------------------------------------- Scryfall lookup

def _norm(name: str) -> str:
    """Name for comparisons: lower-case letters/digits only."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _names_match(cm_name: str, card: dict) -> bool:
    """Cardmarket's name vs a Scryfall card: full name or front face
    (Cardmarket sometimes lists only the front of a double-faced card)."""
    want = _norm(cm_name)
    names = [card.get("name", "")] + [f.get("name", "") for f in card.get("card_faces") or []]
    return want in {_norm(n) for n in names} or want == _norm(card.get("name", "").split("//")[0])


def _price(value):
    return float(value) if value not in (None, "") else None


def moxfield_card(sc: dict) -> dict:
    """Scryfall card object -> the "card" part of a Moxfield collection
    entry (the fields the app reads)."""
    faces = [
        {k: f.get(k) for k in ("name", "mana_cost", "type_line", "oracle_text", "colors",
                               "power", "toughness") if k in f}
        for f in sc.get("card_faces") or []
    ]
    colors = sc.get("colors")
    if colors is None:  # double-faced: colors live on the faces
        colors = sorted({c for f in faces for c in f.get("colors") or []})
    prices = sc.get("prices") or {}
    return {
        "scryfall_id": sc.get("id", ""),
        "set": sc.get("set", ""),
        "set_name": sc.get("set_name", ""),
        "name": sc.get("name", ""),
        "cn": sc.get("collector_number", ""),
        "layout": sc.get("layout", ""),
        "cmc": sc.get("cmc", 0.0),
        "type_line": sc.get("type_line", ""),
        "oracle_text": sc.get("oracle_text", ""),
        "mana_cost": sc.get("mana_cost", ""),
        "power": sc.get("power"),
        "toughness": sc.get("toughness"),
        "colors": colors,
        "color_identity": sc.get("color_identity", []),
        "legalities": sc.get("legalities", {}),
        "frame": sc.get("frame", ""),
        "frame_effects": sc.get("frame_effects", []),
        "reserved": sc.get("reserved", False),
        "digital": sc.get("digital", False),
        "foil": sc.get("foil", False),
        "nonfoil": sc.get("nonfoil", False),
        "rarity": sc.get("rarity", ""),
        "border_color": sc.get("border_color", ""),
        "lang": sc.get("lang", "en"),
        "reprint": sc.get("reprint", False),
        "prices": {k: _price(prices.get(k)) for k in ("eur", "eur_foil", "usd", "usd_foil", "tix")},
        "card_faces": faces,
        "artist": sc.get("artist", ""),
        "promo_types": sc.get("promo_types", []),
        "released_at": sc.get("released_at", ""),
    }


def _is_promo_set(cm_set: str) -> bool:
    """Cardmarket promo sets: its catch-all "PROM" (Promos — own
    numbering, no Scryfall equivalent) and "P" + set code (PEOE, ...)."""
    return cm_set.startswith("P") and len(cm_set) == 4


def _promo_printing(line: dict):
    """For a promo line the set lookups couldn't place: Scryfall's paper
    promo printings of the card, preferring the same collector number,
    then one that comes in the line's finish (foil / nonfoil). None if
    the card has no promo printing."""
    promos = [c for c in scryfall._search_prints(f'!"{line["name"]}" is:promo game:paper')
              if _names_match(line["name"], c)]
    if not promos:
        return None
    finish = "foil" if line["foil"] else "nonfoil"
    return (next((c for c in promos if c["collector_number"] == line["number"]), None)
            or next((c for c in promos if c.get(finish)), None)
            or promos[0])


def _collection_round(lines, guesses, results, make_identifier):
    """One /cards/collection round: builds an identifier for every
    still-unresolved line (make_identifier(line, set, number) -> dict or
    None to skip) and fills in results for the hits."""
    todo = {}  # index -> identifier
    for i, (line, (s, n)) in enumerate(zip(lines, guesses)):
        if results[i] is None:
            ident = make_identifier(line, s, n)
            if ident:
                todo[i] = ident
    if not todo:
        return
    unique = list({tuple(sorted(d.items())): d for d in todo.values()}.values())
    found = scryfall.cards_collection(unique)
    by_number = {(c["set"], c["collector_number"]): c for c in found}
    for i, ident in todo.items():
        line = lines[i]
        if "collector_number" in ident:
            card = by_number.get((ident["set"], ident["collector_number"]))
        else:
            card = next((c for c in found if _names_match(line["name"], c)
                         and ("set" not in ident or c["set"] == ident["set"])), None)
        if card and _names_match(line["name"], card):
            results[i] = card


def _lookup(lines: list) -> list:
    """Scryfall card (or None) for each line. Tries, in rounds, each
    still-unresolved line's set + number, then name + set, then (promo
    lines only) a promo printing of the name, then name alone; a set +
    number hit only counts if the name matches too (Cardmarket's
    numbering occasionally differs from Scryfall's)."""
    results = [None] * len(lines)
    guesses = [cardmarket_set_and_number(l["cm_set"], l["number"]) for l in lines]

    _collection_round(lines, guesses, results,
                      lambda l, s, n: {"set": s, "collector_number": n} if s and n else None)
    _collection_round(lines, guesses, results,
                      lambda l, s, n: {"name": l["name"], "set": s} if s else None)
    # Promo whose set Scryfall doesn't know (e.g. Cardmarket's "PROM"):
    # without this, the name lookup below picks a regular printing.
    for i, line in enumerate(lines):
        if results[i] is None and _is_promo_set(line["cm_set"]):
            results[i] = _promo_printing(line)
    _collection_round(lines, guesses, results, lambda l, s, n: {"name": l["name"]})

    # A name lookup returns Scryfall's default printing, which can be an
    # online-only one (e.g. Masters Edition IV) with no euro price —
    # swap those for the cheapest paper printing.
    for i, card in enumerate(results):
        if card and card.get("digital"):
            name = card["name"]
            paper = (scryfall._search_prints(f'!"{name}" game:paper eur>0')
                     or scryfall._search_prints(f'!"{name}" game:paper'))
            if paper:
                results[i] = paper[0]
    return results


def resolve_entries(lines: list) -> list:
    """Card lines -> Moxfield-collection-shaped entries (looked up on
    Scryfall). Lines Scryfall couldn't find keep a bare card (name /
    Cardmarket set, no image or price) and "unresolved": True."""
    entries = []
    for i, (line, sc) in enumerate(zip(lines, _lookup(lines))):
        if sc:
            card = moxfield_card(sc)
        else:
            s, n = cardmarket_set_and_number(line["cm_set"], line["number"])
            card = {"name": line["name"], "set": s or line["cm_set"].lower(), "cn": n,
                    "rarity": line["rarity"], "prices": {}, "colors": [], "type_line": "",
                    "lang": "en", "card_faces": []}
        lang_name, lang_code = LANGUAGE[line["cm_language"]]
        entries.append({
            "id": f"cm{i}",
            "quantity": line["qty"],
            "condition": CONDITION[line["cm_condition"]][1],
            "finish": "foil" if line["foil"] else "nonFoil",
            "isFoil": line["foil"],
            "purchasePrice": line["price"],
            "rarity": card.get("rarity", ""),
            "language": {"code": lang_code, "name": lang_name},
            "unresolved": sc is None,
            "cardmarket": line,  # the original line, for the Moxfield export
            "card": card,
        })
    return entries


# ------------------------------------------------------------ cross-check

def check_shipment_csv(lines: list, csv_path: Path) -> str:
    """Compares card / foil counts with Cardmarket's shipment CSV (which
    has product IDs only, no names). Returns a one-line verdict."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    csv_qty = sum(int(r["groupCount"]) for r in rows)
    csv_foil = sum(int(r["groupCount"]) for r in rows if r.get("isFoil") == "1")
    pdf_qty = sum(l["qty"] for l in lines)
    pdf_foil = sum(l["qty"] for l in lines if l["foil"])
    ok = csv_qty == pdf_qty and csv_foil == pdf_foil
    return (f"Shipment CSV check: cards {pdf_qty}/{csv_qty}, foils {pdf_foil}/{csv_foil} — "
            + ("OK" if ok else "MISMATCH, some lines may be missing"))


def import_purchase(pdf: Path) -> dict:
    """Reads, parses and resolves a purchase PDF. Returns the purchase
    dict models.purchases saves. Raises CardmarketError if the PDF has
    no card lines (or can't be read), requests errors if Scryfall can't
    be reached."""
    pdf = Path(pdf)
    parsed = parse_purchase(extract_text(pdf))
    if not parsed["lines"]:
        raise CardmarketError("No card lines found — is this a Cardmarket purchase PDF?")

    check = None
    if parsed["order_id"]:
        csv_path = pdf.parent / f"ArticlesFromShipment{parsed['order_id']}.csv"
        if csv_path.exists():
            check = check_shipment_csv(parsed["lines"], csv_path)

    order = parsed["order_id"]
    return {
        "id": order or datetime.now().strftime("%Y%m%d%H%M%S"),
        "name": f"Purchase #{order}" if order else pdf.stem,
        "source": "cardmarket",
        "source_file": pdf.name,
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "seller": parsed["seller"],
        "date": parsed["date"],
        "article_value": parsed["article_value"],
        "shipping": parsed["shipping"],
        "total": parsed["total"],
        "skipped": parsed["skipped"],
        "csv_check": check,
        "entries": resolve_entries(parsed["lines"]),
    }


# ------------------------------------------------------- Moxfield export

def _export_set_and_number(entry: dict):
    """(set, number) for Moxfield: the Scryfall printing when it was
    resolved, else the best guess from Cardmarket's codes."""
    if not entry.get("unresolved"):
        return entry["card"]["set"], entry["card"]["cn"]
    line = entry["cardmarket"]
    return cardmarket_set_and_number(line["cm_set"], line["number"])


def moxfield_csv(entries: list) -> str:
    """Moxfield > Collection > Import (CSV) file contents."""
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(["Count", "Tradelist Count", "Name", "Edition", "Condition",
                "Language", "Foil", "Tags", "Last Modified", "Collector Number",
                "Alter", "Proxy", "Purchase Price"])
    for e in entries:
        line = e["cardmarket"]
        edition, number = _export_set_and_number(e)
        w.writerow([e["quantity"], 0, e["card"]["name"], edition,
                    CONDITION[line["cm_condition"]][0], LANGUAGE[line["cm_language"]][0],
                    "foil" if e["isFoil"] else "", "", "", number, "False", "False",
                    f'{e["purchasePrice"]:.2f}'])
    return out.getvalue()


def moxfield_list(entries: list) -> str:
    """Plain decklist text for a Moxfield deck / binder "Import" box."""
    rows = []
    for e in entries:
        edition, number = _export_set_and_number(e)
        row = f'{e["quantity"]} {e["card"]["name"]}'
        if edition:
            row += f" ({edition.upper()})"
            if number:
                row += f" {number}"
        if e["isFoil"]:
            row += " *F*"
        rows.append(row)
    return "\n".join(rows) + "\n"
