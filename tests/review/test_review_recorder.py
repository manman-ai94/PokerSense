"""Review: the recording path keeps what was recorded and says true things."""

from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient
import numpy as np

from poker_engine.desktop import aa_recorder, aa_server
from poker_engine.desktop.aa_session import AARecognitionSession
from poker_engine.desktop.aa_sources import AACaptureSource

HEADERS = {"X-AA-Live": "1"}


class Recorder:
    def __init__(self):
        self.active = True

    def status(self):
        return {"active": self.active}

    def stop(self, reason="stopped"):
        self.active = False
        return self.status()


class Backend:
    def __init__(self, **options):
        pass

    def release(self):
        pass


class Lock:
    def acquire(self):
        return self

    def release(self):
        pass


def test_a_recording_started_while_the_card_closes_is_still_stopped():
    source = AACaptureSource({"device_index": 0, "api": "AVFOUNDATION"},
                             backend_factory=Backend, device_lock_factory=Lock)
    made = []

    def factory(out, normalization, meta=None):
        # The source closes (idle stop, a device error) while the recorder
        # is being made: close() has looked for a recorder and found none.
        closer = threading.Thread(target=source.close)
        closer.start()
        made.append(closer)
        source.cancel.wait(1)
        time.sleep(0.2)
        recorder = Recorder()
        made.append(recorder)
        return recorder

    source.recorder_factory = factory
    try:
        source.start_recording(Path("never-written"))
    except RuntimeError:
        pass                                      # refusing is fine too
    made[0].join(5)
    recorders = [item for item in made if isinstance(item, Recorder)]
    assert all(not recorder.active for recorder in recorders), (
        "a recorder outlived the closed capture card")


class Recordable:
    def __init__(self):
        self.recording = None
        self.seq = 0

    def read(self):
        self.seq += 1
        return {"image": np.zeros((8, 8, 3), np.uint8), "source_frame": self.seq,
                "pts_seconds": self.seq / 30, "source_kind": "capture-card"}

    def start_recording(self, out):
        self.recording = {"active": True, "folder": Path(out).name}
        return self.recording

    def stop_recording(self, reason="stopped"):
        if self.recording:
            self.recording = {**self.recording, "active": False,
                              "stopped_reason": reason}
        return self.recording

    def recording_status(self):
        return self.recording

    def close(self):
        if self.recording and self.recording["active"]:
            self.stop_recording("source_stopped")


class SlowReader:
    """Recognition of a frame takes a while; ``busy`` is set while the
    second frame is being read."""

    def __init__(self, busy):
        self.busy = busy

    def read(self, image, sequence, sample):
        if sequence == 1:
            self.busy.set()
            time.sleep(0.6)
        return {"hero": None, "strategy_eligible": False}


def test_quitting_the_service_finishes_the_recording_before_the_process_ends(
        tmp_path):
    # Quitting (Ctrl-C) ends the process right after the app's shutdown; the
    # session and recorder threads are daemons. Unless shutdown waits for the
    # recording to be finished, its last segment has no index and there is
    # no recording.json.
    source, busy = Recordable(), threading.Event()
    session = AARecognitionSession(lambda _: source, lambda: SlowReader(busy))
    app = aa_server.create_app(tmp_path / "missing.json", session=session,
                               recordings_dir=tmp_path / "recordings")
    with TestClient(app):
        session.start({"mode": "capture-card"})
        deadline = time.monotonic() + 5
        while session.snapshot()["status"] != "RUNNING":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        session.record(True, tmp_path / "recordings" / "x-live")
        assert busy.wait(5)
    assert source.recording["active"] is False


def test_the_low_space_message_does_not_contradict_itself(tmp_path, monkeypatch):
    class Session:
        def snapshot(self):
            return {"status": "RUNNING", "generation": 0, "payload": None,
                    "source_kind": "capture-card"}

        def preview(self):
            return None

        def stop(self):
            pass

        def record(self, on, out=None):
            raise AssertionError("must not start")

    monkeypatch.setattr(aa_recorder, "free_bytes",
                        lambda path: int(19.6 * aa_recorder.GB))
    app = aa_server.create_app(tmp_path / "missing.json", session=Session(),
                               recordings_dir=tmp_path / "recordings")
    with TestClient(app) as client:
        refused = client.post("/api/recording", json={"on": True}, headers=HEADERS)
    assert refused.status_code == 409
    # 19.6 GB left is not "20 GB left, less than 20 GB".
    assert "只剩 20 GB" not in refused.json()["detail"], refused.json()["detail"]


def test_the_terminal_recorder_does_not_start_with_little_room_left(
        tmp_path, monkeypatch):
    # record-aa-capture.command (tools/record_aa_capture.py) writes to the
    # same folder as the window's button but has no disk guard at all.
    import shutil

    from tools import record_aa_capture

    frame = np.zeros((1080, 1920, 3), np.uint8)
    offered = []

    class Cap:
        def read(self):
            return True, frame

        def release(self):
            pass

    class Writer:
        def __init__(self, out, **options):
            self.seconds = 0.0

        def offer(self, image, seconds):
            offered.append(seconds)

        def close(self):
            pass

    usage = shutil.disk_usage(tmp_path)
    low = type(usage)(usage.total, usage.total - 5 * aa_recorder.GB,
                      5 * aa_recorder.GB)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: low)
    monkeypatch.setattr(aa_recorder, "free_bytes", lambda path: 5 * aa_recorder.GB)
    monkeypatch.setattr(record_aa_capture, "open_device",
                        lambda index, api: (Cap(), frame))
    monkeypatch.setattr(record_aa_capture, "SegmentWriter", Writer)
    try:
        record_aa_capture.main(["--minutes", "0.002", "--out-root", str(tmp_path)])
    except SystemExit:
        pass
    assert offered == [], "recorded with 5 GB free"
