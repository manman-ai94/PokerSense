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
  solve runs on a background thread, so recognition never waits for it. It
  takes one to several seconds (on 10/08 you acted before 6 solves were
  done, one river solve ran past 13 seconds), so the range rule below works
  out an action next to it, in a fraction of a second: until the solve is
  done that is the advice, marked ``provisional``. When the solve cannot
  answer (the street began with more than two players, your hand is not in
  the range your play implies, a bet the tree has no branch for), the range
  rule's action stays the advice, with ``solver_gave_up`` saying why.

- After the flop with more than one opponent there is no solver, and on the
  heads-up flop a solve takes about a minute. Your share of the pot against
  every opponent's range (read from their actions with the same population
  model, ``scoreboard.ranges``) is worked out in the background, and the
  scoreboard's ``range_multiway`` rule turns it into an action against the
  price (``multiway_bot.choose``, with its heads-up cuts against one
  opponent): bet, raise, call, check or fold, with the shares where the
  action changes (``cuts``). The report's ``heads_up`` says which.

  Reading the ranges is plain Python and takes seconds when many players
  are in (a bomb pot, 暴击), and would hold the interpreter lock 5 ms at
  a time, slowing recognition many-fold (on 2026-10-08 in a 5-handed bomb
  pot the window lost its picture for over 2 seconds). Starting a
  background thread makes the interpreter switch threads every
  ``SWITCH_SECONDS`` instead. The solve, the range rule next to it and the
  rough rule can run at once: on 10/07 at real pace recognition took about
  a second a frame for 8 frames while they did.

An action the history missed but the table shows (``aa_solver_input``) is
filled in; the report's ``inferred_actions`` counts them. A decision is the
actions read so far, the street, what your button shows and how many of the
actions still wait for their chips (``decision_key``): when your action and
a re-raise are both missed, the new price is still a new decision, and a
bet whose chips are read once the pot shows again (on 10/08 the pot was
unread for over 2 s twice right as your turn came) is worked out again
instead of staying ``raise_without_amount``. Every frame reports where the
current decision stands:

- ``idle``: not a decision the solver covers (the reason says why);
- ``computing``: being worked out;
- ``ready``: the actions with their frequencies;
- ``abstain``: this hand cannot be used (the reason says why).

Your turn is never left without an action while your cards and the board
are read: when none has come ``ROUGH_SECONDS`` into your turn (or
``ROUGH_FRAMES`` frames, whichever is first; the hand cannot be replayed on
the table, say joined midway, an action missed or four players; the history
still waits for an action; or the work takes longer), a rough rule answers
from the screen alone (``kind`` ``rough``). It runs on a worker of its own:
in the solve's two it waited behind a heads-up solve and its range rule,
and the clock counts a stall the frames do not (10/08 and 10/07 measured at
real pace: four of your turns, most over a second long, got nothing). The
frame that asks waits up to ``ROUGH_WAIT`` for it (it takes under 0.1 s):
two of those turns ended on the frame after a stall that made it due. Each
opponent still in holds the top ``CALLER_SHARE`` of starting hands, the one
with the most chips in on this street the top ``BETTOR_SHARE`` when that is
a bet or raise to you; your share of the pot
against them, against the price on your button, gives check when it is
free, call when the share is at least what the call needs (``required``),
fold otherwise. Before the flop only ``PREFLOP_REALIZE`` of the share counts
(the betting still to come; ``aa_preflop`` counts out of position the same),
unless the call puts you all in. ``rough_for`` is why the other advice is not there; it
replaces the rough one as soon as it comes. (On 10/08 the window left at
least one of your decisions without advice in 50 of the 71 hands you
played.)

The pot the solver sees is corrected to the pot on screen: the AA rules do
not post extra chips such as a mushroom or bomb pot (preflop, extra chips on
screen are added to the pot the policy sees). The mushroom pool read at the
top left of the table (``aa_mushroom``) goes to the preflop policy too, in a
hand of four or more players: the small blind takes it with the pot, so the
policy counts it as extra pot when you are the small blind (the report's
``mushroom_pool`` is then the amount counted). Each opponent's entry and
raise rates over the hands seen so far (``aa_reads``) go to the preflop
policy too, which widens or narrows that seat's expected range by them,
and to the range reading after the flop (``ranges.opponent_ranges``: the
same widening, and bets from a seat that bets or raises clearly more often
than the model after the flop keep some hands the model would not bet
with). That keys on the seat's postflop bets and raises, not its preflop
raise rate: read that way, a tight-aggressive player who bets honestly was
taken as bluffing (on the scoreboard, 2026-10-09: -406 bb/100 in bomb pots
against such a table, with the reads against without them, before it keyed
on them). The report's ``reads_hands`` is how many hands they come from;
every report's ``seat_reads`` has each seat's numbers and word for the
window. A bomb pot (暴击) is replayed as
one (``aa_solver_input.bomb_post``) and advised like any other hand after
the flop; the report's ``bomb_pot`` is each player's post. The advice
comes from a model of how people play and is for study only; nothing here
acts on the client.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from itertools import combinations
import json
import sys
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
from poker_engine.scoreboard.strength import DECK, combo_percentile, range_equity
from poker_engine.solver.texassolver import amount_of, combo_key

from .aa_reads import AAReads
from .aa_session import frame_summary
from .aa_solver_input import RULES_PATH, hand_facts, solver_observation

HERO = 4                        # your seat: bottom centre
SOLVED = ("turn", "river")      # heads-up: a flop solve takes about a minute
THREADS = 4                     # solver threads (the scoreboard uses one)
MAX_ROWS = 6000                 # frames of one hand kept (10 minutes at 10 fps)
RETRY = 3                       # frames to wait for the action before your turn
SWITCH_SECONDS = 0.0001         # thread switch while a background job runs
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
PROVISIONAL_BASIS = ("equity against the opponent's range (a population model fitted "
                     "to AA players' preflop play) against the price, the scoreboard's "
                     "range_multiway rule with its heads-up cuts, until the heads-up "
                     "solve is done; for study only")
WORKERS = 2                     # the solve and the range rule next to it
ROUGH_SECONDS = 0.6             # of your turn without advice
ROUGH_FRAMES = 10               # or frames, where nothing gives the time
ROUGH_WAIT = 0.15               # the frame that asks waits this long for it
CALLER_SHARE = 0.4              # rough rule: each opponent's top 40% of hands
BETTOR_SHARE = 0.2              # and the top 20% for the one who bet or raised to you
PREFLOP_REALIZE = 0.8           # before the flop: aa_preflop's out-of-position realize
ROUGH_TRIALS = 1500              # under 0.1 s with seven opponents
ROUGH_BASIS = ("your share of the pot against fixed ranges (each opponent's top 40% of "
               "starting hands, the top 20% for the one who bet or raised to you) "
               "against the price on your button, from the screen alone: a rough rule "
               "for when the hand cannot be worked out; for study only")
BOARD_CARDS = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
IN_HAND = ("active", "all_in")


def _switch_quickly():
    """The frame loop gets the interpreter lock back within ``SWITCH_SECONDS``
    instead of 5 ms. On a frame-like load next to range jobs from the 10/07
    log (cloud, 2026-10-09; median frame against the frame alone): 5 ms, two
    jobs: 49x slower; 0.5 ms: 3x with one job, 8x with two, 11x with three;
    0.1 ms: 2x, 3x, 5x; the jobs themselves 4-13% slower than at 0.5 ms
    (0.05 ms gains nothing more)."""
    sys.setswitchinterval(min(sys.getswitchinterval(), SWITCH_SECONDS))


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
    """(actions read, street, your button, actions without chips yet): one of
    your decisions."""
    controls = fields.get("hero_controls") or {}
    waiting = sum(action[4] is None for action in history["actions"])
    return (len(history["actions"]), fields.get("street"),
            f"{controls.get('button')}:{controls.get('call_amount')}", waiting)


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


@lru_cache(maxsize=None)
def top_range(share):
    """{combo key: 1.0} for the top ``share`` of starting hands."""
    return {combo_key(pair): 1.0 for pair in combinations(DECK, 2)
            if combo_percentile(pair) <= share}


@lru_cache(maxsize=1)
def open_level():
    """The most a player puts in before the flop without raising: the big
    blind, or the straddle where the AA rules have one."""
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return max(Decimal(rules["big_blind"]), Decimal(rules.get("straddle_amount") or 0))


def rough_advice(fields, cards, street):
    """The rough rule's action for your turn, from the screen alone: your
    share of the pot against fixed ranges, against the price on your button.
    None when the board, the players still in or the price are not read."""
    board = [card for card in fields.get("board") or () if card]
    if street not in BOARD_CARDS or len(board) != BOARD_CARDS[street]:
        return None
    seats = fields.get("participants") or {}
    opponents = sorted(seat for seat, state in seats.items()
                       if seat != str(HERO) and state in IN_HAND)
    pot = _decimal(fields.get("pot"))
    if not opponents or pot is None:
        return None
    wagers = {seat: _decimal(value) or Decimal(0)
              for seat, value in (fields.get("street_wagers") or {}).items()}
    mine = wagers.get(str(HERO), Decimal(0))
    top = max(wagers.get(seat, Decimal(0)) for seat in opponents)
    controls = fields.get("hero_controls") or {}
    if controls.get("button") == "check":
        to_call = Decimal(0)
    else:
        # The button's price, else what the most chips in on this street need.
        to_call = _decimal(controls.get("call_amount"))
        if to_call is None and top > mine:
            to_call = top - mine
        if to_call is None:
            return None
    stack = _decimal((fields.get("stacks") or {}).get(str(HERO)))
    all_in = stack is not None and 0 < stack <= to_call
    if all_in:
        to_call = stack
    raised = to_call > 0 and top > mine and (street != "preflop" or top > open_level())
    ranges = {seat: top_range(BETTOR_SHARE if raised and wagers.get(seat) == top
                              else CALLER_SHARE) for seat in opponents}
    value, counts = ranges_equity(cards, board, ranges, trials=ROUGH_TRIALS)
    if value is None:
        return None
    realize = PREFLOP_REALIZE if street == "preflop" and not all_in else 1.0
    value *= realize
    required = to_call / (pot + to_call) if to_call > 0 else Decimal(0)
    action = "check" if to_call == 0 else "call" if value >= required else "fold"
    return {"kind": "rough", "advice": [{"action": action, "frequency": 1.0}],
            "range_equity": {"value": round(value, 3), "opponents": len(opponents),
                             "hands": None, "hands_each": counts, "realize": realize},
            "required": round(float(required), 3), "pot": str(pot),
            "to_call": str(to_call), "basis": ROUGH_BASIS}


class AASolverAdvice:
    """Per-frame advice status; the solver runs on one background thread."""

    def __init__(self, bot=None, executor=None, preflop=None, model=None,
                 rough_executor=None, clock=time.monotonic):
        self._bot = bot
        self._executor = executor
        # The rough rule's own worker; an executor given for the solve serves
        # it too unless one is given for it.
        self._rough_executor = rough_executor or executor
        self._clock = clock
        self._preflop = preflop
        self._model = model
        self.reset()

    def reset(self):
        """Forget the hand being followed and the reads: a new observation
        numbers its frames, and so its hands, from 0 again, and may be
        another table."""
        self._rows, self._hand_id, self._jobs, self._quick = [], None, {}, {}
        self._rough, self._turn_from = {}, None
        self.reads = AAReads()

    def __call__(self, payload, frame):
        return self.observe(payload, frame)

    def settled(self):
        """This hand's id and its decisions so far: {(decision, street):
        outcome}, None while still being worked out. A solve that finishes
        after you acted is here too, for grading what you did; where the
        window showed the range rule's action instead (the solve could not
        answer) or the rough rule's, that is the outcome."""
        return self._hand_id, {key: self._shown(key) for key in list(self._jobs)}

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
            self._rows, self._hand_id = [], history["hand_id"]
            self._jobs, self._quick, self._rough = {}, {}, {}
        self._rows.append({"processed": frame, "fields": fields})
        del self._rows[:-MAX_ROWS]
        if not (fields.get("hero_controls") or {}).get("visible"):
            self._turn_from = None
            return self._report("idle", "not_your_turn")
        if self._turn_from is None:
            self._turn_from = (frame, self._clock())
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
            self._jobs[key] = self._start(fields, cards, frame, key)
        report = self._outcome(key, street)
        if report["status"] == "ready" or not self._rough_due(frame):
            return report
        return self._rough_outcome(key, fields, cards, street, frame, report) or report

    def _rough_due(self, frame):
        """Long enough into your turn for the rough rule."""
        first, since = self._turn_from
        return frame - first >= ROUGH_FRAMES or self._clock() - since >= ROUGH_SECONDS

    # -- jobs -------------------------------------------------------------------

    def _start(self, fields, cards, frame, key):
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
        self._quick[key] = self._submit(self._quick_rule, self._with_reads(observation),
                                        fields, time.monotonic())
        return self._submit(self._solve, observation, time.monotonic())

    def _submit(self, function, *args):
        if self._executor is None:
            _switch_quickly()
            self._executor = ThreadPoolExecutor(max_workers=WORKERS,
                                                thread_name_prefix="solver-advice")
        return self._executor.submit(function, *args)

    def _submit_rough(self, function, *args):
        """On a worker of its own: in the solve's pool it waits for the solve."""
        if self._rough_executor is None:
            _switch_quickly()
            self._rough_executor = ThreadPoolExecutor(max_workers=1,
                                                      thread_name_prefix="rough-advice")
        return self._rough_executor.submit(function, *args)

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

    def _quick_rule(self, observation, fields, started):
        """The range rule next to a heads-up solve; it never costs the solve."""
        try:
            return self._multiway(observation, fields, started)
        except Exception:                  # the solve still comes
            return {"status": "idle", "reason": "range_rule_failed"}

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

    def _quick_rule_done(self, key):
        """The range rule's advice worked out next to the solve, or None."""
        quick = self._quick.get(key)
        if quick is None or not quick.done() or quick.result().get("status") != "ready":
            return None
        return quick.result()

    def _provisional(self, key):
        """The range rule's advice while the solve is running, or None."""
        quick = self._quick_rule_done(key)
        return quick and {**quick, "provisional": True, "basis": PROVISIONAL_BASIS}

    def _rough_done(self, key):
        """The rough rule's action for this decision, or None (not asked, not
        done, or the screen does not give it what it needs)."""
        job = self._rough.get(key, (None,))[0]
        if job is None or not job.done():
            return None
        try:
            rough = job.result()
        except Exception:                  # never lose the other report over it
            rough = None
        return rough and {**rough, "status": "ready"}

    def _rough_outcome(self, key, fields, cards, street, frame, report):
        """The rough rule's report for this decision, or None. The frame that
        asks waits up to ``ROUGH_WAIT`` for it, so it shows in that frame and
        not the next (after a stall the next can be the turn's last). Asked
        again, ``RETRY`` frames on, with the screen as it is then when the
        frame asked did not give it what it needs (the price came a moment
        later)."""
        job, asked = self._rough.get(key, (None, None))
        if job is None or (job.done() and self._rough_done(key) is None
                           and frame >= asked + RETRY):
            job = self._submit_rough(rough_advice, fields, cards, street)
            self._rough[key] = job, frame
            wait([job], timeout=ROUGH_WAIT)
        rough = self._rough_done(key)
        if rough is None:
            return None
        rough.pop("status")
        return self._report("ready", None, street=street, decision=key[0],
                            rough_for=report.get("reason") or report["status"], **rough)

    def _answer(self, key):
        """The decision's outcome, None while the solve runs: the range rule's
        action when the solve cannot answer."""
        job = self._settle(key)
        if job is not None and job["status"] != "ready":
            quick = self._quick_rule_done(key)
            if quick is not None:          # the solve cannot answer; the rule does
                job = {**quick, "solver_gave_up": job.get("reason")}
        return job

    def _shown(self, key):
        """``_answer``, or the rough rule's action when it has none."""
        job = self._answer(key)
        if job is not None and job["status"] != "ready":
            job = self._rough_done(key) or job
        return job

    def _outcome(self, key, street):
        job = self._answer(key) or self._provisional(key)
        if job is None:
            return self._report("computing", None, street=street, decision=key[0])
        return self._report(job["status"], job.get("reason"), street=street,
                            decision=key[0], **{name: job[name] for name in (
                                "kind", "heads_up", "advice", "options", "cuts", "pot",
                                "to_call", "pot_offset", "mushroom_pool", "reads_hands",
                                "stacks_assumed", "inferred_actions", "range_equity",
                                "bomb_pot", "seconds", "basis", "provisional",
                                "solver_gave_up")
                                if name in job})

    def _report(self, status, reason, **extra):
        return {"schema_version": 1, "status": status, "reason": reason,
                "hand_id": self._hand_id, "basis": BASIS, **extra,
                "seat_reads": self.reads.labels(),
                "advice_emitted": status == "ready", "acts_on_client": False}


__all__ = ["AASolverAdvice", "advice_rows", "decision_key", "multiway_row",
           "range_report"]
