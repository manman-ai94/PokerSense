"""Synthetic timing evidence; no real source/strategy qualification."""

from dataclasses import replace

import pytest

from poker_engine.desktop.aa_turn_runtime import (
    AATurnWindow, TurnEvidence, TurnIdentity, observation_runtime_status,
)


IDENTITY = TurnIdentity("instance", 1, "hand", "turn")


def window(now=100, remaining=10):
    kind = "verified_onset" if remaining == 10 else "verified_countdown_lower_bound"
    return AATurnWindow(IDENTITY, TurnEvidence("synthetic-proof", kind, now, remaining),
                        now=now)


def check(turn, now, **changes):
    fields = dict(now=now, identity=IDENTITY, source_at=now)
    fields.update(changes)
    return turn.check(**fields)


def test_no_full_window_without_evidence_and_no_midturn_first_result_reset():
    with pytest.raises(ValueError, match="explicit timing"):
        AATurnWindow(IDENTITY, None, now=100)
    turn = window(remaining=6)
    assert turn.deadline == 106
    assert check(turn, 100) == "FIRST_RESULT_DEADLINE"
    assert turn.computation_budget_seconds(
        now=100, identity=IDENTITY, source_at=100) == 0


def test_deadline_no_restart_and_budget_includes_elapsed_stages():
    turn = window()
    assert check(turn, 100.1) == "WITHIN_BUDGET"
    assert turn.computation_budget_seconds(now=101.8, identity=IDENTITY,
                                           source_at=101.7) == pytest.approx(.2)
    turn.tighten(TurnEvidence("retry", "verified_onset", 101.8, 10), now=101.8)
    assert turn.deadline == 110
    assert check(turn, 102) == "FIRST_RESULT_DEADLINE"
    assert check(turn, 103) == "FIRST_RESULT_DEADLINE"


def test_existing_result_and_correction_share_absolute_deadline():
    turn = window()
    assert turn.record_first_result(now=101, identity=IDENTITY,
                                    source_at=100.9) == "WITHIN_BUDGET"
    assert check(turn, 106.99) == "WITHIN_BUDGET"
    assert check(turn, 107) == "OPERATION_RESERVE"
    assert check(turn, 110) == "TURN_EXPIRED"


@pytest.mark.parametrize("identity", [
    replace(IDENTITY, instance_id="new"), replace(IDENTITY, generation=2),
    replace(IDENTITY, hand_id="new"), replace(IDENTITY, turn_id="new"),
])
def test_turn_change_permanently_invalidates(identity):
    turn = window()
    assert check(turn, 100.1, identity=identity) == "TURN_IDENTITY_CHANGED"
    assert check(turn, 100.2) == "TURN_IDENTITY_CHANGED"


def test_source_age_identity_legality_and_clock_checks():
    turn = window()
    assert check(turn, 100.1, source_at=None) == "SOURCE_TIME_UNKNOWN"
    assert check(turn, 100.2, source_at=101) == "SOURCE_TIME_INVALID"
    assert check(turn, 101, source_at=100) == "SOURCE_STALE"
    assert check(turn, 101.1, legal=False) == "ILLEGAL_ACTION"
    assert check(turn, 101.2, state_matches=False) == "STATE_CHANGED"
    assert check(turn, 100.9) == "CLOCK_REGRESSION"


@pytest.mark.parametrize("remaining", [True, -1, 11, float("nan")])
def test_malformed_evidence_rejected(remaining):
    with pytest.raises(ValueError):
        TurnEvidence("proof", "verified_countdown_lower_bound", 100, remaining)


def test_shorter_countdown_can_only_tighten_first_result_cutoff():
    turn = window()
    turn.tighten(TurnEvidence("clock", "verified_countdown_lower_bound", 100.2, 8.8),
                 now=100.2)
    assert turn.deadline == 109
    assert check(turn, 101) == "FIRST_RESULT_DEADLINE"


def test_status_never_trusts_payload_deadline_or_advice_flags():
    result = observation_runtime_status({
        "status": "RUNNING", "generation": 4, "instance_id": "test",
        "timing": {"host_source_started_at": 100},
        "payload": {"turn_id": "fake", "countdown": 10, "current_actor": 4,
                    "strategy_eligible": True, "advice": "raise"}}, now=100.2)
    assert result["reason"] == "NO_VERIFIED_TURN_EVIDENCE"
    assert result["turn_id"] is None and result["advice"] is None
    assert result["physical_source_age_ms"] is None
    assert not result["strategy_eligible"]
    assert not result["advice_emitted"]


def test_source_age_refusal_precedes_timing_evidence_gate():
    result = observation_runtime_status({"status": "RUNNING", "payload": {"a": 1},
                                         "timing": {"host_source_started_at": 100}},
                                        now=102)
    assert result["reason"] == "SOURCE_STALE"
