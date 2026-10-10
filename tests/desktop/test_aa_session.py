"""AA worker ownership and stale/late-result isolation, without real capture."""

import json
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


def test_late_result_cannot_publish_after_stop():
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
        session.stop()
        assert session.snapshot()["payload"] is None
        assert session.preview() is None
        assert session.start({})["status"] == "STOPPING"
    finally:
        release.set()
        wait_until(lambda: source.closed.is_set())
    assert session.snapshot()["payload"] is None
    assert session.snapshot()["status"] == "STOPPED"


class TimedSource(Source):
    """Frames stamped when read; the first ``old`` ones as if read long ago."""

    def __init__(self, old=0):
        super().__init__()
        self.old = old

    def read(self):
        record = super().read()
        stamp = time.monotonic() - (10 if self.old > 0 else 0)
        self.old -= 1
        return {**record, "host_source_started_at": stamp,
                "host_source_received_at": stamp}


def test_a_stall_clears_the_table_and_the_next_frame_in_time_shows_again():
    source = TimedSource()
    reader = Reader()
    entered, release = threading.Event(), threading.Event()
    original = reader.read

    def stall(image, sequence, sample):
        if sequence == 1:        # e.g. the advice working out a big pot
            entered.set()
            release.wait(2)
        return {**original(image, sequence, sample), "sequence": sequence}

    reader.read = stall
    session = AARecognitionSession(lambda _: source, lambda: reader,
                                   stale_after=.03, interval_seconds=.005)
    session.start({})
    try:
        assert entered.wait(1)
        generation = session.snapshot()["generation"]
        time.sleep(.04)
        stale = session.snapshot()
        assert stale["status"] == "STALE" and stale["error"] is None
        assert stale["payload"] is None and session.preview() is None
        assert stale["realtime"]["advice"] is None
        # Still running: "start" does not open the source a second time.
        assert session.start({})["status"] == "STALE"
        release.set()
        seen = []

        def shown():
            result = session.snapshot()
            seen.append(result["payload"])
            return result["status"] == "RUNNING" and result["payload"] is not None
        wait_until(shown)
        # The frame that came back late was never shown.
        assert all(payload is None or payload["sequence"] >= 2 for payload in seen)
        assert session.snapshot()["generation"] == generation
        assert not source.closed.is_set()
        assert session.preview().startswith(b"\xff\xd8")
    finally:
        release.set()
        session.stop()
    wait_until(lambda: source.closed.is_set())
    assert session.snapshot()["status"] == "STOPPED"


def test_a_late_first_result_is_never_shown_as_fresh():
    source = TimedSource(old=2)
    reader = Reader()
    entered, release = threading.Event(), threading.Event()
    original = reader.read

    def second_waits(image, sequence, sample):
        if sequence == 1:
            entered.set()
            release.wait(1)
        return {**original(image, sequence, sample), "current_actor": 4}

    reader.read = second_waits
    session = AARecognitionSession(lambda _: source, lambda: reader, stale_after=.03)
    session.start({})
    try:
        assert entered.wait(1)
        # Frame 0 was read long ago: published and cleared at once.
        result = session.snapshot()
        assert result["status"] == "STALE"
        assert result["payload"] is None
        assert result["realtime"]["advice"] is None
        release.set()
        wait_until(lambda: session.snapshot()["status"] == "RUNNING")
        result = session.snapshot()
        assert result["sequence"] >= 2 and result["payload"]["current_actor"] == 4
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


def test_table_math_enriches_payload_and_frames_are_logged(tmp_path):
    import json

    source = Source()
    log = tmp_path / "frames.jsonl"
    session = AARecognitionSession(
        lambda _: source, Reader, table_math=lambda payload: {"seen": True},
        frame_log=log)
    session.start({})
    try:
        wait_until(lambda: log.exists() and len(log.read_text().splitlines()) >= 2)
        result = session.snapshot()
        assert result["payload"]["table_math_v1"] == {"seen": True}
        assert result["timing"]["math_ms"] >= 0
    finally:
        session.stop()
        wait_until(lambda: source.closed.is_set())
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [row["processed"] for row in rows[:2]] == [0, 1]
    assert rows[0]["source_frame"] == 97 and rows[0]["source_kind"] == "fake"
    assert rows[0]["fields"]["table_math"] == {"seen": True}
    assert rows[0]["timing"]["recognition_ms"] >= 0


def test_grades_follow_the_advice_and_reset_when_a_source_starts():
    class Grades:
        def __init__(self):
            self.resets, self.seen = 0, []

        def reset(self):
            self.resets += 1

        def __call__(self, payload, frame):
            self.seen.append(payload.get("solver_advice_v1"))
            return {"graded": len(self.seen)}

    grades, sources = Grades(), []

    def create(options):
        sources.append(Source())
        return sources[-1]

    session = AARecognitionSession(
        create, Reader, solver_advice=lambda payload, frame: {"status": "idle"},
        grades=grades)
    for _ in range(2):
        session.start({})
        try:
            wait_until(lambda: (session.snapshot()["payload"] or {}).get("grade_v1"))
        finally:
            session.stop()
            wait_until(lambda: session.snapshot()["status"] == "STOPPED")
    assert grades.resets == 2 and grades.seen[0] == {"status": "idle"}


def test_an_error_in_the_advice_or_the_grading_never_stops_the_window():
    # 10/09: the advice raised on a stack it could not start the table with,
    # and the error ended the session with the hero's buttons on screen.
    def advice(payload, frame):
        raise ValueError("stack must cover ante and align to minimum chip")

    def grades(payload, frame):
        raise RuntimeError("grading failed")

    session = AARecognitionSession(lambda options: Source(), Reader,
                                   solver_advice=advice, grades=grades)
    session.start({})
    try:
        wait_until(lambda: (session.snapshot()["payload"] or {}).get(
            "solver_advice_v1"))
        snapshot = session.snapshot()
        assert snapshot["status"] == "RUNNING"
        assert snapshot["payload"]["solver_advice_v1"]["reason"] == "advice_failed"
        assert snapshot["payload"]["grade_v1"] is None
    finally:
        session.stop()
        wait_until(lambda: session.snapshot()["status"] == "STOPPED")


def test_frame_summary_prefers_current_evidence_and_keeps_legacy_fields():
    from poker_engine.desktop.aa_session import frame_summary

    legacy = {"observed_state_v2": {"street_candidate": None, "participants": {
        "1": {"state": "folded"}}}}
    assert frame_summary(legacy)["street"] is None
    assert frame_summary(legacy)["participants"] == {"1": "folded"}
    current = {**legacy, "street_v1": {"street": "turn"},
               "seat_states_v1": {"seats": {"1": {"state": "active"}}},
               "hero_controls_v1": {"visible": True, "button": "check",
                                    "call_amount": "0"}}
    summary = frame_summary(current)
    assert summary["street"] == "turn" and summary["street_legacy"] is None
    assert summary["participants"] == {"1": "active"}
    assert summary["participants_legacy"] == {"1": "folded"}
    assert summary["hero_controls"]["button"] == "check"
    shown = {"hand_id": "hand_1", "seats": {"2": {"cards": ["As", "Kd"], "frame": 9}},
             "unknown": []}
    assert frame_summary({**current, "shown_cards_v1": shown})["shown_cards"] == shown


def test_frame_summary_keeps_the_rebuilt_hand_compact():
    from poker_engine.desktop.aa_session import frame_summary

    history = {"hand_id": "hand_7", "complete": True, "start": "pot_went_down",
               "dealer": 2, "actions": [
                   {"frame": 9, "street": "flop", "slot": 3, "kind": "raise",
                    "amount": "19", "amount_source": "pot_rise"}]}
    summary = frame_summary({"action_history_v1": history})
    assert summary["actions_v1"] == {
        "hand_id": "hand_7", "complete": True, "start": "pot_went_down", "dealer": 2,
        "actions": [[9, "flop", 3, "raise", "19", "pot_rise"]]}
    assert frame_summary({})["actions_v1"] is None


def test_the_running_source_can_be_recorded_and_its_outcome_stays_after_stop():
    class Recordable(Source):
        def __init__(self):
            super().__init__()
            self.recording = None

        def start_recording(self, out):
            self.recording = {"active": True, "folder": out.name}
            return self.recording

        def stop_recording(self, reason="stopped"):
            self.recording = {**self.recording, "active": False,
                              "stopped_reason": reason}
            return self.recording

        def recording_status(self):
            return self.recording

        def close(self):
            if self.recording and self.recording["active"]:
                self.stop_recording("source_stopped")
            super().close()

    from pathlib import Path

    source = Recordable()
    session = AARecognitionSession(lambda _: source, Reader)
    with pytest.raises(RuntimeError):
        session.record(True, Path("never"))           # nothing running yet
    session.start({})
    try:
        wait_until(lambda: session.snapshot()["status"] == "RUNNING")
        assert session.snapshot()["recording"] is None
        assert session.record(True, Path("20261008-live"))["active"] is True
        assert session.snapshot()["recording"]["folder"] == "20261008-live"
    finally:
        session.stop()
        wait_until(lambda: session.snapshot()["status"] == "STOPPED")
    # Stopping the source ends the recording; the window can still say so.
    assert session.snapshot()["recording"] == {
        "active": False, "folder": "20261008-live", "stopped_reason": "source_stopped"}
    plain = AARecognitionSession(lambda _: Source(), Reader)
    plain.start({})
    try:
        wait_until(lambda: plain.snapshot()["status"] == "RUNNING")
        with pytest.raises(RuntimeError):
            plain.record(True, Path("x"))             # a source with no recorder
    finally:
        plain.stop()


def test_while_recording_the_window_logs_each_frame_next_to_the_video(tmp_path):
    class Recorder:
        def __init__(self, out):
            out.mkdir()
            self.out, self.begin, self.stopping = out, time.monotonic(), False

    class Recording(TimedSource):
        recorder = None

    source = Recording()
    session = AARecognitionSession(lambda _: source, Reader, interval_seconds=.005)
    session.start({})
    try:
        wait_until(lambda: (session.snapshot()["sequence"] or 0) >= 2)
        source.recorder = Recorder(tmp_path / "20261008-live")
        log = source.recorder.out / "frames.jsonl"
        wait_until(lambda: log.is_file() and len(log.read_text().splitlines()) >= 3)
        source.recorder.stopping = True
        time.sleep(.05)
        count = len(log.read_text().splitlines())
        time.sleep(.05)
        assert len(log.read_text().splitlines()) == count   # stopped with it
    finally:
        session.stop()
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows[0]["processed"] >= 2 and "fields" in rows[0]
    assert all(0 <= row["video_seconds"] < 2 for row in rows)
    assert [row["video_seconds"] for row in rows] == sorted(
        row["video_seconds"] for row in rows)


def test_the_session_knows_when_it_last_saw_the_table():
    class TableReader(Reader):
        def read(self, image, sequence, sample):
            return {"hero": None, "strategy_eligible": False,
                    "scene_supported": sequence >= 3}

    session = AARecognitionSession(lambda _: Source(), TableReader)
    assert session.table_seen() is None
    session.start({})
    try:
        wait_until(lambda: (session.snapshot()["sequence"] or 0) >= 1)
        wait_until(lambda: session.table_seen() is not None)
        assert 0 <= session.table_seen() < 2
    finally:
        session.stop()
        wait_until(lambda: session.snapshot()["status"] == "STOPPED")
    assert session.table_seen() is None         # a new source starts over


def test_the_status_says_which_device_the_source_found():
    source = Source()
    read = source.read
    source.read = lambda: {**read(), "source_kind": "capture-card"}
    source.device = {"device_index": 2, "api": "AVFOUNDATION",
                     "device_check": "phone_between_black_bars"}
    session = AARecognitionSession(lambda _: source, Reader, interval_seconds=.01)
    session.start({"mode": "capture-card", "device_index": 0, "find_phone": True})
    try:
        wait_until(lambda: session.snapshot()["payload"] is not None)
        options = session.snapshot()["source_options"]
        assert options == {"mode": "capture-card", "device_index": 2,
                           "find_phone": True, "api": "AVFOUNDATION",
                           "device_check": "phone_between_black_bars"}
    finally:
        session.stop()
        wait_until(lambda: source.closed.is_set())
