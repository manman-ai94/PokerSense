"""Preflop ranking, Monte Carlo equity and range equity for scoreboard bots."""

import random

import pytest

from poker_engine.scoreboard.strength import (
    DECK, all_classes, class_combos, combo_percentile, equity, hand_class,
    preflop_percentile, preflop_table, range_equity)


def test_hand_classes_cover_every_starting_hand():
    names = all_classes()
    assert len(names) == len(set(names)) == 169
    assert sum(class_combos(name) for name in names) == 1326
    assert hand_class(["Kd", "Ad"]) == "AKs" and hand_class(["Ah", "Kd"]) == "AKo"
    assert hand_class(["7c", "7s"]) == "77"


def test_preflop_ranking_orders_known_hands():
    assert preflop_percentile(["As", "Ah"]) == round(6 / 1326, 4)
    assert (preflop_percentile(["As", "Kh"]) < preflop_percentile(["Ts", "9s"])
            < preflop_percentile(["7c", "2d"]))
    table = preflop_table()["classes"]
    assert max(row["percentile"] for row in table.values()) == 1.0
    assert table["32o"]["rank"] == 169


def test_combinations_spread_evenly_inside_their_class():
    by_class = {}
    for index, first in enumerate(DECK):
        for second in DECK[index + 1:]:
            cards = [first, second]
            by_class.setdefault(hand_class(cards), []).append(combo_percentile(cards))
    for name, places in by_class.items():
        top = preflop_percentile(cards_of(name))
        steps = sorted(round((top - place) * 1326, 6) for place in places)
        assert steps == [i + 0.5 for i in range(class_combos(name))]
    assert combo_percentile(["Ks", "As"]) == combo_percentile(["As", "Ks"])


def cards_of(name):
    return [name[0] + "s", name[1] + ("s" if name.endswith("s") else "d")]


def test_equity_against_random_hands():
    rng = random.Random(3)
    assert abs(equity(["As", "Ah"], [], 1, 4000, rng) - 0.85) < 0.02
    assert equity(["As", "Ah"], [], 0, 10, rng) == 1.0
    made = equity(["As", "Ah"], ["Ad", "Ac", "2s", "7h", "9d"], 3, 200, rng)
    assert made == 1.0            # four aces on a dry river cannot lose


def test_equity_against_a_weighted_range_on_the_river_and_the_turn():
    river = ("2c", "3c", "4d", "7s", "9h")
    aces = ("Ah", "Ad")
    assert range_equity(aces, river, {"KhKd": 1.0}) == (1.0, 1)
    assert range_equity(aces, river, {"AsAc": 1.0}) == (0.5, 1)       # a tie
    # Weights count: kings three times as likely as the other aces.
    value, hands = range_equity(aces, river, {"KhKd": 3.0, "AsAc": 1.0})
    assert hands == 2 and value == pytest.approx((3 * 1 + 0.5) / 4)
    # A hand using one of your cards or a board card cannot be his.
    assert range_equity(aces, river, {"AhKd": 1.0, "9c9d": 1.0}) == (0.0, 1)
    assert range_equity(aces, river, {"AhKd": 1.0}) == (None, 0)
    # On the turn every river card is dealt: 2 of the 44 left give him kings.
    value, hands = range_equity(aces, river[:4], {"KhKd": 1.0})
    assert hands == 1 and value == pytest.approx(42 / 44)
    with pytest.raises(ValueError):
        range_equity(aces, river[:3], {"KhKd": 1.0})
