"""Regression for P3 exception classification and stale PASS annotations."""
from copy import deepcopy

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
              "probes": [{"id": "done", "status": "PASS", "reason": "NOT_REACHED"}]}
    recovered = overlay(initial, update)
    assert "reason" not in recovered
    assert recovered["nested"]["warmup"] == {"status": "PASS"}
    assert recovered["probes"] == [{"id": "done", "status": "PASS"},
                                   {"id": "later", "status": "NOT_RUN",
                                    "reason": "NOT_REACHED"}]
    assert initial["status"] == "NOT_RUN"  # Original evidence is immutable.
    record_property("synthetic_nodes", 0)


def _row(identity):
    return {"id": identity, "status": "NOT_RUN", "reason": "NOT_REACHED"}


def test_recovery_orders_patches_by_frozen_identity_and_keeps_empty_patch(
        record_property):
    initial = {"probes": [_row("first"), _row("middle"), _row("last")]}
    update = {"probes": [{"id": "last", "status": "FAIL", "reason": "rejected"},
                         {"id": "first", "status": "PASS"}]}
    saved_initial, saved_update = deepcopy(initial), deepcopy(update)
    actual = overlay(initial, update)
    assert actual["probes"] == [{"id": "first", "status": "PASS"},
                                _row("middle"),
                                {"id": "last", "status": "FAIL",
                                 "reason": "rejected"}]
    assert overlay(initial, {"probes": []}) == initial
    assert initial == saved_initial and update == saved_update
    actual["probes"][1]["reason"] = "changed copy"
    assert initial == saved_initial
    record_property("synthetic_nodes", 0)


def test_recovery_nested_plans_have_local_identity_scopes(record_property):
    initial = {"batches": [{"id": "A", "nested": {"probes": [
        _row("done"), _row("later")]}}, {"id": "B", "nested": {"probes": [
            _row("done"), _row("later")]}}]}
    update = {"batches": [{"id": "A", "nested": {"probes": [
        {"id": "done", "status": "PASS"}]}}]}
    actual = overlay(initial, update)
    assert actual["batches"][0]["nested"]["probes"] == [
        {"id": "done", "status": "PASS"}, _row("later")]
    assert actual["batches"][1] == initial["batches"][1]
    assert len(actual["batches"]) == 2
    assert sum(len(row["nested"]["probes"]) for row in actual["batches"]) == 4
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("side", ("base", "update"))
@pytest.mark.parametrize("nested", (False, True))
def test_recovery_rejects_duplicate_identity_without_mutating_inputs(
        side, nested, record_property):
    base = {"probes": [_row("done"), _row("later")]}
    update = {"probes": [{"id": "done", "status": "PASS"}]}
    invalid = {"probes": [_row("done"), _row("done")]}
    if side == "base":
        base = invalid
        update = {}  # Untouched malformed plans must still be rejected.
    else:
        update = invalid
    if nested:
        base, update = {"nested": base}, {"nested": update}
    saved_base, saved_update = deepcopy(base), deepcopy(update)
    with pytest.raises(ValueError, match="duplicate planned id"):
        overlay(base, update)
    assert base == saved_base and update == saved_update
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("patch", (
    {"probes": [{"id": "unplanned", "status": "PASS"}]},
    {"new_plan": [_row("unplanned")]},
    {"new_plan": []},
    {"probes": None},
    {"probes": {}},
    {"probes": [{"id": "done", "nested": {"status": "PASS"}}]},
))
def test_recovery_rejects_plan_extensions_and_container_replacement(
        patch, record_property):
    base = {"probes": [dict(_row("done"), nested=1), _row("later")]}
    saved_base, saved_patch = deepcopy(base), deepcopy(patch)
    with pytest.raises(ValueError):
        overlay(base, patch)
    assert base == saved_base and patch == saved_patch
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("unsupported", (
    [1, 2], [[_row("done")]], [{}], [{"id": ""}], [{"id": " "}], [{"id": 1}],
    [{"id": True}], [{"id": None}], [_row("done"), 1],
))
def test_recovery_rejects_anonymous_and_bare_nested_arrays(
        unsupported, record_property):
    with pytest.raises(ValueError, match="nonempty string id"):
        overlay({"probes": unsupported}, {})
    with pytest.raises(ValueError, match="nonempty string id"):
        overlay({"probes": [_row("done")]}, {"probes": unsupported})
    record_property("synthetic_nodes", 0)


def test_recovery_rejects_identity_change_outside_lists(record_property):
    with pytest.raises(ValueError, match="planned id cannot change"):
        overlay({"id": "frozen"}, {"id": "other"})
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("initial, update", (
    ({"value": 1}, {"value": {}}),
    ({"value": 1}, {"value": []}),
    ({"value": {"probes": [_row("done"), _row("later")]}}, {"value": None}),
    ({"value": {"probes": [_row("done"), _row("later")]}}, {"value": []}),
    ({"value": [_row("done")]}, {"value": None}),
    ({"value": [_row("done")]}, {"value": {}}),
))
def test_recovery_rejects_structural_changes_symmetrically(
        initial, update, record_property):
    with pytest.raises(ValueError):
        overlay(initial, update)
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("initial, update", (
    ({"probes": []}, {"probes": [_row("unplanned")]}),
    ({}, {"new": {"probes": [_row("unplanned")]}}),
    ({"outer": [_row("known")]}, {"outer": [{"id": "known", "nested": {
        "probes": [_row("unplanned")]}}]}),
))
def test_recovery_rejects_nested_and_empty_plan_extensions(
        initial, update, record_property):
    with pytest.raises(ValueError):
        overlay(initial, update)
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("invalid", ((1, 2), {1}, float("nan"), float("inf"), {1: 2}))
def test_recovery_rejects_non_json_or_nonfinite_shapes(invalid, record_property):
    with pytest.raises(ValueError):
        overlay({"untouched": invalid}, {})
    with pytest.raises(ValueError):
        overlay({}, {"new": invalid})
    record_property("synthetic_nodes", 0)


@pytest.mark.parametrize("status", ("FAIL", "ERROR", "INTERRUPTED", "NOT_RUN"))
def test_nonpass_terminal_reasons_are_preserved(status, record_property):
    row = {"id": "remaining", "status": "NOT_RUN", "reason": "NOT_REACHED"}
    finish(row, status, "frozen failure reason")
    assert row["reason"] == "frozen failure reason"
    assert overlay({"reason": "initial"}, row)["reason"] == "frozen failure reason"
    record_property("synthetic_nodes", 0)
