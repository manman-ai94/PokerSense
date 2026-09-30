"""Portable test-evidence state transitions; no runtime collector selection."""
from copy import deepcopy

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


def overlay(base, update):
    """Recover nested rows while retaining all unexecuted planned identities."""
    result = deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = overlay(result[key], value)
        else:
            result[key] = deepcopy(value)
    if result.get("status") == "PASS":
        result.pop("reason", None)
    # Full list snapshots can carry explicitly completed rows with stale reasons.

    def clear_completed(value):
        if isinstance(value, dict):
            if value.get("status") == "PASS":
                value.pop("reason", None)
            for child in value.values():
                clear_completed(child)
        elif isinstance(value, list):
            for child in value:
                clear_completed(child)
    clear_completed(result)
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
