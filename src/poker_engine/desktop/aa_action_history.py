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
- **missed calls and raises**: a seat still in the hand whose steady stack
  goes down (not to 0) by just what the nearest pot rise still holds, with
  no call or raise of its own read nearby, put those chips in (``amount_source``
  "stack_drop"). The replay makes it a call or a raise by what the others
  have in. Only once the hand was seen before the flop and its first pot
  was read: the blinds, the straddle and a bomb pot's posts go in before
  it, while the street can still be the last hand's. At 5- and
  6-handed tables on 10/08 none of the top seat's 21 bets and raises was
  read as one, while its stack was read on 99% of frames;
- **badges read again**: a fold read for a seat that already folded, or a
  check or call for a seat that already checked or called on the street
  with no bet since, is the badge still shown and read again, and is left
  out;
- **hand**: a new hand starts when the steady pot goes down, the board goes
  back to preflop, the dealer button moves, or after a readable table
  showed no hand in progress. A hand already running when observation
  started (or restarted after a gap of more than a few seconds, see
  ``aa_reader``) is marked incomplete: actions before it are unknown.
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
        self._held = {}                          # seat -> last frame it was read
        self._wager_reads = {}                   # seat -> (value, count)
        self._wagers = {}                        # seat -> (hand, street, most in)
        self._drops = []                         # stack drops not placed yet
        self._opened = None                      # first frame of the hand's pot

    # -- hands -----------------------------------------------------------------

    def _start(self, frame, dealer, reason, complete=True):
        self._hand = {"hand_id": f"hand_{frame}", "start_frame": frame,
                      "dealer": dealer, "complete": complete, "start": reason,
                      "actions": [], "streets": set()}
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
        if "drop" in action:
            self._price_drop(action, now)
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
        if found == "pending" and self._from_wager(action):
            return
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

    def _from_wager(self, action):
        """While the pot is unreadable, price a call or raise after the flop by
        the seat's bet on the table: what it has in on the street minus what
        its earlier actions there put in. Its pot rise is settled later, as
        for a call the betting prices. Not before the flop (the blinds are in
        the bet but not in the actions), nor when a later action of the seat
        on the street may be in the bet too. True when priced.

        On 10/09 the pot went unreadable around several bets and all-ins
        while the bets on the table were read; the action then waited for
        the pot, and the replay stopped on a raise without an amount (12
        hands; 5 of your decisions got only the rough advice)."""
        if action["street"] not in POSTFLOP:
            return False
        level = self._wager(action)
        mine = [other for other in self._hand["actions"]
                if other is not action and other["slot"] == action["slot"]
                and other["street"] == action["street"] and other["kind"] in PRICED]
        if level is None or any(other["frame"] > action["frame"] for other in mine):
            return False
        if any(other["amount"] is None for other in mine):
            return False
        chips = level - sum(Decimal(other["amount"]) for other in mine)
        if chips <= 0:
            return False
        action["amount"], action["amount_source"] = str(chips), "wager"
        action["owed"] = chips
        return True

    def _wager(self, action):
        """The most ``action``'s seat was read to have in on its street, or None."""
        known = self._wagers.get(str(action["slot"]))
        if known is None or known[:2] != (self._hand["hand_id"], action["street"]):
            return None
        return known[2]

    def _price_all_in(self, action, now):
        """An all-in seen from the stack takes the chips it had out of the
        nearest rise (the rise wins when smaller). Without a rise it is not
        confirmed and is dropped. While the pot is unreadable, the seat's bet
        on the table holding at least those chips confirms it at once (its
        rise is settled later): on 10/09 three all-ins waited for the pot at
        your turn and got only the rough advice."""
        found = self._rise(action["frame"], now)
        if found == "pending":
            level = self._wager(action)
            if level is not None and level >= action["stack"]:
                action["amount"] = str(action["stack"])
                action["amount_source"], action["owed"] = "stack", action["stack"]
            return
        if found is None:
            action["amount_source"] = "unconfirmed"
            return
        chips = min(action["stack"], found[1])
        self._shares[found[0]] = self._shares.get(found[0], 0) + chips
        action["amount"] = str(chips)
        action["amount_source"] = "stack" if chips == action["stack"] else "pot_rise"

    def _price_drop(self, action, now):
        """A call or raise seen from a stack drop needs the nearest pot rise to
        hold just those chips; otherwise it is not confirmed and is dropped (a
        stack read late, or an ante or blind read after the pot)."""
        found = self._rise(action["frame"], now)
        if found == "pending":
            return
        if found is None or found[1] != action["drop"]:
            action["amount_source"] = "unconfirmed"
            return
        self._shares[found[0]] = self._shares.get(found[0], 0) + action["drop"]
        action["amount"], action["amount_source"] = str(action["drop"]), "stack_drop"

    def _watch_stacks(self, payload, frame):
        """Add an all-in for a seat whose steady stack drops to 0 with no call
        or raise of its own nearby."""
        hand = self._hand
        for slot, item in (payload.get("stacks") or {}).items():
            value = _amount((item or {}).get("value"))
            if value is None:
                continue
            if value == self._stacks.get(slot):
                self._held[slot] = frame
            last, count, first = self._stack_reads.get(slot, (None, 0, frame))
            count, first = (count + 1, first) if value == last else (1, frame)
            self._stack_reads[slot] = (value, count, first)
            if count != 2:
                continue
            before, self._stacks[slot] = self._stacks.get(slot), value
            if (before is not None and 0 < value < before
                    and first - self._held.get(slot, first) <= AFTER):
                # Only a drop from a stack still read just before it: after a
                # stretch unread the chips may have gone in long ago.
                self._drops.append((int(slot), first, before - value))
            self._held[slot] = frame
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

    def _watch_wagers(self, payload, frame):
        """The most each seat was read to have in on this street (a bet only
        grows on a street), for telling a call from a raise."""
        hand = self._hand
        for slot, raw in (payload.get("street_wagers") or {}).items():
            value = _amount(raw)
            last, count = self._wager_reads.get(slot, (None, 0))
            count = count + 1 if value == last else 1
            self._wager_reads[slot] = (value, count)
            street = self._street_at(frame)
            if value is None or count != 2 or street not in STREETS:
                continue
            known = self._wagers.get(slot)
            if known is not None and known[:2] == (hand["hand_id"], street):
                value = max(value, known[2])
            self._wagers[slot] = (hand["hand_id"], street, value)

    def _place_drops(self):
        """Add a call or raise for each stack drop with no call or raise of
        the seat's own read nearby (see the module notes)."""
        hand = self._hand
        for seat, at, chips in self._drops:
            street = self._street_at(at)
            mine = [a for a in hand["actions"] if a["slot"] == seat]
            if (at < hand["start_frame"] or self._opened is None
                    or at <= self._opened or "preflop" not in hand["streets"]
                    or street not in STREETS
                    or any(a["kind"] == "fold" and a["frame"] < at for a in mine)
                    or any(a["kind"] in PRICED and abs(a["frame"] - at) <= AFTER
                           for a in mine)):
                continue
            put = {}
            for action in hand["actions"]:
                if action["street"] == street and action["amount"] is not None:
                    put[action["slot"]] = put.get(action["slot"], 0) + Decimal(
                        action["amount"])
            for slot, (hand_id, on, level) in self._wagers.items():
                if (hand_id, on) == (hand["hand_id"], street):
                    put[int(slot)] = max(put.get(int(slot), 0), level)
            level = put.pop(seat, 0) + chips
            hand["actions"].append({
                "frame": at, "street": street, "slot": seat,
                "kind": "raise" if level > max(put.values(), default=0) else "call",
                "amount": None, "amount_source": "pending", "cash_amount": None,
                "drop": chips})
        self._drops = []
        hand["actions"].sort(key=lambda action: action["frame"])

    # -- frames ----------------------------------------------------------------

    def observe(self, payload, frame):
        pot = _amount((payload.get("pot") or {}).get("value"))
        street = (payload.get("street_v1") or {}).get("street")
        if street_evidence(payload) == HAND_OVER and street is None:
            # The street layer clears the street once the hand is really over,
            # not when the board is just unread for a moment after the flop.
            self._hand_over = True
        dropped = False
        if pot is not None:
            self._pots.append((frame, pot))
            runs = steady_runs(list(self._pots)[-3:])
            steady = runs[-1][0] if runs else None
            dropped = steady is not None and self._steady is not None and \
                steady < self._steady
            if dropped:
                self._opened = None
            elif steady and self._opened is None:
                self._opened = frame
            if steady is not None:
                self._steady = steady
        reading = payload.get("dealer_seat")
        self._dealers.append(reading if isinstance(reading, int) else None)
        dealer = (self._dealers[0] if len(self._dealers) == 2
                  and self._dealers[0] == self._dealers[1] else None)
        reason = self._boundary(payload, frame, street, dropped, dealer)
        if reason is not None:
            self._opened = None           # the new hand's pot is read after this
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
            self._hand["streets"].add(street)
        self._take(payload, frame)
        self._watch_wagers(payload, frame)
        self._watch_stacks(payload, frame)
        self._place_drops()
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
            seen = next((other for other in hand["actions"]
                         if ("stack" in other or "drop" in other)
                         and other["slot"] == event.get("slot")
                         and abs(other["frame"] - event["frame"]) <= AFTER), None)
            if priced and seen is not None:
                if "drop" not in seen or seen["amount_source"] != "pending":
                    if "drop" in seen and kind in ("call", "raise"):
                        seen["kind"] = kind   # its chips came from the stack
                    continue              # already seen from the stack
                hand["actions"].remove(seen)  # not confirmed yet: the badge wins
            street = self._street_at(event["frame"])
            if self._read_again(event["slot"], kind, street, event["frame"]):
                continue                  # a badge still shown, read again
            hand["actions"].append({
                "frame": event["frame"], "street": street,
                "slot": event.get("slot"), "kind": kind,
                "amount": None if priced else "0",
                "amount_source": "pending" if priced else "no_chips",
                "cash_amount": event.get("amount") if priced else None})
        # Priced in frame order afterwards: a call's chips depend on the bets
        # before it on the same street.
        hand["actions"].sort(key=lambda action: action["frame"])

    def _read_again(self, seat, kind, street, frame):
        """A badge still shown and read again: ``seat`` already folded in this
        hand, or already checked or called on ``street`` with nobody betting
        since. A call badge is sometimes read again, often for several seats
        in one frame as the street ends (10/08); after a stall the reader
        starts over and reads every badge on the table again."""
        before = [a for a in self._hand["actions"] if a["frame"] < frame]
        if kind == "fold":
            return any(a["slot"] == seat and a["kind"] == "fold" for a in before)
        if kind not in ("check", "call"):
            return False
        before = [a for a in before if a["street"] == street]
        mine = [index for index, a in enumerate(before) if a["slot"] == seat]
        if not mine or before[mine[-1]]["kind"] != kind:
            return False
        return not any(a["kind"] in ("raise", "all_in")
                       for a in before[mine[-1] + 1:])

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
                         "bets on the table, board-card street"}


__all__ = ["AAActionHistory", "COMPACT_FIELDS", "steady_runs"]
