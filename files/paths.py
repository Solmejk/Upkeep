"""Centralized cache/data paths, anchored to this file's location rather
than the process's current working directory.

Every module used to build its own "files/cache/..." string relative to
cwd, which silently breaks (empty cache, no error) if the app is ever
launched from a different directory. Anchoring to __file__ makes launch
directory irrelevant.
"""

from pathlib import Path

FILES_ROOT = Path(__file__).parent
ASSETS_DIR = FILES_ROOT / "assets"
CACHE_DIR = FILES_ROOT / "cache"
IMAGES_DIR = CACHE_DIR / "images"
DECKS_DIR = CACHE_DIR / "decks"
DECK_STATES_PATH = CACHE_DIR / "deck_states.json"
SESSION_PATH = CACHE_DIR / "session.json"
SAVED_AVAILABILITY_DECKS_PATH = CACHE_DIR / "saved_availability_decks.json"
SYNC_LOG_PATH = CACHE_DIR / "sync_log.txt"
COLLECTION_PRICES_PATH = CACHE_DIR / "collection_prices.json"  # Scryfall prices, see scryfall_prices.py

# User-created data — NOT cache: clear_cache never touches this folder.
DATA_DIR = FILES_ROOT / "data"
LOCAL_DECKS_DIR = DATA_DIR / "decks"  # decks built in the Deck Maker
DECK_LANGUAGES_PATH = DATA_DIR / "deck_languages.json"  # confirmed card languages per Moxfield deck
SHOWCASES_PATH = DATA_DIR / "showcases.json"  # Home screen showcases
GAME_TRACKER_PATH = DATA_DIR / "game_tracker.json"  # players + games, see models.game_tracker
TOKEN_PRINTINGS_PATH = DATA_DIR / "token_printings.json"  # chosen default printing per token
PRICE_HISTORY_PATH = DATA_DIR / "price_history.json"  # per-printing prices per day, see models.price_history
ARTIST_PROOFS_DIR = DATA_DIR / "artist_proofs"  # the user's proof images (copied in)
ARTIST_PROOFS_PATH = DATA_DIR / "artist_proofs.json"  # proof index: "set|cn" -> files
PURCHASES_DIR = DATA_DIR / "purchases"  # imported Cardmarket purchases, one JSON each


def user_cache_path(username: str) -> Path:
    """Path to a user's cached profile JSON."""
    return CACHE_DIR / f"user_{username}.json"


def collection_cache_path(collection_id: str) -> Path:
    """Path to a cached collection's JSON."""
    return CACHE_DIR / f"collection_{collection_id}.json"


def decks_list_cache_path(username: str) -> Path:
    """Path to a user's cached deck list JSON (id/name pairs only —
    individual deck contents live under DECKS_DIR, see deck_cache_path)."""
    return CACHE_DIR / f"decks_{username}.json"


def local_deck_path(deck_id: str) -> Path:
    """Path to a Deck Maker deck's JSON (same format as deck_cache_path's
    files, plus "source": "local")."""
    return LOCAL_DECKS_DIR / f"{deck_id}.json"


def deck_cache_path(deck_id: str) -> Path:
    """Path to one deck's cached contents JSON."""
    return DECKS_DIR / f"{deck_id}.json"


def purchase_path(purchase_id: str) -> Path:
    """Path to one imported purchase's JSON (see models.purchases)."""
    return PURCHASES_DIR / f"{purchase_id}.json"


def value_history_path(username: str) -> Path:
    """Path to a user's collection-value history (see models.value_history)."""
    return DATA_DIR / f"value_history_{username}.json"
