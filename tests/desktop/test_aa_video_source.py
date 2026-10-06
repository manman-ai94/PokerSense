"""Recorded capture-card video played at recorded pace, without real files."""

import cv2
import numpy as np
import pytest

from poker_engine.desktop.aa_video_source import (
    AAVideoSource, PacedVideoCapture, VideoSegment, parse_windows, video_segments)


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


class FakeVideo:
    """One segment: frames every ``step`` seconds; seeking lands one frame early."""

    def __init__(self, count, step=0.1, shape=(1080, 1920, 3)):
        self.count, self.step, self.shape = count, step, shape
        self.position = 0
        self.released = False

    def isOpened(self):  # noqa: N802
        return True

    def set(self, prop, value):
        assert prop == cv2.CAP_PROP_POS_MSEC
        self.position = max(0, int(value / 1000 / self.step) - 1)
        return True

    def get(self, prop):
        assert prop == cv2.CAP_PROP_POS_MSEC
        return (self.position - 1) * self.step * 1000

    def read(self):
        if self.position >= self.count:
            return False, None
        self.position += 1
        return True, np.full(self.shape, 40 + self.position % 100, np.uint8)

    def release(self):
        self.released = True


def opener_for(videos):
    opened = []

    def opener(path):
        opened.append(path)
        return videos[path]

    opener.opened = opened
    return opener


def timeline(capture):
    stamps = []
    while True:
        ok, _ = capture.read()
        if not ok:
            return stamps
        stamps.append(round(capture.last_pts, 3))


def test_frames_are_released_at_recorded_pace_across_segments():
    clock = FakeClock()
    videos = {"a.mkv": FakeVideo(3), "b.mkv": FakeVideo(2)}
    capture = PacedVideoCapture(
        [VideoSegment("a.mkv", 0.0), VideoSegment("b.mkv", 0.3)],
        clock=clock, sleep=clock.sleep, opener=opener_for(videos))
    assert timeline(capture) == [0.0, 0.1, 0.2, 0.3, 0.4]
    assert clock.sleeps == [0.1, 0.1, 0.1, 0.1]
    assert capture.finished and videos["a.mkv"].released


def test_speed_scales_the_pace():
    clock = FakeClock()
    capture = PacedVideoCapture([VideoSegment("a.mkv", 0.0)], speed=2.0,
                                clock=clock, sleep=clock.sleep,
                                opener=opener_for({"a.mkv": FakeVideo(3)}))
    timeline(capture)
    assert clock.sleeps == [0.05, 0.05]


def test_excluded_window_is_skipped_even_when_seek_lands_early():
    clock = FakeClock()
    capture = PacedVideoCapture(
        [VideoSegment("a.mkv", 0.0)], exclude=parse_windows(["0.3-0.7"]),
        clock=clock, sleep=clock.sleep,
        opener=opener_for({"a.mkv": FakeVideo(10)}))
    assert timeline(capture) == [0.0, 0.1, 0.2, 0.7, 0.8, 0.9]
    # Pace restarts after the jump instead of sleeping through the gap.
    assert max(clock.sleeps) == pytest.approx(0.1)


def test_start_seeks_into_the_right_segment():
    clock = FakeClock()
    videos = {"a.mkv": FakeVideo(3), "b.mkv": FakeVideo(5)}
    opener = opener_for(videos)
    capture = PacedVideoCapture(
        [VideoSegment("a.mkv", 0.0), VideoSegment("b.mkv", 0.3)], start=0.5,
        clock=clock, sleep=clock.sleep, opener=opener)
    assert timeline(capture) == [0.5, 0.6, 0.7]
    assert opener.opened == ["b.mkv"]


def test_video_segments_from_file_and_recorder_folder(tmp_path):
    single = tmp_path / "one.mkv"
    single.write_bytes(b"x")
    assert video_segments(single) == [VideoSegment(single.resolve(), 0.0)]
    folder = tmp_path / "rec"
    folder.mkdir()
    for name in ("segment_0000.mkv", "segment_0001.mkv"):
        (folder / name).write_bytes(b"x")
    (folder / "segments.csv").write_text(
        "segment_0000.mkv,0.000000,60.000000\n"
        "segment_0001.mkv,60.000000,120.031000\n", encoding="utf-8")
    assert [s.start for s in video_segments(folder)] == [0.0, 60.0]
    with pytest.raises(ValueError):
        video_segments(tmp_path)


@pytest.mark.parametrize("bad", ["300", "820-300", "a-b", "-5-3"])
def test_invalid_skip_windows_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_windows([bad])


def test_video_source_uses_capture_card_canvas_and_ends_cleanly(tmp_path):
    video = tmp_path / "rec.mkv"
    video.write_bytes(b"x")
    source = AAVideoSource(video, opener=lambda path: FakeVideo(3, step=0.01))
    records = []
    while (record := source.read()) is not None:
        records.append(record)
    source.close()
    # Latest-frame semantics may drop a frame, never reorder or invent one.
    stamps = [round(r["source_video_pts"], 3) for r in records]
    assert stamps and stamps[0] == 0.0
    assert stamps == sorted(set(stamps)) and set(stamps) <= {0.0, 0.01, 0.02}
    assert all(r["source_kind"] == "video-replay" for r in records)
    assert records[0]["image"].shape == (1080, 498, 3)
    assert records[0]["physical_source_timestamp"] is None
