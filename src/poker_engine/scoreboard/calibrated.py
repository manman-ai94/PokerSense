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
  of both (a negative slope folds more to bigger bets);
* bets and raises take the sizes measured: half the pot heads-up, 60% in
  pots of three or more, raises 1.1 pots (first raises before the flop as
  ``aa_real``).

The probabilities of each action are worked out (``distribution``) and the
action drawn from them, so the scoreboard and the fidelity measure use the
same numbers. With ``mix``, ``slow``, ``bluff``, ``sticky`` and the slope
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
BET_HU, BET_MULTI, RAISE = 0.5, 0.6, 1.1
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
    if not slope or price <= 0 or not 0 < keep < 1:
        return keep
    z = _logit(keep) + slope * (_logit(price) - _logit(REFERENCE_PRICE))
    return 1 / (1 + math.exp(-z))


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


def facing_probs(win, spot, raise_share, call_share, price, slow, sticky, slope,
                 can_raise=True):
    """[fold, call, raise] probabilities facing a bet at ``price``."""
    win = np.asarray(win, dtype=float)
    keep = raise_share + call_share
    priced = priced_keep(keep, price, slope)
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
            return raise_id
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
        raise_share, call_share = preflop_shares(observation, spot, aa=self.stats)
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
            price = to_call / (float(observation["pot"]) + to_call)
            probs = facing_probs(win, spot, row.get("raise") or 0.1,
                                 row.get("call") or 0.4, price, street["slow"],
                                 street["sticky"], self.params["price_slope"],
                                 raise_id is not None)
        return probs, raise_id


__all__ = ["FITTED", "REFERENCE_PRICE", "CalibratedBot", "cal_stats", "checked_probs",
           "facing_probs", "preflop_probs", "priced_keep"]
