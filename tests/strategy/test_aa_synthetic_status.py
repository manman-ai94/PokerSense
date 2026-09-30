"""Regression for P3 exception classification and stale PASS annotations."""
import pytest

from poker_engine.strategy.aa_mccfr import TrainingBudgetExceeded
from tests.strategy.aa_synthetic_status import (
    PrerequisiteMissing, SyntheticInterrupted, execute_case, finish, overlay,
)


@pytest.mark.parametrize("exc, expected", (
    (AssertionError("transaction invariant"), "FAIL"),
    (AssertionError("export action menu"), "FAIL"),
    (RuntimeError("infrastructure"), "ERROR"),
    (PrerequisiteMissing("missing input"), "NOT_RUN"),
    (SyntheticInterrupted("outer interruption"), "INTERRUPTED"),
    (TrainingBudgetExceeded("node cap"), "INTERRUPTED"),
))
def test_case_executor_keeps_contract_failures_distinct(exc, expected, record_property):
    def failing(row):
        row["partial"] = {"committed_mass": 66, "staged_mass": 3}
        raise exc
    row = execute_case({"id": "public-negative", "status": "NOT_RUN",
                        "reason": "NOT_REACHED"}, failing)
    assert row["status"] == expected
    assert row["reason"] == f"{type(exc).__name__}: {exc}"
    assert row["partial"] == {"committed_mass": 66, "staged_mass": 3}
    record_property("synthetic_nodes", 0)


def test_success_clears_initial_reason(record_property):
    row = execute_case({"status": "NOT_RUN", "reason": "NOT_REACHED"},
                       lambda evidence: evidence.update(value=14))
    assert row == {"status": "PASS", "value": 14}
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("exc", (KeyboardInterrupt("stop"), SystemExit("stop")))
def test_user_interrupt_preserves_partial_evidence_and_propagates(exc, record_property):
    row = {"status": "NOT_RUN", "reason": "NOT_REACHED"}

    def interrupted(evidence):
        evidence["partial"] = {"old_mass": 66}
        raise exc

    with pytest.raises(type(exc), match="stop"):
        execute_case(row, interrupted)
    assert row["status"] == "INTERRUPTED"
    assert row["reason"] == f"{type(exc).__name__}: {exc}"
    assert row["partial"] == {"old_mass": 66}
    record_property("synthetic_nodes", 0)


def test_recovery_clears_reason_but_keeps_unexecuted_rows(record_property):
    initial = {"status": "NOT_RUN", "reason": "NOT_REACHED", "nested": {
        "warmup": {"status": "NOT_RUN", "reason": "NOT_REACHED"}}, "probes": [
            {"id": "done", "status": "NOT_RUN", "reason": "NOT_REACHED"},
            {"id": "later", "status": "NOT_RUN", "reason": "NOT_REACHED"}]}
    update = {"status": "PASS", "nested": {"warmup": {"status": "PASS"}},
              "probes": [{"id": "done", "status": "PASS", "reason": "NOT_REACHED"},
                         {"id": "later", "status": "NOT_RUN",
                          "reason": "NOT_REACHED"}]}
    recovered = overlay(initial, update)
    assert "reason" not in recovered
    assert recovered["nested"]["warmup"] == {"status": "PASS"}
    assert recovered["probes"] == [{"id": "done", "status": "PASS"},
                                   {"id": "later", "status": "NOT_RUN",
                                    "reason": "NOT_REACHED"}]
    assert initial["status"] == "NOT_RUN"  # Original evidence is immutable.
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("status", ("FAIL", "ERROR", "INTERRUPTED", "NOT_RUN"))
def test_nonpass_terminal_reasons_are_preserved(status, record_property):
    row = {"id": "remaining", "status": "NOT_RUN", "reason": "NOT_REACHED"}
    finish(row, status, "frozen failure reason")
    assert row["reason"] == "frozen failure reason"
    assert overlay({"reason": "initial"}, row)["reason"] == "frozen failure reason"
    record_property("synthetic_nodes", 0)
