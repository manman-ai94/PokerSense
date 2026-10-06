"""Development-only full-hand and persistence controls; no actual model evidence."""
from copy import deepcopy
import json
from pathlib import Path
import time

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_arena_evaluation import (  # noqa: E402
    check_call_policy, evaluate_paired,
)
from poker_engine.strategy.aa_frozen_policy import canonical_hash  # noqa: E402
from tools import evaluate_aa_local_fullhands as study  # noqa: E402


def model_folder(parent, index):
    folder = parent / ("model" + str(index))
    folder.mkdir()
    for name in study.screen.MODEL_FILES:
        (folder / name).write_text("{}", encoding="utf-8")
    (folder / "source-metadata.json").write_text(json.dumps({
        "sha": study.screen.MODEL_SPECS[index]["revision"]}), encoding="utf-8")
    return folder


@pytest.fixture
def frozen(tmp_path):
    output = tmp_path / "study"
    study.freeze(output, model_folder(tmp_path, 0), model_folder(tmp_path, 1),
                 tmp_path / "upstream", development=True)
    return output


class SyntheticClient:
    """Scores always choose check/call; this is explicitly an engineering control."""
    instances = []

    def __init__(self, model=None, upstream=None, runtime=None,
                 status="VALID", late=False):
        self.calls, self.closed, self.status, self.late = [], False, status, late
        self.ready = ({"status": "READY", **study.screen.expected_ready(
            model, upstream, runtime)}
                      if runtime is not None else {"status": "READY"})
        self.instances.append(self)

    def receive(self, seconds):
        return deepcopy(self.ready)

    def query(self, query, seconds):
        self.calls.append(deepcopy(query))
        if self.status != "VALID":
            return {"status": self.status, "elapsed_ms": 10000,
                    "reason": "synthetic_failure_control"}
        ids = [option["id"] for option in query["request"]["options"]]
        return {"status": "VALID", "action": "check_call", "cached": False,
                "elapsed_ms": 400 if self.late else 1, "inference_ms": 0.5,
                "scores": {action: int(action == "check_call") for action in ids},
                "context_tokens": 10, "prompt_tokens": 20}

    def close(self):
        self.closed = True


@pytest.mark.parametrize("n", (6, 7, 8))
def test_real_evaluator_worker_adapter_full_four_streets_42_positive_controls(n):
    rules = study.rules_for(study.DEFAULT_RULES, n)
    client = SyntheticClient()
    policy = study.WorkerBackedResearchPolicy(
        rules, study.screen.MODEL_SPECS[0], client, deadline=time.perf_counter() + 60)
    report = evaluate_paired(
        rules, policy, check_call_policy, {"check_call": check_call_policy},
        seeds=study.DEVELOPMENT_SEEDS, bootstrap_samples=100, record_diagnostics=True)
    assert report["complete_pairs"] == n * 2
    assert len(policy.games) == n * 2
    opportunities = [row for game in policy.games for row in game["opportunities"]]
    assert len(client.calls) == len(opportunities) == n * 2 * 4
    assert {row["street"] for row in opportunities} == {
        "preflop", "flop", "turn", "river"}
    assert all(row["cache_calls"] == 1 for row in opportunities)
    assert all(row["failure"] is None and row["action"] == "check_call"
               for row in opportunities)
    assert all(set(query) == {"observation", "request", "request_sha256", "exact_key"}
               for query in client.calls)
    assert all("seed" not in json.dumps(query["request"]) for query in client.calls)
    for row in report["rows"]:
        for field in ("trace_sha256", "terminal", "return_chips"):
            assert row["candidate"][field] == row["baseline"][field]
    # Same observation in another game must infer again, not reuse prior game's cache.
    first = opportunities[0]["observation"]
    count = len(client.calls)
    policy.for_game("f" * 64)(first)
    assert len(client.calls) == count + 1


@pytest.mark.parametrize("status", ("TIMEOUT", "CONTEXT_OVERFLOW", "ERROR"))
def test_model_failures_remain_blocked_without_default_actions(status):
    rules = study.rules_for(study.DEFAULT_RULES, 6)
    client = SyntheticClient(status=status)
    policy = study.WorkerBackedResearchPolicy(
        rules, study.screen.MODEL_SPECS[0], client, deadline=time.perf_counter() + 60)
    report = evaluate_paired(
        rules, policy, check_call_policy, {"check_call": check_call_policy},
        seeds=[4441], bootstrap_samples=100, record_diagnostics=True)
    assert report["expected_pairs"] == report["blocked_pairs"] == 6
    assert report["groups"][0]["delta_net_bb100"] is None
    assert all(row["action"] is None for game in policy.games
               for row in game["opportunities"])
    if status in ("TIMEOUT", "ERROR"):
        assert not policy.available and len(client.calls) == 1


def test_freeze_complete_denominator_without_consuming_new_deals(frozen):
    manifest = study.load_manifest(frozen)
    assert len(manifest["shards"]) == 36 and manifest["expected_pairs"] == 252
    assert len(study._shards(study.EVALUATION_SEEDS)) == 540
    assert sum(row["expected_pairs"] for row in
               study._shards(study.EVALUATION_SEEDS)) == 3780
    assert manifest["sample_kind"] == "DEVELOPMENT_CONTROL"
    assert all(s["seed"] in (4441, 4442) for s in manifest["shards"])
    assert [s["policy_seed"] for s in manifest["shards"]] == list(range(7719, 7755))
    report = study.read_json(frozen / "report.json")
    assert report["reported_pairs"] == report["expected_pairs"] == 252
    assert all(row["status"] == "NOT_RUN" for row in report["pairs"])
    assert all(group["delta_net_bb100"] is None for group in report["groups"])


def actual_record(manifest, shard=None, *, late=False):
    shard = shard or manifest["shards"][0]
    result, available = study.evaluate_shard(
        shard, manifest, SyntheticClient(late=late), deadline=time.perf_counter() + 60,
        sink=lambda games: None)
    assert available
    return {"manifest_sha256": manifest["sha256"], "shard": shard, "batch": 0,
            "result": result, "attempt_files": [shard["id"] + "-b0.json"]}


def test_late_legal_full_hands_are_complete_but_not_timely(frozen):
    manifest = study.load_manifest(frozen)
    record = actual_record(manifest, late=True)
    study.validate_shard_record(record, record["shard"], manifest)
    assert record["result"]["complete_pairs"] == 6
    assert not any(row["timely_complete"] for row in record["result"]["rows"])


@pytest.mark.parametrize("change", [
    "duplicate_hero", "wrong_seed", "wrong_descriptor", "wrong_rules", "wrong_delta",
    "wrong_candidate", "false_timely", "empty_opportunities", "missing_action",
])
def test_copied_or_shifted_shard_cannot_enter_cluster_metrics(frozen, change):
    manifest = study.load_manifest(frozen)
    record = actual_record(manifest)
    result = record["result"]
    if change == "duplicate_hero":
        result["rows"][-1]["hero"] = 0
    elif change == "wrong_seed":
        result["rows"][0]["seed"] = 4442
    elif change == "wrong_descriptor":
        record["shard"] = manifest["shards"][1]
    elif change == "wrong_rules":
        result["protocol"]["rules"]["rake_percent"] = "0.2"
    elif change == "wrong_delta":
        result["rows"][0]["delta_bb"]["numerator"] += 1
    elif change == "false_timely":
        receipt = result["rows"][0]["local_model_receipt"]["opportunities"][0]
        receipt["first_decision_ms"] = 500
        receipt["worker_response"]["elapsed_ms"] = 500
        receipt["timely"] = True
    elif change == "empty_opportunities":
        result["rows"][0]["local_model_receipt"]["opportunities"] = []
    elif change == "missing_action":
        receipt = result["rows"][0]["local_model_receipt"]["opportunities"][0]
        receipt["action"] = None
        receipt["timely"] = False
        result["rows"][0]["timely_complete"] = False
    else:
        result["protocol"]["candidate_id"] = "different-model"
    result["protocol_sha256"] = canonical_hash(result["protocol"])
    with pytest.raises(ValueError):
        study.validate_shard_record(record, manifest["shards"][0], manifest)


def test_atomic_shard_rename_recovers_without_replay(frozen):
    manifest = study.load_manifest(frozen)
    record = actual_record(manifest)
    name = record["shard"]["id"]
    study.screen._atomic(frozen / "shards" / (name + ".json"), record)
    state = study._read_state(frozen, manifest)
    assert state["committed"][name] == canonical_hash(record)
    report = study.write_report(frozen, manifest=manifest, state=state)
    assert report["complete_pairs"] == 6
    assert report["groups"][0]["delta_net_bb100"] is None  # other seed missing


def test_two_batches_no_replay_of_interrupted_or_committed_shards(frozen, monkeypatch):
    SyntheticClient.instances.clear()
    calls = []
    real_evaluate_shard = study.evaluate_shard

    def crash_first(shard, manifest, client, *, deadline, sink):
        calls.append(shard["id"])
        sink([])
        raise SystemExit("synthetic_process_death")

    monkeypatch.setattr(study, "evaluate_shard", crash_first)
    with pytest.raises(SystemExit):
        study.run_batch(frozen, client_factory=SyntheticClient,
                        asset_verifier=lambda *args: None)
    manifest = study.load_manifest(frozen)
    first = manifest["shards"][0]
    before = (frozen / "attempts" / (first["id"] + "-b0.json")).read_bytes()

    def complete_rest(shard, manifest, client, *, deadline, sink):
        calls.append(shard["id"])
        result = real_evaluate_shard(
            shard, manifest, client, deadline=deadline, sink=sink)
        actual_clock = time.perf_counter
        monkeypatch.setattr(study.time, "perf_counter", lambda: actual_clock() + 5000)
        return result

    monkeypatch.setattr(study, "evaluate_shard", complete_rest)
    state = study.run_batch(frozen, client_factory=SyntheticClient,
                            asset_verifier=lambda *args: None)
    assert len(state["batches"]) == 2
    assert len(calls) == len(set(calls)) == 2
    assert before == (frozen / "attempts" / (first["id"] + "-b0.json")).read_bytes()
    first_record = study.read_json(frozen / "shards" / (first["id"] + ".json"))
    assert first_record["result"]["failure"] == "BLOCKED_INTERRUPTED"
    report = study.write_report(frozen)
    assert report["expected_pairs"] == report["reported_pairs"] == 252
    assert report["complete_pairs"] == 6
    assert report["groups"][0]["delta_net_bb100"] is None
    assert report["groups"][0]["blocked_pairs"] == 6
    assert report["groups"][0]["prior_failed_or_interrupted_attempts"] == 1
    assert all(group["delta_net_bb100"] is None for group in report["groups"])
    with pytest.raises(ValueError, match="batch_limit"):
        study.run_batch(frozen)


def test_load_failures_count_against_per_model_per_batch_limit(frozen):
    class FailingClient(SyntheticClient):
        def receive(self, seconds):
            return {"status": "OOM", "reason": "synthetic_load_failure"}
    state = study.run_batch(frozen, client_factory=FailingClient,
                            asset_verifier=lambda *args: None)
    assert all(len(model["loads"]) == 2
               for model in state["batches"][0]["models"].values())
    assert not state["committed"]
    report = study.write_report(frozen)
    assert report["expected_pairs"] == report["reported_pairs"] == 252
    assert report["complete_pairs"] == 0 and all(
        group["delta_net_bb100"] is None for group in report["groups"])


def test_kernel_lease_rejects_concurrent_writer_and_releases(frozen):
    with study.exclusive(frozen):
        with pytest.raises(ValueError, match="already_running"):
            with study.exclusive(frozen):
                pytest.fail("must not acquire twice")
    with study.exclusive(frozen):
        pass


@pytest.mark.parametrize("field", [
    "runtime_identity", "source_sha256", "seeds", "baseline", "sample_kind",
    "stack_depth_bb", "strategy_eligible", "warmup",
])
def test_manifest_rehash_cannot_relabel_frozen_protocol(frozen, field):
    path = frozen / "manifest.json"
    data = study.read_json(path)
    if field == "seeds":
        data[field] = [4441, 4441]
    elif field in ("runtime_identity", "source_sha256", "warmup"):
        data[field] = {}
    elif field == "strategy_eligible":
        data[field] = True
    else:
        data[field] = "incorrect"
    data.pop("sha256")
    data["sha256"] = canonical_hash(data)
    study.screen._atomic(path, data)
    with pytest.raises(ValueError, match="mismatch"):
        study.load_manifest(frozen)


def test_atomic_failure_does_not_replace_existing_artifact(tmp_path, monkeypatch):
    path = tmp_path / "atomic.json"
    study.screen._atomic(path, {"version": 1})
    original = Path.replace

    def fail_pending(self, target):
        if self.name.endswith("pending.json"):
            raise OSError("synthetic_disk_failure")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", fail_pending)
    with pytest.raises(OSError, match="disk_failure"):
        study.screen._atomic(path, {"version": 2})
    assert study.read_json(path) == {"version": 1}


def test_freeze_return_does_not_alias_constant_protocol(tmp_path):
    output = tmp_path / "isolated-protocol"
    result = study.freeze(output, model_folder(tmp_path, 0), model_folder(tmp_path, 1),
                          tmp_path / "upstream", development=True)
    original = deepcopy(study.LIMITS)
    result["limits"]["max_batches"] = 999
    result["upstream"]["files"].clear()
    assert study.LIMITS == original and study.screen.UPSTREAM_FILES
    result.pop("sha256")
    result["sha256"] = canonical_hash(result)
    study.screen._atomic(output / "manifest.json", result)
    with pytest.raises(ValueError, match="mismatch"):
        study.load_manifest(output)
