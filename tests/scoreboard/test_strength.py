"""Preflop ranking and Monte Carlo equity for scoreboard bots."""

import random

from poker_engine.scoreboard.strength import (
    all_classes, class_combos, equity, hand_class, preflop_percentile, preflop_table)


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


def test_equity_against_random_hands():
    rng = random.Random(3)
    assert abs(equity(["As", "Ah"], [], 1, 4000, rng) - 0.85) < 0.02
    assert equity(["As", "Ah"], [], 0, 10, rng) == 1.0
    made = equity(["As", "Ah"], ["Ad", "Ac", "2s", "7h", "9d"], 3, 200, rng)
    assert made == 1.0            # four aces on a dry river cannot lose
