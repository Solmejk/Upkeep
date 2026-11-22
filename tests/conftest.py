"""Shared test setup: makes the app's modules (in files/) importable, and
offers small builders for card data in the shapes the app uses.

Tests never touch the network or your data — anything that saves goes to
pytest's temporary folders.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "files"))


def make_entry(name: str, *, set_code: str = "tst", cn: str = "1", type_line: str = "Creature — Elf",
               colors=("G",), identity=None, cmc: float = 1.0, mana_cost: str = "{G}",
               rarity: str = "common", oracle: str = "", eur=None, eur_foil=None, quantity: int = 1,
               foil: bool = False, language: str = "en", legal=("commander",), released: str = "2020-01-01",
               card_faces=None, layout: str = "normal") -> dict:
    """A collection entry ({"quantity", "isFoil", "card": {...}}) like Moxfield's."""
    colors = list(colors)
    return {
        "quantity": quantity,
        "isFoil": foil,
        "finish": "foil" if foil else "nonFoil",
        "language": {"code": language},
        "card": {
            "name": name, "set": set_code, "cn": cn, "type_line": type_line,
            "colors": colors, "color_identity": list(identity if identity is not None else colors),
            "cmc": cmc, "mana_cost": mana_cost, "rarity": rarity, "oracle_text": oracle,
            "prices": {"eur": eur, "eur_foil": eur_foil}, "legalities": {f: "legal" for f in legal},
            "released_at": released, "card_faces": card_faces or [], "layout": layout, "lang": language,
        },
    }


@pytest.fixture
def entry():
    return make_entry
