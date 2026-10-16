"""Style rules on the heads-up solver's river answer (the style card).

The solver plays a street as an equilibrium: it bluffs at a balanced rate
and, facing a bet, expects the bettor to bluff at one too. The AA players
call a lot (heads-up they fold to a flop bet 42% of the time) and, in the
2009 games the population model comes from, players who were not
aggressive rarely bluffed big river bets: of the hands shown behind a
heads-up river bet of three quarters of the pot or more, 8-9% (passive)
and 15-18% (the rest but the aggressive) were no pair of their own, against
24-27% for the aggressive; behind a river raise 2-6%, against 8-13%
(``tools/phh_showdown_check.py``, 2026-10-15, rerun after a fix). One pair
calling there wins about that share plus part of the pairs: under the 30% a
big bet asks.

Two rules change the solver's river answer, each on its own:

* ``nobluff``: with nothing to call and no pair of your own (``nothing``:
  the board's kind is all you have), its bets become checks: a bluff into
  players who call is lost chips.
* ``nocatch``: facing a big bet (a price of ``BIG_PRICE`` or more of what you
  can win, ``side_pots.price``) or a raise of your bet, with one pair or less
  of your own (``multiway_bot.weak_hand``, top pair included), from an
  opponent not read as aggressive (``aggressive``), its calls and raises
  become a fold.

Both are off unless named (``solver_turn@nobluff@nocatch+...`` on the
scoreboard, ``LIVE`` in the window): the table default changes only on AA
recording or showdown evidence. On the scoreboard (2026-10-15, mixed stacks,
two batches) ``nobluff`` lost 2.4 and 3.6 big blinds a hundred hands on the
AA real-player table, where a river bluff wins the pot often enough.
``nocatch`` fired twice in 32,000 hands: the scoreboard
players bet half the pot on the river, never big, so only recordings can
show what it is worth.
"""

from __future__ import annotations

from phevaluator import evaluate_cards

from .multiway_bot import _board_kind, hand_kind, weak_hand
from .reads import MODEL, aggression_factor
from .side_pots import price

RULES = ("nobluff", "nocatch")
LIVE = frozenset()          # rules the live window applies
BIG_PRICE = 0.30            # a bet of three quarters of the pot asks about this
AGGRESSIVE = 0.40           # bet-or-raise share after the flop of an aggressive read
AGGRESSIVE_ACTIONS = ("BET", "RAISE")


def nothing(hole, board):
    """No pair or better of your own: what you have, the board has (its
    repeated ranks, or a straight or flush it makes by itself, as
    ``multiway_bot.weak_hand`` counts it)."""
    hole, board = list(hole), list(board)
    if hand_kind(hole + board) == _board_kind(board):
        return True
    return len(board) == 5 and evaluate_cards(*board) == evaluate_cards(*hole, *board)


def villain(observation):
    """The one opponent still in, or None."""
    me = observation["observing_seat"]
    live = [seat for seat in observation["occupied_seats"]
            if seat not in observation["folded"] and seat != me]
    return live[0] if len(live) == 1 else None


def aggressive(observation, seat, model=MODEL["aa_population"]):
    """Whether the reads show ``seat`` betting or raising after the flop
    more than ``AGGRESSIVE`` of the time (pulled toward the model's share by
    ``reads.AGGRESSION_PRIOR`` decisions); no read is not aggressive."""
    read = (observation.get("reads") or {}).get(str(seat))
    factor = aggression_factor(read, model)
    return factor is not None and factor * model["aggression"] > AGGRESSIVE


def raised(observation):
    """Whether you face a raise of your own bet on this street."""
    mine = float(observation["bets"].get(str(observation["observing_seat"])) or 0)
    return mine > 0 and float(observation["to_call"] or 0) > 0


def adjust(strategy, observation, rules):
    """(strategy, rule) with ``rules`` applied to the solver's
    {action: probability} for your hand; rule is the one that changed it,
    or None."""
    if not rules or observation["street"] != "river" or villain(observation) is None:
        return strategy, None
    hole, board = observation["own_hole"], observation["board"]
    bets = sum(share for action, share in strategy.items()
               if action.startswith(AGGRESSIVE_ACTIONS))
    if float(observation["to_call"] or 0) <= 0:
        if "nobluff" in rules and bets > 0 and nothing(hole, board):
            checked = {action: share for action, share in strategy.items()
                       if not action.startswith(AGGRESSIVE_ACTIONS)}
            checked["CHECK"] = checked.get("CHECK", 0.0) + bets
            return checked, "nobluff"
        return strategy, None
    if ("nocatch" in rules and strategy.get("FOLD", 0.0) < sum(strategy.values())
            and weak_hand(hole, board)
            and (price(observation) >= BIG_PRICE or raised(observation))
            and not aggressive(observation, villain(observation))):
        return {"FOLD": 1.0}, "nocatch"
    return strategy, None


def rules_of(tokens):
    """The rules named in ``tokens`` (unknown names are an error)."""
    unknown = set(tokens) - set(RULES)
    if unknown:
        raise ValueError(f"unknown style rules {sorted(unknown)}")
    return frozenset(tokens)


__all__ = ["AGGRESSIVE", "BIG_PRICE", "LIVE", "RULES", "adjust", "aggressive",
           "nothing", "raised", "rules_of", "villain"]
