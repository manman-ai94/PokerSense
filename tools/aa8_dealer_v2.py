"""Eight-seat AA dealer-button candidates using the existing badge detector."""

from dataclasses import dataclass

from tools.aa_visual_candidate import canvas_ok
from tools.capture_card_calibration.seat_reader import _find_dealer


# Each AA badge is adjacent to its seat rather than inside the stack crop.
# Coordinates are on the normalized 498x1080 canvas and deliberately exclude
# avatar/name content as much as the fixed layout permits.
DEALER_RECTS = {
    0: (180, 218, 40, 36),
    1: (385, 360, 38, 40),
    2: (385, 517, 38, 40),
    3: (385, 674, 38, 40),
    4: (172, 823, 40, 42),
    5: (76, 674, 38, 40),
    6: (76, 517, 38, 40),
    7: (76, 360, 38, 40),
}
# The bottom seat shows its badge in another place when someone else sits
# there (spectating): right of the stack instead of above-left of the avatar.
# Only one of the two places shows a badge at a time.
OTHER_DEALER_RECTS = {
    4: (284, 908, 28, 30),
}


def dealer_rects(seat):
    return (DEALER_RECTS[seat],) + ((OTHER_DEALER_RECTS[seat],)
                                    if seat in OTHER_DEALER_RECTS else ())


class AA8DealerReader:
    def read(self, image):
        result = {
            "dealer_seat": None,
            "positive_slots": [],
            "reason": "unsupported_canvas",
            "canonical_verified": False,
            "strategy_eligible": False,
        }
        if not canvas_ok(image):
            return result
        positive = []
        for seat in DEALER_RECTS:
            if any(_find_dealer(image[y:y + height, x:x + width])
                   for x, y, width, height in dealer_rects(seat)):
                positive.append(seat)
        reason = (
            "unique_white_disc_black_d_candidate" if len(positive) == 1
            else "no_positive_dealer_badge" if not positive
            else "multiple_dealer_badges"
        )
        return {
            **result,
            "dealer_seat": positive[0] if len(positive) == 1 else None,
            "positive_slots": positive,
            "reason": reason,
            "algorithm": "existing_white_disc_black_d_v1",
            "rois": {str(key): list(value) for key, value in DEALER_RECTS.items()},
            "other_rois": {str(key): list(value)
                           for key, value in OTHER_DEALER_RECTS.items()},
        }


@dataclass
class StableDealerEvidence:
    required: int = 2

    def __post_init__(self):
        if type(self.required) is not int or self.required < 2:
            raise ValueError("required must be an integer >= 2")
        self.last_frame = None
        self.epoch = None
        self.pending = None
        self.streak = 0
        self.current = None
        self.evidence_frames = []

    def observe(self, frame, detected, *, epoch, blocked=False):
        if (type(frame) is not int or frame < 0
                or self.last_frame is not None and frame <= self.last_frame):
            raise ValueError("strictly increasing source frames required")
        gap = self.last_frame is not None and frame != self.last_frame + 1
        changed = epoch != self.epoch
        self.last_frame = frame
        if gap or changed or blocked or not isinstance(epoch, str) or not epoch:
            self.pending = None
            self.streak = 0
            self.current = None
            self.evidence_frames = []
        self.epoch = epoch
        if blocked or not isinstance(epoch, str) or not epoch:
            return self.snapshot(frame, "blocked_or_no_hand_epoch")
        if type(detected) is not int or not 0 <= detected < 8:
            self.pending = None
            self.streak = 0
            return self.snapshot(frame, "no_unique_current_badge")
        if detected != self.current:
            if detected == self.pending:
                self.streak += 1
                self.evidence_frames.append(frame)
            else:
                self.pending = detected
                self.streak = 1
                self.evidence_frames = [frame]
            if self.streak >= self.required:
                self.current = detected
                self.pending = None
                self.streak = 0
                self.evidence_frames = self.evidence_frames[-self.required:]
        else:
            self.pending = None
            self.streak = 0
        return self.snapshot(frame, "stable_dealer_candidate" if (
            self.current is not None) else "waiting_for_stable_badge")

    def snapshot(self, frame, reason):
        return {
            "frame": frame,
            "dealer_seat": self.current,
            "epoch": self.epoch,
            "evidence_frames": list(self.evidence_frames) if (
                self.current is not None) else [],
            "reason": reason,
            "stable_frames_required": self.required,
            "canonical_verified": False,
            "strategy_eligible": False,
        }


__all__ = ["AA8DealerReader", "DEALER_RECTS", "OTHER_DEALER_RECTS",
           "StableDealerEvidence", "dealer_rects"]
