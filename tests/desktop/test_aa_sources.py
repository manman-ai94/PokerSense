import hashlib
import json
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from poker_engine.desktop.aa_sources import (
    AACaptureSource, AADevelopmentSequenceSource, AADevelopmentSource, source_factory,
)


def test_capture_is_lazy_and_uses_aa_canvas():
    calls = []

    class Backend:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def capture(self, target):
            calls.append(target.window_id)
            time.sleep(0.01)
            return SimpleNamespace(image=np.zeros((1080, 498, 3), np.uint8),
                                   frame_seq=8)

        def release(self):
            calls.append("released")

    src = AACaptureSource({"device_index": 2, "api": "DSHOW"},
                          backend_factory=Backend)
    assert len(calls) == 1
    assert calls[0]["normalization"].crop_after_rotation == (711, 0, 1209, 1080)
    record = src.read()
    assert record["source_frame"] == 8
    assert record["host_source_started_at"] <= record["host_source_received_at"]
    assert record["physical_source_timestamp"] is None
    assert record["source_clock"] == "host_monotonic_capture_call"
    assert calls[1] == "uvc-2"
    src.close()
    assert calls[-1] == "released"


@pytest.mark.parametrize("options, expected", [
    ({"api": "AVFOUNDATION"}, "AVFOUNDATION"),
    ({}, None),  # unset: the backend's platform default
])
def test_capture_api_choice_reaches_the_backend(options, expected):
    from poker_engine.perceptual.capture.capture_card_backend import (
        default_capture_api)
    seen = []

    def backend(**kwargs):
        seen.append(kwargs["api"])
        return SimpleNamespace(release=lambda: None)

    AACaptureSource(options, backend_factory=backend)
    assert seen == [expected or default_capture_api()]


@pytest.mark.parametrize("options", [{"device_index": True},
                                     {"device_index": -1}, {"api": "ANY"}])
def test_invalid_device_settings_never_construct_backend(options):
    def forbidden(**kwargs):
        pytest.fail("must reject before constructing backend")
    with pytest.raises(ValueError):
        AACaptureSource(options, backend_factory=forbidden)


def test_manifest_development_only_hash_bound_frames(tmp_path):
    _, encoded = cv2.imencode(".png", np.zeros((1080, 498, 3), np.uint8))
    data = encoded.tobytes()
    (tmp_path / "frame.png").write_bytes(data)
    manifest = {"audit_sha256": "audit", "samples": [
        {"global_frame": 10, "role": "development", "file": "frame.png",
         "sha256": hashlib.sha256(data).hexdigest(), "pts_seconds": "0.3"}]}
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(manifest))
    source = AADevelopmentSource(tmp_path, "audit")
    frame = source.read()
    assert frame["image"].shape == (1080, 498, 3)
    assert frame["pts_seconds"] == 0.3 and frame["source_pts_exact"] == "0.3"
    assert source.read() is None
    (tmp_path / "frame.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        AADevelopmentSource(tmp_path, "audit").read()
    manifest["samples"][0]["role"] = "holdout"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="development frames only"):
        AADevelopmentSource(tmp_path, "audit")


def test_hardware_disabled_by_default(tmp_path):
    factory = source_factory(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="未启用采集卡"):
        factory({"mode": "capture-card"})


def test_browser_cannot_select_arbitrary_replay(tmp_path):
    factory = source_factory(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="已配置"):
        factory({"mode": "development-replay", "path": str(tmp_path)})


def test_capture_thread_release_failure_reaches_session_owner(tmp_path):
    from poker_engine.desktop.aa_device_lock import AACaptureDeviceLock

    class Backend:
        def __init__(self, **kwargs):
            pass

        def capture(self, target):
            raise RuntimeError("capture failed")

        def release(self):
            raise RuntimeError("release failed")

    source = AACaptureSource({}, backend_factory=Backend, device_lock_factory=lambda:
                             AACaptureDeviceLock(tmp_path / "fake.lock",
                                                 legacy_lock_path=None))
    with pytest.raises(RuntimeError):
        source.read()
    with pytest.raises(RuntimeError, match="release failed"):
        source.close()


@pytest.fixture
def playlist(tmp_path):
    _, png = cv2.imencode(".png", np.zeros((1080, 498, 3), np.uint8))
    image_bytes = png.tobytes()
    segments = []
    for name, first, last in (("context", 8, 9), ("owned", 10, 11)):
        pool = tmp_path / name
        pool.mkdir()
        rows = []
        for frame in range(first, last + 1):
            filename = f"frame-{frame}.png"
            (pool / filename).write_bytes(image_bytes)
            rows.append({"global_frame": frame, "role": "development",
                         "file": filename,
                         "sha256": hashlib.sha256(image_bytes).hexdigest(),
                         "pts_seconds": str(frame / 30)})
        raw = json.dumps({"audit_sha256": "a" * 64, "samples": rows}).encode()
        (pool / "samples.json").write_bytes(raw)
        segments.append({"pool": name, "first": first, "last": last,
                         "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                         "context_only": name == "context"})
    path = tmp_path / "playlist.json"
    path.write_text(json.dumps({"schema_version": 1, "audit_sha256": "a" * 64,
                               "segments": segments}), encoding="utf-8")
    return path


def test_playlist_preserves_contiguous_frames_identity_and_context(playlist):
    source = AADevelopmentSequenceSource(playlist, "a" * 64)
    frames = [source.read() for _ in range(4)]
    assert [frame["source_frame"] for frame in frames] == [8, 9, 10, 11]
    assert [frame["context_only"] for frame in frames] == [True, True, False, False]
    assert len({frame["source_id"] for frame in frames}) == 1
    assert len({frame["source_manifest_sha256"] for frame in frames}) == 2
    assert all(frame["source_kind"] == "development-replay" for frame in frames)
    assert frames[2]["pts_seconds"] > frames[1]["pts_seconds"]
    assert source.read() is None


def test_playlist_factory_is_explicit_lazy_and_closes(playlist, tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"audit": "a" * 64}))
    factory = source_factory(profile, replay_playlist=playlist)
    source = factory({"mode": "development-replay"})
    source.close()
    assert source.read() is None
    with pytest.raises(ValueError, match="cannot be combined"):
        source_factory(profile, replay_playlist=playlist, replay_first=10)
    with pytest.raises(ValueError, match="cannot be combined"):
        source_factory(profile, replay_playlist=playlist, replay_pool=tmp_path)


@pytest.mark.parametrize("mutation,match", [
    ("manifest_hash", "manifest hash mismatch"), ("audit", "audit mismatch"),
    ("role", "development frames only"), ("gap", "frame gap or overlap"),
    ("overlap", "frame gap or overlap"), ("path", "frame path or hash"),
    ("nan", "increasing development PTS"), ("pts", "increasing development PTS"),
    ("bool", "increasing development PTS"),
])
def test_playlist_rejects_bad_metadata_before_any_image_read(
        playlist, mutation, match, monkeypatch):
    from tools import aa8_action_transfer
    monkeypatch.setattr(aa8_action_transfer, "load", lambda *args: pytest.fail(
        "metadata validation must precede image reads"))
    spec = json.loads(playlist.read_text())
    manifest_path = playlist.parent / "owned" / "samples.json"
    manifest = json.loads(manifest_path.read_text())
    if mutation == "manifest_hash":
        spec["segments"][1]["manifest_sha256"] = "b" * 64
    elif mutation == "audit":
        manifest["audit_sha256"] = "b" * 64
    elif mutation == "role":
        manifest["samples"][1]["role"] = "holdout"
    elif mutation == "gap":
        spec["segments"][1]["first"] = 11
    elif mutation == "overlap":
        spec["segments"][1] = spec["segments"][0].copy()
    elif mutation == "path":
        manifest["samples"][0]["file"] = "../outside.png"
    elif mutation in ("nan", "pts", "bool"):
        manifest["samples"][0]["pts_seconds"] = {
            "nan": "NaN", "pts": "0.1", "bool": True}[mutation]
    if mutation not in ("manifest_hash", "gap", "overlap"):
        raw = json.dumps(manifest).encode()
        manifest_path.write_bytes(raw)
        spec["segments"][1]["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    playlist.write_text(json.dumps(spec))
    with pytest.raises(ValueError, match=match):
        AADevelopmentSequenceSource(playlist, "a" * 64)


def test_playlist_checks_each_frame_hash_when_consumed(playlist):
    source = AADevelopmentSequenceSource(playlist, "a" * 64)
    (playlist.parent / "context" / "frame-8.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="frame path/hash mismatch"):
        source.read()


def test_playlist_passes_continuous_processed_sequence_and_identity_to_reader(playlist):
    from poker_engine.desktop.aa_session import AARecognitionSession
    calls = []

    class Reader:
        def read(self, image, frame, sample):
            calls.append((frame, sample))
            return {"strategy_eligible": False}

    session = AARecognitionSession(
        lambda _: AADevelopmentSequenceSource(playlist, "a" * 64), Reader,
        interval_seconds=0)
    session.start({"mode": "development-replay"})
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and session.snapshot()["status"] != "ENDED":
        time.sleep(.005)
    assert session.snapshot()["status"] == "ENDED"
    assert [frame for frame, _ in calls] == [0, 1, 2, 3]
    assert len({sample["source_id"] for _, sample in calls}) == 1
    assert [sample["source_frame"] for _, sample in calls] == [8, 9, 10, 11]


def full_frame(kind):
    """A 1920x1080 frame: the phone between black bars, a computer camera's
    picture (bright everywhere), or black."""
    frame = np.zeros((1080, 1920, 3), np.uint8)
    if kind == "phone":
        frame[:, 711:1209] = 120
    elif kind == "camera":
        frame[:] = 160
    return frame


def devices(shows):
    """A backend factory over devices {index: "phone" | "camera" | "black"};
    a device not listed cannot be opened. ``opened`` lists (index, normalized)."""
    opened = []

    class Backend:
        def __init__(self, device_index, normalization=None, **kwargs):
            if device_index not in shows:
                raise RuntimeError(f"could not open capture-card device index "
                                   f"{device_index} (api=AVFOUNDATION)")
            opened.append((device_index, normalization is not None))
            self.index, self.normalization, self.seq = device_index, normalization, 0

        def capture(self, target):
            assert target.window_id == f"uvc-{self.index}"
            time.sleep(0.005)
            self.seq += 1
            frame = full_frame(shows[self.index])
            if self.normalization is not None:
                frame = frame[:, 711:1209]
            return SimpleNamespace(image=frame, frame_seq=self.seq)

        def release(self):
            pass

    return Backend, opened


def test_the_capture_source_finds_the_device_that_shows_the_phone(monkeypatch):
    # The Mac's camera is device 0 and the card device 2; the box said 0.
    backend, opened = devices({0: "camera", 1: "black", 2: "phone"})
    monkeypatch.setattr("poker_engine.desktop.aa_sources.LOOK_SECONDS", 0.05)
    source = AACaptureSource({"device_index": 0, "api": "AVFOUNDATION",
                              "find_phone": True}, backend_factory=backend)
    try:
        record = source.read()
        assert record["image"].shape == (1080, 498, 3)
        assert source.device == {
            "device_index": 2, "api": "AVFOUNDATION",
            "device_check": "phone_between_black_bars",
            "device_seen": {"0": "other", "1": "dark", "2": "phone"}}
        # Looked at 0, 1 and 2 whole, then reads 2 as the phone strip.
        assert opened[1:] == [(0, False), (1, False), (2, False), (2, True)]
    finally:
        source.close()


def test_the_chosen_device_is_looked_at_first():
    backend, opened = devices({0: "camera", 1: "phone"})
    source = AACaptureSource({"device_index": 1, "find_phone": True},
                             backend_factory=backend)
    try:
        source.read()
        assert source.device["device_index"] == 1
        assert source.device["device_seen"] == {"1": "phone"}
        assert opened == [(1, True), (1, False)]
    finally:
        source.close()


def test_without_the_phone_the_chosen_device_is_used_and_said_so():
    backend, _ = devices({0: "camera"})
    source = AACaptureSource({"device_index": 0, "find_phone": True},
                             backend_factory=backend)
    try:
        source.read()
        assert source.device["device_index"] == 0
        assert source.device["device_check"] == "no_phone_found"
        assert source.device["device_seen"] == {"0": "other", "1": None, "2": None,
                                                "3": None}
    finally:
        source.close()


def test_a_chosen_card_without_a_picture_is_kept_and_the_camera_left_alone(monkeypatch):
    # The phone is locked: the card (chosen, device 1) stays black.
    backend, opened = devices({0: "camera", 1: "black"})
    monkeypatch.setattr("poker_engine.desktop.aa_sources.LOOK_SECONDS", 0.05)
    source = AACaptureSource({"device_index": 1, "find_phone": True},
                             backend_factory=backend)
    try:
        source.read()
        assert source.device["device_index"] == 1
        assert source.device["device_check"] == "no_phone_found"
        assert source.device["device_seen"] == {"1": "dark"}
        assert 0 not in [index for index, _ in opened]
    finally:
        source.close()


def test_a_black_card_that_starts_showing_the_phone_says_so(monkeypatch):
    shows = {0: "camera", 1: "black"}
    backend, _ = devices(shows)
    monkeypatch.setattr("poker_engine.desktop.aa_sources.LOOK_SECONDS", 0.05)
    source = AACaptureSource({"device_index": 1, "find_phone": True},
                             backend_factory=backend)
    try:
        source.read()
        assert source.device["device_check"] == "no_phone_found"
        shows[1] = "phone"                  # the phone is unlocked and mirrors
        deadline = time.monotonic() + 2
        while (source.device["device_check"] == "no_phone_found"
               and time.monotonic() < deadline):
            source.read()
        assert source.device["device_check"] == "phone_between_black_bars"
        assert source.device["device_seen"] == {"1": "phone"}
    finally:
        source.close()


def test_without_the_phone_a_black_card_is_used_rather_than_the_camera(monkeypatch):
    backend, opened = devices({0: "camera", 1: "black"})
    monkeypatch.setattr("poker_engine.desktop.aa_sources.LOOK_SECONDS", 0.05)
    source = AACaptureSource({"device_index": 0, "find_phone": True},
                             backend_factory=backend)
    try:
        source.read()
        assert source.device["device_index"] == 1
        assert source.device["device_seen"] == {"0": "other", "1": "dark", "2": None,
                                                "3": None}
        assert opened[-1] == (1, True)          # reads the card, not the camera
    finally:
        source.close()


def test_without_find_phone_no_other_device_is_opened():
    backend, opened = devices({0: "camera", 1: "phone"})
    source = AACaptureSource({"device_index": 0}, backend_factory=backend)
    try:
        source.read()
        assert opened == [(0, True)] and "device_check" not in source.device
    finally:
        source.close()
    with pytest.raises(ValueError):
        AACaptureSource({"find_phone": "yes"}, backend_factory=backend)


def test_a_device_the_mac_does_not_have_is_said_in_plain_words():
    class Missing:
        def __init__(self, **kwargs):
            pass

        def capture(self, target):
            raise RuntimeError("could not open capture-card device index 1 "
                               "(api=AVFOUNDATION); is the card connected and not "
                               "in use by another program?")

        def release(self):
            pass

    source = AACaptureSource({"device_index": 1}, backend_factory=Missing)
    with pytest.raises(RuntimeError, match="^Mac 没认到采集卡"):
        source.read()
    source.close()


def test_the_camera_list_names_what_macos_lists():
    from poker_engine.desktop.aa_sources import CameraList

    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps({"SPCameraDataType": [
            {"_name": "FaceTime HD Camera"}, {"_name": "USB Video"}]}))

    def settles(predicate):
        deadline = time.monotonic() + 2
        while not predicate():
            assert time.monotonic() < deadline
            time.sleep(0.005)

    now = [0.0]
    cameras = CameraList(run=run, platform="darwin", clock=lambda: now[0])
    assert cameras.names() is None                  # read on a thread
    settles(lambda: cameras.names() == ["FaceTime HD Camera", "USB Video"])
    assert calls == [["system_profiler", "-json", "SPCameraDataType"]]
    now[0] = 11                                     # read again after 10 s
    cameras.names()
    settles(lambda: len(calls) == 2)
    assert CameraList(run=run, platform="linux").names() is None

    def broken(args, **kwargs):
        raise OSError("no system_profiler")

    failing = CameraList(run=broken, platform="darwin")
    failing.refresh()
    assert failing.names() is None
