"""The card-luck table: fitted on simulated hands, checked on others."""

import json
from pathlib import Path

import pytest

from poker_engine.scoreboard import luck
from poker_engine.scoreboard.strength import all_classes, class_combos
from tools import build_luck_table as build

RULES = json.loads(Path(build.DEFAULT_RULES).read_text(encoding="utf-8"))


def made_up(scale=lambda seat: seat + 1):
    """Every class at every seat (a deal per seat): worth its rank, times the
    seat's scale, plus what the seat itself is worth."""
    base = luck.centered({name: -index for index, name in enumerate(all_classes())})
    return [(seat, seat, name, scale(seat) * base[name] + seat, 0.0)
            for seat in range(luck.SEATS) for name in all_classes()]


def test_the_fit_finds_each_seats_slope_and_centres_the_classes():
    classes, slopes = build.fit(made_up())
    assert sum(class_combos(name) * value for name, value in classes.items()) == \
        pytest.approx(0, abs=1e-9)
    assert classes["AA"] > classes["KK"] > classes["32o"]
    assert [slope / slopes[0] for slope in slopes] == pytest.approx(range(1, 9))
    # Slope times class value gives back how much one class is worth more
    # than another at the same seat.
    worth = {(seat, name): value for seat, _, name, value, _ in made_up()}
    for seat in (0, 5):
        assert slopes[seat] * (classes["AA"] - classes["72o"]) == pytest.approx(
            worth[seat, "AA"] - worth[seat, "72o"], rel=1e-3)


def test_the_fit_needs_every_class():
    with pytest.raises(ValueError, match="play more deals"):
        build.fit(made_up()[:100])


def test_the_check_reports_the_spread_and_the_card_lucks_average():
    hands = made_up()
    classes, slopes = build.fit(hands)
    hands = [(deal, seat, name, value, value + (200 if deal % 2 else -200))
             for deal, seat, name, value, _ in hands]
    found = build.check(hands, {"classes": classes, "slopes": slopes})
    assert found["hands"] == len(hands) and found["deals"] == luck.SEATS
    spread = found["spread_per_hand_bb"]
    assert spread["both_taken_out"] < spread["runout_taken_out"] < spread["as_dealt"]
    assert found["fewer_hands"]["both"] > found["fewer_hands"]["runout"] > 1


def test_a_deal_gives_a_hand_from_every_seat():
    hands = build.play(RULES, "aa_preflop", ("aa_cal",), [1, 2], 9)
    assert len(hands) == 16
    assert {seat for _, seat, *_ in hands} == set(range(luck.SEATS))
    assert all(name in all_classes() for _, _, name, *_ in hands)
    # A stack is 100 big blinds: no hand wins or loses more.
    assert all(-100 <= value <= 800 and -100 <= came <= 800
               for *_, value, came in hands)
