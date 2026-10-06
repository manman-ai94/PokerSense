"""Frozen I/O, true V2 lookups, diagnostics and interrupted denominator tests."""
from copy import deepcopy
import json

import pytest

from poker_engine.strategy.aa_frozen_policy_v2 import make_policy_v2
from poker_engine.strategy.aa_mccfr import ExternalSamplingMCCFR
from poker_engine.strategy.aa_policy_encoding_v2 import ENCODER_VERSION_V2
from poker_engine.strategy.aa_preflop_support import paired_query, support_specs
from tools import audit_aa_preflop_support as audit
from tools.aa_full_hand_lab import DEFAULT_RULES, rules_for, write_new
from tools.aa_policy_readiness_study import _bound_document


@pytest.fixture
def old_study(tmp_path):
    """Synthetic asset controls; never labelled as learned candidates."""
    source = tmp_path / "old"
    source.mkdir()
    cases = [{"id": f"v2-n{n}-seed{seed}", "players": n, "training_seed": seed,
              "version": "V2"} for n in (6, 7, 8) for seed in audit.TRAINING_SEEDS]
    rules = {str(n): rules_for(DEFAULT_RULES, n).to_dict() for n in (6, 7, 8)}
    manifest = _bound_document({"protocol": {"kind": "AA_POLICY_READINESS_V2"},
                                "cases": cases, "rules": rules})
    write_new(source / "frozen-manifest.json", manifest)
    for case in cases:
        n, name = case["players"], case["id"]
        rule = rules_for(DEFAULT_RULES, n)
        binding = {"case": case, "job_id": name + "-train",
                   "manifest_sha256": manifest["sha256"], "operation": "train",
                   "rules": rule.to_dict(), "rules_fingerprint": rule.fingerprint,
                   "stack_depth_bb": "100"}
        trainer = ExternalSamplingMCCFR(
            range(n), seed=case["training_seed"], binding=binding,
            encoder_id=ENCODER_VERSION_V2)
        query = paired_query(rule, support_specs(n)[0])
        key = query["abstract_key"]
        actions = [a["id"] for a in query["observation"]["legal_actions"]]
        trainer.regrets[key] = dict.fromkeys(actions, 0.0)
        trainer.average[key] = dict.fromkeys(actions, 1.0)
        trainer.visits[key] = 1
        cp = _bound_document({"binding": binding, "trainer": trainer.checkpoint()})
        policy = trainer.export(rules_fingerprint=rule.fingerprint, table_size=n,
                                stack_depth_bb="100", policy_factory=make_policy_v2)
        directory = source / (name + "-train")
        directory.mkdir()
        write_new(directory / "latest-checkpoint.json", cp)
        write_new(directory / "policy.json", policy)
        result = _bound_document({
            "binding": binding, "policy_sha256": policy["sha256"],
            "checkpoint_file_sha256": audit.digest(
                directory / "latest-checkpoint.json"),
            "policy_file_sha256": audit.digest(directory / "policy.json")})
        write_new(directory / "result.json", result)
    return source


def frozen(tmp_path, old_study):
    output = tmp_path / "audit"
    manifest = audit.freeze(old_study, output)
    return output, manifest


def test_real_asset_load_average_verification_and_lookup(old_study, tmp_path):
    output, manifest = frozen(tmp_path, old_study)
    assert audit.load(output) == manifest
    asset = manifest["assets"][0]
    loaded = audit.load_asset(asset, manifest)
    query = paired_query(loaded["rules"], support_specs(6)[0])
    row = audit.inspect(asset["id"], query, loaded)
    assert row["status"] == "HIT" and row["export_nonuniform"] is False
    assert row["average_mass"] == len(query["observation"]["legal_actions"])


@pytest.mark.parametrize("kind", (
    "UNVISITED", "REGRET_TABLE_ONLY_ZERO", "REGRET_ONLY_NONZERO", "AVERAGE_ZERO_MASS"))
def test_missing_classes_not_filled_from_current_regrets(old_study, tmp_path, kind):
    _, manifest = frozen(tmp_path, old_study)
    asset = manifest["assets"][0]
    loaded = audit.load_asset(asset, manifest)
    query = paired_query(loaded["rules"], support_specs(6)[1])
    key, cp = query["abstract_key"], loaded["checkpoint"]
    actions = [a["id"] for a in query["observation"]["legal_actions"]]
    if kind != "UNVISITED":
        cp["regrets"][key] = dict.fromkeys(actions, 0.0)
        cp["committed_visits"][key] = 8
    if kind == "REGRET_ONLY_NONZERO":
        cp["regrets"][key][actions[0]] = 4.0
    if kind == "AVERAGE_ZERO_MASS":
        cp["average"][key] = dict.fromkeys(actions, 0.0)
    row = audit.inspect(asset["id"], query, loaded)
    assert row["status"] == kind and row["distribution"] is None
    assert row["historical_traverser_roles"] == "NOT_RECORDED_UNKNOWN"


def test_asset_bytes_drift_is_rejected(old_study, tmp_path):
    output, manifest = frozen(tmp_path, old_study)
    path = manifest["assets"][0]["files"]["policy"]["path"]
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="frozen_input_file_changed"):
        audit.load(output)


def test_report_retains_all_unexecuted_and_interrupted_rows(old_study, tmp_path):
    output, manifest = frozen(tmp_path, old_study)
    report = audit.write_report(output, manifest)
    assert report["overall_counts"] == {"NOT_RUN": 31941}
    shard = manifest["shards"][0]
    write_new(output / "attempts" / (shard["id"] + ".json"), {})
    report = audit.write_report(output, manifest)
    assert report["overall_counts"] == {"INTERRUPTED": 507, "NOT_RUN": 31434}
    assert report["ev"] is None and report["training_updates"] == 0


def test_second_batch_is_refused_even_after_failure(old_study, tmp_path, monkeypatch):
    output, _ = frozen(tmp_path, old_study)
    monkeypatch.setattr(audit, "run_bounded", lambda *a, **k: {
        "status": "TIMED_OUT_KILLED", "returncode": 1})
    with pytest.raises(RuntimeError, match="batch_failed"):
        audit.run(output)
    with pytest.raises(FileExistsError):
        audit.run(output)


def test_rehashed_export_cannot_disagree_with_original_average(old_study, tmp_path):
    _, manifest = frozen(tmp_path, old_study)
    asset = deepcopy(manifest["assets"][0])
    p = asset["files"]["policy"]["path"]
    document = json.loads(open(p, encoding="utf-8").read())
    values = next(iter(document["policy"].values()))
    for i, key in enumerate(values):
        values[key] = float(i == 0)
    document.pop("sha256")
    document = _bound_document(document)
    with open(p, "w", encoding="utf-8") as stream:
        json.dump(document, stream)
    asset["files"]["policy"]["sha256"] = audit.digest(p)
    with pytest.raises(ValueError, match="receipt_binding_mismatch"):
        audit.load_asset(asset, manifest)


@pytest.mark.parametrize("mutation", ("false_hit", "wrong_observation", "fake_na"))
def test_record_validation_does_not_trust_self_reported_keys_or_hits(
        old_study, tmp_path, mutation):
    _, manifest = frozen(tmp_path, old_study)
    asset = manifest["assets"][0]
    loaded = audit.load_asset(asset, manifest)
    spec = support_specs(6)[1]
    query = paired_query(loaded["rules"], spec)
    check = audit.inspect(asset["id"], query, loaded)
    record = {"spec": spec, "query": query, "checks": [check]}
    assets = {asset["id"]: loaded}
    audit.validate_record(record, manifest, assets)
    if mutation == "false_hit":
        check["status"] = "HIT"
        check["distribution"] = {a["id"]: 1 / len(query["observation"]["legal_actions"])
                                 for a in query["observation"]["legal_actions"]}
    elif mutation == "wrong_observation":
        query["observation"]["own_hole"] = ["Ac", "Ad"]
    else:
        query.update(status="NOT_APPLICABLE", observation=None, exact_key=None,
                     abstract_key=None, reason="invented")
    with pytest.raises(ValueError, match="recorded_"):
        audit.validate_record(record, manifest, assets)


def test_internal_worker_cannot_get_a_second_budget(old_study, tmp_path):
    output, _ = frozen(tmp_path, old_study)
    write_new(output / "batch.json", {"seconds": audit.BATCH_SECONDS, "max_batches": 1})
    write_new(output / "inner-started.json", {"one_attempt": True})
    with pytest.raises(FileExistsError):
        audit._run(output)


def test_output_cannot_write_inside_original_study(old_study):
    with pytest.raises(ValueError, match="read_only"):
        audit.freeze(old_study, old_study / "new-child")
    assert not (old_study / "new-child").exists()


@pytest.mark.parametrize("field", ("rules", "source_manifest_sha256", "seed"))
def test_resigned_metadata_cannot_rebind_original_assets(old_study, tmp_path, field):
    output, manifest = frozen(tmp_path, old_study)
    if field == "rules":
        manifest["rules"]["6"]["big_blind"] = "3"
    elif field == "seed":
        manifest["assets"][0]["seed"] = 999
    else:
        manifest[field] = "0" * 64
    manifest.pop("sha256")
    audit._atomic(output / "manifest.json", _bound_document(manifest))
    with pytest.raises(ValueError, match="metadata_rebinding"):
        audit.load(output)


def test_resigned_journal_cannot_turn_empty_distributions_into_507_hits(
        old_study, tmp_path):
    output, manifest = frozen(tmp_path, old_study)
    shard = manifest["shards"][0]
    specs = support_specs(6)[:169]
    records = [{"spec": s,
                "query": {"status": "READY", "exact_key": s["id"],
                          "abstract_key": s["id"]},
                "checks": [{"asset_id": _case["id"], "status": "HIT",
                            "distribution": None, "average_mass": 0,
                            "export_nonuniform": True}
                           for _case in manifest["assets"][:3]]} for s in specs]
    journal = output / "attempts" / (shard["id"] + ".jsonl")
    journal.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    write_new(output / "shards" / (shard["id"] + ".json"), {
        "manifest_sha256": manifest["sha256"], "shard": shard,
        "journal_sha256": audit.digest(journal)})
    with pytest.raises(ValueError, match="recorded_query"):
        audit.write_report(output, manifest)


def test_unknown_status_cannot_be_classified_as_completed():
    record = {"spec": {}, "query": {"status": "MADE_UP"}, "checks": []}
    with pytest.raises(ValueError, match="unknown_support_record_status"):
        audit.validate_record(record, {}, {})


def test_failure_row_cannot_carry_success_or_nonuniform_fields(old_study, tmp_path):
    _, manifest = frozen(tmp_path, old_study)
    asset = manifest["assets"][0]
    loaded = audit.load_asset(asset, manifest)
    spec = support_specs(6)[0]
    record = {"spec": spec, "query": paired_query(loaded["rules"], spec),
              "checks": [{"asset_id": asset["id"], "status": "ASSET_OR_LOOKUP_ERROR",
                          "reason": "synthetic failure", "export_nonuniform": True,
                          "distribution": {"fake": 1}}]}
    with pytest.raises(ValueError, match="invalid_asset_failure_record"):
        audit.validate_record(record, manifest, {asset["id"]: loaded})
