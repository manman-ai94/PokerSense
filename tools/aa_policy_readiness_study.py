"""Frozen, killable offline policy readiness study. No live or strength admission.

Usage: freeze --output NEW_DIRECTORY; train --output DIRECTORY; evaluate --output
DIRECTORY. Every invocation has a hard external batch watchdog (at most 3600s).
Resume continues only uncommitted work, at the original identity and budgets.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import distribution
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from poker_engine.strategy.aa_frozen_policy import (
    ENCODER_VERSION, FrozenResearchPolicy, canonical_hash, information_key,
    make_policy,
)
from poker_engine.strategy.aa_learning_diagnostics import learning_summary, memory_usage
from poker_engine.strategy.aa_mccfr import (
    ExternalSamplingMCCFR, NUMERICAL_SEMANTICS, TrainingBudget, TrainingBudgetExceeded,
)
from tools.aa_full_hand_lab import (
    ROOT, DEFAULT_RULES, AAFullHandArena, read_json, rules_for, write_new,
)


VERSIONS = ("V1_FIXED", "V2")
TRAINING_SEEDS = (1103, 2207, 3301)
OPPONENT_NAMES = ("check_call", "min_raise", "pot_raise")
EVALUATION_SEEDS = tuple(range(6000000, 6000030))
MAX_BATCH_SECONDS = 3600.0
TERMINAL_JOB_STATUSES = {"COMPLETE", "ERROR", "EXHAUSTED", "GATE_BLOCKED"}


def _hash_file(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def identity():
    """Pin the complete project Python dependency closure, not a short self-list."""
    files = sorted([*ROOT.joinpath("src").rglob("*.py"),
                    *ROOT.joinpath("tools").rglob("*.py"), ROOT / "pyproject.toml"])
    sources = {p.relative_to(ROOT).as_posix(): _hash_file(p) for p in files}
    package = distribution("pokerkit")
    dependency_files = {
        str(item): _hash_file(package.locate_file(item))
        for item in package.files or ()
        if (str(item).endswith((".py", ".pyd", ".so", "/RECORD", "/METADATA"))
            and Path(package.locate_file(item)).is_file())
    }
    return {"sources": sources, "sources_sha256": canonical_hash(sources),
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "python_executable_sha256": _hash_file(sys.executable),
            "pokerkit_version": package.version,
            "pokerkit_files": dependency_files,
            "pokerkit_sha256": canonical_hash(dependency_files)}


def _validate_number(value, name, maximum=None):
    if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            or maximum is not None and value > maximum):
        raise ValueError("invalid_positive_finite_budget:" + name)


def _atomic(path, value):
    """Only mutable journals/checkpoint pointers use replacement; evidence is new."""
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _bound_document(document):
    document = deepcopy(document)
    document["sha256"] = canonical_hash(document)
    return document


def _check_document(document):
    copy = deepcopy(document)
    if copy.pop("sha256", None) != canonical_hash(copy):
        raise ValueError("study_document_digest_mismatch")
    return document


def freeze(output, *, training_seconds=60, requested_sweeps=100000,
           max_nodes=1000000, max_infosets=100000, max_actions=1000,
           rules_path=DEFAULT_RULES):
    from poker_engine.strategy.aa_policy_encoding_v2 import (
        ABSTRACTION_DISCLOSURE, ENCODER_VERSION_V2,
    )
    from tools.aa_policy_street_challenges import CHALLENGE_SPEC, challenge_observations
    _validate_number(training_seconds, "training_seconds", 60)
    for name, value in (("requested_sweeps", requested_sweeps),
                        ("max_nodes", max_nodes),
                        ("max_infosets", max_infosets), ("max_actions", max_actions)):
        if type(value) is not int or value <= 0:
            raise ValueError("invalid_count_budget:" + name)
    rules = {str(n): rules_for(rules_path, n).to_dict() for n in (6, 7, 8)}
    query_schedules = {}
    for n in (6, 7, 8):
        profile = rules_for(rules_path, n)
        query_schedules[str(n)] = {}
        for kind in CHALLENGE_SPEC["kinds"]:
            schedules = [[{"actor": obs["actor"], "street": obs["street"]}
                          for obs in challenge_observations(profile, kind, seed)]
                         for seed in (4441, 4442)]
            if schedules[0] != schedules[1]:
                raise ValueError("query_schedule_depends_on_development_deal")
            query_schedules[str(n)][kind] = schedules[0]
    cases = [{"id": f"{variant.lower()}-n{n}-seed{seed}", "version": variant,
              "players": n, "training_seed": seed,
              "expected_pairs": n * len(EVALUATION_SEEDS) * len(OPPONENT_NAMES),
              "expected_queries": (len(CHALLENGE_SPEC["seeds"]) * sum(
                  len(rows) for rows in query_schedules[str(n)].values())
                  if variant == "V2" else 0)}
             for variant in VERSIONS for n in (6, 7, 8) for seed in TRAINING_SEEDS]
    jobs = []
    for case in cases:
        for operation in ("train", "control"):
            jobs.append({"id": case["id"] + "-" + operation,
                         "case_id": case["id"], "operation": operation,
                         "expected_pairs": 0,
                         "seconds": (training_seconds
                                     if operation == "train" else 5.0)})
        for opponent in OPPONENT_NAMES:
            jobs.append({"id": case["id"] + "-evaluate-" + opponent,
                         "case_id": case["id"], "operation": "evaluate",
                         "opponent": opponent,
                         "expected_pairs": case["players"] * len(EVALUATION_SEEDS)})
        if case["version"] == "V2":
            jobs.append({"id": case["id"] + "-query", "case_id": case["id"],
                         "operation": "query", "expected_pairs": 0,
                         "expected_queries": case["expected_queries"]})
    protocol = {
        "kind": "AA_POLICY_READINESS_V2", "player_counts": [6, 7, 8],
        "versions": list(VERSIONS), "training_seeds": list(TRAINING_SEEDS),
        "numerical_semantics": NUMERICAL_SEMANTICS,
        "encoders": {"V1_FIXED": ENCODER_VERSION, "V2": ENCODER_VERSION_V2},
        "v2_abstraction_disclosure": ABSTRACTION_DISCLOSURE,
        "street_query_spec": deepcopy(CHALLENGE_SPEC),
        "street_query_spec_sha256": canonical_hash(CHALLENGE_SPEC),
        "street_query_schedules": query_schedules,
        "query_schedule_provenance": "POLICY_FREE_SCRIPTS_ON_DEVELOPMENT_4441_4442",
        "training_deal_domain": [2 ** 62, 2 ** 63],
        "evaluation_seeds": list(EVALUATION_SEEDS),
        "confirmation_seed_domain_reserved": [4000000, 4000030],
        "old_evaluation_seeds": {
            "original_million_domain": "DEVELOPMENT_ONLY",
            "prior_three_million_protocol": "RETIRED_BEFORE_FIT_NOT_CONFIRMATION",
            "engineering_fixture_domains": [17, 19, [700, 730]],
        },
        "main_depth_bb": 100, "training_seconds": training_seconds,
        "requested_sweeps": requested_sweeps, "max_nodes": max_nodes,
        "max_infosets": max_infosets, "max_actions": max_actions,
        "control": {"update_regrets": False, "requested_sweeps": 2, "seconds": 5,
                    "purpose": "engineering_negative_control_not_resource_comparison"},
        "gate2": {"minimum_sweeps": 2, "nonuniform_tv_threshold": 1e-8,
                  "require_repeated_exported_nonuniform_infoset": True,
                  "every_v2_training_seed_must_pass": True},
        "gate3": {"minimum_complete_hand_fraction_each_case": 0.8,
                  "all_streets_require_positive_cases": True,
                  "illegal_actions": 0, "private_information_leaks": 0},
        "policy_seed": 7719, "bootstrap_samples": 100,
        "no_automatic_promotion": True,
        "no_fallback_for_unknown_policy": True,
        "unobserved_street_suffix": "UNKNOWN_NOT_A_HIT_OR_MISS",
        "batch_deadline_includes": ["identity", "train", "evaluate", "save"],
        "max_batch_seconds": MAX_BATCH_SECONDS,
        "training_budget_includes": "whole_case_fit_and_checkpoint_save",
        "final_serialization_reserve": {"seconds_cap": 5.0, "slot_fraction": 0.2,
                                        "within_frozen_case_budget": True},
        "evaluation_shard": "candidate_style; atomic_one_seed_all_hero_rotations",
    }
    manifest = _bound_document({
        "schema_version": 1, "protocol": protocol, "identity": identity(),
        "rules": rules, "rules_source_sha256": _hash_file(rules_path),
        "cases": cases, "jobs": jobs, "expected_cases": 18,
        "expected_pairs": sum(case["expected_pairs"] for case in cases),
        "expected_queries": sum(case["expected_queries"] for case in cases),
        "strategy_eligible": False, "advice_emitted": False,
    })
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "frozen-manifest.json", manifest)
    state = {"manifest_sha256": manifest["sha256"], "jobs": {
        job["id"]: {"status": "NOT_STARTED", "attempts": [],
                    "charged_seconds": 0.0, "error": None}
        for job in jobs}}
    _atomic(output / "study-state.json", state)
    _atomic(output / "study-report.json", summarize(output, manifest, state))
    return manifest


def load_frozen(output, *, check_identity=True):
    output = Path(output)
    manifest = _check_document(read_json(output / "frozen-manifest.json"))
    expected_cases = {(variant, n, seed) for variant in VERSIONS
                      for n in (6, 7, 8) for seed in TRAINING_SEEDS}
    if (manifest.get("expected_cases") != 18 or len(manifest["cases"]) != 18
            or {(row["version"], row["players"], row["training_seed"])
                for row in manifest["cases"]} != expected_cases
            or len({row["id"] for row in manifest["cases"]}) != 18
            or len(manifest["jobs"]) != 99
            or len({row["id"] for row in manifest["jobs"]}) != 99):
        raise ValueError("frozen_case_or_job_denominator_mismatch")
    if check_identity and manifest["identity"] != identity():
        raise ValueError("study_source_or_dependency_drift")
    state = read_json(output / "study-state.json")
    if state.get("manifest_sha256") != manifest["sha256"]:
        raise ValueError("study_state_manifest_mismatch")
    if set(state["jobs"]) != {job["id"] for job in manifest["jobs"]}:
        raise ValueError("study_state_job_denominator_mismatch")
    return manifest, state


def _components(variant):
    if variant == "V1_FIXED":
        return ENCODER_VERSION, information_key, make_policy, FrozenResearchPolicy
    if variant != "V2":
        raise ValueError("unknown_study_variant")
    from poker_engine.strategy.aa_policy_encoding_v2 import (
        ENCODER_VERSION_V2, information_key_v2,
    )
    from poker_engine.strategy.aa_frozen_policy_v2 import (
        make_policy_v2, FrozenResearchPolicyV2,
    )
    return (ENCODER_VERSION_V2, information_key_v2, make_policy_v2,
            FrozenResearchPolicyV2)


def _context(output, job_id):
    from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
    manifest, _ = load_frozen(output)
    job = next(row for row in manifest["jobs"] if row["id"] == job_id)
    case = next(row for row in manifest["cases"] if row["id"] == job["case_id"])
    rules = AARuleProfileV2.from_dict(manifest["rules"][str(case["players"])])
    directory = Path(output) / job["id"]
    directory.mkdir(exist_ok=True)
    binding = {"manifest_sha256": manifest["sha256"], "case": case,
               "job_id": job_id, "operation": job["operation"],
               "rules": rules.to_dict(),
               "rules_fingerprint": rules.fingerprint, "stack_depth_bb": "100"}
    return manifest, job, case, rules, directory, binding


def _checkpoint(path, binding, trainer, elapsed):
    value = _bound_document({"binding": binding, "trainer": trainer.checkpoint(),
                             "elapsed_seconds": elapsed, "memory": memory_usage()})
    _atomic(path, value)


def train_job(output, job_id, seconds):
    """Runs only inside an externally killable child; save every complete sweep."""
    started = time.monotonic()
    manifest, job, case, rules, directory, binding = _context(output, job_id)
    _validate_number(seconds, "training_job_seconds", job["seconds"])
    reservation = read_json(Path(output) / "study-state.json")["jobs"][job_id]
    if (reservation["status"] != "RUNNING" or not reservation["attempts"]
            or reservation["attempts"][-1]["status"] != "RUNNING"
            or seconds > reservation["attempts"][-1]["reserved_seconds"]
            or seconds > job["seconds"] - reservation["charged_seconds"]):
        raise ValueError("training_job_requires_remaining_scheduler_reservation")
    if (directory / "result.json").exists():
        raise ValueError("training_job_already_committed")
    protocol = manifest["protocol"]
    encoder_id, encoder, policy_factory, frozen_type = _components(case["version"])
    control = job["operation"] == "control"
    kwargs = {"encoder": encoder, "encoder_id": encoder_id,
              "budget": TrainingBudget(max_nodes=protocol["max_nodes"],
                                       max_infosets=protocol["max_infosets"],
                                       seconds=seconds),
              "update_regrets": not control}
    checkpoint_path = directory / "latest-checkpoint.json"
    prior_elapsed = 0.0
    if checkpoint_path.exists():
        saved = _check_document(read_json(checkpoint_path))
        if saved["binding"] != binding:
            raise ValueError("study_checkpoint_binding_mismatch")
        prior_elapsed = saved["elapsed_seconds"]
        if (prior_elapsed >= job["seconds"]
                or seconds > job["seconds"] - prior_elapsed):
            raise ValueError("training_checkpoint_exhausted_frozen_case_budget")
        restore_kwargs = dict(kwargs)
        restore_kwargs.pop("encoder_id")
        trainer = ExternalSamplingMCCFR.restore(
            saved["trainer"], expected_binding=binding,
            expected_encoder=encoder_id, **restore_kwargs)
    else:
        trainer = ExternalSamplingMCCFR(range(case["players"]),
                                        seed=case["training_seed"],
                                        binding=binding, **kwargs)
        _checkpoint(checkpoint_path, binding, trainer, 0)
    stacks = (rules.big_blind * 100,) * case["players"]

    def factory(seed):
        return AAFullHandArena(rules, starting_stacks=stacks).reset(
            (seed % (2 ** 62)) + 2 ** 62)

    requested = protocol["control"]["requested_sweeps"] if control else protocol[
        "requested_sweeps"]
    deadline = started + seconds
    reason = "REQUESTED_SWEEPS_COMPLETE"
    # Reserve bounded final serialization time within the externally enforced slot.
    reserve_spec = protocol["final_serialization_reserve"]
    reserve = min(reserve_spec["seconds_cap"], seconds * reserve_spec["slot_fraction"])
    while trainer.iterations < requested:
        remaining = deadline - time.monotonic() - reserve
        if remaining <= 0:
            reason = "CASE_WALL_DEADLINE"
            break
        trainer.budget = replace(trainer.budget, seconds=remaining)
        try:
            trainer.iterate(factory)
            _checkpoint(checkpoint_path, binding, trainer,
                        prior_elapsed + time.monotonic() - started)
        except TrainingBudgetExceeded as exc:
            reason = str(exc)
            break
    elapsed = prior_elapsed + time.monotonic() - started
    policy = trainer.export(rules_fingerprint=rules.fingerprint,
                            table_size=case["players"], stack_depth_bb=100,
                            policy_factory=policy_factory)
    # Exercise actual frozen asset parsing; integrity is not performance proof.
    frozen_type(json.loads(json.dumps(policy)))
    _atomic(directory / "policy.json", policy)
    report = {"binding": binding, "stop_reason": reason,
              "last_attempt_nodes": trainer.last_attempt_nodes,
              "diagnostics": learning_summary(trainer, elapsed_seconds=elapsed),
              "policy_sha256": policy["sha256"], "encoder": encoder_id,
              "checkpoint_file_sha256": _hash_file(checkpoint_path),
              "policy_file_sha256": _hash_file(directory / "policy.json"),
              "status": "COMPLETE", "strategy_eligible": False}
    write_new(directory / "result.json", _bound_document(report))
    return report


def evaluate_job(output, job_id):
    """Resume atomic seed blocks; no completed block is executed twice."""
    from poker_engine.strategy.aa_arena_evaluation import (
        check_call_policy, check_fold_policy, evaluate_paired, min_raise_policy,
        pot_raise_policy,
    )
    manifest, job, case, rules, directory, binding = _context(output, job_id)
    existing = _result(output, job_id, manifest)
    if existing is not None:
        return existing
    policy_path = Path(output) / (case["id"] + "-train") / "policy.json"
    candidate_document = read_json(policy_path)
    frozen_type = _components(case["version"])[3]
    candidate = frozen_type(candidate_document)
    binding["policy_file_sha256"] = _hash_file(policy_path)
    opponents = {"check_call": check_call_policy, "min_raise": min_raise_policy,
                 "pot_raise": pot_raise_policy}
    for index, seed in enumerate(manifest["protocol"]["evaluation_seeds"]):
        destination = directory / f"seed-{seed}.json"
        if destination.exists():
            saved = _check_document(read_json(destination))
            if saved["binding"] != binding or saved["seed"] != seed:
                raise ValueError("evaluation_resume_binding_mismatch")
            continue
        result = evaluate_paired(
            rules, candidate, check_fold_policy,
            {job["opponent"]: opponents[job["opponent"]]}, seeds=[seed],
            candidate_id=candidate.sha256, baseline_id="check_fold_v1",
            starting_stacks=(rules.big_blind * 100,) * case["players"],
            bootstrap_samples=manifest["protocol"]["bootstrap_samples"],
            max_actions=manifest["protocol"]["max_actions"],
            # Sampling RNG is separate from deck RNG and does not expose seed.
            policy_seed=manifest["protocol"]["policy_seed"] + index,
            record_diagnostics=True,
        )
        if (result["expected_pairs"] != case["players"]
                or result["complete_pairs"] + result["blocked_pairs"]
                != case["players"]):
            raise ValueError("evaluation_block_denominator_mismatch")
        _atomic(destination, _bound_document({"binding": binding, "seed": seed,
                                              "evaluation": result}))
    report = {"binding": binding, "status": "COMPLETE",
              "seed_blocks": len(manifest["protocol"]["evaluation_seeds"]),
              "metrics": None, "strategy_eligible": False}
    write_new(directory / "result.json", _bound_document(report))
    return report


def query_job(output, job_id, *, deadline):
    from tools.aa_policy_street_challenges import (
        evaluate_queries, hidden_input_rejection_probe,
    )
    manifest, job, case, rules, directory, binding = _context(output, job_id)
    existing = _result(output, job_id, manifest)
    if existing is not None:
        return existing
    path = Path(output) / (case["id"] + "-train") / "policy.json"
    document = read_json(path)
    policy = _components(case["version"])[3](document)
    binding["policy_file_sha256"] = _hash_file(path)
    binding["query_spec_sha256"] = manifest["protocol"]["street_query_spec_sha256"]
    query_report = evaluate_queries(
        rules, policy, spec=deepcopy(manifest["protocol"]["street_query_spec"]),
        deadline=deadline)
    probe = (hidden_input_rejection_probe(rules, policy)
             if time.monotonic() < deadline else {
                 "passed": False, "cases": [], "scope": "UNEXECUTED_BUDGET"})
    report = {"binding": binding, "status": "COMPLETE", "query_report": query_report,
              "hidden_input_probe": probe, "strategy_eligible": False,
              "metrics": None}
    write_new(directory / "result.json", _bound_document(report))
    return report


def _result(output, job_id, manifest):
    path = Path(output) / job_id / "result.json"
    if not path.exists():
        return None
    result = _check_document(read_json(path))
    job = next(row for row in manifest["jobs"] if row["id"] == job_id)
    case = next(row for row in manifest["cases"] if row["id"] == job["case_id"])
    binding = result["binding"]
    if (binding["manifest_sha256"] != manifest["sha256"]
            or binding.get("case") != case
            or binding.get("job_id") != job_id
            or binding.get("operation") != job["operation"]
            or binding.get("rules") != manifest["rules"][str(case["players"])]):
        raise ValueError("result_manifest_mismatch")
    for name, field in (("policy.json", "policy_file_sha256"),
                        ("latest-checkpoint.json", "checkpoint_file_sha256")):
        if field in result and _hash_file(path.parent / name) != result[field]:
            raise ValueError("result_artifact_hash_mismatch")
    return result


def _partial_diagnostics(output, job_id, manifest):
    path = Path(output) / job_id / "latest-checkpoint.json"
    if not path.exists():
        return None
    value = _check_document(read_json(path))
    job = next(row for row in manifest["jobs"] if row["id"] == job_id)
    case = next(row for row in manifest["cases"] if row["id"] == job["case_id"])
    binding = value["binding"]
    if (binding["manifest_sha256"] != manifest["sha256"]
            or binding.get("case") != case
            or binding.get("job_id") != job_id
            or binding.get("operation") != job["operation"]):
        raise ValueError("partial_checkpoint_binding_mismatch")
    trainer = ExternalSamplingMCCFR.restore(
        value["trainer"], expected_binding=binding,
        expected_encoder=value["trainer"]["encoder_id"])
    diagnostics = learning_summary(trainer, elapsed_seconds=value["elapsed_seconds"])
    diagnostics["memory"] = value.get("memory", {
        "rss_bytes": None, "peak_rss_bytes": None,
        "source": "UNKNOWN_KILLED_TRAINING_CHILD"})
    return {"diagnostics": diagnostics,
            "final_export_validated": False, "status": "COMMITTED_CHECKPOINT_ONLY"}


def _control_comparison(output, case):
    paths = [Path(output) / (case["id"] + "-" + operation) / "policy.json"
             for operation in ("train", "control")]
    if not all(path.exists() for path in paths):
        return {"status": "UNAVAILABLE", "resource_comparable": False}
    cls = _components(case["version"])[3]
    trained, control = [cls(read_json(path)).frozen_map() for path in paths]
    shared = set(trained).intersection(control)
    distances = []
    for key in sorted(shared):
        if set(trained[key]) != set(control[key]):
            raise ValueError("control_comparison_menu_mismatch")
        distances.append(sum(abs(trained[key][a] - control[key][a])
                             for a in trained[key]) / 2)
    return {"status": "COMPARED", "shared_infosets": len(shared),
            "different_infosets": sum(value > 1e-8 for value in distances),
            "maximum_tv": max(distances, default=None),
            "train_only_infosets": len(set(trained) - shared),
            "control_only_infosets": len(set(control) - shared),
            "resource_comparable": False,
            "scope": "fixed_two_sweep_negative_control_not_equal_budget"}


def _query_success(query, spec, schedule):
    """Check row/counter consistency; development queries cannot pass admission."""
    report = query["query_report"]
    if (spec.get("version") != "AA_STREET_QUERY_CHALLENGES_V1"
            or report.get("development_only") is not False or report.get("spec") != spec
            or report.get("spec_sha256") != canonical_hash(spec)):
        return False
    counts = {street: {"opportunities": 0, "hit": 0, "illegal": 0}
              for street in ("preflop", "flop", "turn", "river")}
    scope_failures = 0
    groups = {}
    for row in report["rows"]:
        group = (row["kind"], row["seed"])
        groups.setdefault(group, []).append(row["index"])
        expected = schedule.get(row["kind"], [])
        if (type(row["index"]) is not int or row["index"] < 0
                or row["index"] >= len(expected)
                or expected[row["index"]] != {
                    "actor": row["actor"], "street": row["street"]}):
            return False
        scoped = row["kind"] != "side_pot_scope"
        if row["scope_expected"] is not scoped:
            return False
        if not scoped:
            scope_failures += row["lookup_status"] != "SCOPE_MISMATCH"
            continue
        counter = counts[row["street"]]
        counter["opportunities"] += 1
        counter["hit"] += row["lookup_status"] == "HIT"
        counter["illegal"] += row["legal"] is False
        if row["lookup_status"] == "HIT" and row["legal"] is not True:
            return False
    expected_groups = {(kind, seed) for kind in spec["kinds"] for seed in spec["seeds"]}
    if (set(groups) != expected_groups
            or any(indices != list(range(len(schedule[kind])))
                   for (kind, _), indices in groups.items())
            or counts != report["by_street"]
            or scope_failures != report["side_pot_scope_failures"]):
        return False
    positive = all(row["hit"] > 0 for row in counts.values())
    probe = query["hidden_input_probe"]
    cases = probe.get("cases", [])
    return (positive and report["all_streets_have_positive"] is True
            and all(row["illegal"] == 0 for row in counts.values())
            and scope_failures == 0 and probe.get("passed") is True
            and len(cases) == 3
            and [row["container"] for row in cases] == [None, "public_history", "rules"]
            and all(row["rejected"] is True for row in cases))


def gate2(output, manifest):
    """Recompute gates from actual bound checkpoint and export, never report flags."""
    reasons, verified_cases = [], []
    if sum(case["version"] == "V2" for case in manifest["cases"]) != 9:
        return {"status": "BLOCKED", "reasons": [{"reason": "NINE_V2_CASES_REQUIRED"}],
                "verified_cases": []}
    for case in manifest["cases"]:
        if case["version"] != "V2":
            continue
        verified = {"case": case["id"]}
        for operation in ("train", "control"):
            try:
                verified[operation] = _verified_learning(
                    output, manifest, case, operation)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                verified[operation] = None
                reasons.append({"case": case["id"],
                                "reason": operation.upper() + "_ARTIFACT_NOT_VERIFIED",
                                "detail": str(exc)})
        train, control = verified["train"], verified["control"]
        if not train or not train["learning_signal"]:
            reasons.append({"case": case["id"], "reason": "NO_LEARNING_SIGNAL"})
        if (not control or control["completed_sweeps"] < 2
                or control["nonuniform_infosets"] != 0
                or control["update_regrets"] is not False):
            reasons.append({"case": case["id"], "reason": "CONTROL_NOT_VERIFIED"})
        verified_cases.append(verified)
    return {"status": "PASS" if not reasons else "BLOCKED", "reasons": reasons,
            "verification": "RECOMPUTED_FROM_BOUND_CHECKPOINT_AND_FROZEN_EXPORT",
            "verified_cases": verified_cases}


def _verified_learning(output, manifest, case, operation):
    job_id = case["id"] + "-" + operation
    result = _result(output, job_id, manifest)
    if (result is None or result.get("status") != "COMPLETE"
            or not all(result.get(key) for key in (
                "checkpoint_file_sha256", "policy_file_sha256", "policy_sha256",
                "encoder"))):
        raise ValueError("complete_result_with_mandatory_artifact_hashes_required")
    directory = Path(output) / job_id
    saved = _check_document(read_json(directory / "latest-checkpoint.json"))
    binding = result["binding"]
    encoder_id, _, _, cls = _components(case["version"])
    if saved["binding"] != binding or result["encoder"] != encoder_id:
        raise ValueError("gate_checkpoint_binding_or_encoder_mismatch")
    trainer = ExternalSamplingMCCFR.restore(
        saved["trainer"], expected_binding=binding, expected_encoder=encoder_id,
        update_regrets=operation == "train")
    if saved["trainer"].get("numerical_semantics") != NUMERICAL_SEMANTICS:
        raise ValueError("gate_checkpoint_numerical_semantics_mismatch")
    if (trainer.players != tuple(range(case["players"]))
            or trainer.seed != case["training_seed"]):
        raise ValueError("gate_training_seed_or_players_mismatch")
    requested = (manifest["protocol"]["requested_sweeps"] if operation == "train"
                 else manifest["protocol"]["control"]["requested_sweeps"])
    if trainer.iterations > requested:
        raise ValueError("gate_training_exceeded_frozen_sweep_budget")
    if operation == "control" and any(value != 0 for row in trainer.regrets.values()
                                      for value in row.values()):
        raise ValueError("zero_update_control_has_nonzero_regret")
    document = read_json(directory / "policy.json")
    frozen = cls(document)
    if (document["sha256"] != result["policy_sha256"]
            or document["rules_fingerprint"] != binding["rules_fingerprint"]
            or document["table_size"] != case["players"]
            or document["stack_depth_bb"] != "100"
            or document["training"].get("checkpoint_sha256")
            != saved["trainer"]["sha256"]
            or document["training"].get("iterations") != trainer.iterations
            or document["training"].get("seed") != trainer.seed
            or document["training"].get("nodes") != trainer.total_nodes
            or document["training"].get("update_regrets") is not trainer.update_regrets
            or document["training"].get("numerical_semantics") != NUMERICAL_SEMANTICS
            or frozen.frozen_map() != trainer.average_policy()):
        raise ValueError("gate_export_does_not_match_committed_training_state")
    diagnostics = learning_summary(trainer, elapsed_seconds=saved["elapsed_seconds"],
                                   threshold=manifest["protocol"]["gate2"][
                                       "nonuniform_tv_threshold"])
    return {key: diagnostics[key] for key in (
        "completed_sweeps", "nonuniform_infosets",
        "repeated_exported_nonuniform_infosets", "update_regrets", "learning_signal")}


def summarize(output, manifest, state):
    from poker_engine.strategy.aa_policy_diagnostics import summarize_opportunities
    rows = []
    for case in manifest["cases"]:
        complete, blocked, evaluated = 0, 0, 0
        branches = []
        for job in manifest["jobs"]:
            if job["case_id"] != case["id"] or job["operation"] != "evaluate":
                continue
            for seed in manifest["protocol"]["evaluation_seeds"]:
                path = Path(output) / job["id"] / f"seed-{seed}.json"
                if not path.exists():
                    continue
                doc = _check_document(read_json(path))
                binding = doc["binding"]
                if (binding["manifest_sha256"] != manifest["sha256"]
                        or binding.get("case") != case
                        or binding.get("job_id") != job["id"]
                        or binding.get("operation") != "evaluate"
                        or doc["seed"] != seed
                        or binding.get("policy_file_sha256") != _hash_file(
                            Path(output) / (case["id"] + "-train") / "policy.json")):
                    raise ValueError("evaluation_manifest_mismatch")
                result = doc["evaluation"]
                branches.extend(row["candidate"] for row in result["rows"])
                complete += result["complete_pairs"]
                blocked += result["blocked_pairs"]
                evaluated += result["expected_pairs"]
        if complete + blocked != evaluated or evaluated > case["expected_pairs"]:
            raise ValueError("readiness_denominator_mismatch")
        train = _result(output, case["id"] + "-train", manifest)
        control = _result(output, case["id"] + "-control", manifest)
        query = (_result(output, case["id"] + "-query", manifest)
                 if case["version"] == "V2" else None)
        if query is not None:
            path = Path(output) / (case["id"] + "-train") / "policy.json"
            if (query["binding"].get("policy_file_sha256") != _hash_file(path)
                    or query["binding"].get("query_spec_sha256")
                    != manifest["protocol"]["street_query_spec_sha256"]):
                raise ValueError("query_artifact_binding_mismatch")
        executed_queries = (len(query["query_report"]["rows"])
                            if query is not None else 0)
        if executed_queries > case["expected_queries"]:
            raise ValueError("query_denominator_mismatch")
        coverage = summarize_opportunities(branches)
        latencies = sorted(op["policy_latency_ms"] for branch in branches
                           for op in branch.get("hero_opportunities", [])
                           if op.get("policy_latency_ms") is not None)
        timing = {"scope": "LOCAL_POLICY_CALL_ONLY_NOT_CAPTURE_TO_DISPLAY",
                  "samples": len(latencies),
                  "p95_ms": (latencies[math.ceil(0.95 * len(latencies)) - 1]
                             if latencies else None),
                  "p99_ms": (latencies[math.ceil(0.99 * len(latencies)) - 1]
                             if latencies else None)}
        first_hits = coverage["first_hero_hit"]
        coverage["first_hero_hit_fraction_all_planned_pairs"] = (
            first_hits / case["expected_pairs"])
        coverage["unobserved_first_hero_opportunities"] = (
            case["expected_pairs"] - coverage["first_hero_observed"])
        coverage_gate = (complete / case["expected_pairs"] >= 0.8
                         and all(row["hit"] > 0 for row in coverage["streets"].values())
                         and not any(coverage["failure_counts"].get(name, 0)
                                     for name in ("ILLEGAL_ACTION", "INVALID_MENU",
                                                  "ADAPTER_ERROR", "SCOPE_MISMATCH")))
        gate3_status = "NOT_ASSESSED"
        if (query is not None and evaluated == case["expected_pairs"]
                and query["query_report"]["status"] == "COMPLETE_QUERY_DIAGNOSTIC"):
            gate3_pass = (
                complete / case["expected_pairs"] >= 0.8
                and _query_success(query, manifest["protocol"]["street_query_spec"],
                                   manifest["protocol"]["street_query_schedules"][
                                       str(case["players"])])
                and not any(coverage["failure_counts"].get(name, 0)
                            for name in ("ILLEGAL_ACTION", "INVALID_MENU",
                                         "ADAPTER_ERROR", "SCOPE_MISMATCH")))
            gate3_status = "PASS_RESEARCH_EXECUTABILITY" if gate3_pass else "NO_GO"
            if query["query_report"].get("development_only"):
                gate3_status = "NOT_ASSESSED"
        rows.append({**case, "training": train, "control": control,
                     "partial_training": (None if train else _partial_diagnostics(
                         output, case["id"] + "-train", manifest)),
                     "partial_control": (None if control else _partial_diagnostics(
                         output, case["id"] + "-control", manifest)),
                     "control_comparison": _control_comparison(output, case),
                     "street_query": query, "gate3": gate3_status,
                     "executed_queries": executed_queries,
                     "unexecuted_queries": case["expected_queries"] - executed_queries,
                     "complete_pairs": complete, "blocked_pairs": blocked,
                     "unexecuted_pairs": case["expected_pairs"] - evaluated,
                     "complete_hand_fraction": complete / case["expected_pairs"],
                     "observed_prefix_coverage": coverage,
                     "local_policy_latency": timing,
                     "execution_coverage_gate": "PASS" if coverage_gate else "BLOCKED",
                     "metrics": None})
    current = manifest["identity"] == identity()
    case_gates = [row["gate3"] for row in rows if row["version"] == "V2"]
    gate3_status = ("PASS_RESEARCH_EXECUTABILITY"
                    if len(case_gates) == 9 and all(
                        value == "PASS_RESEARCH_EXECUTABILITY" for value in case_gates)
                    else "NOT_ASSESSED" if "NOT_ASSESSED" in case_gates else "NO_GO")
    return {"schema_version": 1, "manifest_sha256": manifest["sha256"],
            "source_and_dependency_identity_verified": current,
            "expected_cases": manifest["expected_cases"], "cases": rows,
            "expected_pairs": manifest["expected_pairs"],
            "complete_pairs": sum(row["complete_pairs"] for row in rows),
            "blocked_pairs": sum(row["blocked_pairs"] for row in rows),
            "unexecuted_pairs": sum(row["unexecuted_pairs"] for row in rows),
            "expected_queries": manifest["expected_queries"],
            "executed_queries": sum(row["executed_queries"] for row in rows),
            "unexecuted_queries": sum(row["unexecuted_queries"] for row in rows),
            "gate2": (gate2(output, manifest) if current else {
                "status": "BLOCKED", "reasons": [{"reason": "SOURCE_DRIFT"}]}),
            "jobs": deepcopy(state["jobs"]),
            "gate3": gate3_status if current else "SOURCE_DRIFT_BLOCKED",
            "metrics": None, "strategy_strength": "NOT_ASSESSED",
            "strategy_eligible": False, "advice_emitted": False}


class _ProcessTree:
    """Windows job object closes the entire owned tree, including nested workers."""

    def __init__(self, process, owns_group=True):
        self.process, self.handle = process, None
        self.owns_group = owns_group
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount",
                         "OtherOperationCount", "ReadTransferCount",
                         "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel = ctypes.windll.kernel32
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not handle:
            raise OSError("cannot_create_owned_process_job")
        if (not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits),
                                               ctypes.sizeof(limits))
                or not kernel.AssignProcessToJobObject(handle, int(process._handle))):
            kernel.CloseHandle(handle)
            raise OSError("cannot_bind_owned_process_job")
        self.handle, self.kernel = handle, kernel

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        elif sys.platform != "win32":
            import signal
            try:
                if self.owns_group:
                    # Nested readiness subprocesses inherit this group. Closing
                    # the outer watchdog therefore kills the whole nested tree.
                    os.killpg(self.process.pid, signal.SIGKILL)
                elif self.process.poll() is None:
                    self.process.kill()
            except ProcessLookupError:
                pass


def run_bounded(command, *, seconds, cwd=ROOT, log_path=None):
    """Actual OS timeout and kill, not Future.cancel() of a running thread."""
    _validate_number(seconds, "child_seconds", MAX_BATCH_SECONDS)
    start = time.monotonic()
    log = open(log_path, "ab") if log_path else subprocess.DEVNULL
    process, tree = None, None
    try:
        owns_group = os.environ.get("POKERSENSE_READINESS_OWNED_TREE") != "1"
        environment = dict(os.environ, POKERSENSE_READINESS_OWNED_TREE="1")
        process = subprocess.Popen(
            command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            start_new_session=sys.platform != "win32" and owns_group, env=environment,
        )
        tree = _ProcessTree(process, owns_group=owns_group)
        try:
            remaining = max(0.001, seconds - (time.monotonic() - start))
            code = process.wait(timeout=remaining)
            return {"status": "EXITED", "returncode": code,
                    "elapsed_seconds": time.monotonic() - start, "pid": process.pid}
        except subprocess.TimeoutExpired:
            tree.close()
            process.wait(timeout=5)
            return {"status": "TIMED_OUT_KILLED", "returncode": process.returncode,
                    "elapsed_seconds": time.monotonic() - start, "pid": process.pid}
    finally:
        if tree is not None:
            tree.close()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if log_path:
            log.close()


def _command(*args):
    return [sys.executable, "-m", "tools.aa_policy_readiness_study", *map(str, args)]


@contextmanager
def _exclusive_study(output):
    """Crash-released OS lock prevents concurrent resume/execution of one study."""
    path = Path(output) / ".execution.lock"
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("study_already_running") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("study_already_running") from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def run_phase(output, phase, *, batch_seconds=3600, runner=run_bounded):
    _validate_number(batch_seconds, "batch_seconds", MAX_BATCH_SECONDS)
    with _exclusive_study(output):
        return _run_phase(output, phase, batch_seconds=batch_seconds, runner=runner)


def _run_phase(output, phase, *, batch_seconds=3600, runner=run_bounded):
    """Inner scheduler; the public CLI additionally supervises this entire process."""
    _validate_number(batch_seconds, "batch_seconds", MAX_BATCH_SECONDS)
    if phase not in ("train", "evaluate"):
        raise ValueError("invalid_phase")
    deadline = time.monotonic() + batch_seconds
    output = Path(output)
    manifest, state = load_frozen(output)
    operations = {"train", "control"} if phase == "train" else {"evaluate", "query"}
    gate = gate2(output, manifest) if phase == "evaluate" else None
    for job in manifest["jobs"]:
        if job["operation"] not in operations:
            continue
        row = state["jobs"][job["id"]]
        if row["status"] in TERMINAL_JOB_STATUSES:
            continue
        directory = output / job["id"]
        directory.mkdir(exist_ok=True)
        # A result atomically committed immediately before parent interruption is
        # authoritative; do not repeat the successfully committed operation.
        if _result(output, job["id"], manifest) is not None:
            row["status"] = "COMPLETE"
            _atomic(output / "study-state.json", state)
            continue
        if gate and gate["status"] != "PASS":
            row["status"], row["error"] = "GATE_BLOCKED", "stage2_not_passed"
            continue
        remaining = deadline - time.monotonic() - 2.0
        if remaining <= 0:
            break
        if row["status"] == "RUNNING":
            # Crash/outer-watchdog timing is unknowable: charge the whole reserved
            # slot. Never grant a fresh 60s or duplicate a potentially live worker.
            row["charged_seconds"] += row["attempts"][-1]["reserved_seconds"]
            row["status"] = "EXHAUSTED"
            row["error"] = "unresolved_interrupted_attempt"
            continue
        slot = remaining
        if job["operation"] in ("train", "control"):
            slot = min(slot, job["seconds"] - row["charged_seconds"])
        if slot <= 0:
            row["status"] = "EXHAUSTED"
            continue
        if manifest["identity"] != identity():
            row["status"], row["error"] = "ERROR", "study_source_or_dependency_drift"
            break
        attempt = {"reserved_seconds": slot, "status": "RUNNING"}
        row["status"] = "RUNNING"
        row["attempts"].append(attempt)
        _atomic(output / "study-state.json", state)
        try:
            result = runner(_command("_job", "--output", output, "--job", job["id"],
                                     "--batch-seconds", slot,
                                     "--job-deadline", time.monotonic() + slot),
                            seconds=slot,
                            log_path=directory / f"attempt-{len(row['attempts'])}.log")
            attempt.update(result)
            row["charged_seconds"] += result["elapsed_seconds"]
            if _result(output, job["id"], manifest) is not None:
                row["status"] = "COMPLETE"
            elif result["status"] == "TIMED_OUT_KILLED":
                row["status"] = ("INTERRUPTED"
                                 if job["operation"] in ("evaluate", "query")
                                 else "EXHAUSTED")
            else:
                row["status"], row["error"] = "ERROR", "worker_exited_without_result"
        except KeyboardInterrupt:
            # run_bounded kills its owned process in finally. Conservatively charge
            # reserved time rather than silently enlarging the fitting budget.
            row["charged_seconds"] += slot
            row["status"] = "INTERRUPTED"
            attempt["status"] = "INTERRUPTED"
            _atomic(output / "study-state.json", state)
            break
        _atomic(output / "study-state.json", state)
    _atomic(output / "study-state.json", state)
    report = summarize(output, manifest, state)
    _atomic(output / "study-report.json", report)
    return report


def supervised_phase(output, phase, *, batch_seconds=3600):
    """The outer process bounds identity checks, orchestration and final saving too."""
    _validate_number(batch_seconds, "batch_seconds", MAX_BATCH_SECONDS)
    output = Path(output).resolve()
    result = run_bounded(_command("_phase", "--phase", phase, "--output", output,
                                  "--batch-seconds", batch_seconds),
                         seconds=batch_seconds,
                         log_path=output / f"{phase}-supervisor.log")
    # No study report is overwritten by the outer watchdog. Partial atomic state
    # remains recoverable and incomplete jobs remain in its frozen denominator.
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "train", "evaluate", "report",
                                            "_phase", "_job"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-seconds", type=float, default=3600)
    parser.add_argument("--training-seconds", type=float, default=60)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--phase", choices=("train", "evaluate"))
    parser.add_argument("--job")
    parser.add_argument("--job-deadline", type=float)
    args = parser.parse_args(argv)
    _validate_number(args.batch_seconds, "batch_seconds", MAX_BATCH_SECONDS)
    if args.command == "freeze":
        value = freeze(args.output, training_seconds=args.training_seconds,
                       rules_path=args.rules)
        print(json.dumps({"manifest_sha256": value["sha256"],
                          "expected_cases": value["expected_cases"]}))
    elif args.command in ("train", "evaluate"):
        value = supervised_phase(args.output, args.command,
                                 batch_seconds=args.batch_seconds)
        print(json.dumps(value))
        return 0 if value.get("returncode") == 0 else 2
    elif args.command == "_phase":
        run_phase(args.output, args.phase, batch_seconds=args.batch_seconds)
    elif args.command == "_job":
        manifest, _ = load_frozen(args.output)
        job = next(row for row in manifest["jobs"] if row["id"] == args.job)
        if job["operation"] == "evaluate":
            evaluate_job(args.output, args.job)
        elif job["operation"] == "query":
            if args.job_deadline is None or not math.isfinite(args.job_deadline):
                raise ValueError("query_requires_external_deadline")
            query_job(args.output, args.job, deadline=args.job_deadline)
        else:
            remaining = (args.job_deadline - time.monotonic()
                         if args.job_deadline is not None else args.batch_seconds)
            _validate_number(remaining, "remaining_job_seconds")
            train_job(args.output, args.job, remaining)
    else:
        manifest, state = load_frozen(args.output)
        report = summarize(args.output, manifest, state)
        print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
