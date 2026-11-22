"""Game Tracker data classes and constants — Player, DeckRef, Seat, Game,
the stats rows (PlayerStats, DeckStats) and GameTrackerError. See the
package docstring (models/game_tracker/__init__.py) for what each means.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

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


def plural_players(n: int) -> str:
    return f"{n} player" if n == 1 else f"{n} players"
