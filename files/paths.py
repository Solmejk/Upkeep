"""Centralized file locations, anchored to known places rather than the
process's current working directory (a cwd-relative "files/cache/..."
silently breaks — empty cache, no error — if the app is launched from
elsewhere).

Two kinds of files:

    Bundled, read-only (RESOURCE_ROOT): the icons and the stylesheet. From
        source that's files/; in the packaged .exe (PyInstaller) it's the
        folder the .exe unpacks itself into (sys._MEIPASS).
    Yours, writable (USER_ROOT): the cache, your data and the session logs.
        From source that's files/ as before; in the packaged .exe it's
        %APPDATA%/Upkeep — the .exe's own folder is
        temporary, so nothing there would survive a restart.
"""

import os
import sys
from pathlib import Path

APP_NAME = "Upkeep"
OLD_APP_NAME = "MTG Collection Manager"  # the app's name before it was Upkeep
FROZEN = getattr(sys, "frozen", False)  # running as the packaged .exe

RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
if FROZEN:
    _appdata = Path(os.environ.get("APPDATA") or Path.home())
    USER_ROOT = _appdata / APP_NAME
    if not USER_ROOT.exists() and (_appdata / OLD_APP_NAME).is_dir():
        try:  # one-time move of the data kept under the old name
            (_appdata / OLD_APP_NAME).rename(USER_ROOT)
        except OSError:
            pass  # in use or locked: start fresh rather than fail to start
else:
    USER_ROOT = Path(__file__).parent

ASSETS_DIR = RESOURCE_ROOT / "assets"
STYLE_PATH = RESOURCE_ROOT / "ui" / "style.qss"
APP_ICON_PATH = ASSETS_DIR / "app_icon.png"

LOGS_DIR = USER_ROOT / "logs"  # this session's and the last one's — see session_log.py
CACHE_DIR = USER_ROOT / "cache"
IMAGES_DIR = CACHE_DIR / "images"
DECKS_DIR = CACHE_DIR / "decks"
DECK_STATES_PATH = CACHE_DIR / "deck_states.json"
SESSION_PATH = CACHE_DIR / "session.json"
SAVED_AVAILABILITY_DECKS_PATH = CACHE_DIR / "saved_availability_decks.json"
SYNC_LOG_PATH = CACHE_DIR / "sync_log.txt"
COLLECTION_PRICES_PATH = CACHE_DIR / "collection_prices.json"  # Scryfall prices, see scryfall_prices.py

# User-created data — NOT cache: clear_cache never touches this folder.
DATA_DIR = USER_ROOT / "data"
DECK_LANGUAGES_PATH = DATA_DIR / "deck_languages.json"  # confirmed card languages per Moxfield deck
# Moxfield's private user-agent for Upkeep (secret: encrypted, see secret_store.py and moxfield.py)
MOXFIELD_ACCESS_PATH = DATA_DIR / "moxfield_access.bin"
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


def deck_cache_path(deck_id: str) -> Path:
    """Path to one deck's cached contents JSON."""
    return DECKS_DIR / f"{deck_id}.json"


def purchase_path(purchase_id: str) -> Path:
    """Path to one imported purchase's JSON (see models.purchases)."""
    return PURCHASES_DIR / f"{purchase_id}.json"


def value_history_path(username: str) -> Path:
    """Path to a user's collection-value history (see models.value_history)."""
    return DATA_DIR / f"value_history_{username}.json"
