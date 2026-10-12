"""Event-driven capture loop: pacing semantics and fault recovery.

These tests pin the two behaviours the realtime migration depends on:

1. ``interval_seconds`` is a **minimum** period. The loop sleeps only the
   remainder after work already done — previously a fixed 1.0s sleep was
   added on top of every step, which alone capped the pipeline near 0.8fps.
2. Device-level faults (``LiveCaptureError``) are transient and recover with
   backoff; programming/config faults are not retried.

``asyncio.sleep`` is recorded rather than performed and the loop's clock is a
stand-in, so the pacing assertions are about *what the loop asked for* instead
of wall-clock timing.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

sys.path.insert(0, "tools")
sys.path.insert(0, "tests")
sys.path.insert(0, "tests/realtime")

import run_benchmark  # noqa: E402
from tools.gen_wepoker_dataset import render_table  # noqa: E402

from orchestrator.fixtures import initial_state  # noqa: E402
from profiles import relaxed_confidence_gate  # noqa: E402

from poker_engine.desktop import live  # noqa: E402
from poker_engine.desktop.live import LiveCaptureError, LiveStreamHealth  # noqa: E402
from poker_engine.memory.hand_memory import InMemoryHandMemory  # noqa: E402
from poker_engine.orchestrator import ApplicationOrchestrator  # noqa: E402
from poker_engine.realtime import RealtimePipeline  # noqa: E402
from poker_engine.state_engine import StateEngine  # noqa: E402


_SCENARIOS = (
    ([], ["AS", "KD"], "10", "5", ("100", "200", "300"), ("CHECK", "CALL")),
    (["QH", "JD", "TC"], ["AS", "KD"], "25", "10", ("100", "200", "300"),
     ("CHECK", "BET")),
    (["QH", "JD", "TC", "2S"], ["AS", "KD"], "50", "20",
     ("150", "250", "350"), ("BET", "CALL")),
)


def _frames(count=3):
    return tuple(
        run_benchmark._frame(
            render_table(
                tuple(bc), tuple(hc), pot, bet, stacks, actions
            ),
            seq,
        )
        for seq, (bc, hc, pot, bet, stacks, actions) in enumerate(
            _SCENARIOS[:count]
        )
    )


class _Clock:
    """Stands in for ``live.time``: monotonic seconds that move only when a
    source pull is charged to them, so recognition's real cost does not count."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


class _SlowSource:
    """Yield synthetic frames, costing ``delay`` seconds per pull on ``clock``.

    Stands in for a real capture device, whose pull cost is the dominant term
    in the frame period.
    """

    def __init__(self, frames, delay=0.0, clock=None):
        self._frames = list(frames)
        self._delay = delay
        self._clock = clock
        self._index = 0
        self.calls = 0

    def next_frame(self):
        import time

        self.calls += 1
        if self._delay and self._clock is not None:
            self._clock.now += self._delay
        elif self._delay:
            time.sleep(self._delay)
        if self._index >= len(self._frames):
            return None
        frame = self._frames[self._index]
        self._index += 1
        return frame


class _FlakySource:
    """Fail ``failures`` times with a transient device fault, then behave."""

    def __init__(self, frames, failures=0, error=None):
        self._inner = _SlowSource(frames)
        self._failures = failures
        self._error = error or LiveCaptureError("device offline")
        self.calls = 0

    def next_frame(self):
        self.calls += 1
        if self._failures > 0:
            self._failures -= 1
            raise self._error
        return self._inner.next_frame()


def _pipeline(source):
    orch = ApplicationOrchestrator(
        StateEngine(),
        InMemoryHandMemory(),
        confidence_gate=relaxed_confidence_gate(),
    )
    orch.start_hand(initial_state(hand_id="h1"))
    return RealtimePipeline(
        frame_source=source,
        vision=run_benchmark.build_engine(),
        table_map=run_benchmark.table_map(),
        orchestrator=orch,
        equity_trials=200,
        equity_seed=7,
    )


def _record_sleeps(monkeypatch):
    """Replace asyncio.sleep with a recorder that never actually waits."""
    recorded = []
    real_sleep = asyncio.sleep  # captured before the patch, or we recurse

    async def fake_sleep(delay):
        recorded.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return recorded


async def _collect(stream, limit=None):
    out = []
    async for frame in stream:
        out.append(frame)
        if limit is not None and len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# Pacing
# --------------------------------------------------------------------------


def test_zero_interval_adds_no_artificial_sleep(monkeypatch):
    """The old fixed 1.0s sleep per frame is gone entirely."""
    sleeps = _record_sleeps(monkeypatch)
    monkeypatch.setattr(
        live, "build_pipeline", lambda *a, **k: _pipeline(_SlowSource(_frames()))
    )

    async def run():
        return await _collect(live.live_analysis_stream(interval_seconds=0.0))

    frames = asyncio.run(run())
    assert len(frames) >= 1
    assert sleeps == [], f"expected no pacing sleep, got {sleeps}"


def test_interval_is_a_minimum_period_not_a_fixed_sleep(monkeypatch):
    """Work already done is credited: sleep is only the remainder."""
    sleeps = _record_sleeps(monkeypatch)
    clock = _Clock()
    monkeypatch.setattr(live, "time", clock)
    monkeypatch.setattr(
        live,
        "build_pipeline",
        lambda *a, **k: _pipeline(_SlowSource(_frames(), delay=0.20, clock=clock)),
    )

    async def run():
        return await _collect(
            live.live_analysis_stream(interval_seconds=2.0), limit=3
        )

    frames = asyncio.run(run())
    assert len(frames) == 3
    assert sleeps, "expected pacing sleeps to be recorded"
    # A step whose source pull costs 0.20s leaves exactly the 1.80s remainder
    # of a 2.0s minimum period; a fixed 2.0s sleep fails this contract.
    assert sleeps == [pytest.approx(1.80)] * len(sleeps), (
        f"sleeps {sleeps} look like a fixed period rather than a remainder")


def test_interval_still_caps_the_rate_when_steps_are_fast(monkeypatch):
    """A minimum period is still honoured when the step costs nothing."""
    sleeps = _record_sleeps(monkeypatch)
    monkeypatch.setattr(live, "time", _Clock())
    monkeypatch.setattr(
        live, "build_pipeline", lambda *a, **k: _pipeline(_SlowSource(_frames()))
    )

    async def run():
        return await _collect(
            live.live_analysis_stream(interval_seconds=0.20), limit=3
        )

    frames = asyncio.run(run())
    assert len(frames) == 3
    assert sleeps, "expected the loop to pace itself"
    # A step that costs nothing waits out the whole period, never more.
    assert sleeps == [pytest.approx(0.20)] * len(sleeps)


def test_interval_rejects_negative_or_non_numeric(monkeypatch):
    monkeypatch.setattr(
        live, "build_pipeline", lambda *a, **k: _pipeline(_SlowSource(_frames()))
    )

    async def run(interval):
        return await _collect(
            live.live_analysis_stream(interval_seconds=interval), limit=1
        )

    with pytest.raises(ValueError, match="interval_seconds must be >= 0"):
        asyncio.run(run(-1.0))
    with pytest.raises(TypeError, match="interval_seconds must be a number"):
        asyncio.run(run("fast"))


# --------------------------------------------------------------------------
# Fault handling
# --------------------------------------------------------------------------


def test_transient_device_fault_recovers_instead_of_killing_stream(monkeypatch):
    sleeps = _record_sleeps(monkeypatch)
    source = _FlakySource(_frames(), failures=2)
    monkeypatch.setattr(
        live, "build_pipeline", lambda *a, **k: _pipeline(source)
    )

    async def run():
        return await _collect(
            live.live_analysis_stream(
                interval_seconds=0.0, backoff_initial_seconds=0.0
            ),
            limit=2,
        )

    frames = asyncio.run(run())
    assert len(frames) == 2, "stream should survive transient capture faults"
    # 2 failures + 2 successful pulls
    assert source.calls == 4
    assert sleeps == [0.0, 0.0], "backoff should be requested per failure"


def test_health_hook_reports_each_failure_and_clears_on_recovery(monkeypatch):
    _record_sleeps(monkeypatch)
    source = _FlakySource(_frames(), failures=3)
    monkeypatch.setattr(
        live, "build_pipeline", lambda *a, **k: _pipeline(source)
    )
    notices = []

    async def run():
        return await _collect(
            live.live_analysis_stream(
                interval_seconds=0.0,
                backoff_initial_seconds=0.0,
                on_health=notices.append,
            ),
            limit=1,
        )

    asyncio.run(run())
    assert len(notices) == 3
    assert [n.consecutive_failures for n in notices] == [1, 2, 3]
    assert all(n.degraded for n in notices)
    assert notices[-1].total_failures == 3


def test_exceeding_max_consecutive_failures_raises(monkeypatch):
    _record_sleeps(monkeypatch)
    # Fail forever: the device is really gone, not blipping.
    source = _FlakySource(_frames(), failures=99)
    monkeypatch.setattr(
        live, "build_pipeline", lambda *a, **k: _pipeline(source)
    )

    async def run():
        return await _collect(
            live.live_analysis_stream(
                interval_seconds=0.0,
                max_consecutive_failures=3,
                backoff_initial_seconds=0.0,
            ),
            limit=1,
        )

    with pytest.raises(LiveCaptureError, match="consecutive failures"):
        asyncio.run(run())


def test_midstream_capture_fault_emits_unavailable_frame_before_retry(monkeypatch):
    _record_sleeps(monkeypatch)
    frames = _frames()

    class Interrupted:
        def __init__(self):
            self.count = 0

        def next_frame(self):
            self.count += 1
            if self.count == 1:
                return frames[0]
            if self.count == 2:
                raise LiveCaptureError("injected disconnection")
            return frames[1] if self.count == 3 else None

    pipe = _pipeline(Interrupted())
    monkeypatch.setattr(live, "build_pipeline", lambda *a, **k: pipe)

    async def run():
        return await _collect(live.live_analysis_stream(
            interval_seconds=0, backoff_initial_seconds=0), limit=3)

    normal, unavailable, resumed = asyncio.run(run())
    assert unavailable.analysis.frame_seq == normal.analysis.frame_seq
    assert unavailable.advice is None
    assert unavailable.advice_unavailable_reason == "capture_unavailable"
    assert unavailable.analysis.equity.unavailable_reason == "capture_unavailable"
    assert all(status == "unknown" for _, status
               in unavailable.analysis.confidence.field_status)
    assert resumed.analysis.frame_seq > normal.analysis.frame_seq


def test_programming_fault_is_not_retried(monkeypatch):
    """A bug is not a device fault — retrying it would only hide it."""
    _record_sleeps(monkeypatch)

    class Broken:
        def step(self):
            raise RuntimeError("desktop capture failed")

        def current_state(self):
            raise AssertionError("must not be reached")

        def action_history(self):
            raise AssertionError("must not be reached")

    monkeypatch.setattr(
        live, "build_pipeline", lambda *a, **k: Broken()
    )

    async def run():
        return await _collect(live.live_analysis_stream(), limit=1)

    with pytest.raises(
        LiveCaptureError, match="capture engine failed: desktop capture failed"
    ):
        asyncio.run(run())


def test_exhausted_source_stops_cleanly_and_reports_it(monkeypatch):
    _record_sleeps(monkeypatch)
    monkeypatch.setattr(
        live, "build_pipeline", lambda *a, **k: _pipeline(_SlowSource(_frames()))
    )
    notices = []

    async def run():
        return await _collect(
            live.live_analysis_stream(
                interval_seconds=0.0, on_health=notices.append
            )
        )

    frames = asyncio.run(run())
    assert len(frames) == 3
    assert notices, "exhaustion should be reported"
    assert notices[-1].exhausted is True
    assert notices[-1].consecutive_failures == 0


# --------------------------------------------------------------------------
# Health value object
# --------------------------------------------------------------------------


def test_live_stream_health_validates_its_fields():
    with pytest.raises(ValueError, match="consecutive_failures must be >= 0"):
        LiveStreamHealth(
            consecutive_failures=-1, total_failures=0, backoff_seconds=0.0
        )
    with pytest.raises(TypeError, match="exhausted must be a bool"):
        LiveStreamHealth(
            consecutive_failures=0,
            total_failures=0,
            backoff_seconds=0.0,
            exhausted="yes",
        )
    with pytest.raises(ValueError, match="backoff_seconds must be >= 0"):
        LiveStreamHealth(
            consecutive_failures=0, total_failures=0, backoff_seconds=-0.1
        )


def test_live_stream_health_degraded_only_while_failing():
    healthy = LiveStreamHealth(
        consecutive_failures=0, total_failures=5, backoff_seconds=0.0
    )
    assert healthy.degraded is False
    assert healthy.total_failures == 5, "history survives recovery"
    failing = LiveStreamHealth(
        consecutive_failures=2, total_failures=5, backoff_seconds=1.0
    )
    assert failing.degraded is True
