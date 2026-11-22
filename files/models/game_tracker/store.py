"""GameTracker: all players and games, loaded from / saved to
data/game_tracker.json on every change (user data — clear_cache never
touches it). Every change goes through a method that keeps the data
consistent (unique players, valid games, links / merges); statistics are
computed by stats.py and elo.py.
"""

from dataclasses import asdict
from datetime import date
from pathlib import Path

import cache_io
import paths

from . import stats
from .data import (
    FILE_VERSION, GUEST, MAX_PLAYERS, MIN_PLAYERS, MOXFIELD, Game, GameTrackerError, Player, _new_id,
)


class GameTracker:
    """All players and games, loaded from / saved to disk on every change."""

    def __init__(self, path=None):
        self._path = Path(path) if path else paths.GAME_TRACKER_PATH
        data = cache_io.read_json(self._path) or {}
        self.players: dict[str, Player] = {
            p["id"]: Player.from_dict(p) for p in data.get("players", [])}
        self.games: list[Game] = [Game.from_dict(g) for g in data.get("games", [])]

    def save(self):
        cache_io.write_json(self._path, {
            "version": FILE_VERSION,
            "players": [asdict(p) for p in self.players.values()],
            "games": [asdict(g) for g in self.games],
        }, indent=1)

    # ----------------------------------------------------------- players
    def players_sorted(self) -> list:
        return sorted(self.players.values(), key=lambda p: p.display_name.lower())

    def find_moxfield(self, username: str) -> Player | None:
        u = username.strip().lower()
        return next((p for p in self.players.values()
                     if p.kind == MOXFIELD and p.username.lower() == u), None)

    def find_guest(self, name: str) -> Player | None:
        n = name.strip().lower()
        return next((p for p in self.players.values() if p.kind == GUEST and p.name.lower() == n), None)

    def add_guest(self, name: str) -> Player:
        name = name.strip()
        if not name:
            raise GameTrackerError("A guest needs a name.")
        if self.find_guest(name):
            raise GameTrackerError(f'There is already a guest called "{name}".')
        player = Player(id=_new_id("p"), kind=GUEST, name=name)
        self.players[player.id] = player
        self.save()
        return player

    def add_moxfield(self, username: str) -> Player:
        """The Moxfield player with that username — made if it's new."""
        username = username.strip()
        if not username:
            raise GameTrackerError("Enter a Moxfield username.")
        existing = self.find_moxfield(username)
        if existing:
            return existing
        player = Player(id=_new_id("p"), kind=MOXFIELD, username=username)
        self.players[player.id] = player
        self.save()
        return player

    def _name_taken(self, name: str, except_id: str) -> bool:
        """True if another player already shows as `name`."""
        n = name.strip().lower()
        return any(p.id != except_id and p.display_name.lower() == n for p in self.players.values())

    def rename_guest(self, player_id: str, name: str):
        player = self.players[player_id]
        name = name.strip()
        if player.kind != GUEST:
            raise GameTrackerError("Moxfield players get a nickname instead (set_nickname).")
        if not name:
            raise GameTrackerError("A guest needs a name.")
        if self._name_taken(name, player_id):
            raise GameTrackerError(f'There is already a player called "{name}".')
        player.name = name
        self.save()

    def set_nickname(self, player_id: str, nickname: str):
        """A Moxfield player's nickname ("" removes it — the username shows)."""
        player = self.players[player_id]
        nickname = nickname.strip()
        if player.kind != MOXFIELD:
            raise GameTrackerError("Only Moxfield players have nicknames — rename the guest instead.")
        if nickname and self._name_taken(nickname, player_id):
            raise GameTrackerError(f'There is already a player called "{nickname}".')
        player.nickname = "" if nickname.lower() == player.username.lower() else nickname
        self.save()

    def link_to_moxfield(self, player_id: str, username: str) -> Player:
        """Turns a guest into a Moxfield player, keeping all their games.
        If that username is already a player, the guest is merged into it
        (their games move over and the guest is removed). Returns the
        resulting player."""
        guest = self.players[player_id]
        username = username.strip()
        if guest.kind != GUEST:
            raise GameTrackerError("Only guests can be linked to a Moxfield username.")
        if not username:
            raise GameTrackerError("Enter a Moxfield username.")
        existing = self.find_moxfield(username)
        if existing is None:
            # the guest's name lives on as the nickname
            guest.kind, guest.username = MOXFIELD, username
            guest.nickname = "" if guest.name.lower() == username.lower() else guest.name
            guest.name = ""
            self.save()
            return guest
        for game in self.games:
            if game.seat_of(existing.id) and game.seat_of(guest.id):
                raise GameTrackerError(
                    f"{guest.name} and {existing.username} played in the same game "
                    f"({game.date}), so they can't be the same person.")
        for game in self.games:
            for seat in game.seats:
                if seat.player_id == guest.id:
                    seat.player_id = existing.id
                if seat.deck_owner_id == guest.id:  # decks the guest lent out
                    seat.deck_owner_id = existing.id
                if seat.deck_owner_id == seat.player_id:  # now their own deck
                    seat.deck_owner_id = ""
            if game.winner_id == guest.id:
                game.winner_id = existing.id
        if not existing.nickname and guest.name.lower() != existing.username.lower():
            existing.nickname = guest.name
        del self.players[guest.id]
        self.save()
        return existing

    def delete_player(self, player_id: str):
        if any(g.seat_of(player_id) for g in self.games):
            raise GameTrackerError("This player has recorded games — delete those games first.")
        if any(s.owner_id == player_id for g in self.games for s in g.seats):
            raise GameTrackerError("Other players have used this player's decks in recorded games.")
        del self.players[player_id]
        self.save()

    # ------------------------------------------------------------- games
    def games_sorted(self) -> list:
        """Newest first (by date, then when it was recorded)."""
        return sorted(self.games, key=lambda g: (g.date, g.created_at), reverse=True)

    @staticmethod
    def _normalise(game: Game):
        """Borrowing your own deck = your own deck."""
        for s in game.seats:
            if s.deck_owner_id == s.player_id:
                s.deck_owner_id = ""

    def _validate(self, game: Game):
        """Raises GameTrackerError (or ValueError for a bad date) if the
        game breaks a rule. Doesn't change the game."""
        ids = [s.player_id for s in game.seats]
        if not MIN_PLAYERS <= len(ids) <= MAX_PLAYERS:
            raise GameTrackerError(f"A game needs {MIN_PLAYERS}-{MAX_PLAYERS} players.")
        if len(set(ids)) != len(ids):
            raise GameTrackerError("Each player can only sit once in a game.")
        if any(pid not in self.players for pid in ids):
            raise GameTrackerError("Unknown player.")
        if any(s.deck_owner_id and s.deck_owner_id not in self.players for s in game.seats):
            raise GameTrackerError("Unknown deck owner.")
        if any(not s.deck.name.strip() for s in game.seats):
            raise GameTrackerError("Every player needs a deck (a name is enough).")
        if game.winner_id is not None and game.winner_id not in ids:
            raise GameTrackerError("The winner has to be one of the players.")
        date.fromisoformat(game.date)  # raises on a bad date

    def add_game(self, seats: list, winner_id: str | None, game_date: str, notes: str = "") -> Game:
        game = Game(id=_new_id("g"), date=game_date, seats=seats, winner_id=winner_id, notes=notes.strip())
        self._normalise(game)
        self._validate(game)
        self.games.append(game)
        self.save()
        return game

    def update_game(self, game_id: str, seats: list, winner_id: str | None, game_date: str, notes: str = ""):
        game = self.game(game_id)
        updated = Game(id=game.id, date=game_date, seats=seats, winner_id=winner_id,
                       notes=notes.strip(), created_at=game.created_at)
        self._normalise(updated)
        self._validate(updated)
        self.games[self.games.index(game)] = updated
        self.save()

    def delete_game(self, game_id: str):
        self.games.remove(self.game(game_id))
        self.save()

    def game(self, game_id: str) -> Game:
        return next(g for g in self.games if g.id == game_id)

    # ------------------------------------------------------------- stats
    # (computed in stats.py / elo.py — see there)
    def player_stats(self) -> list:
        """Games / wins / Elo per player, highest Elo first."""
        return stats.player_stats(self)

    def deck_stats(self) -> list:
        """Games / wins / Elo per deck (owner + deck), highest Elo first."""
        return stats.deck_stats(self)

    def deck_key_function(self):
        """seat -> the deck it counts for (see stats.deck_key_function)."""
        return stats.deck_key_function(self)

    def player_decks(self, player_id: str) -> list:
        """DeckStats of the decks the player owns, highest Elo first."""
        return stats.player_decks(self, player_id)

    def decks_owned_by(self, player_id: str) -> list:
        """The player's decks seen in games, most recent first."""
        return stats.decks_owned_by(self, player_id)

    def player_elo_history(self, player_id: str) -> list:
        """The player's Elo chart points — one per game."""
        return stats.player_elo_history(self, player_id)

    def deck_elo_history(self, deck_key: tuple) -> list:
        """A deck's Elo chart points — one per game."""
        return stats.deck_elo_history(self, deck_key)

    def deck_matchups(self, deck_key: tuple) -> list:
        """A deck's head-to-head record against every deck it has met."""
        return stats.deck_matchups(self, deck_key)

    def deck_pilots(self, deck_key: tuple) -> list:
        """[(player, games, wins)] — who has played a deck."""
        return stats.deck_pilots(self, deck_key)
