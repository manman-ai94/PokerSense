from copy import deepcopy
import hashlib
from itertools import combinations
import json
from pathlib import Path
import time

import pytest

from poker_engine.desktop.aa_analysis import AAConditionalAnalysis, _analysis_worker
from tests.timing import Stopwatch, budget, over, timing, within_budget


EXAMPLES = Path(__file__).resolve().parents[2] / "configs/strategy/examples"
BINDING = {"table_rules_revision": 2, "observation_generation": 7,
           "source": {"kind": "manual"}}


def document(kind="terminal"):
    name = ("terminal-multiway-river-manual.json" if kind == "terminal"
            else "threeway-river-response-manual.json")
    return json.loads((EXAMPLES / name).read_bytes())


def finish(service, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = service.status()
        if value["status"] != "RUNNING":
            return value
        time.sleep(0.025)
    pytest.fail("analysis watchdog did not produce a terminal status")


def controlled_worker(sender, kind, value):
    time.sleep(value.pop("_test_delay", 0))
    _analysis_worker(sender, kind, value)


def crashing_worker(sender, kind, value):
    sender.close()
    raise RuntimeError("fixed trusted test worker crashed")


def forged_worker(sender, kind, value):
    sender.send_bytes(json.dumps({
        "status": "COMPLETE", "error": None, "result": {
            "status": "COMPLETE_CONDITIONAL", "strategy_eligible": True,
            "advice_emitted": True}}).encode())
    sender.close()


def oversized_worker(sender, kind, value):
    sender.send_bytes(b" " * 2_000_001)
    sender.close()


@pytest.mark.parametrize("kind,expected", [
    ("terminal", "COMPLETE_CONDITIONAL"),
    ("threeway", "COMPLETE_CONDITIONAL_ABSTRACTION"),
])
def test_real_spawned_manual_examples_with_binding_and_detached_reports(kind, expected):
    service = AAConditionalAnalysis()
    try:
        value, binding = document(kind), deepcopy(BINDING)
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
        started = service.start(kind, value, binding=binding)
        value["mode"] = "changed_after_submit"
        binding["source"]["kind"] = "changed_after_submit"
        report = finish(service)
        assert report["status"] == "COMPLETE", report
        assert report["result"]["status"] == expected
        assert report["input_sha256"] == hashlib.sha256(raw).hexdigest()
        assert report["job_id"] == started["job_id"] == report["id"]
        assert report["revision"] > started["revision"]
        assert report["binding"] == BINDING
        assert report["manual_notlive"] and not report["strategy_eligible"]
        assert not report["advice_emitted"]
        assert report["result"]["strategy_eligible"] is False
        assert report["result"]["advice_emitted"] is False
        report["result"]["status"] = "forged"
        report["binding"]["source"]["kind"] = "forged"
        assert service.status()["result"]["status"] == expected
        assert service.status()["binding"] == BINDING
    finally:
        service.cancel()


def test_real_worker_keeps_invalid_pot_blocked_without_live_promotion():
    service = AAConditionalAnalysis()
    try:
        value = document()
        value["pot_before"] = "1"
        service.start("terminal", value, binding=BINDING)
        report = finish(service)
        assert report["status"] == "BLOCKED"
        assert "pot_or_current_bet_does_not_reconcile" in report["result"]["reasons"]
        assert report["result"]["recommendation"] is None
    finally:
        service.cancel()


def test_real_worker_parser_exception_is_contained_without_partial_output():
    service = AAConditionalAnalysis()
    try:
        service.start("terminal", {"mode": "manual_hypothesis"}, binding=BINDING)
        report = finish(service)
        assert report["status"] == "ERROR"
        assert "exact declared fields" in report["error"]
        assert report["result"] is None
    finally:
        service.cancel()


@pytest.mark.parametrize("kind,per_range", [("terminal", 17), ("threeway", 12)])
def test_joint_assignment_caps_reject_expanded_inputs_before_large_compute(
        kind, per_range):
    service = AAConditionalAnalysis()
    try:
        value = document(kind)
        deck = [rank + suit for rank in "23456789TJQKA" for suit in "cdhs"]
        combos = list(combinations(deck, 2))[:per_range]
        for opponent in value["ranges"]:
            opponent["combos"] = {a + b: "1" for a, b in combos}
        # Terminal 17**3 exceeds 4096; threeway 12**2 exceeds 128.
        service.start(kind, value, binding=BINDING)
        report = finish(service)
        assert report["status"] == "BLOCKED", report
        assert any("budget" in reason for reason in report["result"]["reasons"])
        assert not report["result"]["strategy_eligible"]
    finally:
        service.cancel()


def test_timeout_terminates_without_status_polling_and_allows_new_job():
    service = AAConditionalAnalysis(timeout_seconds=1, _test_worker=controlled_worker)
    try:
        value = document()
        value["_test_delay"] = 10
        first = service.start("terminal", value, binding=BINDING)
        process = service._process
        # The watchdog must run while the caller does nothing at all. The job
        # itself would end after 10 s, as COMPLETE; the status tells them apart.
        deadline = time.monotonic() + 8
        while process.is_alive() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert not process.is_alive()
        expired = service.status()
        assert expired["status"] == "TIMED_OUT"
        assert expired["result"] is None
        second = service.start("terminal", document(), binding=BINDING)
        assert second["job_id"] != first["job_id"]
        assert finish(service)["status"] == "COMPLETE"
    finally:
        service.cancel()


def parallel_rejection_and_cancel():
    """Seconds cancelling a running job took; the old job never returns."""
    service = AAConditionalAnalysis(_test_worker=controlled_worker)
    try:
        value = document()
        value["_test_delay"] = 10
        first = service.start("terminal", value, binding=BINDING)
        process = service._process
        with pytest.raises(RuntimeError, match="already_running"):
            service.start("terminal", document(), binding=BINDING)
        watch = Stopwatch()
        cancelled = service.cancel()
        took = watch()
        assert cancelled["status"] == "CANCELLED" and cancelled["result"] is None
        assert cancelled["revision"] > first["revision"]
        assert not process.is_alive()
        second = service.start("terminal", document(), binding=BINDING)
        result = finish(service)
        assert result["status"] == "COMPLETE"
        assert result["job_id"] == second["job_id"] != first["job_id"]
        service.cancel()
        assert service.status()["result"] is None
        return took
    finally:
        service.cancel()


def test_parallel_rejection_cancel_terminates_and_old_job_cannot_return():
    parallel_rejection_and_cancel()


@timing
def test_cancel_stops_a_running_job_promptly():
    within_budget(lambda: over("seconds", parallel_rejection_and_cancel(), budget(1.5)))


@pytest.mark.parametrize("target", [crashing_worker, forged_worker, oversized_worker])
def test_child_failure_bad_authority_and_output_budget_are_contained(target):
    service = AAConditionalAnalysis(_test_worker=target)
    try:
        service.start("terminal", document(), binding=BINDING)
        process = service._process
        report = finish(service)
        assert report["status"] == "ERROR", report
        assert report["result"] is None
        assert not process.is_alive()
        assert not report["strategy_eligible"] and not report["advice_emitted"]
    finally:
        service.cancel()


@pytest.mark.parametrize("kind,value,binding,reason", [
    ("script", {"mode": "manual_hypothesis"}, {}, "unsupported_analysis_kind"),
    ("terminal", {"mode": "live"}, {}, "manual_hypothesis"),
    ("terminal", {"mode": "manual_hypothesis", "x": "a" * 200000}, {}, "byte_limit"),
    ("terminal", {"mode": "manual_hypothesis", "x": float("nan")}, {}, "invalid_json"),
    ("terminal", {"mode": "manual_hypothesis", 1: "x"}, {}, "string_keys"),
    ("terminal", {"mode": "manual_hypothesis"}, [], "binding_must_be_json_object"),
])
def test_invalid_requests_rejected_before_spawning(kind, value, binding, reason):
    service = AAConditionalAnalysis()
    with pytest.raises(ValueError, match=reason):
        service.start(kind, value, binding=binding)
    assert service.status()["status"] == "IDLE"
    assert service._process is None


@pytest.mark.parametrize("options", [
    {"timeout_seconds": 0}, {"timeout_seconds": True},
    {"timeout_seconds": float("inf")}, {"max_input_bytes": 0},
    {"max_input_bytes": 200001}, {"max_input_bytes": True},
])
def test_limits_cannot_be_disabled(options):
    with pytest.raises(ValueError):
        AAConditionalAnalysis(**options)


@pytest.mark.parametrize("forged_authority", [False, True])
def test_result_arriving_between_poll_and_child_exit_is_drained_and_validated(
        forged_authority):
    envelope = {"status": "COMPLETE", "error": None, "result": {
        "status": "COMPLETE_CONDITIONAL", "strategy_eligible": forged_authority,
        "advice_emitted": False}}

    class Receiver:
        queued = False
        reads = 0
        closed = False

        def __init__(self):
            self.poll_timeouts = []

        def poll(self, timeout=0):
            self.poll_timeouts.append(timeout)
            return self.queued

        def recv_bytes(self, maxlength):
            assert maxlength == 2_000_000
            self.reads += 1
            return json.dumps(envelope).encode()

        def close(self):
            self.closed = True

    receiver = Receiver()

    class ExitedProcess:
        def is_alive(self):
            # The first timed poll has already returned false; then the child
            # sends its result and exits before the watcher checks liveness.
            receiver.queued = True
            return False

        def join(self, timeout):
            pass

    service = AAConditionalAnalysis()
    service._report.update(status="RUNNING", job_id="exit-during-poll")
    service._watch("exit-during-poll", ExitedProcess(), receiver, time.monotonic() + 3)
    report = service.status()
    assert receiver.poll_timeouts == [0.025, 0]
    assert receiver.reads == 1 and receiver.closed
    if forged_authority:
        assert report["status"] == "ERROR" and report["result"] is None
        assert "protocol_error" in report["error"]
    else:
        assert report["status"] == "COMPLETE"
        assert report["result"] == envelope["result"]
    assert report["strategy_eligible"] is False and report["advice_emitted"] is False
