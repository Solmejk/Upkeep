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

    def fake(identifiers, on_batch=None):
        ids.extend(i["id"] for i in identifiers)
        cards = [{"id": i["id"], "prices": {"eur": "1.00"}} for i in identifiers]
        if on_batch:
            on_batch(cards)
        return cards
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


def test_a_daily_fetch_cut_short_keeps_its_batches_and_resumes(prices_file, monkeypatch):
    save("2000-01-01", ["a", "b", "c"])
    asked = []

    def first_batch_then_429(identifiers, on_batch=None):
        asked.append([i["id"] for i in identifiers])
        on_batch([{"id": "a", "prices": {"eur": "2.00"}}])  # one batch arrives...
        raise RuntimeError("429 Too Many Requests")          # ...then Scryfall refuses
    monkeypatch.setattr(scryfall_prices.scryfall, "cards_collection", first_batch_then_429)
    with pytest.raises(RuntimeError):
        scryfall_prices.refresh(entries("a", "b", "c"))
    kept = scryfall_prices.saved()
    assert kept["prices"]["a"]["eur"] == 2.0      # today's price kept
    assert kept["prices"]["b"] == {"eur": 0.5}    # yesterday's still there meanwhile
    assert scryfall_prices.needs_daily_refresh()  # still due

    def rest(identifiers, on_batch=None):
        asked.append([i["id"] for i in identifiers])
        on_batch([{"id": i["id"], "prices": {"eur": "3.00"}} for i in identifiers])
    monkeypatch.setattr(scryfall_prices.scryfall, "cards_collection", rest)
    scryfall_prices.refresh(entries("a", "b", "c"))
    assert asked[-1] == ["b", "c"]                # resumed: "a" isn't asked again
    assert not scryfall_prices.needs_daily_refresh()


def test_new_cards_only_fetch_just_those_and_keep_the_daily_fetch_due(prices_file, asked):
    save("2000-01-01", ["a", "b"])
    scryfall_prices.refresh(entries("a", "b", "new"), only_new=True)
    assert asked == ["new"]
    assert scryfall_prices.needs_daily_refresh()  # the full fetch still runs today
    asked.clear()
    assert scryfall_prices.refresh(entries("a", "b", "new"), only_new=True) == "no new printings"
    assert asked == []
