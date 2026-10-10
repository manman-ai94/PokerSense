"""Reads on the opponents at the live table, for the advice.

The preflop policy (``aa_preflop``) widens or narrows what it expects from
a seat by how often that seat has put chips in (VPIP) and raised (PFR)
before the flop (``scoreboard.reads``): a seat that raises every other hand
is not the AA statistics' average player. This counts both over the hands
seen since the observation started:

- a hand counts once it is over, and only when its preflop betting replays
  on the AA table to the end with the dealer that was read
  (``aa_solver_input``): the replay knows who was dealt in and tells calls
  from checks and raises from calls. A hand whose dealer only the betting
  order gave is left out: when the first action was missed, the dealer moves
  by one seat and the seat that acted first reads as a blind that folded;
- a seat put chips in when it called something or raised, and raised when
  it raised; posting a blind or the straddle and checking are neither;
- your own seat is not counted, and a seat read empty during a hand starts
  over after it: someone else may sit there next; a bomb pot (暴击) has no
  preflop decisions and is not counted.

After the flop it counts each seat's decisions (check, call, bet, raise and
fold each once) and how many of them bet or raised, over the same hands and
bomb pots too, as far as the hand replays: the range reading
(``scoreboard.ranges``) keeps extra hands for a seat that bets clearly more
often than the AA statistics' players (21% of their postflop decisions), not
for one that only raises more before the flop.

The scoreboard checked these reads against tables of the same kind of
players; at a real table people change gears, so they are a guide, pulled
toward the statistics until a few dozen hands are in.

For the window each seat also gets a word once the hands are clear enough
(``tag``): "raises" when it raises before the flop at least a fifth of the
time, "loose" when it plays at least half its hands, "tight" when at most a
quarter (an AA player plays about 37% and raises 11%). "Clear enough" is the
one-sided 90% Wilson bound past the line, after ``TAG_HANDS`` hands at
least: a few early hands say little. A word stays until the share itself
falls back behind its line, so it does not come and go hand by hand.
"""

from __future__ import annotations

from decimal import Decimal
import math

from .aa_solver_input import HERO, hand_facts, replay_hand

TAG_HANDS = 10
Z = 1.2816              # one-sided 90%
RAISES, LOOSE, TIGHT = 0.2, 0.5, 0.25


def wilson(hits, hands):
    """(low, high) one-sided 90% Wilson bounds of a share."""
    share, z2 = hits / hands, Z * Z
    centre = (share + z2 / (2 * hands)) / (1 + z2 / hands)
    half = Z * math.sqrt(share * (1 - share) / hands + z2 / (4 * hands * hands)) / (
        1 + z2 / hands)
    return centre - half, centre + half


def holds(word, hands, played, raised):
    """Whether a seat's word still fits its shares."""
    return (word == "raises" and raised / hands >= RAISES
            or word == "loose" and played / hands >= LOOSE
            or word == "tight" and played / hands <= TIGHT)


def tag(hands, played, raised, word=None):
    """The window's word for a seat, or None (see the module notes);
    ``word`` is the one it had."""
    if hands < TAG_HANDS:
        return None
    if word is not None and holds(word, hands, played, raised):
        return word
    if wilson(raised, hands)[0] >= RAISES:
        return "raises"
    low, high = wilson(played, hands)
    return "loose" if low >= LOOSE else "tight" if high <= TIGHT else None


def preflop_entries(arena):
    """{seat: (put chips in, raised)} before the flop, from a replay that
    got past the preflop betting; None when it did not."""
    observation = arena.observe(arena.occupied_seats[0])
    if observation["street"] == "preflop" and not arena.terminal:
        return None
    entries = {seat: (False, False) for seat in arena.occupied_seats}
    for row in observation["public_history"]:
        if row["street"] != "preflop":
            continue
        raised = entries[row["actor"]][1]
        if row["kind"] == "raise_to":
            entries[row["actor"]] = (True, True)
        elif row["kind"] == "check_call" and Decimal(row["paid"]) > 0:
            entries[row["actor"]] = (True, raised)
    return entries


def postflop_actions(arena):
    """{seat: (decisions, bets or raises)} after the flop, from a replay."""
    counts = {}
    for row in arena.observe(arena.occupied_seats[0])["public_history"]:
        if row["street"] != "preflop":
            decisions, bets = counts.get(row["actor"], (0, 0))
            counts[row["actor"]] = decisions + 1, bets + (row["kind"] == "raise_to")
    return counts


class AAReads:
    """Each seat's hands, VPIP and PFR over the hands seen so far."""

    def __init__(self):
        self.reset()

    def reset(self):
        # seat -> [hands, put chips in, raised, postflop decisions, bets or raises]
        self._counts = {}
        self._words = {}        # seat -> its word for the window
        self.hands = 0          # hands counted before the flop

    def add_hand(self, rows, stakes=None):
        """Count one finished hand's frame-log rows (oldest first); True
        when it counted. ``stakes``: what earlier hands settled on
        (``aa_stakes``)."""
        if not rows:
            return False
        counted = self._count(rows, stakes)
        for row in rows:
            for slot, state in ((row.get("fields") or {}).get("participants")
                                or {}).items():
                if state == "empty":
                    self._counts.pop(int(slot), None)
        self._words = {seat: tag(*count[:3], self._words.get(seat))
                       for seat, count in self._counts.items()}
        return counted

    def _count(self, rows, stakes=None):
        facts = hand_facts(rows, stakes)
        if not facts["complete"] or not facts["actions"]:
            return False
        replay = replay_hand(facts)
        arena = replay["arena"]
        if arena is None or replay["dealer_source"] not in ("reader", "blinds"):
            return False
        bomb = arena.observe(arena.occupied_seats[0])["bomb_pot"]
        entries = {} if bomb else preflop_entries(arena)   # none in a bomb pot
        if entries is None:
            return False
        for seat, (played, raised) in entries.items():
            if seat != HERO:
                self._add(seat, 0, (1, played, raised))
        for seat, (decisions, bets) in postflop_actions(arena).items():
            if seat != HERO:
                self._add(seat, 3, (decisions, bets))
        self.hands += not bomb
        return True

    def _add(self, seat, at, values):
        count = self._counts.setdefault(seat, [0, 0, 0, 0, 0])
        for offset, value in enumerate(values):
            count[at + offset] += value

    def labels(self):
        """``snapshot`` with each seat's ``tag`` for the window."""
        return {seat: {**read, "tag": self._words.get(int(seat))}
                for seat, read in self.snapshot().items()}

    def snapshot(self):
        """{seat: {"hands", "vpip", "pfr", "postflop", "aggression"}} as the
        preflop policy and the range reading take it: ``postflop`` decisions
        after the flop and the share of them that bet or raised."""
        return {str(seat): {"hands": hands, "vpip": _share(played, hands),
                            "pfr": _share(raised, hands), "postflop": decisions,
                            "aggression": _share(bets, decisions)}
                for seat, (hands, played, raised, decisions, bets)
                in sorted(self._counts.items()) if hands or decisions}


def _share(hits, out_of):
    return round(hits / out_of, 4) if out_of else 0.0


__all__ = ["AAReads", "TAG_HANDS", "holds", "postflop_actions", "preflop_entries",
           "tag", "wilson"]
