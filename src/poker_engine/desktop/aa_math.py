"""Live table math for one AA reader payload: equity, pot odds and SPR.

Every figure states its basis. A missing, partial or unconfirmed input gives
an explicit ``reason`` instead of a guessed number. Equity is against
uniformly random opponent hands: a baseline, not a range read or advice.
"""

from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from poker_engine.core.value_objects import Card, Rank, Suit
from poker_engine.equity.backend import select_evaluator
from poker_engine.realtime.equity import uniform_random_equity

HERO_SLOT = "4"
SLOTS = tuple(str(slot) for slot in range(8))
IN_HAND = frozenset({"active", "all_in"})
KNOWN_STATES = IN_HAND | {"folded", "empty", "waiting"}
EQUITY_TRIALS = 2000


def _unavailable(reason):
    return {"available": False, "reason": reason}


def _card(text):
    try:
        return Card(rank=Rank(text[0].upper()), suit=Suit(text[1].lower()))
    except (TypeError, IndexError, ValueError):
        return None


def _amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _hero_and_board(payload):
    cards = payload.get("cards") or {}
    hero = [_card(text) for text in cards.get("hero") or () if text]
    if len(hero) != 2 or None in hero:
        return None, None, "hero_cards_unknown"
    slots = list(cards.get("board_slots") or [None] * 5)
    shown = [text for text in slots if text]
    if slots[:len(shown)] != shown or len(shown) not in (0, 3, 4, 5):
        return None, None, "board_incomplete"
    board = [_card(text) for text in shown]
    if None in board or len({*hero, *board}) != len(hero) + len(board):
        return None, None, "cards_inconsistent"
    return tuple(hero), tuple(board), None


def _participants(payload):
    """Seat -> state for all eight seats, or None when any seat is unknown."""
    raw = (payload.get("observed_state_v2") or {}).get("participants") or {}
    states = {}
    for slot in SLOTS:
        state = (raw.get(slot) or {}).get("state")
        if state not in KNOWN_STATES:
            return None
        states[slot] = state
    return states


def _opponents(states):
    return [slot for slot, state in states.items()
            if slot != HERO_SLOT and state in IN_HAND]


class AATableMath:
    """Compute table math for successive payloads, caching equity results."""

    def __init__(self, *, trials=EQUITY_TRIALS, cache_size=64):
        self._trials = trials
        self._evaluate, self.evaluator = select_evaluator("auto")
        self._cache = OrderedDict()
        self._cache_size = cache_size

    def compute(self, payload):
        states = _participants(payload)
        return {
            "schema_version": 1,
            "equity": self._equity(payload, states),
            "pot_odds": _pot_odds(payload),
            "spr": _spr(payload, states),
        }

    def _equity(self, payload, states):
        hero, board, reason = _hero_and_board(payload)
        if reason:
            return _unavailable(reason)
        if states is None:
            return _unavailable("participants_unknown")
        if states[HERO_SLOT] not in IN_HAND:
            return _unavailable("hero_not_in_hand")
        count = len(_opponents(states))
        if count == 0:
            return _unavailable("no_opponents")
        key = (tuple(sorted(map(str, hero))), tuple(sorted(map(str, board))), count)
        if key not in self._cache:
            self._cache[key] = uniform_random_equity(
                hero, board, count, trials=self._trials, seed=0,
                evaluate=self._evaluate)
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        self._cache.move_to_end(key)
        snapshot = self._cache[key]
        return {"available": True, "value": snapshot.expected_share,
                "win": snapshot.win_rate, "tie": snapshot.tie_rate,
                "opponents": count, "samples": snapshot.samples,
                "standard_error": snapshot.standard_error,
                "basis": "uniform_random_opponents"}


def _pot_odds(payload):
    controls = payload.get("hero_controls_v1") or {}
    if not controls.get("visible"):
        return _unavailable("not_hero_turn")
    call = _amount(controls.get("call_amount"))
    if call is None:
        return _unavailable("call_amount_unknown")
    pot = _amount((payload.get("pot") or {}).get("value"))
    if pot is None:
        return _unavailable("pot_unknown")
    if call == 0:
        return _unavailable("nothing_to_call")
    return {"available": True, "call": str(call), "pot": str(pot),
            "required_equity": float(call / (pot + call)),
            "ratio": float(pot / call), "basis": "displayed_pot_and_call"}


def _spr(payload, states):
    pot = _amount((payload.get("pot") or {}).get("value"))
    if pot is None or pot == 0:
        return _unavailable("pot_unknown")
    if states is None:
        return _unavailable("participants_unknown")
    stacks = payload.get("stacks") or {}
    hero = _amount((stacks.get(HERO_SLOT) or {}).get("value"))
    if states[HERO_SLOT] not in IN_HAND or hero is None:
        return _unavailable("hero_stack_unknown")
    others = [_amount((stacks.get(slot) or {}).get("value"))
              for slot in _opponents(states)]
    if not others:
        return _unavailable("no_opponents")
    if None in others:
        return _unavailable("opponent_stack_unknown")
    effective = min(hero, max(others))
    return {"available": True, "value": float(effective / pot),
            "effective_stack": str(effective), "pot": str(pot),
            "basis": "displayed_stacks_and_pot"}


__all__ = ["AATableMath", "HERO_SLOT"]
