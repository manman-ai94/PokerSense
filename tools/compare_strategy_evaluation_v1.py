"""Pair future offline candidate reports with the immutable BASELINE V1 cases.

This comparator does not create or optimize a candidate policy. A positive
synthetic delta is a diagnostic, never empirical acceptance or live advice.
"""

import argparse
from fractions import Fraction
import json

from tools.strategy_evaluation_v1 import (
    DEFAULT_INPUT, DEFAULT_PROTOCOL, DEFAULT_RESULTS, _case, action_data,
    book_from_data, digest, load_frozen_baseline, planning_scenarios,
    public_candidates, read_json, stable_json, world_scenario, write_json,
)

FROZEN_RESULT_SHA256 = (
    "720d6cbe6914a2b3aa4daae18a9d6a2e36d7defa40c12f14ebce5f9eaff9223a")
COMPLETE = "COMPLETE_CONDITIONAL_FIXED_POLICY"


def _hash(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _stable(report):
    if not isinstance(report, dict):
        raise ValueError("evaluation_report_required")
    stable = {key: value for key, value in report.items()
              if key not in ("runtime", "deterministic_sha256")}
    if report.get("deterministic_sha256") != digest(
            stable_json(stable).encode()):
        raise ValueError("evaluation_report_digest_mismatch")
    if (stable.get("schema_version") != 1
            or stable.get("scope") != "SYNTHETIC_CONDITIONAL_RIVER_POLICY_EVALUATION"
            or stable.get("strategy_eligible") is not False
            or stable.get("advice_emitted") is not False
            or stable.get("real_hand_acceptance_pending") is not True):
        raise ValueError("evaluation_report_scope_or_safety_mismatch")
    cases = stable.get("cases")
    if (not isinstance(cases, list)
            or not all(isinstance(row, dict)
                       and isinstance(row.get("case_id"), str) for row in cases)
            or type(stable.get("case_count")) is not int
            or len(cases) != stable["case_count"]
            or len({row["case_id"] for row in cases}) != len(cases)):
        raise ValueError("evaluation_cases_missing_or_duplicate")
    for row in cases:
        if (row.get("status") not in (COMPLETE, "BLOCKED")
                or not _hash(row.get("policy_book_sha256"))
                or not _hash(row.get("declared_world_sha256"))):
            raise ValueError("invalid_case_status_or_identity:" + row["case_id"])
    complete = sum(row["status"] == COMPLETE for row in cases)
    if (type(stable.get("complete_count")) is not int
            or type(stable.get("blocked_count")) is not int
            or stable["complete_count"] != complete
            or stable["blocked_count"] != len(cases) - complete):
        raise ValueError("evaluation_case_counts_mismatch")
    return stable, {row["case_id"]: row for row in cases}


def _blocked_case(row, book, plan):
    """Failures remain in the denominator but may not retain partial EV."""
    allowed = {
        "case_id", "status", "reasons", "joint_range_product",
        "legal_joint_assignments", "nodes", "declared_world_sha256",
        "world_scenario_sha256", "policy_book_sha256",
        "model_knowledge_regret_chips", "model_knowledge_regret_scope",
        "world_model_best_action", "frozen_root_action",
    }
    if (set(row) != allowed
            or row["legal_joint_assignments"] is not None
            or row["world_scenario_sha256"] is not None
            or row["model_knowledge_regret_chips"] is not None
            or row["world_model_best_action"] is not None
            or type(row["nodes"]) is not int or row["nodes"] < 0
            or not isinstance(row["reasons"], list) or not row["reasons"]
            or not all(isinstance(reason, str) and reason
                       for reason in row["reasons"])):
        raise ValueError("blocked_case_claims_partial_or_invalid_result:"
                         + row["case_id"])
    root = next((item.action for item in book.decisions
                 if item.history == plan.history), None)
    if root is None or row["frozen_root_action"] != action_data(root):
        raise ValueError("blocked_case_policy_identity_mismatch:" + row["case_id"])


def compare_reports(baseline, candidate, candidate_books=None):
    """Replay claimed results; a self-resealed report is not result authority.

    ``candidate_books`` is a complete group -> serialized PolicyBook mapping.
    Changed books must be supplied, held fixed across every world in a group,
    and evaluated locally with the frozen V1 kernel. This accepts candidate
    actions, not candidate evaluator implementations or world-specific oracles.
    """
    frozen = load_frozen_baseline()
    base_body, base_cases = _stable(baseline)
    candidate_body, candidate_cases = _stable(candidate)
    if (base_body.get("baseline_id") != "BASELINE_V1"
            or baseline["deterministic_sha256"] != FROZEN_RESULT_SHA256):
        raise ValueError("frozen_baseline_report_required")
    if set(base_cases) != set(candidate_cases):
        raise ValueError("unpaired_case_ids")
    for key in ("base_commit", "baseline_file_sha256"):
        if candidate_body.get(key) != base_body.get(key):
            raise ValueError("candidate_evaluation_identity_mismatch:" + key)
    plans, protocol, input_hash, protocol_hash = planning_scenarios(
        DEFAULT_INPUT, DEFAULT_PROTOCOL)
    if (input_hash != frozen["input_sha256"]
            or protocol_hash != frozen["protocol_sha256"]):
        raise ValueError("frozen_evaluation_input_or_protocol_drift")
    if candidate_books is not None and (
            not isinstance(candidate_books, dict)
            or set(candidate_books) != set(frozen["books"])):
        raise ValueError("complete_candidate_books_required")
    books = {group: book_from_data(data) for group, data in (
        frozen["books"] if candidate_books is None else candidate_books).items()}
    # Derive groups from the pinned baseline, never from a candidate's labels.
    group_by_hash = {book["book_sha256"]: group
                     for group, book in frozen["books"].items()}
    candidate_hashes = {group: set() for group in books}
    for case_id, base in base_cases.items():
        group = group_by_hash[base["policy_book_sha256"]]
        candidate_hashes[group].add(candidate_cases[case_id]["policy_book_sha256"])
    for group, hashes in candidate_hashes.items():
        if len(hashes) != 1:
            raise ValueError("candidate_policy_changed_between_worlds:" + group)
        if hashes != {books[group].book_sha256}:
            raise ValueError("candidate_book_payload_required_or_mismatched:" + group)
    calling = next(item for item in public_candidates((1, 2))
                   if item.candidate_id == "calling_public_v1")
    rows = []
    for case_id, base in base_cases.items():
        proposed = candidate_cases[case_id]
        group = group_by_hash[base["policy_book_sha256"]]
        book = books[group]
        for key in ("declared_world_sha256", "joint_range_product"):
            if proposed.get(key) != base.get(key):
                raise ValueError("changed_evaluation_world:" + case_id)
        if base["status"] != COMPLETE:
            raise ValueError("baseline_case_not_complete:" + case_id)
        if proposed["status"] == "BLOCKED":
            _blocked_case(proposed, book, plans[group])
            rows.append({"case_id": case_id, "status": "CANDIDATE_BLOCKED",
                         "reasons": proposed.get("reasons", [])})
            continue
        for key in ("world_scenario_sha256", "legal_joint_assignments"):
            if proposed.get(key) != base.get(key):
                raise ValueError("changed_evaluation_world:" + case_id)
        if base["policy_book_sha256"] == book.book_sha256:
            verified = base
        else:
            world_name = case_id.removeprefix(group + "/")
            if world_name not in protocol["worlds"]:
                raise ValueError("unknown_frozen_world:" + case_id)
            world, overrides = world_scenario(plans[group], world_name, calling)
            verified = _case(group, world_name, book, world, overrides,
                             frozen["max_nodes"])
            verified.pop("elapsed_ms")
        # Includes controls, history denominator, chip/bb algebra, fallback,
        # nodes and diagnostics. Comparing only the policy EV hides drift.
        if proposed != verified:
            raise ValueError("candidate_case_replay_mismatch:" + case_id)
        before = Fraction(base["metrics"]["frozen_policy"]["net_ev_chips"])
        after = Fraction(verified["metrics"]["frozen_policy"]["net_ev_chips"])
        rows.append({"case_id": case_id, "status": "PAIRED",
                     "baseline_ev_chips": str(before),
                     "candidate_ev_chips": str(after),
                     "delta_chips": str(after - before),
                     "candidate_fallback_probability": proposed[
                         "metrics"]["frozen_policy"]["fallback_probability"]})
    paired = [row for row in rows if row["status"] == "PAIRED"]
    deltas = [Fraction(row["delta_chips"]) for row in paired]
    same_books = all(base_cases[key]["policy_book_sha256"]
                     == candidate_cases[key]["policy_book_sha256"]
                     for key in base_cases if candidate_cases[key]["status"]
                     == COMPLETE)
    status = ("INCOMPLETE" if len(paired) != len(base_cases)
              else "SELF_CONTROL" if same_books
              else "COMPARABLE_SYNTHETIC")
    return {
        "schema_version": 1, "status": status,
        "baseline_report_sha256": baseline["deterministic_sha256"],
        "candidate_report_sha256": candidate["deterministic_sha256"],
        "case_count": len(rows), "paired_count": len(paired),
        "candidate_blocked_count": len(rows) - len(paired),
        "positive_delta_count": sum(value > 0 for value in deltas),
        "negative_delta_count": sum(value < 0 for value in deltas),
        "equal_delta_count": sum(value == 0 for value in deltas),
        "cases": rows,
        "qualification": (
            "paired_declared_synthetic_worlds_only",
            "candidate_books_fixed_across_worlds_and_results_replayed",
            "candidate_compile_provenance_and_holdout_independence_not_established",
            "world_model_assumptions_are_not_real_opponent_truth",
            "no_empirical_promotion_or_profitability_or_GTO_claim",
        ),
        "strategy_eligible": False, "advice_emitted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=DEFAULT_RESULTS)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--candidate-books", help=(
        "JSON group-to-book mapping required for any changed policy; "
        "complete results are replayed using the frozen evaluator"))
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        report = compare_reports(read_json(args.baseline),
                                 read_json(args.candidate),
                                 read_json(args.candidate_books)
                                 if args.candidate_books else None)
        if args.output:
            write_json(args.output, report)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"strategy comparison rejected: {exc}\n")
    print(json.dumps({key: report[key] for key in (
        "status", "case_count", "paired_count", "candidate_blocked_count",
        "positive_delta_count", "negative_delta_count")}, indent=2))


if __name__ == "__main__":
    main()
