"""The mushroom pool (蘑菇池) shown at the top left of the AA table.

With the mushroom mode on, a red mushroom icon sits at the top left of the
table with the pool's amount in a dark badge beside it. The small blind who
wins the hand's pot takes the whole pool (see ``scoreboard/mushroom.py``), so
the preflop advice counts it as extra pot for the small blind.

The badge's digits are read with a gray digit bank like the stacks', built
from mushroom badges in recordings (``tools/build_aa_mushroom_bank.py``; the
bank is private data, ``aa_mushroom_bank_v1/bank.npz`` in the private data
folder). Two digits in the badge's font can touch ("48"), so a run of ink
too wide for one digit is split at its faintest column before reading. A
value counts only when the icon is there, every digit is read, and the same
value was read on the frame before; anything else is ``None``. Without the
bank file nothing is read and the advice works as before.
"""

from __future__ import annotations

from dataclasses import asdict
import logging

import cv2
import numpy as np

from poker_engine.data_paths import private_root
from poker_engine.perceptual.vision.amount_recognizer import _column_spans
from poker_engine.perceptual.vision.gray_amount_recognizer import (
    GrayAmountRecognizer, GrayRead)

ICON = (22, 100, 33, 35)        # x, y, width, height on the 498x1080 table
DIGITS = (60, 115, 40, 19)
RED_SHARE = 0.08                # the icon's red cap: about 15% of its box
ONE_DIGIT = 12                  # wider runs of ink are two touching digits
BANK = "aa_mushroom_bank_v1/bank.npz"
MARGIN = 0.03                   # the stacks' bank asks for 0.05

LOG = logging.getLogger(__name__)


def box(image, rect):
    x, y, w, h = rect
    return image[y:y + h, x:x + w]


def icon_visible(image):
    hsv = cv2.cvtColor(box(image, ICON), cv2.COLOR_BGR2HSV)
    red = (((hsv[..., 0] <= 8) | (hsv[..., 0] >= 170))
           & (hsv[..., 1] >= 120) & (hsv[..., 2] >= 120))
    return float(red.mean()) >= RED_SHARE


def glyph_patches(patch):
    """One patch per digit (the rest of the badge filled with its background),
    splitting a run of ink too wide for one digit at its faintest column."""
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    parts = []
    for left, right in _column_spans(binary):
        if right - left > ONE_DIGIT:
            inner = gray[:, left + 3:right - 3].max(axis=0)
            cut = left + 3 + int(np.argmin(inner))
            parts += [(left, cut), (cut + 1, right)]
        else:
            parts.append((left, right))
    background = int(np.percentile(gray, 20))
    patches = []
    for left, right in parts:
        alone = np.full_like(gray, background)
        alone[:, left:right] = gray[:, left:right]
        patches.append(cv2.cvtColor(alone, cv2.COLOR_GRAY2BGR))
    return patches


def read_digits(bank, patch):
    """The badge's amount as a ``GrayRead``: every digit read on its own (ink
    at the box's edge, a number wider than the box, is not read)."""
    patches = glyph_patches(patch)
    if not 1 <= len(patches) <= 6:
        return GrayRead(None, None, "glyph_count", ())
    text, raw, scores = "", "", []
    for single in patches:
        read = bank.diagnose(single)
        if read.raw_text is None or len(read.raw_text) != 1:
            return GrayRead(None, raw or None, read.reason, tuple(scores))
        raw += read.raw_text
        scores.extend(read.scores)
        if read.value is None:
            text = None
        elif text is not None:
            text += read.value
    if text is None or len(text) > 1 and text.startswith("0"):
        return GrayRead(None, raw, "ambiguous", tuple(scores))
    return GrayRead(text, raw, "candidate", tuple(scores))


def load_bank(path=None):
    """The mushroom digit bank, or None when its private file is missing."""
    path = private_root() / BANK if path is None else path
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as data:
        return GrayAmountRecognizer(data["features"], data["labels"],
                                    margin=MARGIN, augment=True)


class AAMushroomPool:
    """``mushroom_pool_v1`` for each frame: the pool's amount when it is read
    the same on two frames in a row."""

    def __init__(self, bank=None, *, load=load_bank):
        if bank is None:
            try:
                bank = load()
            except (OSError, ValueError, KeyError) as error:   # never stop the reader
                LOG.warning("mushroom bank not usable: %s", error)
                bank = None
        self.bank = bank
        self.previous = None

    def __deepcopy__(self, memo):
        # The bank is read-only and large: copies made at a reset share it.
        copied = type(self).__new__(type(self))
        copied.bank, copied.previous = self.bank, self.previous
        return copied

    def observe(self, image, row):
        frame = row.get("frame")
        result = {"visible": False, "value": None, "raw": None,
                  "reason": "no_mushroom_icon", "frame": frame}
        if (row.get("scene_supported") is not True or not isinstance(image, np.ndarray)
                or image.shape != (1080, 498, 3)):
            self.previous = None
            return {**result, "reason": "unsupported_or_obstructed_scene"}
        if self.bank is None:
            self.previous = None
            return {**result, "reason": "bank_missing"}
        if not icon_visible(image):
            self.previous = None
            return result
        read = read_digits(self.bank, box(image, DIGITS))
        stable = read.value is not None and self.previous == (frame - 1, read.value)
        self.previous = (frame, read.value) if read.value is not None else None
        reason = ("stable" if stable else "waiting_stability" if read.value
                  else read.reason)
        return {**result, "visible": True, "value": read.value if stable else None,
                "raw": read.raw_text, "reason": reason,
                "diagnostic": {key: value for key, value in asdict(read).items()
                               if key != "scores"}}

    def __call__(self, image, row):
        row["mushroom_pool_v1"] = self.observe(image, row)
        return row


__all__ = ["AAMushroomPool", "DIGITS", "ICON", "glyph_patches", "icon_visible",
           "load_bank", "read_digits"]
