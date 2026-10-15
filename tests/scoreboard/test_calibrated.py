"""The AA calibrated table: aa_real's rules with the departures fitted on recordings."""

import json
from pathlib import Path

import numpy as np
import pytest

from poker_engine.scoreboard.aa_real import aa_stats
from poker_engine.scoreboard.bots import _rng, make_policy
from poker_engine.scoreboard.calibrated import (FITTED, REFERENCE_PRICE, CalibratedBot,
                                                cal_stats, checked_probs, facing_probs,
                                                preflop_probs, priced_keep)
from poker_engine.scoreboard.fidelity import chances
from poker_engine.scoreboard.replay import kind_of
from poker_engine.scoreboard.runner import POOLS
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"
SPOT = "flop|hu|other|checked_to"
ZERO = {"mix": 0.0, "price_slope": 0.0,
        **{street: {"slow": 0.0, "bluff": 0.0, "sticky": 0.0}
           for street in ("flop", "turn", "river")}}


@pytest.fixture(scope="module")
def arena():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    return AAFullHandArena(rules)


def legal(observation, action):
    """On the menu, or a raise between the smallest and the largest."""
    menu = observation["legal_actions"]
    if action in {a["id"] for a in menu}:
        return True
    sizes = [float(a["raise_to"]) for a in menu if a["kind"] == "raise_to"]
    return (action.startswith("raise_to:") and bool(sizes)
            and min(sizes) <= float(action.split(":")[1]) <= max(sizes))


def test_the_price_moves_the_share_that_goes_on():
    assert priced_keep(0.5, REFERENCE_PRICE, -1.5) == pytest.approx(0.5)
    assert priced_keep(0.5, 0.4, 0.0) == 0.5
    small, large = priced_keep(0.5, 0.15, -1.5), priced_keep(0.5, 0.4, -1.5)
    assert small > 0.5 > large


def test_probabilities_are_whole_and_legal():
    probs = preflop_probs(np.array([0, 1, 2]), 0.1, 0.3, 0.2)
    assert probs.sum(axis=-1) == pytest.approx([1, 1, 1])
    assert probs[2][2] == pytest.approx(0.8 + 0.2 * 0.1)
    no_fold = preflop_probs(0, 0.1, 0.3, 0.0, can_fold=False)
    assert list(no_fold) == [0.0, 1.0, 0.0]
    win = np.linspace(0, 1, 101)
    checked = checked_probs(win, SPOT, 0.3, 0.2, 0.1)
    assert checked.sum(axis=-1) == pytest.approx(np.ones(101))
    assert checked[0][2] == pytest.approx(0.1)          # the weakest bluff
    assert checked[-1][2] == pytest.approx(0.8)         # the strongest slow-play
    facing = facing_probs(win, "flop|hu|other|facing_bet", 0.1, 0.4, 0.4, 0.2, 0.1,
                          -1.5)
    assert facing.sum(axis=-1) == pytest.approx(np.ones(101))
    assert facing[0][1] == pytest.approx(0.1)           # sticky calls
    assert facing[-1][2] == pytest.approx(0.8)
    assert list(checked_probs(win, SPOT, 0.3, 0.0, 0.0, can_raise=False)[-1]) == \
        [0.0, 1.0, 0.0]


def test_without_departures_it_acts_as_aa_real_on_the_same_numbers(arena):
    plain = make_policy("aa_real")
    calibrated = CalibratedBot(params=ZERO, stats=aa_stats())
    compared = 0
    for seed in range(12):
        arena.reset(seed)
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            action = plain.decide(observation, _rng("same", observation))
            mine = calibrated.decide(observation, _rng("same", observation))
            assert kind_of(mine) == kind_of(action)
            if observation["street"] == "preflop":
                assert mine == action
            arena.step(action)
            compared += 1
    assert compared > 100


def test_plays_whole_hands_repeatably_with_its_fitted_numbers(arena):
    assert POOLS["aa_cal"] == ("aa_cal",)
    stats = cal_stats()
    assert stats["preflop"]["ALL|rfi"]["n"] > aa_stats()["preflop"]["ALL|rfi"]["n"]
    bot = make_policy("aa_cal")
    assert bot.params is FITTED
    played = 0
    for seed in range(12):
        arena.reset(seed)
        deciders = {seat: bot.for_game(f"s{seat}") for seat in arena.occupied_seats}
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            action = deciders[arena.actor](observation)
            assert legal(observation, action)
            assert deciders[arena.actor](observation) == action
            mix = chances(bot, observation, _rng(f"s{arena.actor}", observation))
            assert sum(mix.values()) == pytest.approx(1)
            assert mix.get(kind_of(action), 0) > 0
            arena.step(action)
            played += 1
    assert played > 100
