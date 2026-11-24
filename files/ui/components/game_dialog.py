"""GameDialog: record a new game, or edit one (Game Tracker screen).

One row per seat — player, whose deck it is ("Own deck", or the player
it was borrowed from), deck, winner button — plus the date and notes. Players are picked from the tracker's players, or made on the spot
("New guest…" / "Moxfield player…"). The deck box suggests decks for the
deck's owner — your own active (Moxfield) decks for you, a
Moxfield player's public decks (fetched in the background, once per
session), a guest's earlier decks — and also takes any typed-in name.
"""

import sys

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QPushButton,
    QRadioButton, QButtonGroup, QDateEdit, QLineEdit, QInputDialog, QMessageBox, QWidget,
)

from models import game_tracker as gt
from ui.background import run_in_background

NEW_GUEST, NEW_MOXFIELD = "__new_guest__", "__new_moxfield__"
NO_WINNER_ID = -1
DEFAULT_SEATS = 4  # a new game starts as a typical Commander pod

# Moxfield players' public decks, per username (lower case) — fetched once
# per app session and shared by every dialog.
_moxfield_decks_cache: dict[str, list] = {}  # username -> DeckRefs ([] if fetching failed), this session


def _fetch_decks(username: str):
    """Background job: (username, their Moxfield decks), or (username,
    None) if Moxfield can't be reached — logged, never raised, so the
    dialog can remember the failure for this player."""
    try:
        return username, gt.fetch_moxfield_decks(username)
    except Exception as e:
        print(f"Game Tracker: couldn't fetch {username}'s Moxfield decks ({e}) — "
              "suggesting their decks from earlier games only", file=sys.stderr)
        return username, None


class _SeatRow:
    """The widgets of one seat (they live in the dialog's grid)."""

    def __init__(self, player: QComboBox, owner: QComboBox, deck: QComboBox,
                 winner: QRadioButton, remove: QPushButton):
        self.player, self.owner, self.deck, self.winner, self.remove = player, owner, deck, winner, remove

    def widgets(self):
        return (self.player, self.owner, self.deck, self.winner, self.remove)


class GameDialog(QDialog):
    def __init__(self, parent, app, tracker: gt.GameTracker, game: gt.Game | None = None):
        """game: the game to edit, or None to record a new one."""
        super().__init__(parent)
        self.app = app
        self.tracker = tracker
        self._game = game
        self._rows: list[_SeatRow] = []
        self._bg_tasks = []  # keeps background tasks alive — see ui/background.py
        self._fetching = set()
        self.setWindowTitle("Edit game" if game else "Record game")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        date_row = QHBoxLayout()
        date_label = QLabel("Date")
        date_label.setObjectName("settingsLabel")
        date_row.addWidget(date_label)
        self._date = QDateEdit(calendarPopup=True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        self._date.setDate(QDate.fromString(game.date, "yyyy-MM-dd") if game else QDate.currentDate())
        date_row.addWidget(self._date)
        date_row.addStretch()
        layout.addLayout(date_row)

        # Seats: header + one row each
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(8)
        for col, text in enumerate(("Player", "Deck from", "Deck", "Winner")):
            label = QLabel(text)
            label.setObjectName("settingsDescription")
            self._grid.addWidget(label, 0, col)
        self._grid.setColumnStretch(0, 2)
        self._grid.setColumnStretch(1, 2)
        self._grid.setColumnStretch(2, 3)
        grid_box = QWidget()
        grid_box.setLayout(self._grid)
        layout.addWidget(grid_box)

        self._winner_group = QButtonGroup(self)
        add_row = QHBoxLayout()
        self._add_btn = QPushButton("+ Add player")
        self._add_btn.setObjectName("backButton")
        self._add_btn.clicked.connect(lambda: self._add_seat())
        add_row.addWidget(self._add_btn)
        add_row.addStretch()
        self._no_winner = QRadioButton("No winner (draw / unfinished)")
        self._winner_group.addButton(self._no_winner, NO_WINNER_ID)
        add_row.addWidget(self._no_winner)
        layout.addLayout(add_row)

        notes_label = QLabel("Notes")
        notes_label.setObjectName("settingsLabel")
        layout.addWidget(notes_label)
        self._notes = QLineEdit(game.notes if game else "")
        self._notes.setObjectName("searchInput")
        self._notes.setPlaceholderText("Optional — e.g. turn count, how it was won")
        layout.addWidget(self._notes)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("backButton")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        save_btn = QPushButton("Save game")
        save_btn.clicked.connect(self._on_save)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

        # Fill in the seats
        if game:
            for seat in game.seats:
                self._add_seat(seat.player_id, seat.deck, seat.deck_owner_id)
            winner_row = next((i for i, s in enumerate(game.seats) if s.player_id == game.winner_id), None)
            (self._rows[winner_row].winner if winner_row is not None else self._no_winner).setChecked(True)
        else:
            me = self._me()
            self._add_seat(me.id if me else None)
            for _ in range(DEFAULT_SEATS - 1):
                self._add_seat()
            self._no_winner.setChecked(True)

    # ------------------------------------------------------------ players
    def _me(self) -> gt.Player | None:
        """You, as a player (made on first use) — None when logged out."""
        return self.tracker.add_moxfield(self.app.username) if self.app.is_logged_in else None

    def _player_label(self, player: gt.Player) -> str:
        if self.app.is_me(player):
            return f"{player.full_name} (you)"
        return player.full_name if player.kind == gt.MOXFIELD else f"{player.display_name} · guest"

    def _fill_players(self, combo: QComboBox, selected_id: str | None):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Choose a player…", None)
        for player in self.tracker.players_sorted():
            combo.addItem(self._player_label(player), player.id)
        combo.addItem("+ New guest…", NEW_GUEST)
        combo.addItem("+ Moxfield player…", NEW_MOXFIELD)
        index = combo.findData(selected_id) if selected_id else 0
        combo.setCurrentIndex(max(index, 0))
        combo.blockSignals(False)

    def _fill_owners(self, combo: QComboBox, selected_id: str = ""):
        """"Own deck", then every player (whose deck was borrowed)."""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Own deck", "")
        for player in self.tracker.players_sorted():
            combo.addItem(self._player_label(player), player.id)
        combo.setCurrentIndex(max(combo.findData(selected_id or ""), 0))
        combo.blockSignals(False)

    def _place_row(self, row: _SeatRow, r: int):
        """Puts a seat's widgets on grid row r."""
        for col, w in enumerate(row.widgets()):
            self._grid.addWidget(w, r, col, alignment=Qt.AlignCenter if col == 3 else Qt.Alignment())

    def _add_seat(self, player_id: str | None = None, deck: gt.DeckRef | None = None, owner_id: str = ""):
        if len(self._rows) >= gt.MAX_PLAYERS:
            return
        player = QComboBox()
        owner = QComboBox()
        owner.setToolTip("Whose deck — pick the player you borrowed it from")
        deck_box = QComboBox()
        deck_box.setEditable(True)
        deck_box.setInsertPolicy(QComboBox.NoInsert)
        deck_box.lineEdit().setPlaceholderText("Deck name")
        winner = QRadioButton()
        winner.setToolTip("This player won")
        remove = QPushButton("✕")
        remove.setObjectName("backButton")
        remove.setFixedWidth(34)
        remove.setToolTip("Remove this seat")
        row = _SeatRow(player, owner, deck_box, winner, remove)
        self._rows.append(row)
        self._winner_group.addButton(winner)
        self._place_row(row, len(self._rows))

        self._fill_players(player, player_id)
        self._fill_owners(owner, owner_id)
        player.currentIndexChanged.connect(lambda _i, row=row: self._on_player_changed(row))
        # another owner = another set of decks: start the deck over
        owner.currentIndexChanged.connect(lambda _i, row=row: self._fill_decks(row, keep=gt.DeckRef("")))
        remove.clicked.connect(lambda _c=False, row=row: self._remove_seat(row))
        self._fill_decks(row, keep=deck)
        self._update_buttons()

    def _remove_seat(self, row: _SeatRow):
        if len(self._rows) <= gt.MIN_PLAYERS:
            return
        was_winner = row.winner.isChecked()
        for w in row.widgets():
            self._grid.removeWidget(w)
            w.deleteLater()
        self._winner_group.removeButton(row.winner)
        self._rows.remove(row)
        for i, other in enumerate(self._rows, start=1):  # close the gap
            self._place_row(other, i)
        if was_winner:
            self._no_winner.setChecked(True)
        self._update_buttons()

    def _update_buttons(self):
        self._add_btn.setEnabled(len(self._rows) < gt.MAX_PLAYERS)
        for row in self._rows:
            row.remove.setEnabled(len(self._rows) > gt.MIN_PLAYERS)

    def _on_player_changed(self, row: _SeatRow):
        """Handles the "New guest…" / "Moxfield player…" entries, then
        refreshes the row's deck suggestions."""
        choice = row.player.currentData()
        if choice in (NEW_GUEST, NEW_MOXFIELD):
            new_id = None
            if choice == NEW_GUEST:
                name, ok = QInputDialog.getText(self, "New guest", "Guest's name:")
                if ok:
                    try:
                        new_id = self.tracker.add_guest(name).id
                    except gt.GameTrackerError as e:
                        existing = self.tracker.find_guest(name)
                        if existing:
                            new_id = existing.id  # just use the existing guest
                        else:
                            QMessageBox.warning(self, "New guest", str(e))
            else:
                name, ok = QInputDialog.getText(self, "Moxfield player", "Moxfield username:")
                if ok:
                    try:
                        new_id = self.tracker.add_moxfield(name).id
                    except gt.GameTrackerError as e:
                        QMessageBox.warning(self, "Moxfield player", str(e))
            for other in self._rows:  # the new player shows up in every row's lists
                current = other.player.currentData() if other is not row else new_id
                self._fill_players(other.player, current if current not in (NEW_GUEST, NEW_MOXFIELD) else None)
                self._fill_owners(other.owner, other.owner.currentData() or "")
        self._fill_decks(row)

    # -------------------------------------------------------------- decks
    def _deck_suggestions(self, player: gt.Player | None) -> list:
        """DeckRefs to offer for a player (see the module docstring)."""
        if player is None:
            return []
        is_me = self.app.is_me(player)
        # your decks: just the active ones (an archived deck of an edited
        # game is still kept — see _fill_decks); others: what they've played
        decks = [] if is_me else list(self.tracker.decks_owned_by(player.id))
        if is_me:
            for deck in sorted((d for d in self.app.decks if d.active), key=lambda d: d.name.lower()):
                commander = deck.commanders[0]["name"] if deck.commanders else ""
                decks.append(gt.DeckRef(deck.name, gt.DECK_MOXFIELD, deck.deck_id, commander))
        elif player.kind == gt.MOXFIELD:
            key = player.username.lower()
            if key in _moxfield_decks_cache:
                decks += _moxfield_decks_cache[key]
            elif key not in self._fetching:
                self._fetching.add(key)
                run_in_background(lambda u=player.username: _fetch_decks(u),
                                  self._bg_tasks, on_finished=self._on_moxfield_decks)
        unique, seen = [], set()
        for d in decks:
            if d.key not in seen:
                seen.add(d.key)
                unique.append(d)
        return unique

    def _fill_decks(self, row: _SeatRow, keep: gt.DeckRef | None = None):
        """Refills a row's deck suggestions, keeping the deck already
        chosen / typed (or `keep`)."""
        if keep is None:
            keep = self._row_deck(row)
        player = self.tracker.players.get(self._owner_id(row) or "")  # suggestions: the owner's decks
        box = row.deck
        box.blockSignals(True)
        box.clear()
        for deck in self._deck_suggestions(player):
            box.addItem(deck.name, deck)
        if keep and keep.name:
            index = next((i for i in range(box.count()) if box.itemData(i).key == keep.key), -1)
            if index < 0:
                box.insertItem(0, keep.name, keep)
                index = 0
            box.setCurrentIndex(index)
        else:
            box.setCurrentIndex(-1)
            box.setEditText("")
        box.blockSignals(False)

    def _on_moxfield_decks(self, result):
        """A Moxfield player's deck list arrived — or couldn't be fetched
        (decks None): then it's remembered as empty for this session, so
        the dialog doesn't ask Moxfield again on every seat change (their
        decks from earlier games, and typing a name, still work)."""
        username, decks = result
        _moxfield_decks_cache[username.lower()] = decks or []
        self._fetching.discard(username.lower())
        if decks is None:
            return
        for row in self._rows:  # refresh every seat using this player's decks
            player = self.tracker.players.get(self._owner_id(row) or "")
            if player and player.kind == gt.MOXFIELD and player.username.lower() == username.lower():
                self._fill_decks(row)

    def _owner_id(self, row: _SeatRow) -> str | None:
        """Whose deck the row's player uses: the chosen owner, else themselves."""
        player_id = row.player.currentData()
        if player_id in (NEW_GUEST, NEW_MOXFIELD):
            player_id = None
        return row.owner.currentData() or player_id

    def _row_deck(self, row: _SeatRow) -> gt.DeckRef | None:
        """The row's deck: the picked suggestion, or a typed-in name."""
        text = row.deck.currentText().strip()
        if not text:
            return None
        data = row.deck.currentData()
        if isinstance(data, gt.DeckRef) and row.deck.itemText(row.deck.currentIndex()) == row.deck.currentText():
            return data
        # a typed name that is one of the owner's decks is that deck
        for i in range(row.deck.count()):
            deck = row.deck.itemData(i)
            if isinstance(deck, gt.DeckRef) and deck.name.strip().lower() == text.lower():
                return deck
        return gt.DeckRef(text)

    # --------------------------------------------------------------- save
    def _on_save(self):
        seats = []
        for row in self._rows:
            player_id = row.player.currentData()
            if player_id in (None, NEW_GUEST, NEW_MOXFIELD):
                QMessageBox.warning(self, "Save game", "Choose a player for every seat.")
                return
            deck = self._row_deck(row)
            if deck is None:
                QMessageBox.warning(self, "Save game",
                                    f"Pick or type a deck for {self.tracker.players[player_id].display_name}.")
                return
            owner_id = row.owner.currentData() or ""
            seats.append(gt.Seat(player_id, deck, owner_id if owner_id != player_id else ""))
        checked = self._winner_group.checkedButton()
        winner_row = next((r for r in self._rows if r.winner is checked), None)
        winner_id = winner_row.player.currentData() if winner_row else None
        game_date = self._date.date().toString("yyyy-MM-dd")
        try:
            if self._game:
                self.tracker.update_game(self._game.id, seats, winner_id, game_date, self._notes.text())
            else:
                self.tracker.add_game(seats, winner_id, game_date, self._notes.text())
        except (gt.GameTrackerError, ValueError) as e:
            QMessageBox.warning(self, "Save game", str(e))
            return
        self.accept()
