"""TrackerDeckModal: a Game Tracker deck's popout (like the player
popout) — Elo / games / wins / win rate tiles, its Elo over time (one
point per game), its nemesis (the deck that has beaten it most), its prey
(the deck it has beaten most) and who has piloted it. Opened by clicking
a deck name in the Game Tracker's Decks table (MainWindow owns the one
instance).
"""

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame

from card_fields import plural
from models import game_tracker as gt
from ui.components.overlay_modal import OverlayModal
from ui.components.player_modal import StatTile
from ui.theme import elo_color, MUTED, WIN as WIN_COLOR, LOSS as LOSS_COLOR
from ui.components.value_chart import ValueChart

CONTENT_WIDTH = 580


def nemesis(matchups: list):
    """The deck that has beaten this one most (ties: the worse record for
    us), or None if no deck has beaten it."""
    lost_to = [m for m in matchups if m["losses"]]
    return max(lost_to, key=lambda m: (m["losses"], -m["wins"]), default=None)


def prey(matchups: list):
    """The deck this one has beaten most (ties: the better record for us),
    or None if it hasn't beaten any."""
    beaten = [m for m in matchups if m["wins"]]
    return max(beaten, key=lambda m: (m["wins"], -m["losses"]), default=None)


class _RivalCard(QFrame):
    """Nemesis / prey: a title, the deck + owner, and the head-to-head."""

    def __init__(self, title: str, color: str, tooltip: str):
        super().__init__()
        self.setObjectName("settingsSection")
        self.setToolTip(tooltip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        heading = QLabel(title)
        heading.setStyleSheet(f"color: {color}; font-weight: bold; background: transparent;")
        layout.addWidget(heading)
        self._body = QLabel()
        self._body.setObjectName("settingsLabel")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.RichText)
        layout.addWidget(self._body)

    def set_matchup(self, m: dict | None, none_text: str):
        if m is None:
            self._body.setText(f"<span style='color:{MUTED}'>{none_text}</span>")
            return
        self._body.setText(
            f"<b>{html.escape(m['deck'].name)}</b><br>"
            f"<span style='color:{MUTED}'>{html.escape(m['owner'].display_name)}'s deck<br>"
            f"Record against it: {m['wins']}–{m['losses']}</span>")


class TrackerDeckModal(OverlayModal):
    def __init__(self, parent=None):
        super().__init__(parent)
        content = QWidget()
        content.setObjectName("cardModalContent")
        content.setFixedWidth(CONTENT_WIDTH)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(12)

        self._name = QLabel()
        self._name.setObjectName("screenTitle")
        self._name.setWordWrap(True)
        layout.addWidget(self._name)
        self._sub = QLabel()
        self._sub.setObjectName("settingsDescription")
        self._sub.setWordWrap(True)
        layout.addWidget(self._sub)

        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self._elo, self._games, self._wins, self._rate = (
            StatTile("Elo"), StatTile("Games"), StatTile("Wins"), StatTile("Win rate"))
        for tile in (self._elo, self._games, self._wins, self._rate):
            tiles.addWidget(tile)
        layout.addLayout(tiles)

        self._chart = ValueChart(title="Elo", money=False, by_index=True, empty_text="No games yet.")
        self._chart.setFixedHeight(190)
        layout.addWidget(self._chart)

        rivals = QHBoxLayout()
        rivals.setSpacing(8)
        self._nemesis = _RivalCard("Nemesis", LOSS_COLOR, "The deck that has beaten this deck the most")
        self._prey = _RivalCard("Prey", WIN_COLOR, "The deck this deck has beaten the most")
        rivals.addWidget(self._nemesis)
        rivals.addWidget(self._prey)
        layout.addLayout(rivals)

        pilots_title = QLabel("Pilots")
        pilots_title.setObjectName("settingsSectionTitle")
        layout.addWidget(pilots_title)
        self._pilots = QLabel()
        self._pilots.setObjectName("settingsLabel")
        self._pilots.setWordWrap(True)
        self._pilots.setTextFormat(Qt.RichText)
        layout.addWidget(self._pilots)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("backButton")
        close_btn.clicked.connect(self._dismiss)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        self._init_overlay(content)

    def show_deck(self, tracker: gt.GameTracker, deck_key: tuple, player_label=None):
        """Fills the popout for one deck (deck_key: DeckStats.key) and shows
        it. player_label(player) -> str: how to name players (e.g. "(you)")."""
        label = player_label or (lambda p: p.display_name)
        stats = next(s for s in tracker.deck_stats() if s.key == deck_key)

        self._name.setText(stats.deck.name)
        sub = f"{label(stats.owner)}'s deck"
        if stats.deck.commander and stats.deck.commander != stats.deck.name:
            sub += f" · {stats.deck.commander}"
        self._sub.setText(sub)

        self._elo.set(f"{stats.elo:.0f}", elo_color(stats.elo))
        self._games.set(str(stats.games))
        self._wins.set(str(stats.wins))
        self._rate.set(f"{stats.win_rate * 100:.0f}%" if stats.games else "–")
        self._chart.setHistory(tracker.deck_elo_history(deck_key))

        matchups = tracker.deck_matchups(deck_key)
        self._nemesis.set_matchup(nemesis(matchups), "No deck has beaten it yet.")
        self._prey.set_matchup(prey(matchups), "It hasn't beaten a deck yet.")

        lines = []
        for player, games, wins in tracker.deck_pilots(deck_key):
            borrowed = "" if player.id == stats.owner.id else f" <span style='color:{MUTED}'>(borrowed)</span>"
            lines.append(f"{html.escape(label(player))}{borrowed} — "
                         f"<span style='color:{MUTED}'>{plural(games, 'game')}, {plural(wins, 'win')}, "
                         f"{wins / games * 100:.0f}% win rate</span>")
        self._pilots.setText("<br>".join(lines))

        self._content.adjustSize()
        self._show_overlay()
