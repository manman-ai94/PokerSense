"""Every opponent's range from the hand's public actions, and equity against them.

Without a solver (the flop, and pots with more than one opponent) each
opponent still in is read the way the solver strategy reads its heads-up
opponent: start from every two cards the board leaves and keep, at each of
their past actions, the hands the population model plays that way
(``solver_bot.kept``). An action the model would never take with any hand
leaves that range as it was. Your share of the pot against those ranges is
then worked out by dealing each opponent a hand from their range (weighted,
without sharing cards) and the rest of the board, many times over.

Reading an action asks the model about every hand, so a hand with many
actions (a bomb pot, where everyone sees the flop) took seconds per decision
when every decision read the whole hand again. The range each action leaves
its player with depends only on the public hand up to it, so it is kept
(``CACHE_SIZE`` actions) and a later decision of the same hand reads only the
new actions; hands that the board dealt since then are dropped.

The model's players are the AA population. With reads on the opponents
(``observation["reads"]``, see ``reads``) each seat is read as the player
the reads show, not the average one, in two ways:

* before the flop the model plays the seat's first decision with its raise
  and call shares scaled by the reads (``read_factors``), as ``aa_preflop``
  expects it to, so a seat that raises twice as often raises with a range
  twice as wide;
* after the flop a seat that raises clearly more often than the model keeps,
  at each action, ``FLOOR_SLOPE`` x (its raise factor - ``FLOOR_FROM``), at
  most ``MAX_FLOOR``, of the weight of the hands the model would not have
  played that way: such players bet more than the population's thresholds
  say. Below ``FLOOR_FROM`` the difference can be the noise of a short
  session (on an AA table, reads from 100 hands put a fifth of the seats
  above 1.2 by chance), and the AA tables lost by it.

Without reads, or for a seat that plays like the model, nothing changes.
Against reg and maniac tables the AI folded to flop bets with hands that had
the price (23% and 48% of its folds), and in bomb pots far more.
"""

from __future__ import annotations

from bisect import bisect
from dataclasses import replace
from itertools import accumulate
import random

from poker_engine.solver.texassolver import all_combos

from .bots import _rng
from .reads import MODEL, factors
from .replay import public_replay
from .solver_bot import MODEL_SALT, kept
from .strength import CARD_ID, DECK, _EVALUATE_7

TRIALS = 4000
CACHE_SIZE = 1000               # actions whose resulting range is kept
FLOOR_FROM = 1.2     # raise factors up to this are within the noise of 100 hands
FLOOR_SLOPE = 1.5
MAX_FLOOR = 0.5
_KEPT = {}
MAX_DRAWS = 50                  # tries for one deal of hands that do not collide


def read_factors(observation, model, seats):
    """{seat: (raise factor, call factor)} from the reads on each seat."""
    reads = observation.get("reads") or {}
    shares = MODEL["aa_population" if getattr(model, "adjusted", False)
                   else "population"]
    return {seat: factors(reads.get(str(seat)), shares) for seat in seats}


def floor(read):
    """Share of the hands the model would not play that way that a seat
    with these read factors keeps after the flop."""
    return min(MAX_FLOOR, max(0.0, FLOOR_SLOPE * (read[0] - FLOOR_FROM)))


def opponent_ranges(observation, model):
    """{seat: {combo key: weight}} for each opponent still in the hand."""
    me = observation["observing_seat"]
    board = tuple(observation["board"])
    seats = [seat for seat in observation["occupied_seats"]
             if seat not in observation["folded"] and seat != me]
    ranges = {seat: {key: 1.0 for key in all_combos(board)} for seat in seats}
    dealt = set(board)
    reads = read_factors(observation, model, seats)
    table = (type(model).__name__, getattr(model, "adjusted", None),
             observation.get("rules_fingerprint"), tuple(observation["occupied_seats"]),
             observation["dealer_seat"], observation.get("bomb_pot"),
             tuple(sorted(observation["starting_stacks"].items())))
    for index, decision in enumerate(public_replay(observation)):
        if decision.seat not in ranges:
            continue
        read = reads[decision.seat]
        key = (table, read, tuple(decision.observation["board"]),
               tuple(row["id"] for row in observation["public_history"][:index + 1]))
        if key in _KEPT:
            ranges[decision.seat] = {
                combo: weight for combo, weight in _KEPT[key].items()
                if combo[:2] not in dealt and combo[2:] not in dealt}
            continue
        before = ranges[decision.seat]
        if read != (1.0, 1.0):
            decision = replace(decision, observation={
                **decision.observation, "read_factors": read})
        after = kept(before, decision, lambda obs: model.decide(
            obs, _rng(MODEL_SALT, obs))) or before
        kept_share = floor(read) if decision.street != "preflop" else 0.0
        if kept_share:
            after = {combo: max(after.get(combo, 0.0), kept_share * weight)
                     for combo, weight in before.items()}
        ranges[decision.seat] = after
        if len(_KEPT) >= CACHE_SIZE:
            _KEPT.clear()
        _KEPT[key] = ranges[decision.seat]
    return ranges


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


def ranges_equity(hero, board, ranges, *, trials=TRIALS, seed=0):
    """(share of the pot you win, hands left per opponent) against ``ranges``.

    Returns (None, counts) when an opponent has no hand left, or when the
    ranges cannot be dealt together without sharing cards.
    """
    dead = set(hero) | set(board)
    parts = {seat: _Range(weights, dead) for seat, weights in ranges.items()}
    counts = {seat: len(part.hands) for seat, part in parts.items()}
    if not parts or not all(counts.values()):
        return None, counts
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
        best = min(ranks)
        if mine < best:
            won += 1.0
        elif mine == best:
            won += 1.0 / (1 + ranks.count(mine))
        dealt += 1
    if dealt < trials / 2:
        return None, counts
    return won / dealt, counts


__all__ = ["FLOOR_FROM", "FLOOR_SLOPE", "MAX_FLOOR", "TRIALS", "floor",
           "opponent_ranges", "ranges_equity", "read_factors"]
