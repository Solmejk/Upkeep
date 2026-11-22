"""cardmarket: reading a purchase PDF's text, and the Moxfield export
(no PDF reading or Scryfall lookups here)."""

import cardmarket

PDF_TEXT = """Purchase #1315055014
Sent 18.11.2026 14:08
Seller - rdrobny
Unpaid: 17.11.2026 01:59 Paid: 17.11.2026 02:07 Sent: 18.11.2026 14:08 Not yet arrived
Contents 5 articles
Article Value 3,16 EUR
Shipping 3,50 EUR
Total 6,66 EUR
Magic the Gathering Singles:
1 Syr Konrad, the Grim 1 EN NM PROM R Cheap and safe shipping! 0,49 EUR
1 Island (V.3) 337 EN EX USG L 0,49 EUR
2 Moonlit Meditation 69 DE NM EOE R Foil - Cheap and safe shipping! 0,89 EUR
1 Duskwatch Recruiter/Krallenhorde Howler 203 EN EX SOI U H-Mtg store! 0,50 EUR
1 Twiddle EN GD 4ED C (S H) Mtg store in Norway! 0,29 EUR
Shipment History:
19.11.2026 15:52 Zoocomics Refund 1,28 € sent
"""


def test_header():
    p = cardmarket.parse_purchase(PDF_TEXT)
    assert p["order_id"] == "1315055014"
    assert p["seller"] == "rdrobny"
    assert p["date"] == "2026-11-17"  # the paid date
    assert (p["article_value"], p["shipping"], p["total"]) == (3.16, 3.50, 6.66)


def test_card_lines():
    p = cardmarket.parse_purchase(PDF_TEXT)
    lines = {line["name"]: line for line in p["lines"]}
    assert set(lines) == {"Syr Konrad, the Grim", "Island", "Moonlit Meditation",
                          "Duskwatch Recruiter // Krallenhorde Howler", "Twiddle"}
    assert lines["Island"]["number"] == "337"            # "(V.3)" version marker dropped
    meditation = lines["Moonlit Meditation"]
    assert (meditation["qty"], meditation["foil"], meditation["cm_language"], meditation["price"]) == \
        (2, True, "DE", 0.89)
    assert lines["Twiddle"]["number"] == ""              # no collector number printed
    assert lines["Twiddle"]["cm_condition"] == "GD"
    assert p["skipped"] == []                            # the refund line isn't a card


def test_cardmarket_set_codes():
    assert cardmarket.cardmarket_set_and_number("TP", "5") == ("tmp", "5")      # Tempest
    assert cardmarket.cardmarket_set_and_number("XINR", "386") == ("inr", "386")  # extras
    assert cardmarket.cardmarket_set_and_number("PEOE", "113") == ("peoe", "")   # promo numbering differs
    assert cardmarket.cardmarket_set_and_number("MYS", "247") == ("", "")        # reprint sheet: name only
    assert cardmarket._is_promo_set("PROM") and not cardmarket._is_promo_set("EOE")


def test_moxfield_export_uses_scryfall_printing_and_skips_nothing():
    line = cardmarket.parse_purchase(PDF_TEXT)["lines"][2]  # the foil German Meditations
    entry = {"quantity": 2, "isFoil": True, "purchasePrice": 0.89, "unresolved": False,
             "cardmarket": line, "card": {"name": "Moonlit Meditation", "set": "eoe", "cn": "69"}}
    csv_text = cardmarket.moxfield_csv([entry])
    header, row = csv_text.strip().splitlines()
    assert header.startswith('"Count","Tradelist Count","Name","Edition"')
    assert row == '"2","0","Moonlit Meditation","eoe","Near Mint","German","foil","","","69","False","False","0.89"'
    assert cardmarket.moxfield_list([entry]) == "2 Moonlit Meditation (EOE) 69 *F*\n"
