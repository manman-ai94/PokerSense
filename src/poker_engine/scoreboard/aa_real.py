"""The "AA 真人桌" opponents: real AA players' measured shares and bet sizes.

``aa_real`` plays like the population bot, with the numbers measured on AA
recordings (``aa_real_stats_v1.json``, kept by ``tools/build_aa_real_stats.py``
from the counts of ``tools/aa_population_stats.py``) wherever there are
enough of them, and the 2009 players' elsewhere. AA samples are small (96
hands), so each measured share is pulled toward the 2009 one as if the
2009 share had been seen ``PRIOR`` more times: a share from 171 decisions
counts 85%, one from 24 decisions 44% (a rough number gives the direction),
and rows of fewer than 10 decisions are not kept at all.

Before the flop, for each kind of decision:

1. the AA share over all positions (pulled toward the 2009 share over all
   positions);
2. spread over the positions the way the 2009 players' shares differ by
   position (as ``aa_population`` does);
3. where AA players at that position were counted, pulled toward that
   count.

After the flop the population bot's situations take the AA shares in the
same way (multiway flop facing a bet is the best measured). Sizes follow the
recordings: first raises and raises over limpers put in about the pot
before them (``OPEN_POT``; the other bots raise half the pot after calling,
about two thirds of that), bets half the pot heads-up and two thirds in
multiway pots. Re-raises keep the pot-sized raise of the other bots.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
import json

from poker_engine.core.enums import Position

from .bots import (MAX_EQUITY_OPPONENTS, POSTFLOP_TRIALS, opponents_in_hand, passive,
                   position, raise_toward)
from .population import (MAX_CONTINUE, PopulationBot, actions, population_stats,
                         postflop_situation, stats_position, threshold)
from .spots import preflop_spot
from .strength import combo_percentile, equity

STATS_FILE = "aa_real_stats_v1.json"
PRIOR = 30                  # 2009 decisions an AA share is weighed against
OPEN_POT = 0.96             # first raise / raise over limpers: share of the pot
BET_HU, BET_MULTI = 0.5, 0.65
PREFLOP_ACTIONS = ("raise", "call")
POSTFLOP_ACTIONS = ("bet", "raise", "call")


@lru_cache(maxsize=1)
def aa_stats():
    data = resources.files("poker_engine.scoreboard").joinpath(STATS_FILE)
    return json.loads(data.read_text(encoding="utf-8"))


def pulled(row, prior, keys):
    """``prior`` ({action: share}) moved toward the AA ``row`` by its count."""
    if not row:
        return dict(prior)
    weight = row["n"] / (row["n"] + PRIOR)
    return {key: weight * row.get(key, 0.0) + (1 - weight) * prior.get(key, 0.0)
            for key in keys}


def aa_name(observation, seat=None):
    """Position as the AA statistics name it (STR is the straddle)."""
    seat = observation["observing_seat"] if seat is None else seat
    if seat == observation.get("straddler_seat"):
        return "STR"
    found = position(observation, seat)
    if found == Position.UTG:
        return "STR" if observation.get("straddler_seat") is None else "UTG1"
    return found.name


def preflop_shares(observation, spot, seat=None):
    """(raise, call) shares of an AA player at ``seat`` facing ``spot``."""
    stats, aa = population_stats(), aa_stats()["preflop"]
    seat = observation["observing_seat"] if seat is None else seat
    name = stats_position({**observation, "observing_seat": seat})
    every = stats.get(f"ALL|{spot}") or {}
    here = stats.get(f"{name}|{spot}") or every
    overall = pulled(aa.get(f"ALL|{spot}"), every, PREFLOP_ACTIONS)
    spread = {key: (here.get(key, 0.0) * overall[key] / every[key]
                    if every.get(key) else overall[key]) for key in PREFLOP_ACTIONS}
    final = pulled(aa.get(f"{aa_name(observation, seat)}|{spot}"), spread,
                   PREFLOP_ACTIONS)
    raise_share = min(final["raise"], MAX_CONTINUE)
    return raise_share, min(final["call"], MAX_CONTINUE - raise_share)


def preflop_band(observation):
    """The band of hand percentiles the seat's earlier actions leave it with."""
    me = observation["observing_seat"]
    history = actions(observation, "preflop")
    low, high = 0.0, 1.0
    for index, (player, kind) in enumerate(history):
        if player != me:
            continue
        raise_share, call_share = preflop_shares(observation,
                                                 preflop_spot(history[:index], me))
        width = high - low
        if kind == "r":
            high = low + raise_share * width
        else:
            low, high = (low + raise_share * width,
                         low + (raise_share + call_share) * width)
    return low, high


def postflop_shares(spot):
    """{bet, raise, call: share} of AA players at a postflop situation."""
    prior = population_stats().get(spot) or {}
    return pulled(aa_stats()["postflop"].get(spot), prior, POSTFLOP_ACTIONS)


def raise_by_pot(observation, share):
    """A raise that puts in ``share`` of the pot before it (rounded to the
    table's smallest chip, within the legal raises); None if none is legal.

    The other bots pick from the arena's menu of raises (minimum, half pot,
    pot, all in); a pot-sized open lies between two of those, so this raise
    is off the menu, which the arena accepts.
    """
    betting = observation.get("betting") or {}
    low, high = betting.get("min_raise_to"), betting.get("max_raise_to")
    if not betting.get("can_raise") or low is None or high is None:
        return raise_toward(observation, 1.0)
    chip = float(observation["rules"]["minimum_chip"])
    me = str(observation["observing_seat"])
    target = (float(observation["bets"].get(me, 0))
              + share * float(observation["pot"]))
    amount = min(max(round(target / chip) * chip, float(low)), float(high))
    return f"raise_to:{amount:g}"


class AARealBot(PopulationBot):
    name = "aa_real"

    def __init__(self):
        super().__init__(adjusted=True)
        self.name = "aa_real"

    def preflop(self, observation):
        me = observation["observing_seat"]
        spot = preflop_spot(actions(observation, "preflop"), me)
        raise_share, call_share = preflop_shares(observation, spot)
        low, high = preflop_band(observation)
        share = combo_percentile(observation["own_hole"])
        place = (share - low) / (high - low) if high > low else 1.0
        if place <= raise_share:
            action = (raise_by_pot(observation, OPEN_POT)
                      if spot in ("rfi", "vs_limp") else raise_toward(observation, 1.0))
            return action or "check_call"
        if place <= raise_share + call_share:
            return "check_call"
        return passive(observation)

    def postflop(self, observation, rng):
        spot = postflop_situation(observation)
        row = postflop_shares(spot)
        win = equity(observation["own_hole"], observation["board"],
                     min(opponents_in_hand(observation), MAX_EQUITY_OPPONENTS),
                     POSTFLOP_TRIALS, rng)
        if spot.endswith("checked_to"):
            bet = threshold(spot, row.get("bet") or 0.35)
            if bet is not None and win >= bet:
                size = BET_HU if opponents_in_hand(observation) == 1 else BET_MULTI
                return raise_toward(observation, size) or "check_call"
            return "check_call"
        raise_share = row.get("raise") or 0.1
        raise_at = threshold(spot, raise_share)
        call_at = threshold(spot, raise_share + (row.get("call") or 0.4))
        if raise_at is not None and win >= raise_at:
            return raise_toward(observation, 1.0) or "check_call"
        if call_at is not None and win >= call_at:
            return "check_call"
        return passive(observation)


__all__ = ["AARealBot", "aa_name", "aa_stats", "postflop_shares", "preflop_band",
           "preflop_shares", "pulled", "raise_by_pot"]
