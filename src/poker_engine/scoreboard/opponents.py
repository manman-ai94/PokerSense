"""Tougher opponents for the scoreboard: a solid regular, a maniac and a nit.

The AI's results on the scoreboard come from tables of the real-player
population (2009 games, or as loose as AA players before the flop). Real
opponents can play differently; these three test whether the edge holds
against players who do not play like the population:

* ``reg``, a solid regular. Before the flop it never limps: it opens wider
  than the players (their limps become raises), 3-bets twice as often and
  calls a little less. After the flop it bets polarised, value plus bluffs
  at the ratio its two-thirds-pot bet calls for, and heads-up it continues
  against a bet at least as often as the bet size needs to stop bluffs
  (minimum defence).
* ``maniac``: raises two to three times as often before the flop, 3-bets
  four times as often and calls more; after the flop bets and raises far
  more, bluffs as often as it bets for value, bets the pot, rarely folds.
* ``nit``: plays about half as many hands, never limps first in, rarely
  3-bets; bets only strong hands, half the pot, never bluffs and folds more
  to bets.

They use the population bot's machinery with different shares. Before the
flop the 2009 players' raise and call shares at the position and kind of
decision are changed by the profile (``preflop_shares``), and a decision cuts
the range the player's own earlier actions left it, strongest hands raising.
After the flop a share of hands becomes an equity threshold through the
population bot's calibrated quantiles (``population.threshold``): betting
"the top 40%" means betting at or above the equity 40% of the population's
hands had there. Bluffs come from the bottom of the same quantiles. The
quantiles are the population's, so a tighter player (stronger hands at the
same spot) takes a share a little more often than its number says.

``tough`` (see ``runner.POOLS``) seats all three next to AA players.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bots import (MAX_EQUITY_OPPONENTS, POSTFLOP_TRIALS, _Policy, opponents_in_hand,
                   passive, raise_toward)
from .population import (MAX_CONTINUE, actions, population_stats, postflop_situation,
                         preflop_shares as population_shares, stats_position, threshold)
from .spots import preflop_spot
from .strength import combo_percentile, equity

THREE_BET_SPOTS = ("vs_open", "vs_3bet_cold")
MAX_BET = 0.95              # postflop shares stay below this


@dataclass(frozen=True)
class Profile:
    # Before the flop, as factors on the 2009 players' shares.
    open: float           # first in: raise (raise + limp_raise x limps) x open
    limp_raise: float     # share of the players' limps that raise instead
    limp: float           # first in: limps x limp (the rest of the limps fold)
    isolate: float        # after limpers: raise x isolate
    overlimp: float       # after limpers: call x overlimp
    three_bet: float      # facing one raise (or more, cold): raise x three_bet
    four_bet: float       # facing a raise after acting: raise x four_bet
    call: float           # facing raises: call x call
    # After the flop.
    value: float          # with nothing to call: value-bet share = players' x value
    bluff_ratio: float    # bluffs per value bet
    max_bet: float        # value + bluff shares stay at or below this
    bet_size: float       # bets, as a share of the pot
    defend: float         # facing a bet: continue share = players' x defend
    minimum_defence: bool  # heads-up, continue at least 1 - to_call / pot
    raise_: float         # facing a bet: value-raise share = players' x raise_
    raise_bluff: float    # bluff raises per value raise


PROFILES = {
    "reg": Profile(open=1.15, limp_raise=1.0, limp=0.0, isolate=2.0, overlimp=0.5,
                   three_bet=2.0, four_bet=1.3, call=0.9,
                   value=1.0, bluff_ratio=0.4, max_bet=0.75, bet_size=0.66,
                   defend=1.0, minimum_defence=True, raise_=1.0, raise_bluff=0.3),
    "maniac": Profile(open=2.6, limp_raise=1.0, limp=0.3, isolate=3.0, overlimp=1.0,
                      three_bet=4.0, four_bet=2.0, call=1.6,
                      value=1.3, bluff_ratio=1.0, max_bet=0.9, bet_size=1.0,
                      defend=1.35, minimum_defence=False, raise_=2.0, raise_bluff=1.0),
    "nit": Profile(open=0.7, limp_raise=0.5, limp=0.0, isolate=0.7, overlimp=0.3,
                   three_bet=0.6, four_bet=0.8, call=0.5,
                   value=0.6, bluff_ratio=0.0, max_bet=0.6, bet_size=0.5,
                   defend=0.75, minimum_defence=False, raise_=0.5, raise_bluff=0.0),
}


def preflop_shares(profile, name, spot):
    """(raise, call) shares of a player of ``profile`` at this position and spot."""
    raise_share, call_share = population_shares(name, spot)
    if spot == "rfi":
        if name != "BB":        # folded to the straddle: nothing to decide
            raise_share, call_share = (
                (raise_share + profile.limp_raise * call_share) * profile.open,
                call_share * profile.limp)
    elif spot == "vs_limp":
        raise_share, call_share = (raise_share * profile.isolate,
                                   call_share * profile.overlimp)
    else:
        factor = profile.three_bet if spot in THREE_BET_SPOTS else profile.four_bet
        raise_share, call_share = raise_share * factor, call_share * profile.call
    raise_share = min(raise_share, MAX_CONTINUE)      # too many: fewer calls
    return raise_share, min(call_share, MAX_CONTINUE - raise_share)


def preflop_band(profile, observation, name):
    """The band of hand percentiles the seat's earlier actions leave it with."""
    me = observation["observing_seat"]
    history = actions(observation, "preflop")
    low, high = 0.0, 1.0
    for index, (player, kind) in enumerate(history):
        if player != me:
            continue
        raise_share, call_share = preflop_shares(profile, name,
                                                 preflop_spot(history[:index], me))
        width = high - low
        if kind == "r":
            high = low + raise_share * width
        else:
            low, high = (low + raise_share * width,
                         low + (raise_share + call_share) * width)
    return low, high


def minimum_defence(observation):
    """Share of hands that must continue so a bet cannot profit as a pure bluff."""
    pot = float(observation["pot"])
    to_call = float(observation["to_call"] or 0)
    return min(max(1 - to_call / pot, 0.0), 1.0) if pot > 0 else 0.0


def postflop_plan(profile, observation, spot):
    """Shares of hands for each postflop action at ``spot``.

    With nothing to call: {"bet": value share, "bluff": bluff share}. Facing a
    bet: {"raise": value-raise share, "continue": share that raises or calls,
    "bluff": bluff-raise share}, the bluffs taken from hands that would fold.
    """
    row = population_stats().get(spot) or {}
    if spot.endswith("checked_to"):
        value = row.get("bet", 0.35) * profile.value
        bluff = value * profile.bluff_ratio
        if value + bluff > profile.max_bet:
            value = profile.max_bet / (1 + profile.bluff_ratio)
            bluff = value * profile.bluff_ratio
        return {"bet": value, "bluff": bluff}
    raise_share = min(row.get("raise", 0.1) * profile.raise_, MAX_BET)
    keep = (row.get("raise", 0.1) + row.get("call", 0.4)) * profile.defend
    if profile.minimum_defence and opponents_in_hand(observation) == 1:
        keep = max(keep, minimum_defence(observation))
    keep = min(max(keep, raise_share), MAX_BET)
    bluff = min(raise_share * profile.raise_bluff, 1 - keep)
    return {"raise": raise_share, "continue": keep, "bluff": bluff}


def at_least(spot, share, win):
    """Whether ``win`` is in the top ``share`` of hands at ``spot``."""
    if share <= 0:
        return False
    line = threshold(spot, share)
    return line is not None and win >= line


def at_most(spot, share, win):
    """Whether ``win`` is in the bottom ``share`` of hands at ``spot``."""
    if share <= 0:
        return False
    line = threshold(spot, 1 - share)
    return line is not None and win < line


class ToughBot(_Policy):
    def __init__(self, name):
        self.name = name
        self.profile = PROFILES[name]

    def decide(self, observation, rng):
        if observation["street"] == "preflop":
            return self.preflop(observation)
        return self.postflop(observation, rng)

    def preflop(self, observation):
        name = stats_position(observation)
        me = observation["observing_seat"]
        spot = preflop_spot(actions(observation, "preflop"), me)
        raise_share, call_share = preflop_shares(self.profile, name, spot)
        low, high = preflop_band(self.profile, observation, name)
        share = combo_percentile(observation["own_hole"])
        place = (share - low) / (high - low) if high > low else 1.0
        if place <= raise_share:
            size = 0.5 if spot in ("rfi", "vs_limp") else 1.0
            return raise_toward(observation, size) or "check_call"
        if place <= raise_share + call_share:
            return "check_call"
        return passive(observation)

    def postflop(self, observation, rng):
        spot = postflop_situation(observation)
        win = equity(observation["own_hole"], observation["board"],
                     min(opponents_in_hand(observation), MAX_EQUITY_OPPONENTS),
                     POSTFLOP_TRIALS, rng)
        plan = postflop_plan(self.profile, observation, spot)
        if "bet" in plan:
            if at_least(spot, plan["bet"], win) or at_most(spot, plan["bluff"], win):
                return raise_toward(observation, self.profile.bet_size) or "check_call"
            return "check_call"
        if at_least(spot, plan["raise"], win) or at_most(spot, plan["bluff"], win):
            return raise_toward(observation, 1.0) or "check_call"
        if at_least(spot, plan["continue"], win):
            return "check_call"
        return passive(observation)


__all__ = ["PROFILES", "Profile", "ToughBot", "minimum_defence", "postflop_plan",
           "preflop_band", "preflop_shares"]
