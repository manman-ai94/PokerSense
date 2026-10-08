import cv2
import numpy as np
import pytest

from tools.aa8_dealer_v2 import (
    AA8DealerReader,
    DEALER_RECTS,
    OTHER_DEALER_RECTS,
    StableDealerEvidence,
)


def canvas(*seats, rects=DEALER_RECTS):
    image = np.full((1080, 498, 3), (20, 120, 30), np.uint8)
    for seat in seats:
        x, y, width, height = rects[seat]
        center = (x + width // 2, y + height // 2)
        cv2.circle(image, center, 9, (245, 245, 245), -1)
        cv2.putText(
            image, "D", (center[0] - 5, center[1] + 5),
            cv2.FONT_HERSHEY_SIMPLEX, .45, (20, 20, 20), 1, cv2.LINE_AA,
        )
    return image


@pytest.mark.parametrize("seat", range(8))
def test_unique_badge_maps_to_physical_seat(seat):
    result = AA8DealerReader().read(canvas(seat))
    assert result["dealer_seat"] == seat
    assert result["positive_slots"] == [seat]
    assert not result["canonical_verified"]


def test_bottom_seat_badge_right_of_the_stack_when_spectating():
    # Someone else in the bottom seat: the badge sits right of the stack.
    result = AA8DealerReader().read(canvas(4, rects=OTHER_DEALER_RECTS))
    assert result["dealer_seat"] == 4
    assert result["positive_slots"] == [4]


def test_none_multiple_and_invalid_canvas_abstain():
    reader = AA8DealerReader()
    assert reader.read(canvas())["reason"] == "no_positive_dealer_badge"
    assert reader.read(canvas(1, 7))["reason"] == "multiple_dealer_badges"
    assert reader.read(None)["reason"] == "unsupported_canvas"


def test_two_frames_confirm_and_epoch_change_clears_old_dealer():
    tracker = StableDealerEvidence()
    assert tracker.observe(1, 7, epoch="h1")["dealer_seat"] is None
    assert tracker.observe(2, 7, epoch="h1")["dealer_seat"] == 7
    assert tracker.observe(3, None, epoch="h1")["dealer_seat"] == 7
    assert tracker.observe(4, 0, epoch="h2")["dealer_seat"] is None
    value = tracker.observe(5, 0, epoch="h2")
    assert value["dealer_seat"] == 0
    assert value["evidence_frames"] == [4, 5]


def test_gap_modal_and_missing_epoch_clear_history():
    tracker = StableDealerEvidence()
    tracker.observe(1, 4, epoch="h")
    assert tracker.observe(2, 4, epoch="h")["dealer_seat"] == 4
    assert tracker.observe(4, 4, epoch="h")["dealer_seat"] is None
    assert tracker.observe(5, 4, epoch="h", blocked=True)["dealer_seat"] is None
    assert tracker.observe(6, 4, epoch=None)["dealer_seat"] is None


@pytest.mark.parametrize("required", (True, 1, 1.5))
def test_invalid_stability_requirement_rejected(required):
    with pytest.raises(ValueError):
        StableDealerEvidence(required)
