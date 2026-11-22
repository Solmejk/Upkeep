"""card_sort (the Sort menus) and printing (matching exact owned copies)."""

import card_sort
from conftest import make_entry
from printing import deck_card_printing_key, entry_printing_key, printing_key


def test_sort_by_name_ignores_case_and_accents():
    entries = [make_entry("Zombify"), make_entry("éomer"), make_entry("Aang")]
    assert [e["card"]["name"] for e in card_sort.sort_entries(entries, card_sort.SORT_NAME)] == \
        ["Aang", "éomer", "Zombify"]


def test_price_sort_uses_the_foil_price_for_foils():
    cheap = make_entry("Cheap", eur=0.10)
    foil = make_entry("Foil", eur=0.50, eur_foil=5.00, foil=True)  # 5.00 for this copy
    middle = make_entry("Middle", eur=1.00)
    order = card_sort.sort_entries([cheap, foil, middle], card_sort.SORT_PRICE_DESC)
    assert [e["card"]["name"] for e in order] == ["Foil", "Middle", "Cheap"]


def test_unknown_price_counts_as_zero():
    unpriced = make_entry("Unpriced", eur=None)
    cheap = make_entry("Cheap", eur=0.10)
    assert card_sort.sort_entries([cheap, unpriced], card_sort.SORT_PRICE_ASC)[0]["card"]["name"] == "Unpriced"
    assert card_sort.sort_entries([unpriced, cheap], card_sort.SORT_PRICE_DESC)[-1]["card"]["name"] == "Unpriced"


def test_printing_key_normalises_finish_and_case():
    assert printing_key("C21", "263", False, "nonFoil") == ("c21", "263", "nonfoil", "en")
    assert printing_key("c21", "263", True, "") == ("c21", "263", "foil", "en")
    assert printing_key("c21", "263", False, "Etched", "JA") == ("c21", "263", "etched", "ja")


def test_entry_and_deck_card_keys_match_for_the_same_copy():
    entry = make_entry("Sol Ring", set_code="c21", cn="263", foil=True)
    deck_card = {"name": "Sol Ring", "set": "c21", "cn": "263", "isFoil": True, "finish": "foil", "language": "en"}
    assert entry_printing_key(entry) == deck_card_printing_key(deck_card)
