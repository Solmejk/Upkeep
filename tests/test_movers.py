"""Biggest movers (models.price_history.movers): by € change and by %
change, the % ranking leaving out bulk cards. Price history is faked."""

import pytest

from models import price_history

PRICES = {  # scryfall id -> (previous day, last day)
    "big_rise": (40.0, 55.0),     # +€15  (+38 %)
    "pct_rise": (2.0, 5.0),       # +€3   (+150 %)
    "bulk_rise": (0.02, 0.10),    # +€0.08 (+400 %) — bulk: not in the % ranking
    "big_fall": (90.0, 70.0),     # −€20  (−22 %)
    "pct_fall": (4.0, 1.0),       # −€3   (−75 %)
    "same": (3.0, 3.0),
}


@pytest.fixture
def history(monkeypatch):
    monkeypatch.setattr(price_history, "days", lambda: ["2026-11-21", "2026-11-22"])
    monkeypatch.setattr(price_history, "price_on",
                        lambda day, sid, foil: PRICES[sid][0 if day == "2026-11-21" else 1])


def tiles(*ids):
    return [{"card": {"scryfall_id": i, "name": i}, "finish": "nonFoil"} for i in ids]


def name(mover):
    return mover[0]["card"]["name"] if mover else None


def test_ranked_by_value_and_by_percent(history):
    result = price_history.movers(tiles(*PRICES))
    assert result["previous_day"] == "2026-11-21"
    assert [name(m) for m in result["by_value"]] == ["big_rise", "big_fall"]
    assert [name(m) for m in result["by_percent"]] == ["pct_rise", "pct_fall"]


def test_bulk_cards_never_top_the_percent_ranking(history):
    result = price_history.movers(tiles("bulk_rise", "big_rise"))
    assert name(result["by_percent"][0]) == "big_rise"
    assert name(price_history.movers(tiles("bulk_rise"))["by_percent"][0]) is None


def test_nothing_moved(history):
    result = price_history.movers(tiles("same"))
    assert result["by_value"] == (None, None) and result["by_percent"] == (None, None)


def test_needs_two_price_days(monkeypatch):
    monkeypatch.setattr(price_history, "days", lambda: ["2026-11-22"])
    assert price_history.movers(tiles("big_rise")) is None
