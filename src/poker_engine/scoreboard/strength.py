"""Hand strength for scoreboard bots: preflop rank and Monte Carlo equity.

Cards are two-character strings such as "Ah" and "7c", as the arena shows
them. Evaluation uses phevaluator, where a lower rank is a stronger hand.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from itertools import combinations
import json

from phevaluator import _pheval

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)
# phevaluator numbers cards rank * 4 + suit, the order of DECK. Monte Carlo
# equity calls its native 7-card evaluator with these numbers directly; going
# through ``evaluate_cards`` with card names spent most of the time parsing.
CARD_ID = {card: index for index, card in enumerate(DECK)}
_EVALUATE_7 = _pheval.evaluate_7cards
TABLE_NAME = "preflop_strength_v1.json"


def hand_class(cards):
    """"AKs", "AKo" or "QQ" for two hole cards."""
    first, second = cards
    if first[0] == second[0]:
        return first[0] + second[0]
    high, low = sorted((first[0], second[0]), key=RANKS.index, reverse=True)
    return high + low + ("s" if first[1] == second[1] else "o")


def class_combos(name):
    return 6 if len(name) == 2 else 4 if name.endswith("s") else 12


def all_classes():
    names = []
    for high in range(len(RANKS) - 1, -1, -1):
        names.append(RANKS[high] * 2)
        for low in range(high - 1, -1, -1):
            names += [RANKS[high] + RANKS[low] + "s", RANKS[high] + RANKS[low] + "o"]
    return names


@lru_cache(maxsize=1)
def preflop_table():
    data = resources.files("poker_engine.scoreboard").joinpath(TABLE_NAME)
    return json.loads(data.read_text(encoding="utf-8"))


def preflop_percentile(cards):
    """Share of all starting hands (by combinations) at least this strong.

    0.0045 for aces (the 6 best combinations of 1326); a bot that plays its
    top 15% plays every hand whose percentile is at most 0.15.
    """
    return preflop_table()["classes"][hand_class(cards)]["percentile"]


def combo_percentile(cards):
    """Like ``preflop_percentile``, but spread over the combinations of the class.

    The combinations of a class (6 for a pair, 4 suited, 12 offsuit) take
    evenly spaced places inside the class's share, so a cut that falls inside
    a class plays part of it rather than all or none of it.
    """
    name = hand_class(cards)
    high, low = sorted(cards, key=lambda card: (RANKS.index(card[0]),
                                                SUITS.index(card[1])), reverse=True)
    first, second = SUITS.index(high[1]), SUITS.index(low[1])
    if len(name) == 2:
        index = list(combinations(range(4), 2)).index((second, first))
    elif name.endswith("s"):
        index = first
    else:
        index = first * 3 + (second if second < first else second - 1)
    combos = class_combos(name)
    return preflop_percentile(cards) - (combos - index - 0.5) / 1326


def equity(hero, board, opponents, trials, rng):
    """Share of the pot won against ``opponents`` random hands (Monte Carlo)."""
    if opponents < 1:
        return 1.0
    dead = set(hero) | set(board)
    deck = [CARD_ID[card] for card in DECK if card not in dead]
    need = 5 - len(board)
    known = [CARD_ID[card] for card in board]
    first, second = (CARD_ID[card] for card in hero)
    won = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need + 2 * opponents)
        full = known + draw[:need]
        mine = _EVALUATE_7(first, second, *full)
        ranks = [_EVALUATE_7(draw[need + 2 * k], draw[need + 2 * k + 1], *full)
                 for k in range(opponents)]
        best = min(ranks)
        if mine < best:
            won += 1.0
        elif mine == best:
            won += 1.0 / (1 + ranks.count(mine))
    return won / trials


def range_equity(hero, board, weights):
    """Exact share of the pot won against one opponent's weighted range.

    ``weights`` is {"AhKd": weight} as the solver keeps ranges. Hands that
    use one of your cards or a board card are left out; on the turn every
    river card the two hands leave is dealt. Returns (equity, hands counted),
    or (None, 0) when no hand of the range is left.
    """
    if len(board) not in (4, 5):
        raise ValueError("range equity is worked out on the turn or the river")
    dead = set(hero) | set(board)
    first, second = (CARD_ID[card] for card in hero)
    known = [CARD_ID[card] for card in board]
    rivers = [None] if len(board) == 5 else [CARD_ID[card] for card in DECK
                                             if card not in dead]

    def dealt(river):
        return known if river is None else (*known, river)

    mine = {river: _EVALUATE_7(first, second, *dealt(river)) for river in rivers}
    won = total = 0.0
    hands = 0
    for key, weight in weights.items():
        a, b = key[:2], key[2:]
        if weight <= 0 or a in dead or b in dead:
            continue
        x, y = CARD_ID[a], CARD_ID[b]
        share = count = 0
        for river in rivers:
            if river == x or river == y:
                continue
            his = _EVALUATE_7(x, y, *dealt(river))
            share += 2 if mine[river] < his else 1 if mine[river] == his else 0
            count += 1
        won += weight * share / (2 * count)
        total += weight
        hands += 1
    return (won / total, hands) if total else (None, 0)


__all__ = ["DECK", "all_classes", "class_combos", "equity", "hand_class",
           "preflop_percentile", "preflop_table", "range_equity"]
