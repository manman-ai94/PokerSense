"""AA insurance against the table's odds: it loses chips on average."""

import json
from pathlib import Path

import pytest

from poker_engine.strategy.aa_insurance import (
    ODDS, loss_range, premium_return, unseen_cards,
)

CASE = (Path(__file__).parents[1] / "fixtures" / "aa_reference_hands"
        / "insurance_32880_v1.json")


def test_the_reviewed_hand_pays_premium_times_odds():
    quote = json.loads(CASE.read_text(encoding="utf-8"))["quote"]
    outs, premium = quote["outs"], float(quote["premium"])
    assert ODDS[outs] == float(quote["odds_multiplier"])
    assert int(premium * ODDS[outs]) == int(quote["displayed_compensation"])
    # 52 - 4 board - 2 hands in the pot - 4 other cards shown = 40 unseen.
    assert unseen_cards(4, 2, shown=4) == 40
    assert premium_return(outs, 40) == pytest.approx(13 / 40 * 1.8)


def test_every_quote_is_worse_than_fair():
    for outs in ODDS:
        for board in (3, 4):
            for players in (2, 3):
                unseen = unseen_cards(board, players)
                assert ODDS[outs] < (unseen - outs) / outs
                assert premium_return(outs, unseen) < 1
                assert premium_return(outs, unseen, premium_back=True) < 1


def test_what_the_window_says_it_loses():
    # "通常亏掉保费的 2 到 5 成": with nobody else's cards shown.
    low, high = loss_range()
    assert (round(low, 3), round(high, 3)) == (0.238, 0.538)
    assert 0.2 <= low and high < 0.55
    # Many cards turned over by players who folded make the odds less bad.
    assert loss_range(shown=6)[0] < 0.2


def test_outside_the_table_is_refused():
    with pytest.raises(ValueError):
        premium_return(17, 44)
    with pytest.raises(ValueError):
        premium_return(5, 5)
