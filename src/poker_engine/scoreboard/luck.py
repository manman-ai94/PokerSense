"""Luck taken out of a result: the two cards dealt, and the board run out
after an all-in.

Both are chance: nobody decides them. Taking out each one's luck leaves a
player's expected result exactly where it was, whatever he decides, and
makes his results spread less, so fewer hands tell a winner from a loser.
Nothing a player chooses (his betting, the advice he follows) is corrected:
only what the deck did.

Cards (``hole_luck``): how much more than the average hand at the same seat
these two cards win on the simulated AA table, in big blinds, from the table
``luck_table_v1.json`` (``tools/build_luck_table.py``). Over the 1326 hands
that can be dealt it averages exactly zero at every seat, so subtracting it
changes nothing on average, however the cards are played. How much of the
spread it takes out depends on how closely a player's results follow the
table's (the table's ``check`` says how much it took out on deals it was not
fitted on).

Runout (``runout_luck``): after an all-in with every live hand known, what the
cards that came won or lost against the average over every board that could
have come (the scoreboard scores simulated hands this way, ``allin_ev``). It
averages zero over the boards that could come, so it too changes nothing on
average, provided which hands get it does not depend on the board that came.

Seats count from the small blind as the AA table deals: small blind, big
blind, straddle, then on to the dealer. ``table_position`` maps a table of
4-8 players onto the eight seats of the simulated table: the blinds and
straddle stay, the rest count back from the dealer.

``always_valid`` is a 95% interval that stays right however often it is
looked at (a normal-mixture confidence sequence), so a result checked every
day is not declared too early. It is tightest around ``TUNED`` hands, where it
is about 1.5 times as wide as the plain interval.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from itertools import combinations
import json
import math
import random

from .allin_ev import SHOWN, settle
from .strength import _EVALUATE_7, CARD_ID, DECK, all_classes, class_combos, hand_class

TABLE_NAME = "luck_table_v1.json"
SEATS = 8                   # the simulated table
POSITIONS = ("SB", "BB", "STR", "UTG", "MP", "HJ", "CO", "BTN")
FORCED = 3                  # small blind, big blind, straddle
MIN_PLAYERS, MAX_PLAYERS = 4, 8
RUNOUT_SAMPLES = 2000       # boards drawn when all five cards are to come
ALPHA = 0.05
# Hands where the always-valid interval is tightest. A hand on the AA table
# spreads about 20 big blinds (simulated and real), so a result between
# winning and losing 100 bb/100 takes a few thousand hands to call.
TUNED = 5000
Z95 = 1.959964
COMBOS = sum(class_combos(name) for name in all_classes())     # 1326


def table_position(index, players):
    """Seat on the simulated eight-seat table for ``index`` (0 = small
    blind) at a table of ``players``, or None when the size is not covered."""
    if not MIN_PLAYERS <= players <= MAX_PLAYERS or not 0 <= index < players:
        return None
    return index if index < FORCED else SEATS - (players - index)


def seat_order(seats, dealer):
    """The seats in the order the table deals: small blind first, dealer last
    (as ``AAFullHandArena`` orders them)."""
    seats = sorted(seats)
    at = seats.index(dealer)
    return seats[at + 1:] + seats[:at + 1]


def centered(values):
    """Class values shifted so they average zero over the 1326 hands."""
    mean = sum(class_combos(name) * value for name, value in values.items()) / COMBOS
    return {name: value - mean for name, value in values.items()}


@lru_cache(maxsize=1)
def load_table():
    """The packaged table, its class values centred again (the file rounds
    them, which leaves them a millionth of a big blind off zero)."""
    data = resources.files("poker_engine.scoreboard").joinpath(TABLE_NAME)
    table = json.loads(data.read_text(encoding="utf-8"))
    return {**table, "classes": centered(table["classes"])}


def hole_luck(cards, position, table=None):
    """Big blinds these two cards are worth above the average hand at
    ``position`` (0-7 on the simulated table)."""
    return class_luck(hand_class(cards), position, table)


def class_luck(name, position, table=None):
    """``hole_luck`` for a class of hands ("AKs", "QQ")."""
    table = table or load_table()
    return table["slopes"][position] * table["classes"][name]


def runout_luck(contributions, holes, board, street, rake_share=0.0, *,
                samples=RUNOUT_SAMPLES, seed=0):
    """(actual, expected) net result per player of an all-in's runout, or
    None when nothing was left to come.

    ``contributions``: what each player put in, in one unit; ``holes``:
    {player: two cards} for every player still in (the others folded);
    ``board``: the five cards that came; ``street``: where the betting
    closed. ``expected`` averages over every board that could have come
    (sampled when all five were to come), with the cards still in hands and
    on the board as it stood out of the deck; folded cards are unknown, so
    they could have come.
    """
    shown = SHOWN[street]
    if shown >= 5 or len(holes) < 2:
        return None
    outcomes = runout_outcomes(contributions, holes, board[:shown], rake_share,
                               samples=samples, seed=seed)
    totals = [0.0] * len(contributions)
    for _, results in outcomes:
        for player, value in enumerate(results):
            totals[player] += value
    return (runout_result(contributions, holes, board, rake_share),
            [total / len(outcomes) for total in totals])


def runout_outcomes(contributions, holes, known, rake_share=0.0, *,
                    samples=RUNOUT_SAMPLES, seed=0):
    """[(the cards that came, net result per player)] for every board that
    could have come after ``known`` (the board when the betting closed): the
    boards ``runout_luck`` averages over."""
    dead = set(known) | {card for cards in holes.values() for card in cards}
    deck = [card for card in DECK if card not in dead]
    need = 5 - len(known)
    if need <= 2:
        runouts = list(combinations(deck, need))
    else:
        rng = random.Random(seed)
        runouts = [rng.sample(deck, need) for _ in range(samples)]
    return [(tuple(extra), runout_result(contributions, holes, [*known, *extra],
                                         rake_share))
            for extra in runouts]


def runout_result(contributions, holes, board, rake_share=0.0):
    """Net result per player when ``board`` (five cards) came."""
    ranks = {player: _EVALUATE_7(*(CARD_ID[card] for card in (*cards, *board)))
             for player, cards in holes.items()}
    return settle(contributions, ranks, rake_share)


def interval(values):
    """(mean, half-width of the plain 95% interval), per hand."""
    count = len(values)
    if count < 2:
        return (values[0] if values else None), None
    mean = sum(values) / count
    spread = math.sqrt(sum((v - mean) ** 2 for v in values) / (count - 1))
    return mean, Z95 * spread / math.sqrt(count)


def always_valid(values, alpha=ALPHA, tuned=TUNED):
    """(mean, half-width) of the interval that stays right however often it
    is looked at: the normal mixture (Howard et al. 2021) with the sample
    spread, tightest at ``tuned`` hands."""
    count = len(values)
    if count < 2:
        return (values[0] if values else None), None
    mean = sum(values) / count
    variance = sum((v - mean) ** 2 for v in values) / (count - 1)
    return mean, _half_width(variance, count, alpha, tuned) if variance else 0.0


def _half_width(variance, count, alpha, tuned):
    level = -2 * math.log(alpha)
    rho = tuned * variance / (level + math.log(1 + level))
    spent = count * variance
    return math.sqrt((spent + rho) * (math.log((spent + rho) / rho) + level)) / count


def hands_for(spread, half_width, alpha=ALPHA, tuned=TUNED):
    """Hands the always-valid interval needs to come to ``half_width`` (per
    hand) when each hand spreads ``spread``: the first count where it does."""
    if not spread or half_width <= 0:
        return 0

    def width(count):
        return _half_width(spread ** 2, count, alpha, tuned)

    low, high = 1, 1
    while width(high) > half_width:
        high *= 2
    while low < high:
        middle = (low + high) // 2
        low, high = (middle + 1, high) if width(middle) > half_width else (low, middle)
    return low


__all__ = ["POSITIONS", "TABLE_NAME", "always_valid", "centered", "class_luck",
           "hands_for", "hole_luck", "interval", "load_table", "runout_luck",
           "seat_order", "table_position"]
