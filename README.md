# Upkeep

A desktop companion app for Magic: The Gathering, focused on **paper** collections and decks. It syncs your collection and decks from [Moxfield](https://moxfield.com), takes card data and prices from [Scryfall](https://scryfall.com), and adds tools Moxfield doesn't have: availability checks across your decks, a deck builder that only uses cards you own, value and price history, a game tracker with Elo ratings, purchase tracking and token printing.

Built with Python and Qt (PySide6). Runs on Windows. It should also run on macOS and Linux, but it has only been tested on Windows.

---

## Download

From the [Releases page](https://github.com/Solmejk/Upkeep/releases) (Windows 10/11, no Python needed), get either:

- **`Upkeep-Setup-<version>.exe`** (recommended): installs Upkeep to `%LOCALAPPDATA%\Programs\Upkeep` with a Start Menu entry, an optional desktop shortcut and an uninstaller under Windows Settings → Apps. No admin rights needed. **Updates itself:** when a new release is out, an **Update to vX** button appears in the sidebar (also under Settings → Updates); one click downloads it, and Upkeep closes, updates and reopens.
- **`Upkeep-<version>-portable.exe`**: no installation; put it anywhere and run it. It tells you about new versions too, but you download them yourself.

Either way:

- Windows may show a SmartScreen warning the first time, since the app isn't code-signed: click **More info → Run anyway**.
- The first start takes a few seconds (the single .exe unpacks itself).
- Your data is kept in `%APPDATA%\Upkeep`, separate from the program, so updating or uninstalling never touches it. (Data from before the rename, in `%APPDATA%\MTG Collection Manager`, is moved there automatically on the first start.)

## Running from source

**Requirements:** Python 3.10 or newer (developed on 3.13).

```bash
pip install -r requirements.txt
python files/main.py
```

| Package | Used for |
|---|---|
| `PySide6` | The user interface |
| `requests` | Moxfield and Scryfall requests |
| `python-docx`, `pillow` | Token Printer (Word documents, image rotation) |
| `pdfplumber` | Reading Cardmarket purchase PDFs. Not needed if Poppler's `pdftotext` is installed. |

On first launch, click the avatar in the sidebar and enter your **Moxfield username**. Your profile, collection and decks are fetched once and then cached. Your Moxfield collection and decks must be public.

---

## Features

### Home
- A welcome message and your **Game Tracker summary**:
  - your Elo, games, wins and win rate;
  - your best deck, shown with its commander's art.
- **Showcases:** your own collections of favourite cards, such as artist proofs or a set you're completing. Pick one from the dropdown, or choose "+ New showcase…" to make one.

### Decks
- All your Moxfield decks and the decks you've built in the app, with filters for active decks and Commander decks.
- **Import deck:** paste a decklist in Moxfield's text format, or load a `.txt` file, to add it as a local deck.
  - Exact printings and foils are kept: `1 Sol Ring (C21) 263 *F*`.
  - Moxfield tags (`#!Ramp`) and sideboards are ignored.
  - Name-only lines get the card's **newest normal printing**. That skips The List, Art Series cards, serialized cards and unreleased sets.
- **Deck page:**
  - Your Game Tracker Elo for that deck, shown in the title and as a chart.
  - Mana curve, color balance and mana production.
  - Cards grouped by type.
  - The **tokens** the deck makes, each with which cards create it. You can set a **default printing per token**, which is then used in every deck.
  - Checks for which language of each card you use.
  - Edit in the Deck Maker. Moxfield decks are edited as a copy, and decks built in the app can be exported to Moxfield.
  - Local decks without a commander get a **Set commander…** button.

### Collection
- Your whole collection in a fast, searchable grid. Search uses Scryfall's syntax, e.g. `t:creature c:g mv<=3`; the full guide is under Settings.
- Sort by name, price or color.
- Stats: total value, rarities and color breakdown.
- **Collection value over time:** a chart with one point per price update.
- **Biggest movers:** the card that rose most and the card that fell most since the previous price update.
- **Card popup:** the card at full size, which of your decks use it, and a **price history chart** for that printing.

### Deck Maker
Build Commander decks from cards you actually own. It knows which copies are already used in your other active decks.

### Game Tracker
Track game results for your playgroup.

- **Players:**
  - **Guests** are players made in the app.
  - **Moxfield players** are linked to a Moxfield username and can have a **nickname**.
  - Link a guest to a Moxfield username later and all their games stay connected. If that username is already a player, the two are merged.
- **Recording a game:**
  - Pick 2–8 players (4 by default), each player's deck, and the winner (or no winner). Add notes if you like.
  - The deck suggestions follow the player: your active decks for you, a Moxfield player's public decks, or a guest's earlier decks.
  - **Borrowed decks:** set "Deck from" to the friend who owns the deck. The game then counts for the owner's deck.
- **Standings:**
  - A **Players** table and a **Decks** table, with games, wins, win % and **Elo**.
  - Both tables sort when you click a column.
- **Popouts:**
  - Click a **player** to see their Elo chart (one point per game), stats and best deck.
  - Click a **deck** to see its Elo chart, its **nemesis** (the deck that has beaten it most), its **prey** (the deck it has beaten most) and who has piloted it.
- **Elo:**
  - Everyone starts at 1500.
  - The winner takes points from every other player at the table. More points come from higher-rated opponents, so an upset counts for more.
  - The gain is split across the opponents, so a 4-player win is worth about as much as a 1v1 win.
  - Draws change nothing.
  - Player Elo and deck Elo are tracked separately, and both are recalculated from all games, so editing an old game updates everything.

### Other Apps
- **Purchases:** import a **Cardmarket purchase PDF**.
  - Every card is looked up on Scryfall and the purchase is saved like a small collection, with the same grid, search and stats.
  - Mark a purchase **received** (a green ✓ in the list).
  - Remove cards the seller couldn't send (right-click a card).
  - Export a Moxfield CSV, or copy a card list for Moxfield's import.
  - If Cardmarket's `ArticlesFromShipment<order>.csv` is in the same folder as the PDF, card and foil counts are checked against it.
- **Token Printer:**
  - Pick a deck and how many copies of each token you want (2 by default).
  - You get an A4 Word document with the tokens at real card size (88 × 63 mm), two per row, using full-resolution Scryfall images and your default token printings.
  - A page preview shows exactly how it will print. Print at 100% ("Actual size").
- **Availability Checker:** paste any Moxfield deck link to see which cards you own and have free, which are already in another active deck, and which you're missing. Missing cards are priced, and the result can be exported.

### Settings
- **Sync → Refresh all:**
  - Fetches your profile, collection and decks from Moxfield, plus collection prices from Scryfall.
  - **Refresh prices** only asks Scryfall: your cards stay as last synced or imported. Prices also update on their own once a day (at startup, or at midnight if Upkeep is left open), so you rarely need it.
  - **View log** shows when each was last synced.
- **Import from Moxfield export:** the backup for when Moxfield's API can't be reached. Export your collection on moxfield.com (Collection → Export → CSV) and import the file; quantities, foil, language and condition come from the file, card data and prices from Scryfall. Decks come in through Decks → Import deck, with a deck's text export.
- **Cache:** clear the collection, decks, profile or images.
- **Search syntax:** the full guide to the search filters.
- **Custom card images:** use your own front and/or back image for a printing, such as an artist proof or a signed card.

---

## Data and online services

### What's stored where
The **downloaded app** keeps everything in `%APPDATA%\Upkeep`; **running from source** keeps it next to the code, in `files/`. Either way:

| Folder | Contents | Cleared by "Clear cache"? |
|---|---|---|
| `cache/` | Moxfield data, card images, Scryfall prices, the sync log | Yes, everything except the sync log, by category |
| `data/` | Things you made: local decks, showcases, custom card images, purchases, the game tracker, value and price history, default token printings | **Never** |
| `logs/` | `current.log` (this session) and `previous.log` (the one before): everything the app prints, errors and crash tracebacks, timestamped. Settings → Logs → Open log folder | No — each start replaces `previous.log` |

To move from running the source to the downloaded app (or back), copy the `data/` folder across — the cache refills itself.

### Moxfield and Scryfall
- **Moxfield:** your profile, collection and decks, plus other players' public deck lists for the Game Tracker. Data is fetched only when you log in or refresh, and cached in between — never automatically. If Moxfield can't be reached, import its CSV export instead (Settings → Import from Moxfield export).
- **Scryfall:**
  - **Collection prices** are separate from the collection: fetched automatically once a day, on the first start of a new day (about 45 batch requests for 3,000+ printings). Scryfall updates its prices daily, and Moxfield's prices can lag a day or more behind. Refreshing or importing the collection only fetches prices for cards that are new.
  - **Card lookups** for purchases, deck imports and collection CSV imports use batch requests of 75 cards.
  - **Requests are throttled** to 3 per second across the whole app. Scryfall's limit is about 10.
  - **Card images** come from Scryfall's image servers, which aren't rate-limited like the API, and are cached on disk.

---

## Project structure

```
files/
├── main.py                entry point (--self-test checks a build)
├── self_test.py           the build check: bundled files + libraries
├── app.py, session.py     app state and the logged-in user
├── paths.py               all file locations
├── moxfield.py            every Moxfield request
├── scryfall.py            every Scryfall request (search, prices, printings)
├── image_cache.py         every image download (cached on disk)
├── scryfall_prices.py, sync.py, sync_log.py          refreshing from Moxfield / Scryfall
├── cardmarket.py          Cardmarket PDF → purchase (+ Moxfield export)
├── deck_import.py, deck_export.py                    Moxfield text format
├── token_print.py         token sheets (.docx)
├── card_search.py, card_sort.py, printing.py, ...    card logic
├── models/                collection, decks, local decks, purchases,
│   │                      value / price history, ...
│   └── game_tracker/      data, store (GameTracker), elo, stats
└── ui/
    ├── main_window.py, sidebar.py, theme.py, style.qss
    ├── screens/           one file per page (home, decks, collection,
    │   │                  game_tracker, other_apps, purchases, ...)
    │   └── deck_maker/    screen, commander page, build page, helpers
    └── components/        shared widgets: card grid, card tiles,
                           clickable label, section card, popouts,
                           charts, dialogs, ...
tests/                     automated tests (pure logic — no network, no UI)
tools/make_icon.py         draws the app icon (files/assets/app_icon.*)
build.py                   builds the .exe and the installer (tests first)
Upkeep.spec                what goes into the .exe (PyInstaller)
installer/upkeep.iss       the Setup.exe recipe (Inno Setup)
.github/workflows/         GitHub Actions: build + publish a Release
```

Each module starts with a docstring that explains what it does and how it connects to the rest.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests cover the logic that's easiest to break: card search, sorting and printing keys, deck list parsing, Cardmarket PDF parsing and the Moxfield export, and the Game Tracker's rules, merging, borrowing and Elo. They never touch the network or your data.

## Building the app

```bash
pip install -r requirements-dev.txt
python build.py
```

This runs the tests, builds **`dist/Upkeep.exe`** with PyInstaller (`Upkeep.spec`), then wraps it in the installer **`dist/Upkeep-Setup-<version>.exe`** with [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`installer/upkeep.iss`; install it with `winget install JRSoftware.InnoSetup`). The version is the latest git tag, or `dev`. Options: `--skip-tests`, `--no-installer`, `--version 1.2.0`.

Check a build without opening a window:

```bash
dist/Upkeep.exe --self-test
```

It confirms the bundled icons and stylesheet, the libraries features load only when used (pdfplumber, python-docx, Pillow) and a writable data folder, and writes the report to `self_test.txt` in the data folder (exit code 0 = all passed).

### Publishing a release

Push a version tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions (`.github/workflows/release.yml`) then runs the tests, builds the .exe on Windows, runs its self-test, and publishes a Release with `Upkeep-Setup-1.0.0.exe` and `Upkeep-1.0.0-portable.exe` attached. To try the build without releasing, run the **Build Windows app** workflow from the Actions tab — both files are then downloadable from that run.

Installed copies of Upkeep check the latest Release on every start (`files/updater.py`), so publishing a release is all it takes to update everyone. Use a higher version number each time; the tag is also the version the app reports.

