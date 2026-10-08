"""Every opponent's range from the hand's public actions, and equity against them.

Without a solver (the flop, and pots with more than one opponent) each
opponent still in is read the way the solver strategy reads its heads-up
opponent: start from every two cards the board leaves and keep, at each of
their past actions, the hands the population model plays that way
(``solver_bot.kept``). An action the model would never take with any hand
leaves that range as it was. Your share of the pot against those ranges is
then worked out by dealing each opponent a hand from their range (weighted,
without sharing cards) and the rest of the board, many times over.
"""

from __future__ import annotations

from bisect import bisect
from itertools import accumulate
import random

from poker_engine.solver.texassolver import all_combos

from .bots import _rng
from .replay import public_replay
from .solver_bot import MODEL_SALT, kept
from .strength import CARD_ID, DECK, _EVALUATE_7

TRIALS = 4000
MAX_DRAWS = 50                  # tries for one deal of hands that do not collide


def opponent_ranges(observation, model):
    """{seat: {combo key: weight}} for each opponent still in the hand."""
    me = observation["observing_seat"]
    board = tuple(observation["board"])
    seats = [seat for seat in observation["occupied_seats"]
             if seat not in observation["folded"] and seat != me]
    ranges = {seat: {key: 1.0 for key in all_combos(board)} for seat in seats}
    for decision in public_replay(observation):
        if decision.seat in ranges:
            before = ranges[decision.seat]
            ranges[decision.seat] = kept(before, decision, lambda obs: model.decide(
                obs, _rng(MODEL_SALT, obs))) or before
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


__all__ = ["TRIALS", "opponent_ranges", "ranges_equity"]
