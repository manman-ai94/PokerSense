"""One reading per card in a hand: a card read differently is held back.

Real cards do not change within a hand: each board slot keeps the card
dealt to it and your two cards stay the same. On peng's eight recordings of
10/08-10/10 (366 hands) a board slot read two ways in 19 hands, and nearly
every time it was the same thing: at an all-in something covered the middle
of the board for about half a second and the third card was read as
another one (mostly a queen or a ten of the same colour), then as before
again. Your cards were read two ways once the showdown dimmed them (a
diamond read as a spade). Half a second of a wrong reading is enough for
the advice to count a wrong card, and for the one-page rules to refuse the
whole hand (``card_conflict``).

So each board slot, and your two cards as a pair, adds up how long each
reading has been read in this hand. Only the reading read longest is shown;
another reading leaves the slot (or your cards) unknown on that frame, not
guessed. A later reading takes over once it has been read ``MARGIN_SECONDS``
longer than the first: then the first was the mistake (a card read wrong
while it was being dealt), and both readings have been shown.

- A new hand (the action history's ``hand_id``) starts again. The last
  hand's cards can still be on screen for a moment: the last hand's reading
  in a slot is passed on as it is and not counted, until the slot reads
  something else or nothing on ``STALE_EMPTY_FRAMES`` frames in a row.
- A missed start of a hand: your two cards both read as other cards with
  other ranks (a dimmed card keeps its rank), or three or more board slots
  read as other cards while none reads as before, on ``NEW_DEAL_FRAMES``
  frames in a row, is a new deal and starts again.
"""

from __future__ import annotations

SCHEMA_VERSION = 1
SLOTS = 5
MARGIN_SECONDS = 1.0            # a later reading must lead by this much
NEW_DEAL_FRAMES = 3             # frames in a row of a whole new deal
NEW_BOARD_SLOTS = 3             # board slots read as other cards at once
STALE_EMPTY_FRAMES = 3          # empty frames that end the last hand's card
MAX_STEP_SECONDS = 0.5          # one frame never counts for more than this
FIRST_STEP_SECONDS = 0.1


class _Slot:
    """How long each reading has been read in this hand, for one place."""

    def __init__(self):
        self.seconds = {}
        self.shown = None               # the reading that is shown
        self.stale = None               # the last hand's reading, still on screen
        self._empty = 0

    def new_hand(self):
        if self.shown is not None:
            self.stale = self.shown
        self.seconds, self.shown, self._empty = {}, None, 0

    def differs(self, value):
        """True when ``value`` is counted here and is not the shown reading."""
        return (value is not None and value != self.stale
                and self.shown is not None and value != self.shown)

    def observe(self, value, step):
        """The reading to show: ``value`` or None (held back)."""
        if self.stale is not None:
            if value == self.stale:
                self._empty = 0
                return value
            if value is None:
                self._empty += 1
                if self._empty >= STALE_EMPTY_FRAMES:
                    self.stale = None
                return None
            self.stale = None
        if value is None:
            return None
        self.seconds[value] = self.seconds.get(value, 0.) + step
        if self.shown is None or (value != self.shown and self.seconds[value]
                                  > self.seconds[self.shown] + MARGIN_SECONDS):
            self.shown = value
        return value if value == self.shown else None


def _ranks(pair):
    return sorted(card[0] for card in pair)


class AACardCheck:
    """``observe`` once per frame, after the action history."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._hand = None
        self._pts = None
        self._hero = _Slot()
        self._board = [_Slot() for _ in range(SLOTS)]
        self._new_deal = (None, 0)

    def _new_hand(self):
        self._hero.new_hand()
        for slot in self._board:
            slot.new_hand()
        self._new_deal = (None, 0)

    def _whole_new_deal(self, pair, board):
        shown = self._hero.shown
        hero_new = (self._hero.differs(pair) and not set(pair) & set(shown)
                    and _ranks(pair) != _ranks(shown))
        slots = list(zip(self._board, board))
        others = [value for slot, value in slots if slot.differs(value)]
        same = [value for slot, value in slots
                if value is not None and value == slot.shown]
        board_new = len(others) >= NEW_BOARD_SLOTS and not same
        if not (hero_new or board_new):
            self._new_deal = (None, 0)
            return False
        key = (pair if hero_new else None, tuple(board) if board_new else None)
        seen, frames = self._new_deal
        frames = frames + 1 if seen == key else 1
        self._new_deal = (key, frames)
        return frames >= NEW_DEAL_FRAMES

    def observe(self, hero, board, hand_id, pts):
        """(your cards, the five board slots, a report) as they may be shown.

        ``hero``: the reader's two cards or None; ``board``: five slots, each
        a card or None; ``pts``: the frame's time in seconds."""
        hero = list(hero) if hero and len(hero) == 2 and all(hero) else None
        pair = tuple(sorted(hero)) if hero else None
        board = (list(board or ()) + [None] * SLOTS)[:SLOTS]
        step = (FIRST_STEP_SECONDS if self._pts is None or pts is None
                else min(max(pts - self._pts, 0.), MAX_STEP_SECONDS))
        self._pts = pts
        if hand_id != self._hand:
            if self._hand is not None:
                self._new_hand()
            self._hand = hand_id
        new_deal = self._whole_new_deal(pair, board)
        if new_deal:
            self._new_hand()
        hero_out = hero if self._hero.observe(pair, step) is not None else None
        board_out = [slot.observe(value, step)
                     for slot, value in zip(self._board, board)]
        held = {"hero": hero if hero is not None and hero_out is None else None,
                "board": {str(at): value for at, (value, shown)
                          in enumerate(zip(board, board_out))
                          if value is not None and shown is None}}
        return hero_out, board_out, {
            "schema_version": SCHEMA_VERSION, "hand_id": hand_id,
            "new_deal": new_deal,
            "held_back": held if held["hero"] or held["board"] else None}
