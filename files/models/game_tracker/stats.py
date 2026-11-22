"""Game Tracker statistics, computed from a GameTracker's games: games /
wins / Elo per player and per deck, Elo histories (one point per game),
head-to-head matchups, pilots, and which deck a seat counts for (a deck =
its owner + the deck, so borrowed games count for the owner's deck).
GameTracker exposes each of these as a method.
"""

from .elo import ratings as elo_ratings
from .data import ELO_START, DeckStats, PlayerStats, plural_players


def player_stats(tracker) -> list:
    """Games / wins / Elo per player, highest Elo first."""
    stats = {pid: PlayerStats(p) for pid, p in tracker.players.items()}
    for game in tracker.games:
        for seat in game.seats:
            stats[seat.player_id].games += 1
        if game.winner_id:
            stats[game.winner_id].wins += 1
    for pid, elo in elo_ratings(tracker.games, lambda seat: seat.player_id).items():
        stats[pid].elo = elo
    return sorted(stats.values(), key=lambda s: (-s.elo, -s.games, s.player.display_name.lower()))


def player_elo_history(tracker, player_id: str) -> list:
    """Points for the player's Elo chart — one per game they played:
    the 1500 start, then their Elo after each game (a draw / unfinished
    game is a flat step). Each point: {"date", "label", "value"} plus
    "detail" (won / lost / no winner) for the tooltip."""
    history = {}
    elo_ratings(tracker.games, lambda seat: seat.player_id, history)
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


def deck_elo_history(tracker, deck_key: tuple) -> list:
    """Like player_elo_history, for a deck (deck_key: DeckStats.key):
    one point per game it was played in, "detail" naming the pilot."""
    key_of = deck_key_function(tracker)
    history = {}
    elo_ratings(tracker.games, key_of, history)
    games = history.get(deck_key, [])
    if not games:
        return []
    points = [{"date": games[0][0].date, "label": "Start", "value": float(ELO_START)}]
    for n, (game, rating) in enumerate(games, start=1):
        seat = next(s for s in game.seats if key_of(s) == deck_key)
        result = ("Won" if game.winner_id == seat.player_id
                  else "No winner" if game.winner_id is None else "Lost")
        pilot = tracker.players[seat.player_id].display_name
        points.append({"date": game.date, "label": f"Game {n} · {game.date}", "value": rating,
                       "detail": f"{result} · played by {pilot} · {plural_players(len(game.seats))}"})
    return points


def deck_matchups(tracker, deck_key: tuple) -> list:
    """Head-to-head against every other deck it has met: [{"deck",
    "owner", "key", "wins" (this deck won with it at the table),
    "losses" (it won with this deck at the table)}]."""
    key_of = deck_key_function(tracker)
    latest = {}   # key -> (DeckRef, owner) — most recent version
    record = {}   # key -> [wins, losses]
    for game in tracker.games_sorted():  # newest first
        keys = {key_of(s): s for s in game.seats}
        if deck_key not in keys:
            continue
        for key, seat in keys.items():
            if key == deck_key:
                continue
            latest.setdefault(key, (seat.deck, tracker.players[seat.owner_id]))
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


def deck_pilots(tracker, deck_key: tuple) -> list:
    """[(player, games, wins)] — who has played the deck, most games first."""
    key_of = deck_key_function(tracker)
    counts = {}
    for game in tracker.games:
        for seat in game.seats:
            if key_of(seat) == deck_key:
                c = counts.setdefault(seat.player_id, [0, 0])
                c[0] += 1
                c[1] += game.winner_id == seat.player_id
    return sorted(((tracker.players[p], g, w) for p, (g, w) in counts.items()), key=lambda x: (-x[1], -x[2]))


def player_decks(tracker, player_id: str) -> list:
    """DeckStats of the decks the player owns (incl. games others played
    with them), highest Elo first."""
    return [s for s in deck_stats(tracker) if s.owner.id == player_id]


def deck_key_function(tracker):
    """seat -> the deck it counts for: owner + deck, and a typed-in
    name counts as the owner's linked deck of that name (e.g. games
    recorded before the deck was picked from Moxfield)."""
    linked = {}  # (owner, name) -> deck_key of a linked (non-custom) deck
    for game in tracker.games:
        for seat in game.seats:
            if seat.deck.deck_id:
                linked.setdefault((seat.owner_id, seat.deck.name.strip().lower()), seat.deck_key)

    def key_of(seat):
        if not seat.deck.deck_id:
            return linked.get((seat.owner_id, seat.deck.name.strip().lower()), seat.deck_key)
        return seat.deck_key
    return key_of


def decks_owned_by(tracker, player_id: str) -> list:
    """The player's decks seen in games (most recent first, one per
    deck) — including ones others borrowed, not ones they borrowed."""
    seen, decks = set(), []
    for game in tracker.games_sorted():
        for seat in game.seats:
            if seat.owner_id == player_id and seat.deck.key not in seen:
                seen.add(seat.deck.key)
                decks.append(seat.deck)
    return decks


def deck_stats(tracker) -> list:
    """Games / wins / Elo per deck — a deck being its owner + the deck
    (deck_key_function), so games with a borrowed deck count for the
    owner's deck. Highest Elo first."""
    key_of = deck_key_function(tracker)
    stats = {}
    for game in tracker.games_sorted():  # newest first: keeps the latest DeckRef
        for seat in game.seats:
            key = key_of(seat)
            s = stats.get(key)
            if s is None:
                s = stats[key] = DeckStats(tracker.players[seat.owner_id], seat.deck, key=key)
            s.games += 1
            s.played_by.add(seat.player_id)
            if game.winner_id == seat.player_id:
                s.wins += 1
    elo = elo_ratings(tracker.games, key_of)
    for key, s in stats.items():
        s.elo = elo.get(key, ELO_START)
    return sorted(stats.values(), key=lambda s: (-s.elo, -s.games, s.deck.name.lower()))
