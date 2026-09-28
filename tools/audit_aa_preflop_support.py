"""Frozen audit of existing V2 assets on finite preflop support; no fitting.

freeze --source-study OLD --output NEW; run --output NEW; report --output NEW.
One supervised batch (600s including validation and persistence), no retries.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

from poker_engine.strategy.aa_frozen_policy import canonical_hash
from poker_engine.strategy.aa_frozen_policy_v2 import FrozenResearchPolicyV2
from poker_engine.strategy.aa_mccfr import ExternalSamplingMCCFR
from poker_engine.strategy.aa_policy_encoding_v2 import (
    ENCODER_VERSION_V2, information_key_v2,
)
from poker_engine.strategy.aa_preflop_support import (
    SCENARIOS, WORLD_SEEDS, holding_classes, paired_query, support_specs,
)
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
from tools.aa_full_hand_lab import DEFAULT_RULES, read_json, rules_for, write_new
from tools.aa_policy_readiness_study import (
    ROOT, _atomic, _bound_document, _check_document, identity, run_bounded,
)


TRAINING_SEEDS = (1103, 2207, 3301)
BATCH_SECONDS = 600
QUERY_STATUSES = {"READY", "NOT_APPLICABLE", "CONSTRUCTION_ERROR"}
LOOKUP_STATUSES = {"HIT", "UNVISITED", "REGRET_TABLE_ONLY_ZERO",
                   "REGRET_ONLY_NONZERO", "AVERAGE_ZERO_MASS",
                   "NOT_APPLICABLE", "CONSTRUCTION_ERROR", "ASSET_OR_LOOKUP_ERROR"}


def digest(path):
    with Path(path).open("rb") as stream:
        return sha256(stream.read()).hexdigest()


def protocol():
    return {
        "kind": "AA_PREFLOP_SUPPORT_AUDIT_V1", "encoder": ENCODER_VERSION_V2,
        "players": [6, 7, 8], "training_seeds": list(TRAINING_SEEDS),
        "scenarios": list(SCENARIOS), "classes": holding_classes(),
        "world_seeds": list(WORLD_SEEDS), "depth_bb": "100",
        "geometry": "occupied=range(n); dealer=n-1; physical seats retained",
        "planned_support_slots": 10647, "planned_asset_rows": 31941,
        "expected_not_applicable_slots": 1014,
        "expected_not_applicable_asset_rows": 3042,
        "max_batches": 1, "batch_seconds": BATCH_SECONDS,
        "query_work_seconds": 450, "external_worker_seconds": 590,
        "scope": "DEVELOPMENT_SUPPORT_GRID_NOT_FULL_HAND_OR_STRENGTH",
        "weighting": "unweighted class/prefix slots; not natural-deal frequency",
        "no_fitting": True, "no_fallback": True, "no_live_promotion": True,
    }


def _case_id(n, seed):
    return f"v2-n{n}-seed{seed}"


def _shards():
    return [{"id": f"n{n}-h{hero}-{scenario}", "players": n,
             "hero": hero, "scenario": scenario, "expected_rows": 507}
            for n in (6, 7, 8) for hero in range(n) for scenario in SCENARIOS]


def source_assets(source, old):
    if old["protocol"]["kind"] != "AA_POLICY_READINESS_V2":
        raise ValueError("readiness_study_required")
    for n in (6, 7, 8):
        if old["rules"][str(n)] != rules_for(DEFAULT_RULES, n).to_dict():
            raise ValueError("support_requires_frozen_simulation_rules")
    assets = []
    actual_ids = [c["id"] for c in old["cases"] if c["version"] == "V2"]
    if sorted(actual_ids) != sorted(_case_id(n, seed) for n in (6, 7, 8)
                                    for seed in TRAINING_SEEDS):
        raise ValueError("source_v2_matrix_mismatch")
    for n in (6, 7, 8):
        for seed in TRAINING_SEEDS:
            name = _case_id(n, seed)
            case = next(row for row in old["cases"] if row["id"] == name)
            if (case["players"] != n or case["training_seed"] != seed
                    or case["version"] != "V2"):
                raise ValueError("source_case_mismatch")
            directory = source / (name + "-train")
            files = {key: {"path": str(directory / filename),
                           "sha256": digest(directory / filename)}
                     for key, filename in (("checkpoint", "latest-checkpoint.json"),
                                           ("policy", "policy.json"),
                                           ("result", "result.json"))}
            assets.append({"id": name, "players": n, "seed": seed,
                           "case": case, "files": files})
    return assets


def freeze(source_study, output):
    source, output = Path(source_study).resolve(), Path(output).resolve()
    if output == source or source in output.parents:
        raise ValueError("source_study_must_remain_read_only")
    if output.exists():
        raise ValueError("new_audit_directory_required")
    old = _check_document(read_json(source / "frozen-manifest.json"))
    assets = source_assets(source, old)
    manifest = _bound_document({
        "protocol": protocol(), "identity": identity(), "assets": assets,
        "source_manifest_sha256": old["sha256"],
        "source_manifest_file": {"path": str(source / "frozen-manifest.json"),
                                 "sha256": digest(source / "frozen-manifest.json")},
        "rules": old["rules"], "shards": _shards(),
        "strategy_eligible": False, "advice_emitted": False,
    })
    output.mkdir(parents=True)
    (output / "shards").mkdir()
    (output / "attempts").mkdir()
    write_new(output / "manifest.json", manifest)
    write_report(output, manifest)
    return manifest


def load(output):
    manifest = _check_document(read_json(Path(output) / "manifest.json"))
    if (manifest["protocol"] != protocol() or manifest["shards"] != _shards()
            or manifest["identity"] != identity()
            or manifest["strategy_eligible"] is not False
            or manifest["advice_emitted"] is not False):
        raise ValueError("audit_protocol_or_runtime_drift")
    expected = [_case_id(n, seed) for n in (6, 7, 8) for seed in TRAINING_SEEDS]
    if [a["id"] for a in manifest["assets"]] != expected:
        raise ValueError("audit_asset_matrix_changed")
    for item in [manifest["source_manifest_file"], *[
            file for asset in manifest["assets"] for file in asset["files"].values()]]:
        if digest(item["path"]) != item["sha256"]:
            raise ValueError("frozen_input_file_changed")
    path = Path(manifest["source_manifest_file"]["path"])
    old = _check_document(read_json(path))
    if (manifest["source_manifest_sha256"] != old["sha256"]
            or manifest["rules"] != old["rules"]
            or manifest["assets"] != source_assets(path.parent, old)):
        raise ValueError("source_metadata_rebinding_rejected")
    return manifest


def load_asset(asset, manifest):
    docs = {key: read_json(row["path"]) for key, row in asset["files"].items()}
    cp, result, document = docs["checkpoint"], docs["result"], docs["policy"]
    _check_document(cp)
    _check_document(result)
    rules = AARuleProfileV2.from_dict(manifest["rules"][str(asset["players"])])
    binding = {"case": asset["case"], "job_id": asset["id"] + "-train",
               "manifest_sha256": manifest["source_manifest_sha256"],
               "operation": "train", "rules": rules.to_dict(),
               "rules_fingerprint": rules.fingerprint, "stack_depth_bb": "100"}
    if (cp["binding"] != binding or result["binding"] != binding
            or result["checkpoint_file_sha256"]
            != asset["files"]["checkpoint"]["sha256"]
            or result["policy_file_sha256"] != asset["files"]["policy"]["sha256"]):
        raise ValueError("original_receipt_binding_mismatch")
    trainer = ExternalSamplingMCCFR.restore(
        cp["trainer"], expected_binding=binding, expected_encoder=ENCODER_VERSION_V2,
        encoder=information_key_v2)
    policy = FrozenResearchPolicyV2(document)
    if (trainer.seed != asset["seed"]
            or trainer.players != tuple(range(asset["players"]))
            or trainer.update_regrets is not True
            or document["training"]["checkpoint_sha256"] != cp["trainer"]["sha256"]
            or result["policy_sha256"] != policy.sha256
            or policy.frozen_map() != trainer.average_policy()):
        raise ValueError("original_average_export_mismatch")
    return {"policy": policy, "checkpoint": cp["trainer"], "rules": rules,
            "policy_sha256": policy.sha256}


def inspect(asset_id, query, loaded):
    if query["status"] != "READY":
        return {"asset_id": asset_id, "status": query["status"],
                "reason": query["reason"]}
    policy, cp = loaded["policy"], loaded["checkpoint"]
    result = policy.inspect_lookup(query["observation"])
    key = query["abstract_key"]
    if (result.get("information_key") != key
            or result["status"] not in ("HIT", "UNKNOWN_INFORMATION_SET")):
        raise ValueError("real_policy_lookup_validation_failed:" + str(result))
    # Exercise the deployed lookup method, not just table membership.
    if policy.distribution(query["observation"]) != result["distribution"]:
        raise ValueError("lookup_distribution_disagreement")
    regrets, average = cp["regrets"].get(key), cp["average"].get(key)
    nonzero = regrets is not None and any(value != 0 for value in regrets.values())
    mass = sum(average[a] for a in sorted(average)) if average else 0
    if result["status"] == "HIT":
        status = "HIT"
        if mass <= 0:
            raise ValueError("export_without_positive_average")
    elif average is not None:
        if mass > 0:
            raise ValueError("positive_average_missing_from_export")
        status = "AVERAGE_ZERO_MASS"
    elif regrets is None:
        status = "UNVISITED"
    else:
        status = "REGRET_ONLY_NONZERO" if nonzero else "REGRET_TABLE_ONLY_ZERO"
    dist = result["distribution"]
    return {"asset_id": asset_id, "status": status, "reason": result.get("reason"),
            "visits": cp.get("committed_visits", {}).get(key, 0),
            "regret_present": regrets is not None, "regret_nonzero": nonzero,
            "average_present": average is not None, "average_mass": mass,
            "distribution": dist,
            "export_nonuniform": (any(abs(p - 1 / len(dist)) > 1e-8
                                      for p in dist.values()) if dist else None),
            "historical_traverser_roles": "NOT_RECORDED_UNKNOWN"}


def _run(output):
    started = time.perf_counter()
    output = Path(output)
    if read_json(output / "batch.json") != {"seconds": BATCH_SECONDS, "max_batches": 1}:
        raise ValueError("supervised_audit_reservation_required")
    write_new(output / "inner-started.json", {"one_attempt": True})
    manifest = load(output)
    deadline = started + protocol()["query_work_seconds"]
    loaded, failures = {}, {}
    for asset in manifest["assets"]:
        if time.perf_counter() >= deadline:
            break
        try:
            loaded[asset["id"]] = load_asset(asset, manifest)
        except Exception as exc:
            failures[asset["id"]] = f"{type(exc).__name__}: {exc}"
    _atomic(output / "asset-validation.json", {
        "manifest_sha256": manifest["sha256"], "loaded": list(loaded),
        "failed": failures})
    for shard in manifest["shards"]:
        if time.perf_counter() >= deadline:
            break
        write_new(output / "attempts" / (shard["id"] + ".json"), {
            "manifest_sha256": manifest["sha256"], "shard": shard})
        specs = [row for row in support_specs(shard["players"])
                 if row["hero"] == shard["hero"]
                 and row["scenario"] == shard["scenario"]]
        assets = [a for a in manifest["assets"] if a["players"] == shard["players"]]
        rules = AARuleProfileV2.from_dict(manifest["rules"][str(shard["players"])])
        journal = output / "attempts" / (shard["id"] + ".jsonl")
        with journal.open("x", encoding="utf-8") as stream:
            for spec in specs:
                if time.perf_counter() >= deadline:
                    break
                try:
                    query = paired_query(rules, spec)
                except Exception as exc:
                    query = {"status": "CONSTRUCTION_ERROR", "reason": str(exc),
                             "observation": None, "exact_key": None,
                             "abstract_key": None}
                checks = []
                for asset in assets:
                    name = asset["id"]
                    try:
                        if name not in loaded:
                            raise ValueError(failures.get(
                                name, "asset_loading_not_run"))
                        checks.append(inspect(name, query, loaded[name]))
                    except Exception as exc:
                        checks.append({"asset_id": name,
                                       "status": "ASSET_OR_LOOKUP_ERROR",
                                       "reason": str(exc)})
                record = {"spec": spec, "query": query, "checks": checks}
                stream.write(json.dumps(record,
                                        sort_keys=True, allow_nan=False) + "\n")
                stream.flush()
            else:
                stream.flush()
                write_new(output / "shards" / (shard["id"] + ".json"), {
                    "manifest_sha256": manifest["sha256"], "shard": shard,
                    "journal_sha256": digest(journal)})
    load(output)  # Recheck original bytes and implementation after all queries.
    report = write_report(output, manifest)
    _atomic(output / "inner-result.json", {
        "elapsed_seconds_including_report": time.perf_counter() - started})
    return report


def write_report(output, manifest=None):
    output = Path(output)
    manifest = manifest or load(output)
    rows, distinct, exact, slot_counts = {}, {}, {}, Counter()
    checked_assets = {}
    if any((output / "shards" / (s["id"] + ".json")).exists()
           for s in manifest["shards"]):
        for asset in manifest["assets"]:
            try:
                checked_assets[asset["id"]] = load_asset(asset, manifest)
            except Exception:
                # Failed assets may only support explicit failure rows below.
                checked_assets[asset["id"]] = None
    for asset in manifest["assets"]:
        rows[asset["id"]] = {"counts": Counter(), "by_scenario": {}, "examples": {},
                             "export_nonuniform_hits": 0}
        distinct[asset["id"]] = {}
        exact[asset["id"]] = {}
    for shard in manifest["shards"]:
        commit = output / "shards" / (shard["id"] + ".json")
        assets = [a["id"] for a in manifest["assets"]
                  if a["players"] == shard["players"]]
        specs = [s for s in support_specs(shard["players"])
                 if s["hero"] == shard["hero"]
                 and s["scenario"] == shard["scenario"]]
        if not commit.exists():
            attempt = output / "attempts" / (shard["id"] + ".json")
            status = "INTERRUPTED" if attempt.exists() else "NOT_RUN"
            slot_counts[status] += len(specs)
            records = [{"spec": spec, "query": {}, "checks": [
                {"asset_id": name, "status": status} for name in assets]}
                for spec in specs]
        else:
            receipt = read_json(commit)
            journal = output / "attempts" / (shard["id"] + ".jsonl")
            if (receipt["manifest_sha256"] != manifest["sha256"]
                    or receipt["shard"] != shard
                    or receipt["journal_sha256"] != digest(journal)):
                raise ValueError("support_shard_receipt_mismatch")
            records = [json.loads(line) for line in
                       journal.read_text(encoding="utf-8").splitlines()]
            if [r["spec"] for r in records] != specs:
                raise ValueError("support_shard_denominator_mismatch")
            for record in records:
                validate_record(record, manifest, checked_assets)
            slot_counts.update(record["query"]["status"] for record in records)
        for record in records:
            if [r["asset_id"] for r in record["checks"]] != assets:
                raise ValueError("support_asset_row_identity_mismatch")
            for check in record["checks"]:
                name, status = check["asset_id"], check["status"]
                entry = rows[name]
                entry["counts"][status] += 1
                counts = entry["by_scenario"].setdefault(shard["scenario"], Counter())
                counts[status] += 1
                if status == "HIT" and check.get("export_nonuniform") is True:
                    entry["export_nonuniform_hits"] += 1
                if status not in entry["examples"]:
                    entry["examples"][status] = {
                        "spec": record["spec"], **check,
                        "key": record["query"].get("abstract_key")}
                key = record["query"].get("abstract_key")
                if key:
                    if key in distinct[name] and distinct[name][key] != status:
                        raise ValueError("duplicate_key_inconsistent_lookup")
                    distinct[name][key] = status
                    exact[name][record["query"]["exact_key"]] = key
    for asset in manifest["assets"]:
        entry = rows[asset["id"]]
        expected = asset["players"] * len(SCENARIOS) * 169
        assert sum(entry["counts"].values()) == expected
        entry.update(planned=expected,
                     unique_abstract_counts=Counter(distinct[asset["id"]].values()))
        hit = entry["counts"]["HIT"]
        applicable = expected - 338
        entry.update(planned_constructible=applicable,
                     hit_fraction_of_planned=hit / expected,
                     hit_fraction_of_constructible=hit / applicable,
                     unique_exact_keys=len(exact[asset["id"]]),
                     unique_abstract_keys=len(distinct[asset["id"]]),
                     distinct_exact_per_abstract=dict(Counter(
                         Counter(exact[asset["id"]].values()).values())))
        entry["support_status"] = ("COMPLETE_LOOKUP_NOT_STRENGTH"
                                   if hit == applicable else "INCOMPLETE_SUPPORT")
    report = {"manifest_sha256": manifest["sha256"], "scope": protocol()["scope"],
              "planned_asset_rows": 31941, "planned_support_slots": 10647,
              "support_status_counts": slot_counts, "cases": rows,
              "overall_counts": sum((e["counts"] for e in rows.values()), Counter()),
              "strategy_eligible": False, "advice_emitted": False,
              "ev": None, "strength": "NOT_ASSESSED", "training_updates": 0}
    report["execution_complete"] = not any(
        report["overall_counts"].get(status, 0) for status in
        ("NOT_RUN", "INTERRUPTED", "ASSET_OR_LOOKUP_ERROR", "CONSTRUCTION_ERROR"))
    report["construction_contract_matches"] = (
        slot_counts["NOT_APPLICABLE"] == 1014
        and slot_counts["READY"] == 9633
        and sum(slot_counts.values()) == 10647)
    _atomic(output / "report.json", report)
    return report


def validate_record(record, manifest, assets):
    """Recheck old deterministic slots; a self-signed HIT is not evidence."""
    query, spec = record["query"], record["spec"]
    if (query.get("status") not in QUERY_STATUSES
            or any(c.get("status") not in LOOKUP_STATUSES for c in record["checks"])):
        raise ValueError("unknown_support_record_status")
    if query["status"] == "CONSTRUCTION_ERROR":
        if (not isinstance(query.get("reason"), str) or not query["reason"]
                or any(query.get(key) is not None
                       for key in ("observation", "exact_key", "abstract_key"))):
            raise ValueError("invalid_construction_failure_record")
    else:
        rules = AARuleProfileV2.from_dict(manifest["rules"][str(spec["players"])])
        if canonical_hash(query) != canonical_hash(paired_query(rules, spec)):
            raise ValueError("recorded_query_not_frozen_support_point")
    for check in record["checks"]:
        if check["status"] == "ASSET_OR_LOOKUP_ERROR":
            if (set(check) != {"asset_id", "status", "reason"}
                    or not isinstance(check.get("reason"), str) or not check["reason"]):
                raise ValueError("invalid_asset_failure_record")
            continue  # Never upgrade a recorded failure by rechecking it.
        loaded = assets[check["asset_id"]]
        if loaded is None:
            raise ValueError("successful_record_from_unverified_asset")
        expected = inspect(check["asset_id"], query, loaded)
        if canonical_hash(check) != canonical_hash(expected):
            raise ValueError("recorded_lookup_not_original_average_policy")


def run(output):
    output = Path(output).resolve()
    started = time.perf_counter()
    # Exclusive creation both reserves the sole budget and rejects concurrent runs.
    write_new(output / "batch.json", {"seconds": BATCH_SECONDS, "max_batches": 1})
    result = run_bounded(
        [sys.executable, "-m", "tools.audit_aa_preflop_support", "_run",
         "--output", str(output)],
        seconds=protocol()["external_worker_seconds"], cwd=ROOT,
        log_path=output / "supervisor.log")
    _atomic(output / "supervisor.json", {
        "result": result, "elapsed_seconds": time.perf_counter() - started})
    if result["status"] != "EXITED" or result["returncode"] != 0:
        raise RuntimeError("audit_batch_failed_preserve_journals_then_run_report")
    return read_json(output / "report.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run", "_run", "report"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-study", type=Path)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        if args.source_study is None:
            parser.error("freeze requires --source-study")
        result = freeze(args.source_study, args.output)
        print(result["sha256"])
    else:
        operation = {"run": run, "_run": _run, "report": write_report}[args.command]
        result = operation(args.output)
        print(json.dumps(result["overall_counts"], sort_keys=True))


if __name__ == "__main__":
    main()
