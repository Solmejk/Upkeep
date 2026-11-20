"""DeckEloBlock: a deck's Game Tracker Elo on its deck page — the Elo
chart (one point per game) with "Elo 1531 · 2 games · 100% win rate"
underneath, titled like the stats row's other charts. Clicking the line
opens the deck's Game Tracker popout. Shows a note instead when the deck
has no recorded games.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from card_fields import plural
from models import game_tracker as gt
from ui.components.player_modal import elo_color
from ui.components.value_chart import ValueChart

MUTED = "#888888"
WIDTH, CHART_HEIGHT = 300, 130


def tracker_stats_for(app, deck) -> tuple:
    """(tracker, DeckStats | None) for one of your decks (models.deck.Deck):
    your games where that deck was picked, or typed in by the same name."""
    tracker = gt.GameTracker()
    me = tracker.find_moxfield(app.username) if app.is_logged_in else None
    if me is None:
        return tracker, None
    name = deck.name.strip().lower()
    for s in tracker.player_decks(me.id):
        if (s.deck.deck_id and s.deck.deck_id == deck.deck_id) or \
                (not s.deck.deck_id and s.deck.name.strip().lower() == name):
            return tracker, s
    return tracker, None


class DeckEloBlock(QWidget):
    clicked = Signal(object)  # the deck's Game Tracker key — its popout

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(WIDTH)
        self._key = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._chart = ValueChart(title="Elo", money=False, by_index=True, empty_text="")
        self._chart.setFixedHeight(CHART_HEIGHT)
        layout.addWidget(self._chart)
        self._caption = QLabel()
        self._caption.setObjectName("settingsDescription")
        self._caption.setTextFormat(Qt.RichText)
        self._caption.setAlignment(Qt.AlignCenter)
        self._caption.setWordWrap(True)
        layout.addWidget(self._caption)

    def show_deck(self, app, deck):
        """Fills the block for a deck (models.deck.Deck). Returns its
        DeckStats (None without games) — the deck page puts the Elo in its
        title too."""
        tracker, stats = tracker_stats_for(app, deck)
        self._key = stats.key if stats else None
        if stats is None:
            self._chart.hide()
            self._caption.setText(f"<span style='color:{MUTED}'>No games with this deck in the "
                                  f"Game Tracker yet.</span>")
            self._caption.setCursor(Qt.ArrowCursor)
            self._caption.setToolTip("")
            return None
        self._chart.show()
        self._chart.setHistory(tracker.deck_elo_history(stats.key))
        self._caption.setText(
            f"Elo <b style='color:{elo_color(stats.elo)}'>{stats.elo:.0f}</b>"
            f" · {plural(stats.games, 'game')} · {stats.win_rate * 100:.0f}% win rate")
        self._caption.setCursor(Qt.PointingHandCursor)
        self._caption.setToolTip("Click for the deck's Game Tracker stats (nemesis, prey, pilots)")
        return stats

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._key is not None \
                and self._caption.geometry().contains(event.position().toPoint()):
            self.clicked.emit(self._key)
        super().mousePressEvent(event)
