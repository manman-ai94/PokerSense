"""The AA real-player table: measured shares, pulled toward 2009 by sample size."""

import json
from pathlib import Path

import pytest

from poker_engine.scoreboard.aa_real import (PRIOR, aa_name, aa_stats,
                                             preflop_shares, pulled, raise_by_pot)
from poker_engine.scoreboard.bots import make_policy
from poker_engine.scoreboard.population import population_stats
from poker_engine.scoreboard.runner import POOLS
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


@pytest.fixture(scope="module")
def arena():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    return AAFullHandArena(rules)


def test_shares_are_pulled_toward_2009_by_sample_size():
    row = {"n": PRIOR, "raise": 0.2, "call": 0.4}
    assert pulled(row, {"raise": 0.1, "call": 0.0}, ("raise", "call")) == \
        pytest.approx({"raise": 0.15, "call": 0.2})
    assert pulled(None, {"raise": 0.1}, ("raise",)) == {"raise": 0.1}


def test_kept_numbers_have_enough_decisions():
    stats = aa_stats()
    for part in ("preflop", "postflop", "sizes"):
        assert stats[part]
        assert all(row["n"] >= 10 for row in stats[part].values())
    assert stats["preflop"]["ALL|rfi"]["n"] >= 100


def first_decision(arena, seed=1):
    arena.reset(seed)
    return arena.observe(arena.actor)


def test_first_in_limps_far_more_than_2009_players(arena):
    observation = first_decision(arena)
    assert aa_name(observation) == "UTG1"           # first after the straddle
    raise_share, call_share = preflop_shares(observation, "rfi")
    players = population_stats()["EP|rfi"]
    assert call_share > 2 * players["call"]
    assert 0 < raise_share < 0.3


def test_open_raise_puts_in_about_the_pot(arena):
    observation = first_decision(arena)
    action = raise_by_pot(observation, 0.96)
    amount = float(action.split(":")[1])
    assert amount == pytest.approx(0.96 * float(observation["pot"]), abs=1)
    arena.step(action)                               # off the menu, still legal
    assert arena.observe(arena.actor)["public_history"][-1]["id"] == action


def test_plays_whole_hands_with_its_raises(arena):
    bot = make_policy("aa_real")
    played = 0
    for seed in range(15):
        arena.reset(seed)
        deciders = {seat: bot.for_game(f"s{seat}") for seat in arena.occupied_seats}
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            action = deciders[arena.actor](observation)
            assert deciders[arena.actor](observation) == action
            arena.step(action)
            played += 1
    assert played > 100
    assert POOLS["aa_real"] == ("aa_real",)
