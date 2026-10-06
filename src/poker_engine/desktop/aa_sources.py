"""Explicit AA image sources; constructing the application never opens hardware."""

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from poker_engine.perceptual.capture.base import CaptureTarget
from poker_engine.perceptual.capture.capture_card_backend import CaptureCardBackend
from poker_engine.perceptual.capture.normalization import NormalizationConfig

from .aa_device_lock import AACaptureDeviceLock


class AACaptureSource:
    def __init__(self, options, *, backend_factory=CaptureCardBackend,
                 device_lock_factory=None):
        index = options.get("device_index", 0)
        api = options.get("api", "MSMF")
        if type(index) is not int or not 0 <= index <= 20:
            raise ValueError("设备编号必须为 0–20 的整数")
        if api not in {"MSMF", "DSHOW"}:
            raise ValueError("采集接口必须为 MSMF 或 DSHOW")
        self.backend = backend_factory(
            device_index=index, api=api, width=1920, height=1080, fps=30,
            normalization=NormalizationConfig(
                rotate_degrees=0, source_size=(1920, 1080),
                crop_after_rotation=(711, 0, 1209, 1080),
                output_size=(498, 1080), version="aa8-capture-canvas-v1"),
        )
        self.target = CaptureTarget(f"uvc-{index}")
        self.started = time.monotonic()
        self.condition = threading.Condition()
        self.cancel = threading.Event()
        self.thread = None
        self.latest = None
        self.error = None
        self.release_error = None
        self.delivered = None
        self.device_lock = (device_lock_factory or AACaptureDeviceLock)()

    def _pump(self):
        try:
            while not self.cancel.is_set():
                host_started = time.monotonic()
                frame = self.backend.capture(self.target)
                host_received = time.monotonic()
                with self.condition:
                    self.latest = {
                        "image": frame.image, "source_frame": frame.frame_seq,
                        "pts_seconds": host_received - self.started,
                        "host_source_started_at": host_started,
                        "host_source_received_at": host_received,
                        "physical_source_timestamp": None,
                        "source_clock": "host_monotonic_capture_call",
                        "source_kind": "capture-card"}
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error = exc
                self.latest = None
                self.condition.notify_all()
        finally:
            try:
                self.backend.release()
            except Exception as exc:
                self.device_lock.retain_until_process_exit()
                with self.condition:
                    self.release_error = exc
                    self.error = exc
                    self.latest = None
                    self.condition.notify_all()
            else:
                self.device_lock.release()

    def read(self):
        with self.condition:
            if self.cancel.is_set():
                return None
            if self.thread is None:
                self.device_lock.acquire()
                self.thread = threading.Thread(target=self._pump, daemon=True,
                                               name="aa-latest-capture-frame")
                try:
                    self.thread.start()
                except Exception:
                    self.thread = None
                    self.device_lock.release()
                    raise
            ready = self.condition.wait_for(
                lambda: self.error is not None or self.cancel.is_set()
                or self.latest is not None and self.latest["source_frame"] != (
                    self.delivered), timeout=2.0)
            if self.error is not None:
                raise self.error
            if self.cancel.is_set():
                return None
            if not ready:
                raise RuntimeError("采集卡两秒内未提供新帧")
            result = self.latest
            self.delivered = result["source_frame"]
            return result

    def close(self):
        self.cancel.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None:
            # Runs in session worker, never the API thread. A blocked driver
            # leaves STOPPING visible and prevents a second device owner.
            self.thread.join()
            if self.release_error is not None:
                raise self.release_error
        else:
            try:
                self.backend.release()
            finally:
                self.device_lock.release()


class AADevelopmentSource:
    """Only manifest-bound, contiguous development PNGs; no video/holdout path."""

    def __init__(self, pool, audit, *, first=None, last=None):
        from tools.aa8_action_transfer import inventory

        self.pool = Path(pool).resolve(strict=True)
        self.rows = inventory(self.pool, audit)
        keys = list(self.rows)
        first = keys[0] if first is None else first
        last = keys[-1] if last is None else last
        if (type(first) is not int or type(last) is not int or first > last
                or first not in self.rows or last not in self.rows):
            raise ValueError("开发回放区间必须属于已登记开发帧")
        self.frames = iter(range(first, last + 1))
        self.closed = False

    def read(self):
        from tools.aa8_action_transfer import load

        if self.closed:
            return None
        frame = next(self.frames, None)
        if frame is None:
            return None
        row = self.rows[frame]
        pts = row["pts_seconds"]
        if isinstance(pts, bool):
            raise ValueError("开发帧 PTS 必须为数值")
        return {"image": load(self.pool, row), "source_frame": frame,
                "pts_seconds": float(pts), "source_pts_exact": str(pts),
                "source_kind": "development-replay"}

    def close(self):
        self.closed = True


def _sha256_text(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


class AADevelopmentSequenceSource:
    """Hash-bound development segments with one uninterrupted source identity.

    Construction checks metadata for every selected segment before loading any
    pixels. Context-only frames are still real observations; the marker never
    initializes poker state or changes the source's original frame numbers.
    """

    def __init__(self, playlist_path, audit):
        playlist = Path(playlist_path).resolve(strict=True)
        raw = playlist.read_bytes()
        spec = json.loads(raw.decode("utf-8"))
        if (not isinstance(spec, dict)
                or set(spec) != {"schema_version", "audit_sha256", "segments"}
                or type(spec["schema_version"]) is not int
                or spec["schema_version"] != 1):
            raise ValueError("invalid development playlist schema")
        if not _sha256_text(audit) or spec["audit_sha256"] != audit:
            raise ValueError("playlist audit mismatch")
        segments = spec["segments"]
        if not isinstance(segments, list) or not segments:
            raise ValueError("playlist requires ordered segments")
        self.playlist_sha256 = hashlib.sha256(raw).hexdigest()
        self.source_id = f"aa8-development:{audit}:{self.playlist_sha256}"
        selected = []
        previous_frame = previous_pts = previous_float = None
        for segment in segments:
            if (not isinstance(segment, dict) or set(segment) != {
                    "pool", "first", "last", "manifest_sha256", "context_only"}
                    or not isinstance(segment["pool"], str)
                    or not segment["pool"].strip()
                    or type(segment["context_only"]) is not bool
                    or type(segment["first"]) is not int
                    or type(segment["last"]) is not int
                    or not 0 <= segment["first"] <= segment["last"]
                    or not _sha256_text(segment["manifest_sha256"])):
                raise ValueError("invalid development playlist segment")
            pool = (playlist.parent / segment["pool"]).resolve(strict=True)
            manifest_raw = (pool / "samples.json").read_bytes()
            if hashlib.sha256(manifest_raw).hexdigest() != segment["manifest_sha256"]:
                raise ValueError("development manifest hash mismatch")
            manifest = json.loads(manifest_raw.decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("audit_sha256") != audit:
                raise ValueError("development manifest audit mismatch")
            rows = manifest.get("samples")
            if (not isinstance(rows, list) or not rows
                    or any(not isinstance(row, dict) for row in rows)):
                raise ValueError("development manifest samples required")
            ids = [row.get("global_frame") for row in rows]
            if (any(type(frame) is not int or frame < 0 for frame in ids)
                    or ids != list(range(ids[0], ids[-1] + 1))):
                raise ValueError("contiguous unique ordered frames required")
            if any(row.get("role") != "development" for row in rows):
                raise ValueError("development frames only")
            by_frame = dict(zip(ids, rows))
            if segment["first"] not in by_frame or segment["last"] not in by_frame:
                raise ValueError("playlist range outside registered development frames")
            for frame in range(segment["first"], segment["last"] + 1):
                row = by_frame[frame]
                if previous_frame is not None and frame != previous_frame + 1:
                    raise ValueError("playlist source frame gap or overlap")
                filename = row.get("file")
                if (not isinstance(filename, str) or not filename
                        or not (pool / filename).resolve().is_relative_to(pool)
                        or not _sha256_text(row.get("sha256"))):
                    raise ValueError("invalid development frame path or hash")
                try:
                    value = row["pts_seconds"]
                    if isinstance(value, bool):
                        raise ValueError("boolean PTS")
                    pts = Decimal(str(value))
                    source_float = float(pts)
                    if (not pts.is_finite() or pts < 0
                            or not math.isfinite(source_float)
                            or previous_pts is not None and (
                                pts <= previous_pts or source_float <= previous_float)):
                        raise ValueError("unordered PTS")
                except (KeyError, InvalidOperation, TypeError, ValueError,
                        OverflowError):
                    raise ValueError(
                        "finite increasing development PTS required") from None
                selected.append((pool, row, segment["manifest_sha256"],
                                 segment["context_only"], source_float))
                previous_frame, previous_pts, previous_float = frame, pts, source_float
        self.frames = iter(selected)
        self.closed = False

    def read(self):
        from tools.aa8_action_transfer import load

        if self.closed:
            return None
        selected = next(self.frames, None)
        if selected is None:
            return None
        pool, row, manifest_sha, context_only, pts = selected
        return {"image": load(pool, row), "source_frame": row["global_frame"],
                "pts_seconds": pts, "source_pts_exact": str(row["pts_seconds"]),
                "source_kind": "development-replay", "source_id": self.source_id,
                "context_only": context_only, "source_pool": str(pool),
                "source_file": row["file"], "source_png_sha256": row["sha256"],
                "source_manifest_sha256": manifest_sha,
                "source_playlist_sha256": self.playlist_sha256}

    def close(self):
        self.closed = True


def source_factory(profile_path, *, replay_pool=None, replay_first=None,
                   replay_last=None, replay_playlist=None, allow_capture=False):
    """Browser cannot supply a filesystem path, normalization or audit identity."""
    if replay_playlist is not None and any(value is not None for value in (
            replay_pool, replay_first, replay_last)):
        raise ValueError("playlist cannot be combined with pool/range overrides")

    def create(options):
        mode = options.get("mode")
        if mode == "capture-card":
            if not allow_capture:
                raise ValueError("本次启动未启用采集卡；当前仅允许离线验证")
            return AACaptureSource(options)
        if mode == "development-replay" and (replay_pool is not None
                                             or replay_playlist is not None):
            spec = json.loads(Path(profile_path).read_text(encoding="utf-8"))
            if replay_playlist is not None:
                return AADevelopmentSequenceSource(replay_playlist, spec["audit"])
            return AADevelopmentSource(replay_pool, spec["audit"],
                                       first=replay_first, last=replay_last)
        raise ValueError("请选择本次启动已配置的来源")

    return create
