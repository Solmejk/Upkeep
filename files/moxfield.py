"""Everything to do with talking to Moxfield: parsing deck URLs a user
pastes in, the API endpoint URLs, and every request to its API —
profiles, decks, collections and deck searches (the deck list for your
account and for Game Tracker players). Models call these; nothing else
talks to Moxfield directly.

Moxfield's terms for Upkeep's access (from Moxfield, by email):
    - a private user-agent they issue, which must be kept secret: it is
      entered in Settings and stored encrypted for the Windows user
      (secret_store.py) — never in the code, the repo, the build or logs;
    - at most 1 API call per second, or the IP gets banned and the
      user-agent revoked: every request waits its turn on one shared
      limiter (REQUEST_INTERVAL, a little over 1 s for margin), and
      requests are made one at a time;
    - no deck building in the app (removed — see Upkeep Builder);
    - the app stays 100% free.
Without a user-agent no request is made at all. A 429 (too many
requests) or a 403 (refused) stops *all* Moxfield requests for a while
(BLOCK_SECONDS) instead of retrying.
"""

import re
import sys
import threading
import time

import requests

import paths
import secret_store
from rate_limit import RateLimiter

API_BASE = "https://api2.moxfield.com"

REQUEST_INTERVAL = 1.2  # seconds between requests: Moxfield allows 1 per second — keep a margin
BLOCK_SECONDS = 10 * 60  # after a 429 / 403: no Moxfield requests for this long (unless it says longer)
_MAX_USER_AGENT_LENGTH = 512

_rate_limiter = RateLimiter(interval=REQUEST_INTERVAL)
_block_lock = threading.Lock()
_blocked_until = 0.0  # time.monotonic() — see _block
_block_reason = ""
_user_agent_cache: list = []  # [] = not read yet, [str | None] = read (see user_agent)


class MoxfieldError(Exception):
    """A Moxfield request that wasn't made or was refused, with a message
    meant for the user."""


# --------------------------------------------------------- user-agent
def user_agent() -> str | None:
    """The user-agent Moxfield issued, or None if none is set up here."""
    if not _user_agent_cache:
        _user_agent_cache.append(secret_store.load(paths.MOXFIELD_ACCESS_PATH))
    return _user_agent_cache[0]


def has_user_agent() -> bool:
    return bool(user_agent())


def set_user_agent(value: str):
    """Saves (encrypted) the user-agent pasted in Settings. Raises
    ValueError if it isn't a single line of plain text. Clears a block
    from before (a new user-agent deserves a fresh try)."""
    value = value.strip()
    if not value:
        raise ValueError("The user-agent is empty.")
    if len(value) > _MAX_USER_AGENT_LENGTH or not value.isprintable():
        raise ValueError("That doesn't look like a user-agent: it should be one line of plain text.")
    secret_store.save(paths.MOXFIELD_ACCESS_PATH, value)
    _user_agent_cache[:] = [value]
    _unblock()


def clear_user_agent():
    secret_store.delete(paths.MOXFIELD_ACCESS_PATH)
    _user_agent_cache[:] = [None]


# ------------------------------------------------------------- blocks
def blocked_for() -> float:
    """Seconds until Moxfield requests are allowed again (0 if they are)."""
    with _block_lock:
        return max(0.0, _blocked_until - time.monotonic())


def _block(seconds: float, reason: str):
    global _blocked_until, _block_reason
    with _block_lock:
        _blocked_until = max(_blocked_until, time.monotonic() + seconds)
        _block_reason = reason
    print(f"Moxfield: {reason} — no Moxfield requests for {seconds / 60:.0f} min", file=sys.stderr)


def _unblock():
    global _blocked_until, _block_reason
    with _block_lock:
        _blocked_until, _block_reason = 0.0, ""


def _retry_after(response) -> float:
    try:
        return max(BLOCK_SECONDS, float(response.headers.get("Retry-After", "")))
    except ValueError:
        return BLOCK_SECONDS


# ----------------------------------------------------------- requests
def _get(url: str, params: dict | None = None, timeout: int = 10):
    """Every Moxfield request goes through here (see the module docstring).
    Returns the response; raises MoxfieldError when the request isn't
    allowed or Moxfield refuses it, requests' errors otherwise."""
    agent = user_agent()
    if not agent:
        raise MoxfieldError(
            "Moxfield access isn't set up: add the user-agent Moxfield gave you under Settings → "
            "Moxfield access. Until then, import your collection from a Moxfield export "
            "(Settings → Import from Moxfield export).")
    remaining = blocked_for()
    if remaining:
        raise MoxfieldError(
            f"Moxfield requests are paused for another {remaining / 60:.0f} min ({_block_reason}), "
            "so as not to break Moxfield's rate limit.")
    _rate_limiter.wait()
    response = requests.get(url, params=params, timeout=timeout,
                            headers={"User-Agent": agent, "Accept": "application/json"})
    if response.status_code == 429:
        _block(_retry_after(response), "Moxfield said too many requests (429)")
        raise MoxfieldError(
            "Moxfield said Upkeep made too many requests (429). Moxfield requests are paused for "
            f"{blocked_for() / 60:.0f} min. If this keeps happening, tell the developer — "
            "breaking the rate limit can get the user-agent revoked.")
    if response.status_code == 403:
        _block(BLOCK_SECONDS, "Moxfield refused the request (403)")
        raise MoxfieldError(
            "Moxfield refused the request (403 Forbidden). The user-agent under Settings → Moxfield "
            "access may be mistyped or no longer valid. Moxfield requests are paused for "
            f"{BLOCK_SECONDS // 60} min; meanwhile you can import your collection from a Moxfield export.")
    response.raise_for_status()
    return response

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
    result = _get(decks_search_api_url(), params, timeout).json()
    for page in range(2, result.get("totalPages", 1) + 1):
        params["pageNumber"] = page
        result["data"].extend(_get(decks_search_api_url(), params, timeout).json()["data"])
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
    return _get(url, params, timeout).json()
