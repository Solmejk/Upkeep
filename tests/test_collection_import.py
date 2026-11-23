"""Importing a Moxfield collection CSV export (collection_import.py).
Scryfall is replaced by a small fake — no network."""

import json

import pytest

import collection_import
import paths

EXPORT = '''"Count","Tradelist Count","Name","Edition","Condition","Language","Foil","Tags","Last Modified","Collector Number","Alter","Proxy","Purchase Price"
"2","0","Sol Ring","c21","Near Mint","English","","","2025-11-25 20:28:09.820000","263","False","False","1.50"
"1","0","Lightning Bolt","2x2","Lightly Played","Japanese","foil","","2025-11-25 20:28:09.820000","117","False","False",""
"1","0","Jidoor, Aristocratic Capital / Overture","fin","Near Mint","English","etched","","","999","True","False","0"
"1","0","Opt","xln","Near Mint","English","","","","9999","False","False",""
"1","0","Not A Real Card","zzz","Near Mint","English","","","","1","False","False",""
"0","0","Zero Copies","c21","Near Mint","English","","","","1","False","False",""
'''

SCRYFALL = [
    {"id": "sol", "name": "Sol Ring", "set": "c21", "collector_number": "263", "rarity": "uncommon",
     "prices": {"eur": "1.10"}},
    {"id": "bolt", "name": "Lightning Bolt", "set": "2x2", "collector_number": "117", "rarity": "uncommon"},
    {"id": "jidoor", "name": "Jidoor, Aristocratic Capital // Overture", "set": "fin", "collector_number": "999",
     "rarity": "rare", "card_faces": [{"name": "Jidoor, Aristocratic Capital"}, {"name": "Overture"}]},
    {"id": "opt-xln", "name": "Opt", "set": "xln", "collector_number": "65", "rarity": "common"},
]


def fake_cards_collection(asked: list):
    """Scryfall's /cards/collection: returns the cards an identifier finds."""
    def hit(ident, card):
        if "collector_number" in ident:
            return card["set"] == ident["set"] and card["collector_number"] == ident["collector_number"]
        if "set" in ident and card["set"] != ident["set"]:
            return False
        return collection_import._matches(ident["name"], card)
    return [c for c in SCRYFALL if any(hit(i, c) for i in asked)]


def test_parse_reads_moxfield_columns():
    rows = collection_import.parse(EXPORT)
    assert len(rows) == 5  # the "0" row is skipped
    sol, bolt, jidoor = rows[0], rows[1], rows[2]
    assert (sol["quantity"], sol["set"], sol["cn"], sol["finish"], sol["purchase_price"]) == (2, "c21", "263", "nonFoil", 1.5)
    assert (bolt["finish"], bolt["language"], bolt["condition"]) == ("foil", "ja", "lightlyPlayed")
    assert (jidoor["finish"], jidoor["alter"]) == ("etched", True)


def test_parse_rejects_other_files():
    with pytest.raises(ValueError, match="Moxfield collection export"):
        collection_import.parse("Name,Price\nSol Ring,1\n")


def test_resolve_falls_back_from_number_to_name(monkeypatch):
    monkeypatch.setattr(collection_import.scryfall, "cards_collection", fake_cards_collection)
    found, missing = collection_import.resolve(collection_import.parse(EXPORT))
    by_name = {row["name"]: card["id"] for row, card in found}
    assert by_name["Sol Ring"] == "sol"
    assert by_name["Jidoor, Aristocratic Capital / Overture"] == "jidoor"  # "/" vs "//"
    assert by_name["Opt"] == "opt-xln"  # wrong number: found by set + name
    assert [r["name"] for r in missing] == ["Not A Real Card"]


def test_import_writes_a_collection_the_app_can_read(monkeypatch, tmp_path):
    monkeypatch.setattr(collection_import.scryfall, "cards_collection", fake_cards_collection)
    monkeypatch.setattr(paths, "collection_cache_path", lambda cid: tmp_path / f"collection_{cid}.json")
    export = tmp_path / "moxfield_collection.csv"
    export.write_text(EXPORT, encoding="utf-8")

    summary, missing = collection_import.import_file(export, "abc")

    saved = json.loads((tmp_path / "collection_abc.json").read_text(encoding="utf-8"))
    assert saved["totalOverall"] == 5  # 2 + 1 + 1 + 1
    assert summary.startswith("5 cards (4 unique)") and "1 row not found" in summary
    sol = saved["data"][0]
    assert sol["quantity"] == 2 and sol["finish"] == "nonFoil" and not sol["isFoil"]
    assert sol["language"] == {"code": "en", "name": "English"}
    assert sol["card"]["scryfall_id"] == "sol" and sol["card"]["cn"] == "263"
    assert sol["card"]["prices"]["eur"] == 1.10
    bolt = saved["data"][1]
    assert bolt["isFoil"] and bolt["language"]["code"] == "ja" and bolt["condition"] == "lightlyPlayed"
