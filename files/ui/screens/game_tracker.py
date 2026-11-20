"""GameTrackerScreen: record games and see results. Left: every game,
newest first (click to edit, right-click to edit / delete). Right: the
Players table (games, wins, win %, Elo) and the Decks table (owner,
games, win %, Elo — borrowed games count for the owner's deck), both
sortable by clicking a header. Clicking a player's name (tables or
games) opens their popout (player_clicked -> MainWindow's PlayerModal);
clicking a deck in the Decks table opens its popout (deck_clicked ->
TrackerDeckModal).
Data: models.game_tracker; dialogs:
ui.components.game_dialog (record / edit) and players_dialog (manage
players).
"""

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QScrollArea, QFrame, QMenu, QMessageBox, QAbstractItemView,
)

from card_fields import plural
from models import game_tracker as gt
from ui.components.game_dialog import GameDialog
from ui.components.players_dialog import PlayersDialog

WIN_COLOR = "#4caf50"   # same green as elsewhere
LOSS_COLOR = "#d9534f"  # same red as elsewhere
MUTED = "#888888"
TEXT = "#e8e8e8"
GAMES_COLUMN_WIDTH = 440
TABLE_MAX_ROWS = 12  # taller tables scroll
PLAYER_ID_ROLE = Qt.UserRole + 1  # table cells naming a player carry their id
DECK_KEY_ROLE = Qt.UserRole + 2   # Decks table name cells carry the deck's key
NAME_COLUMN_MIN = 170  # player / deck names: at least this wide, else as wide as the longest…
NAME_COLUMN_MAX = 340  # …up to this; longer names end in "…" (the full name is in the tooltip)


class _NameLabel(QLabel):
    """A clickable player name in the games log. Keeps the click to itself
    (accepts it), so the game card underneath doesn't also open its editor."""

    def __init__(self, text: str, color: str, bold: bool, on_click):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click for their stats")
        weight = "bold" if bold else "normal"
        self.setStyleSheet(f"QLabel {{ color: {color}; font-weight: {weight}; background: transparent; }}"
                           f"QLabel:hover {{ text-decoration: underline; }}")
        self._on_click = on_click

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self._on_click()
        else:
            super().mousePressEvent(event)


class _GameRow(QFrame):
    """One game in the list: date, then one line per seat (winner in
    green with a ✓)."""

    def __init__(self, screen, game: gt.Game):
        super().__init__()
        self.setObjectName("settingsSection")
        self.setCursor(Qt.PointingHandCursor)
        self._screen, self._game = screen, game
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        players = screen.tracker.players
        head = f"<b>{html.escape(game.date)}</b>  <span style='color:{MUTED}'>· {plural(len(game.seats), 'player')}"
        head += " · no winner" if game.winner_id is None else ""
        head += "</span>"
        top = QLabel(head)
        top.setObjectName("settingsLabel")
        top.setWordWrap(True)  # never wider than the (narrow) games column
        layout.addWidget(top)

        # one line per seat — fits the narrow column better than one long line.
        # Names (and a borrowed deck's owner) are clickable: that player's
        # popout. Clicking anywhere else on the card edits the game.
        def open_player(player_id):
            return lambda: screen.player_clicked.emit(player_id)

        for seat in game.seats:
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(4)
            won = seat.player_id == game.winner_id
            label = screen.player_label(players[seat.player_id])
            if won:
                line.addWidget(_NameLabel("✓ " + label, WIN_COLOR, True, open_player(seat.player_id)))
            else:
                line.addSpacing(16)  # lines up with the winner's name after its ✓
                line.addWidget(_NameLabel(label, TEXT, False, open_player(seat.player_id)))
            deck = QLabel(f"— {seat.deck.name}" + (" ·" if seat.borrowed else ""))
            deck.setStyleSheet(f"color: {MUTED}; background: transparent;")
            line.addWidget(deck)
            if seat.borrowed:  # e.g. "— Edgar Markov · Solmejk's"
                owner = players[seat.owner_id].display_name + "'s"
                line.addWidget(_NameLabel(owner, MUTED, False, open_player(seat.owner_id)))
            line.addStretch()
            layout.addLayout(line)
        if game.notes:
            notes = QLabel(html.escape(game.notes))
            notes.setObjectName("settingsDescription")
            notes.setWordWrap(True)
            layout.addWidget(notes)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._screen.edit_game(self._game.id)
        elif event.button() == Qt.RightButton:
            self._screen.game_menu(self._game.id, event.globalPosition().toPoint())


class _SortItem(QTableWidgetItem):
    """A cell that sorts by its Qt.UserRole value — numbers as numbers
    ("67%" by 0.67), names case-insensitively."""

    def __lt__(self, other):
        a, b = self.data(Qt.UserRole), other.data(Qt.UserRole)
        if a is not None and b is not None and type(a) is type(b):
            return a < b
        return super().__lt__(other)


def _cell(text: str, sort_value, color: str = TEXT, align=Qt.AlignCenter, tooltip: str = "") -> _SortItem:
    item = _SortItem(text)
    item.setData(Qt.UserRole, sort_value)
    item.setTextAlignment(align | Qt.AlignVCenter)
    item.setForeground(QColor(color))
    if tooltip:
        item.setToolTip(tooltip)
    return item


def _name_cell(text: str, color: str = TEXT, tooltip: str = "") -> _SortItem:
    return _cell(text, text.lower(), color, Qt.AlignLeft, tooltip)


def _elo_color(elo: float) -> str:
    """Above / below the 1500 start in green / red."""
    if elo >= gt.ELO_START + 0.5:
        return WIN_COLOR
    if elo <= gt.ELO_START - 0.5:
        return LOSS_COLOR
    return TEXT


def _stats_table(headers: list) -> QTableWidget:
    """A themed, read-only, sortable stats table (style: QTableWidget#statsTable),
    sized to its columns (see GameTrackerScreen._fill_table)."""
    table = QTableWidget(0, len(headers))
    table.setObjectName("statsTable")
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.setFocusPolicy(Qt.NoFocus)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setDefaultAlignment(Qt.AlignCenter)
    header.setSectionResizeMode(QHeaderView.Fixed)  # widths set in _fill_table / _match_widths
    header.setMinimumSectionSize(48)
    header.setStretchLastSection(False)
    return table


class GameTrackerScreen(QWidget):
    player_clicked = Signal(str)  # a player's name was clicked (their id)
    deck_clicked = Signal(object)  # a deck in the Decks table was clicked (its DeckStats.key)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.tracker = gt.GameTracker()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Game Tracker")
        title.setObjectName("screenTitle")
        header.addWidget(title)
        header.addStretch()
        players_btn = QPushButton("Players…")
        players_btn.setObjectName("backButton")
        players_btn.clicked.connect(self._open_players)
        header.addWidget(players_btn)
        record_btn = QPushButton("Record game")
        record_btn.clicked.connect(self._record_game)
        header.addWidget(record_btn)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(28)

        # Left: the games log (narrow)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        self._games_title = QLabel("Games")
        self._games_title.setObjectName("settingsSectionTitle")
        left.addWidget(self._games_title)
        scroll = QScrollArea()
        scroll.setObjectName("decksScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self._games_layout = QVBoxLayout(container)
        self._games_layout.setContentsMargins(0, 0, 8, 0)
        self._games_layout.setSpacing(8)
        scroll.setWidget(container)
        left.addWidget(scroll, 1)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setFixedWidth(GAMES_COLUMN_WIDTH)
        body.addWidget(left_box)

        # Right: the stats tables
        right = QVBoxLayout()
        right.setSpacing(10)
        players_title = QLabel("Players")
        players_title.setObjectName("settingsSectionTitle")
        right.addWidget(players_title)
        self._players_table = _stats_table(["#", "Player", "Games", "Wins", "Win %", "Elo"])
        self._players_table.cellClicked.connect(lambda r, c: self._on_cell_clicked(self._players_table, r, c))
        right.addWidget(self._players_table, alignment=Qt.AlignLeft)  # spare width stays empty

        right.addSpacing(14)
        decks_title = QLabel("Decks")
        decks_title.setObjectName("settingsSectionTitle")
        right.addWidget(decks_title)
        self._decks_table = _stats_table(["#", "Deck", "Owner", "Games", "Win %", "Elo"])
        self._decks_table.cellClicked.connect(lambda r, c: self._on_cell_clicked(self._decks_table, r, c))
        right.addWidget(self._decks_table, alignment=Qt.AlignLeft)
        self._no_stats = QLabel("The tables fill in once games are recorded.")
        self._no_stats.setObjectName("settingsDescription")
        right.addWidget(self._no_stats)
        right.addStretch()
        body.addLayout(right, 1)

        outer.addLayout(body, 1)
        self.reload()

    # --------------------------------------------------------- display
    def player_label(self, player: gt.Player) -> str:
        you = (self.app.is_logged_in and player.kind == gt.MOXFIELD
               and player.username.lower() == self.app.username.lower())
        return f"{player.display_name} (you)" if you else player.display_name

    def showEvent(self, event):
        """Re-reads from disk each time the tab opens (cheap, keeps it fresh)."""
        super().showEvent(event)
        self.reload()

    def reload(self):
        self.tracker = gt.GameTracker()
        self._fill_players()
        self._fill_decks()
        self._match_widths()

        while self._games_layout.count():
            item = self._games_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        games = self.tracker.games_sorted()
        self._games_title.setText(f"Games ({len(games)})" if games else "Games")
        if not games:
            empty = QLabel("No games yet — click Record game to add the first one.")
            empty.setObjectName("settingsDescription")
            empty.setWordWrap(True)
            self._games_layout.addWidget(empty)
        for game in games:
            self._games_layout.addWidget(_GameRow(self, game))
        self._games_layout.addStretch()

        has_stats = bool(games)
        for w in (self._players_table, self._decks_table):
            w.setVisible(has_stats)
        self._no_stats.setVisible(not has_stats)

    def _fill_table(self, table: QTableWidget, rows: list):
        """rows: [[cell per column after "#"]], in rank order. The table is
        as tall as its rows (scrolls past TABLE_MAX_ROWS) and as wide as its
        columns — _match_widths then evens the two tables out."""
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, cells in enumerate(rows):
            table.setItem(r, 0, _cell(str(r + 1), r + 1, MUTED))
            for c, item in enumerate(cells, start=1):
                table.setItem(r, c, item)
        table.setSortingEnabled(True)
        table.sortItems(0, Qt.AscendingOrder)  # rank order (also resets an earlier click-sort)
        visible = min(len(rows), TABLE_MAX_ROWS)
        table.setFixedHeight(table.horizontalHeader().sizeHint().height()
                             + visible * table.verticalHeader().defaultSectionSize() + 4)
        # as wide as its columns (name column at least NAME_COLUMN_MIN) — not the whole screen
        table.resizeColumnsToContents()
        table.setColumnWidth(1, max(NAME_COLUMN_MIN, min(table.columnWidth(1), NAME_COLUMN_MAX)))
        table.setFixedWidth(self._natural_width(table))

    @staticmethod
    def _natural_width(table: QTableWidget) -> int:
        width = sum(table.columnWidth(c) for c in range(table.columnCount())) + 2 * table.frameWidth()
        if table.rowCount() > TABLE_MAX_ROWS:
            width += table.verticalScrollBar().sizeHint().width()
        return width

    def _match_widths(self):
        """Both tables as wide as the wider one (usually Decks, with its
        Owner column); the narrower one's name column takes the difference
        — so they line up, and both grow when a long name appears."""
        tables = (self._players_table, self._decks_table)
        widths = [self._natural_width(t) for t in tables]
        target = max(widths)
        for table, width in zip(tables, widths):
            if width < target:
                table.setColumnWidth(1, table.columnWidth(1) + target - width)
            table.setFixedWidth(target)

    def _on_cell_clicked(self, table: QTableWidget, row: int, col: int):
        """A player's name (Players table) or a deck's owner (Decks table):
        that player's popout. A deck's name: that deck's popout."""
        item = table.item(row, col)
        if item is None:
            return
        if item.data(PLAYER_ID_ROLE):
            self.player_clicked.emit(item.data(PLAYER_ID_ROLE))
        elif item.data(DECK_KEY_ROLE):
            self.deck_clicked.emit(tuple(item.data(DECK_KEY_ROLE)))

    @staticmethod
    def _player_cell(item: QTableWidgetItem, player_id: str) -> QTableWidgetItem:
        item.setData(PLAYER_ID_ROLE, player_id)
        item.setToolTip((item.toolTip() + " — " if item.toolTip() else "") + "click for their stats")
        return item

    def _fill_players(self):
        rows = []
        for s in (s for s in self.tracker.player_stats() if s.games):
            rows.append([
                self._player_cell(_name_cell(self.player_label(s.player), tooltip=s.player.full_name),
                                  s.player.id),
                _cell(str(s.games), s.games),
                _cell(str(s.wins), s.wins),
                _cell(f"{s.win_rate * 100:.0f}%", s.win_rate),
                _cell(f"{s.elo:.0f}", s.elo, _elo_color(s.elo)),
            ])
        self._fill_table(self._players_table, rows)

    def _fill_decks(self):
        rows = []
        for s in self.tracker.deck_stats():
            others = sorted(self.tracker.players[p].display_name for p in s.played_by if p != s.owner.id)
            tip = s.deck.name + (f" — also played by {', '.join(others)}" if others else "")
            deck_cell = _name_cell(s.deck.name, tooltip=tip + " — click for its stats")
            deck_cell.setData(DECK_KEY_ROLE, list(s.key))
            rows.append([
                deck_cell,
                self._player_cell(_name_cell(self.player_label(s.owner), color=MUTED), s.owner.id),
                _cell(str(s.games), s.games),
                _cell(f"{s.win_rate * 100:.0f}%", s.win_rate),
                _cell(f"{s.elo:.0f}", s.elo, _elo_color(s.elo)),
            ])
        self._fill_table(self._decks_table, rows)

    # --------------------------------------------------------- actions
    def _record_game(self):
        if GameDialog(self, self.app, self.tracker).exec():
            self.reload()

    def edit_game(self, game_id: str):
        if GameDialog(self, self.app, self.tracker, self.tracker.game(game_id)).exec():
            self.reload()

    def game_menu(self, game_id: str, pos):
        menu = QMenu(self)
        edit = menu.addAction("Edit game…")
        delete = menu.addAction("Delete game")
        picked = menu.exec(pos)
        if picked is edit:
            self.edit_game(game_id)
        elif picked is delete:
            game = self.tracker.game(game_id)
            if QMessageBox.question(self, "Delete game", f"Delete the game from {game.date}?") == QMessageBox.Yes:
                self.tracker.delete_game(game_id)
                self.reload()

    def _open_players(self):
        PlayersDialog(self, self.app, self.tracker).exec()
        self.reload()
