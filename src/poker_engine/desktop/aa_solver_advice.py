"""Advice for your preflop, heads-up turn and river, and multiway decisions.

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

- After the flop with more than one opponent there is no solver, and on the
  heads-up flop a solve takes about a minute. Your share of the pot against
  every opponent's range (read from their actions with the same population
  model, ``scoreboard.ranges``) is worked out in the background, and the
  scoreboard's ``range_multiway`` rule turns it into an action against the
  price (``multiway_bot.choose``, with its heads-up cuts against one
  opponent): bet, raise, call, check or fold, with the shares where the
  action changes (``cuts``). The report's ``heads_up`` says which.

An action the history missed but the table shows (``aa_solver_input``) is
filled in; the report's ``inferred_actions`` counts them. A decision is the
actions read so far, the street and what your button shows
(``decision_key``): when your action and a re-raise are both missed, the
new price is still a new decision. Every frame reports where the current
decision stands:

- ``idle``: not a decision the solver covers (the reason says why);
- ``computing``: being worked out;
- ``ready``: the actions with their frequencies;
- ``abstain``: this hand cannot be used (the reason says why).

The pot the solver sees is corrected to the pot on screen: the AA rules do
not post extra chips such as a mushroom or bomb pot (preflop, extra chips on
screen are added to the pot the policy sees). The mushroom pool read at the
top left of the table (``aa_mushroom``) goes to the preflop policy too, in a
hand of four or more players: the small blind takes it with the pot, so the
policy counts it as extra pot when you are the small blind (the report's
``mushroom_pool`` is then the amount counted). Each opponent's entry and
raise rates over the hands seen so far (``aa_reads``) go to the preflop
policy too, which widens or narrows that seat's expected range by them, and
to the range reading after the flop (``ranges.opponent_ranges``: the same
widening, and bets from a seat that raises far more than the model keep
some hands the model would not bet with). The report's ``reads_hands`` is
how many hands they come from; every report's ``seat_reads`` has each
seat's numbers and word for the window. A bomb pot (暴击) is replayed as
one (``aa_solver_input.bomb_post``) and advised like any other hand after
the flop; the report's ``bomb_pot`` is each player's post. The advice
comes from a model of how people play and is for study only; nothing here
acts on the client.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
import time

from poker_engine.core.enums import Position
from poker_engine.scoreboard.bots import position
from poker_engine.scoreboard.mushroom import MIN_PLAYERS
from poker_engine.scoreboard.multiway_bot import choose as multiway_choice
from poker_engine.scoreboard.multiway_bot import cuts as multiway_cuts
from poker_engine.scoreboard.multiway_bot import street_params
from poker_engine.scoreboard.population import PopulationBot
from poker_engine.scoreboard.preflop_policy import AAPreflopPolicy
from poker_engine.scoreboard.ranges import opponent_ranges, ranges_equity
from poker_engine.scoreboard.solver_bot import Fallback, SolverBot
from poker_engine.scoreboard.strength import range_equity
from poker_engine.solver.texassolver import amount_of

from .aa_reads import AAReads
from .aa_session import frame_summary
from .aa_solver_input import hand_facts, solver_observation

HERO = 4                        # your seat: bottom centre
SOLVED = ("turn", "river")      # heads-up: a flop solve takes about a minute
THREADS = 4                     # solver threads (the scoreboard uses one)
MAX_ROWS = 6000                 # frames of one hand kept (10 minutes at 10 fps)
RETRY = 3                       # frames to wait for the action before your turn
SALT = "live-advice"
BASIS = ("heads-up TexasSolver strategy; ranges from a population model of "
         "public hand histories fitted to AA players' preflop play; for study only")
PREFLOP_BASIS = ("expected chips of each option against AA players' preflop "
                 "frequencies (read from recordings) and a heads-up equity table; "
                 "for study only")
MULTIWAY_BASIS = ("equity against every opponent's range (a population model fitted to "
                  "AA players' preflop play) against the price, the scoreboard's "
                  "range_multiway rule; there is no multiway solver; for study only")
HEADS_UP_BASIS = ("equity against the opponent's range (a population model fitted to "
                  "AA players' preflop play) against the price, the scoreboard's "
                  "range_multiway rule with its heads-up cuts; a flop solve takes "
                  "about a minute; for study only")


def _read_hands(observation):
    """How many finished hands the reads in ``observation`` come from."""
    return max((read["hands"] for read in (observation.get("reads") or {}).values()),
               default=0)


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def decision_key(fields, history):
    """(actions read, street, your button): one of your decisions."""
    controls = fields.get("hero_controls") or {}
    return (len(history["actions"]), fields.get("street"),
            f"{controls.get('button')}:{controls.get('call_amount')}")


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


def multiway_row(action, observation):
    """A ``range_multiway`` action id as an advice row, like the solver's."""
    to_call = Decimal(observation["to_call"] or 0)
    if action == "fold":
        return {"action": "fold", "frequency": 1.0}
    if action == "check_call":
        return {"action": "call" if to_call > 0 else "check", "frequency": 1.0}
    mine = Decimal(observation["bets"][str(observation["observing_seat"])])
    to = Decimal(action.partition(":")[2]).quantize(Decimal(1))
    return {"action": "raise" if to_call > 0 else "bet", "frequency": 1.0,
            "chips": str(to - mine), "to": str(to)}


def range_report(observation, weights):
    """Your share of the pot against the opponent's range, and how many of
    its hands your cards and the board leave; None when it leaves none."""
    value, hands = range_equity(observation["own_hole"], observation["board"], weights)
    return None if value is None else {"value": round(value, 3), "hands": hands}


class AASolverAdvice:
    """Per-frame advice status; the solver runs on one background thread."""

    def __init__(self, bot=None, executor=None, preflop=None, model=None):
        self._bot = bot
        self._executor = executor
        self._preflop = preflop
        self._model = model
        self.reset()

    def reset(self):
        """Forget the hand being followed and the reads: a new observation
        numbers its frames, and so its hands, from 0 again, and may be
        another table."""
        self._rows, self._hand_id, self._jobs = [], None, {}
        self.reads = AAReads()

    def __call__(self, payload, frame):
        return self.observe(payload, frame)

    def settled(self):
        """This hand's id and its decisions so far: {(decision, street):
        outcome}, None while still being worked out. A solve that finishes
        after you acted is here too, for grading what you did."""
        return self._hand_id, {key: self._settle(key) for key in list(self._jobs)}

    def observe(self, payload, frame):
        return self.observe_fields(frame_summary(payload), frame)

    def observe_fields(self, fields, frame):
        """The same from a frame's summary (``frame_summary``), as the
        measurement log keeps it: advice can be replayed from a log."""
        history = fields.get("actions_v1")
        if not history:
            return self._report("idle", "no_hand")
        if history["hand_id"] != self._hand_id:
            self.reads.add_hand(self._rows)
            self._rows, self._hand_id, self._jobs = [], history["hand_id"], {}
        self._rows.append({"processed": frame, "fields": fields})
        del self._rows[:-MAX_ROWS]
        if not (fields.get("hero_controls") or {}).get("visible"):
            return self._report("idle", "not_your_turn")
        street = fields.get("street")
        if street not in ("preflop", "flop", *SOLVED):
            return self._report("idle", "street_not_covered", street=street)
        cards = [card for card in fields.get("hero") or () if card]
        if len(cards) != 2:
            return self._report("idle", "your_cards_not_read", street=street)
        key = decision_key(fields, history)
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
        if len(live) > 2 or observation["street"] not in SOLVED:
            return self._submit(self._multiway, self._with_reads(observation), fields,
                                time.monotonic())
        if any(seat in observation["stacks_unknown"] for seat in live):
            return {"status": "abstain", "reason": "stack_unknown"}
        pot = _decimal(fields.get("pot"))
        if pot is not None:
            observation["pot_offset"] = str(pot - Decimal(observation["pot"]))
        if self._bot is None:
            self._bot = SolverBot("solver_turn", human=True, threads=THREADS,
                                  base=self._preflop_policy())
        return self._submit(self._solve, observation, time.monotonic())

    def _submit(self, function, *args):
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1,
                                                thread_name_prefix="solver-advice")
        return self._executor.submit(function, *args)

    def _with_reads(self, observation):
        """``observation`` with each opponent's reads so far, when there are any."""
        reads = self.reads.snapshot()
        return {**observation, "reads": reads} if reads else observation

    def _ranges(self, observation):
        """Your share of the pot against every opponent's range, or None."""
        if self._model is None:
            self._model = PopulationBot(adjusted=self._preflop_policy().adjusted)
        ranges = opponent_ranges(observation, self._model)
        value, counts = ranges_equity(observation["own_hole"], observation["board"],
                                      ranges)
        if value is None:
            return None
        return {"value": round(value, 3), "opponents": len(counts),
                "hands": sum(counts.values()) if len(counts) == 1 else None,
                "hands_each": {str(seat): count for seat, count in counts.items()}}

    def _multiway(self, observation, fields, started):
        """The ``range_multiway`` action for your share of the pot against the
        opponents' ranges; the share alone when your stack is not read."""
        heads_up = len([seat for seat in observation["occupied_seats"]
                        if seat not in observation["folded"]]) == 2
        idle = "heads_up_flop" if heads_up else "more_than_one_opponent"
        edge = self._ranges(observation)
        if edge is None:
            return {"status": "idle", "reason": idle}
        if HERO in observation["stacks_unknown"]:
            return {"status": "idle", "reason": idle, "range_equity": edge}
        pot = _decimal(fields.get("pot"))
        offset = None
        if pot is not None and pot > Decimal(observation["pot"]):
            offset = pot - Decimal(observation["pot"])
            observation = {**observation, "pot": str(pot)}
        action = multiway_choice(observation, edge["value"])
        line = multiway_cuts(observation, street_params(observation))
        return {"status": "ready", "kind": "multiway", "heads_up": heads_up,
                "advice": [multiway_row(action, observation)],
                "cuts": {name: round(value, 3) for name, value in line.items()},
                "range_equity": edge, "pot": observation["pot"],
                "to_call": observation["to_call"],
                "pot_offset": None if offset is None else str(offset),
                "reads_hands": _read_hands(observation),
                "stacks_assumed": observation["stacks_unknown"],
                "inferred_actions": observation.get("inferred_actions", 0),
                "bomb_pot": observation.get("bomb_pot"),
                "basis": HEADS_UP_BASIS if heads_up else MULTIWAY_BASIS,
                "seconds": round(time.monotonic() - started, 2)}

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
        pool = _decimal(fields.get("mushroom_pool"))
        counted = None
        if (pool is not None and pool > 0
                and len(observation["occupied_seats"]) >= MIN_PLAYERS):
            observation = {**observation, "mushroom_pool": str(pool)}
            if position(observation) == Position.SB:
                counted = str(pool)
        observation = self._with_reads(observation)
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
                "mushroom_pool": counted,
                "reads_hands": _read_hands(observation),
                "stacks_assumed": observation["stacks_unknown"],
                "inferred_actions": observation.get("inferred_actions", 0),
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
                "inferred_actions": observation.get("inferred_actions", 0),
                "bomb_pot": observation.get("bomb_pot"),
                "seconds": round(time.monotonic() - started, 2)}

    def _settle(self, key):
        """The decision's outcome, or None while the solve is running."""
        job = self._jobs[key]
        if isinstance(job, Future):
            if not job.done():
                return None
            try:
                job = job.result()
            except Exception:              # the solver process failed
                job = {"status": "abstain", "reason": "solver_error"}
            self._jobs[key] = job
        return job

    def _outcome(self, key, street):
        job = self._settle(key)
        if job is None:
            return self._report("computing", None, street=street, decision=key[0])
        return self._report(job["status"], job.get("reason"), street=street,
                            decision=key[0], **{name: job[name] for name in (
                                "kind", "heads_up", "advice", "options", "cuts", "pot",
                                "to_call", "pot_offset", "mushroom_pool", "reads_hands",
                                "stacks_assumed", "inferred_actions", "range_equity",
                                "bomb_pot", "seconds", "basis")
                                if name in job})

    def _report(self, status, reason, **extra):
        return {"schema_version": 1, "status": status, "reason": reason,
                "hand_id": self._hand_id, "basis": BASIS, **extra,
                "seat_reads": self.reads.labels(),
                "advice_emitted": status == "ready", "acts_on_client": False}


__all__ = ["AASolverAdvice", "advice_rows", "decision_key", "multiway_row",
           "range_report"]
