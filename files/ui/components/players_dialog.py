"""PlayersDialog: manage the Game Tracker's players — add guests or
Moxfield players, rename a guest / give a Moxfield player a nickname,
link a guest to a Moxfield username
(keeping their games; merging if that username is already a player), and
delete players without games. Every change goes through
models.game_tracker.GameTracker, which saves it.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QInputDialog, QMessageBox,
)

from card_fields import plural
from models import game_tracker as gt


class PlayersDialog(QDialog):
    def __init__(self, parent, app, tracker: gt.GameTracker):
        super().__init__(parent)
        self.app = app
        self.tracker = tracker
        self.setWindowTitle("Players")
        self.resize(560, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        info = QLabel("Guests are players made here. Link a guest to a Moxfield username when they "
                      "get one — all their games stay connected. Moxfield players can have a "
                      "nickname that's shown instead of their username.")
        info.setObjectName("settingsDescription")
        info.setWordWrap(True)
        layout.addWidget(info)

        body = QHBoxLayout()
        self._list = QListWidget()
        self._list.setObjectName("deckList")
        self._list.currentItemChanged.connect(lambda *_: self._update_buttons())
        body.addWidget(self._list, 1)

        side = QVBoxLayout()
        self._buttons = {}
        for key, text, slot in (("guest", "Add guest…", self._on_guest),
                                ("moxfield", "Add Moxfield player…", self._on_moxfield),
                                ("rename", "Rename…", self._on_rename),
                                ("link", "Link to Moxfield…", self._on_link),
                                ("delete", "Delete", self._on_delete)):
            btn = QPushButton(text)
            if key in ("rename", "link", "delete"):
                btn.setObjectName("backButton")
            btn.clicked.connect(slot)
            side.addWidget(btn)
            self._buttons[key] = btn
        side.addStretch()
        body.addLayout(side)
        layout.addLayout(body, 1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("backButton")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self._reload()

    def _reload(self, select_id: str | None = None):
        games = {s.player.id: s.games for s in self.tracker.player_stats()}
        self._list.clear()
        for player in self.tracker.players_sorted():
            you = self.app.is_me(player)
            kind = "you · Moxfield" if you else ("Moxfield" if player.kind == gt.MOXFIELD else "guest")
            item = QListWidgetItem(f"{player.full_name}   ({kind}, {plural(games.get(player.id, 0), 'game')})")
            item.setData(Qt.UserRole, player.id)
            self._list.addItem(item)
            if player.id == select_id:
                self._list.setCurrentItem(item)
        self._update_buttons()

    def _selected(self) -> gt.Player | None:
        item = self._list.currentItem()
        return self.tracker.players.get(item.data(Qt.UserRole)) if item else None

    def _update_buttons(self):
        player = self._selected()
        is_guest = bool(player and player.kind == gt.GUEST)
        self._buttons["rename"].setEnabled(player is not None)
        self._buttons["rename"].setText("Nickname…" if player and player.kind == gt.MOXFIELD else "Rename…")
        self._buttons["link"].setEnabled(is_guest)
        self._buttons["delete"].setEnabled(player is not None)

    def _run(self, title: str, action):
        """Runs a tracker change, showing its error if it's refused."""
        try:
            return action()
        except gt.GameTrackerError as e:
            QMessageBox.warning(self, title, str(e))
            return None

    def _on_guest(self):
        name, ok = QInputDialog.getText(self, "Add guest", "Guest's name:")
        if ok and (player := self._run("Add guest", lambda: self.tracker.add_guest(name))):
            self._reload(player.id)

    def _on_moxfield(self):
        name, ok = QInputDialog.getText(self, "Add Moxfield player", "Moxfield username:")
        if ok and (player := self._run("Add Moxfield player", lambda: self.tracker.add_moxfield(name))):
            self._reload(player.id)

    def _on_rename(self):
        """Guests: rename. Moxfield players: set / clear their nickname."""
        player = self._selected()
        if player.kind == gt.MOXFIELD:
            name, ok = QInputDialog.getText(
                self, "Nickname", f"Nickname for {player.username} (leave empty to show the username):",
                text=player.nickname)
            if ok:
                self._run("Nickname", lambda: self.tracker.set_nickname(player.id, name))
        else:
            name, ok = QInputDialog.getText(self, "Rename guest", "Name:", text=player.name)
            if ok:
                self._run("Rename guest", lambda: self.tracker.rename_guest(player.id, name))
        self._reload(player.id)

    def _on_link(self):
        player = self._selected()
        username, ok = QInputDialog.getText(
            self, "Link to Moxfield",
            f"{player.name}'s Moxfield username:\n(If that username is already a player, "
            f"{player.name}'s games are moved to it and the guest is removed.)")
        if ok and (result := self._run("Link to Moxfield",
                                       lambda: self.tracker.link_to_moxfield(player.id, username))):
            self._reload(result.id)

    def _on_delete(self):
        player = self._selected()
        if QMessageBox.question(self, "Delete player", f"Delete {player.display_name}?") != QMessageBox.Yes:
            return
        self._run("Delete player", lambda: self.tracker.delete_player(player.id))
        self._reload()
