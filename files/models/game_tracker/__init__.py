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

The package: data.py (the classes and constants), store.py (GameTracker:
loading, saving, players and games), elo.py (ratings), stats.py
(statistics). Import everything from here: `from models import
game_tracker as gt`.
"""

import moxfield

from .data import (
    DECK_CUSTOM, DECK_LOCAL, DECK_MOXFIELD, ELO_K, ELO_START, FILE_VERSION, GUEST, MAX_PLAYERS,
    MIN_PLAYERS, MOXFIELD, DeckRef, DeckStats, Game, GameTrackerError, Player, PlayerStats, Seat,
    plural_players,
)
from .store import GameTracker

__all__ = [
    "DECK_CUSTOM", "DECK_LOCAL", "DECK_MOXFIELD", "ELO_K", "ELO_START", "FILE_VERSION", "GUEST",
    "MAX_PLAYERS", "MIN_PLAYERS", "MOXFIELD", "DeckRef", "DeckStats", "Game", "GameTracker",
    "GameTrackerError", "Player", "PlayerStats", "Seat", "fetch_moxfield_decks", "plural_players",
]


def fetch_moxfield_decks(username: str) -> list:
    """A Moxfield user's public decks as DeckRefs, newest first
    (moxfield.search_decks). Raises on network errors / unknown users."""
    return [DeckRef(name=d["name"], source=DECK_MOXFIELD, deck_id=d["publicId"],
                    colors=list(d.get("colorIdentity") or []))
            for d in moxfield.search_decks(username).get("data", [])]
