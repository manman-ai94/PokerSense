"""Study orchestration tests inject tiny models; no poker strength is inferred."""
from copy import deepcopy
import json

import pytest

from poker_engine.strategy.aa_frozen_policy import make_policy
from tools import aa_self_play_study as study


BUDGETS = dict(training_seconds=30, iterations=10, max_nodes=10000,
               max_infosets=10000, max_actions=1000)


def fake_training(rules, **kwargs):
    checkpoint = {"binding": {"rules": rules.fingerprint},
                  "trainer": {"seed": kwargs["seed"], "completed": 1}}
    kwargs["checkpoint_sink"](checkpoint)
    return ({"status": "COMPLETE_RESEARCH_RUN", "completed_sweeps_total": 1},
            checkpoint, make_policy(rules_fingerprint=rules.fingerprint,
                                    table_size=rules.table_size,
                                    stack_depth_bb=kwargs["depth"], policy={},
                                    training={"seed": kwargs["seed"]}))


def fake_evaluation(rules, candidate, baseline, opponents, **kwargs):
    count = rules.table_size * len(kwargs["seeds"]) * len(opponents)
    return {"status": "COMPLETE", "expected_pairs": count,
            "complete_pairs": count, "blocked_pairs": 0,
            "groups": [{"opponent": name, "table_size": rules.table_size,
                        "delta_net_bb100": 0, "ci95_delta_net_bb100": [0, 0]}
                       for name in sorted(opponents)],
            "strategy_eligible": False}


def test_manifest_precedes_first_fit_and_every_policy_is_saved_before_evaluation(
        tmp_path, monkeypatch):
    output = tmp_path / "smoke"
    calls = []

    def train(rules, **kwargs):
        frozen = study.read_json(output / "frozen-manifest.json")
        assert frozen["expected_runs"] == len(frozen["cases"]) == 9
        assert frozen["mode"] == "ENGINEERING_SMOKE_ONLY"
        assert frozen["effective_budgets"]["training_seconds"] == 2
        assert frozen["effective_budgets"]["paired_blocks"] == 2
        assert kwargs["seconds"] == 2 and kwargs["iterations"] == 1
        assert kwargs["max_nodes"] == kwargs["max_infosets"] == 2000
        initial = study.read_json(output / "study-report.json")
        assert initial["actual_runs"] == 9
        calls.append(("train", rules.table_size, kwargs["seed"]))
        return fake_training(rules, **kwargs)

    def evaluate(rules, candidate, baseline, opponents, **kwargs):
        assert calls[-1][0] == "train"
        case_path = output / f"n{rules.table_size}-seed{calls[-1][2]}"
        assert (case_path / "checkpoint.json").is_file()
        saved = study.read_json(case_path / "policy.json")
        assert candidate.sha256 == saved["sha256"]
        assert baseline is study.check_fold_policy
        assert set(opponents) == {"check_call", "min_raise", "pot_raise"}
        assert len(kwargs["seeds"]) == 2
        assert kwargs["max_actions"] == 200
        calls.append(("evaluate", rules.table_size))
        return fake_evaluation(rules, candidate, baseline, opponents, **kwargs)

    monkeypatch.setattr(study, "run_training", train)
    monkeypatch.setattr(study, "evaluate_paired", evaluate)
    report = study.run_study(output, **BUDGETS, smoke=True)
    assert [item[0] for item in calls] == ["train", "evaluate"] * 9
    assert report["expected_runs"] == report["actual_runs"] == 9
    assert report["complete_runs"] == 9
    assert report["started_runs"] == 9
    assert report["expected_pairs"] == report["complete_pairs"] == 378
    assert not report["strategy_eligible"]
    assert report["metrics"] is None and report["strategy_quality"] == "NOT_ASSESSED"
    assert "BLOCKED" in report["promotion"]
    assert report == study.read_json(output / "study-report.json")
    assert all("policy.json" in row["artifacts"]
               and "checkpoint.json" in row["artifacts"] for row in report["runs"])
    for row in report["runs"]:
        for name, digest in row["artifacts"].items():
            assert study._file_hash(output / row["run_id"] / name) == digest


def test_all_failures_and_partial_training_preserved_without_best_seed_selection(
        tmp_path, monkeypatch):
    calls = []

    def train(rules, **kwargs):
        calls.append((rules.table_size, kwargs["seed"]))
        result = fake_training(rules, **kwargs)
        if len(calls) == 1:
            raise RuntimeError("injected_after_partial_checkpoint")
        if len(calls) == 2:
            result[0]["status"] = "BUDGET_EXHAUSTED"
        return result

    def evaluate(rules, candidate, baseline, opponents, **kwargs):
        if rules.table_size == 7:
            raise RuntimeError("injected_evaluator_failure")
        result = fake_evaluation(rules, candidate, baseline, opponents, **kwargs)
        if rules.table_size == 8:
            result.update(status="BLOCKED", complete_pairs=0,
                          blocked_pairs=result["expected_pairs"])
            for row in result["groups"]:
                row["delta_net_bb100"] = row["ci95_delta_net_bb100"] = None
        return result

    monkeypatch.setattr(study, "run_training", train)
    monkeypatch.setattr(study, "evaluate_paired", evaluate)
    output = tmp_path / "failures"
    result = study.run_study(output, **BUDGETS, smoke=True)
    assert len(calls) == result["started_runs"] == result["actual_runs"] == 9
    assert len(set(calls)) == 9
    assert result["status"] == "PARTIAL"
    assert result["complete_runs"] == 1
    assert result["complete_pairs"] + result["blocked_pairs"] + result[
        "unreported_pairs"] == result["expected_pairs"]
    first = result["runs"][0]
    assert first["status"] == "ERROR"
    assert first["error"]["message"] == "injected_after_partial_checkpoint"
    assert "latest-checkpoint.json" in first["artifacts"]
    assert first["unreported_pairs"] == first["expected_pairs"]
    second = result["runs"][1]
    assert second["training_status"] == "BUDGET_EXHAUSTED"
    assert second["evaluation_status"] == "COMPLETE"
    assert second["metrics"] is None  # partial fit is not a full successful run
    assert "policy.json" in second["artifacts"]
    assert all(row["metrics"] is None for row in result["runs"]
               if row["status"] != "COMPLETE")


def test_full_mode_obeys_frozen_2000_blocks_without_running_large_study(
        tmp_path, monkeypatch):
    monkeypatch.setattr(study, "run_training", fake_training)

    def evaluate(rules, candidate, baseline, opponents, **kwargs):
        assert len(kwargs["seeds"]) == 2000
        assert kwargs["bootstrap_samples"] == 2000
        assert kwargs["max_actions"] == BUDGETS["max_actions"]
        return fake_evaluation(rules, candidate, baseline, opponents, **kwargs)

    monkeypatch.setattr(study, "evaluate_paired", evaluate)
    report = study.run_study(tmp_path / "full", **BUDGETS)
    assert report["mode"] == "SYNTHETIC_RESEARCH_ONLY"
    assert report["expected_pairs"] == 378000
    assert report["actual_runs"] == 9


def test_interrupt_retains_unstarted_cases_and_stops_training(tmp_path, monkeypatch):
    calls = []

    def interrupt(rules, **kwargs):
        calls.append(kwargs["seed"])
        fake_training(rules, **kwargs)
        raise KeyboardInterrupt()

    monkeypatch.setattr(study, "run_training", interrupt)
    result = study.run_study(tmp_path / "interrupted", **BUDGETS, smoke=True)
    assert len(calls) == result["started_runs"] == 1
    assert result["actual_runs"] == 9
    assert result["runs"][0]["status"] == "INTERRUPTED"
    assert all(row["status"] == "NOT_RUN_INTERRUPTED" for row in result["runs"][1:])
    assert "latest-checkpoint.json" in result["runs"][0]["artifacts"]
    assert result["complete_pairs"] == 0
    assert result["unreported_pairs"] == result["expected_pairs"]


def test_source_drift_blocks_remaining_fits_without_refreshing_manifest(
        tmp_path, monkeypatch):
    original = study._source_hashes()
    calls = []

    def changing_fit(rules, **kwargs):
        calls.append(kwargs["seed"])
        result = fake_training(rules, **kwargs)
        monkeypatch.setattr(study, "_source_hashes", lambda: {"changed.py": "00"})
        return result

    monkeypatch.setattr(study, "run_training", changing_fit)
    result = study.run_study(tmp_path / "drift", **BUDGETS, smoke=True)
    assert len(calls) == 1
    assert result["actual_runs"] == 9
    assert all(row["status"] == "ERROR" for row in result["runs"])
    manifest = study.read_json(tmp_path / "drift" / "frozen-manifest.json")
    assert manifest["source_files_sha256"] == original
    assert all(row["metrics"] is None for row in result["runs"])


def test_refuses_existing_output_and_invalid_protocol_before_writing(
        tmp_path, monkeypatch):
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "preserve.txt").write_text("old evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        study.run_study(existing, **BUDGETS, smoke=True)
    assert list(existing.iterdir()) == [existing / "preserve.txt"]
    protocol = deepcopy(study.read_json(study.DEFAULT_PROTOCOL))
    protocol["training_seeds"] = [1103, 1103, 3301]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        study.run_study(tmp_path / "invalid", **BUDGETS, protocol_path=path)
    assert not (tmp_path / "invalid").exists()


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_invalid_explicit_time_budget_has_no_output(tmp_path, bad):
    budgets = {**BUDGETS, "training_seconds": bad}
    with pytest.raises(ValueError, match="budgets"):
        study.run_study(tmp_path / "bad", **budgets)
    assert not (tmp_path / "bad").exists()


def test_cli_requires_explicit_budgets(tmp_path):
    with pytest.raises(SystemExit):
        study.main(["--output", str(tmp_path / "no-budget"), "--smoke"])
    assert not (tmp_path / "no-budget").exists()


@pytest.mark.parametrize("change", [
    {"training_deal_seed_min": 2 ** 63},
    {"evaluation_seed_start": 2 ** 62 - 2000,
     "confirmation_seed_start": 2 ** 62 - 1000},
    {"evaluation_seed_start": 1000000, "confirmation_seed_start": 1001000},
    {"confirmation_seed_start": 2 ** 62 - 1999},
])
def test_declared_seed_domains_cannot_hide_actual_training_overlap(
        tmp_path, change):
    protocol = study.read_json(study.DEFAULT_PROTOCOL)
    protocol.update(change)
    path = tmp_path / "overlap.json"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    with pytest.raises(ValueError, match="seed_domains"):
        study.run_study(tmp_path / "output", **BUDGETS, protocol_path=path)
    assert not (tmp_path / "output").exists()
