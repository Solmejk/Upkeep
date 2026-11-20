"""PlayerModal: a Game Tracker player's popout (like the card popout) —
name, Elo / games / wins / win rate tiles, their Elo over time (the same
ValueChart as the collection value), their best deck (highest deck Elo)
and the rest of their decks. Opened by clicking a player's name on the
Game Tracker screen (MainWindow owns the one instance).
"""

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame

from card_fields import plural
from models import game_tracker as gt
from ui.components.overlay_modal import OverlayModal
from ui.components.value_chart import ValueChart
from ui import theme

CONTENT_WIDTH = 580
WIN_COLOR, LOSS_COLOR, TEXT, MUTED, ACCENT = theme.WIN, theme.LOSS, theme.TEXT, theme.MUTED, theme.ACCENT
MAX_OTHER_DECKS = 6


elo_color = theme.elo_color  # kept importable from here


class StatTile(QFrame):
    """A stat tile: big value, small label under it."""

    def __init__(self, label: str):
        super().__init__()
        self.setObjectName("settingsSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)
        self.value = QLabel()
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet("font-size: 20px; font-weight: bold; background: transparent;")
        layout.addWidget(self.value)
        caption = QLabel(label)
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        layout.addWidget(caption)

    def set(self, text: str, color: str = TEXT):
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold; background: transparent;")


class PlayerModal(OverlayModal):
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
        layout.addWidget(self._name)
        self._sub = QLabel()
        self._sub.setObjectName("settingsDescription")
        layout.addWidget(self._sub)

        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self._elo, self._games, self._wins, self._rate = (
            StatTile("Elo"), StatTile("Games"), StatTile("Wins"), StatTile("Win rate"))
        for tile in (self._elo, self._games, self._wins, self._rate):
            tiles.addWidget(tile)
        layout.addLayout(tiles)

        self._chart = ValueChart(title="Elo", money=False, by_index=True,  # one point per game
                                 empty_text="No games yet.")
        self._chart.setFixedHeight(190)
        layout.addWidget(self._chart)

        best_title = QLabel("Best deck")
        best_title.setObjectName("settingsSectionTitle")
        layout.addWidget(best_title)
        self._best = QLabel()
        self._best.setObjectName("settingsLabel")
        self._best.setWordWrap(True)
        self._best.setTextFormat(Qt.RichText)
        layout.addWidget(self._best)

        self._others_title = QLabel("Other decks")
        self._others_title.setObjectName("settingsDescription")
        layout.addWidget(self._others_title)
        self._others = QLabel()
        self._others.setObjectName("settingsLabel")
        self._others.setWordWrap(True)
        self._others.setTextFormat(Qt.RichText)
        layout.addWidget(self._others)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("backButton")
        close_btn.clicked.connect(self._dismiss)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        self._init_overlay(content)

    def show_player(self, tracker: gt.GameTracker, player_id: str, you: bool = False):
        """Fills the popout for one player and shows it. you: mark as "(you)"."""
        player = tracker.players[player_id]
        stats = next(s for s in tracker.player_stats() if s.player.id == player_id)

        self._name.setText(player.display_name + ("  (you)" if you else ""))
        if player.kind == gt.MOXFIELD:
            self._sub.setText(f"Moxfield: {player.username}" if player.nickname else "Moxfield player")
        else:
            self._sub.setText("Guest")

        self._elo.set(f"{stats.elo:.0f}", elo_color(stats.elo))
        self._games.set(str(stats.games))
        self._wins.set(str(stats.wins))
        self._rate.set(f"{stats.win_rate * 100:.0f}%" if stats.games else "–")
        self._chart.setHistory(tracker.player_elo_history(player_id))

        decks = tracker.player_decks(player_id)
        if decks:
            best = decks[0]
            self._best.setText(self._deck_html(best, tracker, big=True))
        else:
            self._best.setText(f"<span style='color:{MUTED}'>No games with their own decks yet.</span>")
        others = decks[1:MAX_OTHER_DECKS + 1]
        self._others_title.setVisible(bool(others))
        self._others.setVisible(bool(others))
        self._others.setText("<br>".join(self._deck_html(d, tracker) for d in others))
        if len(decks) > MAX_OTHER_DECKS + 1:
            self._others.setText(self._others.text()
                                 + f"<br><span style='color:{MUTED}'>+ {len(decks) - MAX_OTHER_DECKS - 1} more</span>")

        self._content.adjustSize()
        self._show_overlay()

    @staticmethod
    def _deck_html(s: gt.DeckStats, tracker: gt.GameTracker, big: bool = False) -> str:
        """One deck: name, Elo (colored), win rate and games — plus who else
        has played it."""
        name = html.escape(s.deck.name)
        name = f"<span style='font-size:15px'><b>{name}</b></span>" if big else name
        line = (f"{name} &nbsp; <span style='color:{elo_color(s.elo)}'><b>{s.elo:.0f}</b></span>"
                f" <span style='color:{MUTED}'>Elo · {s.win_rate * 100:.0f}% win rate · "
                f"{plural(s.games, 'game')}</span>")
        others = sorted(tracker.players[p].display_name for p in s.played_by if p != s.owner.id)
        if big and others:
            line += f"<br><span style='color:{MUTED}'>Also played by {html.escape(', '.join(others))}</span>"
        return line
