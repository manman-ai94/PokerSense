"""Reproduce the fixed real frozen-policy path; never train or alter old receipts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from poker_engine.strategy.aa_arena_evaluation import (
    check_call_policy, check_fold_policy, evaluate_paired, min_raise_policy,
    pot_raise_policy,
)
from poker_engine.strategy.aa_frozen_policy import (
    FrozenResearchPolicy, action_ids, information_key, make_policy,
)
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
from tools.aa_full_hand_lab import DEFAULT_RULES, read_json, rules_for, write_new


CONTROL_SEEDS = (4441, 4442)


def known_control(rules, seeds=CONTROL_SEEDS):
    """Declared check/call wiring fixture, explicitly not a learned candidate."""
    table = {}
    for seed in seeds:
        arena = AAFullHandArena(rules).reset(seed)
        while not arena.terminal:
            obs = arena.observe(arena.actor)
            table[information_key(obs)] = {key: float(key == "check_call")
                                           for key in action_ids(obs)}
            arena.step("check_call")
    return make_policy(
        rules_fingerprint=rules.fingerprint, table_size=rules.table_size,
        stack_depth_bb=100, policy=table,
        training={"kind": "DECLARED_WIRING_CONTROL_NOT_LEARNED",
                  "development_seeds": list(seeds)},
    )


def source_hashes(source):
    files = [source / name for name in
             ("protocol.json", "study-report.json", "frozen-manifest.json")]
    for n in (6, 7, 8):
        for seed in (1103, 2207, 3301):
            for name in ("policy.json", "rules.json", "evaluation-report.json",
                         "training-report.json", "checkpoint.json",
                         "latest-checkpoint.json"):
                files.append(source / f"n{n}-seed{seed}" / name)
    return {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


def diagnose(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.is_relative_to(source):
        raise ValueError("diagnostic_output_must_not_be_inside_original_source")
    before = source_hashes(source)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "input-manifest.json", before)
    summary = {"schema_version": 1, "original_failures": {}, "rerun_failures": {},
               "controls": [], "reruns": [], "policy_entries": 0,
               "uniform_entries": 0, "strategy_eligible": False,
               "empirical_strategy": "NOT_ASSESSED"}
    old_errors, new_errors = Counter(), Counter()
    for n in (6, 7, 8):
        rules = rules_for(DEFAULT_RULES, n)
        artifact = known_control(rules)
        write_new(output / f"control-n{n}-policy.json", artifact)
        frozen = FrozenResearchPolicy(read_json(output / f"control-n{n}-policy.json"))
        control = evaluate_paired(
            rules, frozen, check_call_policy, {"passive": check_call_policy},
            seeds=CONTROL_SEEDS, bootstrap_samples=100, record_diagnostics=True,
        )
        assert control["complete_pairs"] == n * 2
        for row in control["rows"]:
            for key in ("trace_sha256", "terminal", "return_chips"):
                assert row["candidate"][key] == row["baseline"][key]
        write_new(output / f"control-n{n}.json", control)
        summary["controls"].append({"players": n, "complete_pairs": n * 2,
                                    "status": "PASS"})
        for seed in (1103, 2207, 3301):
            folder = source / f"n{n}-seed{seed}"
            previous = read_json(folder / "evaluation-report.json")
            old_errors.update(row["candidate"].get("error", "COMPLETE")
                              for row in previous["rows"])
            artifact = read_json(folder / "policy.json")
            for dist in artifact["policy"].values():
                summary["policy_entries"] += 1
                summary["uniform_entries"] += all(
                    abs(value - 1 / len(dist)) < 1e-12 for value in dist.values())
            protocol = previous["protocol"]
            report = evaluate_paired(
                AARuleProfileV2.from_dict(read_json(folder / "rules.json")),
                FrozenResearchPolicy(artifact), check_fold_policy,
                {"check_call": check_call_policy, "min_raise": min_raise_policy,
                 "pot_raise": pot_raise_policy}, seeds=protocol["seeds"],
                bootstrap_samples=protocol["bootstrap_samples"],
                max_actions=protocol["max_actions"],
                bootstrap_seed=protocol["bootstrap_seed"],
                starting_stacks={int(k): v for k, v in
                                 protocol["starting_stacks"].items()},
                policy_seed=protocol["policy_seed"], record_diagnostics=True,
                candidate_id=artifact["sha256"], baseline_id=protocol["baseline_id"],
            )
            new_errors.update(row["candidate"].get("error", "COMPLETE")
                              for row in report["rows"])
            write_new(output / f"rerun-n{n}-seed{seed}.json", report)
            summary["reruns"].append({
                "players": n, "seed": seed,
                "expected_pairs": report["expected_pairs"],
                "complete_pairs": report["complete_pairs"],
                "diagnostics": report["candidate_diagnostics"],
            })
    summary.update(
        original_failures=dict(old_errors), rerun_failures=dict(new_errors),
        original_files_unchanged=source_hashes(source) == before,
    )
    assert summary["original_files_unchanged"]
    write_new(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(args.source, args.output)
    print(json.dumps({key: report[key] for key in
                      ("original_failures", "rerun_failures", "policy_entries",
                       "uniform_entries", "original_files_unchanged")}))


if __name__ == "__main__":
    main()
