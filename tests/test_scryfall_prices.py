"""Collection prices from Scryfall (scryfall_prices.py): the daily full
fetch, and "only new printings" after a collection refresh / import.
Scryfall is replaced by a fake that records what it was asked for."""

from datetime import date

import pytest

import paths
import scryfall_prices

TODAY = date.today().isoformat()


@pytest.fixture
def prices_file(monkeypatch, tmp_path):
    path = tmp_path / "collection_prices.json"
    monkeypatch.setattr(paths, "COLLECTION_PRICES_PATH", path)
    return path


@pytest.fixture
def asked(monkeypatch):
    """Every id Scryfall was asked for; each card costs 1.00 EUR."""
    ids = []

    def fake(identifiers):
        ids.extend(i["id"] for i in identifiers)
        return [{"id": i["id"], "prices": {"eur": "1.00"}} for i in identifiers]
    monkeypatch.setattr(scryfall_prices.scryfall, "cards_collection", fake)
    return ids


def entries(*ids):
    return [{"card": {"scryfall_id": i}} for i in ids]


def save(fetched, ids):
    import cache_io
    cache_io.write_json(paths.COLLECTION_PRICES_PATH,
                        {"fetched": fetched, "prices": {i: {"eur": 0.5} for i in ids}})


def test_due_when_never_fetched_or_fetched_on_an_earlier_day(prices_file):
    assert scryfall_prices.needs_daily_refresh()
    save("2000-01-01", ["a"])
    assert scryfall_prices.needs_daily_refresh()
    save(TODAY, ["a"])
    assert not scryfall_prices.needs_daily_refresh()


def test_daily_fetch_asks_for_everything_once_a_day(prices_file, asked):
    save("2000-01-01", ["a", "b"])
    scryfall_prices.refresh(entries("a", "b", "c"))
    assert sorted(asked) == ["a", "b", "c"]
    assert not scryfall_prices.needs_daily_refresh()
    asked.clear()
    assert scryfall_prices.refresh(entries("a", "b", "c")) == "already fetched today"
    assert asked == []


def test_new_cards_only_fetch_just_those_and_keep_the_daily_fetch_due(prices_file, asked):
    save("2000-01-01", ["a", "b"])
    scryfall_prices.refresh(entries("a", "b", "new"), only_new=True)
    assert asked == ["new"]
    assert scryfall_prices.needs_daily_refresh()  # the full fetch still runs today
    asked.clear()
    assert scryfall_prices.refresh(entries("a", "b", "new"), only_new=True) == "no new printings"
    assert asked == []
