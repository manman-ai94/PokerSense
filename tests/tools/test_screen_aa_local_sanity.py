import json
from copy import deepcopy

import pytest

from tools import screen_aa_local_sanity as study


@pytest.fixture
def frozen(tmp_path):
    for directory in ("small", "large", "upstream"):
        (tmp_path / directory).mkdir()
    output = tmp_path / "results"
    manifest = study.freeze(output, tmp_path / "small", tmp_path / "large",
                            tmp_path / "upstream")
    return output, manifest


class FakeWorker:
    calls = []
    action = "check_call"
    fail_at = None

    def __init__(self, model, upstream, runtime):
        self.count = 0

    def receive(self, seconds):
        return {"status": "READY"}

    def query(self, query, seconds):
        self.count += 1
        self.calls.append(deepcopy(query))
        if self.count == self.fail_at:
            return {"status": "TIMEOUT", "elapsed_ms": 10001,
                    "worker_terminated": True}
        ids = [row["id"] for row in query["request"]["options"]]
        return {"status": "VALID", "action": self.action,
                "scores": {key: int(key == self.action) for key in ids},
                "elapsed_ms": 350}

    def close(self):
        pass


def execute(output, client=FakeWorker):
    return study.run(output, client_factory=client,
                     verify_assets=lambda *args: None,
                     ready_validator=lambda *args: None)


def test_real_cases_and_adapter_requests_never_send_answer_labels(frozen):
    output, manifest = frozen
    assert len(manifest["cases"]) == 9 and manifest["expected_rows"] == 18
    for case in manifest["cases"]:
        request = study.model_query(case["observation"], manifest["models"][0])
        assert set(request) == {"observation", "request", "request_sha256", "exact_key"}
        serialized = json.dumps(request["request"])
        for private_label in ("expected_action", "oracle", "branch_evidence",
                              "strict_margin",
                              "UNREALISTIC_FEE_STRESS_NOT_AA_RULE", case["id"]):
            assert private_label not in serialized
    assert study.load(output)["sha256"] == manifest["sha256"]


def test_wrong_actions_are_retained_as_failures_not_adaptation_errors(frozen):
    output, _ = frozen
    report = execute(output)
    assert report["completed"] and report["expected_rows"] == 18
    for model in report["models"]:
        assert model["summary"] == {
            "planned": 9, "correct": 6, "incorrect": 3,
            "unresolved": 0, "verdict": "FAIL_BASIC_CHECKS"}
        assert all(row["within_300ms"] is False for row in model["rows"])
    assert not report["strategy_eligible"] and not report["advice_emitted"]
    with pytest.raises(ValueError, match="already_started"):
        execute(output)


def test_timeout_preserves_all_eighteen_rows(frozen):
    class Timeout(FakeWorker):
        fail_at = 3  # after warmup and one real query

    report = execute(frozen[0], Timeout)
    for model in report["models"]:
        statuses = [row["status"] for row in model["rows"]]
        assert statuses == ["VALID", "TIMEOUT"] + ["NOT_RUN"] * 7
        assert model["summary"]["unresolved"] == 8


def test_load_failure_never_removes_planned_rows(frozen):
    class CannotLoad(FakeWorker):
        def receive(self, seconds):
            return {"status": "OOM"}

    report = execute(frozen[0], CannotLoad)
    assert all(len(m["rows"]) == 9 and m["summary"]["unresolved"] == 9
               for m in report["models"])


def test_worker_illegal_action_cannot_be_reported_valid(frozen):
    class Bad(FakeWorker):
        action = "raise_to:999999"

    report = execute(frozen[0], Bad)
    for model in report["models"]:
        assert model["rows"][0]["status"] == "ERROR"
        assert model["rows"][0]["action"] is None
        assert model["rows"][0]["correct"] is None
        assert model["summary"]["unresolved"] == 9


@pytest.mark.parametrize("mutate", [
    lambda m: m["limits"].update(query_seconds=20),
    lambda m: m["cases"][0].update(expected_action="fold"),
    lambda m: m["models"][0].update(temperature=9),
    lambda m: m["runtime_identity"].update(python_version="wrong"),
    lambda m: m["source_sha256"].update(unknown="wrong"),
    lambda m: m.update(kind="LIVE_STRATEGY"),
    lambda m: m.update(strategy_eligible=True),
])
def test_rehashed_protocol_drift_rejected(frozen, mutate):
    output, manifest = frozen
    mutate(manifest)
    manifest.pop("sha256")
    manifest["sha256"] = study.canonical_hash(manifest)
    study.screen._atomic(output / "manifest.json", manifest)
    with pytest.raises(ValueError):
        study.load(output)


@pytest.mark.parametrize("mutate", [
    lambda r: r["models"][0]["rows"][0].update(correct=False),
    lambda r: r["models"][0]["rows"][0].update(within_300ms=True),
    lambda r: r["models"][0]["rows"].pop(),
    lambda r: r["models"][0]["rows"][0].update(expected_action="fold"),
])
def test_saved_result_claims_are_independently_recomputed(frozen, mutate):
    report = execute(frozen[0])
    mutate(report)
    with pytest.raises(ValueError):
        study.summarize(report, frozen[1])
