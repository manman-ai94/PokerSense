"""Recording the capture card from inside the live service.

The live service holds the capture card while it runs, so the frames it
already captures are written to the layout ``tools/record_aa_capture.py``
makes: 60-second H.264 segments on a fixed 30 fps clock aligned to wall time
(a late frame is repeated, an early one dropped), with ``segments.csv`` and
``recording.json``. Such a folder plays back with ``--replay-video`` and
``tools/measure_aa_realtime.py``. The service also logs what it read and
advised from each frame to ``frames.jsonl`` there (``aa_session``).

The service keeps only the phone strip of each frame (the normalized crop),
so the strip goes back to its place in a black 1920x1080 frame: replaying the
recording crops the same pixels again. A crop that cannot be put back (a
rotation or a resize) is refused rather than recorded in another layout.
Encoding runs on its own thread; a frame that arrives while the encoder is
busy is skipped and the clock repeats the one before.

A recording needs room: the service does not start one with less than
``MIN_FREE_GB`` free on the disk, and one stops (``low_disk_space``, what was
recorded is kept) once a new segment finds less than ``STOP_FREE_GB``. The
size written so far is in the status (``megabytes``): about 0.1-1.5 GB an
hour on the recordings made so far.

A recording is only worth it when it shows the phone. The capture card puts
the phone's portrait screen between black bars (``picture``): measured on
the recordings, the bars are 0 while a computer camera, which also gives a
1920x1080 picture, is bright there (on 2026-10-07 a recording got the
camera instead of the card).
"""

from __future__ import annotations

import json
from pathlib import Path
import queue
import shutil
import threading
import time

import cv2
import numpy as np

FPS = 30
SIZE = (1920, 1080)
SEGMENT_SECONDS = 60
LIMIT_SECONDS = 2 * 3600            # about 2 hours; a forgotten recording stops
GB = 1024 ** 3
MIN_FREE_GB = 20                    # free space a recording starts with
STOP_FREE_GB = 10                   # and stops at
BARS = ((0, 700), (1220, 1920))     # columns beside the phone strip (711-1208)
BAR_DARK = 16                       # brightest bar pixel (99th percentile)
STRIP_LIT = 4                       # mean brightness of a lit phone screen


def picture(frame):
    """What a full 1920x1080 frame shows: "phone" (a lit phone screen between
    black bars), "dark" (black all over: the phone screen is off, or a
    camera is still starting) or "other" (not the capture card's phone)."""
    if not isinstance(frame, np.ndarray) or frame.shape[:2] != (SIZE[1], SIZE[0]):
        return "other"
    gray = frame.mean(axis=2) if frame.ndim == 3 else frame
    bars = max(np.percentile(gray[::4, x0:x1:4], 99) for x0, x1 in BARS)
    if bars > BAR_DARK:
        return "other"
    return "phone" if gray[:, 711:1209].mean() > STRIP_LIT else "dark"


def free_bytes(path):
    """Free space on the disk holding ``path`` (or its nearest existing folder)."""
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def avc1_writer(path, fps, size):
    return cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"avc1"), fps, size)


class SegmentWriter:
    """Segments on a fixed clock: ``offer(frame, seconds)`` fills the clock up
    to ``seconds`` with ``frame``, the newest frame at that time."""

    def __init__(self, out, *, fps=FPS, size=SIZE, segment_seconds=SEGMENT_SECONDS,
                 writer_factory=avc1_writer):
        self.out = Path(out)
        self.fps, self.size, self.segment_seconds = fps, size, segment_seconds
        self.writer_factory = writer_factory
        self.written = self.seg_written = 0
        self.segment = self.writer = None
        self.seg_start = 0.0
        self.lines = []

    @property
    def seconds(self):
        return self.written / self.fps

    def offer(self, frame, seconds):
        due = int(seconds * self.fps) + 1
        full = self.segment_seconds * self.fps
        while self.written < due:
            if self.writer is None or self.seg_written >= full:
                self._next()
            self.writer.write(frame)
            self.written += 1
            self.seg_written += 1

    def _next(self):
        self.close()
        self.segment = 0 if self.segment is None else self.segment + 1
        self.seg_start, self.seg_written = self.written / self.fps, 0
        writer = self.writer_factory(self.out / f"segment_{self.segment:04d}.mp4",
                                     self.fps, self.size)
        if not writer.isOpened():
            raise RuntimeError("the H.264 encoder did not open")
        self.writer = writer

    def close(self):
        """Finish the current segment and list it in ``segments.csv``."""
        if self.writer is None:
            return
        self.writer.release()
        self.writer = None
        end = self.seg_start + self.seg_written / self.fps
        name = f"segment_{self.segment:04d}.mp4"
        self.lines.append(f"{name},{self.seg_start:.6f},{end:.6f}")
        (self.out / "segments.csv").write_text("\n".join(self.lines) + "\n",
                                               encoding="utf-8")


def strip_box(normalization):
    """Where the normalized strip sits in the full frame: (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = normalization.crop_after_rotation
    if (normalization.rotate_degrees != 0
            or tuple(normalization.source_size) != SIZE
            or tuple(normalization.output_size) != (x1 - x0, y1 - y0)):
        raise ValueError("this crop cannot be put back into a full frame")
    return x0, y0, x1, y1


class AARecorder:
    """One recording of the strips the capture source delivers."""

    def __init__(self, out, normalization, *, meta=None, clock=time.monotonic,
                 writer_factory=avc1_writer, limit_seconds=LIMIT_SECONDS,
                 free=free_bytes, stop_free=STOP_FREE_GB * GB):
        self.box = strip_box(normalization)
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.segments = SegmentWriter(self.out, writer_factory=writer_factory)
        self.clock, self.limit = clock, limit_seconds
        self.free, self.stop_free = free, stop_free
        self.megabytes = 0.0
        self.begin = clock()
        self.queue = queue.Queue(maxsize=2)
        self.offered = self.skipped = 0
        self.stopping = False
        self.reason = self.error = None
        self.meta = {"source": "aa-live-service", "fps": FPS, "size": list(SIZE),
                     "strip": list(self.box), **(meta or {}),
                     "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name="aa-recorder")
        self.thread.start()

    def offer(self, image):
        """Called on the capture thread with each new strip; never blocks."""
        if self.stopping:
            return
        seconds = self.clock() - self.begin
        if seconds >= self.limit:
            self._finish("time_limit")
            return
        try:
            self.queue.put_nowait((image, seconds))
            self.offered += 1
        except queue.Full:
            self.skipped += 1

    def stop(self, reason="stopped"):
        """Finish the recording and wait for the last segment to be written."""
        self._finish(reason)
        self.thread.join(timeout=15)
        return self.status()

    def _finish(self, reason):
        if self.stopping:
            return
        self.stopping, self.reason = True, reason
        try:
            self.queue.put_nowait(None)
        except queue.Full:           # the writer takes a frame, then the stop
            threading.Thread(target=self.queue.put, args=(None,), daemon=True).start()

    def _run(self):
        canvas = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
        x0, y0, x1, y1 = self.box
        checked = None
        try:
            while True:
                item = self.queue.get()
                if item is None:
                    break
                image, seconds = item
                canvas[y0:y1, x0:x1] = image
                self.segments.offer(canvas, seconds)
                if self.segments.segment != checked:      # a new segment began
                    checked = self.segments.segment
                    self._measure()
                    if self.free(self.out) < self.stop_free:
                        self.stopping = True
                        self.reason = self.reason or "low_disk_space"
                        break
        except Exception as exc:
            self.error = exc
            self.stopping = True
            self.reason = self.reason or "error"
        finally:
            try:
                self.segments.close()
            except Exception as exc:
                self.error = self.error or exc
            self._measure()
            self.meta.update(recorded_seconds=round(self.segments.seconds, 3),
                             megabytes=self.megabytes,
                             offered_frames=self.offered, skipped_frames=self.skipped,
                             stopped_reason=self.reason,
                             error=None if self.error is None else str(self.error))
            (self.out / "recording.json").write_text(
                json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def _measure(self):
        self.megabytes = round(sum(path.stat().st_size for path in
                                   self.out.glob("segment_*.mp4")) / 1e6, 1)

    def status(self):
        return {"active": not self.stopping, "seconds": round(self.segments.seconds, 1),
                "folder": self.out.name, "megabytes": self.megabytes,
                "stopped_reason": self.reason,
                "error": None if self.error is None else str(self.error)}


__all__ = ["AARecorder", "free_bytes", "GB", "MIN_FREE_GB", "picture", "SegmentWriter",
           "STOP_FREE_GB", "strip_box"]
