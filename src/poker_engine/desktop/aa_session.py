"""One explicitly started AA observation worker, shared by every UI client."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
import uuid

import cv2
import numpy as np

from .aa_turn_runtime import observation_runtime_status


class AARecognitionSession:
    """Own source lifetime without blocking the server event loop.

    Sources yield normalized BGR frames or None at exhaustion. Reader sequence
    numbers count processed frames; source frame numbers retain their original
    meaning. Source receipt and pixel hashes do not prove device liveness.
    """

    def __init__(self, source_factory, reader_factory, *, stale_after=2.0,
                 interval_seconds=0.1):
        if not callable(source_factory) or not callable(reader_factory):
            raise TypeError("source_factory and reader_factory must be callable")
        for name, value in (("stale_after", stale_after),
                            ("interval_seconds", interval_seconds)):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and nonnegative")
        if stale_after == 0:
            raise ValueError("stale_after must be positive")
        self._source_factory = source_factory
        self._reader_factory = reader_factory
        self._stale_after = stale_after
        self._interval = interval_seconds
        self._lock = threading.RLock()
        self._worker = None
        self._cancel = threading.Event()
        self._generation = 0
        self._instance_id = uuid.uuid4().hex
        self._status = "STOPPED"
        self._payload = self._preview = self._sequence = None
        self._source_frame = self._processing_ms = self._last_result = None
        self._source_kind = self._pts_seconds = None
        self._source_options = {}
        self._error = None
        self._timing = None

    def _clear(self):
        self._payload = self._preview = self._sequence = None
        self._source_frame = self._processing_ms = self._last_result = None
        self._pts_seconds = None
        self._timing = None

    def _expire(self):
        now = time.monotonic()
        age_from = (self._timing or {}).get("host_source_started_at")
        if age_from is None:
            age_from = self._last_result
        if (self._status == "RUNNING" and age_from is not None
                and now - age_from > self._stale_after):
            self._generation += 1
            self._cancel.set()
            self._status = "STALE"
            self._error = "Source or recognition exceeded the stale deadline"
            self._clear()

    def _snapshot(self):
        result = {
                "status": self._status, "instance_id": self._instance_id,
                "generation": self._generation,
                "sequence": self._sequence, "source_frame": self._source_frame,
                "payload": copy.deepcopy(self._payload), "error": self._error,
                "processing_ms": self._processing_ms,
                "source_kind": self._source_kind, "pts_seconds": self._pts_seconds,
                "source_options": copy.deepcopy(self._source_options),
                "timing": copy.deepcopy(self._timing)}
        result["realtime"] = observation_runtime_status(result, now=time.monotonic())
        return result

    def snapshot(self):
        with self._lock:
            self._expire()
            return self._snapshot()

    def preview(self):
        with self._lock:
            self._expire()
            return self._preview

    def evidence(self):
        """Return current fields and their matching preview under one lock."""
        with self._lock:
            self._expire()
            return self._snapshot(), self._preview

    def start(self, source_options: dict):
        if not isinstance(source_options, dict):
            raise TypeError("source_options must be a dict")
        options = copy.deepcopy(source_options)
        with self._lock:
            self._expire()
            if self._worker is not None and self._worker.is_alive():
                if self._cancel.is_set():
                    self._status = "STOPPING"
                return self._snapshot()
            self._generation += 1
            self._clear()
            self._source_options = options
            self._source_kind = options.get("mode")
            self._error = None
            self._status = "STARTING"
            self._cancel = threading.Event()
            self._worker = threading.Thread(
                target=self._run,
                args=(options, self._generation, self._cancel),
                name="pokersense-aa-recognition", daemon=True,
            )
            self._worker.start()
            return self._snapshot()

    def stop(self):
        with self._lock:
            self._generation += 1
            self._cancel.set()
            self._clear()
            self._error = None
            self._status = ("STOPPING" if self._worker is not None
                            and self._worker.is_alive() else "STOPPED")
            return self._snapshot()

    def _finish(self, generation, cancel, status, error=None):
        with self._lock:
            if generation == self._generation and not cancel.is_set():
                cancel.set()
                self._status = status
                self._error = error
                self._clear()

    def _run(self, options, generation, cancel):
        source = None
        try:
            reader = self._reader_factory()
            if cancel.is_set():
                return
            source = self._source_factory(options)
            processed = 0
            while not cancel.is_set():
                read_started = time.monotonic()
                record = source.read()
                read_finished = time.monotonic()
                if cancel.is_set():
                    break
                if record is None:
                    self._finish(generation, cancel, "ENDED")
                    break
                started = time.monotonic()
                host_started = record.get("host_source_started_at")
                host_received = record.get("host_source_received_at")
                if host_started is not None or host_received is not None:
                    if (any(isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or not math.isfinite(value) for value in (
                                host_started, host_received))
                            or not 0 <= host_started <= host_received <= read_finished):
                        raise ValueError("invalid source host timestamps")
                image = record["image"]
                if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
                        or image.ndim != 3 or image.shape[2] != 3 or not image.size):
                    raise ValueError("source must provide a nonempty uint8 BGR image")
                raw_sequence = record["source_frame"]
                pts = record["pts_seconds"]
                kind = record["source_kind"]
                if not isinstance(kind, str) or not kind:
                    raise ValueError("source_kind must be a nonempty string")
                if options.get("mode") is not None and kind != options["mode"]:
                    raise ValueError("source_kind does not match requested mode")
                if isinstance(raw_sequence, bool) or not isinstance(raw_sequence, int):
                    raise ValueError("source_frame must be an integer")
                if (isinstance(pts, bool) or not isinstance(pts, (int, float))
                        or not math.isfinite(pts)):
                    raise ValueError("pts_seconds must be finite")
                sample = {key: value for key, value in record.items() if key != "image"}
                sample["sha256"] = hashlib.sha256(image.tobytes()).hexdigest()
                payload = reader.read(image, processed, sample)
                recognition_finished = time.monotonic()
                if not isinstance(payload, dict):
                    raise ValueError("reader must return a JSON object")
                # Detach mutable reader results and reject NaN/non-JSON values.
                payload = json.loads(json.dumps(payload, allow_nan=False))
                ok, encoded = cv2.imencode(".jpg", image)
                if not ok:
                    raise ValueError("could not encode frame preview")
                with self._lock:
                    if cancel.is_set() or generation != self._generation:
                        break
                    self._status = "RUNNING"
                    self._error = None
                    self._payload = payload
                    self._preview = encoded.tobytes()
                    self._sequence = processed
                    self._source_frame = raw_sequence
                    self._source_kind = kind
                    self._pts_seconds = pts
                    self._processing_ms = (time.monotonic() - started) * 1000
                    self._last_result = time.monotonic()
                    self._timing = {
                        "clock": "host_monotonic",
                        "host_source_started_at": host_started,
                        "host_source_received_at": host_received,
                        "source_read_started_at": read_started,
                        "source_read_finished_at": read_finished,
                        "source_read_ms": (read_finished - read_started) * 1000,
                        "recognition_started_at": started,
                        "recognition_finished_at": recognition_finished,
                        "recognition_ms": (recognition_finished - started) * 1000,
                        "published_at": self._last_result,
                        "physical_source_timestamp": None,
                        "end_to_end_latency_ms": None,
                    }
                    # A late first result must not receive a fresh stale window.
                    self._expire()
                processed += 1
                cancel.wait(self._interval)
        except Exception as exc:
            self._finish(generation, cancel, "ERROR", str(exc))
        finally:
            if source is not None:
                try:
                    source.close()
                except Exception as exc:
                    with self._lock:
                        if self._cancel is cancel:
                            self._status = "ERROR"
                            self._error = f"Source close failed: {exc}"
                            self._clear()
            with self._lock:
                if self._cancel is cancel and self._status == "STOPPING":
                    self._status = "STOPPED"


__all__ = ["AARecognitionSession"]
