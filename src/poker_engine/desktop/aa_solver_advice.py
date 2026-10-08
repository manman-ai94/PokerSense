"""Advice for your preflop and heads-up turn and river decisions.

When it is your turn (your action button is on screen) and both your cards
are read, the hand so far is replayed on the AA table (``aa_solver_input``).

- Before the flop the AA preflop policy (``aa_preflop``) works out what
  folding, calling and raising are each worth in chips against the AA
  players' ranges, and advises the most valuable; the values are the reasons
  shown. It takes milliseconds and runs at once.
- On the turn or the river, with one opponent left, the scoreboard's solver
  strategy (``solver_turn`` in human mode, on ``aa_preflop``: everyone's
  earlier play is read as AA players play) works out how often to check,
  call, fold or bet, and how much, and your share of the pot against the
  opponent's range there (``range_equity``, exact over the river cards). The
  solve runs on a background thread, so recognition never waits for it.

The flop is not covered: a flop solve takes about a minute. Every frame
reports where the current decision stands:

- ``idle``: not a decision the solver covers (the reason says why);
- ``computing``: being worked out;
- ``ready``: the actions with their frequencies;
- ``abstain``: this hand cannot be used (the reason says why).

The pot the solver sees is corrected to the pot on screen: the AA rules do
not post extra chips such as a mushroom or bomb pot (preflop, extra chips on
screen are added to the pot the policy sees). The advice comes from a model
of how people play and is for study only; nothing here acts on the client.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
import time

from poker_engine.scoreboard.preflop_policy import AAPreflopPolicy
from poker_engine.scoreboard.solver_bot import Fallback, SolverBot
from poker_engine.scoreboard.strength import range_equity
from poker_engine.solver.texassolver import amount_of

from .aa_session import frame_summary
from .aa_solver_input import hand_facts, solver_observation

HERO = 4                        # your seat: bottom centre
STREETS = ("preflop", "turn", "river")   # a flop solve takes about a minute
THREADS = 4                     # solver threads (the scoreboard uses one)
MAX_ROWS = 6000                 # frames of one hand kept (10 minutes at 10 fps)
RETRY = 3                       # frames to wait for the action before your turn
SALT = "live-advice"
BASIS = ("heads-up TexasSolver strategy; ranges from a population model of "
         "public hand histories fitted to AA players' preflop play; for study only")
PREFLOP_BASIS = ("expected chips of each option against AA players' preflop "
                 "frequencies (read from recordings) and a heads-up equity table; "
                 "for study only")


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def advice_rows(strategy, observation):
    """The solver's actions for your hand, most frequent first: check, call,
    fold, or a bet or raise with the chips it adds and what it makes your bet."""
    mine = Decimal(observation["bets"][str(observation["observing_seat"])])
    rows = []
    for label, share in sorted(strategy.items(), key=lambda item: (-item[1], item[0])):
        row = {"action": label.split()[0].lower(), "frequency": round(share, 3)}
        if row["action"] in ("bet", "raise"):
            chips = Decimal(str(amount_of(label))).quantize(Decimal(1))
            row.update(chips=str(chips), to=str(mine + chips))
        rows.append(row)
    return rows


def range_report(observation, weights):
    """Your share of the pot against the opponent's range, and how many of
    its hands your cards and the board leave; None when it leaves none."""
    value, hands = range_equity(observation["own_hole"], observation["board"], weights)
    return None if value is None else {"value": round(value, 3), "hands": hands}


class AASolverAdvice:
    """Per-frame advice status; the solver runs on one background thread."""

    def __init__(self, bot=None, executor=None, preflop=None):
        self._bot = bot
        self._executor = executor
        self._preflop = preflop
        self._rows, self._hand_id, self._jobs = [], None, {}

    def __call__(self, payload, frame):
        return self.observe(payload, frame)

    def observe(self, payload, frame):
        return self.observe_fields(frame_summary(payload), frame)

    def observe_fields(self, fields, frame):
        """The same from a frame's summary (``frame_summary``), as the
        measurement log keeps it: advice can be replayed from a log."""
        history = fields.get("actions_v1")
        if not history:
            return self._report("idle", "no_hand")
        if history["hand_id"] != self._hand_id:
            self._rows, self._hand_id, self._jobs = [], history["hand_id"], {}
        self._rows.append({"processed": frame, "fields": fields})
        del self._rows[:-MAX_ROWS]
        if not (fields.get("hero_controls") or {}).get("visible"):
            return self._report("idle", "not_your_turn")
        street = fields.get("street")
        if street not in STREETS:
            return self._report("idle", "street_not_covered", street=street)
        cards = [card for card in fields.get("hero") or () if card]
        if len(cards) != 2:
            return self._report("idle", "your_cards_not_read", street=street)
        key = (len(history["actions"]), street)
        job = self._jobs.get(key)
        retry = isinstance(job, dict) and frame >= job.get("retry_at", frame + 1)
        if job is None or retry:
            self._jobs[key] = self._start(fields, cards, frame)
        return self._outcome(key, street)

    # -- jobs -------------------------------------------------------------------

    def _start(self, fields, cards, frame):
        """A Future for the solve, or a finished outcome when there is none."""
        observation, reason = solver_observation(hand_facts(self._rows), HERO, cards)
        if reason == "not_your_turn_yet":
            # Your buttons show up a moment before the action before them is
            # read: look again shortly.
            return {"status": "idle", "reason": "waiting_for_last_action",
                    "retry_at": frame + RETRY}
        if observation is None:
            return {"status": "abstain", "reason": reason}
        if observation["street"] != fields.get("street"):
            return {"status": "abstain", "reason": "street_mismatch"}
        if observation["street"] == "preflop":
            return self._preflop_advice(observation, fields)
        live = [seat for seat in observation["occupied_seats"]
                if seat not in observation["folded"]]
        if len(live) != 2:
            return {"status": "idle", "reason": "more_than_one_opponent"}
        if any(seat in observation["stacks_unknown"] for seat in live):
            return {"status": "abstain", "reason": "stack_unknown"}
        pot = _decimal(fields.get("pot"))
        if pot is not None:
            observation["pot_offset"] = str(pot - Decimal(observation["pot"]))
        if self._bot is None:
            self._bot = SolverBot("solver_turn", human=True, threads=THREADS,
                                  base=self._preflop_policy())
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1,
                                                thread_name_prefix="solver-advice")
        return self._executor.submit(self._solve, observation, time.monotonic())

    def _preflop_policy(self):
        if self._preflop is None:
            self._preflop = AAPreflopPolicy()
        return self._preflop

    def _preflop_advice(self, observation, fields):
        """The most valuable option and every option's value, at once."""
        if HERO in observation["stacks_unknown"]:
            return {"status": "abstain", "reason": "stack_unknown"}
        started = time.monotonic()
        pot = _decimal(fields.get("pot"))
        offset = None
        if pot is not None and pot > Decimal(observation["pot"]):
            offset = pot - Decimal(observation["pot"])
            observation = {**observation, "pot": str(pot)}
        choice = self._preflop_policy().choose(observation)
        big_blind = Decimal(observation["rules"]["big_blind"])
        mine = Decimal(observation["bets"][str(HERO)])
        price = Decimal(observation["to_call"] or 0)
        options = []
        for name, value in sorted(choice["values"].items(),
                                  key=lambda item: (-item[1], item[0])):
            row = {"action": name, "chips": round(value, 1),
                   "big_blinds": round(value / float(big_blind), 2)}
            if name == "raise":
                to = Decimal(str(choice["raise_to"])).quantize(Decimal(1))
                row.update(to=str(to), chips_in=str(to - mine))
            elif name == "call":
                row.update(chips_in=str(price))
            options.append(row)
        best = options[0]
        advice = [{"action": best["action"], "frequency": 1.0,
                   **({"chips": best["chips_in"], "to": best["to"]}
                      if best["action"] == "raise" else {})}]
        return {"status": "ready", "advice": advice, "options": options,
                "pot": observation["pot"], "to_call": observation["to_call"],
                "pot_offset": None if offset is None else str(offset),
                "stacks_assumed": observation["stacks_unknown"],
                "basis": PREFLOP_BASIS,
                "seconds": round(time.monotonic() - started, 3)}

    def _solve(self, observation, started):
        try:
            strategy, villain = self._bot.solved_spot(observation, SALT)
        except Fallback as reason:
            return {"status": "abstain", "reason": str(reason)}
        try:
            edge = range_report(observation, villain)
        except (KeyError, ValueError):     # never lose the advice over it
            edge = None
        return {"status": "ready", "advice": advice_rows(strategy, observation),
                "pot": observation["pot"], "to_call": observation["to_call"],
                "pot_offset": observation.get("pot_offset"),
                "range_equity": edge,
                "seconds": round(time.monotonic() - started, 2)}

    def _outcome(self, key, street):
        job = self._jobs[key]
        if isinstance(job, Future):
            if not job.done():
                return self._report("computing", None, street=street, decision=key[0])
            try:
                job = job.result()
            except Exception:              # the solver process failed
                job = {"status": "abstain", "reason": "solver_error"}
            self._jobs[key] = job
        return self._report(job["status"], job.get("reason"), street=street,
                            decision=key[0], **{name: job[name] for name in (
                                "advice", "options", "pot", "to_call", "pot_offset",
                                "stacks_assumed", "range_equity", "seconds", "basis")
                                if name in job})

    def _report(self, status, reason, **extra):
        return {"schema_version": 1, "status": status, "reason": reason,
                "hand_id": self._hand_id, "basis": BASIS, **extra,
                "advice_emitted": status == "ready", "acts_on_client": False}


__all__ = ["AASolverAdvice", "advice_rows", "range_report"]
