"""Seat states from current visual evidence, without private recordings."""

from copy import deepcopy

import cv2
import numpy as np
import pytest

from poker_engine.desktop.aa_seat_states import (
    AASeatStates, SeatCueRecorder, frame_evidence, icon_box, icon_score,
    icon_template, plus_score, white_fraction, yellow_text_fraction)

SLOTS = [str(slot) for slot in range(8)]


def frame(*, glyphs=None, scores=None, cues=None, stacks=None, hero=None,
          supported=True, modes=None):
    return {
        "scene_supported": supported,
        "special_modes": modes or {"block_state_updates": False},
        "glyphs": {slot: (glyphs or {}).get(slot) for slot in SLOTS},
        "seat_cues_v1": {slot: {"cue": (cues or {}).get(slot, "UNKNOWN"),
                                "conflict": False,
                                "scores": (scores or {}).get(slot, {})}
                         for slot in SLOTS},
        "stacks": {slot: {"value": value} for slot, value in (stacks or {}).items()},
        "cards": {"hero": list(hero or [None, None])},
    }


@pytest.mark.parametrize("kwargs, expected", [
    ({"glyphs": {"1": "fold"}, "scores": {"1": {"icon": 0.95}}},
     ("folded", "fold_badge")),
    ({"glyphs": {"1": "all_in"}}, ("all_in", "all_in_badge")),
    ({"scores": {"1": {"icon": 0.9}}, "stacks": {"1": "120"}},
     ("active", "card_backs")),
    ({"scores": {"1": {"icon": 0.9}}, "stacks": {"1": "0"}},
     ("all_in", "card_backs_zero_stack")),
    ({"cues": {"1": "BACK_CARDS"}}, ("active", "card_backs")),
    ({"glyphs": {"1": "check"}}, ("active", "check_badge")),
    ({"scores": {"1": {"plus": 0.97, "felt": 0.9}}}, ("empty", "empty_seat")),
    ({"scores": {"1": {"yellow_text": 0.12}}}, ("waiting", "waiting_text")),
    ({"stacks": {"1": "0"}, "scores": {"1": {"white": 0.5}}},
     ("all_in", "face_up_zero_stack")),
    ({"stacks": {"1": "0"}, "scores": {"1": {"white": 0.06}}},
     ("waiting", "zero_stack_away")),
])
def test_evidence_for_one_seat(kwargs, expected):
    assert frame_evidence(frame(**kwargs))["1"] == expected


def test_no_evidence_is_not_guessed():
    evidence = frame_evidence(frame(scores={"1": {"icon": 0.5, "plus": 0.97,
                                                  "felt": 0.2}}))
    assert "1" not in evidence and evidence == {}


def test_hero_cards_mark_the_hero_seat_in_hand():
    assert frame_evidence(frame(hero=["Ah", "Kd"]))["4"] == ("active", "hero_cards")
    assert frame_evidence(frame(hero=["Ah", "Kd"], glyphs={"4": "fold"}))["4"][0] == (
        "folded")


@pytest.mark.parametrize("change", [
    {"supported": False},
    {"modes": {"block_state_updates": True}},
    {"modes": {"block_state_updates": False, "insurance": "VISIBLE"}},
])
def test_unreadable_frames_give_no_evidence(change):
    assert frame_evidence(frame(glyphs={"1": "fold"}, **change)) == {}


def test_newest_evidence_wins_and_short_gaps_are_held():
    seats = AASeatStates(hold_seconds=2.0)
    state = seats.observe(frame(glyphs={"1": "fold"}), 10.0)["seats"]["1"]
    assert state["state"] == "folded" and state["source"] == "fold_badge"
    # The next hand deals the seat in: no boundary needed to replace "folded".
    assert seats.observe(frame(scores={"1": {"icon": 0.93}}), 15.0)[
        "seats"]["1"]["state"] == "active"
    held = seats.observe(frame(), 16.5)["seats"]["1"]
    assert held == {"state": "active", "source": "card_backs", "age_seconds": 1.5}
    assert seats.observe(frame(supported=False), 16.9)["seats"]["1"]["state"] == (
        "active")
    assert seats.observe(frame(), 17.5)["seats"]["1"]["state"] == "unknown"


def test_overlays_do_not_use_up_the_hold():
    seats = AASeatStates(hold_seconds=2.0)
    seats.observe(frame(glyphs={"1": "fold"}), 100.0)
    insurance = {"block_state_updates": False, "insurance": "VISIBLE"}
    for second in range(1, 12):           # an 11-second insurance window
        result = seats.observe(frame(modes=insurance), 100.0 + second)
        assert result["seats"]["1"]["state"] == "folded"
    assert seats.observe(frame(), 112.5)["seats"]["1"]["state"] == "folded"
    assert seats.observe(frame(), 114.5)["seats"]["1"]["state"] == "unknown"


def test_complete_only_when_every_seat_is_known_and_reset_clears():
    seats = AASeatStates()
    every = frame(glyphs={slot: "fold" for slot in SLOTS})
    result = seats.observe(every, 1.0)
    assert result["complete"] and result["schema_version"] == 1
    seats.reset()
    result = seats.observe(frame(), 1.1)
    assert not result["complete"]
    assert {seat["state"] for seat in result["seats"].values()} == {"unknown"}


def test_yellow_text_counts_only_the_middle_band():
    image = np.zeros((1080, 498, 3), dtype=np.uint8)
    rect = (10, 100, 76, 22)
    cv2.rectangle(image, (20, 117), (70, 121), (0, 210, 240), -1)   # bottom: WIN
    assert yellow_text_fraction(image, rect) == 0.0
    cv2.rectangle(image, (20, 106), (70, 112), (0, 210, 240), -1)   # middle text
    assert yellow_text_fraction(image, rect) > 0.25


def test_white_fraction_sees_face_up_cards():
    image = np.full((1080, 498, 3), 60, dtype=np.uint8)
    avatar = (100, 100, 72, 68)
    assert white_fraction(image, avatar) == 0.0
    image[100:168, 100:136] = 255
    assert white_fraction(image, avatar) == pytest.approx(0.5)


def _icon(size=18):
    icon = np.zeros((size, size, 3), dtype=np.uint8)
    icon[:] = (40, 40, 170)
    icon[:, size // 2] = (220, 220, 240)
    icon[size // 2, :] = (220, 220, 240)
    icon[[0, -1], :] = (200, 200, 230)
    return icon


def _table_with_icons(profile, slots, rng, shift=(0, 0)):
    image = rng.integers(0, 255, (1080, 498, 3), dtype=np.uint8)
    for slot in slots:
        x, y, width, height = icon_box(profile["slots"][slot]["avatar"], slot)
        y, x = y + shift[1], x + shift[0]
        image[y:y + height, x:x + width] = _icon()
    return image


@pytest.fixture
def profile():
    rows = [[213, 154], [423, 296], [423, 454], [423, 611],
            [213, 839], [4, 611], [4, 454], [4, 296]]
    return {"slots": [{"slot": slot, "avatar": [x, y, 72, 68],
                       "stack": [x, y + 72, 74, 22]}
                      for slot, (x, y) in enumerate(rows)]}


def test_icon_template_averages_seats_and_tolerates_small_offsets(profile):
    rng = np.random.default_rng(1)
    references = [_table_with_icons(profile, (0, 1, 2, 3, 5, 7), rng)
                  for _ in range(2)]
    template = icon_template(references, profile)
    shifted = _table_with_icons(profile, (6,), rng, shift=(3, -2))
    avatar = profile["slots"][6]["avatar"]
    assert icon_score(shifted, avatar, 6, template) > 0.9
    plain = rng.integers(0, 255, (1080, 498, 3), dtype=np.uint8)
    assert icon_score(plain, avatar, 6, template) < 0.5


def test_icon_template_requires_a_visible_icon(profile):
    blank = np.full((1080, 498, 3), 90, dtype=np.uint8)
    with pytest.raises(ValueError):
        icon_template([blank, blank], profile)


def _plus_seat(shift=(0, 0)):
    image = np.zeros((1080, 498, 3), dtype=np.uint8)
    image[:] = (60, 140, 20)                       # felt green
    cx, cy = 100 + 36 + shift[0], 100 + 34 + shift[1]
    cv2.line(image, (cx - 8, cy), (cx + 8, cy), (230, 230, 230), 2)
    cv2.line(image, (cx, cy - 8), (cx, cy + 8), (230, 230, 230), 2)
    return image


def test_plus_score_aligns_small_offsets():
    avatar = (100, 100, 72, 68)
    patch = _plus_seat()[100:168, 100:172]
    height, width = patch.shape[:2]
    center = patch[height // 2 - 12:height // 2 + 12, width // 2 - 12:width // 2 + 12]
    reference = cv2.inRange(cv2.cvtColor(center, cv2.COLOR_BGR2HSV),
                            (0, 0, 120), (179, 100, 255)) > 0
    assert plus_score(_plus_seat((2, -3)), avatar, reference) == pytest.approx(1.0)
    assert plus_score(np.zeros((1080, 498, 3), np.uint8), avatar, reference) == 0.0


class _Base:
    def __init__(self, profile):
        self.profile = profile
        self.empty = np.ones((24, 24), dtype=bool)
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        return {str(slot): {"cue": "UNKNOWN", "conflict": False, "scores": {}}
                for slot in range(8)}


def test_recorder_adds_scores_keeps_last_and_delegates(profile):
    base = _Base(profile)
    recorder = SeatCueRecorder(base, _icon().astype(np.float32))
    assert recorder.empty is base.empty
    result = recorder.recognize(np.zeros((1080, 498, 3), dtype=np.uint8))
    assert recorder.last is result and base.calls == 1
    assert set(result["3"]["scores"]) == {
        "icon", "plus", "felt", "white", "yellow_text"}
    assert recorder.recognize(None)["3"]["scores"] == {}
    copied = deepcopy(recorder)
    assert copied.empty is not base.empty and copied.profile == profile
