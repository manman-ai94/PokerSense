"""All-in EV replaces the runout with its exact or sampled average."""

from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from poker_engine.scoreboard.allin_ev import runout_ev, settle
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RAKED = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


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
    # The main pot's expected shares: the aces' chance of winning it.
    returns, shares = runout_ev(table, main_pot=True)
    assert returns == expected
    assert shares == pytest.approx({0: 42 / 44, 1: 2 / 44})


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


def raked(table):
    raw = json.loads(RAKED.read_text(encoding="utf-8"))
    table.rules = AARuleProfileV2.from_dict(raw)
    return table


def test_rake_comes_out_of_the_winners_share():
    # 5% of the 200 pot is 10, which is also the cap (5 big blinds of 2).
    table = raked(arena([["Ah", "As"], ["Kh", "Ks"]], ["2c", "7d", "9s", "Jc", "Kd"],
                        "turn", [100, 100]))
    expected = runout_ev(table)
    assert expected[0] == pytest.approx(190 * 42 / 44 - 100)
    assert expected[1] == pytest.approx(190 * 2 / 44 - 100)
    assert sum(expected.values()) == pytest.approx(-10)


def test_rake_is_on_the_called_pot_capped_and_rounded_down():
    board = ["2c", "7d", "9s", "Jc", "Kd"]
    holes = [["Ah", "As"], ["Kh", "Ks"]]
    # 50 of seat 0's 150 is uncalled and goes back: 5% of 200 is 10.
    uncalled = runout_ev(raked(arena(holes, board, "turn", [150, 100])))
    assert sum(uncalled.values()) == pytest.approx(-10)
    # 5% of 42 is 2.1, rounded down to 2.
    small = runout_ev(raked(arena(holes, board, "turn", [21, 21])))
    assert sum(small.values()) == pytest.approx(-2)
    # 5% of 600 is 30, capped at 10.
    big = runout_ev(raked(arena(holes, board, "turn", [300, 300])))
    assert sum(big.values()) == pytest.approx(-10)


def test_settle_takes_the_rake_share_from_every_contested_layer():
    result = settle([100.0, 50.0, 100.0], {0: 2000, 1: 10, 2: 3000}, rake_share=0.1)
    assert result == pytest.approx([-10.0, 85.0, -100.0])
