"""Recording the capture card from the live service, without a real encoder."""

import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from poker_engine.desktop.aa_recorder import (
    FOURCCS, GB, AARecorder, SegmentWriter, check_writer, free_bytes, strip_box,
    WRITER_API)
from poker_engine.desktop.aa_sources import AACaptureSource
from poker_engine.desktop.aa_video_source import AAVideoSource
from poker_engine.perceptual.capture.normalization import NormalizationConfig

AA8 = NormalizationConfig(rotate_degrees=0, source_size=(1920, 1080),
                          crop_after_rotation=(711, 0, 1209, 1080),
                          output_size=(498, 1080), version="aa8-capture-canvas-v1")


class Writer:
    """Keeps what an encoder would get; ``opened=False`` fails to open."""

    made = []

    def __init__(self, path, fps, size, opened=True, backend="FFMPEG"):
        self.path, self.fps, self.size, self.opened = path, fps, size, opened
        self.backend = backend
        self.frames, self.released = [], False
        Writer.made.append(self)

    def isOpened(self):
        return self.opened

    def write(self, frame):
        self.frames.append(frame.copy())

    def getBackendName(self):
        return self.backend

    def release(self):
        self.released = True


@pytest.fixture(autouse=True)
def fresh_writers():
    Writer.made = []


def test_segments_follow_a_fixed_clock(tmp_path):
    segments = SegmentWriter(tmp_path, fps=10, size=(4, 2), segment_seconds=1,
                             writer_factory=Writer)
    one, two = np.full((2, 4, 3), 1, np.uint8), np.full((2, 4, 3), 2, np.uint8)
    segments.offer(one, 0.0)          # the first tick
    segments.offer(one, 0.05)         # early: nothing new is due
    segments.offer(two, 0.45)         # late: the clock catches up to 0.4
    segments.offer(two, 1.25)         # into the second segment
    segments.close()
    assert [len(w.frames) for w in Writer.made] == [10, 3]
    first = Writer.made[0].frames
    assert [first[i][0, 0, 0] for i in (0, 4, 5)] == [1, 2, 2]
    assert segments.seconds == 1.3 and all(w.released for w in Writer.made)
    assert (tmp_path / "segments.csv").read_text().splitlines() == [
        "segment_0000.mp4,0.000000,1.000000", "segment_0001.mp4,1.000000,1.300000"]


def test_a_writer_that_does_not_open_is_an_error(tmp_path):
    segments = SegmentWriter(tmp_path,
                             writer_factory=lambda *a: Writer(*a, opened=False))
    with pytest.raises(RuntimeError, match="encoder"):
        segments.offer(np.zeros((1080, 1920, 3), np.uint8), 0.0)


def named(code, opened=True, backend="FFMPEG"):
    """A writer factory named like ``aa_recorder.fourcc_writer``'s."""
    def make(*args):
        return Writer(*args, opened=opened, backend=backend)
    make.fourcc = code
    return make


def test_without_h264_segments_fall_back_to_mpeg4_and_keep_it(tmp_path):
    assert FOURCCS == ("avc1", "mp4v")
    tried = []

    def avc1(*args):
        tried.append("avc1")
        return Writer(*args, opened=False)
    avc1.fourcc = "avc1"
    segments = SegmentWriter(tmp_path, fps=10, size=(4, 2), segment_seconds=1,
                             writer_factory=(avc1, named("mp4v")))
    segments.offer(np.zeros((2, 4, 3), np.uint8), 1.5)     # two segments
    segments.close()
    assert segments.fourcc == "mp4v"
    assert tried == ["avc1"]                    # not tried again for the second
    assert [w.opened for w in Writer.made] == [False, True, True]
    assert Writer.made[0].released             # the refused writer is let go


def test_windows_media_foundation_is_never_the_encoder(tmp_path):
    """Its H.264 writes 1 bit per pixel (26 GB an hour, 2026-10-15): a writer
    it opened counts as not opened, and its empty file is not left behind."""
    def msmf(path, *args):
        Path(path).write_bytes(b"\0")
        return Writer(path, *args, backend="MSMF")
    msmf.fourcc = "avc1"
    segments = SegmentWriter(tmp_path, fps=10, size=(4, 2), segment_seconds=1,
                             writer_factory=(msmf, named("mp4v")))
    segments.offer(np.zeros((2, 4, 3), np.uint8), 0.0)
    segments.close()
    assert (segments.fourcc, segments.backend) == ("mp4v", "FFMPEG")
    assert Writer.made[0].released and not Writer.made[0].frames
    assert not (tmp_path / "segment_0000.mp4").exists()   # the fake writes none


def test_windows_writes_through_ffmpeg_only():
    import cv2
    import os
    assert WRITER_API == (cv2.CAP_FFMPEG if os.name == "nt" else cv2.CAP_ANY)


def test_no_encoder_at_all_names_what_was_tried(tmp_path):
    segments = SegmentWriter(tmp_path, writer_factory=(named("avc1", False),
                                                       named("mp4v", False)))
    with pytest.raises(RuntimeError, match=r"encoder.*avc1, mp4v"):
        segments.offer(np.zeros((1080, 1920, 3), np.uint8), 0.0)


def test_this_machine_can_write_a_recording_and_read_it_back():
    """The real OpenCV encoders: H.264 where there is one (macOS, Windows),
    else MPEG-4 (the Linux CI)."""
    report = check_writer()
    assert report["ready"] is True, report
    assert report["fourcc"] in FOURCCS
    assert report["backend"] and report["backend"] != "MSMF"


def test_the_writer_check_reports_a_missing_encoder():
    report = check_writer(writers=(named("avc1", False),))
    assert report["ready"] is False and report["fourcc"] is None
    assert "encoder" in report["reason"]


def test_the_strip_goes_back_where_it_was_cropped():
    assert strip_box(AA8) == (711, 0, 1209, 1080)
    turned = NormalizationConfig(rotate_degrees=90, source_size=(1920, 1080),
                                 crop_after_rotation=(711, 0, 1209, 1080),
                                 output_size=(498, 1080), version="x")
    with pytest.raises(ValueError):
        strip_box(turned)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def test_a_recording_writes_full_frames_and_its_summary(tmp_path):
    clock = Clock()
    out = tmp_path / "20261008-020000-live"
    finished = []

    def done(folder):
        finished.append((folder, (folder / "recording.json").exists()))

    recorder = AARecorder(out, AA8, meta={"device_index": 0}, clock=clock,
                          writer_factory=named("avc1"), on_finished=done)
    strip = np.full((1080, 498, 3), 200, np.uint8)
    recorder.offer(strip)
    wait_for(lambda: Writer.made and Writer.made[0].frames)
    clock.now += 0.5
    recorder.offer(strip)
    wait_for(lambda: len(Writer.made[0].frames) == 16)
    assert recorder.status() == {"active": True, "seconds": 0.5,
                                 "folder": "20261008-020000-live", "megabytes": 0.0,
                                 "stopped_reason": None, "error": None}
    status = recorder.stop()
    assert (status["active"], status["stopped_reason"]) == (False, "stopped")
    # Told once the summary is written (the check-up sheet starts from it).
    assert finished == [(out, True)]
    frame = Writer.made[0].frames[0]
    assert frame.shape == (1080, 1920, 3)
    assert (frame[:, 711:1209] == 200).all()
    assert not frame[:, :711].any() and not frame[:, 1209:].any()
    summary = json.loads((out / "recording.json").read_text())
    # The code that recorded it, so its numbers can be tied to a version.
    assert set(summary["code"]) == {"version", "commit", "dirty"}
    assert summary["recorded_seconds"] == round(16 / 30, 3)
    assert summary["device_index"] == 0 and summary["strip"] == [711, 0, 1209, 1080]
    assert summary["stopped_reason"] == "stopped" and summary["error"] is None
    assert summary["fourcc"] == "avc1"         # the encoder that wrote it
    assert summary["backend"] == "FFMPEG"
    assert (out / "segments.csv").exists()
    recorder.offer(strip)                         # after the stop: ignored
    assert recorder.offered == 2
    with pytest.raises(FileExistsError):          # never into an old recording
        AARecorder(out, AA8, writer_factory=Writer)


def test_a_forgotten_recording_stops_at_the_limit(tmp_path):
    clock = Clock()
    recorder = AARecorder(tmp_path / "r", AA8, clock=clock, writer_factory=Writer,
                          limit_seconds=10)
    clock.now += 11
    recorder.offer(np.zeros((1080, 498, 3), np.uint8))
    recorder.thread.join(timeout=3)
    assert recorder.status()["stopped_reason"] == "time_limit"
    assert not recorder.status()["active"]


class FileWriter(Writer):
    """Leaves a 0.4 MB file, as a segment on disk, and keeps no frames."""

    def __init__(self, path, fps, size):
        super().__init__(path, fps, size)
        path.write_bytes(bytes(400_000))

    def write(self, frame):
        pass


def test_a_recording_stops_when_the_disk_gets_full_and_keeps_what_it_has(tmp_path):
    clock, free = Clock(), [50 * GB]
    recorder = AARecorder(tmp_path / "r", AA8, clock=clock, writer_factory=FileWriter,
                          free=lambda path: free[0])
    strip = np.zeros((1080, 498, 3), np.uint8)
    recorder.offer(strip)
    wait_for(lambda: recorder.megabytes == 0.4)
    assert recorder.status()["active"]
    free[0] = 9 * GB                    # the next segment finds the disk nearly full
    clock.now += 61
    recorder.offer(strip)
    recorder.thread.join(timeout=3)
    status = recorder.status()
    assert (status["active"], status["stopped_reason"]) == (False, "low_disk_space")
    assert status["megabytes"] == 0.8 and status["error"] is None
    summary = json.loads((tmp_path / "r" / "recording.json").read_text())
    assert (summary["stopped_reason"], summary["megabytes"]) == ("low_disk_space", 0.8)


def test_free_space_is_read_from_the_nearest_folder_there_is(tmp_path):
    assert free_bytes(tmp_path / "not" / "made" / "yet") == free_bytes(tmp_path) > 0


def test_an_encoder_failure_ends_the_recording_with_its_error(tmp_path):
    recorder = AARecorder(tmp_path / "r", AA8,
                          writer_factory=lambda *a: Writer(*a, opened=False))
    recorder.offer(np.zeros((1080, 498, 3), np.uint8))
    recorder.thread.join(timeout=3)
    status = recorder.status()
    assert not status["active"] and "encoder" in status["error"]
    assert json.loads((tmp_path / "r" / "recording.json").read_text())["error"]


def test_the_capture_source_records_its_frames_until_it_closes(tmp_path):
    captured = threading.Event()

    class Backend:
        def __init__(self, **kwargs):
            self.seq = 0

        def capture(self, target):
            time.sleep(0.005)
            self.seq += 1
            captured.set()
            return SimpleNamespace(image=np.full((1080, 498, 3), 9, np.uint8),
                                   frame_seq=self.seq)

        def release(self):
            pass

    source = AACaptureSource({"device_index": 1}, backend_factory=Backend)
    source.recorder_factory = lambda out, normalization, meta: AARecorder(
        out, normalization, meta=meta, writer_factory=Writer)
    finished = []
    source.after_recording = finished.append
    assert source.recording_status() is None
    source.read()
    status = source.start_recording(tmp_path / "live")
    assert status["active"] and status["folder"] == "live"
    assert source.start_recording(tmp_path / "other")["folder"] == "live"
    wait_for(lambda: Writer.made and Writer.made[0].frames)
    source.close()
    status = source.recording_status()
    assert (status["active"], status["stopped_reason"]) == (False, "source_stopped")
    assert finished == [tmp_path / "live"]
    summary = json.loads((tmp_path / "live" / "recording.json").read_text())
    assert summary["device_index"] == 1 and summary["offered_frames"] >= 1
    assert not (tmp_path / "other").exists()
    with pytest.raises(RuntimeError):
        source.start_recording(tmp_path / "late")


def test_a_recording_being_played_back_is_not_recorded_again(tmp_path):
    with pytest.raises(RuntimeError):
        AAVideoSource.start_recording(object(), tmp_path / "again")
