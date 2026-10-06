"""A recorded capture-card video played back as if it were the live card.

Frames are released at their recorded pace and go through the same
``CaptureCardBackend`` normalization and latest-frame pump as the real card,
so a slow consumer drops frames exactly as it would live. Reserved timeline
windows (for example an untouched holdout) are skipped without being decoded
into the session.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
import time
from typing import Callable, NamedTuple

import cv2

from poker_engine.perceptual.capture.capture_card_backend import CaptureCardBackend

from .aa_sources import AACaptureSource


class VideoSegment(NamedTuple):
    path: Path
    start: float  # timeline seconds of the segment's local timestamp 0


def video_segments(path) -> list[VideoSegment]:
    """One video file, or a recorder folder with ``segments.csv``."""
    path = Path(path)
    if path.is_file():
        return [VideoSegment(path.resolve(), 0.0)]
    index = path / "segments.csv"
    if not index.is_file():
        raise ValueError("录像路径必须是视频文件，或含 segments.csv 的分段录像目录")
    segments = []
    with index.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row or not row[0].strip():
                continue
            name, start = row[0].strip(), float(row[1])
            file = (path / name).resolve()
            if not math.isfinite(start) or start < 0 or not file.is_file():
                raise ValueError(f"segments.csv 中的分段无效：{name}")
            segments.append(VideoSegment(file, start))
    if not segments or any(b.start <= a.start for a, b in zip(segments, segments[1:])):
        raise ValueError("segments.csv 需要按开始时间递增的分段")
    return segments


def parse_windows(values) -> tuple[tuple[float, float], ...]:
    """``"300-820"`` style strings -> sorted half-open ``(start, end)`` pairs."""
    windows = []
    for value in values or ():
        try:
            low, high = (float(part) for part in str(value).split("-", 1))
        except ValueError:
            raise ValueError(f"跳过区间格式应为 开始秒-结束秒：{value}") from None
        if not (math.isfinite(low) and math.isfinite(high) and 0 <= low < high):
            raise ValueError(f"跳过区间无效：{value}")
        windows.append((low, high))
    return tuple(sorted(windows))


class PacedVideoCapture:
    """``cv2.VideoCapture`` stand-in that releases frames at recorded pace."""

    def __init__(self, segments, *, start=0.0, exclude=(), speed=1.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 opener: Callable[[str], object] = cv2.VideoCapture):
        if not segments:
            raise ValueError("at least one video segment is required")
        if not (math.isfinite(speed) and speed > 0):
            raise ValueError("speed must be positive")
        self._segments = list(segments)
        self._exclude = tuple(exclude)
        self._speed = speed
        self._clock, self._sleep, self._opener = clock, sleep, opener
        self._index = -1
        self._cap = None
        self._anchor = None  # (wall clock, timeline seconds)
        self._skip_until = None
        self.last_pts = None
        self.finished = False
        self._seek(float(start))

    def _excluded_until(self, pts):
        for low, high in self._exclude:
            if low <= pts < high:
                return high
        return None

    def _open(self, index, offset):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._index = index
        if index >= len(self._segments):
            self.finished = True
            return
        self._cap = self._opener(str(self._segments[index].path))
        if offset > 0:
            self._cap.set(cv2.CAP_PROP_POS_MSEC, offset * 1000)

    def _seek(self, pts):
        """Continue from timeline ``pts``; playback pace restarts there.

        Seeking lands on a keyframe at or before ``pts``; frames before it are
        decoded and dropped rather than sought again.
        """
        index = max((i for i, s in enumerate(self._segments) if s.start <= pts),
                    default=0)
        self._open(index, pts - self._segments[index].start)
        self._skip_until = pts
        self._anchor = None

    def isOpened(self):  # noqa: N802 - cv2.VideoCapture interface
        return self._cap is not None and bool(self._cap.isOpened())

    def set(self, prop, value):  # resolution/fps requests do not apply to files
        return False

    def get(self, prop):
        return self._cap.get(prop) if self._cap is not None else 0.0

    def read(self):
        while not self.finished:
            ok, frame = self._cap.read()
            if not ok or frame is None:
                self._open(self._index + 1, 0.0)
                continue
            segment = self._segments[self._index]
            pts = segment.start + self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if self._skip_until is not None:
                if pts < self._skip_until:
                    continue
                self._skip_until = None
            resume = self._excluded_until(pts)
            if resume is not None:
                self._seek(resume)
                continue
            if self._anchor is None:
                self._anchor = (self._clock(), pts)
            due = self._anchor[0] + (pts - self._anchor[1]) / self._speed
            delay = due - self._clock()
            if delay > 0:
                self._sleep(delay)
            self.last_pts = pts
            return True, frame
        return False, None

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class _NoDeviceLock:
    """A recording needs no exclusive capture-device ownership."""

    def acquire(self):
        pass

    def release(self):
        pass

    def retain_until_process_exit(self):
        pass


class AAVideoSource(AACaptureSource):
    """The capture-card source fed by a recording instead of the device."""

    def __init__(self, path, *, start=0.0, exclude=(), speed=1.0, opener=None):
        self.video = PacedVideoCapture(
            video_segments(path), start=start, exclude=exclude, speed=speed,
            **({"opener": opener} if opener is not None else {}))

        def backend(**kwargs):
            return CaptureCardBackend(
                **kwargs, video_capture_factory=lambda index, api: self.video)

        super().__init__({"device_index": 0}, backend_factory=backend,
                         device_lock_factory=_NoDeviceLock,
                         source_kind="video-replay")

    def _frame_extras(self):
        return {"source_video_pts": self.video.last_pts}

    def read(self):
        try:
            return super().read()
        except Exception:
            if self.video.finished:
                return None  # the recording ended: a normal end, not a fault
            raise


__all__ = [
    "AAVideoSource", "PacedVideoCapture", "VideoSegment", "parse_windows",
    "video_segments",
]
