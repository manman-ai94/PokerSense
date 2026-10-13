"""Postflop actions read with weights instead of a veto."""

import json
from pathlib import Path

from poker_engine.scoreboard import ranges
from poker_engine.scoreboard.bots import _rng, make_policy
from poker_engine.scoreboard.exclusion import exclusion_trace
from poker_engine.scoreboard.population import PopulationBot
from poker_engine.scoreboard.postflop_reading import (PRUNE, VETO, WEIGHTS, key_of,
                                                      otherwise, soft_kept,
                                                      weights_of)
from poker_engine.scoreboard.replay import kind_of, public_replay, with_hole
from poker_engine.scoreboard.solver_bot import MODEL_SALT, kept
from poker_engine.solver.texassolver import all_combos
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


def checked_down(seed=3):
    """A hand opened by the first seat and called by the next, everyone else
    folding, then checked to the end; (observation, hero, villain)."""
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules).reset(seed)
    hero = arena.actor
    arena.step(next(a["id"] for a in arena.observe(hero)["legal_actions"]
                    if a["kind"] == "raise_to"))
    villain = arena.actor
    while not arena.terminal:
        seat = arena.actor
        arena.step("check_call" if seat in (hero, villain) else "fold")
    return arena.observe(hero), hero, villain


def decide(model):
    return lambda observation: model.decide(observation, _rng(MODEL_SALT, observation))


def flop_check(observation, villain):
    return next(d for d in public_replay(observation)
                if d.seat == villain and d.street == "flop")


def test_kinds_of_hands_played_otherwise_than_the_model():
    assert otherwise("c", "c") is None and otherwise("r", "r") is None
    assert otherwise("c", "r") == "slow"         # checked or called a betting hand
    assert otherwise("c", "f") == "loose"        # called a folding hand
    assert otherwise("r", "c") == otherwise("r", "f") == "bluff"


def test_the_veto_reads_as_before_and_the_weights_keep_slow_played_hands():
    observation, _, villain = checked_down()
    decision = flop_check(observation, villain)
    model = PopulationBot(adjusted=True)
    board = tuple(decision.observation["board"])
    every = {key: 1.0 for key in all_combos(board)}
    assert soft_kept(every, decision, decide(model), VETO) == kept(
        every, decision, decide(model))
    soft = soft_kept(every, decision, decide(model))
    betting = [key for key in every
               if kind_of(decide(model)(with_hole(decision.observation,
                                                  (key[:2], key[2:])))) == "r"]
    assert betting, "the model bets some hands on this flop"
    slow = WEIGHTS["slow"][0]
    assert all(soft[key] == slow for key in betting)
    assert all(soft[key] == 1.0 for key in every if key not in betting)


def test_hands_far_below_the_largest_weight_are_dropped():
    observation, _, villain = checked_down()
    decision = flop_check(observation, villain)
    model = PopulationBot(adjusted=True)
    weights = {key: 1.0 for key in all_combos(tuple(decision.observation["board"]))}
    tiny = next(iter(weights))
    weights[tiny] = PRUNE / 2
    assert tiny not in soft_kept(weights, decision, decide(model))


def test_a_slow_played_hand_stays_in_the_range_read_for_the_advice():
    observation, _, villain = checked_down()
    decision = flop_check(observation, villain)
    veto, soft = PopulationBot(adjusted=True), PopulationBot(adjusted=True)
    veto.postflop_reading = VETO
    before = ranges.opponent_ranges(observation, veto, cache={})[villain]
    after = ranges.opponent_ranges(observation, soft, cache={})[villain]
    board = tuple(decision.observation["board"])
    # A hand the model would have bet on the flop but that was checked.
    held = next(key for key in all_combos(tuple(observation["board"]))
                if key[:2] not in board and key[2:] not in board
                and kind_of(decide(soft)(with_hole(decision.observation,
                                                   (key[:2], key[2:])))) == "r"
                and before.get(key, 0.0) == 0.0 and after.get(key, 0.0) > 0)
    cards = (held[:2], held[2:])
    hard = exclusion_trace(observation, villain, cards, veto)
    kept_now = exclusion_trace(observation, villain, cards, soft)
    assert hard["steps"][-1]["excluded"] and not kept_now["steps"][-1]["excluded"]


def test_two_postflop_readings_of_the_same_line_do_not_share_a_kept_range():
    observation, _, villain = checked_down()
    veto, soft = PopulationBot(adjusted=True), PopulationBot(adjusted=True)
    veto.postflop_reading = VETO
    cache = {}
    first = ranges.opponent_ranges(observation, veto, cache=cache)
    second = ranges.opponent_ranges(observation, soft, cache=cache)
    assert first != second
    assert second == ranges.opponent_ranges(observation, soft, cache={})
    assert key_of(VETO) != key_of(WEIGHTS)


def test_vetoread_plays_a_policy_with_the_old_reading():
    plain = make_policy("range_multiway@hu=1+aa_preflop")
    old = make_policy("vetoread+range_multiway@hu=1+aa_preflop")
    assert old.name == "vetoread+range_multiway@hu=1+aa_preflop"
    assert weights_of(plain.model) == WEIGHTS and weights_of(old.model) == VETO
