"""Pluggable equity strategies for the realtime pipeline.

The realtime layer needs "hero vs random opponent range" equity. Two strategies:

  - :class:`MonteCarloRandomRangeEquity` — fast Monte Carlo over the random
    range (default for realtime; bounded latency).
  - :class:`ExactRandomRangeEquity` — exact enumeration over the random range
    (slower; used to self-check that Monte Carlo converges to the exact value).

The exact enumeration can also take an explicit opponent range (the Task 9
range-equity capability), which is the bridge to the future opponent model.
"""

from __future__ import annotations

from itertools import combinations
from collections import OrderedDict
import math
import random
from typing import Protocol

from poker_engine.core.enums import PlayerStatus
from poker_engine.core.state import PokerState
from poker_engine.equity._deck import remaining_deck
from poker_engine.equity.backend import select_evaluator
from poker_engine.equity.range import enumeration_range_equity
from poker_engine.core.value_objects import Card

from .analysis import EquitySnapshot


class EquityStrategy(Protocol):
    """Compute a hero equity snapshot from a canonical state."""

    def compute(self, state: PokerState) -> EquitySnapshot:
        ...


def _random_range(state: PokerState) -> tuple[tuple[Card, Card], ...]:
    """All distinct two-card holdings not in hero/board (the random range)."""
    hero = tuple(state.hero_cards)
    board = tuple(state.board_cards)
    used = set(hero) | set(board)
    deck = remaining_deck(tuple(used))
    return tuple(combinations(deck, 2))


class MonteCarloRandomRangeEquity:
    """Showdown equity against every active opponent, with uniform ranges.

    Uniform ranges are an explicit baseline, not action-conditioned strategy
    or rake/side-pot EV. Deal all unknown cards without replacement so a
    multiway trial never needs collision rejection. Reuse identical queries
    with a bounded cache; all runs use the same fixed trial count and seed.
    """

    def __init__(self, trials: int = 2000, seed: int = 0,
                 evaluator: str = "auto") -> None:
        if isinstance(trials, bool) or not isinstance(trials, int) or trials <= 0:
            raise ValueError("trials must be a positive integer")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an integer")
        self._trials = trials
        self._seed = seed
        self._evaluate, self.evaluator_backend = select_evaluator(evaluator)
        self._cache: OrderedDict[tuple, EquitySnapshot] = OrderedDict()

    def compute(self, state: PokerState) -> EquitySnapshot:
        hero = tuple(state.hero_cards)
        board = tuple(state.board_cards)
        count, reason = _opponent_count(state)
        if reason is not None:
            return _unavailable(reason, count)
        key = (tuple(sorted(hero)), tuple(sorted(board)), count)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        result = uniform_random_equity(hero, board, count, trials=self._trials,
                                       seed=self._seed, evaluate=self._evaluate)
        self._cache[key] = result
        if len(self._cache) > 128:
            self._cache.popitem(last=False)
        return result


def uniform_random_equity(hero, board, opponent_count, *, trials=2000, seed=0,
                          evaluate=None) -> EquitySnapshot:
    """Seeded Monte Carlo hero equity against uniformly random opponent hands.

    Deals all unknown cards without replacement. ``hero`` is two cards,
    ``board`` 0/3/4/5 cards and ``opponent_count`` the number of opponents
    still holding cards.
    """
    hero, board = tuple(hero), tuple(board)
    if evaluate is None:
        evaluate, _ = select_evaluator("auto")
    deck = remaining_deck(hero + board)
    rng = random.Random(seed)
    need = 5 - len(board)
    wins = ties = 0
    shares = squares = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need + 2 * opponent_count)
        full_board = board + tuple(draw[:need])
        hero_value = evaluate(hero + full_board)
        tied = 0
        lost = False
        for opponent in range(opponent_count):
            offset = need + 2 * opponent
            value = evaluate(tuple(draw[offset:offset + 2]) + full_board)
            if value > hero_value:
                lost = True
                break
            tied += value == hero_value
        share = 0.0
        if not lost:
            wins += tied == 0
            ties += tied > 0
            share = 1.0 / (tied + 1)
        shares += share
        squares += share * share
    mean = shares / trials
    error = None
    if trials > 1:
        variance = max(0.0, (squares - shares * mean) / (trials - 1))
        error = math.sqrt(variance / trials)
    return EquitySnapshot(
        win_rate=wins / trials, tie_rate=ties / trials,
        opponent_count=opponent_count, samples=trials,
        expected_share=mean, standard_error=error,
        basis="uniform_random_active_opponents",
    )


class ExactRandomRangeEquity:
    """Hero equity vs a random opponent range, via exact enumeration.

    Slower than Monte Carlo; use to verify convergence / for offline analysis.
    May be expensive on the flop (large random range x board completions).
    """

    def compute(self, state: PokerState) -> EquitySnapshot:
        hero = tuple(state.hero_cards)
        board = tuple(state.board_cards)
        count, reason = _opponent_count(state)
        if reason is not None:
            return _unavailable(reason, count)
        if count != 1:
            return _unavailable("exact_random_equity_requires_heads_up", count)
        rng = _random_range(state)
        res = enumeration_range_equity(hero, (rng,), board)
        return EquitySnapshot(
            win_rate=res.win, tie_rate=res.tie, expected_share=res.equity,
            opponent_count=count, samples=res.samples, standard_error=0.0,
            basis="uniform_random_active_opponents",
        )


def _unavailable(reason: str, count: int | None = None) -> EquitySnapshot:
    return EquitySnapshot(
        0.0, 0.0, opponent_count=count,
        basis="uniform_random_active_opponents", unavailable_reason=reason,
    )


def _opponent_count(state: PokerState) -> tuple[int | None, str | None]:
    if len(state.hero_cards) != 2:
        return None, "hero_cards_unavailable"
    if len(state.board_cards) != {"preflop": 0, "flop": 3, "turn": 4,
                                  "river": 5}.get(state.street.value):
        return None, "board_street_mismatch"
    cards = tuple(state.hero_cards) + tuple(state.board_cards)
    if len(set(cards)) != len(cards):
        return None, "card_conflict"
    live_statuses = (PlayerStatus.ACTIVE, PlayerStatus.ALL_IN)
    if any(p.status is PlayerStatus.UNKNOWN or
           (p.status in live_statuses and not p.has_cards) for p in state.players):
        return None, "player_status_unavailable"
    active = tuple(
        p for p in state.players if p.status in live_statuses and p.has_cards
    )
    if not any(p.is_hero for p in active):
        return None, "hero_not_in_hand"
    count = len(active) - 1
    if count < 1:
        return 0, "waiting_for_active_players"
    return count, None


__all__ = [
    "EquityStrategy",
    "MonteCarloRandomRangeEquity",
    "ExactRandomRangeEquity",
]
