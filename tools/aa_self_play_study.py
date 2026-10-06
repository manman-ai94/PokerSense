"""Run a frozen nine-case local self-play study; no promotion or paid services."""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform

from poker_engine.strategy.aa_frozen_policy import FrozenResearchPolicy, canonical_hash
from poker_engine.strategy.aa_arena_evaluation import (
    check_call_policy, check_fold_policy, evaluate_paired, min_raise_policy,
    pot_raise_policy,
)

if __package__:
    from tools.aa_full_hand_lab import (
        ROOT, DEFAULT_PROTOCOL, DEFAULT_RULES, checkpoint_writer, read_json, rules_for,
        run_training, write_new,
    )
else:  # Support `python tools/aa_self_play_study.py` as well as `python -m tools...`.
    from aa_full_hand_lab import (
        ROOT, DEFAULT_PROTOCOL, DEFAULT_RULES, checkpoint_writer, read_json, rules_for,
        run_training, write_new,
    )


SOURCE_FILES = (
    "tools/aa_self_play_study.py", "tools/aa_full_hand_lab.py",
    "src/poker_engine/strategy/aa_full_hand_arena.py",
    "src/poker_engine/strategy/aa_arena_evaluation.py",
    "src/poker_engine/strategy/aa_mccfr.py",
    "src/poker_engine/strategy/aa_frozen_policy.py",
    "src/poker_engine/strategy/aa_rules_v2.py",
)
OPPONENTS = {"check_call": check_call_policy, "min_raise": min_raise_policy,
             "pot_raise": pot_raise_policy}


def _file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _source_hashes():
    return {name: _file_hash(ROOT / name) for name in SOURCE_FILES}


def _assert_sources(expected):
    if _source_hashes() != expected:
        raise ValueError("study_source_changed_after_freeze")


def _replace_report(path, document):
    temporary = path.with_suffix(".pending.json")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
    temporary.replace(path)


def _validate(protocol, seconds, iterations, nodes, infosets, actions):
    if (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0
            or any(type(value) is not int or value <= 0
                   for value in (iterations, nodes, infosets, actions))):
        raise ValueError("explicit_positive_finite_budgets_required")
    if (protocol.get("protocol_id") != "AA_FULL_HAND_PROSPECTIVE_V1"
            or protocol.get("player_counts") != [6, 7, 8]
            or protocol.get("paired_blocks_per_player_count_per_opponent") != 2000
            or protocol.get("strategy_eligible") is not False
            or protocol.get("advice_emitted") is not False):
        raise ValueError("unsupported_nine_case_prospective_protocol")
    seeds = protocol.get("training_seeds")
    if (not isinstance(seeds, list) or len(seeds) != 3
            or any(type(seed) is not int for seed in seeds) or len(set(seeds)) != 3):
        raise ValueError("protocol_requires_three_distinct_training_seeds")
    for key in ("main_stack_depth_bb", "bootstrap_samples", "evaluation_seed_start",
                "confirmation_seed_start", "training_deal_seed_min"):
        if type(protocol.get(key)) is not int or protocol[key] <= 0:
            raise ValueError("invalid_prospective_protocol_field:" + key)
    if (protocol["training_deal_seed_min"] != 2 ** 62
            or protocol.get("confidence") != 0.95
            or protocol["bootstrap_samples"] < 100
            or protocol["evaluation_seed_start"] + 2000
            > protocol["confirmation_seed_start"]
            or protocol["confirmation_seed_start"] + 2000
            > protocol["training_deal_seed_min"]):
        raise ValueError("protocol_seed_domains_or_bootstrap_budget_invalid")


def _artifacts(directory):
    return {path.name: _file_hash(path) for path in sorted(directory.glob("*.json"))
            if not path.name.endswith(".pending.json")}


def run_study(output, *, training_seconds, iterations, max_nodes, max_infosets,
              max_actions, smoke=False, protocol_path=DEFAULT_PROTOCOL,
              rules_path=DEFAULT_RULES):
    """Freeze all nine cases before fitting; retain errors and partial checkpoints.

    Training has one wall-clock budget per case, not per iteration. Evaluation
    has fixed blocks and per-hand action limits. --smoke caps training at 2s,
    2000 nodes/infosets and one sweep, and uses two blocks with 100 bootstraps.
    No study outcome promotes policy or establishes empirical poker strength.
    """
    protocol = read_json(protocol_path)
    _validate(protocol, training_seconds, iterations, max_nodes, max_infosets,
              max_actions)
    rules_by_count = {n: rules_for(rules_path, n) for n in (6, 7, 8)}
    effective = {
        "training_seconds": min(training_seconds, 2.0) if smoke else training_seconds,
        "iterations": min(iterations, 1) if smoke else iterations,
        "max_nodes": min(max_nodes, 2000) if smoke else max_nodes,
        "max_infosets": min(max_infosets, 2000) if smoke else max_infosets,
        "max_actions": min(max_actions, 200) if smoke else max_actions,
        "paired_blocks": 2 if smoke else 2000,
        "bootstrap_samples": 100 if smoke else protocol["bootstrap_samples"],
        "policy_seed": 7719, "bootstrap_seed": 0,
    }
    cases = [{"run_id": f"n{n}-seed{seed}", "players": n, "training_seed": seed,
              "depth_bb": protocol["main_stack_depth_bb"],
              "rules_fingerprint": rules_by_count[n].fingerprint,
              "expected_pairs": n * effective["paired_blocks"] * len(OPPONENTS)}
             for n in (6, 7, 8) for seed in protocol["training_seeds"]]
    sources = _source_hashes()
    manifest = {
        "schema_version": 1, "study_kind": "AA_SELF_PLAY_STUDY_V1",
        "mode": "ENGINEERING_SMOKE_ONLY" if smoke else "SYNTHETIC_RESEARCH_ONLY",
        "protocol_sha256": canonical_hash(protocol),
        "source_files_sha256": sources, "source_sha256": canonical_hash(sources),
        "dependencies": {"python": platform.python_version(),
                         "pokerkit": version("pokerkit")},
        "requested_budgets": {"training_seconds": training_seconds,
                              "iterations": iterations, "max_nodes": max_nodes,
                              "max_infosets": max_infosets, "max_actions": max_actions},
        "effective_budgets": effective,
        "configured_total_training_budget_seconds": effective["training_seconds"] * 9,
        "baseline": "check_fold_v1", "opponents": sorted(OPPONENTS),
        "expected_runs": 9, "cases": cases,
        "rules_by_player_count": {str(n): r.to_dict()
                                  for n, r in rules_by_count.items()},
        "selection": "retain_all_nine_no_best_seed_or_tuning",
        "strategy_eligible": False, "advice_emitted": False,
        "promotion": "NOT_PERMITTED_BY_THIS_STUDY",
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "protocol.json", protocol)
    write_new(output / "frozen-manifest.json", manifest)
    manifest_hash = _file_hash(output / "frozen-manifest.json")
    runs = [{**deepcopy(case), "status": "NOT_STARTED", "train_attempted": False,
             "evaluation_attempted": False, "training_status": "NOT_STARTED",
             "evaluation_status": "NOT_STARTED", "metrics": None,
             "complete_pairs": 0, "blocked_pairs": 0,
             "unreported_pairs": case["expected_pairs"], "artifacts": {}}
            for case in cases]

    def summary():
        complete = sum(row["status"] == "COMPLETE" for row in runs)
        return {
            "schema_version": 1, "mode": manifest["mode"],
            "status": "COMPLETE_RESEARCH_EXECUTION" if complete == 9 else "PARTIAL",
            "expected_runs": 9, "actual_runs": len(runs),
            "started_runs": sum(row["train_attempted"] for row in runs),
            "complete_runs": complete, "incomplete_runs": 9 - complete,
            "expected_pairs": sum(row["expected_pairs"] for row in runs),
            "complete_pairs": sum(row["complete_pairs"] for row in runs),
            "blocked_pairs": sum(row["blocked_pairs"] for row in runs),
            "unreported_pairs": sum(row["unreported_pairs"] for row in runs),
            "manifest_sha256": manifest_hash,
            "protocol_sha256": manifest["protocol_sha256"],
            "source_sha256": manifest["source_sha256"], "runs": deepcopy(runs),
            "strategy_eligible": False, "advice_emitted": False,
            "strategy_quality": "NOT_ASSESSED",
            "promotion": "BLOCKED_PENDING_INDEPENDENT_AND_LIVE_ACCEPTANCE",
            "metrics": None,
            "limitations": ["synthetic_scripts_are_not_real_opponent_pool",
                            "missing_or_failed_runs_remain_in_denominator",
                            "partial_training_is_saved_but_not_a_successful_full_run",
                            "unreported_pairs_are_not_claimed_executed_or_successful",
                            "no_retry_tuning_best_seed_selection_or_promotion"],
        }

    _replace_report(output / "study-report.json", summary())
    interrupted = False
    for row in runs:
        if interrupted:
            row["status"] = "NOT_RUN_INTERRUPTED"
            continue
        directory = output / row["run_id"]
        directory.mkdir()
        rules = rules_by_count[row["players"]]
        try:
            write_new(directory / "rules.json", rules.to_dict())
            _assert_sources(sources)
            row["train_attempted"] = True
            row["status"] = "RUNNING_TRAINING"
            row["training_status"] = "RUNNING"
            _replace_report(output / "study-report.json", summary())
            training, checkpoint, policy = run_training(
                rules, depth=row["depth_bb"], protocol=deepcopy(protocol),
                iterations=effective["iterations"], seed=row["training_seed"],
                seconds=effective["training_seconds"], max_nodes=effective["max_nodes"],
                max_infosets=effective["max_infosets"],
                checkpoint_sink=checkpoint_writer(directory),
            )
            write_new(directory / "training-report.json", training)
            write_new(directory / "checkpoint.json", checkpoint)
            write_new(directory / "policy.json", policy)
            row["training_status"] = training["status"]
            _assert_sources(sources)
            frozen = FrozenResearchPolicy(read_json(directory / "policy.json"))
            row["evaluation_attempted"] = True
            row["status"] = "RUNNING_EVALUATION"
            row["evaluation_status"] = "RUNNING"
            _replace_report(output / "study-report.json", summary())
            evaluation = evaluate_paired(
                rules, frozen, check_fold_policy, dict(OPPONENTS),
                seeds=list(range(protocol["evaluation_seed_start"],
                                 protocol["evaluation_seed_start"]
                                 + effective["paired_blocks"])),
                candidate_id=frozen.sha256, baseline_id="check_fold_v1",
                starting_stacks=(rules.big_blind * row["depth_bb"],) * row["players"],
                bootstrap_samples=effective["bootstrap_samples"],
                bootstrap_seed=effective["bootstrap_seed"],
                max_actions=effective["max_actions"],
                policy_seed=effective["policy_seed"],
            )
            write_new(directory / "evaluation-report.json", evaluation)
            _assert_sources(sources)
            if (evaluation["expected_pairs"] != row["expected_pairs"]
                    or evaluation["complete_pairs"] + evaluation["blocked_pairs"]
                    != row["expected_pairs"]):
                raise ValueError("evaluation_denominator_mismatch")
            row.update(evaluation_status=evaluation["status"],
                       complete_pairs=evaluation["complete_pairs"],
                       blocked_pairs=evaluation["blocked_pairs"], unreported_pairs=0)
            if (training["status"] == "COMPLETE_RESEARCH_RUN"
                    and evaluation["status"] == "COMPLETE"
                    and not evaluation["blocked_pairs"]):
                row["status"] = "COMPLETE"
                row["metrics"] = deepcopy(evaluation["groups"])
            else:
                row["status"] = "BLOCKED"
        except KeyboardInterrupt:
            row["status"] = "INTERRUPTED"
            for key in ("training_status", "evaluation_status"):
                if row[key] == "RUNNING":
                    row[key] = "INTERRUPTED"
            row["error"] = {"type": "KeyboardInterrupt", "message": "study_interrupted"}
            interrupted = True
        except Exception as exc:
            row["status"] = "ERROR"
            for key in ("training_status", "evaluation_status"):
                if row[key] == "RUNNING":
                    row[key] = "ERROR"
            row["error"] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            row["artifacts"] = _artifacts(directory)
            _replace_report(output / "study-report.json", summary())
    report = summary()
    _replace_report(output / "study-report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--training-seconds", type=float, required=True)
    parser.add_argument("--iterations", type=int, required=True)
    parser.add_argument("--max-nodes", type=int, required=True)
    parser.add_argument("--max-infosets", type=int, required=True)
    parser.add_argument("--max-actions", type=int, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    report = run_study(
        args.output, training_seconds=args.training_seconds,
        iterations=args.iterations,
        max_nodes=args.max_nodes, max_infosets=args.max_infosets,
        max_actions=args.max_actions, smoke=args.smoke,
        protocol_path=args.protocol, rules_path=args.rules,
    )
    print(json.dumps({"report": str((args.output / "study-report.json").resolve()),
                      "status": report["status"], "expected_runs": 9,
                      "actual_runs": report["actual_runs"],
                      "strategy_eligible": False}))
    return 130 if any(row["status"] == "INTERRUPTED" for row in report["runs"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
