"""Per-printing price history: one row of prices per Scryfall price day
(see scryfall_prices.py — fetched at most once a day, on a collection
refresh). Feeds the price chart in the card popup and the Collection
screen's biggest riser / faller.

Stored compactly in data/price_history.json (user data — clear_cache
never touches it):
    {"ids":  [scryfall_id, ...],                 # append-only index
     "days": {"YYYY-MM-DD": [[eur, eur_foil], ...]}}  # row i = ids[i]
A day's row only covers the ids known at the time (later ids are simply
missing from older rows). About 12 bytes per printing per day — roughly
14 MB a year for a 3,000-printing collection refreshed daily.
"""

from datetime import date, timedelta

import cache_io
import paths
import scryfall_prices

_cache = {"mtime": None, "data": None}  # parsed file, reused until it changes


def _load() -> dict:
    path = paths.PRICE_HISTORY_PATH
    mtime = path.stat().st_mtime if path.exists() else None
    if _cache["data"] is None or _cache["mtime"] != mtime:
        _cache["data"] = cache_io.read_json(path) or {"ids": [], "days": {}}
        _cache["mtime"] = mtime
        _cache["index"] = {sid: i for i, sid in enumerate(_cache["data"]["ids"])}
    return _cache["data"]


def record_saved_prices():
    """Adds (or replaces) the row for the day of the last Scryfall price
    fetch, from scryfall_prices' cache. Cheap no-op when there's nothing
    saved or that day is already recorded with every printing."""
    saved = scryfall_prices.saved()
    day, prices = saved.get("fetched"), saved.get("prices") or {}
    if not day or not prices:
        return
    data = _load()
    index = _cache["index"]
    if day in data["days"] and all(sid in index for sid in prices) \
            and len(data["days"][day]) == len(data["ids"]):
        return
    for sid in prices:
        if sid not in index:
            index[sid] = len(data["ids"])
            data["ids"].append(sid)
    row = []
    for sid in data["ids"]:
        p = prices.get(sid)
        row.append([p.get("eur"), p.get("eur_foil")] if p else [None, None])
    data["days"][day] = row
    data["days"] = dict(sorted(data["days"].items()))
    cache_io.write_json(paths.PRICE_HISTORY_PATH, data)  # compact, no indent
    _cache["data"] = None  # re-read (and re-index) on next use


def days() -> list:
    """Recorded days, oldest first."""
    return list(_load()["days"])


def price_on(day: str, scryfall_id: str, foil: bool):
    """A printing's price on a recorded day — the foil price for foil
    copies when there is one (like card_sort.copy_price). None if unknown."""
    data = _load()
    i = _cache["index"].get(scryfall_id)
    row = data["days"].get(day)
    if i is None or row is None or i >= len(row):
        return None
    eur, eur_foil = row[i]
    return eur_foil if foil and eur_foil is not None else eur


def series(scryfall_id: str, foil: bool) -> list:
    """[{"date", "value"}] for the price chart, oldest first (days with
    no price for this printing are skipped)."""
    points = []
    for day in days():
        value = price_on(day, scryfall_id, foil)
        if value is not None:
            points.append({"date": day, "value": value})
    return points


PERCENT_MIN_EUR = 1.0  # the % ranking only counts cards worth this much (before or after)

# Movers' periods: key -> (label, days back; None = the previous update,
# "all" = the first recorded day)
PERIODS = {
    "last": ("Last update", None),
    "week": ("Last week", 7),
    "month": ("Last month", 30),
    "year": ("Last year", 365),
    "all": ("All time", "all"),
}


def comparison_day(period: str, recorded: list) -> str | None:
    """The recorded day a period compares the latest one with: the
    previous update, the last day at least N days back (the oldest day if
    history doesn't reach that far yet), or the first day. None if there's
    only one day."""
    if len(recorded) < 2:
        return None
    back = PERIODS.get(period, PERIODS["last"])[1]
    if back is None:
        return recorded[-2]
    if back == "all":
        return recorded[0]
    target = (date.fromisoformat(recorded[-1]) - timedelta(days=back)).isoformat()
    earlier = [d for d in recorded[:-1] if d <= target]
    return earlier[-1] if earlier else recorded[0]


def movers(tiles: list, period: str = "last"):
    """Biggest risers and fallers among collection tiles (merged entries:
    one per printing + finish) between the latest recorded day and the
    period's comparison_day, ranked two ways. Returns None if fewer than
    two days are recorded, else

        {"previous_day": "YYYY-MM-DD",    # the day compared with
         "by_value":   (riser, faller),   # biggest change in € per copy
         "by_percent": (riser, faller)}   # biggest change in %, cards
                                          # worth PERCENT_MIN_EUR+ only —
                                          # else bulk dominates (€0.02 ->
                                          # €0.05 is +150 %)

    each mover a (tile, old, new) tuple, or None if nothing went that way.
    A card without a price on the comparison day (added later) is measured
    from its first recorded price. The same card can top both rankings."""
    recorded = days()
    prev_day = comparison_day(period, recorded)
    if prev_day is None:
        return None
    last_day = recorded[-1]
    later_days = recorded[recorded.index(prev_day) + 1:-1]  # for cards added after prev_day
    best = {"value_up": None, "value_down": None, "pct_up": None, "pct_down": None}
    score = {k: 0.0 for k in best}

    def consider(key, value, mover):
        if best[key] is None or value > score[key]:
            best[key], score[key] = mover, value

    for tile in tiles:
        sid = tile["card"].get("scryfall_id")
        if not sid:
            continue
        foil = bool(tile.get("isFoil")) or str(tile.get("finish", "")).lower() in ("foil", "etched")
        old, new = price_on(prev_day, sid, foil), price_on(last_day, sid, foil)
        if old is None and new is not None:  # added since: from its first price
            old = next((p for p in (price_on(d, sid, foil) for d in later_days) if p is not None), None)
        if old is None or new is None or new == old:
            continue
        mover, diff = (tile, old, new), new - old
        consider("value_up" if diff > 0 else "value_down", abs(diff), mover)
        if old > 0 and max(old, new) >= PERCENT_MIN_EUR:
            consider("pct_up" if diff > 0 else "pct_down", abs(diff) / old, mover)
    return {"previous_day": prev_day,
            "by_value": (best["value_up"], best["value_down"]),
            "by_percent": (best["pct_up"], best["pct_down"])}
