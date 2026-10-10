"""The two cards each opponent turns face up, as they are shown.

At the showdown (and when a player shows after folding) AA draws the two
cards over the player's picture, side by side and about 37x54 pixels each.
Where a seat's picture has that white block, each half is read with the card
model used for the hero's and the board's cards (it reads the corner, so
the smaller size does not matter).

A pair counts once the same two cards are read on ``CONFIRM`` frames in a
row, and is kept for the rest of the hand. A seat read as two different
pairs in one hand is left unknown rather than guessed, and so is a seat
with a card that is also another seat's, the hero's or on the board. Folded
seats that show are kept too: whether a seat was still in at the showdown
is in the hand's action history. A seat that mucks has "盖牌" over its
picture instead and gets no cards.

On the 10/08 and 10/09 recordings (five live segments, 38 showdowns with
74 opponent seats still in) 57 seats showed and all 57 were read; the
other 17 mucked. Over all hands 77 pairs were read (players also show
after folding), and every one was looked at by eye: none was wrong. A
player who shows one card and keeps the other face down is not read.
"""

from __future__ import annotations

import numpy as np

HERO = 4
CONFIRM = 3                    # frames in a row with the same two cards
CARD = (53, 78)                # the size the card model reads (the hero's)
WIDTH = (66, 82)               # the two shown cards side by side
CARD_HEIGHT = 54
WHITE = 190                    # every channel at least this
GREY = 40                      # and at most this far apart
FILL = .5                      # share of a row, or of a column of the top band
FACE = .35                     # share of a card that is white (.51-.77; a back .08)


def _white(region):
    region = region.astype(np.int16)
    low, high = region.min(axis=2), region.max(axis=2)
    return (low > WHITE) & (high - low < GREY)


def face_block(image, avatar):
    """(x, y, width, height) of the two shown cards over a seat's picture.

    The top is the sharpest step up to rows that are mostly white, and the
    width is taken from the white band just below it: lower down the
    pictures on a king, queen or jack fill most of a card (two of them left
    no row half white, and a light picture above the cards moved a top
    found by a fixed share two pixels up, reading a spade as a club). The
    cards are always ``CARD_HEIGHT`` tall."""
    x, y, width, height = avatar
    x0, y0 = max(0, x - 8), max(0, y - 2)
    white = _white(image[y0:y0 + height + 4, x0:min(image.shape[1], x + width + 8)])
    rows = white.mean(axis=1)
    top, step = None, 0.
    for row in range(1, len(rows) - CARD_HEIGHT):
        if rows[row:row + 6].min() > FILL:
            rise = rows[row:row + 4].mean() - rows[max(0, row - 3):row].mean()
            if rise > step:
                top, step = row, rise
    if top is None:
        return None
    cols = np.flatnonzero(white[top + 1:top + 9].mean(axis=0) > FILL)
    if len(cols) < 10 or not WIDTH[0] <= cols[-1] + 1 - cols[0] <= WIDTH[1]:
        return None
    return (int(x0 + cols[0]), int(y0 + top), int(cols[-1] + 1 - cols[0]), CARD_HEIGHT)


def read_card(model, image, rect):
    """One card's identity such as ``"As"``, or None."""
    import cv2
    from poker_engine.perceptual.vision.fused_card_recognizer import FusedSlotBuffer

    x, y, width, height = rect
    crop = cv2.resize(image[y:y + height, x:x + width], CARD,
                      interpolation=cv2.INTER_CUBIC)
    buffer = FusedSlotBuffer((0, 0) + CARD)
    if not buffer.ingest(crop):
        return None
    glyphs = buffer.latest_glyphs()
    if glyphs is None:
        return None
    read = model.recognize_fused(*glyphs)
    return str(read.value[0]) if read.value else None


def _agreed(reads):
    reads = [read for read in reads if read]
    best = max(set(reads), key=reads.count, default=None)
    return best if reads.count(best) >= 2 else None


def read_pair(model, image, avatar):
    """The two cards shown over one seat's picture, or None.

    Each card is read from three crops a pixel apart and kept when two of
    them agree: a crop of the right card that takes in the edge of the left
    one, or cuts into the right card's corner, can read another card (an ace
    of clubs as spades, a 6 of spades as a 5). A player may show
    one card and leave the other face down; that is not read (the red back
    was read as a 10 of hearts)."""
    block = face_block(image, avatar)
    if block is None:
        return None
    x, y, width, height = block
    half = width // 2
    for start, end in ((x, x + half), (x + half + 1, x + width)):
        if _white(image[y:y + height, start:end]).mean() < FACE:
            return None            # one card shown, the other face down
    left = _agreed(read_card(model, image, (x + dx, y, half, height))
                   for dx in (-1, 0, 1) if x + dx >= 0)
    right = _agreed(read_card(model, image,
                              (x + half + dx, y, width - half - dx, height))
                    for dx in (0, 1, 2))
    return (left, right) if left and right and left != right else None


class AAShownCards:
    """Per hand: the opponents' shown cards confirmed so far."""

    def __init__(self, model, slots):
        self.model = model
        self.avatars = {int(row["slot"]): tuple(row["avatar"]) for row in slots
                        if int(row["slot"]) != HERO}
        self.reset()

    def reset(self):
        self._hand = None
        self._runs = {}            # slot -> (pair, frames in a row)
        self._pairs = {}           # slot -> {pair: first confirmed frame}
        self._clashed = set()      # slots with a card read elsewhere too

    def observe(self, image, frame, hand_id, *, readable=True, known=()):
        """This hand's shown cards after one frame, or None if none yet.

        ``known`` are cards read elsewhere on this frame (the hero's, the
        board's); a shown card equal to one of them is a misread."""
        if hand_id != self._hand:
            self.reset()
            self._hand = hand_id
        if hand_id is None or self.model is None:
            return None
        if readable:
            for slot, avatar in self.avatars.items():
                self._observe_seat(slot, read_pair(self.model, image, avatar), frame)
        seats = {slot: next(iter(pairs.items())) for slot, pairs in self._pairs.items()
                 if len(pairs) == 1 and slot not in self._clashed}
        cards = [card for pair, _ in seats.values() for card in pair]
        cards += [card for card in known if card]
        self._clashed |= {slot for slot, (pair, _) in seats.items()
                          if any(cards.count(card) > 1 for card in pair)}
        unknown = sorted(str(slot) for slot in self._pairs
                         if len(self._pairs[slot]) > 1 or slot in self._clashed)
        seats = {str(slot): {"cards": list(pair), "frame": first}
                 for slot, (pair, first) in sorted(seats.items())
                 if slot not in self._clashed}
        if not seats and not unknown:
            return None
        return {"hand_id": hand_id, "seats": seats, "unknown": unknown}

    def _observe_seat(self, slot, pair, frame):
        if pair is None:
            self._runs.pop(slot, None)
            return
        pair = tuple(sorted(pair))
        previous, count = self._runs.get(slot, (None, 0))
        count = count + 1 if previous == pair else 1
        self._runs[slot] = (pair, count)
        if count < CONFIRM:
            return
        self._pairs.setdefault(slot, {}).setdefault(pair, frame)
