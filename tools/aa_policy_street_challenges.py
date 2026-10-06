"""Frozen synthetic query challenges, separate from on-policy full-hand returns."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import random
import time

from poker_engine.strategy.aa_frozen_policy import canonical_hash
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena, ArenaAction


CHALLENGE_SPEC = {
    "version": "AA_STREET_QUERY_CHALLENGES_V1",
    "seeds": [5000000, 5000001, 5000002, 5000003, 5000004],
    "kinds": ["check_call_path", "off_grid_prefix", "all_in_price", "side_pot_scope"],
    "policy_salt_seed": 81771,
    "max_actions": 1000,
    "side_pot_starting_bb": [100, 60, 40],
    "semantics": "COUNTERFACTUAL_LEGAL_PREFIX_QUERIES_NOT_POLICY_PLAY_OR_EV",
    "side_pot_expectation": "OUT_OF_EQUAL_100BB_SCOPE_MUST_REFUSE",
}
DEVELOPMENT_SPEC = {
    **CHALLENGE_SPEC, "version": "AA_STREET_QUERY_DEVELOPMENT_CONTROL_V1",
    "seeds": [4441, 4442],
}


def challenge_observations(rules, kind, seed):
    """Yield public-only decision snapshots along predeclared scripted prefixes."""
    if kind not in CHALLENGE_SPEC["kinds"]:
        raise ValueError("unknown_street_challenge")
    stacks = [rules.big_blind * 100] * rules.table_size
    if kind == "side_pot_scope":
        stacks[:3] = [rules.big_blind * n
                      for n in CHALLENGE_SPEC["side_pot_starting_bb"]]
    arena = AAFullHandArena(rules, starting_stacks=stacks).reset(seed)
    count = 0
    while not arena.terminal:
        if count >= CHALLENGE_SPEC["max_actions"]:
            raise ValueError("challenge_action_budget")
        obs = arena.observe(arena.actor)
        yield obs
        if count == 0 and kind == "off_grid_prefix":
            raises = [a for a in arena.legal_actions() if a.kind == "raise_to"]
            if not raises:
                raise ValueError("off_grid_prefix_missing_raise")
            minimum = min(a.raise_to for a in raises)
            maximum = max(a.raise_to for a in raises)
            targets = {a.raise_to for a in raises}
            target = minimum + rules.minimum_chip
            while target in targets:
                target += rules.minimum_chip
            if target >= maximum:
                raise ValueError("no_in_scope_off_grid_raise")
            arena.step(ArenaAction("raise_to", target))
        elif count == 0 and kind in ("all_in_price", "side_pot_scope"):
            arena.step(max((a for a in arena.legal_actions() if a.kind == "raise_to"),
                           key=lambda a: a.raise_to))
        else:
            arena.step("check_call")
        count += 1


def evaluate_queries(rules, policy, *, spec=CHALLENGE_SPEC, deadline=None):
    if spec not in (CHALLENGE_SPEC, DEVELOPMENT_SPEC):
        raise ValueError("unfrozen_challenge_definition")
    rng = random.Random(spec["policy_salt_seed"])
    rows = []
    for kind in spec["kinds"]:
        for seed in spec["seeds"]:
            bound = policy.for_game(format(rng.getrandbits(256), "064x"))
            observations = challenge_observations(rules, kind, seed)
            for index, observation in enumerate(observations):
                if deadline is not None and time.monotonic() >= deadline:
                    return {"status": "UNREPORTED_SUFFIX_BUDGET", "rows": rows,
                            "spec": spec, "remaining_opportunities": None,
                            "strategy_eligible": False}
                diagnostic = policy.inspect_lookup(observation)
                row = {"kind": kind, "seed": seed, "index": index,
                       "street": observation["street"], "actor": observation["actor"],
                       "observation_sha256": canonical_hash(observation),
                       "lookup_status": diagnostic["status"],
                       "scope_expected": kind != "side_pot_scope",
                       "action": None, "legal": None, "policy_latency_ms": None}
                if diagnostic["status"] == "HIT":
                    started = time.perf_counter()
                    action = bound(observation)
                    row["policy_latency_ms"] = (time.perf_counter() - started) * 1000
                    row["action"] = action
                    row["legal"] = action in {
                        a["id"] for a in observation["legal_actions"]}
                rows.append(row)
    by_street = {street: {"opportunities": 0, "hit": 0, "illegal": 0}
                 for street in ("preflop", "flop", "turn", "river")}
    for row in rows:
        if not row["scope_expected"]:
            continue
        group = by_street[row["street"]]
        group["opportunities"] += 1
        group["hit"] += row["lookup_status"] == "HIT"
        group["illegal"] += row["legal"] is False
    scope_failures = sum(row["lookup_status"] != "SCOPE_MISMATCH"
                         for row in rows if not row["scope_expected"])
    return {"status": "COMPLETE_QUERY_DIAGNOSTIC", "spec": spec,
            "development_only": spec == DEVELOPMENT_SPEC,
            "spec_sha256": canonical_hash(spec), "rows": rows,
            "by_street": by_street,
            "failure_counts": dict(Counter(row["lookup_status"] for row in rows)),
            "side_pot_scope_failures": scope_failures,
            "all_streets_have_positive": all(row["hit"] > 0
                                             for row in by_street.values()),
            "strategy_eligible": False, "ev": None}


def hidden_input_rejection_probe(rules, policy):
    """Explicit malicious-input tests; not a complete information-flow proof."""
    arena = AAFullHandArena(rules).reset(3200100)
    obs = arena.observe(arena.actor)
    results = []
    for container in (None, "public_history", "rules"):
        changed = deepcopy(obs)
        if container is None:
            changed["opponent_hole"] = ["As", "Ah"]
        elif container == "public_history":
            changed[container].append({"future_board": ["2c"]})
        else:
            changed[container]["seed"] = 123
        diagnostic = policy.inspect_lookup(changed)
        results.append({"container": container,
                        "rejected": diagnostic["status"] in
                        ("ADAPTER_ERROR", "INVALID_OBSERVATION"),
                        "status": diagnostic["status"]})
    return {"cases": results, "passed": all(row["rejected"] for row in results),
            "scope": "DECLARED_MALICIOUS_INPUT_PROBES_NOT_UNIVERSAL_LEAK_PROOF"}
