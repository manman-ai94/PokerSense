"""Per-seat hand state from what the AA table shows now.

Every readable frame gives positive evidence for some seats: the "弃牌"
(fold) badge, which stays on a folded seat for the rest of the hand, the
all-in badge, card backs, an action badge, the empty "+" seat, the yellow
"等待下一手" text, or a zero stack: with face-up cards an all-in showdown,
otherwise "留座" (a player away from the table). The newest evidence wins.
A seat with no evidence in the current frame keeps its last state for a short
hold, because badges blink at street changes and chips briefly cover card
backs; after the hold it becomes unknown. The hold only counts readable
time: an overlay such as the insurance window changes nobody's state, so
states are kept until the table shows again.

No hand boundary is inferred. A new hand replaces the previous hand's states
through fresh evidence (card backs replace "folded", the waiting text replaces
"active"), so a missed boundary cannot leave a stale state behind.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import cv2
import numpy as np

HERO_SLOT = "4"
SLOTS = tuple(str(slot) for slot in range(8))
STATES = ("active", "folded", "all_in", "empty", "waiting")
ACTION_BADGES = frozenset({"call", "check", "aggressive"})
WAITING_CUES = frozenset({"WAITING_POST_OR_PASS", "WAITING_NEXT_HAND"})
HOLD_SECONDS = 2.0
# Score floors, set from the development recordings: card-back icons score
# about 0.90 or more and seats without one at most 0.45; face-up cards cover
# 46-60% of the avatar in white, an away player's darkened avatar about 6%.
FLOORS = {"icon": 0.70, "plus": 0.90, "felt": 0.60, "yellow_text": 0.05,
          "face_up": 0.25}


def yellow_text_fraction(image, rect):
    """Share of yellow pixels in the middle band of a stack box.

    "等待下一手" is yellow text on the middle rows; the winner's gold "WIN!"
    sits on the bottom rows, so it does not count.
    """
    x, y, width, _ = rect
    patch = image[y + 3:y + 16, x:x + width]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, (15, 80, 110), (40, 255, 255))
    return float(np.count_nonzero(yellow) / yellow.size)


def white_fraction(image, avatar):
    """Share of near-white pixels on the avatar (face-up cards cover it)."""
    x, y, width, height = avatar
    hsv = cv2.cvtColor(image[y:y + height, x:x + width], cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 1] < 50) & (hsv[:, :, 2] > 200)
    return float(np.count_nonzero(white) / white.size)


ICON_SEARCH = 4      # pixels the card-back icon may sit off its nominal spot
ICON_BLUR = 0.8
PLUS_SEARCH = 3      # same for the empty seat's "+"


def icon_box(avatar, slot):
    """Nominal 18x18 inner box of the small card-back icon on a seat's avatar.

    Right-hand seats (0-4) show it at the avatar's lower right, left-hand
    seats (5-7) at the lower left.
    """
    x, y, _, height = avatar
    left = x + 50 if int(slot) <= 4 else x + 9
    return left, y + height - 22, 18, 18


def _blurred(patch):
    # Thin border lines land on different sub-pixels after scaling; a light
    # blur makes the comparison depend on the icon's shape, not its pixels.
    return cv2.GaussianBlur(patch.astype(np.float32), (0, 0), ICON_BLUR)


def icon_template(references, profile, slots=(0, 1, 2, 3, 5, 7)):
    """Average the card-back icon over reference frames and seats.

    Averaging over different avatars removes the avatar showing at the
    icon's edges. Each crop is aligned to the first one before averaging.
    """
    rows = {row["slot"]: row for row in profile["slots"]}

    def area(image, slot, pad):
        x, y, width, height = icon_box(rows[slot]["avatar"], slot)
        return image[y - pad:y + height + pad,
                     x - pad:x + width + pad].astype(np.float32)

    seed = area(references[0], slots[0], 0)
    crops = []
    for image in references:
        for slot in slots:
            region = area(image, slot, ICON_SEARCH)
            result = cv2.matchTemplate(region, seed, cv2.TM_CCOEFF_NORMED)
            _, best, _, (dx, dy) = cv2.minMaxLoc(result)
            if best >= 0.5:
                crops.append(region[dy:dy + seed.shape[0], dx:dx + seed.shape[1]])
    if len(crops) < 3 or float(seed.std()) < 10:
        raise ValueError("card-back icon template required")
    return _blurred(np.mean(crops, axis=0))


def icon_score(image, avatar, slot, template):
    """Best normalized correlation of the icon near its nominal spot."""
    x, y, width, height = icon_box(avatar, slot)
    region = image[max(0, y - ICON_SEARCH):y + height + ICON_SEARCH,
                   max(0, x - ICON_SEARCH):x + width + ICON_SEARCH]
    if region.shape[0] < height or region.shape[1] < width:
        return 0.0
    return float(cv2.matchTemplate(
        _blurred(region), template, cv2.TM_CCOEFF_NORMED).max())


def plus_score(image, avatar, reference_plus):
    """Best overlap (dice) of the empty-seat "+" allowing a small offset.

    The "+" is read from the 24x24 centre of the avatar box; the mask is
    computed once over that centre widened by the search margin.
    """
    x, y, width, height = avatar
    size = 24 + 2 * PLUS_SEARCH
    top = y + height // 2 - 12 - PLUS_SEARCH
    left = x + width // 2 - 12 - PLUS_SEARCH
    region = image[max(0, top):top + size, max(0, left):left + size]
    if top < 0 or left < 0 or region.shape[:2] != (size, size):
        return 0.0
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 120), (179, 100, 255)) > 0
    reference_count = np.count_nonzero(reference_plus)
    best = 0.0
    for dy in range(2 * PLUS_SEARCH + 1):
        for dx in range(2 * PLUS_SEARCH + 1):
            window = mask[dy:dy + 24, dx:dx + 24]
            total = np.count_nonzero(window) + reference_count
            if total:
                best = max(best, 2 * np.count_nonzero(window & reference_plus) / total)
    return float(best)


def felt_fraction(image, avatar):
    """Share of table-felt green inside the avatar box (an empty seat is felt)."""
    x, y, width, height = avatar
    hsv = cv2.cvtColor(image[y:y + height, x:x + width], cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (35, 80, 30), (95, 255, 255))
    return float(np.count_nonzero(green) / green.size)


class SeatCueRecorder:
    """Wrap the participation reader: keep its last per-seat cues and scores.

    Adds positional-tolerant scores to each seat: ``icon`` (card-back icon),
    ``plus`` (empty seat), ``felt``, ``white`` (face-up cards) and
    ``yellow_text`` ("等待下一手").
    Everything else is delegated, so the rest of the pipeline is unchanged.
    """

    def __init__(self, base, icon):
        self.base = base
        self.icon = icon
        self.reference_plus = np.asarray(base.empty, dtype=bool)
        self.last = None

    def __getattr__(self, name):
        base = self.__dict__.get("base")  # absent while copy/pickle rebuilds us
        if base is None:
            raise AttributeError(name)
        return getattr(base, name)

    def recognize(self, image):
        result = self.base.recognize(image)
        if isinstance(image, np.ndarray) and image.shape == (1080, 498, 3):
            for row in self.base.profile["slots"]:
                seat = result.get(str(row["slot"]))
                if seat is None:
                    continue
                avatar = row["avatar"]
                seat.setdefault("scores", {}).update(
                    icon=round(icon_score(image, avatar, row["slot"], self.icon), 4),
                    plus=round(plus_score(image, avatar, self.reference_plus), 4),
                    felt=round(felt_fraction(image, avatar), 4),
                    white=round(white_fraction(image, avatar), 4),
                    yellow_text=round(yellow_text_fraction(image, row["stack"]), 4))
        self.last = result
        return result


def _stack(payload, slot):
    value = ((payload.get("stacks") or {}).get(slot) or {})
    value = value.get("value") if isinstance(value, dict) else value
    try:
        amount = Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return None
    return amount if amount is not None and amount.is_finite() else None


def _readable(payload):
    modes = payload.get("special_modes") or {}
    return (payload.get("scene_supported") is True
            and not modes.get("block_state_updates")
            and modes.get("insurance") != "VISIBLE")


def frame_evidence(payload, *, floors=None):
    """Seat -> (state, source) for the seats this frame shows evidence for."""
    if not _readable(payload):
        return {}
    floors = {**FLOORS, **(floors or {})}
    glyphs = payload.get("glyphs") or {}
    cues = payload.get("seat_cues_v1") or {}
    hero_cards = [card for card in (payload.get("cards") or {}).get("hero") or ()
                  if card]
    evidence = {}
    for slot in SLOTS:
        glyph = glyphs.get(slot)
        cue = cues.get(slot) or {}
        base = None if cue.get("conflict") else cue.get("cue")
        scores = cue.get("scores") or {}
        stack = _stack(payload, slot)
        backs = (base == "BACK_CARDS"
                 or (scores.get("icon") or 0.0) >= floors["icon"])
        empty = (base == "EMPTY"
                 or (scores.get("plus") or 0.0) >= floors["plus"]
                 and (scores.get("felt") or 0.0) >= floors["felt"])
        waiting = (base in WAITING_CUES
                   or (scores.get("yellow_text") or 0.0) >= floors["yellow_text"])
        if glyph == "fold":
            evidence[slot] = ("folded", "fold_badge")
        elif glyph == "all_in":
            evidence[slot] = ("all_in", "all_in_badge")
        elif slot == HERO_SLOT and len(hero_cards) == 2:
            evidence[slot] = (("all_in", "hero_cards_zero_stack") if stack == 0
                              else ("active", "hero_cards"))
        elif backs:
            evidence[slot] = (("all_in", "card_backs_zero_stack") if stack == 0
                              else ("active", "card_backs"))
        elif glyph in ACTION_BADGES:
            evidence[slot] = ("active", glyph + "_badge")
        elif empty:
            evidence[slot] = ("empty", "empty_seat")
        elif waiting:
            evidence[slot] = ("waiting", "waiting_text")
        elif stack == 0 and (scores.get("white") or 0.0) >= floors["face_up"]:
            evidence[slot] = ("all_in", "face_up_zero_stack")
        elif stack == 0:
            evidence[slot] = ("waiting", "zero_stack_away")
    return evidence


class AASeatStates:
    """Track the eight seats across frames of one continuous observation."""

    def __init__(self, *, hold_seconds=HOLD_SECONDS, floors=None):
        self.hold_seconds = hold_seconds
        self.floors = {**FLOORS, **(floors or {})}
        self.reset()

    def reset(self):
        self._seen = {}
        self._clock = 0.0       # readable seconds observed so far
        self._last_pts = None

    def observe(self, payload, pts):
        if self._last_pts is not None and _readable(payload):
            self._clock += max(0.0, pts - self._last_pts)
        self._last_pts = pts
        for slot, (state, source) in frame_evidence(
                payload, floors=self.floors).items():
            self._seen[slot] = (state, source, self._clock)
        seats = {}
        for slot in SLOTS:
            state, source, seen = self._seen.get(slot, (None, None, None))
            age = None if seen is None else self._clock - seen
            if age is None or age > self.hold_seconds:
                seats[slot] = {"state": "unknown", "source": None,
                               "age_seconds": None if age is None else round(age, 3)}
            else:
                seats[slot] = {"state": state, "source": source,
                               "age_seconds": round(age, 3)}
        return {"schema_version": 1, "seats": seats,
                "complete": all(seat["state"] != "unknown" for seat in seats.values()),
                "hold_seconds": self.hold_seconds,
                "basis": "current_visual_evidence_with_short_hold"}


__all__ = ["AASeatStates", "SeatCueRecorder", "frame_evidence", "icon_template",
           "FLOORS", "STATES", "SLOTS", "HERO_SLOT"]
