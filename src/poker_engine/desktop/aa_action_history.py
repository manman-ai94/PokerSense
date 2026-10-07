"""The current hand's betting history, for strategy input.

The reader already turns action badges (fold, check, call, raise, all in)
into actions, but the amounts come only from matching a stack decrease, and
its streets and hands drift: on new recordings only about half the calls and
raises had an amount and about one action in ten sat on the wrong street.
This layer keeps the reader's actions and rebuilds the rest:

- **street**: the board-card street (``street_v1``) at the action's frame;
- **amount**: the pot rise nearest to the action. The displayed pot includes
  the street's bets, so a call or a raise lifts it from one steady value to
  the next, usually a little before the badge is read. On three recordings
  this matched every one of the 147 amounts the reader had, and gave 94% of
  calls and raises an amount. A call after the flop is priced by the betting
  instead (the street's highest bet minus what the caller already put in),
  which also splits a rise that held the next bet too while the pot was
  unreadable. Chips of a rise are given out once; the rise from an empty
  pot is the blinds and antes, never an action;
- **all in**: Mac recordings show the All in badge in a style the reader
  does not match, and some all-ins turn the cards face up at once. A seat
  whose steady stack drops to 0 with no call or raise of its own nearby
  went all in, if the pot rises next to it: the action gets the stack it
  had (or the rise, when smaller). On two recordings each such drop matched
  a pot rise no action explained;
- **hand**: a new hand starts when the steady pot goes down, the board goes
  back to preflop, the dealer button moves, or after a readable table
  showed no hand in progress. A hand already running when observation
  started (or restarted after a gap) is marked incomplete: actions before
  it are unknown.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal, InvalidOperation

from .aa_street import HAND_OVER, street_evidence

STREETS = ("preflop", "flop", "turn", "river")
POSTFLOP = STREETS[1:]
KINDS = {"fold": "fold", "check": "check", "call": "call", "aggressive": "raise",
         "raise": "raise", "bet": "raise", "all_in": "all_in"}
PRICED = frozenset({"call", "raise", "all_in"})
BEFORE, AFTER = 10, 15          # reader frames searched around an action's frame
WAIT = 120                      # longest wait for an unreadable pot to come back
HISTORY = 400                   # reader frames of pot and street kept
# One action in the compact form the measurement log keeps (``frame_summary``).
COMPACT_FIELDS = ("frame", "street", "slot", "kind", "amount", "source")


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def steady_runs(pots):
    """Pot values read on at least two frames in a row: [(value, first, last)]."""
    runs, value, first, last, count = [], None, None, None, 0
    for frame, pot in pots:
        if pot == value:
            last, count = frame, count + 1
            continue
        if value is not None and count >= 2:
            runs.append((value, first, last))
        value, first, last, count = pot, frame, frame, 1
    if value is not None and count >= 2:
        runs.append((value, first, last))
    return runs


class AAActionHistory:
    """Track hands and their actions across frames of one continuous observation."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._pots = deque(maxlen=HISTORY)       # (frame, pot) readable frames
        self._streets = deque(maxlen=HISTORY)    # (frame, street)
        self._taken = set()                      # reader actions already placed
        self._shares = {}                        # pot rise -> chips given out
        self._hand = None
        self._hand_over = False
        self._steady = None                      # last steady pot value
        self._dealers = deque(maxlen=2)          # last dealer readings
        self._stack_reads = {}                   # seat -> (value, count, first)
        self._stacks = {}                        # seat -> last steady stack

    # -- hands -----------------------------------------------------------------

    def _start(self, frame, dealer, reason, complete=True):
        self._hand = {"hand_id": f"hand_{frame}", "start_frame": frame,
                      "dealer": dealer, "complete": complete, "start": reason,
                      "actions": []}
        self._hand_over = False

    def _boundary(self, payload, frame, street, dropped, dealer):
        """Why a new hand starts at this frame, or None."""
        hand = self._hand
        if hand is None:
            return "first_hand_seen"
        if self._hand_over and street in STREETS:
            return "after_hand_over"
        last = next((s for f, s in reversed(self._streets) if f < frame), None)
        if (street == "preflop" and last in STREETS[1:]
                and street_evidence(payload) == "preflop"):
            return "board_cleared"
        if None not in (dealer, hand["dealer"]) and dealer != hand["dealer"]:
            return "dealer_moved"
        if dropped:
            return "pot_went_down"
        return None

    # -- amounts ---------------------------------------------------------------

    def _rise(self, frame, now):
        """(rise frame, chips left) of the pot rise nearest to ``frame``;
        "pending" while it may still come; None if there is none.

        A rise runs from the last frame the old pot was read to the first frame
        the new one was: the pot is sometimes unreadable for seconds right when
        chips go in, and the whole span counts. The nearest span to the action
        wins (within BEFORE frames before it and AFTER after it). Chips already
        given to other actions are not given again.
        """
        runs = steady_runs(self._pots)
        best = None
        for old, new in zip(runs, runs[1:]):
            left = new[0] - old[0] - self._shares.get(new[1], 0)
            if old[0] == 0 or left <= 0:
                continue
            last_old, first_new = old[2], new[1]
            distance = (0 if last_old <= frame <= first_new
                        else last_old - frame if frame < last_old
                        else frame - first_new)
            allowed = BEFORE if frame > first_new else AFTER
            if distance <= allowed and (best is None or distance < best[0]):
                best = (distance, first_new, left)
        if best is not None:
            return best[1], best[2]
        # A steady pot read past the window settles it; an unreadable pot keeps
        # the action waiting (at most WAIT frames) for the pot to come back.
        settled = any(run[2] > frame + AFTER for run in runs)
        waiting = now < frame + AFTER or (not settled and now < frame + WAIT)
        return "pending" if waiting else None

    def _owed(self, action):
        """What a call after the flop adds: the street's highest bet minus what
        the caller already put in. "pending" while an earlier bet on the street
        has no chips yet; None when the betting cannot tell."""
        if action["kind"] != "call" or action["street"] not in POSTFLOP:
            return None
        put = {}
        for other in self._hand["actions"]:
            if other is action:
                break
            if other["street"] != action["street"] or other["kind"] not in PRICED:
                continue
            if other["amount_source"] == "pending":
                return "pending"
            if other["amount"] is None:
                return None
            put[other["slot"]] = put.get(other["slot"], 0) + Decimal(other["amount"])
        owed = max(put.values(), default=0) - put.get(action["slot"], 0)
        return owed if owed > 0 else None

    def _price(self, action, now):
        """Give a call or raise its chips once they are known.

        A call the betting prices gets its chips at once; its pot rise is
        settled later. Other calls and raises take what is left of the
        nearest rise.
        """
        if "stack" in action:
            self._price_all_in(action, now)
            return
        owed = self._owed(action)
        if owed == "pending":
            action["amount_source"] = "pending"
            return
        if owed is not None:
            action["amount"], action["amount_source"] = str(owed), "street_logic"
            action["owed"] = owed
            self._settle(action, now)
            return
        found = self._rise(action["frame"], now)
        if found == "pending":
            action["amount_source"] = "pending"
        elif found is not None:
            self._shares[found[0]] = self._shares.get(found[0], 0) + found[1]
            action["amount"], action["amount_source"] = str(found[1]), "pot_rise"
        else:
            cash = action["cash_amount"]
            action["amount"] = cash
            action["amount_source"] = "cash" if cash is not None else "unknown"

    def _settle(self, action, now):
        """Take a betting-priced call's chips out of its pot rise once read.

        The rest of the rise stays for the next bet: the same rise holds both
        when the pot was unreadable in between. A rise smaller than what was
        owed (a short all-in call) wins.
        """
        found = self._rise(action["frame"], now)
        if found == "pending":
            return
        owed = action.pop("owed")
        if found is not None:
            self._shares[found[0]] = self._shares.get(found[0], 0) + min(owed, found[1])
            if found[1] <= owed:
                action["amount"], action["amount_source"] = str(found[1]), "pot_rise"

    def _price_all_in(self, action, now):
        """An all-in seen from the stack takes the chips it had out of the
        nearest rise (the rise wins when smaller). Without a rise it is not
        confirmed and is dropped."""
        found = self._rise(action["frame"], now)
        if found == "pending":
            return
        if found is None:
            action["amount_source"] = "unconfirmed"
            return
        chips = min(action["stack"], found[1])
        self._shares[found[0]] = self._shares.get(found[0], 0) + chips
        action["amount"] = str(chips)
        action["amount_source"] = "stack" if chips == action["stack"] else "pot_rise"

    def _watch_stacks(self, payload, frame):
        """Add an all-in for a seat whose steady stack drops to 0 with no call
        or raise of its own nearby."""
        hand = self._hand
        for slot, item in (payload.get("stacks") or {}).items():
            value = _amount((item or {}).get("value"))
            if value is None:
                continue
            last, count, first = self._stack_reads.get(slot, (None, 0, frame))
            count, first = (count + 1, first) if value == last else (1, frame)
            self._stack_reads[slot] = (value, count, first)
            if count != 2:
                continue
            before, self._stacks[slot] = self._stacks.get(slot), value
            if value != 0 or not before or first < hand["start_frame"]:
                continue
            seat = int(slot)
            if any(a["slot"] == seat and a["kind"] in PRICED
                   and abs(a["frame"] - first) <= AFTER for a in hand["actions"]):
                continue
            hand["actions"].append({
                "frame": first, "street": self._street_at(first), "slot": seat,
                "kind": "all_in", "amount": None, "amount_source": "pending",
                "cash_amount": None, "stack": before})
        hand["actions"].sort(key=lambda action: action["frame"])

    # -- frames ----------------------------------------------------------------

    def observe(self, payload, frame):
        pot = _amount((payload.get("pot") or {}).get("value"))
        street = (payload.get("street_v1") or {}).get("street")
        if street_evidence(payload) == HAND_OVER:
            self._hand_over = True
        dropped = False
        if pot is not None:
            self._pots.append((frame, pot))
            runs = steady_runs(list(self._pots)[-3:])
            steady = runs[-1][0] if runs else None
            dropped = steady is not None and self._steady is not None and \
                steady < self._steady
            if steady is not None:
                self._steady = steady
        reading = payload.get("dealer_seat")
        self._dealers.append(reading if isinstance(reading, int) else None)
        dealer = (self._dealers[0] if len(self._dealers) == 2
                  and self._dealers[0] == self._dealers[1] else None)
        reason = self._boundary(payload, frame, street, dropped, dealer)
        hand = self._hand
        if (reason is not None and hand is not None and hand["complete"]
                and not hand["actions"]):
            # Between hands the board clears, the pot resets and the button moves
            # one after another: while the new hand has no action yet they all
            # mark the same start, which stays at the first of them.
            hand["dealer"] = dealer if dealer is not None else hand["dealer"]
            self._hand_over = False
        elif reason is not None:
            self._start(frame, dealer, reason, complete=reason != "first_hand_seen")
            self._shares.clear()
        elif self._hand["dealer"] is None and dealer is not None:
            self._hand["dealer"] = dealer
        if street in STREETS:
            self._streets.append((frame, street))
        self._take(payload, frame)
        self._watch_stacks(payload, frame)
        for action in self._hand["actions"]:
            if action["amount_source"] == "pending":
                self._price(action, frame)
            elif "owed" in action:
                self._settle(action, frame)
        self._hand["actions"] = [action for action in self._hand["actions"]
                                 if action["amount_source"] != "unconfirmed"]
        return self.snapshot()

    def _street_at(self, frame):
        known = [s for f, s in self._streets if f <= frame]
        return known[-1] if known else None

    def _take(self, payload, frame):
        hand = self._hand
        for event in payload.get("action_history_candidate") or ():
            key = (event.get("frame"), event.get("slot"), event.get("kind"))
            kind = KINDS.get(event.get("kind"))
            if key in self._taken or kind is None or event.get("frame") is None:
                continue
            self._taken.add(key)
            if event["frame"] < hand["start_frame"]:
                continue                  # belongs to a hand already over
            priced = kind in PRICED
            if priced and any("stack" in other and other["slot"] == event.get("slot")
                              and abs(other["frame"] - event["frame"]) <= AFTER
                              for other in hand["actions"]):
                continue                  # the all-in already seen from the stack
            hand["actions"].append({
                "frame": event["frame"], "street": self._street_at(event["frame"]),
                "slot": event.get("slot"), "kind": kind,
                "amount": None if priced else "0",
                "amount_source": "pending" if priced else "no_chips",
                "cash_amount": event.get("amount") if priced else None})
        # Priced in frame order afterwards: a call's chips depend on the bets
        # before it on the same street.
        hand["actions"].sort(key=lambda action: action["frame"])

    def snapshot(self):
        hand = self._hand
        actions = [{key: action[key] for key in
                    ("frame", "street", "slot", "kind", "amount", "amount_source")}
                   for action in hand["actions"]]
        return {"schema_version": 1, "hand_id": hand["hand_id"],
                "start_frame": hand["start_frame"], "start": hand["start"],
                "dealer": hand["dealer"], "complete": hand["complete"],
                "actions": actions,
                "pending_amounts": sum(a["amount_source"] == "pending"
                                       for a in actions),
                "missing_amounts": sum(a["amount_source"] == "unknown"
                                       for a in actions),
                "basis": "reader action badges, pot rises, betting, stacks, "
                         "board-card street"}


__all__ = ["AAActionHistory", "COMPACT_FIELDS", "steady_runs"]
