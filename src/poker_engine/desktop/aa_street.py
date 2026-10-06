"""The current street from the board cards on screen.

No board card while a hand is being played is preflop, three cards the flop,
four the turn and five the river. No hand history is needed, so joining in
the middle of a hand gives the street on the first readable frame.

While cards are being dealt (one or two shown) or the table is covered, the
last street is kept for a short hold that, as for seat states, only counts
readable time; after it the street is unknown. A readable table with no
board card and nobody in a hand means the hand is over: the street is
cleared at once.
"""

from __future__ import annotations

from .aa_seat_states import _readable

STREETS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}
IN_HAND = frozenset({"active", "all_in"})
HOLD_SECONDS = 2.0


def board_count(payload):
    """Board cards dealt, from the rightmost card shown.

    The board is dealt left to right, so a card shown in a slot means every
    slot before it is dealt too; an empty slot before it is an unread card.
    """
    slots = list((payload.get("cards") or {}).get("board_slots") or [None] * 5)
    shown = [index for index, card in enumerate(slots) if card]
    return shown[-1] + 1 if shown else 0


def hand_in_progress(payload):
    hero = [card for card in (payload.get("cards") or {}).get("hero") or () if card]
    seats = ((payload.get("seat_states_v1") or {}).get("seats") or {}).values()
    return len(hero) == 2 or any(seat.get("state") in IN_HAND for seat in seats)


HAND_OVER = "hand_over"


def street_evidence(payload):
    """The street this frame shows, ``HAND_OVER`` between hands, or None."""
    if not _readable(payload):
        return None
    count = board_count(payload)
    if count == 0:
        return "preflop" if hand_in_progress(payload) else HAND_OVER
    return STREETS.get(count)


class AAStreet:
    """Track the street across frames of one continuous observation."""

    def __init__(self, *, hold_seconds=HOLD_SECONDS):
        self.hold_seconds = hold_seconds
        self.reset()

    def reset(self):
        self._street = self._seen = self._last_pts = None
        self._clock = 0.0       # readable seconds observed so far

    def observe(self, payload, pts):
        if self._last_pts is not None and _readable(payload):
            self._clock += max(0.0, pts - self._last_pts)
        self._last_pts = pts
        seen = street_evidence(payload)
        if seen == HAND_OVER:
            self._street = self._seen = None
        elif seen is not None:
            self._street, self._seen = seen, self._clock
        age = None if self._seen is None else self._clock - self._seen
        held = age is not None and age <= self.hold_seconds
        return {"schema_version": 1, "street": self._street if held else None,
                "source": ("board_cards" if seen not in (None, HAND_OVER)
                           else "held" if held else None),
                "age_seconds": None if age is None else round(age, 3),
                "basis": "board_card_count"}


__all__ = ["AAStreet", "board_count", "street_evidence", "STREETS"]
