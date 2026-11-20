"""Everything to do with talking to Moxfield: parsing deck URLs a user
pastes in, the API endpoint URLs, and every request to its API —
profiles, decks, collections and deck searches (the deck list for your
account and for Game Tracker players). Models call these; nothing else
talks to Moxfield directly."""

import re

import requests

API_BASE = "https://api2.moxfield.com"

_DECK_URL_RE = re.compile(r"moxfield\.com/decks/([A-Za-z0-9_-]+)")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def extract_deck_id(url: str) -> str | None:
    """Pull the public deck ID out of a Moxfield deck URL. Also accepts a
    bare ID, in case that's what was pasted instead of a full URL."""
    url = url.strip()
    if not url:
        return None
    match = _DECK_URL_RE.search(url)
    if match:
        return match.group(1)
    if _BARE_ID_RE.match(url):
        return url
    return None


def user_api_url(username: str) -> str:
    """Endpoint for fetching a user's profile (avatar, collection ID)."""
    return f"{API_BASE}/v1/users/{username}"


def decks_search_api_url() -> str:
    """Endpoint for searching/listing a user's decks. Query params
    (author, sort, etc.) are added by the caller — see User.load_decks."""
    return f"{API_BASE}/v2/decks/search"


def collection_search_api_url(collection_id: str) -> str:
    """Endpoint for fetching a collection's full card list."""
    return f"{API_BASE}/v1/collections/search/{collection_id}"


def deck_api_url(deck_id: str) -> str:
    """Endpoint for fetching one deck's full contents."""
    return f"{API_BASE}/v3/decks/all/{deck_id}"


def search_decks(username: str, timeout: int = 15) -> dict:
    """A Moxfield user's public decks, newest first — every page (Moxfield
    serves at most 100 per request). Returns the first page's response
    with "data" holding all pages' decks (each with name, publicId,
    format, colorIdentity, ...). Raises on network errors / unknown users."""
    params = {
        "includePinned": "false",
        "showIllegal": "true",
        "authorUserNames": username,
        "sortType": "updated",
        "sortDirection": "descending",
        "board": "mainboard",
        "pageNumber": 1,
        "pageSize": 100,  # Moxfield's max; defaults to 25
    }
    response = requests.get(decks_search_api_url(), params=params, timeout=timeout)
    response.raise_for_status()
    result = response.json()
    for page in range(2, result.get("totalPages", 1) + 1):
        params["pageNumber"] = page
        response = requests.get(decks_search_api_url(), params=params, timeout=timeout)
        response.raise_for_status()
        result["data"].extend(response.json()["data"])
    return result


def fetch_profile(username: str, timeout: int = 10) -> dict:
    """A user's profile (avatar, collection id, ...). Raises on errors."""
    return _get_json(user_api_url(username), timeout=timeout)


def fetch_deck(deck_id: str, timeout: int = 10) -> dict:
    """One deck's full contents (boards, tokens, ...). Raises on errors."""
    return _get_json(deck_api_url(deck_id), timeout=timeout)


def fetch_collection_page(collection_id: str, page: int, timeout: int = 10) -> dict:
    """One page (100 entries, by card name) of a collection. Raises on errors."""
    params = {"pageNumber": page, "pageSize": 100, "sortType": "cardName", "sortDirection": "ascending"}
    return _get_json(collection_search_api_url(collection_id), params, timeout)


def _get_json(url: str, params: dict | None = None, timeout: int = 10) -> dict:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()
