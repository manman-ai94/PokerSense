"""The default advice (classic) under the vision contract (补充二, 2026-10-16).

Before, every decision of yours replayed the hand on the AA table
(``aa_solver_input``) and worked it out three ways at once, on background
threads: the preflop model or the range rule, the heads-up solver on the turn
and the river, and a rough rule from the screen alone 0.6 s in. Whichever came
first showed, and a later one replaced it (补充二: of 593 decisions of yours
85 showed rough advice first, 22 changed their action, 9% ended rough; 26% on
杜's machine). That engine is still here as ``legacy`` (``AASolverAdvice``),
for replays that compare against it.

Here the old strategy's decisions go through the same contract as the
one-page rules (``aa_plain_advice``): the hand's state latched frame by frame
(``HandState``), the decision worked out once it is ready, once per (hand,
street, price), never changed, missing inputs filled in by their defaults, and
after 2 s still not ready the iron rule 5 (fold, or check when it is free) with
what is missing; not in your blind before the flop with no raise, where v3.2
lifted it for the one-page rules too (your cards read: worked out on what was
read; else check, or complete). Only the policy is the old one:

- before the flop ``aa_preflop`` (what folding, calling and raising are each
  worth against the AA players' ranges, with this session's reads of each
  opponent), the most valuable option;
- after the flop the ``range_multiway`` rule on every street with any number
  of opponents (your share of the pot against each opponent's range, read from
  their actions, against the price; heads-up with its own cuts), under the
  big-pot guard. No solver: the window does not wait for one (the scoreboard
  put the two level, 2026-10-10 and again 2026-10-16).

There is no rough rule and no answer from a background thread: one answer, on
the frame's own thread. Reading the opponents' ranges takes up to a second or
more a hand, so from your first action before the flop they are read ahead on
one thread of its own as the hand goes (only into ``opponent_ranges``' cache,
as before), again with each new card, stack, bet or fold read, and up to your
turn (who is still to act before you checks or calls): at your turn only what
came since is left to read. Only shows advice; never acts for you.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from decimal import Decimal
import sys
import threading
import time

from poker_engine.core.enums import Position
from poker_engine.scoreboard.bots import position
from poker_engine.scoreboard.mushroom import MIN_PLAYERS
from poker_engine.scoreboard.multiway_bot import DEFAULTS as MULTIWAY_LINES
from poker_engine.scoreboard.multiway_bot import cuts as multiway_cuts
from poker_engine.scoreboard.multiway_bot import guard_action, guarded, street_params
from poker_engine.scoreboard.multiway_bot import unguarded
from poker_engine.scoreboard.preflop_policy import AAPreflopPolicy
from poker_engine.scoreboard.preflop_reading import reading_model, reading_of
from poker_engine.scoreboard.ranges import opponent_ranges, ranges_equity
from poker_engine.scoreboard.side_pots import pots as side_pots

from poker_engine.scoreboard.replay import replay_deck
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

from .aa_plain_advice import DEFAULTS as DEFAULT_WORDS
from .aa_plain_advice import (EPSILON, HERO, MISSING, STREETS, AAPlainAdvice,
                              _money, blind_unraised, table_observation)
from .aa_solver_input import DEEP, board_history
from .aa_stakes import stakes_report

KIND = "classic"
MIN_SEATS, MAX_SEATS = 4, 8     # the tables the old strategy's models know
# The frame loop gets the interpreter lock back this soon while ranges are read
# ahead (measured in ``aa_solver_advice._switch_quickly``).
SWITCH_SECONDS = 0.0001
BASIS = ("the default strategy: preflop the AA preflop model, after the flop "
         "equity against each opponent's range against the price; for study only")
PREFLOP_BASIS = ("expected chips of each option against AA players' preflop "
                 "frequencies (read from recordings) and a heads-up equity table; "
                 "for study only")
MULTIWAY_BASIS = ("equity against every opponent's range (a population model fitted to "
                  "AA players' preflop play) against the price, the scoreboard's "
                  "range_multiway rule; for study only")
HEADS_UP_BASIS = ("equity against the opponent's range (a population model fitted to "
                  "AA players' preflop play) against the price, the scoreboard's "
                  "range_multiway rule with its heads-up cuts; for study only")
# What the old strategy takes for an input that is missing (补充二 §4): an
# opponent's stack never read is deep, as before.
DEFAULTS = {**DEFAULT_WORDS, "opponent_stack": "缺对手筹码→按很深算"}
UNREAD_BASIS = ("the screen was not steady for 2 s: iron rule 5 (fold, or check when "
                "it is free); for study only")
BLIND_BASIS = ("your blind before the flop with no raise, the screen not steady for "
               "2 s: iron rule 5 does not apply (v3.2); check, or complete; for study "
               "only")


def multiway_row(action, observation):
    """A ``range_multiway`` action id as an advice row (``fold``,
    ``check_call``, ``raise_to:<chips>``)."""
    to_call = Decimal(observation["to_call"] or 0)
    if action == "fold":
        return {"action": "fold", "frequency": 1.0}
    if action == "check_call":
        return {"action": "call" if to_call > 0 else "check", "frequency": 1.0}
    mine = Decimal(observation["bets"][str(observation["observing_seat"])])
    to = Decimal(action.partition(":")[2]).quantize(Decimal(1))
    return {"action": "raise" if to_call > 0 else "bet", "frequency": 1.0,
            "chips": _money(to - mine), "to": _money(to)}


def table_state(observation, partial=False):
    """The screen's observation (``aa_plain_advice.table_observation``) played
    out on the scoreboard table: (the table's observation for you, actions
    filled in). The old strategy reads each opponent's range by replaying
    their actions one by one, in turn; the actions read from the chips have
    no checks, may miss a call or a fold, and are in the order they were
    read. Each seat's own actions are played in their order when the table
    comes to that seat on that street; a seat with none left there (you
    too, while others' actions on the street are still to come) is filled
    in: with nothing to call it checks; facing a bet it folds if it has
    folded by now and acts no more in this hand, else it calls. A fold read
    with nothing to call waits for a bet still to come on the street, or
    else is played as a check (the table allows no such fold) and the seat
    counted folded; a raise the table does not allow is moved to the nearest
    one it does. Raises ``ValueError`` where the
    actions still do not fit (an action of a seat still in the hand left
    over, not your turn on this street at the end): the iron rule 5 then.
    ``partial``: the table after the last action read, whoever's turn it is
    (to read the ranges ahead of your turn)."""
    seats = observation["occupied_seats"]
    stacks = {int(seat): Decimal(chips)
              for seat, chips in observation["stacks"].items()}
    put = {int(seat): Decimal(chips)
           for seat, chips in observation["contributions"].items()}
    starting = {seat: stacks.get(seat, DEEP) + put[seat] for seat in seats}
    arena = AAFullHandArena(AARuleProfileV2.from_dict(observation["rules"]),
                            starting_stacks=starting, occupied_seats=seats,
                            dealer_seat=observation["dealer_seat"])
    arena.reset(0, deck=replay_deck(board_history(observation["board"]), len(seats)),
                bomb=observation.get("bomb_pot"))
    pending = list(observation["public_history"])
    folded = set(observation["folded"])
    filled = 0
    while not arena.terminal and not (partial and not pending):
        seat, street = arena.actor, arena.street
        mine = [row for row in pending
                if row["actor"] == seat and row["street"] == street]
        if (seat == HERO and street == observation["street"] and not mine
                and not any(row["street"] == street for row in pending)):
            break
        owed = Decimal(arena.observe(seat)["to_call"] or 0)
        if (mine and mine[0]["id"] == "fold" and owed <= 0
                and any(row["street"] == street and row["kind"] == "raise_to"
                        for row in pending if row["actor"] != seat)):
            mine = []                  # its fold came after a bet still to come
        if mine:
            pending.remove(mine[0])
            arena.step(_fitted(arena, mine[0]["id"]))
            continue
        if any(STREETS.index(row["street"]) < STREETS.index(street)
               for row in pending if row["actor"] == seat):
            raise ValueError("an action read on a street already over")
        later = any(row["actor"] == seat for row in pending)
        arena.step("fold" if owed > 0 and seat in folded and not later
                   else "check_call")
        filled += 1
    if not partial and (arena.terminal or arena.street != observation["street"]):
        raise ValueError("not your turn on this street")
    table = arena.observe(HERO)
    if any(row["actor"] not in table["folded"] + table["all_in"] for row in pending):
        raise ValueError("an action left over")
    table["folded"] = sorted(set(table["folded"]) | folded)
    return table, filled


def _fitted(arena, action):
    """``action`` as the table allows it here: a fold with nothing to call is
    a check, a raise outside what the table allows the nearest one it does
    (a call when it allows none)."""
    here = arena.observe(arena.actor)
    if action == "fold":
        return "fold" if Decimal(here["to_call"] or 0) > 0 else "check_call"
    if not action.startswith("raise_to:"):
        return action
    betting = here["betting"]
    if not betting["can_raise"]:
        return "check_call"
    unit = Decimal(str(here["rules"]["minimum_chip"]))
    to = Decimal(action.partition(":")[2])
    low, high = Decimal(betting["min_raise_to"]), Decimal(betting["max_raise_to"])
    to = min(high, max(low, to))
    return f"raise_to:{_money((to / unit).quantize(Decimal(1)) * unit)}"


def guard_report(size, was, street):
    """What the big-pot guard changed: the pot in big blinds and the advice
    before it."""
    return {"pot_big_blinds": round(size, 1), "line": MULTIWAY_LINES["guard"],
            "street": street, "was": was}


class ClassicPolicy:
    """The old strategy on one observation (the scoreboard table's shape)."""

    def __init__(self, reads=None, preflop=None, model=None):
        self._reads = reads or (lambda: {})
        self._preflop = preflop
        self._model = model

    def ready(self):
        """The models are loaded."""
        return self._model is not None

    def preflop_policy(self):
        if self._preflop is None:
            self._preflop = AAPreflopPolicy()
        return self._preflop

    def range_model(self):
        if self._model is None:
            policy = self.preflop_policy()
            self._model = reading_model(policy.adjusted, reading_of(policy))
        return self._model

    def with_reads(self, observation):
        reads = self._reads()
        return {**observation, "reads": reads} if reads else observation

    def decide(self, observation):
        """The report's advice part for the scoreboard table's observation
        (``table_state``), or what is missing for one: ``seats`` (the old
        strategy's models are of 4 to 8 players), ``ranges`` (the opponents'
        ranges leave no hand)."""
        if not MIN_SEATS <= len(observation["occupied_seats"]) <= MAX_SEATS:
            return "seats"
        observation = self.with_reads(observation)
        if observation["street"] == "preflop":
            return self.preflop(observation)
        return self.postflop(observation)

    def preflop(self, observation):
        pool = Decimal(observation.get("mushroom_pool") or 0)
        counted = None
        if (pool > 0 and len(observation["occupied_seats"]) >= MIN_PLAYERS
                and position(observation) == Position.SB):
            counted = _money(pool)
        choice = self.preflop_policy().choose(observation)
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
                row.update(to=_money(to), chips_in=_money(to - mine))
            elif name == "call":
                row.update(chips_in=_money(price))
            options.append(row)
        best = options[0]
        advice = {"action": best["action"], "frequency": 1.0}
        if best["action"] == "raise":
            advice.update(chips=best["chips_in"], to=best["to"])
        elif best["action"] == "call" and price <= 0:
            advice["action"] = "check"
        return {"kind": "preflop", "advice": [advice], "options": options,
                "mushroom_pool": counted, "reads_hands": _read_hands(observation),
                "basis": PREFLOP_BASIS}

    def postflop(self, observation):
        live = [seat for seat in observation["occupied_seats"]
                if seat not in observation["folded"]]
        heads_up = len(live) == 2
        ranges = opponent_ranges(observation, self.range_model())
        split = side_pots(observation)
        value, counts = ranges_equity(observation["own_hole"], observation["board"],
                                      ranges, pots=split)
        if value is None:
            return "ranges"
        edge = {"value": round(value, 3), "opponents": len(counts),
                "hands": sum(counts.values()) if len(counts) == 1 else None,
                "hands_each": {str(seat): count for seat, count in counts.items()}}
        if len(split) > 1:
            edge["side_pots"] = [{"chips": round(chips, 2),
                                  "seats": [str(seat) for seat in seats]}
                                 for chips, seats in split]
        bold = unguarded(observation, value)
        action = guard_action(observation, bold, value)
        line = multiway_cuts(observation, street_params(observation))
        report = {"kind": "multiway", "heads_up": heads_up,
                  "advice": [multiway_row(action, observation)],
                  "range_equity": edge,
                  "cuts": {name: round(cut, 3) for name, cut in line.items()},
                  "reads_hands": _read_hands(observation),
                  "basis": HEADS_UP_BASIS if heads_up else MULTIWAY_BASIS}
        if action != bold:
            report["guard"] = guard_report(guarded(observation),
                                           multiway_row(bold, observation),
                                           observation["street"])
        return report


def _read_ranges(observation, model, stop):
    """``opponent_ranges`` on the table as it is now, for its cache, until
    ``stop`` is set (checked after each action read)."""
    def stopped(*_):
        if stop.is_set():
            raise _Stopped
    try:
        opponent_ranges(observation, model, trace=stopped)
        return True
    except Exception:                       # stopped, or only a head start lost
        return False


class _Stopped(Exception):
    """The reading ahead was stopped."""


def _follows(line, later):
    """``later`` is the same hand as ``line`` with (maybe) more actions and
    cards."""
    (stacks, board, actions), (stacks_now, board_now, actions_now) = line, later
    return (stacks == stacks_now and board_now[:len(board)] == board
            and actions_now[:len(actions)] == actions)


def _line(table):
    """What a reading of the ranges on ``table`` depends on: the starting
    stacks, the cards on the board and the actions."""
    return (table["starting_stacks"], table["board"],
            [row["id"] for row in table["public_history"]])


def _read_hands(observation):
    """How many finished hands the reads in ``observation`` come from."""
    return max((read["hands"] for read in (observation.get("reads") or {}).values()),
               default=0)


class AAClassicAdvice(AAPlainAdvice):
    """Per-frame default advice: the hand's latched state, each decision worked
    out once on the frame's thread, by the old strategy."""

    kind = KIND
    basis = BASIS

    def __init__(self, policy=None, clock=time.monotonic):
        self.policy = policy or ClassicPolicy()
        self._read_ahead = None
        super().__init__(clock=clock)

    def reset(self):
        super().reset()
        # (hand, the reading ahead running, its table, a flag that stops it)
        self._ahead = None
        self._marked = None             # what was on the table when it started
        self._seen = None               # and when it was last looked at

    def observe_fields(self, fields, frame):
        report = super().observe_fields(fields, frame)
        self._read(fields)
        return report

    def _read(self, fields):
        """The opponents' ranges as they are now, read on the thread of its own
        (into the cache) while you are still in the hand, from your first
        action before the flop on:
        one reading at a time, again after each new card, stack, bet, fold or
        action read; one running that took the hand another way is stopped."""
        state, history = self.state, fields.get("actions_v1")
        if state is None or not history:
            return
        if self._ahead is None and not self.policy.ready():
            # The models load once, in a third of a second: not at your first turn.
            self._ahead = (self._hand_id, self._submit(self.policy.range_model),
                           None, None)
        street = fields.get("street")
        if (street not in STREETS or state.states.get(HERO) == "folded"
                or (street == "preflop" and street not in state.acted)):
            return
        mark = (self._hand_id, fields["street"], tuple(state.board),
                tuple(sorted(state.stacks.items())), len(state.events),
                len(state.folds), len(history.get("actions") or ()))
        running = self._ahead is not None and not self._ahead[1].done()
        if mark == (self._seen if running else self._marked):
            return
        self._seen = mark
        table = self._table(state, fields)
        if running:
            line = self._ahead[2]
            if line is not None and table is not None and not _follows(line,
                                                                       _line(table)):
                self._ahead[3].set()
            return
        self._marked = mark
        if table is None:
            return
        stop = threading.Event()
        self._ahead = (self._hand_id, self._submit(
            _read_ranges, self.policy.with_reads(table), self.policy.range_model(),
            stop), _line(table), stop)

    def _table(self, state, fields):
        """The scoreboard table as the screen has it now, up to your turn
        (whoever is still to act before you checks or calls, as the gaps are
        filled in at your turn) or else to the last action read; or None."""
        try:
            observation, _, _ = table_observation(state, fields, self.stakes(),
                                                  fit=False)
            seats = len(observation["occupied_seats"]) if observation else 0
            if not MIN_SEATS <= seats <= MAX_SEATS:
                return None
            try:
                return table_state(observation)[0]
            except ValueError:
                return table_state(observation, partial=True)[0]
        except Exception:                   # only a head start is lost
            return None

    def _submit(self, function, *args):
        if self._read_ahead is None:
            sys.setswitchinterval(min(sys.getswitchinterval(), SWITCH_SECONDS))
            self._read_ahead = ThreadPoolExecutor(max_workers=1,
                                                  thread_name_prefix="range-ahead")
        return self._read_ahead.submit(function, *args)

    def _decide(self, state, fields, street, now, missing, waited, history):
        stakes = self.stakes()
        if not missing:
            found = self._worked_out(state, fields, now, stakes)
            if not isinstance(found, list):
                return self._ready(found, fields, street, now, waited, history, stakes,
                                   {"tag": f"就绪 {waited:.1f}s"})
            missing = found
        return self._iron5(fields, street, now, missing, waited, history, stakes)

    def _worked_out(self, state, fields, now, stakes):
        """(the policy's part of the report, the table it was worked out on,
        the screen's observation, the defaults taken), or what is missing for
        it (a list): ``seats``, ``actions`` (the hand put together contradicts
        itself), ``ranges``, or the inputs ``table_observation`` misses."""
        observation, defaults, missing = table_observation(state, fields, stakes)
        if observation is None:
            return missing
        if not MIN_SEATS <= len(observation["occupied_seats"]) <= MAX_SEATS:
            return ["seats"]
        try:
            table, filled = table_state(observation)
            if abs(Decimal(table["to_call"]) - now) > Decimal(EPSILON):
                raise ValueError("the table's price is not the button's")
            table.update(own_hole=observation["own_hole"],
                         mushroom_pool=observation["mushroom_pool"],
                         flop_pot=observation["flop_pot"],
                         inferred_actions=observation["inferred_actions"] + filled)
            self._caught_up(table)
            found = self.policy.decide(table)
        except Exception:                   # the hand put together contradicts itself
            return ["actions"]
        if isinstance(found, str):
            return [found]
        return found, table, observation, defaults

    def _ready(self, worked, fields, street, now, waited, history, stakes, contract):
        found, table, observation, defaults = worked
        controls = fields.get("hero_controls") or {}
        facing = Decimal(observation["bets"][str(HERO)]) + now
        return self._report(
            "ready", None, street=street, **found,
            contract={**contract, "waited": round(waited, 1),
                      "defaults": [DEFAULTS[key] for key in defaults]},
            pot=table["pot"], to_call=table["to_call"], price=_money(now),
            decision=len(history.get("actions") or ()),
            inferred_actions=table["inferred_actions"],
            bomb_pot=observation["bomb_pot"], stakes_used=stakes_report(stakes),
            button=controls.get("button"), facing=_money(facing) if now else None)

    def _caught_up(self, table):
        """The reading ahead done: what it reads is read once, not twice. One
        that took the hand another way (the actions it filled in before your
        turn are not the ones taken) stops after the action it is reading."""
        if self._ahead is None or self._ahead[0] != self._hand_id:
            return
        _, job, line, stop = self._ahead
        if line is not None and not _follows(line, _line(table)):
            stop.set()
        wait([job])

    def _iron5(self, fields, street, now, missing, waited, history, stakes):
        """Not ready after 2 s, or nothing to work out from: iron rule 5 (fold,
        or check when it is free), saying what is missing; in your blind
        before the flop with no raise ``_blind`` instead."""
        if street == "preflop" and blind_unraised(self.state, stakes, now):
            return self._blind(fields, street, now, missing, waited, history, stakes)
        controls = fields.get("hero_controls") or {}
        action = "check" if controls.get("button") == "check" else "fold"
        words = "、".join(MISSING[key] for key in missing)
        return self._report(
            "ready", None, street=street, kind="unread",
            advice=[{"action": action, "frequency": 1.0}],
            contract={"tag": f"铁律 5：缺{MISSING[missing[0]]}",
                      "waited": round(waited, 1), "defaults": [],
                      "missing": list(missing), "reason": f"画面没读稳：缺{words}"},
            basis=UNREAD_BASIS,
            to_call=("0" if action == "check"
                     else None if now is None else _money(now)),
            price=None if now is None else _money(now),
            decision=len(history.get("actions") or ()),
            stakes_used=stakes_report(stakes), button=controls.get("button"))

    def _blind(self, fields, street, now, missing, waited, history, stakes):
        """Your small or big blind (or straddle) before the flop with no raise,
        not worked out (the screen not steady for 2 s, or the hand not fitting
        the table): iron rule 5 does not apply there (v3.2, as for the one-page
        rules). Your cards read and never two ways: the old strategy on what
        was read. Else check, or complete: a blind folds no hand it has not
        seen for the price of a check or half a blind."""
        state = self.state
        words = "、".join(MISSING[key] for key in missing)
        if state.hero is not None and not state.card_conflict():
            found = self._worked_out(state, fields, now, stakes)
            if not isinstance(found, list):
                return self._ready(found, fields, street, now, waited, history, stakes,
                                   {"tag": f"盲位照算：缺{MISSING[missing[0]]}",
                                    "blind": True, "missing": list(missing)})
        controls = fields.get("hero_controls") or {}
        action = "check" if now == 0 else "call"
        word = "过牌" if action == "check" else "补齐"
        return self._report(
            "ready", None, street=street, kind="unread",
            advice=[{"action": action, "frequency": 1.0}],
            contract={"tag": f"盲位没人加注：{word}（缺{MISSING[missing[0]]}）",
                      "waited": round(waited, 1), "defaults": [], "blind": True,
                      "missing": list(missing),
                      "reason": f"盲位没人加注，铁律 5 不适用：画面没读稳（缺{words}），先{word}"},
            basis=BLIND_BASIS, to_call=_money(now), price=_money(now),
            decision=len(history.get("actions") or ()),
            stakes_used=stakes_report(stakes), button=controls.get("button"))


__all__ = ["AAClassicAdvice", "BASIS", "ClassicPolicy", "DEFAULTS", "KIND",
           "multiway_row", "table_state"]
