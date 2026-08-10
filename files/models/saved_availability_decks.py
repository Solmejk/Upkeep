"""Persists the list of deck URLs a user has saved from the Availability
Checker, so they can re-check a deck later without hunting down the URL
again. Stored as an ordered list of {deck_id, name, url} in a single
saved_availability_decks.json file, keyed/deduped by deck_id.
"""

import cache_io
from paths import SAVED_AVAILABILITY_DECKS_PATH


def get_saved() -> list[dict]:
    """Returns the saved decks in save order: [{deck_id, name, url}, ...].
    Empty list if none have been saved yet."""
    return cache_io.read_json(SAVED_AVAILABILITY_DECKS_PATH) or []


def save_deck(deck_id: str, name: str, url: str, summary: dict):
    """Adds `deck_id` to the saved list, or updates its name/url/summary
    in place if it was already saved (moving it is not necessary — order
    is by first save). summary: {"free": int, "used": int, "unowned":
    int, "missing_cost": float} from the last check, so the saved-decks
    row can show counts without re-fetching."""
    saved = get_saved()
    for entry in saved:
        if entry["deck_id"] == deck_id:
            entry["name"] = name
            entry["url"] = url
            entry["summary"] = summary
            break
    else:
        saved.append({"deck_id": deck_id, "name": name, "url": url, "summary": summary})
    cache_io.write_json(SAVED_AVAILABILITY_DECKS_PATH, saved, indent=2)


def remove_deck(deck_id: str):
    """Removes `deck_id` from the saved list, if present."""
    saved = [entry for entry in get_saved() if entry["deck_id"] != deck_id]
    cache_io.write_json(SAVED_AVAILABILITY_DECKS_PATH, saved, indent=2)


def is_saved(deck_id: str) -> bool:
    """Whether `deck_id` is currently in the saved list."""
    return any(entry["deck_id"] == deck_id for entry in get_saved())
