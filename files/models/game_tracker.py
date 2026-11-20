"""Game Tracker data: players, the decks they played and who won.

    Player   — a guest (just a name, made in the app) or a Moxfield user
               (a username, optionally with a nickname shown instead). A
               guest can later be linked to a Moxfield username; games
               refer to players by id, so every earlier game stays
               attached (and if that username is already a player, the two
               are merged into one). The guest's name becomes the nickname.
    DeckRef  — the deck a player used in one game: a name plus where it
               came from — one of your decks (Moxfield / local), one of a
               Moxfield player's public decks, or a typed-in name.
    Seat     — one player + the deck they played in a game, and whose deck
               it is: their own, or one borrowed from another player
               (deck_owner_id). A deck's identity includes its owner, so a
               borrowed deck's games count for the owner's deck in stats.
    Game     — a date, 2-8 seats, the winner's player id (None = no
               winner: a draw or an unfinished game) and notes.

GameTracker loads / saves everything as data/game_tracker.json (user data
— clear_cache never touches it) and does every change through methods
that keep it consistent (unique players, valid winners, merges).

Elo (player and deck, separately): everyone starts at 1500. In a game
with a winner, the winner "beats" each other player at the table; those
pairwise changes are divided by the number of opponents, so a pod win
isn't worth three 1v1 wins. Games without a winner change nothing.
Ratings are recomputed from every game in date order, so editing or
deleting an old game is reflected correctly.
"""

import uuid
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path

import cache_io
import moxfield
import paths

GUEST, MOXFIELD = "guest", "moxfield"
DECK_MOXFIELD, DECK_LOCAL, DECK_CUSTOM = "moxfield", "local", "custom"
MIN_PLAYERS, MAX_PLAYERS = 2, 8
FILE_VERSION = 1
ELO_START = 1500
ELO_K = 32


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class GameTrackerError(ValueError):
    """A change that would make the data inconsistent (shown to the user)."""


@dataclass
class Player:
    id: str
    kind: str                  # GUEST or MOXFIELD
    name: str = ""             # guests: their name (Moxfield players: unused)
    username: str = ""         # Moxfield players: their Moxfield username
    nickname: str = ""         # Moxfield players: shown instead of the username, if set
    created_at: str = field(default_factory=_now)

    @property
    def display_name(self) -> str:
        """The name shown in standings / game lists."""
        if self.kind == MOXFIELD:
            return self.nickname or self.username
        return self.name

    @property
    def full_name(self) -> str:
        """display_name plus the username behind a nickname — for pickers
        and the players list, e.g. "Bob (BobMox)"."""
        if self.kind == MOXFIELD and self.nickname:
            return f"{self.nickname} ({self.username})"
        return self.display_name

    @staticmethod
    def from_dict(d: dict) -> "Player":
        return Player(id=d["id"], kind=d["kind"], name=d.get("name", ""),
                      username=d.get("username", ""), nickname=d.get("nickname", ""),
                      created_at=d.get("created_at", ""))


@dataclass
class DeckRef:
    name: str
    source: str = DECK_CUSTOM  # DECK_MOXFIELD / DECK_LOCAL / DECK_CUSTOM
    deck_id: str = ""          # Moxfield public id / local deck id ("" for custom)
    commander: str = ""        # when known
    colors: list = field(default_factory=list)  # color identity, e.g. ["W", "U"], when known

    @property
    def key(self) -> tuple:
        """Identifies the deck among one owner's decks (see Seat.deck_key)."""
        return (self.source, self.deck_id) if self.deck_id else (DECK_CUSTOM, self.name.strip().lower())

    @staticmethod
    def from_dict(d: dict) -> "DeckRef":
        return DeckRef(name=d.get("name", ""), source=d.get("source", DECK_CUSTOM),
                       deck_id=d.get("deck_id", ""), commander=d.get("commander", ""),
                       colors=list(d.get("colors") or []))


@dataclass
class Seat:
    player_id: str
    deck: DeckRef
    deck_owner_id: str = ""    # "" = their own deck, else the player it was borrowed from

    @property
    def owner_id(self) -> str:
        """Whose deck it is (the player themselves unless borrowed)."""
        return self.deck_owner_id or self.player_id

    @property
    def borrowed(self) -> bool:
        return bool(self.deck_owner_id) and self.deck_owner_id != self.player_id

    @property
    def deck_key(self) -> tuple:
        """Identifies "the same deck" across all games: owner + deck — so a
        borrowed deck is the owner's deck, and two players' decks with the
        same typed-in name stay separate."""
        return (self.owner_id,) + self.deck.key

    @staticmethod
    def from_dict(d: dict) -> "Seat":
        return Seat(player_id=d["player_id"], deck=DeckRef.from_dict(d.get("deck") or {}),
                    deck_owner_id=d.get("deck_owner_id", ""))


@dataclass
class Game:
    id: str
    date: str                  # "YYYY-MM-DD"
    seats: list                # [Seat], in seating order
    winner_id: str | None = None
    notes: str = ""
    created_at: str = field(default_factory=_now)

    def seat_of(self, player_id: str) -> Seat | None:
        return next((s for s in self.seats if s.player_id == player_id), None)

    @staticmethod
    def from_dict(d: dict) -> "Game":
        return Game(id=d["id"], date=d["date"], seats=[Seat.from_dict(s) for s in d["seats"]],
                    winner_id=d.get("winner_id"), notes=d.get("notes", ""),
                    created_at=d.get("created_at", ""))


@dataclass
class DeckStats:
    owner: Player
    deck: DeckRef              # the most recent version (name may have changed)
    games: int = 0
    wins: int = 0
    played_by: set = field(default_factory=set)  # player ids who played it
    elo: float = ELO_START
    key: tuple = ()            # identifies the deck (see deck_key_function)

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0


@dataclass
class PlayerStats:
    player: Player
    games: int = 0
    wins: int = 0
    elo: float = ELO_START

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0


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

    def _validate(self, game: Game):
        ids = [s.player_id for s in game.seats]
        if not MIN_PLAYERS <= len(ids) <= MAX_PLAYERS:
            raise GameTrackerError(f"A game needs {MIN_PLAYERS}-{MAX_PLAYERS} players.")
        if len(set(ids)) != len(ids):
            raise GameTrackerError("Each player can only sit once in a game.")
        if any(pid not in self.players for pid in ids):
            raise GameTrackerError("Unknown player.")
        if any(s.deck_owner_id and s.deck_owner_id not in self.players for s in game.seats):
            raise GameTrackerError("Unknown deck owner.")
        for s in game.seats:  # borrowing your own deck = your own deck
            if s.deck_owner_id == s.player_id:
                s.deck_owner_id = ""
        if any(not s.deck.name.strip() for s in game.seats):
            raise GameTrackerError("Every player needs a deck (a name is enough).")
        if game.winner_id is not None and game.winner_id not in ids:
            raise GameTrackerError("The winner has to be one of the players.")
        date.fromisoformat(game.date)  # raises on a bad date

    def add_game(self, seats: list, winner_id: str | None, game_date: str, notes: str = "") -> Game:
        game = Game(id=_new_id("g"), date=game_date, seats=seats, winner_id=winner_id, notes=notes.strip())
        self._validate(game)
        self.games.append(game)
        self.save()
        return game

    def update_game(self, game_id: str, seats: list, winner_id: str | None, game_date: str, notes: str = ""):
        game = self.game(game_id)
        updated = Game(id=game.id, date=game_date, seats=seats, winner_id=winner_id,
                       notes=notes.strip(), created_at=game.created_at)
        self._validate(updated)
        self.games[self.games.index(game)] = updated
        self.save()

    def delete_game(self, game_id: str):
        self.games.remove(self.game(game_id))
        self.save()

    def game(self, game_id: str) -> Game:
        return next(g for g in self.games if g.id == game_id)

    # ------------------------------------------------------------- stats
    def player_stats(self) -> list:
        """Games / wins / Elo per player, highest Elo first."""
        stats = {pid: PlayerStats(p) for pid, p in self.players.items()}
        for game in self.games:
            for seat in game.seats:
                stats[seat.player_id].games += 1
            if game.winner_id:
                stats[game.winner_id].wins += 1
        for pid, elo in self._elo(lambda seat: seat.player_id).items():
            stats[pid].elo = elo
        return sorted(stats.values(), key=lambda s: (-s.elo, -s.games, s.player.display_name.lower()))

    def _elo(self, key_of, history: dict | None = None) -> dict:
        """Elo per key (key_of(seat) -> player id / deck key) after every
        game in date order — see the module docstring. history: if given,
        filled with key -> [(game, rating after it)] for every game the key
        took part in (games without a winner leave the rating unchanged)."""
        ratings = {}
        for game in sorted(self.games, key=lambda g: (g.date, g.created_at)):
            self._rate_game(game, key_of, ratings)
            if history is not None:
                for key in dict.fromkeys(key_of(s) for s in game.seats):
                    history.setdefault(key, []).append((game, ratings.get(key, ELO_START)))
        return ratings

    @staticmethod
    def _rate_game(game: "Game", key_of, ratings: dict):
        """Applies one game's Elo changes to `ratings` (in place)."""
        winner = game.seat_of(game.winner_id) if game.winner_id else None
        if winner is None:
            return
        losers = [s for s in game.seats if s is not winner and key_of(s) != key_of(winner)]
        if losers:
            w = key_of(winner)
            rw = ratings.get(w, ELO_START)
            change = {}
            for seat in losers:
                l = key_of(seat)
                rl = ratings.get(l, ELO_START)
                expected = 1 / (1 + 10 ** ((rl - rw) / 400))  # winner's expected score
                delta = ELO_K * (1 - expected) / len(losers)
                change[w] = change.get(w, 0) + delta
                change[l] = change.get(l, 0) - delta
            for key, delta in change.items():
                ratings[key] = ratings.get(key, ELO_START) + delta

    def player_elo_history(self, player_id: str) -> list:
        """Points for the player's Elo chart — one per game they played:
        the 1500 start, then their Elo after each game (a draw / unfinished
        game is a flat step). Each point: {"date", "label", "value"} plus
        "detail" (won / lost / no winner) for the tooltip."""
        history = {}
        self._elo(lambda seat: seat.player_id, history)
        games = history.get(player_id, [])
        if not games:
            return []
        points = [{"date": games[0][0].date, "label": "Start", "value": float(ELO_START)}]
        for n, (game, rating) in enumerate(games, start=1):
            result = ("Won" if game.winner_id == player_id
                      else "No winner" if game.winner_id is None else "Lost")
            points.append({"date": game.date, "label": f"Game {n} · {game.date}", "value": rating,
                           "detail": f"{result} · {plural_players(len(game.seats))}"})
        return points

    def deck_elo_history(self, deck_key: tuple) -> list:
        """Like player_elo_history, for a deck (deck_key: DeckStats.key):
        one point per game it was played in, "detail" naming the pilot."""
        key_of = self.deck_key_function()
        history = {}
        self._elo(key_of, history)
        games = history.get(deck_key, [])
        if not games:
            return []
        points = [{"date": games[0][0].date, "label": "Start", "value": float(ELO_START)}]
        for n, (game, rating) in enumerate(games, start=1):
            seat = next(s for s in game.seats if key_of(s) == deck_key)
            result = ("Won" if game.winner_id == seat.player_id
                      else "No winner" if game.winner_id is None else "Lost")
            pilot = self.players[seat.player_id].display_name
            points.append({"date": game.date, "label": f"Game {n} · {game.date}", "value": rating,
                           "detail": f"{result} · played by {pilot} · {plural_players(len(game.seats))}"})
        return points

    def deck_matchups(self, deck_key: tuple) -> list:
        """Head-to-head against every other deck it has met: [{"deck",
        "owner", "key", "wins" (this deck won with it at the table),
        "losses" (it won with this deck at the table)}]."""
        key_of = self.deck_key_function()
        latest = {}   # key -> (DeckRef, owner) — most recent version
        record = {}   # key -> [wins, losses]
        for game in self.games_sorted():  # newest first
            keys = {key_of(s): s for s in game.seats}
            if deck_key not in keys:
                continue
            for key, seat in keys.items():
                if key == deck_key:
                    continue
                latest.setdefault(key, (seat.deck, self.players[seat.owner_id]))
                rec = record.setdefault(key, [0, 0])
                winner = game.seat_of(game.winner_id) if game.winner_id else None
                if winner is None:
                    continue
                if key_of(winner) == deck_key:
                    rec[0] += 1
                elif key_of(winner) == key:
                    rec[1] += 1
        return [{"deck": latest[k][0], "owner": latest[k][1], "key": k, "wins": w, "losses": l}
                for k, (w, l) in record.items()]

    def deck_pilots(self, deck_key: tuple) -> list:
        """[(player, games, wins)] — who has played the deck, most games first."""
        key_of = self.deck_key_function()
        counts = {}
        for game in self.games:
            for seat in game.seats:
                if key_of(seat) == deck_key:
                    c = counts.setdefault(seat.player_id, [0, 0])
                    c[0] += 1
                    c[1] += game.winner_id == seat.player_id
        return sorted(((self.players[p], g, w) for p, (g, w) in counts.items()), key=lambda x: (-x[1], -x[2]))

    def player_decks(self, player_id: str) -> list:
        """DeckStats of the decks the player owns (incl. games others played
        with them), highest Elo first."""
        return [s for s in self.deck_stats() if s.owner.id == player_id]

    def deck_key_function(self):
        """seat -> the deck it counts for: owner + deck, and a typed-in
        name counts as the owner's linked deck of that name (e.g. games
        recorded before the deck was picked from Moxfield)."""
        linked = {}  # (owner, name) -> deck_key of a linked (non-custom) deck
        for game in self.games:
            for seat in game.seats:
                if seat.deck.deck_id:
                    linked.setdefault((seat.owner_id, seat.deck.name.strip().lower()), seat.deck_key)

        def key_of(seat):
            if not seat.deck.deck_id:
                return linked.get((seat.owner_id, seat.deck.name.strip().lower()), seat.deck_key)
            return seat.deck_key
        return key_of

    def decks_owned_by(self, player_id: str) -> list:
        """The player's decks seen in games (most recent first, one per
        deck) — including ones others borrowed, not ones they borrowed."""
        seen, decks = set(), []
        for game in self.games_sorted():
            for seat in game.seats:
                if seat.owner_id == player_id and seat.deck.key not in seen:
                    seen.add(seat.deck.key)
                    decks.append(seat.deck)
        return decks

    def deck_stats(self) -> list:
        """Games / wins / Elo per deck — a deck being its owner + the deck
        (deck_key_function), so games with a borrowed deck count for the
        owner's deck. Highest Elo first."""
        key_of = self.deck_key_function()
        stats = {}
        for game in self.games_sorted():  # newest first: keeps the latest DeckRef
            for seat in game.seats:
                key = key_of(seat)
                s = stats.get(key)
                if s is None:
                    s = stats[key] = DeckStats(self.players[seat.owner_id], seat.deck, key=key)
                s.games += 1
                s.played_by.add(seat.player_id)
                if game.winner_id == seat.player_id:
                    s.wins += 1
        elo = self._elo(key_of)
        for key, s in stats.items():
            s.elo = elo.get(key, ELO_START)
        return sorted(stats.values(), key=lambda s: (-s.elo, -s.games, s.deck.name.lower()))


def plural_players(n: int) -> str:
    return f"{n} player" if n == 1 else f"{n} players"


def fetch_moxfield_decks(username: str) -> list:
    """A Moxfield user's public decks as DeckRefs, newest first
    (moxfield.search_decks). Raises on network errors / unknown users."""
    return [DeckRef(name=d["name"], source=DECK_MOXFIELD, deck_id=d["publicId"],
                    colors=list(d.get("colorIdentity") or []))
            for d in moxfield.search_decks(username).get("data", [])]
