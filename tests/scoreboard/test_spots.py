"""Decision kinds shared by the PHH statistics and the population bot."""

import pytest

from poker_engine.scoreboard.spots import postflop_spot, preflop_spot


@pytest.mark.parametrize("actions, me, expected", [
    ([], 3, "rfi"),
    ([(3, "f"), (4, "c")], 5, "vs_limp"),
    ([(3, "f"), (4, "r")], 5, "vs_open"),
    ([(3, "c"), (4, "r"), (5, "r")], 6, "vs_3bet_cold"),
    ([(3, "c"), (4, "r")], 3, "limp_vs_raise"),
    ([(3, "r"), (5, "c"), (6, "r")], 5, "call_vs_3bet"),
    ([(3, "r"), (4, "r")], 3, "open_vs_3bet"),
    ([(3, "r"), (5, "r"), (3, "r")], 5, "3bet_vs_4bet"),
])
def test_preflop_spot(actions, me, expected):
    assert preflop_spot(actions, me) == expected


@pytest.mark.parametrize("street, actions, me, opponents, aggressor, expected", [
    ("flop", [], 4, 1, 4, "flop|hu|pfa|checked_to"),
    ("flop", [(1, "c")], 4, 2, 4, "flop|multi|pfa|checked_to"),
    ("turn", [(1, "c"), (4, "r")], 1, 2, 4, "turn|multi|other|facing_bet"),
    ("river", [(1, "r"), (4, "r")], 1, 1, None, "river|hu|other|facing_raise"),
    ("river", [(1, "r"), (4, "r"), (1, "r")], 4, 1, 4, "river|hu|pfa|facing_raise"),
])
def test_postflop_spot(street, actions, me, opponents, aggressor, expected):
    assert postflop_spot(street, actions, me, opponents, aggressor) == expected
