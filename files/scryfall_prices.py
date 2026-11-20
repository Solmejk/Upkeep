"""Collection prices from Scryfall instead of Moxfield (Moxfield's lag a
day or more behind — Scryfall updates once a day).

refresh() runs after each Moxfield collection refresh (sync.py): it looks
up every printing's prices with Scryfall's batch endpoint (75 cards per
request, through scryfall.py's shared rate limiter — ~45 requests for a
3,000+ printing collection) and saves them to cache/collection_prices.json.
At most once a day: Scryfall only updates daily, so a second refresh the
same day only looks up printings that are new since the last fetch.

apply() overlays the saved prices onto collection entries (models/
collection.py calls it on every load), so the stats, sorting, card popup
and value chart all use them. Printings Scryfall didn't return keep
Moxfield's price. The cache file is named collection_*.json so clearing
the collection cache clears it too.
"""

from datetime import date

import cache_io
import paths
import scryfall

PRICE_KEYS = ("eur", "eur_foil", "usd", "usd_foil")


def _load() -> dict:
    """{"fetched": "YYYY-MM-DD", "prices": {scryfall_id: {key: float|None}}}"""
    return cache_io.read_json(paths.COLLECTION_PRICES_PATH) or {"fetched": None, "prices": {}}


def saved() -> dict:
    """The last fetch: {"fetched": "YYYY-MM-DD" | None, "prices": {...}}."""
    return _load()


def _to_float(value):
    return float(value) if value not in (None, "") else None


def refresh(entries: list) -> str:
    """Fetches Scryfall prices for the collection's printings — all of
    them once a day, else only ones not fetched yet. Returns a short
    summary for the sync log. Raises on network errors (the caller keeps
    Moxfield's prices then)."""
    today = date.today().isoformat()
    saved = _load()
    ids = {e["card"].get("scryfall_id") for e in entries} - {None, ""}
    if saved["fetched"] == today:
        todo = sorted(ids - saved["prices"].keys())
        if not todo:
            return "already fetched today"
        prices = saved["prices"]
    else:
        todo = sorted(ids)
        prices = {}

    for card in scryfall.cards_collection([{"id": i} for i in todo]):
        p = card.get("prices") or {}
        prices[card["id"]] = {k: _to_float(p.get(k)) for k in PRICE_KEYS}

    cache_io.write_json(paths.COLLECTION_PRICES_PATH, {"fetched": today, "prices": prices})
    requests_sent = -(-len(todo) // scryfall.COLLECTION_BATCH)  # ceil
    found = sum(1 for i in todo if i in prices)
    return f"{found}/{len(todo)} printings from Scryfall ({requests_sent} requests)"


def apply(entries: list):
    """Overlays the saved Scryfall prices onto the entries' card prices
    (in place). The price date (prices.lastUpdatedAtUtc, which the value
    chart dates its points by) becomes the Scryfall fetch day."""
    saved = _load()
    if not saved["prices"]:
        return
    stamp = f"{saved['fetched']}T00:00:00Z"
    for entry in entries:
        sp = saved["prices"].get(entry["card"].get("scryfall_id"))
        if sp is None:
            continue
        prices = entry["card"].setdefault("prices", {})
        for k in PRICE_KEYS:
            prices[k] = sp[k]
        prices["lastUpdatedAtUtc"] = stamp
        prices["source"] = "scryfall"
