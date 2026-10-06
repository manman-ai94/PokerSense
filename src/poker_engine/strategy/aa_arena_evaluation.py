"""Same-deal, seat-rotated full-hand comparisons; failures stay in denominator.

This is a synthetic evaluation scaffold, not an empirical promotion gate. The
caller freezes protocol, candidate and opponent implementations before running.
Policies are pure observation -> action-id functions after optional for_game
binding to independent opaque per-seat salts; no deck seed enters a policy.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import random
from statistics import mean
import time

from .aa_full_hand_arena import AAFullHandArena, ArenaAction, SETTLEMENT_MODEL
from .aa_policy_diagnostics import failure_category, summarize_opportunities


def check_call_policy(observation):
    return "check_call"


def check_fold_policy(observation):
    return "check_call" if observation["to_call"] == "0" else "fold"


def min_raise_policy(observation):
    raises = [action for action in observation["legal_actions"]
              if action["kind"] == "raise_to"]
    return raises[0]["id"] if raises else "check_call"


def pot_raise_policy(observation):
    """Largest non-all-in abstract raise, or check/call when unavailable."""
    raises = [action for action in observation["legal_actions"]
              if action["kind"] == "raise_to"]
    return raises[max(0, len(raises) - 2)]["id"] if raises else "check_call"


def _exact(value):
    value = Fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator}


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _play(arena, hero, policy, opponent, max_actions, policy_salts,
          record_diagnostics=False):
    trace = []
    opportunities = []
    binding_success = False
    phase, failing_seat, street = "BIND", None, None
    attempted_index = None
    try:
        bound = {}
        for seat in arena.occupied_seats:
            failing_seat = seat
            chooser = policy if seat == hero else opponent
            factory = getattr(chooser, "for_game", None)
            if factory is not None:
                if not callable(factory):
                    raise ValueError("policy_for_game_must_be_callable")
                chooser = factory(policy_salts[seat])
            if not callable(chooser):
                raise ValueError("policy_for_game_must_return_callable")
            bound[seat] = chooser
        binding_success = True
        while not arena.terminal:
            phase, failing_seat, street = "BUDGET", arena.actor, arena.street
            attempted_index = len(trace)
            if len(trace) >= max_actions:
                raise RuntimeError("max_actions_exceeded")
            obs = arena.observe(arena.actor)
            street = obs["street"]
            phase = "DECIDE"
            chooser = bound[arena.actor]
            opportunity = None
            if record_diagnostics and arena.actor == hero:
                inspect = getattr(policy, "inspect_lookup", None)
                diagnostic = (inspect(obs) if callable(inspect) else
                              {"status": "EXTERNAL_POLICY"})
                opportunity = {"street": street, "action_index": len(trace),
                               "hero_opportunity_index": len(opportunities),
                               "lookup_status": diagnostic["status"],
                               "diagnostic": diagnostic,
                               "policy_latency_ms": None}
                opportunities.append(opportunity)
            started = time.perf_counter()
            try:
                action = chooser(obs)
            finally:
                if opportunity is not None:
                    opportunity["policy_latency_ms"] = (
                        time.perf_counter() - started) * 1000
            # Repeated calls cannot establish purity, but detect an accidental
            # stateful/random adapter before claiming a paired experiment.
            repeated = chooser(arena.observe(arena.actor))
            action_id = action.id if isinstance(action, ArenaAction) else action
            repeat_id = (repeated.id if isinstance(repeated, ArenaAction)
                         else repeated)
            if action_id != repeat_id:
                raise ValueError("policy_not_deterministic_for_observation")
            trace.append({"actor": arena.actor, "observation_sha256": _digest(obs),
                          "action": action_id})
            phase = "STEP"
            arena.step(action)
        returns = arena.terminal_returns()
        result = {"status": "COMPLETE", "return": returns[hero],
                  "actions": len(trace), "trace_sha256": _digest(trace),
                  "terminal": arena.terminal_result()}
        if record_diagnostics:
            result.update(binding_success=binding_success,
                          hero_opportunities=opportunities, first_failure=None,
                          action_count_semantics="ATTEMPTED_ACTIONS")
        return result
    except Exception as exc:
        result = {"status": "BLOCKED", "error_type": type(exc).__name__,
                  "error": str(exc), "actions": len(trace),
                  "trace_sha256": _digest(trace), "return": None}
        if record_diagnostics:
            result.update(binding_success=binding_success,
                          hero_opportunities=opportunities,
                          action_count_semantics="ATTEMPTED_ACTIONS",
                          first_failure={"phase": phase, "actor": failing_seat,
                                         "actor_is_hero": failing_seat == hero,
                                         "street": street,
                                         "action_index": attempted_index,
                                         "category": failure_category(exc, phase)})
        return result


def _cluster_interval(values, samples, seed):
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    draws = sorted(mean(rng.choices(values, k=len(values)))
                   for _ in range(samples))
    return [draws[int((samples - 1) * 0.025)],
            draws[int((samples - 1) * 0.975)]]


def evaluate_paired(rules, candidate, baseline, opponents, *, seeds,
                    candidate_id="candidate", baseline_id="baseline",
                    starting_stacks=None, bootstrap_samples=1000,
                    bootstrap_seed=0, max_actions=1000, policy_seed=7719,
                    record_diagnostics=False):
    """Compare both policies in every Hero seat, with fixed same-deal seeds.

    One seed's complete set of Hero rotations is one bootstrap cluster. Rows
    from failed games remain and make the affected group's metrics unavailable.
    Optional policy.for_game(opaque_salt) may bind a mixed policy to a fresh,
    pure per-game decision sampler. The same per-seat salts are reused in the
    paired branches; independent policy_seed RNG never exposes deck seeds.
    Bound callables must be frozen deterministic pure policies; no online
    learning, future-card access, paid calls or policy selection occurs here.
    """
    seeds = tuple(seeds)
    if not seeds or any(type(seed) is not int for seed in seeds):
        raise ValueError("seeds must be a nonempty integer sequence")
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate seeds would inflate the sample size")
    if (type(bootstrap_samples) is not int or bootstrap_samples < 100
            or type(bootstrap_seed) is not int or type(policy_seed) is not int
            or type(max_actions) is not int or max_actions < 1):
        raise ValueError("invalid fixed evaluation budgets")
    if not opponents or any(not isinstance(k, str) or not k
                            for k in opponents):
        raise ValueError("at least one named opponent is required")
    for name, policy in [(candidate_id, candidate), (baseline_id, baseline),
                         *opponents.items()]:
        factory = getattr(policy, "for_game", None)
        if (not isinstance(name, str) or not name
                or (not callable(policy) and not callable(factory))
                or (factory is not None and not callable(factory))):
            raise ValueError("policies need identifiers and callable factories")
    prototype = AAFullHandArena(rules, starting_stacks=starting_stacks)
    bb = Fraction(rules.big_blind)
    rows, groups = [], []
    policy_rng = random.Random(policy_seed)
    for opponent_name, opponent in sorted(opponents.items()):
        group_rows, seed_means = [], []
        for seed in seeds:
            block_deltas = []
            # Every seed has a fresh deck; both branches clone exactly this root.
            initial = prototype.reset(seed)
            for hero in initial.occupied_seats:
                salts = {seat: format(policy_rng.getrandbits(256), "064x")
                         for seat in initial.occupied_seats}
                left = _play(initial.clone(), hero, candidate, opponent, max_actions,
                             salts, record_diagnostics)
                right = _play(initial.clone(), hero, baseline, opponent, max_actions,
                              salts, record_diagnostics)
                complete = left["status"] == right["status"] == "COMPLETE"
                delta = ((left["return"] - right["return"]) / bb
                         if complete else None)
                row = {"table_size": rules.table_size,
                       "opponent": opponent_name, "seed": seed, "hero": hero,
                       "status": "COMPLETE" if complete else "BLOCKED",
                       "delta_bb": _exact(delta) if complete else None}
                for label, result in (("candidate", left), ("baseline", right)):
                    row[label] = {key: val for key, val in result.items()
                                  if key != "return"}
                    row[label]["return_chips"] = (
                        _exact(result["return"]) if result["return"] is not None
                        else None)
                group_rows.append(row)
                if complete:
                    block_deltas.append(delta)
            if len(block_deltas) == len(initial.occupied_seats):
                seed_means.append(float(sum(block_deltas) / len(block_deltas) * 100))
        rows.extend(group_rows)
        failures = sum(row["status"] != "COMPLETE" for row in group_rows)
        metrics_ready = not failures and len(seed_means) == len(seeds)
        interval = (_cluster_interval(seed_means, bootstrap_samples, bootstrap_seed)
                    if metrics_ready else None)
        groups.append({
            "table_size": rules.table_size, "opponent": opponent_name,
            "expected_pairs": len(seeds) * len(initial.occupied_seats),
            "complete_pairs": len(group_rows) - failures,
            "blocked_pairs": failures, "expected_clusters": len(seeds),
            "complete_clusters": len(seed_means),
            "status": "COMPLETE" if metrics_ready else "BLOCKED",
            "delta_net_bb100": mean(seed_means) if metrics_ready else None,
            "ci95_delta_net_bb100": interval,
            "evidence_status": ("SYNTHETIC_COMPARISON_ONLY" if interval is not None
                                else "INSUFFICIENT_DATA"),
        })
    protocol = {"schema_version": 1, "arena_version": "aa-full-hand-arena-v1",
                "rules": rules.to_dict(), "candidate_id": candidate_id,
                "baseline_id": baseline_id, "opponents": sorted(opponents),
                "seeds": list(seeds), "bootstrap_seed": bootstrap_seed,
                "policy_seed": policy_seed,
                "policy_sampling": "per_game_per_seat_salts_shared_by_paired_branches",
                "bootstrap_samples": bootstrap_samples, "max_actions": max_actions,
                "starting_stacks": {str(k): str(v) for k, v in
                                    prototype.starting_stacks.items()},
                "cluster_unit": "one_seed_all_hero_rotations",
                "ci": "two_sided_95_percentile_cluster_bootstrap"}
    result = {
        "schema_version": 1, "protocol": protocol,
        "protocol_sha256": _digest(protocol), "rows": rows, "groups": groups,
        "expected_pairs": sum(g["expected_pairs"] for g in groups),
        "complete_pairs": sum(g["complete_pairs"] for g in groups),
        "blocked_pairs": sum(g["blocked_pairs"] for g in groups),
        "status": "BLOCKED" if any(g["blocked_pairs"] for g in groups) else "COMPLETE",
        "settlement_model": SETTLEMENT_MODEL,
        "strategy_eligible": False, "promotion": "NOT_ASSESSED",
        "limitations": ["synthetic_opponents_not_empirical_player_pool",
                        "policy_identifiers_are_not_source_integrity_proofs",
                        "determinism_probe_is_not_a_policy_purity_proof",
                        "no_automatic_promotion_from_confidence_intervals",
                        "same_PokerKit_engine_is_not_an_independent_oracle"],
    }
    if record_diagnostics:
        result["candidate_diagnostics"] = summarize_opportunities(
            row["candidate"] for row in rows)
        result["baseline_diagnostics"] = summarize_opportunities(
            row["baseline"] for row in rows)
    return result
