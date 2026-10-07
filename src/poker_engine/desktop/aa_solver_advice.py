"""Heads-up turn and river advice from the solver, worked out in the background.

When it is your turn (your action button is on screen) on the turn or the
river, with one opponent left and both your cards read, the hand so far is
replayed on the AA table (``aa_solver_input``) and the scoreboard's solver
strategy (``solver_turn`` in human mode) works out what to do with your hand:
how often to check, call, fold or bet, and how much. The solve runs on a
background thread, so recognition never waits for it. Every frame reports
where the current decision stands:

- ``idle``: not a decision the solver covers (the reason says why);
- ``computing``: being worked out;
- ``ready``: the actions with their frequencies;
- ``abstain``: this hand cannot be used (the reason says why).

The pot the solver sees is corrected to the pot on screen: the AA rules do
not post extra chips such as a mushroom or bomb pot. The advice comes from a
model of how people play and is for study only; nothing here acts on the
client.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
import time

from poker_engine.scoreboard.solver_bot import Fallback, SolverBot
from poker_engine.solver.texassolver import amount_of

from .aa_session import frame_summary
from .aa_solver_input import hand_facts, solver_observation

HERO = 4                        # your seat: bottom centre
STREETS = ("turn", "river")     # the flop takes about a minute: too slow live
THREADS = 4                     # solver threads (the scoreboard uses one)
MAX_ROWS = 6000                 # frames of one hand kept (10 minutes at 10 fps)
RETRY = 3                       # frames to wait for the action before your turn
SALT = "live-advice"
BASIS = ("heads-up TexasSolver strategy; ranges from a population model of "
         "public hand histories; for study only")


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


class AASolverAdvice:
    """Per-frame advice status; the solver runs on one background thread."""

    def __init__(self, bot=None, executor=None):
        self._bot = bot
        self._executor = executor
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
            self._bot = SolverBot("solver_turn", human=True, threads=THREADS)
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1,
                                                thread_name_prefix="solver-advice")
        return self._executor.submit(self._solve, observation, time.monotonic())

    def _solve(self, observation, started):
        try:
            strategy = self._bot.solved_strategy(observation, SALT)
        except Fallback as reason:
            return {"status": "abstain", "reason": str(reason)}
        return {"status": "ready", "advice": advice_rows(strategy, observation),
                "pot": observation["pot"], "to_call": observation["to_call"],
                "pot_offset": observation.get("pot_offset"),
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
                                "advice", "pot", "to_call", "pot_offset", "seconds")
                                if name in job})

    def _report(self, status, reason, **extra):
        return {"schema_version": 1, "status": status, "reason": reason,
                "hand_id": self._hand_id, **extra, "basis": BASIS,
                "advice_emitted": status == "ready", "acts_on_client": False}


__all__ = ["AASolverAdvice", "advice_rows"]
