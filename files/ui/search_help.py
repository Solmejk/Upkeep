"""The user-facing guide to the card search syntax, shown on the Settings
screen's "Search syntax" page. Keep in sync with card_search.py.
"""

import html
from ui import theme

_ACCENT = theme.ACCENT
_MUTED = theme.MUTED


def _rows(rows):
    """rows: (syntax, meaning) pairs. Syntax is plain text (escaped here,
    so "mv<=2" isn't read as an HTML tag; "&nbsp;" separators are kept);
    meaning may contain HTML."""
    return "".join(
        f"<tr><td style='padding:3px 16px 3px 0; white-space:nowrap;'>"
        f"<code>{html.escape(syntax).replace('&amp;nbsp;', '&nbsp;')}</code></td>"
        f"<td style='padding:3px 0;'>{meaning}</td></tr>"
        for syntax, meaning in rows
    )


def _section(title, rows):
    return (
        f"<h3 style='color:{_ACCENT}; margin-top:18px;'>{title}</h3>"
        f"<table cellspacing='0'>{_rows(rows)}</table>"
    )


SEARCH_HELP_HTML = f"""
<p>The card search boxes on the <b>Collection</b> page and inside a deck
understand <a href="https://scryfall.com/docs/syntax" style="color:{_ACCENT};">Scryfall's search syntax</a>.
Combine as many filters as you like — results update when you stop typing,
and a mistake in the query is explained next to the search box.</p>

<p style='color:{_MUTED};'>The search on the Decks page just finds decks by
name.</p>

{_section("Combining filters", [
    ("t:goblin c:r", "both must match (a space means AND)"),
    ("t:elf or t:goblin", "either one matches"),
    ("-t:land", "minus excludes: everything that is <i>not</i> a land"),
    ("(c:r or c:g) t:dragon", "brackets group filters"),
    ('o:"draw a card"', "quotes keep words together"),
])}

{_section("Name", [
    ("bolt", "name contains the word"),
    ('"lightning bolt"', "name contains the phrase"),
    ('!"Lightning Bolt"', "exact name"),
    ("name:/^dark/", "regex (see below)"),
])}

{_section("Type, rules text, flavor, artist", [
    ("t:creature &nbsp; t:legendary", "type line contains"),
    ('o:flying &nbsp; o:"enters the battlefield"', "rules text contains"),
    ("o:~", "<code>~</code> stands for the card's own name"),
    ('ft:"dragon"', "flavor text contains"),
    ("a:yueko", "artist contains"),
])}

{_section("Colors", [
    ("c:g", "green (and possibly other colors)"),
    ("c=rg", "exactly red and green"),
    ("c<=rg", "only red and/or green (or colorless)"),
    ("c:c &nbsp; c:m", "colorless / multicolored"),
    ("c>=3", "three or more colors"),
    ("id:esper", "color identity fits in an Esper (WUB) commander deck"),
    ("c:azorius", "color names work too: guilds, shards and wedges"),
])}

{_section("Mana cost and numbers", [
    ("mv=3 &nbsp; mv<=2 &nbsp; mv:even", "mana value (also <code>cmc</code>)"),
    ("m:{G}{G} &nbsp; m:2WW", "mana cost contains these symbols"),
    ("m={3}{W}", "exact mana cost"),
    ("pow>=5 &nbsp; tou<2 &nbsp; loy>=4", "power, toughness, loyalty"),
])}

<p style='color:{_MUTED};'>Number filters take <code>:</code> <code>=</code> <code>!=</code>
<code>&lt;</code> <code>&lt;=</code> <code>&gt;</code> <code>&gt;=</code>.</p>

{_section("Rarity, set, legality", [
    ("r:mythic &nbsp; r>=rare", "rarity (c / u / r / m work too)"),
    ("s:tla", "set code"),
    ("cn:4 &nbsp; cn>=300", "collector number"),
    ("year>=2024", "release year"),
    ("f:commander &nbsp; f:modern", "legal in a format (<code>edh</code> works too)"),
    ("banned:commander &nbsp; restricted:vintage", "banned / restricted in a format"),
    ("border:borderless &nbsp; frame:showcase", "border color, frame or frame effect"),
])}

{_section("Prices and your copies", [
    ("eur>=5 &nbsp; usd<1 &nbsp; tix>2", "price (foil copies use the foil price)"),
    ("qty>=4", "how many copies you have / the deck runs"),
    ("is:foil &nbsp; is:nonfoil &nbsp; is:etched", "your copy's finish"),
    ("is:proof &nbsp; is:signed &nbsp; is:altered", "marked as an artist proof / signed / altered "
                                                   "in Settings → Custom card images"),
    ("is:proxy", "your copy is a proxy"),
    ("lang:en &nbsp; lang:japanese", "your copy's language"),
    ("is:used", "every copy you own of this version is in an active deck "
                "(Collection search)"),
    ("-is:used", "you have a free copy — not tied up in an active deck"),
    ("is:unique", "you own exactly one copy, across all sets, foils and languages"),
])}

{_section("is: / not:", [
    ("is:commander", "can be your commander"),
    ("is:spell &nbsp; is:permanent &nbsp; is:historic", "card categories"),
    ("is:vanilla", "creature with no rules text"),
    ("is:dfc &nbsp; is:mdfc &nbsp; is:transform", "double-faced cards"),
    ("is:split &nbsp; is:adventure &nbsp; is:flip &nbsp; is:meld", "other card layouts"),
    ("is:reserved &nbsp; is:reprint &nbsp; is:digital", "printing facts"),
    ("is:multicolor &nbsp; is:colorless", "same as c:m / c:c"),
    ("not:foil", "<code>not:</code> is the opposite of <code>is:</code>"),
])}

{_section("Regular expressions", [
    ("o:/^flying$/", "a line of rules text that is exactly \"Flying\""),
    ("name:/^dark/", "name starts with \"dark\""),
    (r"o:/deals? \d+ damage/", "regex works in name, o:, t:, ft: and a:"),
])}

{_section("Examples", [
    ("t:creature c:g mv<=2", "cheap green creatures"),
    ('id<=esper o:"draw a card" -t:land', "card draw for an Esper deck"),
    ("t:legendary t:creature c=rg", "Gruul commanders"),
    ("is:foil r>=rare eur>=5", "your valuable foils"),
    ("t:creature c:g -is:used", "green creatures you can still use"),
    ("f:commander -is:reprint year>=2025", "new commander-legal cards"),
])}

<p style='color:{_MUTED}; margin-top:18px;'>Not available, because Moxfield
doesn't provide the data: <code>kw:</code> (keywords — <code>o:</code> finds most),
<code>produces:</code>, <code>wm:</code> (watermark) and <code>game:</code>.</p>
"""
