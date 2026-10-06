"""Real spawn/process deadline tests with synthetic frozen policies only."""

import time

import pytest

from poker_engine.desktop import aa_policy_worker
from poker_engine.desktop.aa_policy_worker import AAIsolatedPolicyWorker
from poker_engine.desktop.aa_turn_runtime import (
    AATurnWindow, TurnEvidence, TurnIdentity,
)


IDENTITY = TurnIdentity("test-instance", 1, "hand1", "turn1")


def hanging_worker(connection, policy):
    connection.send("READY")
    connection.recv()
    time.sleep(20)


def fields():
    now = time.monotonic()
    evidence = TurnEvidence("synthetic-onset", "verified_onset", now, 10)
    window = AATurnWindow(IDENTITY, evidence, now=now)
    return dict(identity=IDENTITY, state_key="state1", rules_fingerprint="rules1",
                legal_actions=["fold", "call"], window=window, source_at=now,
                is_current=lambda binding: True)


@pytest.fixture
def worker():
    result = AAIsolatedPolicyWorker({"information": {"fold": .25, "call": .75}})
    result.preload()
    try:
        yield result
    finally:
        result.close()


def test_preloaded_map_deterministic_mixture_and_full_binding(worker):
    args = fields()
    results = [worker.lookup("information", **args) for _ in range(6)]
    assert all(item["status"] == "SHADOW_RESULT" for item in results)
    assert len({item["action"] for item in results}) == 1
    assert len({item["request_key"] for item in results}) == 1
    assert all(not item["advice_emitted"] and not item["strategy_eligible"]
               for item in results)
    assert results[0]["binding"]["rules"] == "rules1"
    changed = worker.lookup("information", **{**args, "state_key": "changed"})
    assert changed["request_key"] != results[0]["request_key"]


def test_current_state_rechecked_and_policy_cannot_substitute_illegal_action(worker):
    result = worker.lookup("information", **{**fields(), "is_current": lambda _: False})
    assert result["reason"] == "STATE_CHANGED" and result["action"] is None
    result = worker.lookup("information", **{**fields(), "legal_actions": ["check"]})
    assert result["reason"] == "ILLEGAL_ACTION" and result["action"] is None
    assert worker.lookup("unknown", **fields())["reason"] == "POLICY_COVERAGE_MISS"


def test_deadline_kills_actual_hanging_process_without_restarting(monkeypatch):
    monkeypatch.setattr(aa_policy_worker, "_lookup_worker", hanging_worker)
    worker = AAIsolatedPolicyWorker({"information": {"call": 1.0}})
    worker.preload()
    try:
        started = time.monotonic()
        result = worker.lookup("information", **fields())
        elapsed = time.monotonic() - started
        assert result["reason"] == "COMPUTATION_DEADLINE"
        # Scheduling slack is reported as a test bound, not a production p99.
        assert elapsed < 1.0
        later = worker.lookup("information", **fields())
        assert later["reason"] == "WORKER_NOT_PRELOADED"
        worker._process.join(timeout=1)
        assert not worker._process.is_alive()
    finally:
        worker.close()


def test_no_work_without_preload_or_fresh_source():
    worker = AAIsolatedPolicyWorker({"information": {"call": 1}})
    assert worker.lookup("information", **fields())["reason"] == "WORKER_NOT_PRELOADED"


@pytest.mark.parametrize("policy", [
    {"i": {"call": 2}}, {"i": {"call": -1}},
    {"i": {"call": True}}, {"i": {"call": float("nan")}},
])
def test_invalid_frozen_probabilities_reject_before_spawn(policy):
    with pytest.raises(ValueError):
        AAIsolatedPolicyWorker(policy)
