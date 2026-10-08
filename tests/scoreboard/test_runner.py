"""Scoreboard runs: same deals for every strategy, reproducible results."""

import json
from pathlib import Path

import pytest

from poker_engine.scoreboard.runner import lineup, pairwise, run_scoreboard, summarize
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v1.json"
RAKED = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


def test_lineup_repeats_the_pool_and_depends_only_on_the_deal():
    first = lineup(7, ("tag", "lag", "rock", "station"), tuple(range(8)))
    assert first == lineup(7, ("tag", "lag", "rock", "station"), tuple(range(8)))
    assert sorted(first.values()) == sorted(["tag", "lag", "rock", "station"] * 2)
    assert first != lineup(8, ("tag", "lag", "rock", "station"), tuple(range(8)))


def test_summary_reports_bb_per_100_and_paired_differences():
    rows = [(1, {"a": (1.0, 0), "b": (0.5, 1)}), (2, {"a": (3.0, 2), "b": (2.0, 0)})]
    summary, versus = summarize(rows, ("a", "b"), "b", 8)
    assert summary["a"]["bb_per_100"] == 200.0 and summary["a"]["hands"] == 16
    assert summary["a"]["all_in_ev_share"] == round(2 / 16, 4)
    assert summary["a"]["ci95"] == [4.0, 396.0]
    assert versus == {"a": {"delta_bb_per_100": 75.0, "ci95": [26.0, 124.0]}}


def test_results_split_by_how_the_hand_reached_the_flop():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    report = run_scoreboard(rules, ["tag", "always_call"], deals=4, base_seed=3,
                            reference="always_call")
    for name, row in report["strategies"].items():
        parts = row["by_flop"]
        assert set(parts) == {"preflop", "heads_up", "multiway"}
        total = sum(part["bb_per_100"] for part in parts.values())
        assert abs(total - row["bb_per_100"]) < 0.05
        assert abs(sum(p["share"] for p in parts.values()) - 1) < 1e-3
    # Calling everything sees most flops with company.
    assert report["strategies"]["always_call"]["by_flop"]["multiway"]["share"] > 0.3
    versus = report["versus_reference"]["tag"]
    assert abs(sum(p["delta_bb_per_100"] for p in versus["by_flop"].values())
               - versus["delta_bb_per_100"]) < 0.05


def test_runs_are_reproducible_and_independent_of_workers():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    kwargs = {"deals": 3, "base_seed": 4, "reference": "always_call"}
    one = run_scoreboard(rules, ["tag", "always_call"], workers=1, **kwargs)
    two = run_scoreboard(rules, ["tag", "always_call"], workers=2, chunk=1, **kwargs)
    for key in ("strategies", "versus_reference", "hands_per_strategy"):
        assert one[key] == two[key]
    assert one["hands_per_strategy"] == 24


def test_rake_lowers_every_strategy_on_the_same_deals():
    kwargs = {"deals": 4, "base_seed": 3, "reference": "always_call"}
    results = {}
    for name, path in (("free", RULES), ("raked", RAKED)):
        rules = AARuleProfileV2.from_dict(json.loads(path.read_text(encoding="utf-8")))
        results[name] = run_scoreboard(rules, ["population", "always_call"], **kwargs)
    for strategy in ("population", "always_call"):
        assert (results["raked"]["strategies"][strategy]["bb_per_100"]
                < results["free"]["strategies"][strategy]["bb_per_100"])


def test_too_little_input_is_refused():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    with pytest.raises(ValueError):
        run_scoreboard(rules, ["tag"], deals=1)


def test_progress_is_reported_after_every_batch():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    calls = []
    run_scoreboard(rules, ["tag"], deals=4, chunk=1, pool=("tag",),
                   progress=lambda done, total, seconds: calls.append((done, total)))
    assert calls == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_every_pair_of_strategies_is_compared_on_the_same_deals():
    rows = [(1, {"a": (1.0, 0), "b": (0.5, 1), "c": (0.0, 0)}),
            (2, {"a": (3.0, 2), "b": (2.0, 0), "c": (1.0, 0)})]
    result = pairwise(rows, ("a", "b", "c"))
    assert set(result) == {"a - b", "a - c", "b - c"}
    assert result["a - b"] == {"delta_bb_per_100": 75.0, "ci95": [26.0, 124.0]}
    assert result["a - c"]["delta_bb_per_100"] == 150.0
