"""Per-printing price history: one row of prices per Scryfall price day
(see scryfall_prices.py — fetched at most once a day, on a collection
refresh). Feeds the price chart in the card popup and the Collection
screen's biggest riser / faller.

Stored compactly in data/price_history.json (user data — clearCache
never touches it):
    {"ids":  [scryfall_id, ...],                 # append-only index
     "days": {"YYYY-MM-DD": [[eur, eur_foil], ...]}}  # row i = ids[i]
A day's row only covers the ids known at the time (later ids are simply
missing from older rows). About 12 bytes per printing per day — roughly
14 MB a year for a 3,000-printing collection refreshed daily.
"""

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


def movers(tiles: list):
    """Biggest riser and faller between the last two recorded days among
    collection tiles (merged entries: one per printing + finish). Returns
    (riser, faller, previous_day) — each mover a (tile, old, new) tuple or
    None — or None if fewer than two days are recorded. Ranked by the
    change in € per copy."""
    recorded = days()
    if len(recorded) < 2:
        return None
    prev_day, last_day = recorded[-2], recorded[-1]
    riser = faller = None
    for tile in tiles:
        sid = tile["card"].get("scryfall_id")
        if not sid:
            continue
        foil = bool(tile.get("isFoil")) or str(tile.get("finish", "")).lower() in ("foil", "etched")
        old, new = price_on(prev_day, sid, foil), price_on(last_day, sid, foil)
        if old is None or new is None:
            continue
        diff = new - old
        if diff > 0 and (riser is None or diff > riser[2] - riser[1]):
            riser = (tile, old, new)
        if diff < 0 and (faller is None or diff < faller[2] - faller[1]):
            faller = (tile, old, new)
    return riser, faller, prev_day
