"""AA worker ownership and stale/late-result isolation, without real capture."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from poker_engine.desktop.aa_session import AARecognitionSession


def wait_until(predicate):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("worker did not reach expected state")


class Source:
    def __init__(self):
        self.closed = threading.Event()
        self.seq = 90

    def read(self):
        self.seq += 7
        return {"image": np.zeros((8, 8, 3), dtype=np.uint8),
                "source_frame": self.seq, "pts_seconds": self.seq / 30,
                "source_kind": "fake"}

    def close(self):
        self.closed.set()


class Reader:
    def __init__(self):
        self.calls = []

    def read(self, image, sequence, sample):
        self.calls.append((sequence, sample))
        return {"hero": None, "strategy_eligible": False}


def test_session_instances_do_not_reuse_generation_namespace():
    one = AARecognitionSession(lambda _: Source(), Reader)
    two = AARecognitionSession(lambda _: Source(), Reader)
    assert one.snapshot()["instance_id"] != two.snapshot()["instance_id"]
    first = one.snapshot()["instance_id"]
    one.stop()
    assert one.snapshot()["instance_id"] == first


def test_explicit_start_shared_worker_and_restart():
    sources = []
    reader = Reader()

    def create(options):
        sources.append(Source())
        return sources[-1]

    session = AARecognitionSession(create, lambda: reader, interval_seconds=.01)
    assert session.snapshot()["status"] == "STOPPED"
    assert not sources
    session.start({})
    try:
        wait_until(lambda: len(reader.calls) >= 2)
        generation = session.snapshot()["generation"]
        with ThreadPoolExecutor(max_workers=8) as clients:
            snapshots = list(clients.map(lambda _: session.start({}), range(8)))
        assert all(item["generation"] == generation for item in snapshots)
        assert len(sources) == 1
        assert [call[0] for call in reader.calls[:2]] == [0, 1]
        assert reader.calls[0][1]["source_frame"] == 97
        assert len(reader.calls[0][1]["sha256"]) == 64
        assert session.preview().startswith(b"\xff\xd8")
        stopped = session.stop()
        assert stopped["payload"] is None and session.preview() is None
        wait_until(lambda: sources[0].closed.is_set())
        wait_until(lambda: session.snapshot()["status"] == "STOPPED")
        session.start({})
        wait_until(lambda: len(sources) == 2)
    finally:
        session.stop()
        wait_until(lambda: sources[-1].closed.is_set())


def test_source_provenance_shared_with_other_observers_and_retained_on_stop():
    source = Source()
    session = AARecognitionSession(lambda _: source, Reader, interval_seconds=.01)
    options = {"mode": "fake", "device_index": 3}
    session.start(options)
    try:
        wait_until(lambda: session.snapshot()["payload"] is not None)
        options["mode"] = "changed"
        first_observer = session.snapshot()
        assert first_observer["source_kind"] == "fake"
        assert first_observer["pts_seconds"] > 0
        first_observer["source_options"]["mode"] = "changed"
        assert session.snapshot()["source_options"]["mode"] == "fake"
        assert session.stop()["source_kind"] == "fake"
        assert session.snapshot()["pts_seconds"] is None
    finally:
        session.stop()
        wait_until(lambda: source.closed.is_set())


def test_source_cannot_mislabel_replay_as_capture():
    source = Source()
    session = AARecognitionSession(lambda _: source, Reader)
    session.start({"mode": "capture-card"})
    wait_until(lambda: source.closed.is_set())
    result = session.snapshot()
    assert result["status"] == "ERROR"
    assert "does not match" in result["error"]
    assert result["payload"] is None


def test_release_failure_after_explicit_stop_is_not_hidden():
    source = Source()

    def fail_close():
        source.closed.set()
        raise RuntimeError("device release failed")

    source.close = fail_close
    session = AARecognitionSession(lambda _: source, Reader, interval_seconds=.01)
    session.start({})
    wait_until(lambda: session.snapshot()["payload"] is not None)
    session.stop()
    wait_until(lambda: session.snapshot()["status"] == "ERROR")
    assert "device release failed" in session.snapshot()["error"]
    assert session.snapshot()["payload"] is None


@pytest.mark.parametrize("failure", ["source", "reader", "ended"])
def test_errors_and_exhaustion_clear_and_release(failure):
    source = Source()
    reader = Reader()
    session = AARecognitionSession(lambda _: source, lambda: reader,
                                   interval_seconds=.02)
    session.start({})
    wait_until(lambda: session.snapshot()["payload"] is not None)

    def fail(*args):
        raise RuntimeError("intentional failure")

    if failure == "reader":
        reader.read = fail
    else:
        source.read = (lambda: None) if failure == "ended" else fail
    wait_until(lambda: source.closed.is_set())
    result = session.snapshot()
    assert result["status"] == ("ENDED" if failure == "ended" else "ERROR")
    assert result["payload"] is None and result["source_frame"] is None
    assert session.preview() is None


@pytest.mark.parametrize("expire", [False, True])
def test_late_result_cannot_publish_after_stop_or_stale(expire):
    source = Source()
    reader = Reader()
    entered = threading.Event()
    release = threading.Event()
    original = reader.read

    def block(image, sequence, sample):
        if sequence == 1:
            entered.set()
            release.wait(2)
        return original(image, sequence, sample)

    reader.read = block
    session = AARecognitionSession(lambda _: source, lambda: reader,
                                   stale_after=.03, interval_seconds=.005)
    session.start({})
    try:
        assert entered.wait(1)
        if expire:
            time.sleep(.04)
            assert session.snapshot()["status"] == "STALE"
        else:
            session.stop()
        assert session.snapshot()["payload"] is None
        assert session.preview() is None
        assert session.start({})["status"] == "STOPPING"
    finally:
        release.set()
        wait_until(lambda: source.closed.is_set())
    assert session.snapshot()["payload"] is None
    assert session.snapshot()["status"] == "STOPPED"


def test_late_first_recognition_cannot_relabel_old_source_as_fresh():
    source = Source()
    read = source.read

    def timed_read():
        stamp = time.monotonic()
        return {**read(), "host_source_started_at": stamp,
                "host_source_received_at": stamp}

    source.read = timed_read
    reader = Reader()
    entered, release = threading.Event(), threading.Event()

    def slow_read(image, sequence, sample):
        entered.set()
        release.wait(1)
        return {"current_actor": 4}

    reader.read = slow_read
    session = AARecognitionSession(lambda _: source, lambda: reader, stale_after=.03)
    session.start({})
    try:
        assert entered.wait(1)
        time.sleep(.04)
        release.set()
        wait_until(lambda: source.closed.is_set())
        result = session.snapshot()
        assert result["status"] == "STALE"
        assert result["payload"] is None
        assert result["realtime"]["advice"] is None
    finally:
        release.set()
        session.stop()


def test_session_reports_separate_host_timing_without_physical_claim():
    source = Source()
    read = source.read

    def timed_read():
        stamp = time.monotonic()
        return {**read(), "host_source_started_at": stamp,
                "host_source_received_at": stamp}

    source.read = timed_read
    session = AARecognitionSession(lambda _: source, Reader)
    session.start({})
    try:
        wait_until(lambda: session.snapshot()["payload"] is not None)
        result = session.snapshot()
        timing = result["timing"]
        assert timing["host_source_received_at"] <= timing["recognition_started_at"]
        assert timing["recognition_started_at"] <= timing["recognition_finished_at"]
        assert timing["recognition_finished_at"] <= timing["published_at"]
        assert timing["source_read_ms"] >= 0 and timing["recognition_ms"] >= 0
        assert timing["physical_source_timestamp"] is None
        assert timing["end_to_end_latency_ms"] is None
        assert result["realtime"]["reason"] == "NO_VERIFIED_TURN_EVIDENCE"
    finally:
        session.stop()
        wait_until(lambda: source.closed.is_set())
