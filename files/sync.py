"""Refresh jobs the UI runs in the background: everything from Moxfield,
or just the collection / just the decks; the collection's prices alone
(Scryfall only — no Moxfield); and importing the collection from a
Moxfield CSV export (collection_import.py). Each step is recorded in the
sync log (sync_log.py). source: what triggered the sync, for the log
("Home", "Login", "Decks page", "Collection page", "Settings").
"""

import collection_import
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
    """Re-fetches the collection from Moxfield, then prices for any new
    printings in it (_update_prices). Only gets past the first step if
    the Moxfield fetch succeeded — logged() re-raises."""
    sync_log.logged("Collection", source, user.username, user.refresh_collection)
    if user.collection is None:
        return
    _update_prices(user, source)


def refresh_prices(user: User, source: str):
    """The collection's prices from Scryfall, without asking Moxfield for
    the collection again: the cards you have stay as last synced or
    imported. Run by the app once a day on its own ("Daily prices"), and
    by Settings → Sync → Refresh prices. Scryfall updates once a day, so a
    second run the same day only fetches printings that are new. Raises
    if it fails (the collection keeps its previous prices)."""
    if user.collection is None:
        user.load_collection()
    if not user.collection.cards:
        raise ValueError("There's no collection yet — refresh it from Moxfield or import a Moxfield export first.")
    summary = sync_log.logged("Prices", source, user.username,
                              lambda: scryfall_prices.refresh(user.collection.cards))
    _record_prices(user)
    return f"Prices: {summary}."


def import_collection(user: User, source: str, csv_path) -> str:
    """Replaces the collection with a Moxfield CSV export's cards (card
    data from Scryfall), then updates prices. Returns a message for the
    user, naming any rows Scryfall couldn't find."""
    result = {}

    def step():
        summary, result["missing"] = collection_import.import_file(csv_path, user.collection_id)
        return summary
    summary = sync_log.logged("Collection", source + " (CSV import)", user.username, step)
    user.load_collection()  # from the file just written
    _update_prices(user, source)
    message = f"Imported {summary}."
    missing = result.get("missing") or []
    if missing:
        names = ", ".join(f"{r['name']} ({r['set'].upper()} {r['cn']})".replace(" ()", "") for r in missing[:15])
        message += f"\n\nNot found: {names}" + (f" and {len(missing) - 15} more" if len(missing) > 15 else "") + "."
    return message


def _update_prices(user: User, source: str):
    """After the collection changed: prices for its new printings only
    (the daily full fetch runs on its own — see refresh_prices); on
    failure they keep what they have. Then records the value and per-card
    price history."""
    try:
        sync_log.logged("Prices", source, user.username,
                        lambda: scryfall_prices.refresh(user.collection.cards, only_new=True))
    except Exception:
        pass  # logged as FAILED
    _record_prices(user)


def _record_prices(user: User):
    cards = user.collection.cards
    scryfall_prices.apply(cards)
    value_history.record(user.username, cards)
    price_history.record_saved_prices()  # per-card history (card popup, movers)


def refresh_decks(user: User, source: str):
    sync_log.logged("Decks", source, user.username, user.refresh_decks)
