"""Elo ratings for players and decks. Everyone starts at ELO_START (1500).
In a game with a winner, the winner "beats" each other player at the
table; those pairwise changes are divided by the number of opponents, so
a pod win isn't worth three 1v1 wins (and beating higher-rated opponents
gains more, losing to lower-rated ones costs more). Games without a
winner change nothing. Ratings are always recomputed from every game in
date order, so editing or deleting an old game is reflected correctly.

key_of(seat) picks what is rated: the player (seat.player_id) or the
deck (stats.deck_key_function).
"""

from .data import ELO_K, ELO_START, Game


def ratings(games: list, key_of, history: dict | None = None) -> dict:
    """Elo per key after every game in date order. history: if given,
    filled with key -> [(game, rating after it)] for every game the key
    took part in (games without a winner leave the rating unchanged)."""
    result = {}
    for game in sorted(games, key=lambda g: (g.date, g.created_at)):
        rate_game(game, key_of, result)
        if history is not None:
            for key in dict.fromkeys(key_of(s) for s in game.seats):
                history.setdefault(key, []).append((game, result.get(key, ELO_START)))
    return result


def rate_game(game: Game, key_of, ratings: dict):
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
