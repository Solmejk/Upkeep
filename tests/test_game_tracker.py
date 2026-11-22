"""models.game_tracker: players, games, borrowing, merging, stats and Elo.
Each test gets its own empty tracker file in a temporary folder."""

import pytest

from models.game_tracker import (
    ELO_START, DeckRef, GameTracker, GameTrackerError, Seat, GUEST, MOXFIELD,
)


@pytest.fixture
def tracker(tmp_path):
    return GameTracker(tmp_path / "game_tracker.json")


def deck(name, deck_id=""):
    return DeckRef(name, "moxfield" if deck_id else "custom", deck_id)


def seats(*pairs):
    """seats((player, "Deck"), (player, "Deck", owner)) -> [Seat]"""
    out = []
    for p in pairs:
        d = p[1] if isinstance(p[1], DeckRef) else deck(p[1])
        out.append(Seat(p[0].id, d, p[2].id if len(p) > 2 else ""))
    return out


# ------------------------------------------------------------------ players

def test_players_unique_and_case_insensitive(tracker):
    me = tracker.add_moxfield("Solmejk")
    assert tracker.add_moxfield("solmejk") is me
    tracker.add_guest("Bob")
    with pytest.raises(GameTrackerError):
        tracker.add_guest("bob")
    with pytest.raises(GameTrackerError):
        tracker.add_guest("  ")


def test_nicknames(tracker):
    kim = tracker.add_moxfield("KimTheGreat99")
    tracker.add_guest("Bob")
    tracker.set_nickname(kim.id, "Kim")
    assert (kim.display_name, kim.full_name) == ("Kim", "Kim (KimTheGreat99)")
    with pytest.raises(GameTrackerError):
        tracker.set_nickname(kim.id, "bob")  # another player shows as Bob
    tracker.set_nickname(kim.id, "")
    assert kim.display_name == "KimTheGreat99"


# ------------------------------------------------------------------ games

def test_game_rules(tracker):
    a, b, c = (tracker.add_guest(n) for n in "ABC")
    for bad in (
        lambda: tracker.add_game(seats((a, "x")), None, "2026-01-01"),                 # one player
        lambda: tracker.add_game(seats((a, "x"), (a, "y")), None, "2026-01-01"),       # same player twice
        lambda: tracker.add_game(seats((a, "x"), (b, "y")), c.id, "2026-01-01"),       # winner not seated
        lambda: tracker.add_game(seats((a, ""), (b, "y")), None, "2026-01-01"),        # no deck
    ):
        with pytest.raises(GameTrackerError):
            bad()
    with pytest.raises(ValueError):
        tracker.add_game(seats((a, "x"), (b, "y")), None, "not a date")


def test_edit_and_delete_games(tracker):
    a, b = tracker.add_guest("A"), tracker.add_guest("B")
    game = tracker.add_game(seats((a, "x"), (b, "y")), a.id, "2026-01-01")
    tracker.update_game(game.id, seats((a, "x"), (b, "y")), b.id, "2026-01-02", "rematch")
    assert (tracker.game(game.id).winner_id, tracker.game(game.id).notes) == (b.id, "rematch")
    tracker.delete_game(game.id)
    assert tracker.games == []


def test_saves_and_reloads(tracker, tmp_path):
    me, bob = tracker.add_moxfield("Solmejk"), tracker.add_guest("Bob")
    tracker.add_game(seats((me, deck("Edgar", "4AM")), (bob, "Elves", me)), bob.id, "2026-01-01", "close")
    again = GameTracker(tmp_path / "game_tracker.json")
    assert len(again.players) == 2 and len(again.games) == 1
    seat = again.games[0].seats[1]
    assert (seat.deck.name, seat.deck_owner_id, again.games[0].notes) == ("Elves", me.id, "close")


# ------------------------------------------------------------------ linking / merging

def test_link_guest_keeps_games_and_name(tracker):
    bob, ann = tracker.add_guest("Bob"), tracker.add_guest("Ann")
    tracker.add_game(seats((bob, "Elves"), (ann, "Atraxa")), bob.id, "2026-01-01")
    linked = tracker.link_to_moxfield(bob.id, "BobMox")
    assert linked.kind == MOXFIELD and linked.full_name == "Bob (BobMox)"
    assert tracker.games[0].winner_id == linked.id


def test_merge_into_existing_player(tracker):
    kim = tracker.add_moxfield("KimMox")
    tommy, ann = tracker.add_guest("Tommy"), tracker.add_guest("Ann")
    tracker.add_game(seats((tommy, "Krenko"), (ann, "Atraxa")), tommy.id, "2026-01-01")
    merged = tracker.link_to_moxfield(tommy.id, "kimmox")
    assert merged is kim and tommy.id not in tracker.players
    assert tracker.games[0].winner_id == kim.id and kim.nickname == "Tommy"


def test_cannot_merge_players_who_played_each_other(tracker):
    kim, tommy = tracker.add_moxfield("KimMox"), tracker.add_guest("Tommy")
    tracker.add_game(seats((kim, "x"), (tommy, "y")), None, "2026-01-01")
    with pytest.raises(GameTrackerError):
        tracker.link_to_moxfield(tommy.id, "KimMox")


def test_delete_player_only_without_games_or_lent_decks(tracker):
    a, b, lender = tracker.add_guest("A"), tracker.add_guest("B"), tracker.add_guest("Lender")
    tracker.add_game(seats((a, "x", lender), (b, "y")), None, "2026-01-01")
    for player in (a, lender):
        with pytest.raises(GameTrackerError):
            tracker.delete_player(player.id)
    free = tracker.add_guest("Free")
    tracker.delete_player(free.id)
    assert free.id not in tracker.players


# ------------------------------------------------------------------ borrowing / deck identity

def test_borrowed_games_count_for_the_owners_deck(tracker):
    me, bob = tracker.add_moxfield("Solmejk"), tracker.add_guest("Bob")
    edgar = deck("Edgar Markov", "4AM")
    tracker.add_game(seats((me, edgar), (bob, "Elves")), me.id, "2026-01-01")
    tracker.add_game(seats((bob, edgar, me), (me, "Syr Konrad")), bob.id, "2026-01-02")
    stats = {(s.owner.display_name, s.deck.name): s for s in tracker.deck_stats()}
    assert (stats[("Solmejk", "Edgar Markov")].games, stats[("Solmejk", "Edgar Markov")].wins) == (2, 2)
    assert ("Bob", "Edgar Markov") not in stats
    pilots = {p.display_name: (g, w) for p, g, w in tracker.deck_pilots(stats[("Solmejk", "Edgar Markov")].key)}
    assert pilots == {"Solmejk": (1, 1), "Bob": (1, 1)}


def test_same_typed_name_for_different_owners_stays_separate(tracker):
    bob, ann = tracker.add_guest("Bob"), tracker.add_guest("Ann")
    tracker.add_game(seats((bob, "Elves"), (ann, "Elves")), bob.id, "2026-01-01")
    assert len(tracker.deck_stats()) == 2


def test_typed_name_counts_as_the_owners_linked_deck(tracker):
    me, bob = tracker.add_moxfield("Solmejk"), tracker.add_guest("Bob")
    tracker.add_game(seats((me, "syr konrad"), (bob, "Elves")), None, "2026-01-01")     # typed
    tracker.add_game(seats((me, deck("Syr Konrad", "pfB")), (bob, "Elves")), None, "2026-01-02")  # linked
    mine = [s for s in tracker.player_decks(me.id)]
    assert len(mine) == 1 and mine[0].games == 2


def test_borrowing_your_own_deck_is_your_own_deck(tracker):
    a, b = tracker.add_guest("A"), tracker.add_guest("B")
    game = tracker.add_game(seats((a, "x", a), (b, "y")), None, "2026-01-01")
    assert game.seats[0].deck_owner_id == ""


# ------------------------------------------------------------------ Elo

def test_elo_win_draw_and_conservation(tracker):
    a, b, c, d = (tracker.add_guest(n) for n in "ABCD")
    tracker.add_game(seats((a, "a"), (b, "b")), a.id, "2026-01-01")
    elo = {s.player.display_name: s.elo for s in tracker.player_stats()}
    assert elo["A"] == pytest.approx(ELO_START + 16) and elo["B"] == pytest.approx(ELO_START - 16)

    tracker.add_game(seats((a, "a"), (b, "b"), (c, "c"), (d, "d")), c.id, "2026-01-02")
    elo = {s.player.display_name: s.elo for s in tracker.player_stats()}
    assert elo["C"] == pytest.approx(ELO_START + 16, abs=0.5)   # a pod win ≈ a 1v1 win
    assert elo["A"] < ELO_START + 16                              # the stronger player paid more
    assert sum(elo.values()) == pytest.approx(4 * ELO_START)     # points are conserved

    before = dict(elo)
    tracker.add_game(seats((a, "a"), (b, "b")), None, "2026-01-03")  # draw
    assert {s.player.display_name: s.elo for s in tracker.player_stats()} == pytest.approx(before)


def test_upsets_move_more_points(tracker):
    strong, weak, x = tracker.add_guest("Strong"), tracker.add_guest("Weak"), tracker.add_guest("X")
    for day in range(1, 6):
        tracker.add_game(seats((strong, "s"), (x, "x")), strong.id, f"2026-01-0{day}")
    gain_vs_strong = _elo_gain(tracker, weak, strong)
    gain_vs_equal = _elo_gain(tracker, weak, tracker.add_guest("Equal"))
    assert gain_vs_strong > gain_vs_equal


def _elo_gain(tracker, winner, loser):
    before = {s.player.id: s.elo for s in tracker.player_stats()}[winner.id]
    game = tracker.add_game(seats((winner, "w"), (loser, "l")), winner.id, "2026-02-01")
    after = {s.player.id: s.elo for s in tracker.player_stats()}[winner.id]
    tracker.delete_game(game.id)
    return after - before


def test_elo_history_has_one_point_per_game(tracker):
    a, b = tracker.add_guest("A"), tracker.add_guest("B")
    for winner in (a, a, b):
        tracker.add_game(seats((a, "a"), (b, "b")), winner.id, "2026-01-01")   # same day
    tracker.add_game(seats((a, "a"), (b, "b")), None, "2026-01-02")
    history = tracker.player_elo_history(a.id)
    assert [p["label"].split(" · ")[0] for p in history] == ["Start", "Game 1", "Game 2", "Game 3", "Game 4"]
    assert history[0]["value"] == ELO_START and history[-1]["value"] == history[-2]["value"]  # draw: flat
    final = {s.player.id: s.elo for s in tracker.player_stats()}[a.id]
    assert history[-1]["value"] == pytest.approx(final)


def test_deck_history_and_matchups(tracker):
    me, bob, ann = tracker.add_moxfield("Solmejk"), tracker.add_guest("Bob"), tracker.add_guest("Ann")
    tracker.add_game(seats((me, "Konrad"), (bob, "Elves")), me.id, "2026-01-01")
    tracker.add_game(seats((me, "Konrad"), (bob, "Elves")), me.id, "2026-01-02")
    tracker.add_game(seats((me, "Konrad"), (ann, "Atraxa")), ann.id, "2026-01-03")
    konrad = tracker.player_decks(me.id)[0]
    assert len(tracker.deck_elo_history(konrad.key)) == 4
    record = {m["deck"].name: (m["wins"], m["losses"]) for m in tracker.deck_matchups(konrad.key)}
    assert record == {"Elves": (2, 0), "Atraxa": (0, 1)}
