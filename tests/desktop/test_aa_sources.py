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
