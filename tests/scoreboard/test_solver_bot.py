"""The solver strategy's bookkeeping; the last test needs TexasSolver installed."""

import json
from pathlib import Path
import random

import pytest

from poker_engine.scoreboard import solver_bot
from poker_engine.scoreboard.replay import Decision
from poker_engine.scoreboard.runner import run_scoreboard
from poker_engine.scoreboard.solver_bot import (Fallback, SolverBot, kept, sample,
                                                weighted)
from poker_engine.solver.texassolver import solver_binary
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v1.json"
LEGAL = [{"id": "fold", "kind": "fold", "raise_to": None},
         {"id": "check_call", "kind": "check_call", "raise_to": None},
         {"id": "raise_to:16", "kind": "raise_to", "raise_to": "16"},
         {"id": "raise_to:29", "kind": "raise_to", "raise_to": "29"},
         {"id": "raise_to:58", "kind": "raise_to", "raise_to": "58"},
         {"id": "raise_to:171", "kind": "raise_to", "raise_to": "171"}]


def decision(kind, to_call="0", raise_to=None, seat=3, bets=None):
    action = {"id": "check_call", "kind": "check_call", "raise_to": None}
    if kind == "fold":
        action = {"id": "fold", "kind": "fold", "raise_to": None}
    elif kind == "raise":
        action = {"id": f"raise_to:{raise_to}", "kind": "raise_to",
                  "raise_to": raise_to}
    observation = {"to_call": to_call, "bets": bets or {str(seat): "0"},
                   "own_hole": ["2c", "3d"]}
    return Decision(seat, "river", observation, action)


NODE = {"actions": ["CHECK", "BET 29.000000", "BET 58.000000", "BET 171.000000"],
        "strategy": {"actions": ["CHECK", "BET 29.000000", "BET 58.000000",
                                 "BET 171.000000"],
                     "strategy": {"AhKd": [0.5, 0.5, 0.0, 0.0],
                                  "QsQd": [0.0, 0.0, 0.0, 1.0]}}}


def test_actions_taken_at_the_table_map_to_solution_branches():
    assert SolverBot.label(NODE, decision("call")) == "CHECK"
    assert SolverBot.label(NODE, decision("raise", raise_to="30")) == "BET 29.000000"
    assert SolverBot.label(NODE, decision("raise", raise_to="171")) == "BET 171.000000"
    facing = {"actions": ["CALL", "FOLD"]}
    assert SolverBot.label(facing, decision("call", to_call="29")) == "CALL"
    with pytest.raises(Fallback):
        SolverBot.label(facing, decision("raise", to_call="29", raise_to="100"))


def test_solver_choices_become_legal_table_actions():
    observation = {"to_call": "0", "bets": {"3": "0"}, "observing_seat": 3,
                   "legal_actions": LEGAL}
    assert SolverBot.to_arena("CHECK", observation) == "check_call"
    assert SolverBot.to_arena("FOLD", observation) == "check_call"   # nothing to call
    assert SolverBot.to_arena("BET 29.000000", observation) == "raise_to:29"
    assert SolverBot.to_arena("BET 60.000000", observation) == "raise_to:58"
    facing = {**observation, "to_call": "29"}
    assert SolverBot.to_arena("FOLD", facing) == "fold"


def test_ranges_follow_the_actions_taken():
    weights = {"AhKd": 1.0, "QsQd": 1.0}
    assert weighted(weights, NODE, "BET 29.000000") == {"AhKd": 0.5}
    # A policy whose choice depends on the order the cards were dealt in.
    by_order = kept(weights, decision("call"),
                    lambda obs: "check_call" if obs["own_hole"][0][0] == "A"
                    else "raise_to:29", both_orders=True)
    assert by_order == {"AhKd": 0.5}
    assert kept(weights, decision("call"), lambda obs: "check_call") == weights


def test_sampling_is_repeatable_and_follows_the_probabilities():
    strategy = {"CHECK": 0.25, "BET 29.000000": 0.75}
    draws = [sample(strategy, random.Random(seed)) for seed in range(2000)]
    assert draws == [sample(strategy, random.Random(seed)) for seed in range(2000)]
    assert 0.70 < draws.count("BET 29.000000") / len(draws) < 0.80


def test_without_the_solver_it_plays_like_its_base_policy(monkeypatch):
    monkeypatch.setattr(solver_bot, "solver_binary", lambda: None)
    monkeypatch.setattr(solver_bot, "_SOLVERS", {})
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    report = run_scoreboard(rules, ["rfi_table", "solver_river"], deals=4,
                            pool=("population",), reference="rfi_table")
    assert report["strategies"]["solver_river"] == {
        **report["strategies"]["rfi_table"]}
    counts = report["decision_counts"].get("solver_river", {})
    assert "solved" not in counts


@pytest.mark.skipif(solver_binary() is None, reason="TexasSolver is not installed")
def test_heads_up_rivers_are_solved():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    report = run_scoreboard(rules, ["solver_river"], deals=12, pool=("population",))
    assert report["decision_counts"]["solver_river"].get("solved", 0) > 0
