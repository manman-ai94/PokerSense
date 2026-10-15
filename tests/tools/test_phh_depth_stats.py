"""Price and depth counts from synthetic PHH hands (the real dataset is not needed)."""

from collections import Counter
import json
import zipfile

import pytest

from tools.phh_depth_stats import (POSTFLOP_DEPTHS, PREFLOP_DEPTHS, PRICES, bucket,
                                   count_file, count_hand, effective, main)

# Seat 3 opens to 6, seat 7 (30 chips) and the big blind (30) call. Flop,
# 19 in the pot: the big blind checks, seat 3 bets 10, seat 7 calls, the big
# blind raises all in to 24; seat 3 folds, seat 7 calls its last 14 all in.
HAND = """
[1]
variant = "NT"
antes = [0, 0, 0, 0, 0, 0, 0]
blinds_or_straddles = [1, 2, 0, 0, 0, 0, 0]
min_bet = 2
starting_stacks = [200, 30, 200, 200, 200, 200, 30]
actions = [
  "d dh p1 ????", "d dh p2 ????", "d dh p3 ????", "d dh p4 ????",
  "d dh p5 ????", "d dh p6 ????", "d dh p7 ????",
  "p3 cbr 6", "p4 f", "p5 f", "p6 f", "p7 cc", "p1 f", "p2 cc",
  "d db AhKd2c",
  "p2 cc", "p3 cbr 10", "p7 cc", "p2 cbr 24", "p3 f", "p7 cc",
  "d db 7s", "d db 3d",
]

[2]
variant = "NT"
antes = [1, 1, 1, 1, 1, 1, 1]
blinds_or_straddles = [1, 2, 0, 0, 0, 0, 0]
min_bet = 2
starting_stacks = [200, 200, 200, 200, 200, 200, 200]
actions = ["p3 f"]
"""


def test_buckets_and_the_effective_stack():
    assert bucket(0.05, PRICES) == "p00" and bucket(0.33, PRICES) == "p30"
    assert bucket(0.9, PRICES) == "p45"
    assert bucket(100, PREFLOP_DEPTHS) == "bb100"
    assert bucket(500, PREFLOP_DEPTHS) == "bb150"
    assert bucket(0.7, POSTFLOP_DEPTHS) == "spr0.5"
    # 200 behind, but the deepest other player still in has 40: 40 is at risk.
    assert effective(0, [200, 40, 30], [0, 0, 0], set()) == 40
    assert effective(0, [200, 40, 300], [0, 0, 0], {2}) == 40
    assert effective(1, [200, 40, 30], [6, 2, 0], set()) == 38


def test_every_decision_is_counted_by_price_and_depth(tmp_path):
    archive = tmp_path / "phh.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("data/handhq/sample.phhs", HAND)
    counts = count_file((archive, "data/handhq/sample.phhs"))
    assert counts == Counter({
        # Seat 3 first in facing the big blind: 2 to call into 3; 200 at risk.
        "rfi|p40|bb100|0|raise": 1,
        # Three folds facing 6 into 9 (6 / 15 = 0.4).
        "vs_open|p40|bb100|0|fold": 3,
        "vs_open|p40|bb15|0|call": 1,               # seat 7: 30 chips, 15 bb
        "vs_open|p25|bb60|0|fold": 1,               # small blind: 5 into 15
        "vs_open|p20|bb00|0|call": 1,               # big blind: 4 into 15, 28 left
        # Flop, pot 19: at most 24 more at risk for everyone (SPR 1.3).
        "flop|multi|other|checked_to|-|spr1|0|check": 1,
        "flop|multi|pfa|checked_to|-|spr1|0|bet:s40": 1,          # 10 into 19
        "flop|multi|other|facing_bet|p25|spr0.5|0|call": 1,       # 10 into 29
        "flop|multi|other|facing_bet|p20|spr0.5|0|raise": 1,      # 10 into 39
        # 14 more into 63 with 14 left at risk: seat 7's call is all in.
        "flop|multi|pfa|facing_raise|p15|spr0|0|fold": 1,
        "flop|hu|other|facing_raise|p15|spr0|1|call": 1,
        "hands": 1,
    })


def test_hands_out_of_scope_are_skipped():
    hand = {"starting_stacks": [200] * 5, "antes": [0] * 5,
            "blinds_or_straddles": [1, 2, 0, 0, 0], "actions": ["p3 f"]}
    counts = Counter()
    assert count_hand(hand, counts) is False
    assert not counts


def test_writes_only_counts(tmp_path, monkeypatch):
    archive = tmp_path / "phh.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("data/handhq/sample.phhs", HAND)
    out = tmp_path / "depth.json"
    monkeypatch.setattr("tools.phh_depth_stats.ProcessPoolExecutor",
                        pytest.importorskip("concurrent.futures").ThreadPoolExecutor)
    main(["--zip", str(archive), "--out", str(out), "--workers", "1"])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["hands"] == 1 and report["files_read"] == 1
    assert sum(report["counts"].values()) == 13
    assert set(report) == {"schema_version", "source", "files_read", "hands",
                           "skipped_malformed", "scope", "buckets", "counts"}
