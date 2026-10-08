"""The Terminal recorder finds the phone, minds the disk and keeps its last segment."""

import json
import os
import signal

import numpy as np
import pytest

from poker_engine.desktop import aa_recorder
from poker_engine.desktop.aa_recorder import picture
from tools import record_aa_capture


def frame(bars=0, strip=90):
    """A 1920x1080 frame: the phone strip (columns 711-1208) between bars."""
    image = np.full((1080, 1920, 3), bars, np.uint8)
    image[:, 711:1209] = strip
    return image


CAMERA = np.full((1080, 1920, 3), 170, np.uint8)


class Cap:
    def __init__(self, frames, on_read=None):
        self.frames, self.on_read = list(frames), on_read
        self.reads = 0
        self.released = False

    def read(self):
        self.reads += 1
        if self.on_read:
            self.on_read(self.reads)
        return (True, self.frames[min(self.reads, len(self.frames) - 1)])

    def release(self):
        self.released = True


class Writer:
    def __init__(self, out, **options):
        self.out, self.segment_seconds = out, options["segment_seconds"]
        self.segment, self.seconds, self.offered = None, 0.0, []

    def offer(self, image, seconds):
        self.offered.append(seconds)
        self.segment = int(seconds // self.segment_seconds)
        self.seconds = seconds

    def close(self):
        pass


def test_the_phone_is_told_from_a_camera_by_the_black_bars():
    assert picture(frame()) == "phone"
    assert picture(frame(strip=0)) == "dark"         # screen off, camera starting
    assert picture(CAMERA) == "other"
    assert picture(frame(bars=40)) == "other"
    assert picture(frame()[:720, :1280]) == "other"  # not the card's size
    assert picture(None) == "other"


def test_the_first_device_showing_the_phone_is_used(monkeypatch):
    caps = {0: Cap([CAMERA]), 1: Cap([frame()])}

    def open_device(index, api):
        if index not in caps:
            raise SystemExit("no such device")
        return caps[index], caps[index].frames[0]

    monkeypatch.setattr(record_aa_capture, "open_device", open_device)
    index, cap, first = record_aa_capture.find_phone("AVFOUNDATION")
    assert index == 1 and cap is caps[1] and picture(first) == "phone"
    assert caps[0].released and not caps[1].released


def test_nothing_is_recorded_when_no_device_shows_the_phone(monkeypatch, tmp_path):
    caps = {0: Cap([CAMERA]), 1: Cap([frame(strip=0)])}
    monkeypatch.setattr(record_aa_capture, "LOOK_SECONDS", 0)
    monkeypatch.setattr(record_aa_capture, "open_device",
                        lambda index, api: (caps[index], caps[index].frames[0])
                        if index in caps else (_ for _ in ()).throw(SystemExit()))
    monkeypatch.setattr(aa_recorder, "free_bytes", lambda path: 100 * aa_recorder.GB)
    with pytest.raises(SystemExit) as stopped:
        record_aa_capture.record(tmp_path / "x", api="AVFOUNDATION")
    assert str(stopped.value).startswith(record_aa_capture.NO_PHONE)
    assert not (tmp_path / "x").exists() and all(cap.released for cap in caps.values())
    # A device named on the command line is checked the same way.
    with pytest.raises(SystemExit):
        record_aa_capture.record(tmp_path / "x", index=0, api="AVFOUNDATION")


def record_with(monkeypatch, tmp_path, cap, free, seconds=5):
    monkeypatch.setattr(record_aa_capture, "open_device",
                        lambda index, api: (cap, cap.frames[0]))
    monkeypatch.setattr(record_aa_capture, "SegmentWriter", Writer)
    monkeypatch.setattr(aa_recorder, "free_bytes", free)
    out = tmp_path / "rec"
    meta = record_aa_capture.record(out, api="AVFOUNDATION", seconds=seconds,
                                    segment_seconds=0.01)
    return meta, json.loads((out / "recording.json").read_text())


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="no SIGHUP on Windows")
def test_closing_the_window_keeps_what_was_recorded(monkeypatch, tmp_path):
    before = signal.getsignal(signal.SIGHUP)
    cap = Cap([frame()], on_read=lambda reads: reads == 3 and os.kill(
        os.getpid(), signal.SIGHUP))
    meta, saved = record_with(monkeypatch, tmp_path, cap,
                              lambda path: 100 * aa_recorder.GB)
    assert saved["stopped_reason"] == "window_closed_SIGHUP" == meta["stopped_reason"]
    assert saved["device_index"] == 0 and cap.released
    assert signal.getsignal(signal.SIGHUP) is before


def test_a_recording_stops_when_the_disk_fills(monkeypatch, tmp_path):
    left = iter([30, 30, 9])                  # GB at the start, then per segment
    meta, saved = record_with(
        monkeypatch, tmp_path, Cap([frame()]),
        lambda path: next(left, 9) * aa_recorder.GB)
    assert saved["stopped_reason"] == "low_disk_space"
