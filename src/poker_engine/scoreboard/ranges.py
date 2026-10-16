"""Every opponent's range from the hand's public actions, and equity against them.

Without a solver (the flop, and pots with more than one opponent) each
opponent still in is read the way the solver strategy reads its heads-up
opponent: start from every two cards the board leaves and keep, at each of
their past actions, the hands the population model plays that way
(``solver_bot.kept``); after the flop the hands it plays otherwise keep a
weight (``postflop_reading``: slow play, calls the model folds, bluffs)
instead of dropping out. An action the model would never take with any hand
leaves that range as it was. Your share of the pot against those ranges is
then worked out by dealing each opponent a hand from their range (weighted,
without sharing cards) and the rest of the board, many times over.

Reading an action asks the model about every hand, so a hand with many
actions (a bomb pot, where everyone sees the flop) took seconds per decision
when every decision read the whole hand again. The range each action leaves
its player with depends only on the public hand up to it, so it is kept
(``CACHE_SIZE`` actions, for every hand of the process) and a later decision
reads only the new actions. Each action is read from the hands the board of
that moment leaves; the cards dealt since are taken out only at the end.
Until 2026-10-11 the hands were cut by the board of the decision that first
read the action, and another hand with the same actions but other cards got
that range (96 of 265 postflop readings on an AA population table differed
from reading afresh), so results depended on which hands a process had
played before.

The model's players are the AA population. With reads on the opponents
(``observation["reads"]``, see ``reads``) each seat is read as the player
the reads show, not the average one, in two ways:

* before the flop the model plays the seat's first decision with its raise
  and call shares scaled by the reads (``read_factors``), as ``aa_preflop``
  expects it to, so a seat that raises twice as often raises with a range
  twice as wide;
* after the flop a seat whose read shows it bets or raises clearly more often
  than the model there (``reads.aggression_factor``) keeps, at each action,
  ``FLOOR_SLOPE`` x (that factor - ``FLOOR_FROM``), at most ``MAX_FLOOR``, of
  the weight of the hands the model would not have played that way: such
  players bet with more than the population's thresholds say. Below
  ``FLOOR_FROM`` the difference can be the noise of a short session. Raising
  more before the flop is not taken as betting more after it: a tight
  aggressive player who bets honestly was read as a maniac that way and
  called down far too lightly in bomb pots. A read with no postflop numbers
  keeps no extra hands.

Without reads, or for a seat that plays like the model, nothing changes.
Against reg and maniac tables the AI folded to flop bets with hands that had
the price (23% and 48% of its folds), and in bomb pots far more.

A bet read by strength alone (``narrowed``, for the live window's rough rule,
which has no model of the hand): each hand of the range keeps exp(-p / scale)
of its weight, p its place in the range by the hand it makes with the board
of the bet (0 the strongest, 1 the weakest); ``BET_SCALE`` for a bet,
``RAISE_SCALE`` for a raise over a bet or a bet of ``BIG_BET`` of the pot or
more, and a flush or open-ended straight draw keeps at least
``DRAW_WEIGHT``. The scales are those of the hands shown at the end of a
hand in the recordings of 2026-09-14 to 10-16 (10 of the window's own logs
and 杜's three): placed in a top-40% range on the board of each of their
bets, the 82 shown bets had their middle at 0.23, a quarter beyond 0.44 and
a tenth beyond 0.75, and the 17 shown raises 0.08, 0.16 and (two draws)
1.0; exp(-p / scale) has its middle at scale x ln 2, its quarter at
scale x ln 4 and its tenth at scale x ln 10 (0.23, 0.46, 0.76 for 0.33;
0.08, 0.16, 0.26 for 0.115). Shown draws were 8% of the bets (10% of the
ranges were such draws) and 2 of the 13 raises before the river (6%), so a
draw weighs about the average hand of the range. Shown hands lean strong (a
bluff that is not called is not shown), so these read a bettor a little
stronger than he is.
"""

from __future__ import annotations

from bisect import bisect
from dataclasses import replace
from functools import partial
from itertools import accumulate
import math
import random

from phevaluator import evaluate_cards

from poker_engine.solver.texassolver import all_combos

from .bots import _rng
from .postflop_reading import key_of, soft_kept, weights_of
from .reads import MODEL, aggression_factor, factors
from .replay import public_replay
from .solver_bot import MODEL_SALT, kept
from .strength import CARD_ID, DECK, _EVALUATE_7

TRIALS = 4000
CACHE_SIZE = 1000               # actions whose resulting range is kept
FLOOR_FROM = 1.3     # aggression factors up to this are within a short session's noise
FLOOR_SLOPE = 3.0
MAX_FLOOR = 0.5
_KEPT = {}
MAX_DRAWS = 50                  # tries for one deal of hands that do not collide
# A bet weighs each hand exp(-p / scale), p its place by strength (``narrowed``).
BET_SCALE = 0.33
RAISE_SCALE = 0.115             # a raise, or a bet of BIG_BET of the pot or more
DRAW_WEIGHT = 0.25              # a strong draw keeps at least this
BIG_BET = 0.9                   # of the pot before it
_RANK_VALUES = {rank: value for value, rank in enumerate("23456789TJQKA", start=2)}


def _shares(model):
    return MODEL["aa_population" if getattr(model, "adjusted", False) else "population"]


def read_factors(observation, model, seats):
    """{seat: (raise factor, call factor)} from the reads on each seat."""
    reads = observation.get("reads") or {}
    return {seat: factors(reads.get(str(seat)), _shares(model)) for seat in seats}


def floor(aggression):
    """Share of the hands the model would not play that way that a seat
    betting ``aggression`` times as often as the model keeps after the flop."""
    if aggression is None:
        return 0.0
    return min(MAX_FLOOR, max(0.0, FLOOR_SLOPE * (aggression - FLOOR_FROM)))


def read_floors(observation, model, seats):
    """{seat: ``floor``} from the postflop part of the reads on each seat."""
    reads = observation.get("reads") or {}
    return {seat: floor(aggression_factor(reads.get(str(seat)), _shares(model)))
            for seat in seats}


def strong_draw(hole, board):
    """Whether ``hole`` holds a flush draw or an open-ended straight draw
    (two ranks that make a straight with one of its cards) on the flop or
    the turn, without a straight or a flush yet."""
    if len(board) not in (3, 4):
        return False
    cards = list(hole) + list(board)
    for suit in "cdhs":
        mine = sum(card[1] == suit for card in hole)
        if mine and sum(card[1] == suit for card in cards) == 4:
            return True
    ranks = {_RANK_VALUES[card[0]] for card in cards}
    own = {_RANK_VALUES[card[0]] for card in hole}
    ranks |= {1} if 14 in ranks else set()
    own |= {1} if 14 in own else set()

    def straight(have):
        return any(all(low + step in have for step in range(5))
                   and own & set(range(low, low + 5)) for low in range(1, 11))
    if straight(ranks):
        return False
    makes = sum(straight(ranks | {rank} | ({1} if rank == 14 else set()))
                for rank in range(2, 15) if rank not in ranks)
    return makes >= 2


def narrowed(weights, base, board, scale):
    """``weights`` (part of ``base``) after a bet on ``board``: each hand's
    weight times exp(-p / ``scale``), p its place in the ``base`` range by the hand it
    makes with the board (the share of ``base`` that makes a stronger one,
    and half of an equal one); a strong draw (``strong_draw``) at least
    ``DRAW_WEIGHT`` of its weight."""
    ranks = {key: evaluate_cards(key[:2], key[2:], *board) for key in base
             if key[:2] not in board and key[2:] not in board}
    total = sum(base[key] for key in ranks)
    if not total:
        return weights
    order = sorted(ranks, key=ranks.get)
    place, above, start = {}, 0.0, 0
    while start < len(order):
        end = start
        while end < len(order) and ranks[order[end]] == ranks[order[start]]:
            end += 1
        group = sum(base[key] for key in order[start:end])
        place[ranks[order[start]]] = (above + group / 2) / total
        above += group
        start = end
    result = {}
    for key, weight in weights.items():
        if key[:2] in board or key[2:] in board:
            continue
        keep = math.exp(-place[ranks[key]] / scale)
        if strong_draw((key[:2], key[2:]), board):
            keep = max(keep, DRAW_WEIGHT)
        result[key] = weight * keep
    return result


def _decide(model, observation):
    return model.decide(observation, _rng(MODEL_SALT, observation))


def _without(weights, cards):
    return {combo: weight for combo, weight in weights.items()
            if combo[:2] not in cards and combo[2:] not in cards}


def opponent_ranges(observation, model, *, cache=None, trace=None):
    """{seat: {combo key: weight}} for each opponent still in the hand.

    ``cache``: where each action's reading is kept (default: the one shared
    by every reading in the process). ``trace(decision, weights)`` is called
    after each of an opponent's actions with the range it leaves
    (``exclusion``).
    """
    kept_ranges = _KEPT if cache is None else cache
    me = observation["observing_seat"]
    seats = [seat for seat in observation["occupied_seats"]
             if seat not in observation["folded"] and seat != me]
    every = {key: 1.0 for key in all_combos()}
    ranges = dict.fromkeys(seats, every)
    reads = read_factors(observation, model, seats)
    floors = read_floors(observation, model, seats)
    # The reader's (slow play, bluff) before the flop and its weights after it
    # are part of the key: two readings of the same line must not share a range.
    postflop = weights_of(model)
    table = (type(model).__name__, getattr(model, "adjusted", None),
             getattr(model, "reading", None), key_of(postflop),
             observation.get("rules_fingerprint"), tuple(observation["occupied_seats"]),
             observation["dealer_seat"], observation.get("bomb_pot"),
             tuple(sorted(observation["starting_stacks"].items())))
    for index, decision in enumerate(public_replay(observation)):
        if decision.seat not in ranges:
            continue
        read = reads[decision.seat]
        board = tuple(decision.observation["board"])
        key = (table, read, floors[decision.seat], board,
               tuple(row["id"] for row in observation["public_history"][:index + 1]))
        after = kept_ranges.get(key)
        if after is None:
            # Only the board at the action, which the key holds, may cut the
            # range kept for it: the same action line comes up in other hands
            # and on later streets, with other cards dealt since.
            before = _without(ranges[decision.seat], board)
            if read != (1.0, 1.0):
                decision = replace(decision, observation={
                    **decision.observation, "read_factors": read})
            if decision.street == "preflop":
                after = kept(before, decision, partial(_decide, model)) or before
            else:
                after = soft_kept(before, decision, partial(_decide, model),
                                  postflop) or before
            kept_share = floors[decision.seat] if decision.street != "preflop" else 0.0
            if kept_share:
                after = {combo: max(after.get(combo, 0.0), kept_share * weight)
                         for combo, weight in before.items()}
            if len(kept_ranges) >= CACHE_SIZE:
                kept_ranges.clear()
            kept_ranges[key] = after
        ranges[decision.seat] = after
        if trace is not None:
            trace(decision, after)
    dealt = set(observation["board"])
    return {seat: _without(weights, dealt) for seat, weights in ranges.items()}


class _Range:
    """One opponent's hands as card numbers, for weighted draws."""

    def __init__(self, weights, dead):
        self.hands = []
        for key, weight in weights.items():
            a, b = key[:2], key[2:]
            if weight > 0 and a not in dead and b not in dead:
                self.hands.append(((CARD_ID[a], CARD_ID[b]), weight))
        self.totals = list(accumulate(weight for _, weight in self.hands))

    def draw(self, rng):
        return self.hands[bisect(self.totals, rng.random() * self.totals[-1])][0]


def ranges_equity(hero, board, ranges, *, trials=TRIALS, seed=0, pots=None):
    """(share of the pot you win, hands left per opponent) against ``ranges``.

    ``pots``: [(chips, seats)] when the pot is split into a main pot and side
    pots (``side_pots.pots``): your share of each is against the seats that
    can win it, and the share returned is of all their chips together. By
    default one pot against everyone.

    Returns (None, counts) when an opponent has no hand left, or when the
    ranges cannot be dealt together without sharing cards.
    """
    dead = set(hero) | set(board)
    parts = {seat: _Range(weights, dead) for seat, weights in ranges.items()}
    counts = {seat: len(part.hands) for seat, part in parts.items()}
    if not parts or not all(counts.values()):
        return None, counts
    order = list(parts)
    if pots is None:
        pots = [(1.0, order)]
    total = sum(chips for chips, _ in pots)
    # Each pot as (its part of the chips, the places in ``order`` of the seats
    # that can win it); one pot against everyone weighs exactly 1.
    split = [(chips / total, [order.index(seat) for seat in seats if seat in parts])
             for chips, seats in pots]
    rng = random.Random(seed)
    first, second = (CARD_ID[card] for card in hero)
    known = [CARD_ID[card] for card in board]
    deck = [CARD_ID[card] for card in DECK if card not in dead]
    need = 5 - len(board)
    won = dealt = 0.0
    for _ in range(trials):
        for _ in range(MAX_DRAWS):
            hands = [part.draw(rng) for part in parts.values()]
            used = {card for hand in hands for card in hand}
            if len(used) == 2 * len(hands):
                break
        else:
            continue
        rest = rng.sample([card for card in deck if card not in used], need)
        full = (*known, *rest)
        mine = _EVALUATE_7(first, second, *full)
        ranks = [_EVALUATE_7(x, y, *full) for x, y in hands]
        for weight, seats in split:
            won += weight * _won(mine, [ranks[place] for place in seats])
        dealt += 1
    if dealt < trials / 2:
        return None, counts
    return won / dealt, counts


def _won(mine, ranks):
    """Your share of one pot against the hands ``ranks`` (lower is better)."""
    if not ranks:
        return 1.0
    best = min(ranks)
    if mine < best:
        return 1.0
    if mine == best:
        return 1.0 / (1 + ranks.count(mine))
    return 0.0


__all__ = ["BET_SCALE", "BIG_BET", "DRAW_WEIGHT", "FLOOR_FROM", "FLOOR_SLOPE",
           "MAX_FLOOR", "RAISE_SCALE", "TRIALS", "floor", "narrowed",
           "opponent_ranges", "ranges_equity", "read_factors", "strong_draw"]
