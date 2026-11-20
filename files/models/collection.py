"""Collection: one Moxfield collection's card list. Loaded from cache or
fetched fresh — see load() for the two modes.
"""

from concurrent.futures import ThreadPoolExecutor

import requests
import cache_io
import moxfield
import paths
import scryfall_prices

class Collection:
    def __init__(self, collection_id):
        """collection_id: the Moxfield public ID of this collection, or
        "-1" for "no collection" (e.g. a logged-out placeholder — see
        MTGApp.collection). Starts empty — call load() to populate."""
        self._collection_id = collection_id
        self._cards = []
        self._total_cards = 0

    @property
    def cards(self):
        """Raw Moxfield collection entries: each has at least "quantity"
        and "card" (with name/set/cn/prices/etc.)."""
        return self._cards

    @property
    def total_cards(self):
        return self._total_cards

    def load(self, force=False):
        """Populates cards/total_cards. force: False reads the cached
        collection_<id>.json if present (leaves the collection empty if
        not cached yet); True fetches the full collection from Moxfield's
        search API and overwrites the cache. A collection_id of "-1" (no
        real collection) makes the force branch a no-op."""
        path = paths.collection_cache_path(self._collection_id)

        if not force:
            data = cache_io.read_json(path)
            if data is None:
                return
        else:
            if self._collection_id == "-1":
                return
            data = self._fetch_all_pages()
            if data is None:
                return
            cache_io.write_json(path, data)

        self._total_cards = data["totalOverall"]
        self._cards = data["data"]
        scryfall_prices.apply(self._cards)  # Scryfall's (fresher) prices over Moxfield's

    def _fetch_all_pages(self):
        """Fetches every page of the collection from Moxfield's search API
        and returns the first page's response with "data" replaced by all
        pages' entries combined, or None if the collection is empty.
        Moxfield rejects pageSize 0 and caps pages at 100 entries, so the
        full collection takes one request per page — pages after the
        first (which reports totalPages) are fetched a few at a time."""
        url = moxfield.collection_search_api_url(self._collection_id)

        def fetch_page(page):
            params = {
                "pageNumber": page,
                "pageSize": 100,
                "sortType": "cardName",
                "sortDirection": "ascending",
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()

        data = fetch_page(1)
        if data == {}:
            return None

        remaining = range(2, data.get("totalPages", 1) + 1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for page_data in pool.map(fetch_page, remaining):  # keeps page order
                data["data"].extend(page_data["data"])

        return data
