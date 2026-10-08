"""Frozen, offline evaluation of the current bounded AA river planning policy.

The baseline is a table of public-history actions compiled at the exact
declared source revision. Evaluation never recompiles it from an evaluation
world. All worlds are synthetic/manual hypotheses; this is neither real-hand
acceptance nor a measure of live winnings or equilibrium strength.
"""

import argparse
from dataclasses import fields, replace
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from math import prod
from pathlib import Path
import platform
import subprocess
import sys
import time

from poker_engine.core.enums import PlayerStatus
from poker_engine.strategy.range_tracker import enumerate_joint_assignments
from poker_engine.strategy.threeway_policy_evaluation_v1 import (
    FrozenDecision, PolicyBook, _json, compile_policy_book, evaluate_policy_book,
    policy_book_hash,
)
from poker_engine.strategy.threeway_river_v1 import RiverAction, analyze_threeway_river
from tools.analyze_threeway_river import scenario_from_dict
from tools.analyze_terminal_multiway import unique_object
from tools.validate_threeway_models import (
    public_candidates, public_scenario, world_scenario,
)


BASE_COMMIT = "d98084aba96eac6ff3bc0cf07dad99b00e36ff31"
SOURCE_PATHS = (
    "src/poker_engine/core/_freeze.py",
    "src/poker_engine/core/enums.py",
    "src/poker_engine/core/errors.py",
    "src/poker_engine/core/events.py",
    "src/poker_engine/core/opponents.py",
    "src/poker_engine/core/request_context.py",
    "src/poker_engine/core/state.py",
    "src/poker_engine/core/value_objects.py",
    "src/poker_engine/strategy/contracts.py",
    "src/poker_engine/strategy/context_factory.py",
    "src/poker_engine/strategy/input_provenance.py",
    "src/poker_engine/strategy/threeway_river_v1.py",
    "src/poker_engine/strategy/threeway_policy_evaluation_v1.py",
    "src/poker_engine/strategy/terminal_multiway_v1.py",
    "src/poker_engine/strategy/aa_rules_v2.py",
    "src/poker_engine/strategy/range_tracker.py",
    "src/poker_engine/strategy/response_model_calibration_v1.py",
    "src/poker_engine/strategy/state.py",
    "src/poker_engine/equity/evaluator.py",
    "tools/analyze_threeway_river.py",
    "tools/analyze_terminal_multiway.py",
    "tools/validate_threeway_models.py",
)
DEFAULT_INPUT = Path("configs/strategy/examples/threeway-river-response-manual.json")
DEFAULT_PROTOCOL = Path(
    "configs/strategy/examples/threeway-validation-protocol-v1.json")
DEFAULT_BASELINE = Path("configs/strategy/evaluation/baseline-v1.json")
DEFAULT_RESULTS = Path("configs/strategy/evaluation/baseline-v1-results.json")
FROZEN_BASELINE_SHA256 = (
    "5ecae40e03ce18b22799599446745ce1db467e7a8bf41cc994a2d4cdeabfdac6")
MODEL_SCOPE = "SYNTHETIC_CONDITIONAL_RIVER_POLICY_EVALUATION"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=unique_object)


def stable_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                indent=2) + "\n")


def source_hashes(root=Path(".")):
    return {name: digest((root / name).read_bytes()) for name in SOURCE_PATHS}


def load_frozen_baseline(baseline_path=DEFAULT_BASELINE):
    """Bind V1 to the independently reproduced artifact, not its own claims."""
    raw = Path(baseline_path).read_bytes()
    if digest(raw) != FROZEN_BASELINE_SHA256:
        raise ValueError("canonical_baseline_artifact_required")
    frozen = json.loads(raw, object_pairs_hook=unique_object)
    if frozen["source_sha256"] != source_hashes():
        raise ValueError("baseline_source_drift")
    return frozen


def require_base_sources():
    """Do not silently relabel a later policy or changed evaluator as V1."""
    current = source_hashes()
    for name, actual in current.items():
        original = subprocess.run(
            ["git", "show", f"{BASE_COMMIT}:{name}"], check=True,
            capture_output=True).stdout
        if actual != digest(original):
            raise ValueError("baseline_source_drift:" + name)
    return current


def action_data(action):
    return {"actor": action.actor, "kind": action.kind,
            "target": str(action.target)}


def action_from_data(data):
    if set(data) != {"actor", "kind", "target"}:
        raise ValueError("invalid_frozen_action")
    return RiverAction(data["actor"], data["kind"], Decimal(data["target"]))


def book_data(book):
    return {
        "policy_id": book.policy_id,
        "public_conditions_json": book.public_conditions_json,
        "planning_scenario_sha256": book.planning_scenario_sha256,
        "planning_best_ev": str(book.planning_best_ev),
        "decisions": [{"history": [action_data(a) for a in item.history],
                       "action": action_data(item.action)}
                      for item in book.decisions],
        "book_sha256": book.book_sha256,
        "fallback": book.fallback,
        "schema_version": book.schema_version,
    }


def book_from_data(data):
    if set(data) != {field.name for field in fields(PolicyBook)}:
        raise ValueError("invalid_frozen_book_fields")
    book = PolicyBook(
        data["policy_id"], data["public_conditions_json"],
        data["planning_scenario_sha256"], Fraction(data["planning_best_ev"]),
        tuple(FrozenDecision(tuple(map(action_from_data, item["history"])),
                             action_from_data(item["action"]))
              for item in data["decisions"]),
        data["book_sha256"], data["fallback"], data["schema_version"])
    if policy_book_hash(book) != book.book_sha256:
        raise ValueError("frozen_book_hash_mismatch")
    return book


def require_protocol(value):
    if (value.get("schema_version") != 1
            or value.get("source_kind") != "synthetic_model_stress"
            or value.get("table_sizes") != [6, 7, 8]
            or value.get("roots") != ["facing_bet", "unopened"]
            or value.get("worlds") != ["reference_control", "value_heavy",
                                       "weak_callers", "rank_aware", "check_trap"]):
        raise ValueError("unexpected_baseline_protocol")


def planning_scenarios(input_path, protocol_path):
    raw_input = Path(input_path).read_bytes()
    raw_protocol = Path(protocol_path).read_bytes()
    data = json.loads(raw_input, object_pairs_hook=unique_object)
    protocol = json.loads(raw_protocol, object_pairs_hook=unique_object)
    require_protocol(protocol)
    scenario_from_dict(data)
    plans = {f"n{size}-{root}": public_scenario(data, size, root)
             for size in protocol["table_sizes"] for root in protocol["roots"]}
    return plans, protocol, digest(raw_input), digest(raw_protocol)


def freeze_baseline(input_path=DEFAULT_INPUT, protocol_path=DEFAULT_PROTOCOL,
                    output=DEFAULT_BASELINE):
    if subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                      capture_output=True, text=True).stdout.strip() != BASE_COMMIT:
        raise ValueError("freeze_requires_exact_base_commit")
    sources = require_base_sources()
    plans, protocol, input_hash, protocol_hash = planning_scenarios(
        input_path, protocol_path)
    books = {}
    for group, plan in plans.items():
        book = compile_policy_book(plan, policy_id="baseline-v1-" + group,
                                   max_joint_assignments=128, max_nodes=20000)
        books[group] = book_data(book)
    frozen = {
        "schema_version": 1, "baseline_id": "BASELINE_V1",
        "base_commit": BASE_COMMIT, "scope": MODEL_SCOPE,
        "input_path": str(input_path).replace("\\", "/"),
        "input_sha256": input_hash,
        "protocol_path": str(protocol_path).replace("\\", "/"),
        "protocol_sha256": protocol_hash,
        "source_sha256": sources, "max_joint_assignments": 128,
        "max_nodes": 20000, "groups": len(plans),
        "worlds": protocol["worlds"], "books": books,
        "real_hand_acceptance_pending": True, "strategy_eligible": False,
        "advice_emitted": False,
    }
    encoded = (json.dumps(frozen, sort_keys=True, ensure_ascii=False,
                          indent=2) + "\n").encode("utf-8")
    if digest(encoded) != FROZEN_BASELINE_SHA256:
        raise ValueError("freeze_does_not_reproduce_canonical_baseline")
    write_json(output, frozen)
    return frozen


def _metrics(result):
    return {metric.name: {
        "net_ev_chips": str(metric.net_ev_chips),
        "conditional_net_ev_bb": str(metric.conditional_net_ev_bb),
        "fallback_probability": str(metric.probability_of_any_fallback),
        "expected_fallback_count": str(metric.expected_fallback_count),
        "nodes": metric.nodes,
    } for metric in result.metrics}


def _case(group, world_name, book, world, overrides, max_nodes):
    declared_world_sha256 = digest(_json({
        "scenario": world, "overrides": overrides}).encode())
    begin = time.perf_counter_ns()
    result = evaluate_policy_book(book, world, world_overrides=overrides,
                                  max_joint_assignments=128,
                                  max_nodes=max_nodes)
    elapsed_ms = (time.perf_counter_ns() - begin) / 1_000_000
    product = prod(len(r.combo_weights) for r in world.ranges)
    legal = (len(enumerate_joint_assignments(
        world.ranges, world.hero_cards + world.board_cards,
        max_combinations=128))
        if result.status == "COMPLETE_CONDITIONAL_FIXED_POLICY" else None)
    row = {"case_id": group + "/" + world_name,
           "status": result.status, "reasons": list(result.reasons),
           "joint_range_product": product, "legal_joint_assignments": legal,
           "nodes": result.nodes, "elapsed_ms": round(elapsed_ms, 3),
           "declared_world_sha256": declared_world_sha256,
           "world_scenario_sha256": result.world_scenario_sha256,
           "policy_book_sha256": book.book_sha256,
           "model_knowledge_regret_chips": None,
           "model_knowledge_regret_scope": "NOT_COMPUTED_FOR_OUT_OF_FAMILY_OVERRIDE"
           if overrides else "SAME_KERNEL_WITH_WORLD_MODEL_KNOWN_IN_ADVANCE",
           "world_model_best_action": None,
           "frozen_root_action": action_data(next(
               item.action for item in book.decisions
               if item.history == world.history))}
    if result.status != "COMPLETE_CONDITIONAL_FIXED_POLICY":
        return row
    if result.world_scenario_sha256 != declared_world_sha256:
        raise ValueError("evaluation_world_identity_mismatch")
    row["metrics"] = _metrics(result)
    row["delta_vs_check_fold_chips"] = str(result.delta_vs_check_fold_chips)
    row["delta_vs_check_call_chips"] = str(result.delta_vs_check_call_chips)
    row["history_likelihood"] = str(result.history_likelihood)
    if not overrides:
        known = analyze_threeway_river(world, max_joint_assignments=128,
                                       max_nodes=max_nodes)
        if known.status == "COMPLETE_CONDITIONAL_ABSTRACTION":
            regret = known.best_ev - result.metrics[0].net_ev_chips
            if regret < 0:
                raise ValueError("negative_model_knowledge_regret")
            row["model_knowledge_regret_chips"] = str(regret)
            row["world_model_best_action"] = action_data(known.best_action)
            row["world_model_planning_nodes"] = known.nodes
        else:
            row["model_knowledge_regret_scope"] = "WORLD_REPLAN_BLOCKED"
            row["world_model_reasons"] = list(known.reasons)
    return row


def capacity_probes(plan):
    """Exercise rejection boundaries without relaxing production budgets."""
    folded = next(seat for seat in plan.seats
                  if seat.status is PlayerStatus.FOLDED)
    four_active = replace(plan, seats=tuple(
        replace(seat, status=PlayerStatus.ACTIVE)
        if seat.seat_id == folded.seat_id else seat for seat in plan.seats))
    one_all_in = replace(plan, seats=tuple(
        replace(seat, status=PlayerStatus.ALL_IN)
        if seat.seat_id == plan.action_order[-1] else seat
        for seat in plan.seats))
    combos = ("2c2d", "2h2s", "3c3d", "3h3s", "4c4d", "4h4s",
              "5c5d", "5h5s", "6c6d", "6h6s", "7c7d", "7h7s")
    over_joint = replace(plan, ranges=tuple(replace(
        item, combo_weights={combo: Decimal(1) for combo in combos})
        for item in plan.ranges))
    declared = (
        ("node_budget_1", plan, {"max_nodes": 1}),
        ("joint_budget_1", plan, {"max_joint_assignments": 1}),
        ("default_joint_budget_128", over_joint, {}),
        ("unknown_fees", replace(plan, other_fees=None), {}),
        ("four_active", four_active, {}),
        ("one_all_in", one_all_in, {}),
    )
    rows = []
    for name, scenario, kwargs in declared:
        result = analyze_threeway_river(scenario, **kwargs)
        rows.append({"probe": name, "status": result.status,
                     "reasons": list(result.reasons),
                     "best_action": None if result.best_action is None
                     else action_data(result.best_action),
                     "strategy_eligible": result.strategy_eligible,
                     "advice_emitted": result.advice_emitted})
    return rows


def run_benchmark(baseline_path=DEFAULT_BASELINE,
                  input_path=DEFAULT_INPUT, protocol_path=DEFAULT_PROTOCOL,
                  output=None):
    frozen = load_frozen_baseline(baseline_path)
    if (frozen.get("schema_version") != 1
            or frozen.get("baseline_id") != "BASELINE_V1"
            or frozen.get("base_commit") != BASE_COMMIT
            or frozen.get("scope") != MODEL_SCOPE
            or frozen.get("source_sha256") != source_hashes()
            or frozen.get("real_hand_acceptance_pending") is not True
            or frozen.get("strategy_eligible") is not False
            or frozen.get("advice_emitted") is not False):
        raise ValueError("invalid_or_drifted_baseline")
    plans, protocol, input_hash, protocol_hash = planning_scenarios(
        input_path, protocol_path)
    if (input_hash != frozen["input_sha256"]
            or protocol_hash != frozen["protocol_sha256"]
            or protocol["worlds"] != frozen["worlds"]
            or len(plans) != frozen["groups"]
            or set(plans) != set(frozen["books"])):
        raise ValueError("baseline_input_or_protocol_drift")
    # This named model is declared in the frozen protocol and never fitted to
    # evaluation outcomes. The old study's synthetic training selection is not
    # run here; only its explicit world-construction vocabulary is reused.
    calling = next(candidate for candidate in public_candidates((1, 2))
                   if candidate.candidate_id == "calling_public_v1")
    cases = []
    for group, plan in plans.items():
        book = book_from_data(frozen["books"][group])
        for world_name in protocol["worlds"]:
            world, overrides = world_scenario(plan, world_name, calling)
            cases.append(_case(group, world_name, book, world, overrides,
                               frozen["max_nodes"]))
    complete = [row for row in cases
                if row["status"] == "COMPLETE_CONDITIONAL_FIXED_POLICY"]
    negative = [row["case_id"] for row in complete
                if (Fraction(row["delta_vs_check_fold_chips"]) < 0
                    or Fraction(row["delta_vs_check_call_chips"]) < 0)]
    regrets = sorted(((Fraction(row["model_knowledge_regret_chips"]),
                       row["case_id"]) for row in complete
                      if row["model_knowledge_regret_chips"] is not None),
                     reverse=True)
    stable = {
        "schema_version": 1, "baseline_id": "BASELINE_V1",
        "base_commit": BASE_COMMIT, "scope": MODEL_SCOPE,
        "baseline_file_sha256": digest(Path(baseline_path).read_bytes()),
        "case_count": len(cases), "complete_count": len(complete),
        "blocked_count": len(cases) - len(complete),
        "negative_vs_simple_policy_case_ids": negative,
        "worst_model_knowledge_regret": [
            {"case_id": name, "chips": str(value)} for value, name in regrets[:5]],
        "cases": [{k: v for k, v in row.items() if k != "elapsed_ms"}
                  for row in cases],
        "capacity_probes": capacity_probes(plans["n6-facing_bet"]),
        "strategy_eligible": False, "advice_emitted": False,
        "real_hand_acceptance_pending": True,
        "qualification": [
            "manual_synthetic_worlds_not_empirical_opponent_population",
            "conditional_river_chip_EV_not_full_hand_bb_per_100_or_profit",
            "model_knowledge_regret_reuses_planner_kernel_not_independent_oracle",
            "no_real_hand_visual_or_strategy_acceptance",
        ],
    }
    report = {**stable, "deterministic_sha256": digest(stable_json(stable).encode()),
              "runtime": {
                  "python": sys.version.split()[0],
                  "platform": platform.platform(),
                  "processor": platform.processor(),
                  "case_elapsed_ms": {row["case_id"]: row["elapsed_ms"]
                                      for row in cases},
                  "max_case_elapsed_ms": max(row["elapsed_ms"] for row in cases),
                  "total_case_elapsed_ms": round(sum(
                      row["elapsed_ms"] for row in cases), 3),
              }}
    if output is not None:
        write_json(output, report)
    return report


def verify_published_results(actual, expected):
    """Check the published payload itself, not only its untrusted digest field."""
    if not isinstance(expected, dict):
        raise ValueError("invalid_published_results")
    stable = {key: value for key, value in expected.items()
              if key not in ("runtime", "deterministic_sha256")}
    claimed = expected.get("deterministic_sha256")
    if claimed != digest(stable_json(stable).encode()):
        raise ValueError("published_results_digest_mismatch")
    actual_stable = {key: value for key, value in actual.items()
                     if key not in ("runtime", "deterministic_sha256")}
    if stable != actual_stable:
        raise ValueError("baseline_results_drift")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run", "check"))
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    try:
        if args.mode == "freeze":
            value = freeze_baseline(args.input, args.protocol, args.baseline)
            summary = {"baseline_id": value["baseline_id"],
                       "groups": value["groups"],
                       "books": len(value["books"])}
        else:
            report = run_benchmark(args.baseline, args.input, args.protocol,
                                   args.output if args.mode == "run" else None)
            if args.mode == "check":
                verify_published_results(report, read_json(args.output))
            summary = {key: report[key] for key in (
                "case_count", "complete_count", "blocked_count",
                "deterministic_sha256")}
    except (OSError, ValueError, KeyError, TypeError,
            subprocess.CalledProcessError) as exc:
        parser.exit(2, f"strategy evaluation rejected: {exc}\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
