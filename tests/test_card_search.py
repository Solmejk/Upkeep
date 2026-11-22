"""card_search: the Scryfall-style search used by the Collection, deck and
Deck Maker search boxes."""

import pytest

import card_search
from conftest import make_entry

ELF = make_entry("Llanowar Elves", type_line="Creature — Elf Druid", colors=("G",), cmc=1,
                 oracle="{T}: Add {G}.", rarity="common", eur=0.30, set_code="m19", cn="314")
BOLT = make_entry("Lightning Bolt", type_line="Instant", colors=("R",), cmc=1, mana_cost="{R}",
                  oracle="Lightning Bolt deals 3 damage to any target.", rarity="uncommon", eur=1.50,
                  set_code="2x2", cn="117", foil=True)
DRAGON = make_entry("Shivan Dragon", type_line="Creature — Dragon", colors=("R",), cmc=6,
                    mana_cost="{4}{R}{R}", oracle="Flying", rarity="rare", eur=0.80, set_code="m20")
GRUUL = make_entry("Gruul Spellbreaker", type_line="Creature — Ogre Warrior", colors=("R", "G"), cmc=3,
                   mana_cost="{1}{R}{G}", oracle="Riot", rarity="rare", eur=0.25)
FOREST = make_entry("Forest", type_line="Basic Land — Forest", colors=(), identity=("G",), cmc=0,
                    mana_cost="", rarity="common", eur=0.05)
SOL_RING = make_entry("Sol Ring", type_line="Artifact", colors=(), cmc=1, mana_cost="{1}",
                      oracle="{T}: Add {C}{C}.", rarity="uncommon", eur=1.00, quantity=3)
ALL = [ELF, BOLT, DRAGON, GRUUL, FOREST, SOL_RING]


def names(query: str, context=None) -> set:
    predicate = card_search.compile_query(query, context)
    return {e["card"]["name"] for e in ALL if predicate(e)}


def test_empty_query_matches_everything():
    assert names("") == {e["card"]["name"] for e in ALL}
    assert names("   ") == {e["card"]["name"] for e in ALL}


def test_bare_words_search_the_name():
    assert names("bolt") == {"Lightning Bolt"}
    assert names('"lightning bolt"') == {"Lightning Bolt"}


def test_type_and_negation():
    assert names("t:creature") == {"Llanowar Elves", "Shivan Dragon", "Gruul Spellbreaker"}
    assert names("t:creature -t:dragon") == {"Llanowar Elves", "Gruul Spellbreaker"}


def test_colors():
    assert names("c:g") == {"Llanowar Elves", "Gruul Spellbreaker"}
    assert "Gruul Spellbreaker" not in names("c=g")  # exactly green


def test_mana_value_comparisons():
    assert names("mv<=1") == {"Llanowar Elves", "Lightning Bolt", "Forest", "Sol Ring"}
    assert names("mv>=6") == {"Shivan Dragon"}


def test_oracle_text():
    assert names("o:damage") == {"Lightning Bolt"}


def test_or_and_parentheses():
    assert names("t:instant or t:dragon") == {"Lightning Bolt", "Shivan Dragon"}
    assert names("(c:r or c:g) mv>2") == {"Shivan Dragon", "Gruul Spellbreaker"}


def test_rarity_and_price():
    assert names("r:rare") == {"Shivan Dragon", "Gruul Spellbreaker"}
    assert names("eur>=1") == {"Lightning Bolt", "Sol Ring"}


def test_foil():
    assert names("is:foil") == {"Lightning Bolt"}


def test_context_checks_come_from_the_screen():
    context = {"is": {"used": lambda e: e["card"]["name"] == "Sol Ring"}}
    assert names("is:used", context) == {"Sol Ring"}


def test_bad_queries_raise_search_error():
    for query in ("(t:creature", "t:creature)", "mv<=abc"):
        with pytest.raises(card_search.SearchError):
            card_search.compile_query(query)
