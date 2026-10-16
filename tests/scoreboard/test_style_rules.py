"""Style rules on the solver's river answer: no bluff with nothing, no
bluff-catch with one pair against a big bet from a player not read as
aggressive."""

import pytest

from poker_engine.scoreboard.runner import _counts
from poker_engine.scoreboard.style_rules import LIVE, adjust, rules_of

BOARD = ["Ah", "Kd", "7c", "3s", "2d"]
BOTH = {"nobluff", "nocatch"}
WILD = {"hands": 300, "postflop": 200, "aggression": 0.6}


def spot(hole, to_call=0, pot=100, mine=0, board=BOARD, street="river", folded=(6,),
         reads=None):
    """You (seat 4) against seat 2 (seat 6 folded); ``pot`` holds every bet."""
    return {"street": street, "observing_seat": 4, "occupied_seats": [2, 4, 6],
            "folded": list(folded), "own_hole": list(hole), "board": list(board),
            "pot": pot, "to_call": to_call, "bets": {"4": mine, "2": mine + to_call},
            **({"reads": reads} if reads else {})}


def test_no_bluff_with_nothing():
    mixed = {"CHECK": 0.6, "BET 50.000000": 0.3, "BET 100.000000": 0.1}
    strategy, rule = adjust(mixed, spot(["Qs", "Jc"]), BOTH)
    assert rule == "nobluff" and strategy == pytest.approx({"CHECK": 1.0})
    # A pair of your own bets as the solver says.
    assert adjust(mixed, spot(["Kc", "9h"]), BOTH) == (mixed, None)
    # Only with the rule named.
    assert adjust(mixed, spot(["Qs", "Jc"]), {"nocatch"}) == (mixed, None)


def test_a_pair_folds_to_a_big_bet_from_a_player_not_read_as_aggressive():
    catch = {"CALL": 0.7, "FOLD": 0.3}
    # 100 into 100: the call is a third of what you can win.
    big = spot(["Kc", "9h"], to_call=100, pot=200)
    assert adjust(catch, big, BOTH) == ({"FOLD": 1.0}, "nocatch")
    assert adjust(catch, big, {"nobluff"}) == (catch, None)
    # Read as aggressive (bets or raises 60% of 200 decisions): call.
    assert adjust(catch, {**big, "reads": {"2": WILD}}, BOTH) == (catch, None)
    # A few aggressive decisions are pulled toward the AA players' share.
    few = {"hands": 20, "postflop": 10, "aggression": 0.6}
    assert adjust(catch, {**big, "reads": {"2": few}}, BOTH)[1] == "nocatch"
    # A small bet (30 into 100) pays the price.
    assert adjust(catch, spot(["Kc", "9h"], to_call=30, pot=130), BOTH) == (catch, None)
    # Two pair of your own calls.
    two_pair = spot(["Ac", "Ks"], to_call=100, pot=200)
    assert adjust(catch, two_pair, BOTH) == (catch, None)
    # Already folding: nothing changed.
    assert adjust({"FOLD": 1.0}, big, BOTH) == ({"FOLD": 1.0}, None)


def test_a_raise_of_your_bet_is_folded_to_even_at_a_small_price():
    # You bet 20, raised to 50: 30 to call into 120.
    raised = spot(["Kc", "9h"], to_call=30, pot=120, mine=20)
    assert adjust({"CALL": 1.0}, raised, BOTH) == ({"FOLD": 1.0}, "nocatch")


def test_only_the_heads_up_river():
    mixed = {"CHECK": 0.5, "BET 50.000000": 0.5}
    turn = spot(["Qs", "Jc"], board=BOARD[:4], street="turn")
    assert adjust(mixed, turn, BOTH) == (mixed, None)
    multiway = spot(["Qs", "Jc"], folded=())
    assert adjust(mixed, multiway, BOTH) == (mixed, None)


def test_rules_are_named_and_off_in_the_window():
    assert rules_of(["nocatch", "nobluff"]) == BOTH
    assert rules_of([]) == frozenset() and LIVE == frozenset()
    with pytest.raises(ValueError):
        rules_of(["nobluf"])


def test_counts_include_the_wrapped_policys():
    class Kept:
        def __init__(self, counts, base=None):
            self.counts, self.base = counts, base

    outer = Kept({"decided": 3}, Kept({"solved": 2, "style_nobluff": 1}, Kept({})))
    assert _counts(outer) == {"decided": 3, "solved": 2, "style_nobluff": 1}


def test_a_straight_or_flush_the_board_makes_is_nothing_of_your_own():
    # Code check 10/16: two blanks on a straight board play the board, and a
    # solver bet there is a bluff that nobluff should take away.
    from poker_engine.scoreboard.style_rules import nothing
    assert nothing(["Kc", "2d"], ["5h", "6d", "7c", "8s", "9h"])
    assert nothing(["Kc", "3d"], ["Ah", "Jh", "7h", "4h", "2h"])
    assert not nothing(["Th", "2d"], ["5h", "6d", "7c", "8s", "9h"])   # higher
    assert not nothing(["Kh", "3d"], ["Ah", "Jh", "7h", "4h", "2h"])   # bigger flush
