"""All-in EV replaces the runout with its exact or sampled average."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from poker_engine.scoreboard.allin_ev import runout_ev, settle


class Card:
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return self.text


def arena(holes, board, last_street, contributions, folded=(), rake="0"):
    return SimpleNamespace(
        terminal=True, rules=SimpleNamespace(rake_percent=Decimal(rake),
                                             minimum_chip=Decimal("1")),
        _seats=tuple(range(len(holes))), _history=[{"street": last_street}],
        _folded=set(folded), _contributions=contributions,
        _holes=[tuple(Card(c) for c in hole) for hole in holes],
        _state=SimpleNamespace(board_cards=[[Card(c)] for c in board]))


def test_settle_splits_layers_and_refunds_the_uncalled_part():
    # Seat 1 is all in for 50 and has the best hand: it wins the 150 main pot.
    # The 100 side pot between seats 0 and 2 goes to seat 0's better hand.
    result = settle([100.0, 50.0, 100.0], {0: 2000, 1: 10, 2: 3000})
    assert result == [0.0, 100.0, -100.0]
    # A tie splits; a folded player's chips stay in the pot.
    assert settle([10.0, 10.0, 4.0], {0: 5, 1: 5}) == [2.0, 2.0, -4.0]
    # Only one player paid the top layer: it is returned to them.
    assert settle([30.0, 10.0], {0: 9, 1: 1}) == [-10.0, 10.0]


def test_turn_all_in_is_averaged_over_every_river():
    # Aces against kings on 2c 7d 9s Jc: kings win only with the last two kings.
    table = arena([["Ah", "As"], ["Kh", "Ks"]], ["2c", "7d", "9s", "Jc", "Kd"],
                  "turn", [100, 100])
    expected = runout_ev(table)
    assert expected[0] == pytest.approx(200 * 42 / 44 - 100)
    assert expected[1] == pytest.approx(-(200 * 42 / 44 - 100))


def test_preflop_all_in_is_sampled_and_folded_seats_keep_their_loss():
    table = arena([["Ah", "As"], ["Kd", "Kc"], ["7h", "2d"]],
                  ["3c", "8d", "Ts", "4h", "Js"], "preflop", [100, 100, 3],
                  folded=[2])
    expected = runout_ev(table, samples=4000, seed=5)
    assert expected[2] == pytest.approx(-3)
    assert sum(expected.values()) == pytest.approx(0)
    share = (expected[0] + 100) / 203      # aces hold about 82%
    assert 0.79 < share < 0.85


@pytest.mark.parametrize("change", [
    {"last_street": "river"}, {"folded": [1]}])
def test_no_adjustment_without_a_runout(change):
    kwargs = {"holes": [["Ah", "As"], ["Kh", "Ks"]],
              "board": ["2c", "7d", "9s", "Jc", "Kd"], "last_street": "turn",
              "contributions": [100, 100], **change}
    assert runout_ev(arena(**kwargs)) is None


def test_raked_tables_are_refused():
    table = arena([["Ah", "As"], ["Kh", "Ks"]], ["2c", "7d", "9s", "Jc", "Kd"],
                  "turn", [100, 100], rake="0.03")
    with pytest.raises(ValueError):
        runout_ev(table)
