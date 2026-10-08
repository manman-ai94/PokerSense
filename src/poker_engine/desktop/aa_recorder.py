"""Recording the capture card from inside the live service.

The live service holds the capture card while it runs, so the frames it
already captures are written to the layout ``tools/record_aa_capture.py``
makes: 60-second H.264 segments on a fixed 30 fps clock aligned to wall time
(a late frame is repeated, an early one dropped), with ``segments.csv`` and
``recording.json``. Such a folder plays back with ``--replay-video`` and
``tools/measure_aa_realtime.py``.

The service keeps only the phone strip of each frame (the normalized crop),
so the strip goes back to its place in a black 1920x1080 frame: replaying the
recording crops the same pixels again. A crop that cannot be put back (a
rotation or a resize) is refused rather than recorded in another layout.
Encoding runs on its own thread; a frame that arrives while the encoder is
busy is skipped and the clock repeats the one before.
"""

from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
import time

import cv2
import numpy as np

FPS = 30
SIZE = (1920, 1080)
SEGMENT_SECONDS = 60
LIMIT_SECONDS = 2 * 3600            # about 2 hours; a forgotten recording stops


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
                 writer_factory=avc1_writer, limit_seconds=LIMIT_SECONDS):
        self.box = strip_box(normalization)
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.segments = SegmentWriter(self.out, writer_factory=writer_factory)
        self.clock, self.limit = clock, limit_seconds
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
        try:
            while True:
                item = self.queue.get()
                if item is None:
                    break
                image, seconds = item
                canvas[y0:y1, x0:x1] = image
                self.segments.offer(canvas, seconds)
        except Exception as exc:
            self.error = exc
            self.stopping = True
            self.reason = self.reason or "error"
        finally:
            try:
                self.segments.close()
            except Exception as exc:
                self.error = self.error or exc
            self.meta.update(recorded_seconds=round(self.segments.seconds, 3),
                             offered_frames=self.offered, skipped_frames=self.skipped,
                             stopped_reason=self.reason,
                             error=None if self.error is None else str(self.error))
            (self.out / "recording.json").write_text(
                json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def status(self):
        return {"active": not self.stopping, "seconds": round(self.segments.seconds, 1),
                "folder": self.out.name, "stopped_reason": self.reason,
                "error": None if self.error is None else str(self.error)}


__all__ = ["AARecorder", "SegmentWriter", "strip_box"]
