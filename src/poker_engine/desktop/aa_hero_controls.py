"""Read the Hero's green action button: an amount to call, a check, or all in.

The button shows either an amount above the word "跟注" (call), the centred
word "让牌" (check: nothing to call) or "All in" (calling takes the whole
stack). Its white text is read inside the button only, so the rim never
reaches the digit reader, and specks smaller than a stroke are ignored. The
amount digits are cut out with a margin of plain button around them.

The digit reader was built from stack amounts, whose digits are 11-12 pixels
tall; the button's digits are 17-18. They are scaled to the stack height
before reading, so the strokes look like the ones the reader knows.

A value is reported once two consecutive observations agree and the Hero is
the current actor. No absent button is interpreted as a legal check.
"""

from dataclasses import asdict
from decimal import Decimal, InvalidOperation

import cv2
import numpy as np

from tools.aa8_hero_turn import hero_turn_candidate

BUTTON_CENTRE = (369, 875)   # green button on the 498x1080 canvas
TEXT_RADIUS = 30             # the text sits well inside; the rim lies outside
WHITE = 170                  # minimum of B, G and R for white text
MIN_PART = 6                 # pixels; smaller specks are the rim's antialiasing
STACK_DIGIT_HEIGHT = 12      # digit height of the stack amounts the reader knows


def _bands(parts):
    """Group text parts into rows of text; parts within 2 rows join a band."""
    bands = []
    for part in sorted(parts, key=lambda item: item[1]):
        x, y, width, height = part
        if bands and y <= bands[-1]["bottom"] + 2:
            bands[-1]["bottom"] = max(bands[-1]["bottom"], y + height - 1)
            bands[-1]["parts"].append(part)
        else:
            bands.append({"top": y, "bottom": y + height - 1, "parts": [part]})
    return bands


def button_text(image):
    """Classify the button text and cut out the amount digits when present.

    Returns ``kind`` "call", "check", "all_in" or None, with the digits as a
    grey patch for "call".
    """
    cx, cy = BUTTON_CENTRE
    r = TEXT_RADIUS
    region = image[cy - r:cy + r + 1, cx - r:cx + r + 1].min(axis=2)
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    ink = ((region >= WHITE) & (xx * xx + yy * yy <= r * r)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = [i for i in range(1, count) if stats[i][4] >= MIN_PART]
    parts = {i: tuple(int(v) for v in stats[i][:4]) for i in keep}
    bands = _bands(list(parts.values()))
    if not bands:
        return {"kind": None, "reason": "no_button_text"}
    middle = r   # region row of the button centre
    if len(bands) == 2 and bands[0]["bottom"] < middle < bands[1]["top"]:
        digits = bands[0]
        left = min(x for x, _, _, _ in digits["parts"]) - 3
        right = max(x + w for x, _, w, _ in digits["parts"]) + 3
        top, bottom = digits["top"] - 3, digits["bottom"] + 4
        if left < 0 or top < 0 or right > region.shape[1] or bottom > region.shape[0]:
            return {"kind": None, "reason": "amount_too_close_to_rim"}
        patch = region[top:bottom, left:right].copy()
        ids = [i for i, part in parts.items() if part in digits["parts"]]
        stray = (ink[top:bottom, left:right] > 0) & ~np.isin(
            labels[top:bottom, left:right], ids)
        background = region[top:bottom, left:right][ink[top:bottom, left:right] == 0]
        patch[stray] = int(np.median(background)) if background.size else 0
        scale = STACK_DIGIT_HEIGHT / (digits["bottom"] - digits["top"] + 1)
        patch = cv2.resize(patch, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
        return {"kind": "call", "digits": patch,
                "box": [int(cx - r + left), int(cy - r + top),
                        int(right - left), int(bottom - top)]}
    centred = len(bands) == 1 and abs(
        (bands[0]["top"] + bands[0]["bottom"]) / 2 - middle) <= 7
    if centred:
        band = bands[0]
        height = band["bottom"] - band["top"] + 1
        # "All in" has two thin full-height strokes ("ll"); "让牌" has none.
        thin = sum(1 for _, _, width, part_height in band["parts"]
                   if width <= 3 and part_height >= 0.7 * height)
        return {"kind": "all_in" if thin >= 2 else "check"}
    return {"kind": None, "reason": "unexpected_button_text"}


def _hero_stack(row):
    value = ((row.get("stacks") or {}).get("4") or {})
    value = value.get("value") if isinstance(value, dict) else value
    try:
        amount = Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return None
    return value if amount is not None and amount.is_finite() and amount > 0 else None


class AAHeroControls:
    def __init__(self, bank):
        self.bank = bank
        self.previous = None

    def observe(self, image, row):
        frame = row["frame"]
        modes = row.get("special_modes") or {}
        blocked = (row.get("scene_supported") is not True
                   or modes.get("block_state_updates")
                   or modes.get("insurance") == "VISIBLE")
        result = {"visible": False, "button": None, "call_amount": None,
                  "raw_call_amount": None, "price_confirmed": False,
                  "reason": "controls_not_visible", "hero_slot": 4, "frame": frame,
                  "strategy_eligible": False, "legal_menu_verified": False,
                  "preprocessing": "minimum_bgr_channel_text_bands_v2"}
        if (blocked or not isinstance(image, np.ndarray)
                or image.shape != (1080, 498, 3)):
            self.previous = None
            return {**result, "reason": "unsupported_or_obstructed_scene"}
        controls = hero_turn_candidate(image)
        if controls.get("hero_turn") is not True:
            self.previous = None
            return result
        text = button_text(image)
        kind, value, raw, diagnostic = text["kind"], None, None, None
        if kind == "call":
            diagnostic = asdict(self.bank.diagnose(text["digits"]))
            value, raw = diagnostic["value"], diagnostic["raw_text"]
            if value is not None and Decimal(value) <= 0:
                value = None
        elif kind == "check":
            value = "0"
        elif kind == "all_in":
            value = _hero_stack(row)
        valid = value is not None and row.get("current_actor") == 4
        stable = valid and self.previous == (frame - 1, kind, value)
        self.previous = (frame, kind, value) if valid else None
        if stable:
            reason = "stable_visible_call_price_candidate"
        elif valid:
            reason = "price_waiting_stability"
        elif kind is None:
            reason = text["reason"]
        elif kind == "all_in" and value is None:
            reason = "all_in_stack_unknown"
        else:
            reason = "price_or_actor_unknown"
        return {**result, "visible": True, "button": kind,
                "button_evidence": controls, "call_amount": value if stable else None,
                "raw_call_amount": raw, "diagnostic": diagnostic,
                "price_confirmed": stable, "all_in_call": kind == "all_in",
                "reason": reason, "crop": text.get("box")}

    def __call__(self, image, row):
        row["hero_controls_v1"] = self.observe(image, row)
        return row
