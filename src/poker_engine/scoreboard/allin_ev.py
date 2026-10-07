"""All-in EV: score a hand by its expected result when the board runs out.

When betting closes with two or more players and board cards still to come
(an all-in), the remaining cards change who wins but nobody decides anything
more. Replacing the actual runout with the average over every possible
runout removes that luck without biasing the result. One or two cards to
come are enumerated exactly; a preflop all-in averages over sampled boards.

Rake is taken as the arena takes it: the configured share of the contested
pot (what is left after uncalled chips go back), out of each pot in
proportion to its size, from that pot's winners.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from itertools import combinations
import random

from poker_engine.strategy.aa_rules_v2 import estimate_rake

from .strength import _EVALUATE_7, CARD_ID, DECK

SHOWN = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}
RUNOUT_SAMPLES = 2000


def settle(contributions, ranks, rake_share=0.0):
    """Net result per player for one runout; ``ranks`` covers players in the hand.

    Pots are built in layers of equal contribution, as the arena does: a layer
    only one player paid into goes back to that player, every other layer is
    split between the best hands among the players still in it, less
    ``rake_share`` of it.
    """
    credits = [0.0] * len(contributions)
    prior = 0.0
    for threshold in sorted(set(contributions)):
        payers = [i for i, value in enumerate(contributions) if value >= threshold]
        amount = (threshold - prior) * len(payers)
        prior = threshold
        if not amount:
            continue
        if len(payers) == 1:
            credits[payers[0]] += amount
            continue
        eligible = [i for i in payers if i in ranks]
        if not eligible:
            raise ValueError("pot has no player still in the hand")
        best = min(ranks[i] for i in eligible)
        winners = [i for i in eligible if ranks[i] == best]
        for i in winners:
            credits[i] += amount * (1 - rake_share) / len(winners)
    return [credits[i] - contributions[i] for i in range(len(contributions))]


def runout_ev(arena, *, samples=RUNOUT_SAMPLES, seed=0):
    """Expected return per seat (chips) for an all-in runout, else None."""
    if not arena.terminal:
        raise ValueError("hand is not finished")
    seats, history = arena._seats, arena._history
    alive = [i for i, seat in enumerate(seats) if seat not in arena._folded]
    if len(alive) < 2 or not history:
        return None
    board = [repr(card) for row in arena._state.board_cards for card in row]
    shown = SHOWN[history[-1]["street"]]
    if shown >= len(board):
        return None
    known = board[:shown]
    holes = [[repr(card) for card in hole] for hole in arena._holes]
    dead = {card for hole in holes for card in hole} | set(known)
    deck = [CARD_ID[card] for card in DECK if card not in dead]
    need = 5 - shown
    if need <= 2:
        runouts = list(combinations(deck, need))
    else:
        rng = random.Random(seed)
        runouts = [rng.sample(deck, need) for _ in range(samples)]
    contributions = [float(value) for value in arena._contributions]
    rake_share = _rake_share(arena.rules, arena._contributions)
    totals = [0.0] * len(seats)
    known = [CARD_ID[card] for card in known]
    hole_ids = [[CARD_ID[card] for card in hole] for hole in holes]
    for extra in runouts:
        full = known + list(extra)
        ranks = {i: _EVALUATE_7(*hole_ids[i], *full) for i in alive}
        for i, value in enumerate(settle(contributions, ranks, rake_share)):
            totals[i] += value
    unit = float(arena.rules.minimum_chip)
    return {seat: totals[i] / len(runouts) * unit for i, seat in enumerate(seats)}


def _rake_share(rules, contributions):
    """Rake as a share of the contested pot (the same on every runout)."""
    if not rules.rake_percent:
        return 0.0
    ordered = sorted(Fraction(value) for value in contributions)
    # Everything but the largest contribution's excess over the second largest
    # is contested; that excess is uncalled and goes back.
    pot = sum(ordered) - (ordered[-1] - ordered[-2])
    if not pot:
        return 0.0
    chips = pot * Fraction(rules.minimum_chip)
    rake = estimate_rake(rules, str(Decimal(chips.numerator) / chips.denominator),
                         saw_flop=True).amount
    return float(Fraction(rake) / chips)


__all__ = ["RUNOUT_SAMPLES", "runout_ev", "settle"]
