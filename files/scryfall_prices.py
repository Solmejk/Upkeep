"""Collection prices from Scryfall instead of Moxfield (Moxfield's lag a
day or more behind — Scryfall updates once a day).

Prices are separate from the collection: the collection only changes when
you refresh it from Moxfield or import an export, but prices are fetched
on their own once a day — the app does it at startup (and at midnight if
it's left open) whenever needs_daily_refresh(), or with Settings → Sync →
Refresh prices. refresh() looks up every printing's prices with Scryfall's
batch endpoint (75 cards per request, through scryfall.py's shared rate
limiter — ~45 requests for a 3,000+ printing collection) and saves them to
cache/collection_prices.json. A collection refresh / import then only asks
for printings that are new (only_new), and a second run the same day too.

apply() overlays the saved prices onto collection entries (models/
collection.py calls it on every load), so the stats, sorting, card popup
and value chart all use them. Printings Scryfall didn't return keep
Moxfield's price. The cache file is named collection_*.json so clearing
the collection cache clears it too.
"""

from datetime import date

import cache_io
import paths
import progress
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


def needs_daily_refresh() -> bool:
    """True if the last full price fetch wasn't today (or never ran) —
    the app then fetches prices on its own (MainWindow, at startup and
    when the date changes while it's open)."""
    return _load()["fetched"] != date.today().isoformat()


def refresh(entries: list, only_new: bool = False) -> str:
    """Fetches Scryfall prices for the collection's printings — all of
    them once a day, else only ones not fetched yet. only_new: just the
    printings without a saved price (after a collection refresh / import
    brought in new cards), leaving the daily full fetch to its schedule.
    Returns a short summary for the sync log. Raises on network errors
    (the collection keeps the prices it has then)."""
    today = date.today().isoformat()
    saved = _load()
    ids = {e["card"].get("scryfall_id") for e in entries} - {None, ""}
    prices = dict(saved["prices"])  # yesterday's stay until today's arrive
    # printings already fetched today by a daily fetch that was cut short
    done_today = set(saved.get("partial", {}).get("ids", [])) if saved.get("partial", {}).get("day") == today else set()
    daily = not only_new and saved["fetched"] != today
    if daily:
        todo = sorted(ids - done_today)
    else:
        todo = sorted(ids - prices.keys())
        if not todo:
            return "no new printings" if only_new and saved["fetched"] != today else "already fetched today"

    got = set()

    def keep(cards):  # each batch as it arrives — a later failure doesn't lose it
        for card in cards:
            p = card.get("prices") or {}
            prices[card["id"]] = {k: _to_float(p.get(k)) for k in PRICE_KEYS}
            got.add(card["id"])
        done_today.update(got)

    batches = -(-len(todo) // scryfall.COLLECTION_BATCH)
    try:
        with progress.stage("Prices", total=batches, step_seconds=0.5) as step:  # Scryfall: 2 requests/s
            def keep_and_count(cards):
                keep(cards)
                step.advance()
            scryfall.cards_collection([{"id": i} for i in todo], on_batch=keep_and_count)
    except Exception:
        if daily:  # still due: the next try today fetches only what's missing
            cache_io.write_json(paths.COLLECTION_PRICES_PATH, {
                "fetched": saved["fetched"], "prices": prices,
                "partial": {"day": today, "ids": sorted(done_today)}})
        elif prices != saved["prices"]:
            cache_io.write_json(paths.COLLECTION_PRICES_PATH, {**saved, "prices": prices})
        raise

    if daily:  # complete: drop printings no longer in the collection
        prices = {i: p for i, p in prices.items() if i in ids}
    fetched = today if (daily or saved["fetched"] == today or not saved["fetched"]) else saved["fetched"]
    cache_io.write_json(paths.COLLECTION_PRICES_PATH, {"fetched": fetched, "prices": prices})
    requests_sent = -(-len(todo) // scryfall.COLLECTION_BATCH)  # ceil
    resumed = ", continuing today's earlier try" if daily and done_today - got else ""
    return f"{len(got)}/{len(todo)} printings from Scryfall ({requests_sent} requests{resumed})"


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
