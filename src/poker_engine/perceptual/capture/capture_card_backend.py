"""UVC capture-card backend (calibration guide stage L — realtime backend).

Captures frames from an Android phone routed through a USB capture card
(``phone -> video adapter -> UVC capture card -> PC``). The card appears to the
host as a UVC video device and is read through OpenCV's ``VideoCapture``.

Platform notes (measured on a real setup):

- The GreenLian-style capture card only produces frames under Media Foundation
  (``CAP_MSMF``); DirectShow (``CAP_DSHOW``) returns black frames.
- On macOS the card is read through AVFoundation (``CAP_AVFOUNDATION``), which
  is the default API there; see :func:`default_capture_api`.
- YUY2 is preferred as the negotiated pixel format (``CAP_PROP_FOURCC``) to
  avoid MJPEG decode overhead and artifacts; OpenCV still hands frames back as
  BGR.
- A portrait phone screen is streamed as landscape content letterboxed into the
  UVC frame, so recognition must run on a *normalized* frame — see
  :mod:`poker_engine.perceptual.capture.normalization`.

This backend is the realtime capture half of the capture-card platform. It does
**not** claim the capture-card platform is calibrated: recognition calibration
(ROIs, thresholds, templates) is produced separately from real capture-card
recordings and remains ``UNKNOWN`` until that evidence exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
import sys
import time
from typing import Any, Callable

import numpy as np

from .base import CaptureError, CaptureTarget, CaptureService, Frame, WindowRect
from .normalization import NormalizationConfig, normalize
from .pixel_repeat import PixelRepeatObserver

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - dependency is pinned in pyproject
    cv2 = None

# API preference names -> cv2 backend constants. Resolved lazily so the module
# imports cleanly even where a given constant is not defined on the platform.
_API_NAMES = {"MSMF", "DSHOW", "AVFOUNDATION", "ANY"}

_CAP_CONSTANTS = {
    "MSMF": getattr(cv2, "CAP_MSMF", None) if cv2 is not None else None,
    "DSHOW": getattr(cv2, "CAP_DSHOW", None) if cv2 is not None else None,
    "AVFOUNDATION": (getattr(cv2, "CAP_AVFOUNDATION", None)
                     if cv2 is not None else None),
    "ANY": getattr(cv2, "CAP_ANY", None) if cv2 is not None else None,
}


def default_capture_api() -> str:
    """The capture API used when none is chosen: AVFoundation on macOS."""
    return "AVFOUNDATION" if sys.platform == "darwin" else "MSMF"


_VideoCaptureFactory = Callable[..., Any]


def _fourcc_code(code: str) -> int:
    """Convert a 4-character pixel-format code (e.g. ``"YUY2"``) to a FOURCC int."""
    return cv2.VideoWriter_fourcc(*code)


class CaptureCardBackend(CaptureService):
    """Read normalized frames from a UVC capture-card video device.

    ``CaptureTarget.window_id`` is *not* used to select the device — a backend
    instance is bound to exactly one device index at construction time, mirroring
    how :class:`AdbBackend` resolves one ADB serial. A target that names a
    different device index fails closed rather than silently switching devices.
    """

    def __init__(
        self,
        device_index: int = 0,
        api: str | None = None,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        fourcc: str | None = None,
        normalization: NormalizationConfig | None = None,
        detect_signal_loss: bool = True,
        video_capture_factory: _VideoCaptureFactory | None = None,
    ) -> None:
        super().__init__()
        if cv2 is None:
            raise RuntimeError("opencv-python is not installed")
        if isinstance(device_index, bool) or not isinstance(device_index, int):
            raise TypeError("device_index must be an int")
        if device_index < 0:
            raise ValueError("device_index must be >= 0")
        if api is None:
            api = default_capture_api()
        if api not in _API_NAMES:
            raise ValueError(f"api must be one of {sorted(_API_NAMES)}")
        for name, value in (("width", width), ("height", height), ("fps", fps)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
            if value <= 0:
                raise ValueError(f"{name} must be > 0")
        if fourcc is not None:
            if not isinstance(fourcc, str) or len(fourcc) != 4:
                raise ValueError("fourcc must be a 4-character string or None")
        if normalization is not None and not isinstance(
            normalization, NormalizationConfig
        ):
            raise TypeError("normalization must be a NormalizationConfig or None")
        if not isinstance(detect_signal_loss, bool):
            raise TypeError("detect_signal_loss must be a bool")

        self._device_index = device_index
        self._api = api
        self._width = width
        self._height = height
        self._fps = fps
        self._fourcc = fourcc
        self._normalization = normalization
        self._detect_signal_loss = detect_signal_loss
        self._factory = video_capture_factory or cv2.VideoCapture
        self._cap: Any | None = None
        self._pixel_repeat = PixelRepeatObserver()

    @property
    def pixel_repeat_evidence(self):
        """Last pixel observation, not proof of current source liveness."""
        return self._pixel_repeat.evidence

    @property
    def device_index(self) -> int:
        return self._device_index

    @property
    def normalization(self) -> NormalizationConfig | None:
        return self._normalization

    def _api_constant(self) -> int:
        const = _CAP_CONSTANTS.get(self._api)
        if const is None:
            # Media Foundation / DirectShow constants do not exist off Windows
            # (or on odd builds); fall back to the auto-detection backend.
            return _CAP_CONSTANTS["ANY"] if _CAP_CONSTANTS["ANY"] is not None else 0
        return const

    def _open(self) -> Any:
        if self._cap is not None:
            return self._cap
        cap = self._factory(self._device_index, self._api_constant())
        if cap is None or not cap.isOpened():
            raise CaptureError(
                f"could not open capture-card device index {self._device_index} "
                f"(api={self._api}); is the card connected and not in use by "
                f"another program?"
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        cap.set(cv2.CAP_PROP_FPS, self._fps)
        if self._fourcc is not None:
            cap.set(cv2.CAP_PROP_FOURCC, _fourcc_code(self._fourcc))
        self._cap = cap
        return cap

    def release(self) -> None:
        """Release the underlying device; safe to call multiple times."""
        self._pixel_repeat.reset()
        if self._cap is not None:
            try:
                self._cap.release()
            finally:
                self._cap = None

    def capture(self, target: CaptureTarget) -> Frame:
        if not isinstance(target, CaptureTarget):
            raise TypeError("target must be a CaptureTarget")
        # Per-seat window selection / fullscreen fallback do not apply to UVC
        # capture (same policy as the ADB backend).
        if target.window_index is not None or target.allow_fullscreen_fallback:
            raise CaptureError(
                "window_index/fullscreen fallback do not apply to capture-card "
                "capture"
            )
        requested = _parse_device_index(target.window_id)
        if requested is not None and requested != self._device_index:
            raise CaptureError(
                f"capture-card backend is bound to device index "
                f"{self._device_index}, not {requested}"
            )

        cap = self._open()
        ok, frame = cap.read()
        if not ok or frame is None:
            self.release()
            raise CaptureError(
                f"capture-card device {self._device_index} stopped producing "
                f"frames (disconnected or unplugged)"
            )
        if frame.size == 0:
            self.release()
            raise CaptureError(
                f"capture-card device {self._device_index} returned an empty frame"
            )

        image = np.asarray(frame)
        if self._detect_signal_loss and _is_black_frame(image):
            self._pixel_repeat.reset()
            raise CaptureError(
                f"capture-card device {self._device_index} reported signal loss "
                f"(all-black frame); re-plug the card and confirm the phone is "
                f"mirroring"
            )

        if self._normalization is not None:
            image = normalize(image, self._normalization)

        height, width = image.shape[:2]
        captured = Frame(
            frame_seq=self._next_seq(),
            timestamp=datetime.now(timezone.utc),
            window_id=f"uvc-{self._device_index}",
            window_rect=WindowRect(0, 0, width, height),
            image=image,
            width=width,
            height=height,
        )
        # Host receipt time/frame id is not an authoritative device sequence.
        # Track identical pixels for diagnostics, without rejecting static play.
        self._pixel_repeat.observe(captured.image, captured.frame_seq, time.monotonic())
        return captured


def _parse_device_index(window_id: str) -> int | None:
    """Parse an optional device index out of ``CaptureTarget.window_id``.

    Accepts a bare integer string (``"0"``) or the backend's own label form
    (``"uvc-0"``). Returns ``None`` for an empty / unrecognized identifier, so a
    caller can keep a human-readable id without implying a device switch.
    """
    if not window_id:
        return None
    text = window_id.strip()
    if text.lower().startswith("uvc-"):
        text = text[4:]
    if text.isdigit():
        return int(text)
    return None


def _is_black_frame(image: np.ndarray) -> bool:
    """True when every pixel is zero (the capture card's "no signal" state)."""
    if image.size == 0:
        return True
    return bool(int(image.min()) == 0 and int(image.max()) == 0)


__all__ = ["CaptureCardBackend", "NormalizationConfig"]
