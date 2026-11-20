"""HomeScreen: the app's landing page — a welcome message, your Game
Tracker summary (Elo, best deck with its commander's art) and the
showcases. (Collection numbers live on the Collection screen; the full
Moxfield refresh on Settings: Sync → Refresh all.)
"""

import html
from urllib.parse import quote

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame

import scryfall
from app import MTGApp
from card_fields import plural
from models import game_tracker as gt
from ui.components.image_tile import ImageTile
from ui.components.player_modal import elo_color
from ui.components.showcase_panel import ShowcasePanel

MUTED = "#888888"
ART_W, ART_H = 120, 168
# a card image by (fuzzy) name — for decks typed in by name, without a commander on file
NAMED_IMAGE_URL = "https://api.scryfall.com/cards/named?format=image&version=normal&fuzzy={}"


class _Clickable(QLabel):
    """A label that calls on_click on a left click (and keeps the click)."""

    def __init__(self, on_click):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self._on_click()
        else:
            super().mousePressEvent(event)


class _TrackerCard(QFrame):
    """Your Game Tracker summary: commander art of your best deck, your Elo
    and record, and that deck's stats. Re-read with refresh()."""

    def __init__(self, home):
        super().__init__()
        self.setObjectName("settingsSection")
        self._home = home
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(18, 16, 18, 16)
        self._layout.setSpacing(20)

    def refresh(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        app = self._home.app
        tracker = gt.GameTracker()
        me = tracker.find_moxfield(app.username) if app.is_logged_in else None
        stats = next((s for s in tracker.player_stats() if me and s.player.id == me.id), None)
        if stats is None or not stats.games:
            note = QLabel("Record games in the Game Tracker to see your Elo and best deck here.")
            note.setObjectName("settingsDescription")
            note.setWordWrap(True)
            self._layout.addWidget(note)
            return

        decks = tracker.player_decks(me.id)
        best = decks[0] if decks else None
        if best is not None:
            url, cache_name = self._commander_art(best)
            art = ImageTile(url, cache_name, "", best.key, width=ART_W, height=ART_H, radius=8)
            for caption in art.findChildren(QLabel, "imageTileCaption"):
                caption.hide()
            art.setToolTip("Click for the deck's stats")
            art.clicked.connect(lambda key: self._home.deck_clicked.emit(key))
            art.request_image_load()
            self._layout.addWidget(art)

        text = QVBoxLayout()
        text.setSpacing(4)
        heading = QLabel("Game Tracker")
        heading.setObjectName("settingsSectionTitle")
        text.addWidget(heading)

        elo = _Clickable(lambda: self._home.player_clicked.emit(me.id))
        elo.setTextFormat(Qt.RichText)
        elo.setText(f"<span style='font-size:30px; font-weight:bold; color:{elo_color(stats.elo)}'>"
                    f"{stats.elo:.0f}</span> <span style='color:{MUTED}'>Elo</span>")
        elo.setToolTip("Click for your stats and Elo chart")
        text.addWidget(elo)
        record = QLabel(f"{plural(stats.games, 'game')} · {plural(stats.wins, 'win')} · "
                        f"{stats.win_rate * 100:.0f}% win rate")
        record.setObjectName("settingsDescription")
        text.addWidget(record)

        if best is not None:
            text.addSpacing(8)
            deck = _Clickable(lambda: self._home.deck_clicked.emit(best.key))
            deck.setTextFormat(Qt.RichText)
            deck.setWordWrap(True)
            deck.setText(
                f"<span style='color:{MUTED}'>Best deck</span><br>"
                f"<b style='font-size:15px'>{html.escape(best.deck.name)}</b><br>"
                f"<span style='color:{elo_color(best.elo)}'><b>{best.elo:.0f}</b></span>"
                f"<span style='color:{MUTED}'> Elo · {best.win_rate * 100:.0f}% win rate · "
                f"{plural(best.games, 'game')}</span>")
            deck.setToolTip("Click for the deck's stats")
            text.addWidget(deck)
        text.addStretch()
        self._layout.addLayout(text, 1)

    def _commander_art(self, best: gt.DeckStats) -> tuple:
        """(image url, cache name) for the deck's commander: from your deck
        (Moxfield or Deck Maker) when it's one of yours, else Scryfall by
        the commander's / deck's name."""
        deck = next((d for d in self._home.app.decks if best.deck.deck_id and d.deck_id == best.deck.deck_id), None)
        if deck is not None:
            if not deck.commanders:
                deck.load()  # cache read — the commander isn't in the deck list stub
            if deck.commanders and deck.commanders[0].get("image_url"):
                commander = deck.commanders[0]
                return commander["image_url"], scryfall.card_image_cache_name(commander)
        name = best.deck.commander or best.deck.name
        return NAMED_IMAGE_URL.format(quote(name)), f"named_{name.lower().replace(' ', '_')}"


class HomeScreen(QWidget):
    card_clicked = Signal(dict)  # a showcase card was clicked — card info popout payload
    player_clicked = Signal(str)  # your Elo was clicked (your player id) — player popout
    deck_clicked = Signal(object)  # your best deck was clicked (its key) — deck popout

    def __init__(self, app: MTGApp):
        """Builds and populates the screen from `app`'s current state —
        rebuilt from scratch (not updated in place) whenever the
        underlying data changes, see MainWindow._rebuild_data_screens.
        The Game Tracker card re-reads its data each time Home is shown."""
        super().__init__()
        self.app = app

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        welcome_text = f"Welcome, {app.username}" if app.is_logged_in else "Welcome"
        title = QLabel(welcome_text)
        title.setObjectName("homeTitle")
        layout.addWidget(title)

        if not app.is_logged_in:
            hint = QLabel("Log in via the avatar in the sidebar to load your collection.")
            hint.setObjectName("homeHint")
            layout.addWidget(hint)

        self._tracker_card = _TrackerCard(self)
        self._tracker_card.setMaximumWidth(560)
        layout.addWidget(self._tracker_card)

        # Showcases: the user's own picks from the collection
        layout.addSpacing(12)
        self.showcases = ShowcasePanel(app)
        self.showcases.card_clicked.connect(self.card_clicked.emit)
        layout.addWidget(self.showcases, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self._tracker_card.refresh()  # picks up games recorded since
