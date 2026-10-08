"""How each of your decisions compares with the advice, once you have acted.

The advice for one of your decisions (``AASolverAdvice``; a solve that
finishes after you acted counts too) is kept with what the table showed at
the time, until your action for it appears in the hand's history
(``action_history_v1``). Then the action is graded:

- preflop, by the big blinds it gives up against the most valuable option
  (the ``aa_preflop`` values): under 0.05 best, under 0.5 fine, under 2 a
  slip, else a mistake;
- turn and river, by how often the solver takes that action, every bet or
  raise size counted together: its most frequent action or at least half the
  time best, at least 20% fine, at least 2% a slip, else a mistake;
- after the flop with more than one opponent, and on the heads-up flop,
  against the action your share of the pot against their ranges called for
  (``range_multiway``, its heads-up cuts against one opponent): that
  action best, otherwise by how far the share is from where your action
  would have been the one: under 5 points fine, under 15 a slip, else a
  mistake.

An action that cannot be matched to an option (a check facing a bet, a raise
the policy did not offer) is left ungraded rather than guessed. Every grade
of this observation is kept, newest first in the report, with the hands you
were dealt, how many grades were best, and the big blinds given up preflop.

The report also sums up the observation for the session list: how many of
your actions there were and how many had advice ready, how many grades of
each kind, and your chips won or lost in big blinds (``HeroChips``).
For study only; nothing here acts on the client.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import time

from .aa_session import frame_summary
from .aa_solver_input import RULES_PATH

HERO = 4
SHOWN = 20                          # grades sent with each frame, newest first
DEALT = frozenset({"active", "folded", "all_in"})
AGGRESSIVE = frozenset({"bet", "raise", "allin"})
PREFLOP = ((0.05, "best"), (0.5, "fine"), (2.0, "slip"))       # big blinds lost
SOLVER = ((0.5, "best"), (0.2, "fine"), (0.02, "slip"))        # solver frequency
MULTIWAY = ((0.05, "fine"), (0.15, "slip"))     # share off your action's span
GRADES = ("best", "fine", "slip", "mistake")
IN_PLAY = frozenset({"active", "all_in"})
BIG_BLIND = Decimal(json.loads(RULES_PATH.read_text(encoding="utf-8"))["big_blind"])


def _decimal(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _slot(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _band(value, bands, above):
    """The grade of the first band ``value`` falls in."""
    for limit, grade in bands:
        if (value < limit) if not above else (value >= limit):
            return grade
    return "mistake"


def preflop_choice(kind, options, to_call, stack):
    """The preflop option your action took, or None when none fits."""
    names = {row["action"] for row in options}
    if kind == "all_in":
        kind = ("call" if None not in (to_call, stack) and stack <= to_call
                else "raise")
    if kind == "call" and "call" not in names and to_call == 0:
        kind = "check"
    return kind if kind in names else None


def preflop_grade(kind, options, to_call, stack):
    chosen = preflop_choice(kind, options, to_call, stack)
    if chosen is None:
        return None
    value = next(row["big_blinds"] for row in options if row["action"] == chosen)
    lost = max(0.0, max(row["big_blinds"] for row in options) - value)
    return {"chosen": chosen, "lost_big_blinds": round(lost, 2),
            "grade": _band(lost, PREFLOP, above=False)}


def solver_group(action):
    return "raise" if action in AGGRESSIVE else action


def _kind(kind, to_call, stack):
    """Your action as fold, check, call or raise; None when not possible."""
    if kind == "all_in":
        kind = ("call" if None not in (to_call, stack) and stack <= to_call
                else "raise")
    if kind == "call" and to_call == 0:
        kind = "check"
    if kind == "check" and to_call is not None and to_call > 0:
        return None
    return kind if kind in ("fold", "check", "call", "raise") else None


def solver_grade(kind, rows, to_call, stack):
    """Your action against the solver's mix, or None when it was not possible."""
    kind = _kind(kind, to_call, stack)
    if kind is None:
        return None
    shares = {}
    for row in rows:
        group = solver_group(row["action"])
        shares[group] = shares.get(group, 0.0) + row["frequency"]
    share = shares.get(kind, 0.0)
    top = max(shares.values(), default=0.0)
    grade = "best" if share > 0 and share >= top else _band(share, SOLVER, above=True)
    return {"chosen": kind, "frequency": round(share, 3), "grade": grade}


def multiway_grade(kind, outcome, to_call, stack):
    """Your action against the ``range_multiway`` advice, or None when it was
    not possible: how far your share of the pot was from your action's span."""
    kind = _kind(kind, to_call, stack)
    share = (outcome.get("range_equity") or {}).get("value")
    line, rows = outcome.get("cuts") or {}, outcome.get("advice") or []
    if kind is None or share is None or not rows:
        return None
    if "bet" in line:
        spans = {"check": (0.0, line["bet"]), "raise": (line["bet"], 1.0)}
    else:
        spans = {"fold": (0.0, line["call"]), "call": (line["call"], line["raise"]),
                 "raise": (line["raise"], 1.0)}
    if kind not in spans:
        return None
    low, high = spans[kind]
    gap = max(0.0, low - share, share - high)
    best = kind == solver_group(rows[0]["action"])
    return {"chosen": kind, "share": share, "gap": round(gap, 3),
            "grade": "best" if best else _band(gap, MULTIWAY, above=False)}


def _facing(actions, street):
    """The street's last bet or raise before you, and how many there were."""
    raises = [a for a in actions if a[1] == street and a[3] in ("raise", "all_in")]
    if not raises:
        return None
    last = raises[-1]
    return {"slot": last[2], "kind": last[3], "amount": last[4], "raises": len(raises)}


class HeroChips:
    """Your chips won or lost since you were first dealt in, rebuys left out.

    What you have is your stack plus the chips in front of you on this
    street (a blind you posted is still in front of you when the hand
    starts); after you fold only the stack is yours. A reading counts once
    two readable frames in a row agree. The result moves when a new hand
    starts and while you are out of the hand (folded, or waiting with no
    cards), so the chips of a pot still being played do not count as lost
    or won yet. Coming back from 0, or after the seat was read empty, while
    you are not in a hand is a rebuy or a new buy-in: the change is not a
    result (a pot you win after being all in comes while you are still in
    the hand)."""

    def __init__(self):
        self.start = self.settled = self._last = self._steady = None
        self.rebuys, self.added, self._hand = 0, Decimal(0), None
        self._empty, self._away = 0, False

    def observe(self, fields, hand, dealt):
        stacks = fields.get("stacks") or {}
        state = (fields.get("participants") or {}).get(str(HERO))
        total = _decimal(stacks.get(str(HERO), stacks.get(HERO)))
        front = _decimal((fields.get("street_wagers") or {}).get(str(HERO)))
        if total is not None and front is not None and state != "folded":
            total += front
        self._empty = self._empty + 1 if state == "empty" else 0
        self._away = self._away or self._empty >= 2
        if total is not None and state != "empty":
            if total == self._last and (total != self._steady or self._away):
                if (self._steady is not None and total != self._steady
                        and state not in IN_PLAY and (self._steady == 0 or self._away)):
                    self.rebuys += 1
                    self.added += total - self._steady
                    self.settled = None if self.start is None else total
                self._steady, self._away = total, False
            self._last = total
        if self.start is None:
            if dealt and self._steady is not None:
                self.start = self.settled = self._steady
        elif hand != self._hand or state in ("folded", "waiting"):
            self.settled = self._steady
        self._hand = hand

    def net(self):
        """Chips won (negative when lost), or None before you were dealt in."""
        return None if self.start is None else self.settled - self.start - self.added


class AAGrades:
    """Grades of your decisions in one observation; fed every frame."""

    def __init__(self, advice, clock=time.time):
        self._advice = advice
        self._clock = clock
        self.reset()

    def reset(self):
        self._rows, self._dealt = [], set()
        self._hand, self._spots, self._done = None, {}, set()
        self._decisions = self._advised = 0
        self._chips = HeroChips()

    def __call__(self, payload, frame):
        return self.observe_fields(frame_summary(payload), frame)

    def observe_fields(self, fields, frame):
        history = fields.get("actions_v1")
        if history:
            hand = history["hand_id"]
            if hand != self._hand:
                self._hand, self._spots, self._done = hand, {}, set()
            if len([card for card in fields.get("hero") or () if card]) == 2:
                self._dealt.add(hand)
            self._chips.observe(fields, hand, hand in self._dealt)
            if (fields.get("hero_controls") or {}).get("visible"):
                self._remember(fields, history)
            hand_id, outcomes = self._advice.settled()
            if hand_id == hand:
                self._grade(history, outcomes)
        return self.report()

    def report(self):
        net = self._chips.net()
        return {"schema_version": 1, "hands": len(self._dealt),
                "decisions": self._decisions, "advised": self._advised,
                "graded": len(self._rows),
                "best": sum(row["grade"] == "best" for row in self._rows),
                "grades": {grade: sum(row["grade"] == grade for row in self._rows)
                           for grade in GRADES},
                "preflop_lost_big_blinds": round(sum(
                    row.get("lost_big_blinds", 0.0) for row in self._rows), 2),
                "net_chips": None if net is None else str(net),
                "net_big_blinds": (None if net is None
                                   else round(float(net / BIG_BLIND), 1)),
                "rebuys": self._chips.rebuys,
                "last": self._rows[-1] if self._rows else None,
                "rows": self._rows[:-SHOWN - 1:-1], "acts_on_client": False}

    # -- decisions -------------------------------------------------------------

    def _remember(self, fields, history):
        """What the table showed at this decision (the advice's key)."""
        actions = history["actions"]
        street = fields.get("street")
        controls = fields.get("hero_controls") or {}
        stacks = fields.get("stacks") or {}
        seen = {
            "street": street,
            "hero": list(fields.get("hero") or [None, None]),
            "board": list(fields.get("board") or [None] * 5),
            "pot": fields.get("pot"),
            "to_call": "0" if controls.get("button") == "check"
            else controls.get("call_amount"),
            "stack": stacks.get(str(HERO), stacks.get(HERO)),
            "dealer": history.get("dealer"),
            "dealt": sorted(_slot(seat) for seat, state in (
                fields.get("participants") or {}).items()
                if state in DEALT and _slot(seat) is not None),
            "facing": _facing(actions, street)}
        spot = self._spots.setdefault((len(actions), street), seen)
        for name, value in seen.items():     # a read that came in late
            if spot[name] is None or (isinstance(value, list) and None in spot[name]
                                      and None not in value):
                spot[name] = value

    def _grade(self, history, outcomes):
        for index, action in enumerate(history["actions"]):
            frame, street, slot, kind, amount, source = action[:6]
            if _slot(slot) != HERO or frame in self._done or source == "pending":
                continue
            keys = [key for key in outcomes if key[1] == street and key[0] <= index]
            if not keys:
                self._done.add(frame)            # no advice for this decision
                self._decisions += 1
                continue
            key = max(keys)
            outcome = outcomes[key]
            if outcome is None:                  # the solve is still running
                continue
            self._done.add(frame)
            self._decisions += 1
            self._advised += outcome.get("status") == "ready"
            if outcome.get("status") == "ready" and key in self._spots:
                row = self._row(self._spots[key], outcome, kind, amount)
                if row is not None:
                    self._rows.append(row)

    def _row(self, spot, outcome, kind, amount):
        stack = _decimal(spot["stack"])
        to_call = _decimal(outcome.get("to_call"))
        if to_call is None:
            to_call = _decimal(spot["to_call"])
        if outcome.get("options"):
            graded = preflop_grade(kind, outcome["options"], to_call, stack)
            shown = {"options": outcome["options"]}
        elif outcome.get("kind") == "multiway":
            graded = multiway_grade(kind, outcome, to_call, stack)
            shown = {"kind": "multiway", "advice": outcome.get("advice") or [],
                     "cuts": outcome.get("cuts") or {}}
        else:
            graded = solver_grade(kind, outcome.get("advice") or [], to_call, stack)
            shown = {"advice": outcome.get("advice") or []}
        if graded is None:
            return None
        return {"at": round(self._clock(), 1), "hand_id": self._hand, **spot,
                "to_call": None if to_call is None else str(to_call),
                "action": {"kind": kind, "amount": amount}, **shown, **graded}


__all__ = ["AAGrades", "HeroChips", "multiway_grade", "preflop_grade",
           "solver_grade"]
