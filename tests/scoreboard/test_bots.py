"""Scoreboard policies: legal, deterministic, and true to their style."""

import json
from pathlib import Path

import pytest

from poker_engine.core.enums import Position
from poker_engine.scoreboard.bots import POLICY_NAMES, make_policy, position
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v1.json"


@pytest.fixture(scope="module")
def rules():
    return AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))


def test_every_policy_plays_legal_repeatable_actions(rules):
    arena = AAFullHandArena(rules)
    bots = [make_policy(name) for name in POLICY_NAMES]
    for seed in range(12):
        arena.reset(seed)
        deciders = {seat: bots[(seat + seed) % len(bots)].for_game(f"salt{seat}")
                    for seat in arena.occupied_seats}
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            action = deciders[arena.actor](observation)
            assert action in {a["id"] for a in observation["legal_actions"]}
            assert deciders[arena.actor](arena.observe(arena.actor)) == action
            arena.step(action)


def observation(hole, *, seat=5, history=(), to_call="4", street="preflop"):
    return {"street": street, "own_hole": hole, "board": [],
            "public_history": list(history), "occupied_seats": list(range(8)),
            "dealer_seat": 7, "observing_seat": seat, "to_call": to_call,
            "pot": "23", "folded": [],
            "bets": {str(s): "4" if s == 2 else "0" for s in range(8)},
            "legal_actions": [{"id": "fold", "kind": "fold", "raise_to": None},
                              {"id": "check_call", "kind": "check_call",
                               "raise_to": None},
                              {"id": "raise_to:8", "kind": "raise_to", "raise_to": "8"},
                              {"id": "raise_to:17", "kind": "raise_to",
                               "raise_to": "17"}]}


def test_positions_follow_the_dealer():
    seen = [position(observation(["As", "Ah"], seat=s)) for s in range(8)]
    assert seen == [Position.SB, Position.BB, Position.UTG, Position.UTG1,
                    Position.LJ, Position.HJ, Position.CO, Position.BTN]


@pytest.mark.parametrize("name, hole, expected", [
    ("tag", ["As", "Ah"], "raise_to:17"),
    ("tag", ["7c", "2d"], "fold"),
    ("station", ["Jc", "8d"], "check_call"),      # limps far too much
    ("rock", ["Ts", "9s"], "fold"),
    ("rfi_table", ["As", "Kd"], "raise_to:17"),   # in the repository's HJ chart
    ("rfi_table", ["7c", "2d"], "fold"),
])
def test_unopened_preflop_choices(name, hole, expected):
    decide = make_policy(name).for_game("salt")
    assert decide(observation(hole)) == expected


def test_facing_a_raise_tightens_up():
    raised = [{"street": "preflop", "kind": "raise_to", "actor": 3}]
    decide = make_policy("tag").for_game("salt")
    assert decide(observation(["As", "Ah"], history=raised)) == "raise_to:17"
    assert decide(observation(["Ts", "9s"], history=raised)) == "fold"
    assert make_policy("station").for_game("s")(
        observation(["Ts", "9s"], history=raised)) == "check_call"


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError):
        make_policy("nobody")
