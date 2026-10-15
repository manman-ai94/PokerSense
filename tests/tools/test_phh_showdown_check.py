"""Showdown hands behind postflop bets, from synthetic PHH hands."""

from collections import Counter
import zipfile

from tools.phh_showdown_check import (category, count_file, count_hand, player_bucket,
                                      shares, size_bucket, wilson)

HAND = """
[1]
variant = "NT"
antes = [0, 0, 0, 0, 0, 0, 0]
blinds_or_straddles = [1, 2, 0, 0, 0, 0, 0]
min_bet = 2
starting_stacks = [200, 200, 200, 200, 200, 200, 200]
players = ["a", "b", "c", "d", "e", "f", "g"]
actions = [
  "d dh p1 ????", "d dh p2 ????", "d dh p3 ????", "d dh p4 ????",
  "d dh p5 ????", "d dh p6 ????", "d dh p7 ????",
  "p3 cbr 6", "p4 f", "p5 f", "p6 f", "p7 cc", "p1 f", "p2 cc",
  "d db AhKd2c",
  "p2 cc", "p3 cbr 10", "p7 cc", "p2 cc",
  "d db 7s",
  "p2 cc", "p3 cc", "p7 cc",
  "d db 3d",
  "p2 cc", "p3 cbr 20", "p7 f", "p2 cbr 80", "p3 cc",
  "p2 sm Ad2d", "p3 sm KsQs",
]
"""

FLOP_BET = "flop|multi|pfa|bet|40-75%"
RIVER_BET = "river|multi|pfa|bet|40-75%"
CHECK_RAISE = "river|hu|other|check_raise|>110%"


def test_bets_and_raises_are_counted_with_the_hand_shown(tmp_path):
    archive = tmp_path / "phh.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("data/handhq/sample.phhs", HAND)
    counts = count_file((archive, "data/handhq/sample.phhs"))
    assert counts == Counter({
        # The preflop raiser bets 10 into 19 on the flop and 20 into 49 on
        # the river (three players still in), shows a pair of kings.
        f"{FLOP_BET}|all|events": 1, f"{FLOP_BET}|all|shown": 1,
        f"{FLOP_BET}|all|pair": 1,
        f"{RIVER_BET}|all|events": 1, f"{RIVER_BET}|all|shown": 1,
        f"{RIVER_BET}|all|pair": 1,
        # The big blind checked and raised 80 into 69 heads-up: aces and twos.
        f"{CHECK_RAISE}|all|events": 1, f"{CHECK_RAISE}|all|shown": 1,
        f"{CHECK_RAISE}|all|strong": 1,
        "hands": 1,
    })
    row = shares(counts)[f"{CHECK_RAISE}|all"]
    assert row["events"] == row["shown"] == 1
    assert row["strong"]["share"] == 1.0 and row["nothing"]["share"] == 0.0


def test_players_are_also_counted_in_their_bucket():
    import tomllib
    hand = tomllib.loads(HAND)["1"]
    counts = Counter()
    assert count_hand(hand, counts, names={"b": "passive"})
    assert counts[f"{CHECK_RAISE}|passive|strong"] == 1
    assert not any("|passive|" in key for key in counts if key.startswith("flop"))


def test_hands_with_antes_or_straddles_or_six_players_are_skipped():
    for change in ({"antes": [1] * 7}, {"blinds_or_straddles": [1, 2, 4, 0, 0, 0, 0]},
                   {"starting_stacks": [200] * 6}):
        hand = {"starting_stacks": [200] * 7, "antes": [0] * 7,
                "blinds_or_straddles": [1, 2, 0, 0, 0, 0, 0], "actions": []}
        hand.update(change)
        counts = Counter()
        assert count_hand(hand, counts, names={}) is False
        assert not counts


def test_categories_count_only_the_players_own_cards():
    assert category(["Ad", "2d"], ["Ah", "Kd", "2c", "7s", "3d"]) == "strong"
    assert category(["Ks", "Qs"], ["Ah", "Kd", "2c", "7s", "3d"]) == "pair"
    assert category(["Qs", "Jc"], ["Ah", "Kd", "2c", "7s", "3d"]) == "nothing"
    assert category(["Ah", "Qc"], ["7h", "7d", "2c", "9s", "Kh"]) == "nothing"
    assert category(["2h", "3c"], ["As", "Ks", "Qs", "Js", "Ts"]) == "nothing"


def test_buckets_and_sizes():
    assert player_bucket(49, 0) == "few"
    assert player_bucket(100, 10) == "passive"
    assert player_bucket(100, 30) == "normal"
    assert player_bucket(100, 50) == "aggressive"
    assert [size_bucket(x) for x in (0.3, 0.5, 1.0, 1.2)] == [
        "<40%", "40-75%", "75-110%", ">110%"]
    low, high = wilson(5, 10)
    assert low < 0.5 < high
