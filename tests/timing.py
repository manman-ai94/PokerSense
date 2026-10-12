"""Wall-clock budgets for the few tests that guard a real speed requirement.

A shared CI machine stalls now and then (another job, antivirus, a GC pause in
a thread left over from an earlier test): for a second or more nothing in this
process runs. A test that asserts "this took under 0.75 s" then fails although
the code is as fast as ever. 2026-10 CI: 1.7-3.3 s against 0.75 s budgets, a
different test each time.

So a test that has to measure real time:

* is marked ``timing`` (``pytest -m "not timing"`` leaves them out);
* checks correctness in every attempt;
* passes its budget when one of ``ATTEMPTS`` attempts meets it. A stall only
  ever adds time, so the fastest attempt is the code's own speed; code that is
  really too slow misses in every attempt;
* multiplies every budget by ``POKERSENSE_TIMING_SCALE`` (default 1), for a
  machine known to be slower.

Everything that does not need real time (pacing arithmetic, which wait a frame
asks for, protocol checks) uses an injected clock or a budget far from the
point instead, and is not marked.
"""

from __future__ import annotations

import os
import time

import pytest

ATTEMPTS = 3

timing = pytest.mark.timing


def scale():
    value = float(os.environ.get("POKERSENSE_TIMING_SCALE", "1"))
    if not value >= 1:
        raise ValueError("POKERSENSE_TIMING_SCALE must be >= 1")
    return value


def budget(limit):
    """``limit`` (seconds or milliseconds) on this machine."""
    return limit * scale()


def over(name, value, limit):
    """``[]`` when ``value`` is within ``limit``, else one line saying by how much."""
    return [] if value < limit else [f"{name} {value:.3f} >= {limit:.3f}"]


def within_budget(attempt, attempts=ATTEMPTS):
    """Run ``attempt()`` until one returns no overruns; fail if none does.

    ``attempt`` runs the scenario from scratch, asserts its correctness (an
    assertion there fails at once, it is not retried) and returns the budgets it
    missed (``over(...)``), empty when all held.
    """
    missed = []
    for _ in range(attempts):
        overruns = attempt()
        if not overruns:
            return
        missed.append(overruns)
    pytest.fail(f"over budget in all {attempts} attempts: {missed}")


class Stopwatch:
    """Seconds since it was made (``time.perf_counter``)."""

    def __init__(self):
        self.started = time.perf_counter()

    def __call__(self):
        return time.perf_counter() - self.started


__all__ = ["ATTEMPTS", "Stopwatch", "budget", "over", "scale", "timing",
           "within_budget"]
