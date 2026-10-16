"""Winners' profiles from synthetic PHH hands."""

from collections import Counter
import pickle
import tomllib
import zipfile

import pytest

from tools.phh_winner_profiles import (MIN_GROUP, Row, count_file, count_hand,
                                       groups_of, settle, summarize, win_rate)

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


def hand():
    return tomllib.loads(HAND)["1"]


def test_a_hand_is_settled_and_counted_per_player(tmp_path):
    archive = tmp_path / "phh.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("data/handhq/sample.phhs", HAND)
    rows, counts = count_file((archive, "data/handhq/sample.phhs"))
    assert counts == Counter({"hands": 1, "net_source|settled_no_rake": 1})
    rows = pickle.loads(pickle.dumps(rows))          # as a worker hands them back
    b, c, g = rows[("b", 2.0)], rows[("c", 2.0)], rows[("g", 2.0)]
    # The big blind wins the 209 chip pot with aces and twos: 113 chips up.
    assert b.net == pytest.approx(56.5) and c.net == pytest.approx(-48)
    assert g.net == pytest.approx(-8) and rows[("a", 2.0)].net == pytest.approx(-0.5)
    assert c.get("rfi_opp") == c.get("rfi_raise") == c.get("pfr") == c.get("vpip") == 1
    assert c.get("cbet_multi_opp") == c.get("cbet_multi") == 1
    assert b.get("vs_raise_opp") == b.get("vs_raise_call") == 1 and b.get("pfr") == 0
    d = rows[("d", 2.0)]
    assert d.get("vs_raise_opp") == 1 and d.get("vpip") == 0
    assert g.get("vs_cbet_opp") == 1 and g.get("fold_to_cbet") == 0
    # The check-raise to 80 into 69 is a big river bet, shown as two pair.
    assert b.get("river_big_bets") == b.get("river_big_shown") == 1
    assert b.get("river_big_strong") == 1
    assert b.get("river_aggressive") == 1 and b.get("flop_calls") == 1
    assert g.get("vs_river_bet_opp") == g.get("fold_to_river_bet") == 1
    assert g.get("vs_river_big_opp") == 0
    assert b.get("showdowns") == c.get("showdowns") == 1
    assert b.get("won_showdown") == 1 and c.get("won_showdown") == 0
    seen = [rows[(n, 2.0)].get("saw_flop") for n in "abcdefg"]
    assert seen == [0, 1, 1, 0, 0, 0, 1]


def test_finishing_stacks_win_over_settling():
    data = {**hand(), "finishing_stacks": [199, 300, 110, 200, 200, 200, 191]}
    rows, counts = {}, Counter()
    assert count_hand(data, rows, counts)
    assert counts["net_source|finishing_stacks"] == 1
    assert rows[("b", 2.0)].net == 50 and rows[("c", 2.0)].net == -45


def test_side_pots_and_an_uncalled_bet():
    # Player 0 all in for 50, players 1 and 2 put 150 each, player 3 folded.
    # Without player 3, a 400 bet nobody matched gets 250 back.
    board = ["Ah", "Kd", "2c", "7s", "3d"]
    shown = {0: ["As", "Ac"], 1: ["Kh", "Kc"], 2: ["Qs", "Js"]}
    net = settle([50, 150, 150, 0], {3}, shown, board)
    # Main pot 150 to the aces; side pot 200 to the kings.
    assert net == [100, 50, -150, 0]
    assert settle([50, 150, 400], set(), shown, board) == [100, 50, -150]
    assert settle([50, 150], set(), {}, board) is None       # nobody shown


def test_win_rates_and_groups():
    row = Row()
    for result in [1.0, -0.5] * 50:
        row.add("net_hands")
        row.net += result
        row.net_sq += result * result
    rate = win_rate(row)
    assert rate[0] == pytest.approx(25.0) and rate[1] > 0
    assert groups_of(rate) == ["all", "winner", "big_winner"]
    assert groups_of((-3.0, -6.0, -1.0)) == ["all", "loser"]
    assert groups_of((1.0, -2.0, 4.0)) == ["all", "even"]


def test_groups_with_too_few_players_are_left_out():
    def player(result, hands=10):
        row = Row()
        row.add("hands", hands)
        row.add("vpip", 3)
        for i in range(hands):
            value = result + (1 if i % 2 else -1)
            row.add("net_hands")
            row.net += value
            row.net_sq += value * value
        return row
    rows = {(f"w{i}", 0.1): player(5.0) for i in range(MIN_GROUP)}
    rows[("l0", 0.1)] = player(-5.0)
    out = summarize(rows, min_hands=10)
    assert set(out) == {"bb=0.1", "low"}
    groups = out["low"]
    assert set(groups) == {"all", "winner", "big_winner"}     # one loser: not written
    assert groups["winner"]["players"] == MIN_GROUP
    assert groups["all"]["vpip"]["share"] == 0.3
    assert groups["winner"]["bb_per_100_median"] == pytest.approx(500.0)


def test_a_player_at_two_low_stakes_is_one_player_in_low():
    # Code check 10/16: the pooled "low" stake had one member per (player,
    # stake) row, so a player at NL25 and NL50 counted twice.
    def player(result, hands=10):
        row = Row()
        row.add("hands", hands)
        row.add("vpip", 3)
        for i in range(hands):
            value = result + (1 if i % 2 else -1)
            row.add("net_hands")
            row.net += value
            row.net_sq += value * value
        return row

    count = MIN_GROUP
    rows = {(f"w{i}", stake): player(5.0) for i in range(count)
            for stake in (0.25, 0.5)}
    out = summarize(rows, min_hands=10)
    assert out["low"]["winner"]["players"] == count
    assert out["bb=0.25"]["winner"]["players"] == count
    # Fewer distinct players than MIN_GROUP: no low group at all.
    few = {key: row for key, row in rows.items() if key[0] != "w0"}
    assert "winner" not in summarize(few, min_hands=10).get("low", {})
