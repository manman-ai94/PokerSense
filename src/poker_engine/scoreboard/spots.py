"""Kinds of betting decisions, shared by the PHH statistics and the population bot.

Both sides describe a hand the same way, as the actions so far in order:
``(player, kind)`` with kind ``"f"`` (fold), ``"c"`` (check or call) or ``"r"``
(bet or raise). Blinds, straddles and antes are not actions. Using one
definition keeps "how often real players do X here" and "where the bot is
now" the same thing.
"""

from __future__ import annotations

KINDS = {"fold": "f", "check_call": "c", "raise_to": "r"}


def preflop_spot(actions, me):
    """Kind of preflop decision ``me`` faces after ``actions``.

    A first decision is ``rfi`` (nobody in yet), ``vs_limp``, ``vs_open`` (one
    raise) or ``vs_3bet_cold`` (more). A later one depends on the player's own
    last action: ``limp_vs_raise``, ``call_vs_3bet``, ``open_vs_3bet`` or
    ``3bet_vs_4bet``.
    """
    raises = limpers = 0
    mine = None                    # (kind, raises before it) of my last action
    for player, kind in actions:
        if player == me:
            mine = (kind, raises)
        if kind == "r":
            raises += 1
        elif kind == "c" and raises == 0:
            limpers += 1
    if mine is None:
        if raises == 0:
            return "rfi" if limpers == 0 else "vs_limp"
        return "vs_open" if raises == 1 else "vs_3bet_cold"
    kind, before = mine
    if kind == "c":
        return "limp_vs_raise" if before == 0 else "call_vs_3bet"
    return "open_vs_3bet" if before == 0 else "3bet_vs_4bet"


def postflop_spot(street, actions, me, opponents, aggressor):
    """``street|hu or multi|pfa or other|checked_to, facing_bet or facing_raise``.

    ``actions`` are this street's actions so far, ``opponents`` the players
    still in the hand besides ``me`` and ``aggressor`` the last preflop raiser.
    """
    bets = sum(1 for _, kind in actions if kind == "r")
    facing = ("checked_to", "facing_bet", "facing_raise")[min(bets, 2)]
    width = "hu" if opponents == 1 else "multi"
    role = "pfa" if aggressor == me else "other"
    return f"{street}|{width}|{role}|{facing}"


__all__ = ["KINDS", "postflop_spot", "preflop_spot"]
