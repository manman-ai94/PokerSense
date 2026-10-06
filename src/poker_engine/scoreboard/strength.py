"""Hand strength for scoreboard bots: preflop rank and Monte Carlo equity.

Cards are two-character strings such as "Ah" and "7c", as the arena shows
them. Evaluation uses phevaluator, where a lower rank is a stronger hand.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
import json

from phevaluator import evaluate_cards

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)
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


def equity(hero, board, opponents, trials, rng):
    """Share of the pot won against ``opponents`` random hands (Monte Carlo)."""
    if opponents < 1:
        return 1.0
    dead = set(hero) | set(board)
    deck = [card for card in DECK if card not in dead]
    need = 5 - len(board)
    won = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need + 2 * opponents)
        full = list(board) + draw[:need]
        mine = evaluate_cards(*hero, *full)
        ranks = [evaluate_cards(draw[need + 2 * k], draw[need + 2 * k + 1], *full)
                 for k in range(opponents)]
        best = min(ranks)
        if mine < best:
            won += 1.0
        elif mine == best:
            won += 1.0 / (1 + ranks.count(mine))
    return won / trials


__all__ = ["DECK", "all_classes", "class_combos", "equity", "hand_class",
           "preflop_percentile", "preflop_table"]
