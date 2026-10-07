"""Tools of the AA preflop policy: AA player counts, equity table, tuning grid."""

import json

from tools import build_aa_preflop_stats, build_preflop_equity, tune_aa_preflop


def frame(hand_id, actions, complete=True):
    return {"fields": {"actions_v1": {
        "hand_id": hand_id, "complete": complete, "start": 1, "dealer": 7,
        "actions": [[i + 1, street, slot, kind, None, "reader"]
                    for i, (street, slot, kind) in enumerate(actions)]}}}


def test_aa_counts_take_complete_hands_by_kind_of_decision(tmp_path):
    rows = [
        # seat 3 limps, 4 raises, 5 folds, 3 calls the raise; flop not counted
        frame("a", [("preflop", 3, "call"), ("preflop", 4, "raise"),
                    ("preflop", 5, "fold"), ("preflop", 3, "call"),
                    ("flop", 3, "check")]),
        frame("b", [("preflop", 3, "raise")], complete=False),
    ]
    path = tmp_path / "m" / "frames.jsonl"
    path.parent.mkdir()
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    report = build_aa_preflop_stats.build([path])
    assert report["hands"] == 1 and report["sources"] == [{"log": "m", "hands": 1}]
    assert report["spots"] == {
        "rfi": {"n": 1, "raise": 0, "call": 1, "fold": 0},
        "vs_limp": {"n": 1, "raise": 1, "call": 0, "fold": 0},
        "vs_open": {"n": 1, "raise": 0, "call": 0, "fold": 1},
        "limp_vs_raise": {"n": 1, "raise": 0, "call": 1, "fold": 0}}


def test_equity_rows_count_card_removal_and_rank_hands():
    names = build_preflop_equity.class_order()
    index, equities, counts = build_preflop_equity.row((0, names, 50))
    assert names[0] == "AA" and index == 0
    assert sum(counts) == 1225                  # hands left besides a pair of aces
    assert counts[names.index("AA")] == 1 and counts[names.index("AKs")] == 2
    assert equities[names.index("72o")] > 0.6


def test_tuning_grid_names_every_combination():
    grid = tune_aa_preflop.parse_grid(["realize_ip=0.9,1", "crowd=0"])
    assert tune_aa_preflop.strategy_names("aa_preflop", grid) == [
        "aa_preflop@realize_ip=0.9:crowd=0", "aa_preflop@realize_ip=1:crowd=0"]
    assert tune_aa_preflop.strategy_names("aa_preflop", []) == ["aa_preflop"]


def test_tuning_ranks_settings_against_the_reference(capsys):
    tune_aa_preflop.main(["--grid", "realize_ip=0.9,1.1", "--deals", "2",
                          "--workers", "1", "--pool", "population"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("pool population, 2 deals")
    assert len(lines) == 3 and all("aa_preflop@realize_ip=" in line
                                   for line in lines[1:])
