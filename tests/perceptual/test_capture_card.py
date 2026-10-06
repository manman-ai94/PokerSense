"""Tests for the UVC capture-card backend and stage-C normalization."""

from __future__ import annotations

import json

import numpy as np
import pytest

from poker_engine.perceptual import (
    CaptureCardBackend,
    CaptureError,
    CaptureTarget,
    NormalizationConfig,
    normalize,
)


# --------------------------------------------------------------------------
# NormalizationConfig validation + serialization
# --------------------------------------------------------------------------

def test_normalization_config_rejects_invalid_rotation():
    with pytest.raises(ValueError):
        NormalizationConfig(rotate_degrees=45)
    with pytest.raises(ValueError):
        NormalizationConfig(rotate_degrees=360)


def test_normalization_config_rejects_empty_crop():
    with pytest.raises(ValueError):
        NormalizationConfig(
            rotate_degrees=0, crop_after_rotation=(10, 10, 10, 20)
        )


def test_normalization_config_rejects_invalid_color_transform():
    with pytest.raises(ValueError):
        NormalizationConfig(rotate_degrees=0, color_transform="auto")


def test_normalization_config_json_roundtrip():
    cfg = NormalizationConfig(
        rotate_degrees=90,
        mirror_horizontal=True,
        source_size=(1920, 1080),
        crop_after_rotation=(0, 0, 1080, 1920),
        output_size=(1080, 1920),
    )
    assert NormalizationConfig.from_json(cfg.to_json()) == cfg


def test_normalization_config_rejects_unsupported_schema():
    with pytest.raises(ValueError):
        NormalizationConfig.from_dict(
            {"schema_version": 99, "rotate_degrees": 0}
        )


# --------------------------------------------------------------------------
# normalize() pure transform
# --------------------------------------------------------------------------

def test_normalize_rotate_90_counterclockwise():
    # A 2x3 BGR image (height=2, width=3): the top-left pixel is red.
    img = np.zeros((2, 3, 3), dtype=np.uint8)
    img[0, 0] = (0, 0, 255)  # BGR red at row0,col0
    out = normalize(img, NormalizationConfig(rotate_degrees=90))
    # 90 CCW: (h,w) -> (w,h); original top-left goes to bottom-left.
    assert out.shape == (3, 2, 3)
    assert tuple(out[2, 0]) == (0, 0, 255)


def test_normalize_mirror_horizontal():
    img = np.zeros((1, 3, 3), dtype=np.uint8)
    img[0, 0] = (1, 2, 3)
    out = normalize(img, NormalizationConfig(rotate_degrees=0, mirror_horizontal=True))
    assert tuple(out[0, 2]) == (1, 2, 3)


def test_normalize_crop_and_output_size():
    img = np.full((4, 4, 3), 7, dtype=np.uint8)
    out = normalize(
        img,
        NormalizationConfig(
            rotate_degrees=0,
            crop_after_rotation=(1, 1, 3, 3),
            output_size=(2, 2),
        ),
    )
    assert out.shape == (2, 2, 3)
    assert out.min() == 7


def test_normalize_source_size_mismatch_fails():
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    with pytest.raises(CaptureError, match="source size"):
        normalize(
            img, NormalizationConfig(rotate_degrees=0, source_size=(999, 999))
        )


def test_normalize_output_size_mismatch_fails():
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    with pytest.raises(CaptureError, match="normalized size"):
        normalize(
            img, NormalizationConfig(rotate_degrees=0, output_size=(5, 5))
        )


def test_normalize_crop_out_of_bounds_fails():
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    with pytest.raises(CaptureError, match="exceeds"):
        normalize(
            img,
            NormalizationConfig(rotate_degrees=0, crop_after_rotation=(0, 0, 9, 9)),
        )


# --------------------------------------------------------------------------
# CaptureCardBackend with a mocked VideoCapture
# --------------------------------------------------------------------------

class _FakeCap:
    """Minimal stand-in for cv2.VideoCapture."""

    def __init__(self, frames, opened=True, read_results=None):
        self._frames = list(frames)
        self._opened = opened
        self._read_results = read_results
        self._calls = 0
        self.released = False
        self.props = {}

    def isOpened(self):
        return self._opened

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def read(self):
        if self._read_results is not None:
            return self._read_results
        if self._calls < len(self._frames):
            frame = self._frames[self._calls]
            self._calls += 1
            return True, frame
        return False, None

    def release(self):
        self.released = True


def _backend(frames, **kwargs):
    cap = _FakeCap(frames)
    backend = CaptureCardBackend(
        video_capture_factory=lambda idx, api: cap, **kwargs
    )
    return backend, cap


def test_backend_captures_frame_with_monotonic_seq():
    frame = np.full((8, 6, 3), 23, dtype=np.uint8)
    backend, _ = _backend([frame, frame])
    target = CaptureTarget(window_id="uvc-0")
    f1 = backend.capture(target)
    f2 = backend.capture(target)
    assert f1.frame_seq == 0
    assert f2.frame_seq == 1
    assert f1.window_id == "uvc-0"
    assert f1.image.shape == (8, 6, 3)


def test_backend_open_failure_raises():
    cap = _FakeCap([], opened=False)
    backend = CaptureCardBackend(video_capture_factory=lambda idx, api: cap)
    with pytest.raises(CaptureError, match="could not open"):
        backend.capture(CaptureTarget(window_id="0"))


def test_backend_disconnect_raises_and_releases():
    cap = _FakeCap([], read_results=(False, None))
    backend = CaptureCardBackend(video_capture_factory=lambda idx, api: cap)
    with pytest.raises(CaptureError, match="disconnected"):
        backend.capture(CaptureTarget(window_id="0"))
    assert cap.released is True


def test_backend_signal_loss_black_frame_raises():
    frame = np.zeros((8, 6, 3), dtype=np.uint8)
    backend, _ = _backend([frame], detect_signal_loss=True)
    with pytest.raises(CaptureError, match="signal loss"):
        backend.capture(CaptureTarget(window_id="0"))


def test_backend_black_frame_ok_when_signal_loss_disabled():
    frame = np.zeros((8, 6, 3), dtype=np.uint8)
    backend, _ = _backend([frame], detect_signal_loss=False)
    out = backend.capture(CaptureTarget(window_id="0"))
    assert out.image.shape == (8, 6, 3)


def test_backend_applies_normalization():
    frame = np.full((2, 3, 3), 23, dtype=np.uint8)
    cfg = NormalizationConfig(rotate_degrees=90, output_size=(2, 3))
    backend, _ = _backend([frame], normalization=cfg)
    out = backend.capture(CaptureTarget(window_id="0"))
    assert out.image.shape == (3, 2, 3)


def test_backend_rejects_different_device_index():
    backend, _ = _backend([np.zeros((2, 2, 3), np.uint8)])
    with pytest.raises(CaptureError, match="bound to device index 0"):
        backend.capture(CaptureTarget(window_id="3"))


def test_backend_rejects_window_index_and_fallback():
    backend, _ = _backend([np.zeros((2, 2, 3), np.uint8)])
    with pytest.raises(CaptureError, match="do not apply"):
        backend.capture(CaptureTarget(window_id="0", window_index=1))
    with pytest.raises(CaptureError, match="do not apply"):
        backend.capture(
            CaptureTarget(window_id="0", allow_fullscreen_fallback=True)
        )


def test_backend_sets_requested_properties():
    cap = _FakeCap([np.full((2, 2, 3), 5, np.uint8)])
    backend = CaptureCardBackend(
        video_capture_factory=lambda idx, api: cap,
        width=1280,
        height=720,
        fps=60,
        fourcc="YUY2",
    )
    backend.capture(CaptureTarget(window_id="0"))
    import cv2

    assert cap.props[cv2.CAP_PROP_FRAME_WIDTH] == 1280
    assert cap.props[cv2.CAP_PROP_FRAME_HEIGHT] == 720
    assert cap.props[cv2.CAP_PROP_FPS] == 60
    assert cap.props[cv2.CAP_PROP_FOURCC] == cv2.VideoWriter_fourcc(*"YUY2")


def test_backend_constructor_validation():
    with pytest.raises(ValueError):
        CaptureCardBackend(device_index=-1)
    with pytest.raises(ValueError):
        CaptureCardBackend(api="V4L2")
    with pytest.raises(ValueError):
        CaptureCardBackend(fourcc="YUV")
    with pytest.raises(ValueError):
        CaptureCardBackend(width=0)
    with pytest.raises(TypeError):
        CaptureCardBackend(normalization="not-a-config")


@pytest.mark.parametrize("platform, expected", [
    ("darwin", "AVFOUNDATION"), ("win32", "MSMF"), ("linux", "MSMF")])
def test_default_capture_api_follows_the_platform(monkeypatch, platform, expected):
    from poker_engine.perceptual.capture import capture_card_backend as module
    monkeypatch.setattr(module.sys, "platform", platform)
    assert module.default_capture_api() == expected


@pytest.mark.parametrize("api, platform", [
    ("AVFOUNDATION", "win32"),  # explicit choice wins on any platform
    (None, "darwin"),           # no choice: macOS default
])
def test_backend_opens_avfoundation(monkeypatch, api, platform):
    import cv2
    from poker_engine.perceptual.capture import capture_card_backend as module
    monkeypatch.setattr(module.sys, "platform", platform)
    opened = []
    cap = _FakeCap([np.full((8, 6, 3), 23, dtype=np.uint8)])
    backend = CaptureCardBackend(
        api=api,
        video_capture_factory=lambda idx, api: opened.append(api) or cap)
    backend.capture(CaptureTarget(window_id="uvc-0"))
    assert opened == [cv2.CAP_AVFOUNDATION]


def test_parse_device_index_forms():
    from poker_engine.perceptual.capture.capture_card_backend import (
        _parse_device_index,
    )

    assert _parse_device_index("0") == 0
    assert _parse_device_index("uvc-3") == 3
    assert _parse_device_index("UVC-2") == 2
    assert _parse_device_index("") is None
    assert _parse_device_index("front-camera") is None


# --------------------------------------------------------------------------
# Platform calibration state (cards calibrated; legacy path stays closed)
# --------------------------------------------------------------------------

def test_capture_card_platform_calibration_state():
    """Cards are calibrated (gray-fused-mlp-v3); legacy path stays closed.

    The platform graduated from the uncalibrated scaffold on 2026-09-04:
    the fused card measurement is real evidence, but the legacy
    single-frame card path must remain fail-closed (floor=1.0) so nothing
    can accidentally serve the old matcher with a loosened gate, and no
    geometry/threshold may be inherited from LDPlayer/H5.
    """
    import hashlib
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    vision = repo_root / "configs" / "vision" / "wepoker_android_capture_card"
    data = json.loads((vision / "calibration.json").read_text(encoding="utf-8"))
    assert data["platform_id"] == "wepoker_android_capture_card"
    assert data["status"] == "calibrated"
    # legacy single-frame template source stays "wepoker" (guide rule 2:
    # card ART templates may be shared after independent verification); the
    # fused pipeline uses its own card_heads.npz, not these templates.
    assert data["template_source"] == "wepoker"

    legacy = data["card"]
    assert legacy["readable_score_floor"] == 1.0
    assert legacy["unreadable_score_ceiling"] == 1.0

    fused = data["card_fused"]
    assert fused["validation_correct"] == fused["validation_positive_samples"]
    assert fused["false_valid"] == 0
    assert 0.0 <= fused["rank_floor"] <= 1.0
    assert 0.0 < fused["suit_floor"] <= 1.0
    heads = vision / fused["models"]
    assert heads.is_file()
    digest = hashlib.sha256(heads.read_bytes()).hexdigest()
    assert digest == fused["models_sha256"]


def test_capture_card_backend_exported_from_package():
    import poker_engine.perceptual as p
    import poker_engine.perceptual.capture as c

    assert hasattr(p, "CaptureCardBackend")
    assert hasattr(p, "NormalizationConfig")
    assert hasattr(p, "normalize")
    assert hasattr(c, "CaptureCardBackend")
