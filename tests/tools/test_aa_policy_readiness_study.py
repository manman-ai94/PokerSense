"""Bounded readiness infrastructure checks, never evidence of AA poker strength."""
from copy import deepcopy
import json
import sys
import time

import pytest

from poker_engine.strategy.aa_frozen_policy import canonical_hash
from poker_engine.strategy.aa_learning_diagnostics import learning_summary, memory_usage
from poker_engine.strategy.aa_mccfr import ExternalSamplingMCCFR, TrainingBudget
from tools import aa_policy_readiness_study as study


class TinyGame:
    """Two-player complete toy tree with repeated information sets."""

    def __init__(self, seed):
        self.history = []

    @property
    def actor(self):
        return len(self.history)

    @property
    def terminal(self):
        return len(self.history) == 2

    def observe(self, actor):
        return {"key": str(actor) + ":" + ",".join(self.history),
                "actions": ("a", "b")}

    def clone(self):
        return deepcopy(self)

    def step(self, action):
        self.history.append(action)

    def terminal_returns(self):
        utility = (2 if self.history[0] == "a" else 0) - (
            1 if self.history[1] == "a" else 0)
        return {0: utility, 1: -utility}


def learner(**kwargs):
    return ExternalSamplingMCCFR((0, 1), seed=42,
                                 encoder=lambda obs: obs["key"],
                                 menu=lambda obs: obs["actions"], **kwargs)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "identity", lambda: {"test_identity": "fixed"})
    output = tmp_path / "study"
    manifest = study.freeze(output)
    return output, manifest


def _fake_result(output, manifest, job_id, **diagnostics):
    job = next(row for row in manifest["jobs"] if row["id"] == job_id)
    case = next(row for row in manifest["cases"] if row["id"] == job["case_id"])
    directory = output / job_id
    directory.mkdir(exist_ok=True)
    value = {"binding": {"manifest_sha256": manifest["sha256"], "case": case,
                         "job_id": job_id,
                         "operation": job["operation"],
                         "rules": manifest["rules"][str(case["players"])]},
             "diagnostics": {"learning_signal": True, "completed_sweeps": 2,
                             "nonuniform_infosets": 0, "update_regrets": False,
                             **diagnostics}}
    study.write_new(directory / "result.json", study._bound_document(value))


def test_manifest_has_all_version_seed_cases_and_unexecuted_denominator(frozen):
    output, manifest = frozen
    assert len(manifest["cases"]) == 18
    assert len(manifest["jobs"]) == 90
    assert manifest["expected_pairs"] == 11340
    for version in study.VERSIONS:
        assert sum(row["expected_pairs"] for row in manifest["cases"]
                   if row["version"] == version) == 5670
    report = study.read_json(output / "study-report.json")
    assert report["unexecuted_pairs"] == report["expected_pairs"]
    assert report["gate2"]["status"] == "BLOCKED"
    assert report["metrics"] is None
    assert not report["strategy_eligible"]
    protocol = manifest["protocol"]
    assert protocol["evaluation_seeds"] == list(range(3000000, 3000030))
    assert protocol["control"]["requested_sweeps"] == 2
    assert protocol["max_batch_seconds"] == 3600
    with pytest.raises(FileExistsError):
        study.freeze(output)


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), 61, True])
def test_invalid_training_budget_does_not_create_output(tmp_path, bad):
    with pytest.raises(ValueError, match="budget"):
        study.freeze(tmp_path / "not-created", training_seconds=bad)
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), 3601, True])
def test_invalid_batch_budget_never_starts_process(tmp_path, bad):
    with pytest.raises(ValueError, match="budget"):
        study.run_phase(tmp_path, "train", batch_seconds=bad)


def test_real_mccfr_no_update_control_stays_uniform_but_learning_changes():
    trained, control = learner(), learner(update_regrets=False)
    for _ in range(20):
        trained.iterate(TinyGame)
        control.iterate(TinyGame)
    measured = learning_summary(trained, elapsed_seconds=1)
    negative = learning_summary(control, elapsed_seconds=1)
    assert measured["learning_signal"]
    assert measured["repeated_exported_nonuniform_infosets"] > 0
    assert negative["completed_sweeps"] == 20
    assert negative["nonuniform_infosets"] == 0
    assert all(value == 0 for row in control.regrets.values() for value in row.values())
    assert measured["strategy_strength"] == "NOT_ASSESSED"


def test_visits_and_mode_checkpoint_restore_and_failed_sweep_are_transactional():
    trainer = learner(update_regrets=False)
    trainer.iterate(TinyGame)
    original = trainer.checkpoint()
    resumed = ExternalSamplingMCCFR.restore(
        json.loads(json.dumps(original)), encoder=lambda obs: obs["key"],
        menu=lambda obs: obs["actions"])
    assert resumed.update_regrets is False
    trainer.iterate(TinyGame)
    resumed.iterate(TinyGame)
    assert trainer.checkpoint() == resumed.checkpoint()
    before = trainer.checkpoint()
    trainer.budget = TrainingBudget(max_nodes=1)
    with pytest.raises(RuntimeError, match="budget"):
        trainer.iterate(TinyGame)
    assert trainer.checkpoint() == before
    with pytest.raises(ValueError, match="learning_mode"):
        ExternalSamplingMCCFR.restore(original, update_regrets=True)


def test_legacy_checkpoint_without_telemetry_remains_restorable():
    trainer = learner()
    trainer.iterate(TinyGame)
    old = trainer.checkpoint()
    old.pop("sha256")
    old.pop("update_regrets")
    old.pop("committed_visits")
    old["sha256"] = canonical_hash(old)
    restored = ExternalSamplingMCCFR.restore(old)
    assert restored.regrets == trainer.regrets
    assert restored.average == trainer.average
    assert restored.iterations == trainer.iterations
    assert restored.visits == {} and restored.update_regrets


def test_real_external_timeout_kills_worker_before_it_can_write(tmp_path):
    marker = tmp_path / "should-not-exist.txt"
    command = [sys.executable, "-c",
               "import time,pathlib; time.sleep(4); "
               f"pathlib.Path({str(marker)!r}).write_text('late')"]
    started = time.monotonic()
    result = study.run_bounded(command, seconds=0.3)
    assert result["status"] == "TIMED_OUT_KILLED"
    assert time.monotonic() - started < 3
    assert not marker.exists()


def test_outer_timeout_kills_descendant_process_too(tmp_path):
    marker = tmp_path / "grandchild-late.txt"
    child = ("import time,pathlib;time.sleep(2);"
             f"pathlib.Path({str(marker)!r}).write_text('late')")
    command = [sys.executable, "-c",
               "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',"
               f"{child!r}]);time.sleep(10)"]
    result = study.run_bounded(command, seconds=0.5)
    assert result["status"] == "TIMED_OUT_KILLED"
    time.sleep(2)
    assert not marker.exists()


def test_resume_never_reexecutes_committed_training_jobs(frozen):
    output, manifest = frozen
    called = []

    def worker(command, **kwargs):
        job_id = command[command.index("--job") + 1]
        called.append(job_id)
        _fake_result(output, manifest, job_id)
        return {"status": "EXITED", "returncode": 0, "elapsed_seconds": 0.01}

    study.run_phase(output, "train", runner=worker)
    assert len(called) == 36 and len(set(called)) == 36
    study.run_phase(output, "train", runner=worker)
    assert len(called) == 36
    state = study.read_json(output / "study-state.json")
    assert all(len(row["attempts"]) == 1 for key, row in state["jobs"].items()
               if key.endswith(("-train", "-control")))


def test_result_commit_immediately_before_interrupt_is_not_duplicated(frozen):
    output, manifest = frozen
    calls = []

    def interrupted(command, **kwargs):
        job_id = command[command.index("--job") + 1]
        calls.append(job_id)
        _fake_result(output, manifest, job_id)
        raise KeyboardInterrupt()

    study.run_phase(output, "train", runner=interrupted)
    assert len(calls) == 1
    first = calls[0]

    def complete(command, **kwargs):
        job_id = command[command.index("--job") + 1]
        assert job_id != first
        calls.append(job_id)
        _fake_result(output, manifest, job_id)
        return {"status": "EXITED", "returncode": 0, "elapsed_seconds": 0.01}

    report = study.run_phase(output, "train", runner=complete)
    assert len(calls) == len(set(calls)) == 36
    assert report["unexecuted_pairs"] == 11340


def test_manifest_binding_and_source_changes_reject_resume(frozen, monkeypatch):
    output, manifest = frozen
    first = manifest["jobs"][0]["id"]
    _fake_result(output, manifest, first)
    path = output / first / "result.json"
    result = study.read_json(path)
    result.pop("sha256")
    result["binding"]["case"] = manifest["cases"][1]
    study._atomic(path, study._bound_document(result))
    with pytest.raises(ValueError, match="manifest_mismatch"):
        study.run_phase(output, "train")
    monkeypatch.setattr(study, "identity", lambda: {"test_identity": "changed"})
    with pytest.raises(ValueError, match="drift"):
        study.load_frozen(output)


def test_one_failed_v2_seed_blocks_all_evaluation_and_retains_pairs(frozen):
    output, manifest = frozen
    for case in manifest["cases"]:
        if case["version"] == "V2":
            _fake_result(output, manifest, case["id"] + "-train",
                         learning_signal=case["training_seed"] != 3301)
            _fake_result(output, manifest, case["id"] + "-control")
    report = study.run_phase(output, "evaluate", runner=lambda *a, **k: pytest.fail(
        "gate failed but evaluation started"))
    assert report["gate2"]["status"] == "BLOCKED"
    assert report["unexecuted_pairs"] == 11340
    assert report["complete_pairs"] == report["blocked_pairs"] == 0
    assert sum(row["status"] == "GATE_BLOCKED" for row in report["jobs"].values()) == 54


def test_real_memory_is_positive_or_explicitly_unknown():
    result = memory_usage()
    for name in ("rss_bytes", "peak_rss_bytes"):
        assert result[name] is None or result[name] > 0
    if result["source"] == "UNKNOWN":
        assert result["rss_bytes"] is result["peak_rss_bytes"] is None


def test_cli_report_is_nonmutating(frozen):
    output, _ = frozen
    before = {path: path.read_bytes() for path in output.glob("*.json")}
    assert study.main(["report", "--output", str(output)]) == 0
    assert before == {path: path.read_bytes() for path in output.glob("*.json")}


def test_concurrent_resume_is_rejected_and_lock_releases_on_interrupt(frozen):
    output, _ = frozen
    with study._exclusive_study(output):
        with pytest.raises(ValueError, match="already_running"):
            study.run_phase(output, "train")
    with study._exclusive_study(output):
        pass


def test_actual_evaluator_resumes_only_uncommitted_seed_blocks(tmp_path, monkeypatch):
    """Real empty asset exercises retained misses, not a claimed learned policy."""
    from poker_engine.strategy import aa_arena_evaluation as evaluation
    from poker_engine.strategy.aa_frozen_policy import make_policy
    monkeypatch.setattr(study, "identity", lambda: {"fixture_identity": "fixed"})
    monkeypatch.setattr(study, "EVALUATION_SEEDS", (17, 19))
    output = tmp_path / "actual-evaluation"
    manifest = study.freeze(output)
    case = manifest["cases"][0]
    job_id = case["id"] + "-evaluate-check_call"
    _, _, _, rules, directory, _ = study._context(output, job_id)
    asset_directory = output / (case["id"] + "-train")
    asset_directory.mkdir()
    policy = make_policy(rules_fingerprint=rules.fingerprint, table_size=6,
                         stack_depth_bb=100, policy={},
                         training={"purpose": "EMPTY_ASSET_ENGINEERING_FAILURE_TEST"})
    study.write_new(asset_directory / "policy.json", policy)
    actual = evaluation.evaluate_paired
    calls = []

    def interrupt_after_first(*args, **kwargs):
        seed = kwargs["seeds"][0]
        calls.append(seed)
        if seed == 19:
            raise KeyboardInterrupt()
        return actual(*args, **kwargs)

    monkeypatch.setattr(evaluation, "evaluate_paired", interrupt_after_first)
    with pytest.raises(KeyboardInterrupt):
        study.evaluate_job(output, job_id)
    committed = (directory / "seed-17.json").read_bytes()
    assert not (directory / "seed-19.json").exists()
    # A crash while saving may leave this unfinished sibling. Resume replaces only
    # the unfinished bytes, never the immutable completed seed-17 receipt.
    (directory / "seed-19.json.pending").write_text("unfinished", encoding="utf-8")

    def complete(*args, **kwargs):
        calls.append(kwargs["seeds"][0])
        return actual(*args, **kwargs)

    monkeypatch.setattr(evaluation, "evaluate_paired", complete)
    study.evaluate_job(output, job_id)
    study.evaluate_job(output, job_id)
    assert calls == [17, 19, 19]
    assert (directory / "seed-17.json").read_bytes() == committed
    manifest, state = study.load_frozen(output)
    result = study.summarize(output, manifest, state)
    assert result["blocked_pairs"] == 12
    assert result["complete_pairs"] == 0
    assert result["unexecuted_pairs"] == result["expected_pairs"] - 12
    first = result["cases"][0]
    assert first["observed_prefix_coverage"]["first_hero_hit"] == 0
    assert first["local_policy_latency"]["samples"] == 12
    assert first["execution_coverage_gate"] == "BLOCKED"
    assert first["metrics"] is None
    # An intact hash on a seed block cannot let it move to another style/job.
    altered = study.read_json(directory / "seed-17.json")
    altered.pop("sha256")
    altered["binding"]["job_id"] = case["id"] + "-evaluate-pot_raise"
    study._atomic(directory / "seed-17.json", study._bound_document(altered))
    with pytest.raises(ValueError, match="manifest_mismatch"):
        study.summarize(output, manifest, state)


def test_export_refuses_wrong_encoder_factory_even_for_empty_asset():
    from poker_engine.strategy.aa_frozen_policy import make_policy
    trainer = ExternalSamplingMCCFR(range(6), encoder_id="different_encoder")
    with pytest.raises(ValueError, match="encoder_factory"):
        trainer.export(rules_fingerprint="f" * 64, table_size=6, stack_depth_bb=100,
                       policy_factory=make_policy)


@pytest.mark.parametrize("variant", ["v1_fixed", "v2"])
def test_actual_training_job_retains_atomic_state_on_node_budget_failure(
        tmp_path, monkeypatch, variant):
    """Single-node probes validate plumbing; neither is a training experiment."""
    monkeypatch.setattr(study, "identity", lambda: {"fixture_identity": "fixed"})
    output = tmp_path / variant
    manifest = study.freeze(output, max_nodes=1)
    job_id = variant + "-n6-seed1103-control"
    report = study.train_job(output, job_id, seconds=0.5)
    assert report["stop_reason"] == "whole_sweep_budget_exceeded"
    assert report["diagnostics"]["completed_sweeps"] == 0
    assert report["diagnostics"]["nonuniform_infosets"] == 0
    assert report["diagnostics"]["update_regrets"] is False
    assert not report["diagnostics"]["learning_signal"]
    saved = study.read_json(output / job_id / "latest-checkpoint.json")
    assert saved["binding"]["manifest_sha256"] == manifest["sha256"]
    assert saved["trainer"]["committed_visits"] == {}
    assert (output / job_id / "policy.json").exists()
    result = study._result(output, job_id, manifest)
    assert result["policy_sha256"] == report["policy_sha256"]
