"""Portable test-evidence state transitions; no runtime collector selection."""
from copy import deepcopy
from math import isfinite

from poker_engine.strategy.aa_mccfr import TrainingBudgetExceeded


STATUSES = ("PASS", "FAIL", "ERROR", "INTERRUPTED", "NOT_RUN")


class PrerequisiteMissing(RuntimeError):
    pass


class SyntheticInterrupted(RuntimeError):
    pass


def classify_exception(exc):
    if isinstance(exc, (TrainingBudgetExceeded, SyntheticInterrupted,
                        KeyboardInterrupt, SystemExit)):
        return "INTERRUPTED"
    if isinstance(exc, PrerequisiteMissing):
        return "NOT_RUN"
    return "FAIL" if isinstance(exc, AssertionError) else "ERROR"


def finish(row, status, reason=None):
    if status not in STATUSES:
        raise ValueError("unsupported evidence status")
    row["status"] = status
    if status == "PASS":
        row.pop("reason", None)
    elif reason is not None:
        row["reason"] = reason
    return row


def _validate_planned_lists(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("evidence dictionary keys must be strings")
        for child in value.values():
            _validate_planned_lists(child)
    elif isinstance(value, list):
        seen = set()
        for row in value:
            identity = row.get("id") if isinstance(row, dict) else None
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError("planned lists require rows with nonempty string id")
            if identity in seen:
                raise ValueError("duplicate planned id")
            seen.add(identity)
            _validate_planned_lists(row)
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise ValueError("evidence must have JSON-compatible values")
    elif isinstance(value, float) and not isfinite(value):
        raise ValueError("evidence numbers must be finite")


def _merge_evidence(base, update):
    result = deepcopy(base)
    for key, value in update.items():
        if key == "id" and key in result and result[key] != value:
            raise ValueError("planned id cannot change")
        if isinstance(value, dict):
            if key in result and not isinstance(result[key], dict):
                raise ValueError("evidence container type cannot change")
            result[key] = _merge_evidence(result.get(key, {}), value)
        elif isinstance(value, list):
            if key not in result or not isinstance(result[key], list):
                raise ValueError("list updates require an existing frozen plan")
            patches = {row["id"]: row for row in value}
            known = {row["id"] for row in result[key]}
            if patches.keys() - known:
                raise ValueError("unknown planned id")
            result[key] = [_merge_evidence(row, patches.get(row["id"], {}))
                           for row in result[key]]
        else:
            if isinstance(result.get(key), (dict, list)):
                raise ValueError("evidence container type cannot change")
            result[key] = deepcopy(value)
    return result


def _clear_completed(value):
    if isinstance(value, dict):
        if value.get("status") == "PASS":
            value.pop("reason", None)
        for child in value.values():
            _clear_completed(child)
    elif isinstance(value, list):
        for child in value:
            _clear_completed(child)


def overlay(base, update):
    """Apply partial evidence patches to a frozen plan without dropping rows.

    Every list must contain uniquely identified dict rows. Omitted rows remain
    in base order; unknown/duplicate ids and container replacement are rejected.
    Nested row lists inside dicts are supported, anonymous arrays are not.
    Values must be JSON-compatible and finite. This helper handles planned
    evidence, not arbitrary checkpoint/data-array merges.
    Empty patches preserve existing row identities; new list fields are always
    rejected. PASS reason cleanup still applies to untouched completed rows.
    """
    if not isinstance(base, dict) or not isinstance(update, dict):
        raise ValueError("evidence roots must be dictionaries")
    _validate_planned_lists(base)
    _validate_planned_lists(update)
    result = _merge_evidence(base, update)
    _clear_completed(result)
    return result


def execute_case(row, function):
    finish(row, "INTERRUPTED", "CASE_IN_PROGRESS")
    try:
        function(row)
    except BaseException as exc:
        finish(row, classify_exception(exc), f"{type(exc).__name__}: {exc}")
        if not isinstance(exc, Exception):
            raise
    else:
        finish(row, "PASS")
    return row
