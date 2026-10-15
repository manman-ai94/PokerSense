"""Luck taken out of a result: the cards dealt and the all-in runout."""

from itertools import combinations
import math

import pytest

from poker_engine.scoreboard import luck
from poker_engine.scoreboard.allin_ev import settle
from poker_engine.scoreboard.strength import DECK, all_classes, class_combos


def test_tables_of_four_to_eight_map_onto_the_eight_seats():
    assert [luck.table_position(i, 8) for i in range(8)] == list(range(8))
    # Blinds and straddle stay; the rest count back from the dealer.
    assert [luck.table_position(i, 4) for i in range(4)] == [0, 1, 2, 7]
    assert [luck.table_position(i, 6) for i in range(6)] == [0, 1, 2, 5, 6, 7]
    assert luck.table_position(0, 3) is None and luck.table_position(0, 9) is None
    assert luck.table_position(6, 6) is None


def test_seats_are_ordered_from_the_small_blind_to_the_dealer():
    assert luck.seat_order([5, 0, 2, 4], 4) == [5, 0, 2, 4]
    assert luck.seat_order([0, 2, 4, 5], 2) == [4, 5, 0, 2]


def test_the_table_covers_every_class_and_seat():
    table = luck.load_table()
    assert set(table["classes"]) == set(all_classes())
    assert len(table["slopes"]) == luck.SEATS == len(table["seats"])
    assert table["unit"] == "big blinds"


@pytest.mark.parametrize("position", range(luck.SEATS))
def test_card_luck_averages_zero_over_every_hand_that_can_be_dealt(position):
    """Exactly zero at every seat: taking it out cannot change a result on
    average, whatever the player does with the cards."""
    total = sum(luck.hole_luck(list(cards), position)
                for cards in combinations(DECK, 2))
    assert total / 1326 == pytest.approx(0, abs=1e-9)


def test_centering_weights_each_class_by_its_combinations():
    found = luck.centered({name: float(name == "AA") for name in all_classes()})
    assert sum(class_combos(name) * value for name, value in found.items()) == \
        pytest.approx(0, abs=1e-12)
    assert found["AA"] - found["72o"] == pytest.approx(1.0)


def test_strong_cards_are_lucky_and_weak_ones_unlucky():
    assert luck.hole_luck(["Ah", "Ad"], 7) > 0 > luck.hole_luck(["7c", "2d"], 7)


def test_a_turn_all_in_is_scored_against_every_river():
    # Aces against kings on 2c 7d 9h Js; the river is the last king.
    board = ["2c", "7d", "9h", "Js", "Kd"]
    holes = {0: ["Ah", "Ad"], 1: ["Kc", "Ks"]}
    actual, expected = luck.runout_luck([100.0, 100.0], holes, board, "turn")
    assert actual == [-100.0, 100.0]
    # 44 rivers; the aces lose to Kd and Kh.
    assert expected[0] == pytest.approx(100 * 42 / 44 - 100 * 2 / 44)
    assert sum(expected) == pytest.approx(0)


def test_runout_luck_averages_zero_over_the_boards_that_could_come():
    holes = {0: ["Ah", "Kh"], 2: ["Qc", "Qd"]}
    flop = ["2h", "7h", "9c"]
    contributions = [60.0, 7.0, 60.0]           # seat 1 folded, its chips stay in
    seen = set(flop) | {card for cards in holes.values() for card in cards}
    lucks = []
    for turn, river in combinations([card for card in DECK if card not in seen], 2):
        actual, expected = luck.runout_luck(contributions, holes,
                                            flop + [turn, river], "flop", 0.05)
        lucks.append(actual[0] - expected[0])
        assert actual == settle(contributions, _ranks(holes, flop + [turn, river]),
                                0.05)
    assert sum(lucks) / len(lucks) == pytest.approx(0, abs=1e-9)
    assert actual[1] == expected[1] == -7.0      # the folded seat has no luck


def _ranks(holes, board):
    from poker_engine.scoreboard.strength import _EVALUATE_7, CARD_ID
    return {player: _EVALUATE_7(*(CARD_ID[c] for c in cards + board))
            for player, cards in holes.items()}


def test_nothing_to_come_is_no_runout():
    holes = {0: ["Ah", "Ad"], 1: ["Kc", "Ks"]}
    board = ["2c", "7d", "9h", "Js", "Kd"]
    assert luck.runout_luck([10.0, 10.0], holes, board, "river") is None
    assert luck.runout_luck([10.0, 10.0], {0: holes[0]}, board, "flop") is None


def test_a_preflop_all_in_samples_boards_the_same_way_each_time():
    holes = {0: ["Ah", "Ad"], 1: ["Kc", "Ks"]}
    board = ["2c", "7d", "9h", "Js", "Kd"]
    one = luck.runout_luck([100.0, 100.0], holes, board, "preflop", seed=3)
    assert one == luck.runout_luck([100.0, 100.0], holes, board, "preflop", seed=3)
    # Aces win about 82% against kings.
    assert 0.78 < (one[1][0] + 100) / 200 < 0.86


def test_the_always_valid_interval_is_wider_than_one_look():
    values = [(-1) ** i * (i % 7) for i in range(luck.TUNED)]
    mean, plain = luck.interval(values)
    same, valid = luck.always_valid(values)
    assert same == pytest.approx(mean)
    assert 1.4 < valid / plain < 1.7            # tightest here: about 1.55 times
    assert luck.always_valid([1.0]) == (1.0, None)
    assert luck.always_valid([2.0, 2.0]) == (2.0, 0.0)


def test_hands_for_is_the_first_count_whose_interval_is_narrow_enough():
    count = luck.hands_for(20.0, 1.0)
    width = _width(20.0, count)
    assert width <= 1.0 < _width(20.0, count - 1)
    assert luck.hands_for(20.0, 0.5) > 4 * count * 0.9


def _width(spread, count):
    level = -2 * math.log(luck.ALPHA)
    rho = luck.TUNED * spread ** 2 / (level + math.log(1 + level))
    spent = count * spread ** 2
    return math.sqrt((spent + rho) * (math.log(spent / rho + 1) + level)) / count
