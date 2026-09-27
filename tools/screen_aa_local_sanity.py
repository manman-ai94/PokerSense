"""Fixed public-information decision checks, not a poker-strength certificate."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time

from poker_engine.strategy.aa_external_local_policy import (
    ExternalLocalResearchPolicy, select_action,
)
from poker_engine.strategy.aa_frozen_policy import canonical_hash
from poker_engine.strategy.aa_local_sanity import build_sanity_cases
from poker_engine.strategy.aa_policy_encoding_v2 import encode_decision_v2
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
from tools.aa_full_hand_lab import read_json
from tools.aa_policy_readiness_study import run_bounded
from tools import screen_aa_local_policy as screen


LIMITS = {"batch_seconds": 600, "load_seconds": 120, "query_seconds": 10}


def model_query(observation, model):
    """No case label, expected answer, branch results or oracle reach the model."""
    rules = AARuleProfileV2.from_dict(observation["rules"])
    adapter = ExternalLocalResearchPolicy(
        rules, lambda request: None, model_id=model["id"],
        model_revision=model["revision"])
    request = adapter.prepare_request(observation)
    return {"observation": observation, "request": request,
            "request_sha256": canonical_hash(request),
            "exact_key": encode_decision_v2(observation)["exact_key"]}


def initial(manifest):
    return {"manifest_sha256": manifest["sha256"], "started": False,
            "completed": False, "strategy_eligible": False, "advice_emitted": False,
            "scope": "FIXED_SYNTHETIC_PUBLIC_ORACLE_NOT_FULL_STRATEGY",
            "models": [{"id": model["id"], "load": {"status": "NOT_RUN"},
                        "warmup": {"status": "NOT_RUN"},
                        "rows": [{"id": case["id"], "status": "NOT_RUN",
                                  "expected_action": case["expected_action"],
                                  "action": None, "correct": None}
                                 for case in manifest["cases"]]}
                       for model in manifest["models"]]}


def freeze(output, model_08b, model_2b, upstream_package):
    output = Path(output)
    if output.exists():
        raise ValueError("new_output_directory_required")
    cases = build_sanity_cases()
    assert len(cases) == 9
    manifest = {"kind": "AA_LOCAL_PUBLIC_SANITY_V1", "limits": dict(LIMITS),
                "models": [screen._manifest_model(path, spec) for path, spec in
                           zip((model_08b, model_2b), screen.MODEL_SPECS)],
                "upstream": {"directory": str(Path(upstream_package).resolve()),
                             "commit": screen.UPSTREAM_COMMIT,
                             "files": dict(screen.UPSTREAM_FILES)},
                "cases": cases, "expected_rows": 18,
                "warmup": screen.frozen_queries()[0]["observation"],
                "runtime_identity": screen.runtime_identity(),
                "source_sha256": screen._source_hashes(),
                "clock": screen.clock_identity(), "strategy_eligible": False}
    manifest["sha256"] = canonical_hash(manifest)
    output.mkdir(parents=True)
    screen._atomic(output / "manifest.json", manifest)
    screen._atomic(output / "results.json", initial(manifest))
    return manifest


def load(output):
    manifest = read_json(Path(output) / "manifest.json")
    body = {key: value for key, value in manifest.items() if key != "sha256"}
    if (canonical_hash(body) != manifest["sha256"]
            or manifest["kind"] != "AA_LOCAL_PUBLIC_SANITY_V1"
            or manifest["strategy_eligible"] is not False
            or manifest["limits"] != LIMITS or manifest["expected_rows"] != 18
            or manifest["cases"] != build_sanity_cases()
            or manifest["source_sha256"] != screen._source_hashes()
            or manifest["runtime_identity"] != screen.runtime_identity()
            or manifest["clock"] != screen.clock_identity()
            or manifest["warmup"] != screen.frozen_queries()[0]["observation"]
            or manifest["upstream"]["commit"] != screen.UPSTREAM_COMMIT
            or manifest["upstream"]["files"] != screen.UPSTREAM_FILES
            or len(manifest["models"]) != 2):
        raise ValueError("sanity_protocol_or_runtime_mismatch")
    for model, spec in zip(manifest["models"], screen.MODEL_SPECS):
        if any(model.get(key) != val for key, val in spec.items()):
            raise ValueError("sanity_model_mismatch")
    return manifest


def summarize(report, manifest):
    if (report.get("manifest_sha256") != manifest["sha256"]
            or len(report["models"]) != len(manifest["models"])):
        raise ValueError("sanity_report_identity_mismatch")
    for model, spec in zip(report["models"], manifest["models"]):
        if model["id"] != spec["id"] or len(model["rows"]) != 9:
            raise ValueError("sanity_report_denominator_mismatch")
        for row, case in zip(model["rows"], manifest["cases"]):
            if (row["id"] != case["id"]
                    or row["expected_action"] != case["expected_action"]):
                raise ValueError("sanity_report_case_mismatch")
            if row["status"] == "VALID":
                ids = [item["id"] for item in case["observation"]["legal_actions"]]
                elapsed = row["elapsed_ms"]
                if (select_action(row["scores"], ids) != row["action"]
                        or type(elapsed) not in (int, float)
                        or not math.isfinite(elapsed) or elapsed < 0):
                    raise ValueError("sanity_report_response_mismatch")
                correct = row["action"] == case["expected_action"]
                if (row["correct"] is not correct
                        or row["within_300ms"] is not (elapsed <= 300)):
                    raise ValueError("sanity_report_claim_mismatch")
            elif row["correct"] is not None or row["action"] is not None:
                raise ValueError("sanity_failed_row_cannot_claim_an_action")
        correct = sum(row["correct"] is True for row in model["rows"])
        incorrect = sum(row["correct"] is False for row in model["rows"])
        model["summary"] = {"planned": 9, "correct": correct,
                            "incorrect": incorrect,
                            "unresolved": 9 - correct - incorrect,
                            "verdict": "PASS_BASIC_CHECKS_ONLY" if correct == 9 else
                            "FAIL_BASIC_CHECKS" if incorrect else "INCOMPLETE"}
    report["expected_rows"] = 18
    report["strength"] = "NOT_ASSESSED"


def run(output, *, client_factory=screen.WorkerClient,
        verify_assets=screen.verify_assets, ready_validator=screen.validate_ready):
    output = Path(output)
    started = time.perf_counter()
    deadline = started + 585
    # Reuse the OS lock, without sharing any ledger with the full-hand study.
    from tools.aa_policy_readiness_study import _exclusive_study
    with _exclusive_study(output):
        manifest = load(output)
        report = read_json(output / "results.json")
        if report != initial(manifest):
            raise ValueError("sanity_already_started")
        report["started"] = True

        def save():
            report["elapsed_seconds"] = time.perf_counter() - started
            summarize(report, manifest)
            screen._atomic(output / "results.json", report)

        save()
        for model, result in zip(manifest["models"], report["models"]):
            client = None
            active_row = None
            try:
                if time.perf_counter() >= deadline:
                    result["load"] = {"status": "NOT_RUN_BATCH_DEADLINE"}
                    continue
                verify_assets(model, manifest["upstream"])
                load_start = time.perf_counter()
                client = client_factory(model, manifest["upstream"],
                                        runtime=manifest["runtime_identity"])
                ready = client.receive(min(120, deadline - time.perf_counter()))
                ready["elapsed_ms"] = (time.perf_counter() - load_start) * 1000
                result["load"] = ready
                save()
                if ready["status"] != "READY":
                    continue
                ready_validator(ready, model, manifest["upstream"],
                                manifest["runtime_identity"])
                result["warmup"] = client.query(
                    model_query(manifest["warmup"], model),
                    min(10, deadline - time.perf_counter()))
                save()
                if result["warmup"]["status"] == "TIMEOUT":
                    continue
                for case, row in zip(manifest["cases"], result["rows"]):
                    if time.perf_counter() >= deadline:
                        break
                    row["status"] = "RUNNING"
                    active_row = row
                    save()
                    query = model_query(case["observation"], model)
                    response = client.query(
                        query, min(10, deadline - time.perf_counter()))
                    row.update(response)
                    if response["status"] == "VALID":
                        ids = [item["id"] for item in query["request"]["options"]]
                        if response["action"] != select_action(response["scores"], ids):
                            raise ValueError("sanity_worker_action_score_mismatch")
                        row["correct"] = response["action"] == case["expected_action"]
                        row["within_300ms"] = response["elapsed_ms"] <= 300
                    save()
                    active_row = None
                    if response["status"] == "TIMEOUT":
                        break
            except Exception as exc:
                result["error"] = screen._error(exc)
                if active_row is not None:
                    active_row.update(status="ERROR", correct=None,
                                      reason=str(exc),
                                      rejected_action=active_row["action"])
                    active_row["action"] = None
            finally:
                if client is not None:
                    client.close()
                save()
        report["completed"] = True
        save()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "_run", "report"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-08b", type=Path)
    parser.add_argument("--model-2b", type=Path)
    parser.add_argument("--upstream-package", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        if None in (args.model_08b, args.model_2b, args.upstream_package):
            parser.error("freeze requires fixed model and upstream paths")
        manifest = freeze(args.output, args.model_08b, args.model_2b,
                          args.upstream_package)
        print(json.dumps({"manifest_sha256": manifest["sha256"], "planned": 18}))
    elif args.phase == "run":
        start = time.perf_counter()
        result = run_bounded([sys.executable, "-m", "tools.screen_aa_local_sanity",
                              "_run", "--output", str(args.output.resolve())],
                             seconds=590, cwd=screen.ROOT,
                             log_path=args.output / "screen.log")
        result["supervisor_perf_counter_seconds"] = time.perf_counter() - start
        result["helper_elapsed_clock"] = "monotonic_in_reused_run_bounded"
        result["supervisor_clock"] = screen.clock_identity()
        screen._atomic(args.output / "supervisor.json", result)
        print(json.dumps(result))
    elif args.phase == "_run":
        run(args.output)
    else:
        manifest = load(args.output)
        report = read_json(args.output / "results.json")
        summarize(report, manifest)
        print(json.dumps(report))


if __name__ == "__main__":
    main()
