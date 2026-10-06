"""Population counts from synthetic PHH hands (the real dataset is not needed)."""

from collections import Counter
import zipfile

import pytest

from tools.phh_population_stats import count_file, count_hand, frequencies, position

HAND = """
[1]
variant = "NT"
antes = [0, 0, 0, 0, 0, 0, 0]
blinds_or_straddles = [1, 2, 0, 0, 0, 0, 0]
min_bet = 2
starting_stacks = [200, 200, 200, 200, 200, 200, 200]
actions = [
  "d dh p1 ????", "d dh p2 ????", "d dh p3 ????", "d dh p4 ????",
  "d dh p5 ????", "d dh p6 ????", "d dh p7 ????",
  "p3 f", "p4 cbr 6", "p5 f", "p6 f", "p7 cc", "p1 f", "p2 cc",
  "d db AhKd2c",
  "p2 cc", "p4 cbr 8", "p7 f", "p2 cbr 30", "p4 f",
]

[2]
variant = "NT"
antes = [1, 1, 1, 1, 1, 1, 1]
blinds_or_straddles = [1, 2, 0, 0, 0, 0, 0]
min_bet = 2
starting_stacks = [200, 200, 200, 200, 200, 200, 200]
actions = ["p3 f"]
"""


def test_positions_count_back_from_the_button():
    assert [position(i, 9) for i in range(9)] == [
        "SB", "BB", "EP", "EP", "EP", "LJ", "HJ", "CO", "BTN"]
    assert [position(i, 6) for i in range(6)] == ["SB", "BB", "LJ", "HJ", "CO", "BTN"]


def test_every_decision_is_counted_in_its_spot(tmp_path):
    archive = tmp_path / "phh.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("data/handhq/sample.phhs", HAND)
    counts = count_file((archive, "data/handhq/sample.phhs"))
    assert counts == Counter({
        "7-9|EP|rfi|fold": 1, "7-9|LJ|rfi|raise": 1,
        "7-9|HJ|vs_open|fold": 1, "7-9|CO|vs_open|fold": 1,
        "7-9|BTN|vs_open|call": 1, "7-9|SB|vs_open|fold": 1,
        "7-9|BB|vs_open|call": 1,
        "7-9|flop|multi|other|checked_to|check": 1,
        "7-9|flop|multi|pfa|checked_to|bet": 1,
        "7-9|flop|multi|other|facing_bet|fold": 1,
        # The big blind checked first; facing the bet is counted too, and
        # with the button gone it is heads-up.
        "7-9|flop|hu|other|facing_bet|raise": 1,
        "7-9|flop|hu|pfa|facing_raise|fold": 1,
        "7-9|hands": 1,
    })


@pytest.mark.parametrize("change", [
    {"antes": [1] * 7},
    {"blinds_or_straddles": [1, 2, 4, 0, 0, 0, 0]},
    {"starting_stacks": [200] * 5, "antes": [0] * 5,
     "blinds_or_straddles": [1, 2, 0, 0, 0]},
])
def test_hands_out_of_scope_are_skipped(change):
    hand = {"starting_stacks": [200] * 7, "antes": [0] * 7,
            "blinds_or_straddles": [1, 2, 0, 0, 0, 0, 0], "actions": ["p3 f"]}
    hand.update(change)
    counts = Counter()
    assert count_hand(hand, counts) is False
    assert not counts


def test_hands_with_a_missing_blind_are_skipped():
    hand = {"starting_stacks": [200] * 6, "antes": [0] * 6,
            "blinds_or_straddles": [2, 0, 0, 0, 0, 0],
            "actions": ["p2 f", "p3 f", "p4 f", "p5 f", "p6 f"]}
    counts = Counter()
    assert count_hand(hand, counts) is False
    assert counts == Counter({"skipped_missing_blind": 1})


def test_frequencies_are_shares_and_pool_positions():
    counts = Counter({"7-9|EP|rfi|fold": 3, "7-9|EP|rfi|raise": 1,
                      "7-9|BTN|rfi|raise": 4,
                      "7-9|flop|hu|pfa|checked_to|bet": 7,
                      "7-9|flop|hu|pfa|checked_to|check": 3, "7-9|hands": 9})
    result = frequencies(counts)["7-9"]
    assert result["EP|rfi"] == {"n": 4, "fold": 0.75, "raise": 0.25}
    assert result["ALL|rfi"] == {"n": 8, "fold": 0.375, "raise": 0.625}
    assert result["flop|hu|pfa|checked_to"] == {"n": 10, "bet": 0.7, "check": 0.3}
    assert "hands" not in result
