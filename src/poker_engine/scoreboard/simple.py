"""大道至简 ("the great way is simple"): one rule for every decision.

Every decision, before the flop or after it, heads-up or multiway, does one
thing: narrow each opponent's hands by what he did, work out your share of
the pot against them, and hold it against the price. A strong player does
this at the table with a few tables in his head; this module writes those
tables down.

**Reading an opponent.** His hands start as every two cards (any two cards
in a bomb pot, where no one chose to play). Each of his actions cuts them:
his hands are put in order of strength (before the flop by the starting-hand
order, after it by their share against a random hand on the board of that
moment), and the action keeps the band of that order an AA player keeps
when he plays that way (``PREFLOP``, ``CHECKED_TO``, ``FACING_BET``,
``FACING_RAISE``: shares measured on the AA recordings, 10/16):

* a bet keeps the top band as wide as AA players bet there (heads-up on the
  flop checked to, not the preflop raiser: 24%); a raise the top band as
  wide as they raise; a call the band below the raises; a check everything
  below the bets;
* the bigger the bet, the narrower the band (``SIZE_FACTOR``: half the pot
  as measured, the pot x0.75, more or all in x0.55);
* the hands outside the band keep a little weight, never none: bluffs
  (``BLUFF``, ``RAISE_FLOOR``), slow play (``SLOW``: strong hands that check
  or call) and sticky calls (``STICKY``). So a range is never cut down to a
  few hands, and a big bet or an all in is never read as weak, which is where
  the 10/07-10/16 real hands lost most (19 hands, -1,272 bb after luck: the
  advice put a one-pair hand at 60-100% against a raise or a shove).

Before the flop AA players play far less by their cards than any chart: the
AA calibrated table fitted ``MIX`` of 0.6 on the recordings (a limp can hold
aces, an open raise trash), so the hands outside a band keep
``MIX x share / (1 - MIX + MIX x share)`` of the weight.

**Your decision.** Your share of the pot against those ranges (side pots
against the players in them, ``side_pots``) against the price (the call over
what it can win, after rake):

* facing a bet: call when the share is at least the price, else fold; raise
  when your share against the hands that would go on against the raise is
  over ``fair + MARGIN`` (fair: a half heads-up, a third three-way, ...);
* nothing to call: bet when your share against the hands that would call
  the bet is over ``fair + MARGIN``, else check. No bluffs;
* sizes: bets ``BET_SIZE`` of the pot, raises to a pot-sized raise, all in
  when what would be left is under ``JAM`` of the pot after it.

**Before the flop** the same, with a chart only for raising (raising wins
the blinds and limps, which an equity cannot see): first in, raise the top
``OPEN[players still to act]`` of hands; over limpers the top ``ISO`` x
that; against one raise re-raise the top ``THREE``, against more the top
``FOUR`` all in. Otherwise call when the share times what it can realize
after the flop (``realize``) beats the price, else fold. A raise at 15 big
blinds or less, or one that would put in ``JAM_PREFLOP`` of the stack, is all
in. The mushroom pool (蘑菇) counts in the pot when you are the small blind,
who takes it with the pot.

``simple`` plays every street this way; ``simple+aa_preflop`` plays before
the flop with ``aa_preflop`` and after it this way. The rule is for study
only: it advises, a person acts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
from itertools import combinations
import random

import numpy as np

from poker_engine.core.enums import Position
from poker_engine.solver.texassolver import combo_key

from .bots import _Policy, position
from .ranges import ranges_equity
from .replay import public_replay
from .side_pots import pots as side_pots
from .side_pots import price as side_price
from .spots import KINDS, preflop_spot
from .strength import CARD_ID, DECK, _EVALUATE_7, combo_percentile, range_equity

# -- the tables ----------------------------------------------------------------
# (raise, call) shares of AA players at each kind of preflop decision
# (``spots.preflop_spot``), all positions pooled: the AA calibrated table's
# numbers on 2026-10-16 (aa_cal_stats_v1.json, 20 recordings, 533 hands).
PREFLOP = {"rfi": (0.113, 0.376), "vs_limp": (0.151, 0.471),
           "vs_open": (0.063, 0.253), "vs_3bet_cold": (0.015, 0.029),
           "limp_vs_raise": (0.067, 0.425), "open_vs_3bet": (0.091, 0.40),
           "call_vs_3bet": (0.033, 0.20), "3bet_vs_4bet": (0.18, 0.36)}
# After the flop, nothing to call: how often AA players bet, by street,
# heads-up or multiway and whether they raised last before the flop.
CHECKED_TO = {("flop", "hu", "pfa"): 0.80, ("flop", "hu", "other"): 0.24,
              ("flop", "multi", "pfa"): 0.55, ("flop", "multi", "other"): 0.19,
              ("turn", "hu", "pfa"): 0.62, ("turn", "hu", "other"): 0.39,
              ("turn", "multi", "pfa"): 0.42, ("turn", "multi", "other"): 0.25,
              ("river", "hu", "pfa"): 0.38, ("river", "hu", "other"): 0.49,
              ("river", "multi", "pfa"): 0.26, ("river", "multi", "other"): 0.26}
# Facing a bet: (raise, call) shares. Facing a raise (few counted): one guess
# for every street.
FACING_BET = {("flop", "hu"): (0.06, 0.32), ("flop", "multi"): (0.07, 0.22),
              ("turn", "hu"): (0.13, 0.43), ("turn", "multi"): (0.08, 0.15),
              ("river", "hu"): (0.20, 0.26), ("river", "multi"): (0.08, 0.08)}
FACING_RAISE = {"hu": (0.15, 0.45), "multi": (0.05, 0.22)}
# A bet's band against its size (chips it adds over the pot before it):
# (size up to, factor); the shares above are of bets about half the pot.
SIZE_FACTOR = ((0.4, 1.25), (0.8, 1.0), (1.2, 0.75), (None, 0.55))
MIX = 0.6                       # before the flop: decisions not by the cards
# After the flop, the weight hands outside the band keep (of the band's 1):
SLOW = 0.3                      # strong hands that check or call
BLUFF = {"flop": 0.10, "turn": 0.08, "river": 0.05}     # bets without one
STICKY = {"flop": 0.15, "turn": 0.10, "river": 0.05}    # calls without one
RAISE_FLOOR = 0.03              # raises without one (river raises: 3% air)

# -- your play -----------------------------------------------------------------
MARGIN = 0.05                   # a bet or raise needs fair share + this
BET_SIZE = 0.66                 # of the pot
RAISE_SIZE = 1.0                # a pot-sized raise
JAM = 0.5                       # all in when less than this of the pot is left
# First in: the top share of hands to raise, by players still to act.
OPEN = {1: 0.35, 2: 0.28, 3: 0.22, 4: 0.18, 5: 0.15, 6: 0.13, 7: 0.12}
ISO = 0.75                      # over limpers: that share of OPEN
THREE = 0.04                    # against one raise: TT+, AQs+, AK
FOUR = 0.026                    # against two or more: QQ+, AK, all in
SHORT_BB = 15.0                 # a raise is all in at this stack or less
JAM_PREFLOP = 0.4               # or when it puts in this share of the stack
REALIZE_IP, REALIZE_OOP = 0.9, 0.75
REALIZE_SUITED = 0.05           # suited hands and pairs realize more
REALIZE_CROWD = 0.05            # less for each opponent after the first
TRIALS = 2500
PREFLOP_TRIALS = 1500
FLOP_RUNOUTS = 40               # turn and river cards dealt to rank flop hands

STREETS = ("preflop", "flop", "turn", "river")
# Every two cards, as card numbers and as the solver's names.
PAIRS = list(combinations(range(52), 2))
KEYS = [combo_key((DECK[a], DECK[b])) for a, b in PAIRS]
_FIRST = np.array([a for a, _ in PAIRS])
_SECOND = np.array([b for _, b in PAIRS])
_HOLDS = np.array([(_FIRST == card) | (_SECOND == card) for card in range(52)])
# Before the flop, strength is the starting-hand order (higher is stronger).
PREFLOP_STRENGTH = -np.array([combo_percentile((DECK[a], DECK[b])) for a, b in PAIRS])


@dataclass(frozen=True)
class Move:
    """One opponent action, as the reading needs it."""
    seat: int
    street: str
    kind: str                   # "f" fold, "c" check or call, "r" bet or raise
    spot: str                   # preflop: ``preflop_spot``; after the flop:
    #                             checked_to, facing_bet or facing_raise
    width: str = "hu"           # "hu" or "multi": his opponents then
    role: str = "other"         # "pfa": he raised last before the flop
    size: float = 0.0           # bet or raise: chips it adds over the pot
    #                             before it; call: the bet it calls, the same way
    free: bool = False          # nothing to call: a check
    board: tuple = ()


@dataclass
class Spot:
    """Your decision, as the rule needs it."""
    hero: tuple
    board: tuple
    street: str
    opponents: tuple            # seats still in
    moves: tuple                # their actions so far (``Move``)
    pot: float                  # in the middle, every bet on this street included
    to_call: float
    stack: float                # your chips behind
    bet: float                  # your chips in front on this street
    top: float                  # the highest bet on this street
    big_blind: float
    price: float                # the call over what it can win (0 when free)
    pots: list | None = None    # [(chips, seats)] main pot first; None: one pot
    all_in: tuple = ()          # opponents with nothing behind
    posted: tuple = ()          # opponents with chips in on this street
    can_raise: bool = True
    min_raise_to: float | None = None
    max_raise_to: float | None = None
    preflop_spot: str = "rfi"
    raises: int = 0             # raises before the flop so far
    behind: int = 0             # before the flop: players still to act after you
    in_position: bool = False   # you act last after the flop
    effective_bb: float = 100.0
    bomb: bool = False
    seed: int = 0


@dataclass
class Advice:
    action: str                 # fold, check, call, bet or raise
    to: float | None = None     # bet or raise: your bet after it
    equity: float | None = None  # your share of the pot against their ranges
    need: float | None = None   # the share the action needed
    rule: str = ""              # which line decided
    kept: dict = field(default_factory=dict)  # {seat: share of hands left}

    def row(self):
        item = {"action": self.action, "rule": self.rule,
                "equity": None if self.equity is None else round(self.equity, 3),
                "need": None if self.need is None else round(self.need, 3)}
        if self.to is not None:
            item["to"] = round(self.to, 2)
        if self.kept:
            item["kept"] = {str(seat): round(share, 3)
                            for seat, share in self.kept.items()}
        return item


# -- reading -------------------------------------------------------------------

def size_factor(size):
    return next(factor for top, factor in SIZE_FACTOR if top is None or size <= top)


def alive(cards):
    """Combinations that use none of ``cards``."""
    ids = [CARD_ID[card] for card in cards if card]
    if not ids:
        return np.ones(len(PAIRS), bool)
    return ~_HOLDS[ids].any(axis=0)


def board_strength(board):
    """Each two cards' share of the pot against one random hand on ``board``
    (the river exact, the turn over every river, the flop over
    ``FLOP_RUNOUTS`` turns and rivers); -1 where they use a board card."""
    if not board:
        return PREFLOP_STRENGTH
    return _strength(tuple(sorted(CARD_ID[card] for card in board)))


@lru_cache(maxsize=4096)
def _strength(board):
    rest = [card for card in range(52) if card not in board]
    if len(board) == 5:
        runouts = [()]
    elif len(board) == 4:
        runouts = [(card,) for card in rest]
    else:
        rng = random.Random(hashlib.sha256(repr(board).encode()).digest())
        runouts = [tuple(rng.sample(rest, 5 - len(board))) for _ in range(FLOP_RUNOUTS)]
    total = np.zeros(len(PAIRS))
    count = np.zeros(len(PAIRS))
    for extra in runouts:
        full = (*board, *extra)
        live = ~_HOLDS[list(full)].any(axis=0)
        index = np.flatnonzero(live)
        ranks = np.array([_EVALUATE_7(int(_FIRST[i]), int(_SECOND[i]), *full)
                          for i in index])
        order = np.sort(ranks)
        worse = len(ranks) - np.searchsorted(order, ranks, side="right")
        ties = (np.searchsorted(order, ranks, side="right")
                - np.searchsorted(order, ranks, side="left") - 1)
        total[index] += (worse + 0.5 * ties) / max(len(ranks) - 1, 1)
        count[index] += 1
    strength = np.full(len(PAIRS), -1.0)
    seen = count > 0
    strength[seen] = total[seen] / count[seen]
    strength[~alive([DECK[card] for card in board])] = -1.0
    return strength


def places(weights, strength):
    """Each hand's place in the range from the top (0 strongest, 1 weakest):
    the share of the range's weight stronger than it, plus half its own."""
    order = np.argsort(-strength, kind="stable")
    sorted_weights = weights[order]
    total = sorted_weights.sum()
    place = np.ones(len(weights))
    if total <= 0:
        return place
    place[order] = (np.cumsum(sorted_weights) - sorted_weights / 2) / total
    return place


def likelihood(move, place):
    """How likely each hand at ``place`` is to have played ``move``."""
    if move.street == "preflop":
        raise_share, call_share = PREFLOP.get(move.spot, (0.1, 0.3))
        if move.kind == "r":
            inside, share = place <= raise_share, raise_share
        elif move.free:             # a blind's free check: all but the raises
            inside, share = place > raise_share, 1 - raise_share
        else:
            inside = (place > raise_share) & (place <= raise_share + call_share)
            share = call_share
        floor = MIX * share / (1 - MIX + MIX * share)
        return np.where(inside, 1.0, floor)
    factor = size_factor(move.size)
    if move.spot == "checked_to":
        bet = CHECKED_TO.get((move.street, move.width, move.role), 0.3)
        if move.kind == "r":
            return np.where(place <= min(1.0, bet * factor), 1.0, BLUFF[move.street])
        return np.where(place <= bet, SLOW, 1.0)
    if move.spot == "facing_bet":
        raise_share, call_share = FACING_BET.get((move.street, move.width), (0.1, 0.3))
    else:
        raise_share, call_share = FACING_RAISE[move.width]
    if move.kind == "r":
        return np.where(place <= raise_share * factor, 1.0, RAISE_FLOOR)
    keep = min(1.0, (raise_share + call_share) * factor)
    top = min(raise_share * factor, keep)       # the hands that would raise
    return np.where(place <= top, SLOW,
                    np.where(place <= keep, 1.0, STICKY[move.street]))


def read_ranges(moves, seats, dead=()):
    """{seat: weights over ``PAIRS``} for each of ``seats`` after ``moves``,
    without the hands that use a card of ``dead`` (yours and the board)."""
    ranges = {seat: np.ones(len(PAIRS)) for seat in seats}
    for move in moves:
        if move.seat not in ranges or move.kind == "f":
            continue
        weights = ranges[move.seat] * alive(move.board)
        strength = board_strength(move.board)
        after = weights * likelihood(move, places(weights, strength))
        if after.sum() > 0:
            ranges[move.seat] = after
    keep = alive(dead)
    return {seat: weights * keep for seat, weights in ranges.items()}


def continuing(weights, board, street, width, facing, size):
    """The part of a range that goes on against your bet (``facing``
    "facing_bet") or raise ("facing_raise") of ``size``: the raises and calls
    an AA player makes there, the rest at their sticky weight."""
    if facing == "facing_bet":
        raise_share, call_share = FACING_BET.get((street, width), (0.1, 0.3))
    else:
        raise_share, call_share = FACING_RAISE[width]
    keep = min(1.0, (raise_share + call_share) * size_factor(size))
    floor = STICKY.get(street, 0.05)
    place = places(weights, board_strength(board))
    return weights * np.where(place <= keep, 1.0, floor)


def as_keys(weights):
    return {KEYS[i]: float(weights[i]) for i in np.flatnonzero(weights > 0)}


def share_of_pot(spot, ranges, pots=None, trials=TRIALS):
    """Your share of the pot against ``ranges`` ({seat: weights})."""
    if not ranges:
        return 1.0
    board = tuple(card for card in spot.board if card)
    if len(ranges) == 1 and len(board) >= 4 and not pots:
        (weights,) = ranges.values()
        value, _ = range_equity(tuple(spot.hero), board, as_keys(weights))
        if value is not None:
            return value
    value, _ = ranges_equity(tuple(spot.hero), board,
                             {seat: as_keys(weights)
                              for seat, weights in ranges.items()},
                             trials=trials, seed=spot.seed, pots=pots)
    return value


# -- deciding ------------------------------------------------------------------

def decide(spot):
    """``Advice`` for ``spot``."""
    if spot.street == "preflop":
        return preflop(spot)
    return postflop(spot)


def kept(ranges, dead):
    """{seat: share of the hands the cards leave that the reading keeps}."""
    room = alive(dead).sum()
    return {seat: float(weights.sum() / room) for seat, weights in ranges.items()}


def _sized(spot, put):
    """Your bet after putting ``put`` more in, all in when little would be left."""
    most = spot.max_raise_to if spot.max_raise_to is not None else spot.bet + spot.stack
    to = spot.bet + put
    left = spot.bet + spot.stack - to
    after = spot.pot + put + max(0.0, to - spot.top)
    if left < JAM * after:
        to = most
    if spot.min_raise_to is not None:
        to = max(to, spot.min_raise_to)
    return min(to, most)


def bet_to(spot):
    return _sized(spot, BET_SIZE * spot.pot)


def raise_to(spot):
    return _sized(spot, spot.to_call + RAISE_SIZE * (spot.pot + spot.to_call))


def postflop(spot):
    dead = (*spot.hero, *spot.board)
    ranges = read_ranges(spot.moves, spot.opponents, dead)
    share = share_of_pot(spot, ranges, spot.pots)
    if share is None:                         # no hand left to deal: be careful
        return Advice("check" if spot.to_call == 0 else "fold", rule="no_range")
    left = kept(ranges, dead)
    actors = [seat for seat in spot.opponents if seat not in spot.all_in]
    fair = 1.0 / (len(spot.opponents) + 1)
    width = "hu" if len(spot.opponents) == 1 else "multi"
    can_raise = spot.can_raise and actors and spot.stack > spot.to_call
    if spot.to_call == 0:
        if not can_raise:
            return Advice("check", equity=share, rule="nobody_to_bet_into", kept=left)
        to = bet_to(spot)
        callers = {seat: continuing(weights, spot.board, spot.street, width,
                                    "facing_bet", (to - spot.bet) / max(spot.pot, 1e-9))
                   for seat, weights in ranges.items()}
        against = share_of_pot(spot, callers, spot.pots)
        if against is not None and against >= fair + MARGIN:
            return Advice("bet", to, against, fair + MARGIN, "value_bet", left)
        return Advice("check", equity=share, need=fair + MARGIN, rule="check",
                      kept=left)
    if can_raise and share >= spot.price:
        to = raise_to(spot)
        size = (to - spot.top) / max(spot.pot + spot.to_call, 1e-9)
        goers = {seat: continuing(weights, spot.board, spot.street, width,
                                  "facing_raise", size)
                 for seat, weights in ranges.items()}
        against = share_of_pot(spot, goers, spot.pots)
        if against is not None and against >= fair + MARGIN:
            return Advice("raise", to, against, fair + MARGIN, "value_raise", left)
    if share >= spot.price:
        return Advice("call", equity=share, need=spot.price, rule="price", kept=left)
    return Advice("fold", equity=share, need=spot.price, rule="price", kept=left)


def realize(spot, opponents):
    """The share of its equity a hand keeps when the hand is played on."""
    value = REALIZE_IP if spot.in_position else REALIZE_OOP
    first, second = spot.hero
    if first[0] == second[0] or first[1] == second[1]:
        value += REALIZE_SUITED
    value -= REALIZE_CROWD * max(0, opponents - 1)
    return min(1.0, max(0.5, value))


def preflop_raise(spot, all_in=False):
    most = spot.max_raise_to if spot.max_raise_to is not None else spot.bet + spot.stack
    to = spot.top + (spot.pot + spot.to_call)          # a pot-sized raise
    if (all_in or spot.effective_bb <= SHORT_BB
            or to - spot.bet >= JAM_PREFLOP * (spot.stack + spot.bet)):
        to = most
    if spot.min_raise_to is not None:
        to = max(to, spot.min_raise_to)
    return min(to, most)


def preflop(spot):
    place = combo_percentile(tuple(spot.hero))
    behind = max(1, min(7, spot.behind))
    can_raise = spot.can_raise and spot.stack > spot.to_call
    opening = OPEN[behind]
    if spot.raises == 0:
        line = opening if spot.preflop_spot == "rfi" else ISO * opening
        if can_raise and place <= line:
            return Advice("raise", preflop_raise(spot), need=line, rule="open"
                          if spot.preflop_spot == "rfi" else "isolate")
        if spot.to_call == 0:
            return Advice("check", rule="free")
        if spot.preflop_spot == "rfi":
            return Advice("fold", need=line, rule="open_chart")
    elif can_raise and place <= (THREE if spot.raises == 1 else FOUR):
        return Advice("raise", preflop_raise(spot, all_in=spot.raises >= 2),
                      need=THREE if spot.raises == 1 else FOUR,
                      rule="three_bet" if spot.raises == 1 else "four_bet")
    # Who you play against: the players in, and the blinds who posted (in a
    # limped pot they see the flop for free).
    involved = [seat for seat in spot.opponents
                if seat in spot.posted
                or any(move.seat == seat and move.kind != "f" for move in spot.moves)]
    ranges = read_ranges(spot.moves, involved, spot.hero)
    share = share_of_pot(spot, ranges, None, trials=PREFLOP_TRIALS)
    if share is None:
        return Advice("fold", rule="no_range")
    all_in = spot.stack <= spot.to_call or (
        involved and all(seat in spot.all_in for seat in involved))
    worth = share if all_in else share * realize(spot, len(involved))
    action = "call" if worth >= spot.price else "fold"
    return Advice(action, equity=worth, need=spot.price, rule="price",
                  kept=kept(ranges, spot.hero))


# -- the scoreboard table's observations ---------------------------------------

def moves_of(observation):
    """(``Move`` for every past action but yours, [(actor, kind)] before the
    flop with yours) from the hand's public actions."""
    me = observation["observing_seat"]
    preflop_actions, raiser, moves = [], None, []
    raises_on = {}
    for decision in public_replay(observation):
        seen = decision.observation
        kind = KINDS[decision.action["kind"]]
        street = decision.street
        to_call = float(seen["to_call"] or 0)
        pot = float(seen["pot"])
        if street == "preflop":
            spot = preflop_spot(preflop_actions, decision.seat)
            preflop_actions.append((decision.seat, kind))
            if kind == "r":
                raiser = decision.seat
            if decision.seat != me:
                moves.append(Move(decision.seat, street, kind, spot, free=to_call == 0))
            continue
        before = raises_on.get(street, 0)
        if kind == "r":
            raises_on[street] = before + 1
        if decision.seat == me:
            continue
        live = len(seen["occupied_seats"]) - len(seen["folded"]) - 1
        facing = ("checked_to", "facing_bet", "facing_raise")[min(before, 2)]
        if kind == "r":
            mine = float(seen["bets"][str(decision.seat)])
            size = (float(decision.action["raise_to"]) - mine) / max(pot, 1e-9)
        else:
            size = to_call / max(pot - to_call, 1e-9) if to_call else 0.0
        moves.append(Move(decision.seat, street, kind, facing,
                          "hu" if live == 1 else "multi",
                          "pfa" if decision.seat == raiser else "other", size,
                          to_call == 0, tuple(seen["board"])))
    return moves, preflop_actions


def _postflop_order(observation, seat):
    """Where ``seat`` acts after the flop: 0 first (small blind) ... last the
    button."""
    occupied = observation["occupied_seats"]
    start = occupied.index(observation["dealer_seat"])
    clockwise = occupied[start:] + occupied[:start]
    return (clockwise.index(seat) - 1) % len(clockwise)


def spot_from_observation(observation):
    """The ``Spot`` of the player to act on the scoreboard table (or of a
    live hand replayed on it)."""
    me = observation["observing_seat"]
    folded = set(observation["folded"])
    opponents = tuple(seat for seat in observation["occupied_seats"]
                      if seat != me and seat not in folded)
    bets = {int(seat): float(value) for seat, value in observation["bets"].items()}
    stacks = {int(seat): float(value) for seat, value in observation["stacks"].items()}
    big_blind = float(observation["rules"]["big_blind"])
    moves, preflop_actions = moves_of(observation)
    to_call = float(observation["to_call"] or 0)
    pot = float(observation["pot"])
    price = side_price(observation)
    pool = observation.get("mushroom_pool")
    if (observation["street"] == "preflop" and pool and float(pool) > 0
            and len(observation["occupied_seats"]) >= 4
            and position(observation) == Position.SB and to_call):
        price = to_call / (to_call / price + float(pool)) if price else 0.0
    layers = side_pots(observation)
    betting = observation.get("betting") or {}
    acted = {seat for seat, _ in preflop_actions}
    reach = [stacks[seat] + bets[seat] for seat in opponents]
    effective = min(stacks[me] + bets[me], max(reach, default=0.0))
    digest = hashlib.sha256("|".join((
        ",".join(observation["own_hole"]), ",".join(observation["board"]),
        str(len(observation["public_history"])))).encode()).digest()
    return Spot(
        hero=tuple(observation["own_hole"]), board=tuple(observation["board"]),
        street=observation["street"], opponents=opponents, moves=tuple(moves),
        pot=pot, to_call=to_call, stack=stacks[me], bet=bets[me],
        top=max(bets.values()), big_blind=big_blind, price=price,
        pots=layers if len(layers) > 1 else None,
        all_in=tuple(seat for seat in opponents if stacks[seat] <= 0),
        posted=tuple(seat for seat in opponents if bets[seat] > 0),
        can_raise=bool(betting.get("can_raise", True)),
        min_raise_to=(float(betting["min_raise_to"])
                      if betting.get("min_raise_to") is not None else None),
        max_raise_to=(float(betting["max_raise_to"])
                      if betting.get("max_raise_to") is not None else None),
        preflop_spot=preflop_spot(preflop_actions, me),
        raises=sum(kind == "r" for _, kind in preflop_actions),
        behind=sum(seat not in acted for seat in opponents),
        in_position=all(_postflop_order(observation, me)
                        > _postflop_order(observation, seat) for seat in opponents),
        effective_bb=effective / big_blind if big_blind else 100.0,
        bomb=observation.get("bomb_pot") is not None,
        seed=int.from_bytes(digest[:4], "big"))


def action_id(advice, observation):
    """The table's action id for ``advice``."""
    if advice.action in ("bet", "raise") and advice.to is not None:
        betting = observation.get("betting") or {}
        if betting.get("can_raise", True):
            chip = float(observation["rules"]["minimum_chip"])
            amount = round(advice.to / chip) * chip
            low, high = betting.get("min_raise_to"), betting.get("max_raise_to")
            if low is not None:
                amount = max(amount, float(low))
            if high is not None:
                amount = min(amount, float(high))
            return f"raise_to:{amount:g}"
        return "check_call"
    if advice.action == "fold" and float(observation["to_call"] or 0) > 0:
        return "fold"
    return "check_call"


class SimpleBot(_Policy):
    """``simple``: every decision by the rule above; ``simple+base``: before
    the flop by ``base``."""

    def __init__(self, base=None, name="simple"):
        self.base, self.name = base, name
        self.adjusted = True

    def for_game(self, salt):
        base = self.base.for_game(salt) if self.base is not None else None

        def policy(observation):
            if base is not None and observation["street"] == "preflop":
                return base(observation)
            return action_id(decide(spot_from_observation(observation)), observation)
        return policy

    def decide(self, observation, rng):
        if self.base is not None and observation["street"] == "preflop":
            return self.base.decide(observation, rng)
        return action_id(decide(spot_from_observation(observation)), observation)


def from_name(name, make_policy):
    """``simple`` or ``simple+base``."""
    _, _, base = name.partition("+")
    return SimpleBot(make_policy(base) if base else None, name)


__all__ = ["Advice", "Move", "SimpleBot", "Spot", "board_strength", "continuing",
           "decide", "from_name", "likelihood", "moves_of", "places", "read_ranges",
           "spot_from_observation"]
