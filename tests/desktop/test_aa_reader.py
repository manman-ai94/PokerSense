"""AA8 session adapter checks without private assets or capture devices."""

import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from poker_engine.desktop.aa_reader import AA8Reader, preflight_profile


@pytest.fixture
def profile(tmp_path):
    spec = {"audit": "a" * 64}
    for key in ("source", "context_source", "late_source", "bomb_pool"):
        folder = tmp_path / key
        folder.mkdir()
        (folder / "samples.json").write_text("{}", encoding="utf-8")
        spec[key] = key
    for key in ("bank_path", "profile_path", "heads_path", "reservations"):
        (tmp_path / key).write_text("{}", encoding="utf-8")
        spec[key] = key
    (tmp_path / "profile_path").write_text(json.dumps({
        "canvas": [498, 1080], "hero_slot": 4,
        "slots": [{"slot": i} for i in range(8)]}), encoding="utf-8")
    path = tmp_path / "reader.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


class Scene:
    def recognize(self, image):
        return {"scene": "AA_TABLE_CANDIDATE"}


class Modes:
    def recognize(self, image):
        return {"block_state_updates": False,
                "insurance": "VISIBLE" if image[0, 0, 0] else "UNKNOWN"}


class Glyphs:
    scene = Scene()

    def recognize(self, image):
        return {str(i): "call" if i == 0 else None for i in range(8)}


class Candidate:
    def __init__(self, spec):
        self.p = math  # Real FrozenPredictionState retains a pipeline module.
        self.audit = spec["audit"]
        self.reader, self.modes = Glyphs(), Modes()
        self.profile = {}
        self.count = 0

    def read(self, image, frame, sample):
        assert self.p is math
        self.count += 1
        glyphs = self.reader.recognize(image)
        return {"frame": frame, "source_sha256": sample["sha256"],
                "cards": {"source": self.audit}, "count": self.count,
                "glyph_transitions": self.tracker.observe(frame, glyphs),
                "glyphs": glyphs, "strategy_eligible": False}


@pytest.fixture
def image():
    return np.zeros((1080, 498, 3), dtype=np.uint8)


def test_preflight_resolves_relative_paths_without_loading_models(profile, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preflight must not load models")
    monkeypatch.setattr(np, "load", forbidden)
    result = preflight_profile(profile)
    assert result["ready"] and result["errors"] == []
    assert result["paths"]["bank_path"] == str(profile.parent / "bank_path")
    assert result["strategy_eligible"] is False


@pytest.mark.parametrize("change", [
    {"audit": True}, {"bank_path": 7}, {"module": "arbitrary.code"},
    {"glyph_supplement": {}}, {"glyph_supplement": [{"label": "fold"}]},
])
def test_invalid_profile_rejected_before_factory(profile, change):
    spec = json.loads(profile.read_text())
    spec.update(change)
    profile.write_text(json.dumps(spec))
    called = []
    with pytest.raises(ValueError):
        AA8Reader(profile, factory=lambda spec: called.append(spec))
    assert not called


def test_missing_assets_and_nine_slot_layout_fail(profile):
    (profile.parent / "bank_path").unlink()
    layout = {"canvas": [498, 1080], "hero_slot": 5,
              "slots": [{"slot": i} for i in range(9)]}
    (profile.parent / "profile_path").write_text(json.dumps(layout))
    result = preflight_profile(profile)
    assert not result["ready"]
    assert "missing_file:bank_path" in result["errors"]
    assert "aa8_hero4_layout_required" in result["errors"]


def test_target_identity_hash_and_temporal_events(profile, image):
    reader = AA8Reader(profile, factory=Candidate)
    first = reader.read(image, 0, {"pts_seconds": 0, "source_id": "new-session"})
    second = reader.read(image, 1, {"pts_seconds": .1, "source_id": "new-session"})
    assert first["glyph_transitions"] == []
    assert second["glyph_transitions"] == [{"frame": 1, "slot": 0, "glyph": "call"}]
    assert first["cards"]["source"] == "new-session"
    assert first["training_audit_sha256"] == "a" * 64
    assert first["source_sha256"] == hashlib.sha256(image.tobytes()).hexdigest()
    assert first["candidate_only"] is True
    assert first["strategy_eligible"] is False
    assert first["complete_legal_state"] is False


def test_perception_validation_disables_strategy_sidecar(profile, image, monkeypatch):
    from poker_engine.desktop import aa_river_strategy

    def forbidden(row):
        raise AssertionError("perception validation must not execute strategy")

    monkeypatch.setattr(aa_river_strategy, "current_river_study", forbidden)
    reader = AA8Reader(profile, factory=Candidate, analysis_enabled=False)
    row = reader.read(image, 0, {"pts_seconds": 0, "source_id": "test"})
    assert row["river_strategy_v1"]["status"] == "ANALYSIS_DISABLED"
    assert row["critical_perception_v1"]["candidate_only"] is True


@pytest.mark.parametrize("next_frame,next_pts,next_source", [
    (2, .1, "session"), (1, 1.1, "session"), (0, 0, "new-session"),
])
def test_gap_or_source_change_resets_without_reloading_factory(
        profile, image, next_frame, next_pts, next_source):
    calls = []

    def factory(spec):
        calls.append(spec)
        return Candidate(spec)

    reader = AA8Reader(profile, factory=factory)
    reader.read(image, 0, {"pts_seconds": 0, "source_id": "session"})
    row = reader.read(image, next_frame, {
        "pts_seconds": next_pts, "source_id": next_source})
    assert row["reader_gap_reset"] is True
    assert row["count"] == 1 and row["glyph_transitions"] == []
    assert len(calls) == 1


class SeatCandidate(Candidate):
    """Readable table where seat 2 shows the fold badge only at time zero."""

    def read(self, image, frame, sample):
        row = super().read(image, frame, sample)
        fold = sample["pts_seconds"] == 0
        row.update(scene_supported=True, special_modes={},
                   glyphs={str(i): "fold" if i == 2 and fold else None
                           for i in range(8)})
        return row


def test_seat_states_follow_reads_and_reset_on_gaps(profile, image):
    reader = AA8Reader(profile, factory=SeatCandidate)
    first = reader.read(image, 0, {"pts_seconds": 0, "source_id": "session"})
    assert first["seat_cues_v1"] is None   # test candidate has no seat reader
    assert first["seat_states_v1"]["seats"]["2"]["state"] == "folded"
    held = reader.read(image, 1, {"pts_seconds": .5, "source_id": "session"})
    assert held["seat_states_v1"]["seats"]["2"]["state"] == "folded"
    after_gap = reader.read(image, 5, {"pts_seconds": .6, "source_id": "session"})
    assert after_gap["reader_gap_reset"] is True
    assert after_gap["seat_states_v1"]["seats"]["2"]["state"] == "unknown"


class BoardCandidate(Candidate):
    """A readable table on the flop. A frame reading that starts over shows
    no board card on its first two frames, as the real one needs a few
    frames before the cards agree."""

    def read(self, image, frame, sample):
        row = super().read(image, frame, sample)
        board = ["Ah", "7c", "2s", None, None] if self.count > 2 else [None] * 5
        row.update(scene_supported=True, special_modes={}, pot={"value": "70"},
                   cards={"source": self.audit, "board_slots": board,
                          "hero": ["Kd", "Kc"]})
        return row


def test_a_stall_keeps_the_street_and_the_hand(profile, image):
    reader = AA8Reader(profile, factory=BoardCandidate)
    rows = [reader.read(image, i, {"pts_seconds": i / 10, "source_id": "session"})
            for i in range(5)]
    assert rows[-1]["street_v1"]["street"] == "flop"
    hand = rows[-1]["action_history_v1"]["hand_id"]
    # One frame took 1.5 s: the frame reading starts over and misses the
    # board for two frames, while the flop and the hand go on.
    stalled = [reader.read(image, 5 + i, {"pts_seconds": 1.9 + i / 10,
                                          "source_id": "session"})
               for i in range(3)]
    assert stalled[0]["reader_gap_reset"] is True and stalled[0]["count"] == 1
    assert [row["street_v1"]["street"] for row in stalled] == ["flop"] * 3
    assert {row["action_history_v1"]["hand_id"] for row in stalled} == {hand}
    # After a gap of more than HAND_GAP_SECONDS the hand counts as joined in
    # the middle.
    late = reader.read(image, 8, {"pts_seconds": 5.5, "source_id": "session"})
    assert late["action_history_v1"]["hand_id"] != hand
    assert late["action_history_v1"]["complete"] is False


def test_insurance_suspends_streak(profile, image):
    reader = AA8Reader(profile, factory=Candidate)
    reader.read(image, 0, {"pts_seconds": 0})
    overlay = image.copy()
    overlay[0, 0, 0] = 1
    hidden = reader.read(overlay, 1, {"pts_seconds": .1})
    assert hidden["glyph_transitions"] == []
    assert all(v is None for v in hidden["glyphs"].values())
    assert reader.read(image, 2, {"pts_seconds": .2})["glyph_transitions"] == []
    assert len(reader.read(image, 3, {"pts_seconds": .3})["glyph_transitions"]) == 1


@pytest.mark.parametrize("bad_frame,bad_sample", [
    (0, {"pts_seconds": .1}), (1, {"pts_seconds": 0}),
    (True, {"pts_seconds": .1}), (1, {"pts_seconds": float("nan")}),
    (1, {"pts_seconds": .1, "source_id": ""}),
])
def test_bad_sequence_invalidates_temporal_evidence(
        profile, image, bad_frame, bad_sample):
    reader = AA8Reader(profile, factory=Candidate)
    reader.read(image, 0, {"pts_seconds": 0})
    with pytest.raises(ValueError):
        reader.read(image, bad_frame, bad_sample)
    row = reader.read(image, 1, {"pts_seconds": .1})
    assert row["reader_gap_reset"] and row["glyph_transitions"] == []


@pytest.mark.parametrize("shape,dtype", [
    ((1080, 1920, 3), np.uint8), ((1080, 498, 3), np.float32),
])
def test_bad_canvas_rejected(profile, shape, dtype):
    reader = AA8Reader(profile, factory=Candidate)
    with pytest.raises(ValueError, match="aa8_uint8_bgr"):
        reader.read(np.zeros(shape, dtype=dtype), 0, {"pts_seconds": 0})


def test_supplement_hash_checked_before_decoding(profile, monkeypatch):
    spec = json.loads(profile.read_text())
    spec["glyph_supplement"] = [
        {"label": label, "path": "bank_path", "slot": i, "sha256": "b" * 64}
        for i, label in enumerate(("fold", "muck", "all_in"))]
    profile.write_text(json.dumps(spec))
    from tools import wpk_video_dataset
    monkeypatch.setattr(wpk_video_dataset, "read_image", lambda path: pytest.fail(
        "mismatched reference must not be decoded"))
    with pytest.raises(ValueError, match="glyph_reference_hash_mismatch"):
        AA8Reader(profile, factory=Candidate)


def test_supplement_precedes_transition_and_is_copied_on_reset(
        profile, monkeypatch, image):
    from tools import aa8_glyph_supplement_v3, wpk_video_dataset
    spec = json.loads(profile.read_text())
    digest = hashlib.sha256((profile.parent / "bank_path").read_bytes()).hexdigest()
    spec["glyph_supplement"] = [
        {"label": label, "path": "bank_path", "slot": i, "sha256": digest}
        for i, label in enumerate(("fold", "muck", "all_in"))]
    profile.write_text(json.dumps(spec))
    monkeypatch.setattr(wpk_video_dataset, "read_image", lambda path: image)

    def supplement(profile, images):
        assert set(images) == {"fold", "muck", "all_in"}
        return SimpleNamespace(recognize=lambda im, base, supported: {
            **base, "0": "all_in"})

    monkeypatch.setattr(aa8_glyph_supplement_v3, "GlyphSupplementV3", supplement)
    reader = AA8Reader(profile, factory=Candidate)
    reader.read(image, 0, {"pts_seconds": 0})
    row = reader.read(image, 1, {"pts_seconds": .1})
    assert row["glyph_transitions"][0]["glyph"] == "all_in"
    row = reader.read(image, 3, {"pts_seconds": .3})
    assert row["glyphs"]["0"] == "all_in" and not row["glyph_transitions"]


def test_the_window_reads_the_pot_at_a_looser_label_match(monkeypatch):
    from types import ModuleType
    import tools.aa8_unmarked_money as money
    from poker_engine.desktop import aa_reader
    seen = []

    def pot_patch(image, prefix, threshold=.90):
        seen.append(threshold)
        return np.full((4, 4), prefix, np.uint8)

    monkeypatch.setattr(money, "pot_patch", pot_patch)
    frozen = ModuleType("pipeline")
    frozen.unique_pot_patch, frozen.region = "frozen", "kept"
    live = aa_reader._live_pipeline(frozen)
    assert isinstance(live, ModuleType) and live.region == "kept"
    assert frozen.unique_pot_patch == "frozen"              # offline tools keep .90
    assert live.unique_pot_patch(None, [7, 7]) is not None  # the labels agree
    assert seen == [aa_reader.POT_LABEL_MATCH] * 2 == [.80] * 2
    assert live.unique_pot_patch(None, [7, 8]) is None      # they disagree: no pot
