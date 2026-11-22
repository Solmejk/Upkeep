"""deck_import.parse: reading pasted decklists (no Scryfall lookups here)."""

import deck_import


def names(lines):
    return [line["name"] for line in lines]


def test_moxfield_export_layout_commander_then_blank_line():
    parsed = deck_import.parse("1 Edgar Markov (INR) 491 *F*\n\n1 Sol Ring (C21) 263\n10 Mountain\n")
    assert names(parsed["commanders"]) == ["Edgar Markov"]
    assert names(parsed["cards"]) == ["Sol Ring", "Mountain"]
    commander = parsed["commanders"][0]
    assert (commander["set"], commander["cn"], commander["foil"]) == ("inr", "491", True)
    assert parsed["cards"][1]["qty"] == 10


def test_section_headers_and_partners():
    parsed = deck_import.parse("Commander\n1 Tymna the Weaver\n1 Thrasios, Triton Hero\nDeck\n1 Sol Ring\n"
                               "Sideboard\n1 Opt\n")
    assert names(parsed["commanders"]) == ["Tymna the Weaver", "Thrasios, Triton Hero"]
    assert names(parsed["cards"]) == ["Sol Ring"]  # sideboard left out


def test_a_lone_sideboard_header_keeps_the_export_layout():
    parsed = deck_import.parse("1 Edgar Markov\n\n1 Sol Ring\n\nSIDEBOARD:\n1 Opt\n")
    assert names(parsed["commanders"]) == ["Edgar Markov"]
    assert names(parsed["cards"]) == ["Sol Ring"]


def test_plain_list_has_no_commander():
    parsed = deck_import.parse("4 Lightning Bolt\n20 Mountain\n")
    assert parsed["commanders"] == []
    assert names(parsed["cards"]) == ["Lightning Bolt", "Mountain"]


def test_moxfield_tags_x_quantities_and_etched():
    parsed = deck_import.parse("1x Sol Ring (CMM) 410 #!Ramp #!Cost reducer\n"
                               "1 Command Tower (CM1) 2 *E* #!Land\n")
    sol, tower = parsed["cards"]
    assert (sol["name"], sol["set"], sol["cn"]) == ("Sol Ring", "cmm", "410")
    assert tower["etched"] and not tower["foil"]
    assert parsed["unreadable"] == []


def test_single_slash_double_faced_names():
    parsed = deck_import.parse("1 Jidoor, Aristocratic Capital / Overture (FIN) 284\n")
    assert names(parsed["cards"]) == ["Jidoor, Aristocratic Capital // Overture"]


def test_unreadable_lines_and_comments():
    parsed = deck_import.parse("// my deck\n1 Sol Ring\nthis is not a card line\n")
    assert names(parsed["cards"]) == ["Sol Ring"]
    assert parsed["unreadable"] == ["this is not a card line"]


def test_card_matching_ignores_back_faces():
    bolt_mdfc = {"name": "Emeritus of Conflict // Lightning Bolt"}
    assert not deck_import._matches("Lightning Bolt", bolt_mdfc)
    assert deck_import._matches("Emeritus of Conflict", bolt_mdfc)
    assert deck_import._matches("Lightning Bolt", {"name": "Lightning Bolt"})
