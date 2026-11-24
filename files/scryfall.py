"""Scryfall image URL / cache-key / pricing helpers, shared across the
collection grid, deck detail, card modal, and availability check."""

import sys
import threading
import time

import requests

from rate_limit import RateLimiter

BASE_IMAGE_URL = "https://cards.scryfall.io/normal/front"
SEARCH_URL = "https://api.scryfall.com/cards/search"

# Scryfall rejects requests using the HTTP library's default User-Agent.
HEADERS = {
    "User-Agent": "Upkeep/1.0",
    "Accept": "*/*",
}


# 2 per second: Scryfall refused (429) a ~45-request price fetch at 3 per
# second, so stay well under — its card search / collection endpoints are
# stricter than the API in general. Every request also backs off after a
# 429 (_send).
_rate_limiter = RateLimiter(max_per_second=2)
BATCH_SIZE = 15  # names per Scryfall query, combined with "or" — see cheapest_prices_eur


def image_url(scryfall_id: str) -> str:
    """Builds the cards.scryfall.io image URL for a card's Scryfall ID.
    Returns "" if scryfall_id is falsy (some cached card data lacks one)."""
    if not scryfall_id:
        return ""
    return f"{BASE_IMAGE_URL}/{scryfall_id[0]}/{scryfall_id[1]}/{scryfall_id}.jpg"


def card_key(card: dict) -> str:
    """Unique per printing: set + collector number."""
    return f"{card.get('set', '')}_{card.get('cn', '')}"


def card_image_cache_name(card: dict) -> str:
    """The on-disk cache filename (without extension) for a card's image,
    via image_cache.get_image_path()."""
    return f"card_{card_key(card)}"


# The standard Magic card back (Scryfall's default card_back_id)
MAGIC_BACK_URL = "https://backs.scryfall.io/normal/0/a/0aeebaf5-8c7d-4636-9e82-8c27447861f7.jpg"
MAGIC_BACK_CACHE_NAME = "magic_card_back"


def back_image_url(scryfall_id: str) -> str:
    """A double-faced card's back face image ("" without an ID)."""
    if not scryfall_id:
        return ""
    return f"https://cards.scryfall.io/normal/back/{scryfall_id[0]}/{scryfall_id[1]}/{scryfall_id}.jpg"


def back_cache_name(card: dict) -> str:
    """Cache name for a printing's back image (a double-faced card's back
    face, or an artist proof's back — see models.artist_proofs)."""
    return f"back_{card_key(card)}"


def search(query: str, unique: str = "cards", order: str | None = None, direction: str | None = None,
           include_extras: bool = False, max_pages: int | None = None, quiet: bool = False,
           timeout: int = 20) -> list[dict]:
    """One Scryfall card search — the shared way every module searches.
    query: Scryfall search syntax. unique: "cards" (one per card) or
    "prints" (every printing). order / direction: e.g. "eur" / "asc",
    "released" / "desc". include_extras: tokens, art cards etc. too.
    max_pages: stop after this many pages (175 cards each; None = all).

    Every request goes through the shared rate limiter; a 429 ("too many
    requests") backs off and retries (_send). No matches -> []. Other
    failures raise — unless quiet, which returns what was found so far
    (used where a missing result is acceptable, e.g. price lookups)."""
    params = {"q": query, "unique": unique}
    if order:
        params["order"] = order
    if direction:
        params["dir"] = direction
    if include_extras:
        params["include_extras"] = "true"
    url, results, pages = SEARCH_URL, [], 0
    try:
        while url and (max_pages is None or pages < max_pages):
            response = _get(url, params, timeout)
            if response.status_code == 404:  # no matches
                break
            response.raise_for_status()
            page = response.json()
            results += page.get("data", [])
            pages += 1
            url, params = page.get("next_page"), None  # next_page already holds the query
    except Exception:
        if not quiet:
            raise
    return results


API_ROOT = "https://api.scryfall.com/"


def _get(url: str, params: dict | None, timeout: int):
    """A rate-limited GET to the Scryfall API (see _send)."""
    return _send("GET", url, params=params, timeout=timeout)


def api_get(url: str, timeout: int = 10):
    """A GET to any Scryfall API URL (e.g. /cards/named?format=image from
    image_cache), paced and backed off like every other API request."""
    return _send("GET", url, timeout=timeout)


BACKOFF = (5, 15, 30)  # seconds to wait after each 429 in a row, unless Scryfall says how long
_pause_lock = threading.Lock()
_paused_until = 0.0  # after a 429, every request (any thread) waits until then


def _send(method: str, url: str, **kwargs):
    """Every Scryfall API request goes through here: the shared rate
    limiter, and after a 429 ("too many requests") a pause before trying
    again — as long as Scryfall's Retry-After says, else BACKOFF — that
    holds back every other Scryfall request in the app too, instead of
    them piling on. Returns the response (still a 429 if Scryfall kept
    refusing; the caller's raise_for_status reports it)."""
    global _paused_until
    for attempt in range(len(BACKOFF) + 1):
        with _pause_lock:
            pause = _paused_until - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        _rate_limiter.wait()
        response = requests.request(method, url, headers=HEADERS, **kwargs)
        if response.status_code != 429 or attempt == len(BACKOFF):
            return response
        try:
            wait = max(1.0, float(response.headers.get("Retry-After", "")))
        except ValueError:
            wait = BACKOFF[attempt]
        with _pause_lock:
            _paused_until = max(_paused_until, time.monotonic() + wait)
        print(f"Scryfall: too many requests (429) — waiting {wait:.0f}s before retrying", file=sys.stderr)
    return response


def cheapest_prices_eur(card_names: list[str]) -> dict[str, dict | None]:
    """Cheapest EUR price (and which set it's from) for each name, one
    Scryfall request per BATCH_SIZE names (an "or"-combined query) instead
    of one request per card — this is what keeps a deck with 70+ missing
    cards from firing 70+ requests and tripping Scryfall's rate limit.

    Returns {name: {"price": float, "set": str}} or {name: None} if no
    priced printing was found.

    The query filters to eur>0 server-side rather than sorting all prints
    ascending and filtering nulls client-side: with dir=asc, unpriced
    printings (digital-only, promos with no paper release, etc.) sort
    first, so a card with many of those would otherwise never reach a
    priced entry and wrongly look like it has no price at all."""
    unique_names = list(dict.fromkeys(card_names))  # de-dup, keep order
    results: dict[str, dict | None] = {name: None for name in unique_names}

    for i in range(0, len(unique_names), BATCH_SIZE):
        batch = unique_names[i:i + BATCH_SIZE]
        name_clauses = " or ".join(f'!"{name}"' for name in batch)
        prints = search(f"({name_clauses}) eur>0", unique="prints", order="eur", direction="asc",
                        max_pages=1, quiet=True)
        for p in prints:
            name = p.get("name", "")
            price = p.get("prices", {}).get("eur")
            # Results are sorted ascending, so the first hit per name is its
            # cheapest — later duplicates of the same name are only pricier.
            if name in results and results[name] is None and price is not None:
                results[name] = {"price": float(price), "set": p.get("set", "")}

    return results


COLLECTION_URL = "https://api.scryfall.com/cards/collection"
COLLECTION_BATCH = 75  # Scryfall's max identifiers per /cards/collection request


def cards_collection(identifiers: list[dict], on_batch=None) -> list[dict]:
    """Looks up many specific cards at once via Scryfall's
    /cards/collection endpoint (75 identifiers per request, rate-limited
    like every other call here). identifiers: Scryfall identifier dicts,
    e.g. {"set": "khm", "collector_number": "12"}, {"name": "Opt",
    "set": "xln"} or {"name": "Opt"}. Returns the found card objects (in
    no guaranteed relation to the input — match them up by set/number or
    name). on_batch(cards): called with each batch's cards as they
    arrive, so a caller can keep what it got if a later batch fails.
    Raises on network errors, so a failed lookup isn't mistaken for
    "card doesn't exist"."""
    found = []
    for i in range(0, len(identifiers), COLLECTION_BATCH):
        batch = identifiers[i:i + COLLECTION_BATCH]
        response = _send("POST", COLLECTION_URL, json={"identifiers": batch}, timeout=30)
        response.raise_for_status()
        cards = response.json().get("data", [])
        found.extend(cards)
        if on_batch is not None:
            on_batch(cards)
    return found


CARD_URL = "https://api.scryfall.com/cards/"


def all_paper_printings(scryfall_id: str) -> list[dict]:
    """Every paper printing of the same card (same oracle) as the given
    printing, newest first — tokens included (include_extras). One request
    to find its oracle ID, then one per 175 printings. Raises on network
    errors."""
    response = _get(CARD_URL + scryfall_id, None, 15)
    response.raise_for_status()
    oracle_id = response.json().get("oracle_id")
    if not oracle_id:
        return []
    return search(f"oracleid:{oracle_id} -is:digital", unique="prints", include_extras=True,
                  order="released", direction="desc")
