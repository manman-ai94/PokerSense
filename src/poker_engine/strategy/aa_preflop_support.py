"""Finite, policy-free V2 preflop support queries, never action advice.

Slots that do not produce a real decision remain NOT_APPLICABLE. Prefixes are
scripted interventions, not observed opponent behaviour or range estimates.
"""
from __future__ import annotations

import random

from .aa_full_hand_arena import AAFullHandArena
from .aa_policy_encoding_v2 import encode_decision_v2


SCENARIOS = ("fold_to_first", "call_to_first", "limp_then_min_raise")
WORLD_SEEDS = (8300101, 8300102)
RANKS = "23456789TJQKA"


def holding_classes():
    """Exactly 13 pairs + 78 suited + 78 offsuit; no strength ordering."""
    rows = []
    for high, rank in enumerate(RANKS):
        rows.append({"class": rank + rank, "holding": [rank + "c", rank + "d"]})
        for low in RANKS[:high]:
            rows.append({"class": rank + low + "s",
                         "holding": [rank + "c", low + "c"]})
            rows.append({"class": rank + low + "o",
                         "holding": [rank + "c", low + "d"]})
    return rows


def support_specs(players):
    if type(players) is not int or players not in (6, 7, 8):
        raise ValueError("support_requires_6_7_8_players")
    return [{"id": f"n{players}-h{hero}-{scenario}-{row['class']}",
             "players": players, "hero": hero, "scenario": scenario, **row}
            for hero in range(players) for scenario in SCENARIOS
            for row in holding_classes()]


def build_query(rules, spec, *, world_seed):
    """Use a complete legal deck; hidden cards never reach policy input.

    Canonical physical geometry is seats 0..n-1, BTN n-1. The arena deals two
    consecutive cards to each physical seat in this geometry. This function
    checks the observed holding rather than assuming the mapping silently.
    """
    if (spec["players"] != rules.table_size
            or type(spec["hero"]) is not int
            or spec["hero"] not in range(rules.table_size)
            or spec["scenario"] not in SCENARIOS
            or {"class": spec["class"], "holding": spec["holding"]}
            not in holding_classes()):
        raise ValueError("invalid_support_spec")
    hero, holding = spec["hero"], spec["holding"]
    deck = [rank + suit for rank in RANKS for suit in "cdhs"
            if rank + suit not in holding]
    random.Random(world_seed).shuffle(deck)
    deck[2 * hero:2 * hero] = holding
    arena = AAFullHandArena(rules).reset(world_seed, deck=deck)
    steps = 0

    def step(action):
        nonlocal steps
        steps += 1
        if steps > 2 * rules.table_size + 2:
            raise ValueError("support_prefix_action_bound")
        arena.step(action)

    def ended(reason):
        return {"status": "NOT_APPLICABLE", "reason": reason,
                "prefix_actions": steps, "observation": None,
                "exact_key": None, "abstract_key": None}

    first_action = "fold" if spec["scenario"] == "fold_to_first" else "check_call"
    while not arena.terminal and arena.street == "preflop" and arena.actor != hero:
        step(first_action)
    if arena.terminal:
        return ended("HAND_TERMINATED_BEFORE_HERO")
    if arena.street != "preflop":
        return ended("PREFLOP_CLOSED_BEFORE_HERO")
    if spec["scenario"] == "limp_then_min_raise":
        step("check_call")
        if arena.terminal or arena.street != "preflop":
            return ended("HERO_CALL_CLOSED_PREFLOP")
        raises = [a for a in arena.legal_actions() if a.kind == "raise_to"]
        if not raises:
            return ended("NEXT_ACTOR_CANNOT_RAISE")
        step(min(raises, key=lambda a: a.raise_to))
        while not arena.terminal and arena.street == "preflop" and arena.actor != hero:
            step("check_call")
        if arena.terminal or arena.street != "preflop":
            return ended("NO_PREFLOP_RESPONSE_AFTER_RAISE")
    observation = arena.observe(hero)
    if set(observation["own_hole"]) != set(holding):
        raise ValueError("support_deck_seat_mapping_changed")
    encoded = encode_decision_v2(observation)
    return {"status": "READY", "reason": None, "prefix_actions": steps,
            "observation": observation, "exact_key": encoded["exact_key"],
            "abstract_key": encoded["abstract_key"]}


def paired_query(rules, spec):
    """Two hidden completions must give identical decision-time observations."""
    first, second = [build_query(rules, spec, world_seed=seed) for seed in WORLD_SEEDS]
    if first != second:
        raise ValueError("support_query_depends_on_hidden_completion")
    return first
