"""Collection value over time: one data point (date, total EUR value,
card count) per Moxfield price update, recorded each time the collection
is refreshed — see sync.refresh_collection. Shown as a line chart on the
Collection screen (ui.components.value_chart).

A point is dated by when Moxfield last updated the prices (the cards'
prices.lastUpdatedAtUtc), not by when you refreshed: refreshing before
Moxfield has new prices just overwrites that day's point instead of
adding a flat duplicate, so the line only moves on real price changes.

One file per user under data/ (user data, not cache: clearCache never
touches it — clearing the collection cache mustn't erase the history).
"""

from datetime import date

import cache_io
import card_sort
import paths


def collection_value(entries: list) -> float:
    """Total EUR value of collection entries — per copy, foil price for
    foil copies (same as the Sort menu); unknown prices count as 0."""
    return sum((card_sort.copy_price(e) or 0) * e["quantity"] for e in entries)


def price_date(entries: list) -> str | None:
    """The day Moxfield last updated these cards' prices ("YYYY-MM-DD",
    the newest prices.lastUpdatedAtUtc), or None if none is recorded."""
    days = [str((e["card"].get("prices") or {}).get("lastUpdatedAtUtc") or "")[:10]
            for e in entries]
    days = [d for d in days if d]
    return max(days) if days else None


def load(username: str) -> list:
    """[{"date": "YYYY-MM-DD", "value": float, "cards": int}, ...], oldest
    first (empty if nothing's recorded yet)."""
    return cache_io.read_json(paths.value_history_path(username)) or []


def record(username: str, entries: list):
    """Adds a data point from the collection entries, dated by their
    price update (today if Moxfield gives no date), replacing an earlier
    point from that same day. No-op for an empty collection (a failed /
    missing fetch shouldn't plot a drop to 0)."""
    if not username or not entries:
        return
    day = price_date(entries) or date.today().isoformat()
    point = {
        "date": day,
        "value": round(collection_value(entries), 2),
        "cards": sum(e["quantity"] for e in entries),
    }
    history = [p for p in load(username) if p["date"] != day]
    history.append(point)
    history.sort(key=lambda p: p["date"])
    cache_io.write_json(paths.value_history_path(username), history, indent=1)


def seed_if_empty(username: str, entries: list):
    """First run with an existing cached collection: records it as the
    first data point, so the chart has a starting point right away."""
    if username and not load(username):
        record(username, entries)
