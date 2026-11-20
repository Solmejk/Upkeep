"""User: one Moxfield account's profile, collection, and deck list.
Composes Collection and Deck — loading a User cascades into loading
(cache-only, or force-fetching) all three.
"""

import requests
import cache_io
import moxfield
import paths
from models.collection import Collection
from models import local_decks
from models.deck import Deck, SOURCE_MOXFIELD

class User:
    def __init__(self, username):
        """username: the Moxfield username this User represents. Starts
        empty — call load() to populate profile/collection/decks."""
        self._username = username
        self._profile_image_url = ""
        self._collection_id = "-1"
        self._collection = None
        self._decks = []

    @property
    def username(self):
        return self._username

    @property
    def collection_id(self):
        """The Moxfield public ID of this user's collection, or "-1" if
        unknown (profile not yet loaded, or the account has none)."""
        return self._collection_id

    @property
    def collection(self):
        """This user's Collection, or None if load_collection() hasn't
        run yet."""
        return self._collection

    @property
    def decks(self):
        """This user's decks (as Deck stubs — see load_decks for what's
        populated immediately vs. loaded lazily per-deck)."""
        return self._decks

    @property
    def profile_image_url(self):
        return self._profile_image_url

    def load(self, force=False):
        """Loads profile, collection, and deck list, in that order (deck
        list's cache key doesn't depend on the others, but collection's
        does — see load_profile). force: False reads from cache only;
        True re-fetches everything from Moxfield."""
        self.load_profile(force=force)
        self.load_collection(force=force)
        self.load_decks(force=force)

    def load_profile(self, force=False):
        """Loads profileImageUrl and collectionPublicId. force: False
        reads the cached user_<username>.json if present (leaves fields
        unchanged if not cached yet); True fetches from Moxfield's users
        API and overwrites the cache."""
        path = paths.user_cache_path(self._username)

        if not force:
            data = cache_io.read_json(path)
            if data is None:
                return
        else:
            response = requests.get(moxfield.user_api_url(self._username), timeout=10)
            response.raise_for_status()
            data = response.json()
            cache_io.write_json(path, data, indent=2)

        self._profile_image_url = data.get("profileImageUrl", "")
        self._collection_id = data.get("collectionPublicId", "-1")

    def load_decks(self, force=False):
        """Loads the list of this user's decks as Deck stubs (id + name
        only — each deck's cards/format load separately, on demand, via
        Deck.load()): their Moxfield decks, then the decks they built in
        the Deck Maker (see models.local_decks). force: False reads the
        cached decks_<username>.json if present; True fetches the
        Moxfield deck list from its search API and overwrites the cache."""
        path = paths.decks_list_cache_path(self._username)

        if not force:
            decks = cache_io.read_json(path) or {"data": []}
        else:
            url = moxfield.decks_search_api_url()
            params = {
                "includePinned": "false",
                "showIllegal": "true",
                "authorUserNames": self._username,
                "sortType": "updated",
                "sortDirection": "descending",
                "board": "mainboard",
                "pageNumber": 1,
                "pageSize": 100,  # Moxfield's max; defaults to 25
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            decks = response.json()
            for page in range(2, decks.get("totalPages", 1) + 1):
                params["pageNumber"] = page
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                decks["data"].extend(response.json()["data"])
            cache_io.write_json(path, decks)

        self._decks = []
        for deck in decks["data"]:
            name = deck["name"]
            deck_id = deck["publicId"]
            self._decks.append(Deck(deck_id, name))
        self._decks += local_decks.load_stubs(self._username)

    def load_collection(self, force=False):
        """(Re)builds self._collection using the current collection_id
        (set by load_profile) and loads it. force: passed straight
        through to Collection.load()."""
        self._collection = Collection(self._collection_id)
        self._collection.load(force=force)

    # --- Moxfield refresh steps ---------------------------------------
    # Each re-fetches one part of the user's data and returns a short
    # summary for the sync log (see sync.py, which runs and logs them).

    def refresh_profile(self):
        """Re-fetches the profile (avatar, collection ID)."""
        self.load_profile(force=True)
        return f"collection ID {self._collection_id}"

    def refresh_collection(self):
        """Re-fetches the collection only. The profile is fetched first
        only if the collection ID isn't known yet (not cached)."""
        if self._collection_id == "-1":
            self.load_profile(force=True)
        self.load_collection(force=True)
        if self._collection_id == "-1":
            return "account has no collection"
        cards = self._collection.cards
        return f"{sum(c['quantity'] for c in cards)} cards ({len(cards)} unique)"

    def refresh_decks(self):
        """Re-fetches the deck list, then the contents of each deck that
        changed on Moxfield since the last sync (by lastUpdatedAtUtc) or
        whose contents aren't cached. One deck failing doesn't stop the
        rest — failures are counted in the summary instead."""
        list_path = paths.decks_list_cache_path(self._username)
        old_list = cache_io.read_json(list_path) or {"data": []}
        old_stamps = {d["publicId"]: d.get("lastUpdatedAtUtc") for d in old_list["data"]}

        self.load_decks(force=True)
        new_stamps = {
            d["publicId"]: d.get("lastUpdatedAtUtc")
            for d in cache_io.read_json(list_path)["data"]
        }

        updated = failed = 0
        moxfield_decks = [d for d in self._decks if d.source == SOURCE_MOXFIELD]
        for deck in moxfield_decks:
            unchanged = old_stamps.get(deck.deck_id) == new_stamps.get(deck.deck_id)
            if unchanged:
                deck.load()  # cache-only: tells us if it's missing or outdated
                if deck.cards and not deck.outdated:
                    continue
            try:
                deck.load(force=True)
                updated += 1
            except Exception:
                failed += 1

        summary = f"{len(moxfield_decks)} decks, {updated} updated"
        if failed:
            summary += f", {failed} failed"
        return summary
