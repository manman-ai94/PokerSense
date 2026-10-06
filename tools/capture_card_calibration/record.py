"""Stage A/B recording helpers for capture-card calibration.

This module is the *only* part of the toolkit that needs a real UVC device or
a video file, so it is the only place ``cv2`` is imported.

What it produces (guide sections 4 and 5):

- ``source/raw/<session_id>.mkv`` — the raw, **un-normalized** UVC stream.
  Normalization (stage C) is applied later, offline, so the recording must
  preserve exactly what the card produced and not pre-rotate / pre-crop.
- an updated ``source/device_and_capture.json`` whose ``uvc`` and ``recording``
  sections are filled from a live device probe.
- a per-session capture log (JSON lines) recording frame counts, timestamps
  and every signal event (disconnect / black frame / reconnect) so the
  ``reconnect`` / ``signal_loss`` evidence required by stage B is auditable.

Design note: the production :class:`CaptureCardBackend` is a single-frame
``capture()`` abstraction that re-opens the device on every call. Recording
must instead hold the device open and read continuously, so a live
``cv2.VideoCapture`` is managed directly here rather than going through that
backend.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - only needed with real hardware
    cv2 = None

from . import SCHEMA_VERSION
from .schema import DeviceAndCapture, SchemaError

_VideoCaptureFactory = Callable[..., Any]

# Four-byte pixel formats we will try, in preference order. YUY2 first: it is
# the measured-good format for GreenLian-style cards and avoids MJPEG decode
# overhead. Each is only *requested*; the card/OpenCV still decide what sticks.
_PREFERRED_FOURCC = ("YUY2", "MJPG", "NV12")

# Recording codecs, in preference order. Lossless intra-frame first (best for
# frame extraction later), then high-bitrate H.264/H.265 as the guide permits.
_RECORDING_CODECS = ("FFV1", "MJPG", "H264", "HEVC")


@dataclass(frozen=True)
class SignalEvent:
    """One recorded signal transition during a capture session."""

    event: str  # "start" | "black_frame" | "disconnect" | "reconnect" | "stop"
    timestamp_ms: int
    source_frame: int
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "timestamp_ms": self.timestamp_ms,
            "source_frame": self.source_frame,
            "detail": self.detail,
        }


@dataclass
class CaptureSessionLog:
    """Per-session capture metadata, written as JSON lines."""

    session_id: str
    started_at: str = ""
    ended_at: str = ""
    source_frames: int = 0
    written_frames: int = 0
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    fps_requested: int = 0
    events: list[SignalEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "source_frames": self.source_frames,
            "written_frames": self.written_frames,
            "duration_s": round(self.duration_s, 3),
            "width": self.width,
            "height": self.height,
            "fps_requested": self.fps_requested,
            "events": [event.to_dict() for event in self.events],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaptureSessionLog":
        return cls(
            session_id=data["session_id"],
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            source_frames=int(data.get("source_frames", 0)),
            written_frames=int(data.get("written_frames", 0)),
            duration_s=float(data.get("duration_s", 0.0)),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            fps_requested=int(data.get("fps_requested", 0)),
            events=[SignalEvent(**e) for e in data.get("events", ())],
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frame_timestamp_ms() -> int:
    return int(time.monotonic() * 1000)


def _is_black_frame(image: Any) -> bool:
    if image is None or image.size == 0:
        return True
    return bool(int(image.min()) == 0 and int(image.max()) == 0)


def resolve_api_constant(api: str) -> int:
    """Resolve a backend API name to a cv2 constant (MSMF/DSHOW/AVFOUNDATION/ANY)."""
    if cv2 is None:
        raise RuntimeError("opencv-python is not installed")
    name = api.upper()
    if name == "MSMF":
        return int(getattr(cv2, "CAP_MSMF", cv2.CAP_ANY))
    if name == "DSHOW":
        return int(getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY))
    if name == "AVFOUNDATION":
        return int(getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY))
    return int(getattr(cv2, "CAP_ANY", 0))


def probe_device(
    device_index: int = 0,
    api: str = "MSMF",
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    fourcc: str | None = None,
    video_capture_factory: _VideoCaptureFactory | None = None,
) -> dict[str, Any]:
    """Open a device, read one frame and report its negotiated parameters.

    Returns a dict suitable for merging into ``device_and_capture.json``'s
    ``uvc`` section: the *actual* frame size, the reported fps and the
    fourcc the card accepted. Raises :class:`SchemaError` when the device
    cannot be opened or yields no frame (fail closed, mirroring the backend).
    """
    if cv2 is None:
        raise RuntimeError("opencv-python is not installed")
    factory = video_capture_factory or cv2.VideoCapture
    cap = factory(device_index, resolve_api_constant(api))
    if cap is None or not cap.isOpened():
        raise SchemaError(
            f"could not open capture-card device index {device_index} "
            f"(api={api}); is the card connected and not in use elsewhere?"
        )
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        if fourcc is not None:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise SchemaError(
                f"capture-card device {device_index} produced no frame "
                f"(no signal or another program holds the device)"
            )
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = float(cap.get(cv2.CAP_PROP_FPS))
        actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        return {
            "frame_size": [actual_w, actual_h],
            "fps": round(actual_fps, 3),
            "pixel_format": _fourcc_to_str(actual_fourcc),
            "color_space": "",
            "color_range": "",
        }
    finally:
        cap.release()


def _fourcc_to_str(code: int) -> str:
    chars = "".join(chr((code >> (8 * shift)) & 0xFF) for shift in range(4))
    return chars.rstrip("\x00") or "unknown"


def _pick_writer_fourcc(video_writer_factory: Any, codec: str) -> int:
    try:
        return int(video_writer_factory(*codec))
    except TypeError:
        return int(video_writer_factory(*codec[:4]))


def record_session(
    output_path: Path | str,
    *,
    session_id: str,
    device_index: int = 0,
    api: str = "MSMF",
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    fourcc: str | None = "YUY2",
    codec: str | None = None,
    max_seconds: float | None = None,
    stop_on_eof: bool = False,
    video_capture_factory: _VideoCaptureFactory | None = None,
    video_writer_factory: Callable[..., int] | None = None,
    video_writer_class: Any | None = None,
    black_frame_threshold_ms: int = 2000,
) -> CaptureSessionLog:
    """Record a capture session to ``output_path`` while watching the signal.

    Reads frames continuously without re-opening the device. Every signal
    event (black frame, disconnect, reconnect) is appended to the returned
    :class:`CaptureSessionLog`, so stage B's ``signal_loss`` / ``reconnect``
    evidence is produced automatically and audibly in the log.

    ``black_frame_threshold_ms`` is how long an all-black read must persist
    before it is *reported* as a signal event (a single dropped frame is
    ignored). A black frame is never written to the output, so the recorded
    video contains only real picture.

    ``stop_on_eof`` ends the session when reading the device fails (instead of
    waiting for a reconnect). It is off by default, matching a live card that
    the operator stops with Ctrl+C after reconnecting; it is on for offline
    replay and tests where the frame source has a definite end.
    """
    if cv2 is None:
        raise RuntimeError("opencv-python is not installed")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    factory = video_capture_factory or cv2.VideoCapture
    writer_factory = video_writer_factory or cv2.VideoWriter_fourcc
    writer_class = video_writer_class or cv2.VideoWriter
    cap = factory(device_index, resolve_api_constant(api))
    if cap is None or not cap.isOpened():
        raise SchemaError(
            f"could not open capture-card device index {device_index} "
            f"(api={api}); is the card connected and not in use elsewhere?"
        )

    log = CaptureSessionLog(session_id=session_id, fps_requested=fps)
    writer: Any = None
    black_since: int | None = None
    disconnected = False
    start = time.monotonic()

    def _start_writer(frame_w: int, frame_h: int) -> None:
        nonlocal writer
        codec_name = codec or _select_codec(writer_factory)
        writer_code = _pick_writer_fourcc(writer_factory, codec_name)
        writer = writer_class(
            str(output), writer_code, float(fps), (frame_w, frame_h)
        )
        if not writer.isOpened():
            writer.release()
            raise SchemaError(
                f"could not open video writer for {output} with codec "
                f"{codec_name!r}; try a different --codec"
            )

    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        if fourcc is not None:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))

        log.started_at = _now_iso()
        log.events.append(
            SignalEvent("start", _frame_timestamp_ms(), 0, f"api={api}")
        )

        while True:
            if max_seconds is not None and time.monotonic() - start >= max_seconds:
                break
            ok, frame = cap.read()
            log.source_frames += 1

            if not ok or frame is None:
                if not disconnected:
                    disconnected = True
                    log.events.append(
                        SignalEvent(
                            "disconnect",
                            _frame_timestamp_ms(),
                            log.source_frames,
                            "read failed (device unplugged or no signal)",
                        )
                    )
                if stop_on_eof:
                    break
                # Back off before retrying so we do not spin on a dead device.
                time.sleep(0.05)
                continue

            if disconnected:
                disconnected = False
                log.events.append(
                    SignalEvent(
                        "reconnect",
                        _frame_timestamp_ms(),
                        log.source_frames,
                        "read resumed",
                    )
                )

            if _is_black_frame(frame):
                if black_since is None:
                    black_since = _frame_timestamp_ms()
                elif _frame_timestamp_ms() - black_since >= black_frame_threshold_ms:
                    log.events.append(
                        SignalEvent(
                            "black_frame",
                            _frame_timestamp_ms(),
                            log.source_frames,
                            f"all-black persisted {black_frame_threshold_ms}ms+",
                        )
                    )
                    black_since = None
                continue  # never write a signal-loss frame to disk

            black_since = None
            frame_h, frame_w = frame.shape[:2]
            if writer is None:
                _start_writer(frame_w, frame_h)
                log.width = frame_w
                log.height = frame_h
            writer.write(frame)
            log.written_frames += 1
    finally:
        if writer is not None:
            writer.release()
        cap.release()
        log.ended_at = _now_iso()
        log.duration_s = time.monotonic() - start
        log.events.append(
            SignalEvent("stop", _frame_timestamp_ms(), log.source_frames, "")
        )

    return log


def _select_codec(writer_factory: Callable[..., int]) -> str:
    """Pick the first codec whose fourcc the writer backend can build."""
    for codec in _RECORDING_CODECS:
        try:
            value = writer_factory(*codec)
            if value and int(value) not in (0, -1):
                return codec
        except (TypeError, ValueError):
            continue
    return "MJPG"


def write_session_log(path: Path | str, log: CaptureSessionLog) -> Path:
    """Write a session log as a single JSON object (per session)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(log.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return target


def update_device_manifest(
    root: Path | str,
    *,
    uvc: Mapping[str, Any],
    recording: Mapping[str, Any] | None = None,
    sessions: list[Mapping[str, Any]] | None = None,
) -> DeviceAndCapture:
    """Merge probed UVC / recording facts into ``device_and_capture.json``.

    Reads the existing manifest (which the operator filled in for the phone /
    adapter / card fields), overwrites only the ``uvc`` and ``recording``
    sections, appends session records, and writes it back. Returns the
    refreshed manifest so the caller can inspect ``require_ready()``.
    """
    root = Path(root)
    path = root / "source" / "device_and_capture.json"
    if not path.is_file():
        raise SchemaError(
            f"missing {path}; run `init` first and fill in the phone/adapter/"
            f"card fields"
        )
    device = DeviceAndCapture.from_json(path.read_text(encoding="utf-8"))

    updates: dict[str, Any] = {}
    updates["uvc"] = dict(device.uvc)
    for key, value in uvc.items():
        if value not in ("", None):
            updates["uvc"][key] = value
    if recording is not None:
        merged = dict(device.recording)
        merged.update(recording)
        updates["recording"] = merged
    if sessions is not None:
        existing = list(device.sessions)
        existing.extend(sessions)
        updates["sessions"] = existing

    refreshed = DeviceAndCapture(
        phone=dict(device.phone),
        app=dict(device.app),
        video_adapter=dict(device.video_adapter),
        capture_card=dict(device.capture_card),
        uvc=updates["uvc"],
        recording=updates.get("recording", dict(device.recording)),
        sessions=tuple(updates.get("sessions", list(device.sessions))),
        schema_version=SCHEMA_VERSION,
    )
    path.write_text(
        refreshed.to_json(),
        encoding="utf-8",
    )
    return refreshed


__all__ = [
    "CaptureSessionLog",
    "SignalEvent",
    "probe_device",
    "record_session",
    "resolve_api_constant",
    "update_device_manifest",
    "write_session_log",
]
