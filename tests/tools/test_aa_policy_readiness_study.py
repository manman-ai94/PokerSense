"""Bounded readiness infrastructure checks, never evidence of AA poker strength."""
from copy import deepcopy
import json
import sys
import time

import pytest

from poker_engine.strategy.aa_frozen_policy import canonical_hash
from poker_engine.strategy.aa_learning_diagnostics import learning_summary, memory_usage
from poker_engine.strategy.aa_mccfr import ExternalSamplingMCCFR, TrainingBudget
from poker_engine.strategy import aa_mccfr as mccfr_module
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


def naive_left_to_right_sum(values, start=0):
    """CPython 3.11-style accumulation, even when tests run on newer Python."""
    total = start
    for value in values:
        total += value
    return total


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    from tools import aa_policy_street_challenges as queries
    monkeypatch.setattr(study, "identity", lambda: {"test_identity": "fixed"})
    monkeypatch.setattr(study, "EVALUATION_SEEDS", tuple(range(700, 730)))
    monkeypatch.setattr(queries, "CHALLENGE_SPEC", queries.DEVELOPMENT_SPEC)
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
    assert len(manifest["jobs"]) == 99
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
    assert protocol["evaluation_seeds"] == list(range(700, 730))
    assert protocol["control"]["requested_sweeps"] == 2
    assert protocol["max_batch_seconds"] == 3600
    assert protocol["final_serialization_reserve"] == {
        "seconds_cap": 5.0, "slot_fraction": 0.2, "within_frozen_case_budget": True}
    assert manifest["expected_queries"] == 1260  # only development two-seed fixtures
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
    old.pop("numerical_semantics")
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
    assert sum(row["status"] == "GATE_BLOCKED" for row in report["jobs"].values()) == 63


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
    monkeypatch.setattr(study, "EVALUATION_SEEDS", tuple(range(700, 730)))
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
        if seed == 701:
            raise KeyboardInterrupt()
        return actual(*args, **kwargs)

    monkeypatch.setattr(evaluation, "evaluate_paired", interrupt_after_first)
    with pytest.raises(KeyboardInterrupt):
        study.evaluate_job(output, job_id)
    committed = (directory / "seed-700.json").read_bytes()
    assert not (directory / "seed-701.json").exists()
    # A crash while saving may leave this unfinished sibling. Resume replaces only
    # the unfinished bytes, never the immutable completed seed-700 receipt.
    (directory / "seed-701.json.pending").write_text("unfinished", encoding="utf-8")

    def complete(*args, **kwargs):
        calls.append(kwargs["seeds"][0])
        return actual(*args, **kwargs)

    monkeypatch.setattr(evaluation, "evaluate_paired", complete)
    study.evaluate_job(output, job_id)
    study.evaluate_job(output, job_id)
    assert calls == [700, 701, *range(701, 730)]
    assert (directory / "seed-700.json").read_bytes() == committed
    manifest, state = study.load_frozen(output)
    result = study.summarize(output, manifest, state)
    assert result["blocked_pairs"] == 180
    assert result["complete_pairs"] == 0
    assert result["unexecuted_pairs"] == result["expected_pairs"] - 180
    first = result["cases"][0]
    assert first["observed_prefix_coverage"]["first_hero_hit"] == 0
    assert first["local_policy_latency"]["samples"] == 180
    assert first["execution_coverage_gate"] == "BLOCKED"
    assert first["metrics"] is None
    # An intact hash on a seed block cannot let it move to another style/job.
    altered = study.read_json(directory / "seed-700.json")
    altered.pop("sha256")
    altered["binding"]["job_id"] = case["id"] + "-evaluate-pot_raise"
    study._atomic(directory / "seed-700.json", study._bound_document(altered))
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
    state = study.read_json(output / "study-state.json")
    state["jobs"][job_id].update(status="RUNNING", attempts=[
        {"status": "RUNNING", "reserved_seconds": 0.5}])
    study._atomic(output / "study-state.json", state)
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


def test_gate2_rejects_self_rehashed_success_flag_without_actual_artifacts(frozen):
    output, manifest = frozen
    for case in manifest["cases"]:
        if case["version"] == "V2":
            _fake_result(output, manifest, case["id"] + "-train",
                         learning_signal=True, completed_sweeps=0,
                         nonuniform_infosets=0, update_regrets=False)
            _fake_result(output, manifest, case["id"] + "-control")
    result = study.gate2(output, manifest)
    assert result["status"] == "BLOCKED"
    assert all(row["train"] is None for row in result["verified_cases"])
    assert any(row["reason"] == "TRAIN_ARTIFACT_NOT_VERIFIED"
               for row in result["reasons"])


def test_gate2_recomputes_real_checkpoint_export_instead_of_report_flags(frozen):
    output, manifest = frozen
    case = next(case for case in manifest["cases"] if case["version"] == "V2")

    class MoreSeatsToy(TinyGame):
        def observe(self, actor):
            view = super().observe(actor)
            view["actions"] = ("fold", "check_call")
            return view

        def terminal_returns(self):
            utility = (2 if self.history[0] == "fold" else 0) - (
                1 if self.history[1] == "fold" else 0)
            return {0: utility, 1: -utility,
                    **{seat: 0 for seat in range(2, case["players"])}}

    for operation in ("train", "control"):
        job_id = case["id"] + "-" + operation
        _, _, _, rules, directory, binding = study._context(output, job_id)
        encoder_id, _, factory, _ = study._components(case["version"])
        trainer = ExternalSamplingMCCFR(
            range(case["players"]), seed=case["training_seed"], binding=binding,
            encoder_id=encoder_id, update_regrets=operation == "train",
            encoder=lambda obs: canonical_hash(obs["key"]),
            menu=lambda obs: obs["actions"])
        for _ in range(20 if operation == "train" else 2):
            trainer.iterate(MoreSeatsToy)
        study._checkpoint(directory / "latest-checkpoint.json", binding, trainer, 1)
        document = trainer.export(rules_fingerprint=rules.fingerprint,
                                  table_size=case["players"], stack_depth_bb=100,
                                  policy_factory=factory)
        study.write_new(directory / "policy.json", document)
        report = {"binding": binding, "status": "COMPLETE", "encoder": encoder_id,
                  "policy_sha256": document["sha256"],
                  "policy_file_sha256": study._hash_file(directory / "policy.json"),
                  "checkpoint_file_sha256": study._hash_file(
                      directory / "latest-checkpoint.json"),
                  "diagnostics": {"learning_signal": False, "completed_sweeps": 0}}
        study.write_new(directory / "result.json", study._bound_document(report))
    verified = study._verified_learning(output, manifest, case, "train")
    assert verified["learning_signal"] and verified["completed_sweeps"] == 20
    control = study._verified_learning(output, manifest, case, "control")
    assert control["nonuniform_infosets"] == 0 and control["completed_sweeps"] == 2
    # The other eight V2 cases still exist and prevent a global gate pass.
    assert study.gate2(output, manifest)["status"] == "BLOCKED"
    path = output / (case["id"] + "-train") / "policy.json"
    modified = study.read_json(path)
    modified.pop("sha256")
    key = next(iter(modified["policy"]))
    modified["policy"][key] = {a: 1 / len(modified["policy"][key])
                               for a in modified["policy"][key]}
    study._atomic(path, study._bound_document(modified))
    result_path = path.parent / "result.json"
    report = study.read_json(result_path)
    report.pop("sha256")
    report["policy_file_sha256"] = study._hash_file(path)
    report["policy_sha256"] = study.read_json(path)["sha256"]
    study._atomic(result_path, study._bound_document(report))
    with pytest.raises(ValueError, match="export_does_not_match"):
        study._verified_learning(output, manifest, case, "train")


def test_private_job_entry_cannot_grant_new_time_or_bypass_scheduler(frozen):
    output, manifest = frozen
    job_id = manifest["cases"][0]["id"] + "-train"
    with pytest.raises(ValueError, match="budget"):
        study.train_job(output, job_id, seconds=61)
    with pytest.raises(ValueError, match="scheduler_reservation"):
        study.train_job(output, job_id, seconds=60)
    state = study.read_json(output / "study-state.json")
    state["jobs"][job_id].update(
        status="RUNNING", charged_seconds=59,
        attempts=[{"status": "RUNNING", "reserved_seconds": 60}])
    study._atomic(output / "study-state.json", state)
    with pytest.raises(ValueError, match="scheduler_reservation"):
        study.train_job(output, job_id, seconds=2)


def test_actual_development_query_job_is_bound_and_cannot_pass_admission(frozen):
    output, manifest = frozen
    case = next(row for row in manifest["cases"] if row["version"] == "V2")
    job_id = case["id"] + "-query"
    _, _, _, rules, directory, _ = study._context(output, job_id)
    encoder, _, factory, _ = study._components("V2")
    policy_directory = output / (case["id"] + "-train")
    policy_directory.mkdir()
    document = factory(rules_fingerprint=rules.fingerprint, table_size=case["players"],
                       stack_depth_bb=100, policy={},
                       training={"purpose": "DEVELOPMENT_QUERY_WIRING_ONLY"})
    study.write_new(policy_directory / "policy.json", document)
    report = study.query_job(output, job_id, deadline=time.monotonic() + 20)
    assert report["query_report"]["development_only"] is True
    assert {row["seed"] for row in report["query_report"]["rows"]} == {4441, 4442}
    assert report["query_report"]["side_pot_scope_failures"] == 0
    assert report["hidden_input_probe"]["passed"]
    assert report["binding"]["query_spec_sha256"] == manifest["protocol"][
        "street_query_spec_sha256"]
    assert not study._query_success(report, manifest["protocol"]["street_query_spec"],
                                    manifest["protocol"]["street_query_schedules"]["6"])
    before = (directory / "result.json").read_bytes()
    study.query_job(output, job_id, deadline=time.monotonic() + 20)
    assert (directory / "result.json").read_bytes() == before
    assert document["encoder"] == encoder


def test_rehashed_manifest_cannot_remove_failed_cases_from_denominator(frozen):
    output, manifest = frozen
    changed = deepcopy(manifest)
    changed.pop("sha256")
    changed["cases"].pop()
    changed = study._bound_document(changed)
    study._atomic(output / "frozen-manifest.json", changed)
    with pytest.raises(ValueError, match="denominator"):
        study.load_frozen(output)
    assert study.gate2(output, {"cases": []})["status"] == "BLOCKED"


def test_query_gate_rejects_consistently_rehashed_truncated_suffixes(frozen):
    _, manifest = frozen
    spec = deepcopy(manifest["protocol"]["street_query_spec"])
    spec["version"] = "AA_STREET_QUERY_CHALLENGES_V1"
    schedule = manifest["protocol"]["street_query_schedules"]["6"]
    rows = []
    for kind in spec["kinds"]:
        for seed in spec["seeds"]:
            for index, expected in enumerate(schedule[kind]):
                scoped = kind != "side_pot_scope"
                rows.append({**expected, "kind": kind, "seed": seed, "index": index,
                             "scope_expected": scoped,
                             "legal": True if scoped else None,
                             "lookup_status": "HIT" if scoped else "SCOPE_MISMATCH"})

    def result(query_rows):
        counts = {street: {"opportunities": 0, "hit": 0, "illegal": 0}
                  for street in ("preflop", "flop", "turn", "river")}
        for row in query_rows:
            if row["scope_expected"]:
                counts[row["street"]]["opportunities"] += 1
                counts[row["street"]]["hit"] += 1
        return {"query_report": {
            "spec": spec, "spec_sha256": canonical_hash(spec),
            "development_only": False,
            "rows": query_rows, "by_street": counts, "side_pot_scope_failures": 0,
            "all_streets_have_positive": True},
            "hidden_input_probe": {"passed": True, "cases": [
                {"container": name, "rejected": True}
                for name in (None, "public_history", "rules")]}}

    assert study._query_success(result(rows), spec, schedule)
    truncated = [row for row in rows if row["index"] < len(schedule[row["kind"]]) - 1]
    assert not study._query_success(result(truncated), spec, schedule)


@pytest.mark.parametrize("variant", ["V1_FIXED", "V2"])
@pytest.mark.parametrize("accumulator", ["native", "naive"])
def test_sorted_json_full_aa_resume_matches_uninterrupted_development_deal(
        variant, accumulator, monkeypatch):
    # Newer CPython sum() is more accurate and can mask insertion-order bugs.
    # Exercise the older naive accumulator explicitly on every supported runtime.
    if accumulator == "naive":
        monkeypatch.setattr(mccfr_module, "sum", naive_left_to_right_sum, raising=False)
    encoder_id, encoder, _, _ = study._components(variant)
    rules = study.rules_for(study.DEFAULT_RULES, 6)
    budget = TrainingBudget(max_nodes=10000, max_infosets=10000, seconds=30)
    trainer = ExternalSamplingMCCFR(range(6), seed=71013, budget=budget,
                                    encoder=encoder, encoder_id=encoder_id)

    def factory(unused_seed):
        # Repeated DEVELOPMENT deal deliberately creates revisits for numerical
        # continuation checking. It is never used as a learning-quality result.
        return study.AAFullHandArena(rules).reset(71012)

    for _ in range(3):
        trainer.iterate(factory)
    checkpoint = json.loads(json.dumps(trainer.checkpoint(), sort_keys=True))
    resumed = ExternalSamplingMCCFR.restore(checkpoint, budget=budget, encoder=encoder,
                                            expected_encoder=encoder_id)
    for _ in range(3):
        trainer.iterate(factory)
        resumed.iterate(factory)
    assert trainer.checkpoint() == resumed.checkpoint()
    assert json.dumps(trainer.checkpoint(), sort_keys=True) == json.dumps(
        resumed.checkpoint(), sort_keys=True)
    assert learning_summary(trainer, elapsed_seconds=1)["nonuniform_infosets"] > 0


def test_normalization_is_json_order_independent_with_naive_float_sum(monkeypatch):
    monkeypatch.setattr(mccfr_module, "sum", naive_left_to_right_sum, raising=False)
    original = {"z": 1e16, "a": 1.0, "b": 1.0}
    restored = json.loads(json.dumps(original, sort_keys=True))
    # Demonstrates this test would catch the previous order-sensitive implementation.
    assert naive_left_to_right_sum(original.values()) != naive_left_to_right_sum(
        restored.values())
    assert ExternalSamplingMCCFR._strategy(original) == ExternalSamplingMCCFR._strategy(
        restored)
    first, second = learner(), learner()
    first.average, second.average = {"state": original}, {"state": restored}
    assert json.dumps(first.average_policy(), sort_keys=True) == json.dumps(
        second.average_policy(), sort_keys=True)


def test_numerical_semantics_are_declared_and_unknown_future_semantics_rejected():
    trainer = learner()
    checkpoint = trainer.checkpoint()
    assert checkpoint["numerical_semantics"] == mccfr_module.NUMERICAL_SEMANTICS
    checkpoint.pop("sha256")
    checkpoint["numerical_semantics"] = "unknown_future_numerics"
    checkpoint["sha256"] = canonical_hash(checkpoint)
    with pytest.raises(ValueError, match="numerical_semantics"):
        ExternalSamplingMCCFR.restore(checkpoint)
