"""Moxfield refresh jobs the UI runs in the background: everything, or
just the collection / just the decks. Each step is recorded in the sync
log (sync_log.py). source: what triggered the sync, for the log
("Home", "Login", "Decks page", "Collection page").
"""

import scryfall_prices
import sync_log
from models import price_history, value_history
from models.user import User


def refresh_all(user: User, source: str):
    """Profile, then collection, then decks (collection needs the
    collection ID the profile provides)."""
    sync_log.logged("Profile", source, user.username, user.refresh_profile)
    refresh_collection(user, source)
    refresh_decks(user, source)


def refresh_collection(user: User, source: str):
    """Re-fetches the collection from Moxfield, then its prices from
    Scryfall (at most once a day; on failure Moxfield's prices stay),
    then adds a point to the collection-value chart. Only gets past the
    first step if the Moxfield fetch succeeded — logged() re-raises."""
    sync_log.logged("Collection", source, user.username, user.refresh_collection)
    if user.collection is None:
        return
    cards = user.collection.cards
    try:  # fresher prices from Scryfall (once a day) — see scryfall_prices.py
        sync_log.logged("Prices", source, user.username, lambda: scryfall_prices.refresh(cards))
    except Exception:
        pass  # logged as FAILED; the collection keeps Moxfield's prices
    scryfall_prices.apply(cards)
    value_history.record(user.username, cards)
    price_history.record_saved_prices()  # per-card history (card popup, movers)


def refresh_decks(user: User, source: str):
    sync_log.logged("Decks", source, user.username, user.refresh_decks)
