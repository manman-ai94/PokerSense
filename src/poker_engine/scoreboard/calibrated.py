"""The "AA 校准桌" opponents: AA players as the recordings show them.

``aa_real`` (``aa_real.py``) plays the shares measured on AA recordings as a
strict ranking of hands: before the flop the strongest raise and the next
call; after the flop the hands with the most equity bet, raise and call and
the rest check or fold, whatever the price. Put to the recorded hands
(``tools/sim_fidelity.py``), real players do not play that way: they bet and
call with hands the ranking would not, check strong hands, and fold more to
bigger bets heads-up, so the cards they show are often hands ``aa_real``
could not hold there.

``aa_cal`` plays ``aa_real``'s rules with the AA numbers of every recording
(``aa_cal_stats_v1.json``, built as ``aa_real_stats_v1.json`` is) and these
departures, by amounts fitted on the recordings (``tools/fit_aa_cal.py``,
the values in ``FITTED``):

* before the flop a share ``mix`` of decisions follow the spot's shares
  whatever the cards (a limp can hold aces, an open raise trash);
* after the flop, on each street, ``slow`` of the hands strong enough to bet
  or raise check or call instead, ``bluff`` of those too weak to bet bet
  anyway and ``sticky`` of those too weak to call call anyway. The equity
  lines move so that betting, raising and calling stay as often as measured:
  a slow-played hand or a bluff takes the place of an honest one;
* facing a bet, the share that goes on depends on the price (the call as a
  share of the pot after calling): the measured share holds at
  ``REFERENCE_PRICE`` and moves with ``price_slope`` on the log-odds scale
  of both (a negative slope folds more to bigger bets); likewise with the
  depth (``depth_slope``, on the log of the effective stack, over the pot
  after the flop) and a call that is all in (``allin_shift``), and before
  the flop with the ``preflop_`` ones (``adjusted_keep``; all 0 until the
  recordings show they hold, see ``tools/fit_aa_cal.py --phh``);
* bets and raises take the sizes measured: half the pot heads-up, 60% in
  pots of three or more, raises 1.1 pots (first raises before the flop as
  ``aa_real``); after the flop, with little behind for the pot, all in as
  often as AA players go all in at that depth (``SHOVE_BET``,
  ``SHOVE_RAISE``).

The probabilities of each action are worked out (``distribution``) and the
action drawn from them, so the scoreboard and the fidelity measure use the
same numbers. With ``mix``, ``slow``, ``bluff``, ``sticky`` and the slopes
all 0 it plays as ``aa_real`` on its numbers, except the bet sizes.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
import json
import math

import numpy as np

from .aa_real import (OPEN_POT, AARealBot, postflop_shares, preflop_band,
                      preflop_shares, raise_by_pot)
from .bots import MAX_EQUITY_OPPONENTS, POSTFLOP_TRIALS, opponents_in_hand, raise_toward
from .population import actions, postflop_situation, threshold
from .spots import preflop_spot
from .strength import combo_percentile, equity

STATS_FILE = "aa_cal_stats_v1.json"
STREETS = ("flop", "turn", "river")
REFERENCE_PRICE = 0.26      # typical price of the bets AA players faced
# Medians over AA players' decisions facing a bet (15 recordings): the price
# of the raises faced before the flop, and the depth, before the flop the
# effective stack in big blinds, after it over the pot. A depth outside the
# range counts as its nearer end (a stack the recording did not read is
# taken as very deep).
PREFLOP_REFERENCE_PRICE = 0.16
REFERENCE_DEPTH_BB, DEPTH_BB_RANGE = 243.0, (10.0, 500.0)
REFERENCE_SPR, SPR_RANGE = 3.4, (0.2, 20.0)
PRICE_RANGE = (0.05, 0.5)
BET_HU, BET_MULTI, RAISE = 0.5, 0.6, 1.1
# How often AA players' bets and raises after the flop go all in, by the
# effective stack over the pot (SPR): (SPR below, share). 15 recordings:
# bets 5/5 below 0.5, 28/48 below 1, 5/34 below 2, about 0 above; raises
# 7/7 below 1, 6/10 below 2, 2/15 below 4, 0/30 above.
SHOVE_BET = ((0.5, 1.0), (1.0, 0.6), (2.0, 0.15), (None, 0.0))
SHOVE_RAISE = ((1.0, 1.0), (2.0, 0.6), (4.0, 0.13), (None, 0.0))
# Fitted 2026-10-15 on 475 replayed hands of 15 recordings (``tools/fit_aa_cal.py``;
# out of sample each half of them fits the other better than ``aa_real``). A
# price slope did not hold from one half to the other, so it is 0 for now.
FITTED = {"mix": 0.6, "price_slope": 0.0,
          "flop": {"slow": 0.4, "bluff": 0.06, "sticky": 0.2},
          "turn": {"slow": 0.5, "bluff": 0.1, "sticky": 0.15},
          "river": {"slow": 0.7, "bluff": 0.0, "sticky": 0.03}}
KINDS = ("f", "c", "r")


@lru_cache(maxsize=1)
def cal_stats():
    data = resources.files("poker_engine.scoreboard").joinpath(STATS_FILE)
    return json.loads(data.read_text(encoding="utf-8"))


def _clip(value, low=0.0, high=1.0):
    return min(max(value, low), high)


def _logit(share):
    share = _clip(share, 1e-6, 1 - 1e-6)
    return math.log(share / (1 - share))


def priced_keep(keep, price, slope):
    """The share that goes on facing a bet at ``price``, when ``keep`` goes
    on at ``REFERENCE_PRICE``."""
    return adjusted_keep(keep, (price, 0.0, False), {"price_slope": slope})


def effective_stack(observation):
    """The most the seat to act can still lose: its chips behind, or what the
    deepest other player still in can put in beyond its own bet."""
    me = observation["observing_seat"]
    stacks, bets = observation["stacks"], observation["bets"]
    folded = set(observation["folded"])
    others = [float(stacks[str(seat)]) + float(bets[str(seat)]) - float(bets[str(me)])
              for seat in observation["occupied_seats"]
              if seat != me and seat not in folded]
    return max(0.0, min(float(stacks[str(me)]), max(others, default=0.0)))


def situation(observation):
    """(price, depth, all in) of a decision: the call as a share of the pot
    after calling (0 with nothing to call); the effective stack before the
    flop in big blinds, after it over the pot; whether calling is all in."""
    to_call = float(observation["to_call"] or 0)
    pot = float(observation["pot"])
    depth = effective_stack(observation)
    if observation["street"] == "preflop":
        depth /= float(observation["big_blind"])
    else:
        depth = depth / pot if pot else 99.0
    mine = float(observation["stacks"][str(observation["observing_seat"])])
    return (to_call / (pot + to_call) if to_call else 0.0, depth,
            bool(to_call) and to_call >= mine)


def adjusted_keep(keep, features, params, preflop=False):
    """The share that goes on facing a bet, when ``keep`` goes on at the
    reference price and depth: moved on the log-odds scale by the price
    (``price_slope``), the depth (``depth_slope``, on its log) and a call
    that is all in (``allin_shift``); ``preflop_`` before each name before
    the flop."""
    price, depth, all_in = features
    head = "preflop_" if preflop else ""
    shift = 0.0
    slope = params.get(head + "price_slope", 0.0)
    if slope and price > 0:
        reference = PREFLOP_REFERENCE_PRICE if preflop else REFERENCE_PRICE
        low, high = PRICE_RANGE
        shift += slope * (_logit(min(max(price, low), high)) - _logit(reference))
    slope = params.get(head + "depth_slope", 0.0)
    if slope:
        reference, (low, high) = ((REFERENCE_DEPTH_BB, DEPTH_BB_RANGE) if preflop
                                  else (REFERENCE_SPR, SPR_RANGE))
        shift += slope * (math.log(min(max(depth, low), high)) - math.log(reference))
    if all_in:
        shift += params.get(head + "allin_shift", 0.0)
    if not shift or not 0 < keep < 1:
        return keep
    return 1 / (1 + math.exp(-(_logit(keep) + shift)))


def preflop_adjusted(raise_share, call_share, features, params):
    """The spot's (raise, call) shares at this price and depth."""
    keep = raise_share + call_share
    if not features[0] or not keep:
        return raise_share, call_share
    moved = adjusted_keep(keep, features, params, preflop=True)
    return raise_share * moved / keep, call_share * moved / keep


def preflop_probs(base, raise_share, call_share, mix, can_fold=True, can_raise=True):
    """[fold, call, raise] probabilities: the band's action ``base`` (0, 1 or
    2; an array of them works too) mixed with the spot's shares."""
    base = np.asarray(base)
    shares = np.array([max(1 - raise_share - call_share, 0.0), call_share,
                       raise_share])
    probs = (1 - mix) * (base[..., None] == np.arange(3)) + mix * shares
    return _legal(probs, can_fold, can_raise)


def _legal(probs, can_fold, can_raise):
    probs = np.array(probs, dtype=float)
    if not can_fold:
        probs[..., 1] += probs[..., 0]
        probs[..., 0] = 0.0
    if not can_raise:
        probs[..., 1] += probs[..., 2]
        probs[..., 2] = 0.0
    return probs


def checked_probs(win, spot, bet, slow, bluff, can_raise=True):
    """[fold, check, bet] probabilities with nothing to call. ``win``: the
    hand's equity (or an array of them); ``bet``: the measured bet share."""
    win = np.asarray(win, dtype=float)
    value = _clip((bet - bluff) / max(1 - slow - bluff, 1e-6))
    line = threshold(spot, value) if value > 0 else None
    strong = win >= line if line is not None else np.zeros(win.shape, bool)
    betting = np.where(strong, 1 - slow, bluff)
    probs = np.stack([np.zeros(win.shape), 1 - betting, betting], axis=-1)
    return _legal(probs, False, can_raise)


def facing_probs(win, spot, raise_share, call_share, priced, slow, sticky,
                 can_raise=True):
    """[fold, call, raise] probabilities facing a bet, when ``priced`` of the
    players go on at this price and depth (``adjusted_keep``)."""
    win = np.asarray(win, dtype=float)
    keep = raise_share + call_share
    raising = raise_share * priced / keep if keep else 0.0
    value_keep = _clip((priced - sticky) / max(1 - sticky, 1e-6))
    value_raise = min(_clip(raising / max(1 - slow, 1e-6)), value_keep)
    none = np.zeros(win.shape, bool)
    line = threshold(spot, value_raise) if value_raise > 0 else None
    top = win >= line if line is not None else none
    line = threshold(spot, value_keep) if value_keep > 0 else None
    going = win >= line if line is not None else none
    raises = np.where(top, 1 - slow, 0.0)
    calls = np.where(top, slow, np.where(going, 1.0, sticky))
    probs = np.stack([1 - raises - calls, calls, raises], axis=-1)
    return _legal(probs, True, can_raise)


def street_params(params, street):
    return params.get(street) or {"slow": 0.0, "bluff": 0.0, "sticky": 0.0}


def all_in_or(observation, raise_id, draw):
    """``raise_id``, or all in after the flop as often as AA players go all
    in at this depth (``SHOVE_BET``, ``SHOVE_RAISE``); ``draw`` in [0, 1)."""
    betting = observation.get("betting") or {}
    pot = float(observation["pot"])
    if observation["street"] == "preflop" or not betting.get("max_raise_to") or not pot:
        return raise_id
    spr = effective_stack(observation) / pot
    table = SHOVE_RAISE if float(observation["to_call"] or 0) else SHOVE_BET
    share = next(share for top, share in table if top is None or spr < top)
    return f"raise_to:{float(betting['max_raise_to']):g}" if draw < share else raise_id


class CalibratedBot(AARealBot):
    name = "aa_cal"

    def __init__(self, params=None, stats=None):
        super().__init__()
        self.name = "aa_cal"
        self.params = params or FITTED
        self._stats = stats

    @property
    def stats(self):
        return self._stats or cal_stats()

    def decide(self, observation, rng):
        probs, raise_id = self.plan(observation, rng)
        roll = rng.random()
        if roll < probs[2] and raise_id is not None:
            return all_in_or(observation, raise_id, roll / probs[2])
        if roll < probs[2] + probs[1] or float(observation["to_call"] or 0) == 0:
            return "check_call"
        return "fold"

    def distribution(self, observation, rng):
        probs, _ = self.plan(observation, rng)
        return {kind: float(p) for kind, p in zip(KINDS, probs) if p > 0}

    def plan(self, observation, rng):
        """([fold, call, raise] probabilities, the raise to make or None)."""
        if observation["street"] == "preflop":
            return self.preflop_plan(observation)
        return self.postflop_plan(observation, rng)

    def preflop_plan(self, observation):
        me = observation["observing_seat"]
        spot = preflop_spot(actions(observation, "preflop"), me)
        raise_share, call_share = preflop_adjusted(
            *preflop_shares(observation, spot, aa=self.stats), situation(observation),
            self.params)
        low, high = preflop_band(observation, aa=self.stats)
        share = combo_percentile(observation["own_hole"])
        place = (share - low) / (high - low) if high > low else 1.0
        base = (2 if place <= raise_share else
                1 if place <= raise_share + call_share else 0)
        raise_id = (raise_by_pot(observation, OPEN_POT)
                    if spot in ("rfi", "vs_limp") else raise_toward(observation, 1.0))
        probs = preflop_probs(base, raise_share, call_share, self.params["mix"],
                              float(observation["to_call"] or 0) > 0,
                              raise_id is not None)
        return probs, raise_id

    def postflop_plan(self, observation, rng):
        spot = postflop_situation(observation)
        row = postflop_shares(spot, aa=self.stats)
        opponents = opponents_in_hand(observation)
        win = equity(observation["own_hole"], observation["board"],
                     min(opponents, MAX_EQUITY_OPPONENTS), POSTFLOP_TRIALS, rng)
        street = street_params(self.params, observation["street"])
        to_call = float(observation["to_call"] or 0)
        if to_call == 0:
            size = BET_HU if opponents == 1 else BET_MULTI
            raise_id = raise_by_pot(observation, size)
            probs = checked_probs(win, spot, row.get("bet") or 0.35, street["slow"],
                                  street["bluff"], raise_id is not None)
        else:
            raise_id = raise_by_pot(observation, RAISE)
            raise_share, call_share = row.get("raise") or 0.1, row.get("call") or 0.4
            priced = adjusted_keep(raise_share + call_share, situation(observation),
                                   self.params)
            probs = facing_probs(win, spot, raise_share, call_share, priced,
                                 street["slow"], street["sticky"], raise_id is not None)
        return probs, raise_id


__all__ = ["FITTED", "REFERENCE_PRICE", "CalibratedBot", "adjusted_keep", "all_in_or",
           "cal_stats", "checked_probs", "effective_stack", "facing_probs",
           "preflop_adjusted", "preflop_probs", "priced_keep", "situation"]
