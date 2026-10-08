"""Reads on the opponents at the live table, for the preflop advice.

The preflop policy (``aa_preflop``) widens or narrows what it expects from
a seat by how often that seat has put chips in (VPIP) and raised (PFR)
before the flop (``scoreboard.reads``): a seat that raises every other hand
is not the AA statistics' average player. This counts both over the hands
seen since the observation started:

- a hand counts once it is over, and only when its preflop betting replays
  on the AA table to the end (``aa_solver_input``): the replay knows who was
  dealt in and tells calls from checks and raises from calls;
- a seat put chips in when it called something or raised, and raised when
  it raised; posting a blind or the straddle and checking are neither;
- your own seat is not counted, and a seat read empty during a hand starts
  over after it: someone else may sit there next.

The scoreboard checked these reads against tables of the same kind of
players; at a real table people change gears, so they are a guide, pulled
toward the statistics until a few dozen hands are in.
"""

from __future__ import annotations

from decimal import Decimal

from .aa_solver_input import HERO, hand_facts, replay_hand


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


class AAReads:
    """Each seat's hands, VPIP and PFR over the hands seen so far."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._counts = {}       # seat -> [hands, put chips in, raised]
        self.hands = 0          # hands counted

    def add_hand(self, rows):
        """Count one finished hand's frame-log rows (oldest first); True
        when it counted."""
        if not rows:
            return False
        counted = self._count(rows)
        for row in rows:
            for slot, state in ((row.get("fields") or {}).get("participants")
                                or {}).items():
                if state == "empty":
                    self._counts.pop(int(slot), None)
        return counted

    def _count(self, rows):
        facts = hand_facts(rows)
        if not facts["complete"] or not facts["actions"]:
            return False
        replay = replay_hand(facts)
        if replay["arena"] is None:
            return False
        entries = preflop_entries(replay["arena"])
        if entries is None:
            return False
        for seat, (played, raised) in entries.items():
            if seat == HERO:
                continue
            count = self._counts.setdefault(seat, [0, 0, 0])
            count[0] += 1
            count[1] += played
            count[2] += raised
        self.hands += 1
        return True

    def snapshot(self):
        """{seat: {"hands", "vpip", "pfr"}} as the preflop policy takes it."""
        return {str(seat): {"hands": hands, "vpip": round(played / hands, 4),
                            "pfr": round(raised / hands, 4)}
                for seat, (hands, played, raised) in sorted(self._counts.items())
                if hands}


__all__ = ["AAReads", "preflop_entries"]
