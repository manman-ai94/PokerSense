"""After the flop with two or more opponents: play by equity against their ranges.

``range_multiway+aa_preflop`` plays like its base policy everywhere except
postflop decisions with more than one opponent. There every opponent's range
is read from their actions with the population model and your share of the
pot against those ranges is worked out (``ranges``); then

- facing a bet: raise about the pot when the share is at least ``raise``,
  call when it beats the price (``to_call / (pot + to_call)``) by ``margin``,
  otherwise fold;
- with nothing to call: bet when the share is at least ``bet``, otherwise
  check; about two thirds of the pot (``size``) against two opponents, the
  pot (``size3``) against three or more.

With ``hu=1`` the heads-up flop is played the same way, with its own cuts
``hu_bet`` and ``hu_raise`` (one opponent's fair share is a half, not a
third or less): the live window has no solver for that street (a flop solve
takes about a minute) and plays it so. 0.55 and 0.7 won the most of the cuts
tried on the scoreboard (2026-10-08, AA pool with the mushroom pool).

``bet`` was 0.4 until 2026-10-09: with seven opponents that bet only with
twice a fair share, and the 10/09 session showed checks with strong hands in
big multiway pots. 0.3 beat 0.4 on the AA real-player table (mushroom pool,
bomb pots, reads) on two batches of deals.

``size3`` was two thirds until 2026-10-09 too. The scoreboard table offers
the minimum, half the pot, the pot and all in, so two thirds plays as half
the pot there; betting the pot into three or more opponents won +9.2 and
+5.5 bb/100 on the AA real-player table on two batches of deals, while the
pot against two opponents lost 4.0.

Parameters can follow the name, for example
``range_multiway@bet=0.55:raise=0.7:margin=0.05+aa_preflop`` (":" between
them: "," separates strategies on the command line).
"""

from __future__ import annotations

from collections import Counter

from .bots import _Policy, opponents_in_hand, raise_toward
from .population import PopulationBot
from .ranges import opponent_ranges, ranges_equity

DEFAULTS = {"bet": 0.3, "raise": 0.6, "margin": 0.0, "trials": 600,
            "hu": 0.0, "hu_bet": 0.55, "hu_raise": 0.7,
            "size": 0.66, "size3": 1.0, "raise_size": 1.0}


class RangeMultiwayBot(_Policy):
    def __init__(self, base, name="range_multiway", **params):
        unknown = set(params) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"unknown parameters {sorted(unknown)}")
        self.base, self.name = base, name
        self.params = {**DEFAULTS, **params}
        self.model = PopulationBot(adjusted=getattr(base, "adjusted", False))
        self.counts = Counter()

    def decide(self, observation, rng):
        if not covered(observation, self.params):
            return self.base.decide(observation, rng)
        ranges = opponent_ranges(observation, self.model)
        share, _ = ranges_equity(observation["own_hole"], observation["board"], ranges,
                                 trials=int(self.params["trials"]),
                                 seed=rng.randrange(2 ** 31))
        if share is None:
            self.counts["no_equity"] += 1
            return self.base.decide(observation, rng)
        self.counts["decided"] += 1
        return choose(observation, share, self.params)


def covered(observation, params=DEFAULTS):
    """Whether the rule plays this decision: after the flop with two or more
    opponents, and on the heads-up flop with ``hu``."""
    if observation["street"] == "preflop":
        return False
    opponents = opponents_in_hand(observation)
    return opponents >= 2 or (opponents == 1 and observation["street"] == "flop"
                              and bool(params["hu"]))


def street_params(observation, params=DEFAULTS):
    """The cuts for this decision: heads-up ones against one opponent."""
    opponents = opponents_in_hand(observation)
    if opponents >= 3:
        return {**params, "size": params["size3"]}
    if opponents == 2:
        return params
    return {**params, "bet": params["hu_bet"], "raise": params["hu_raise"],
            "size": DEFAULTS["size"]}


def cuts(observation, params=DEFAULTS):
    """The shares of the pot where the action changes: with nothing to call,
    ``bet``; facing a bet, ``call`` (the price plus the margin) and ``raise``."""
    to_call = float(observation["to_call"] or 0)
    if to_call == 0:
        return {"bet": params["bet"]}
    price = to_call / (float(observation["pot"]) + to_call)
    return {"call": price + params["margin"], "raise": params["raise"]}


def choose(observation, share, params=DEFAULTS):
    """The action id for your share of the pot against the field."""
    params = street_params(observation, params)
    line = cuts(observation, params)
    if "bet" in line:
        if share >= line["bet"]:
            return raise_toward(observation, params["size"]) or "check_call"
        return "check_call"
    if share >= line["raise"]:
        return raise_toward(observation, params["raise_size"]) or "check_call"
    return "check_call" if share >= line["call"] else "fold"


def from_name(name, make_policy):
    """``range_multiway[@k=v:...]+base`` as a policy."""
    head, _, base = name.partition("+")
    _, _, text = head.partition("@")
    params = {}
    for item in filter(None, text.split(":")):
        key, _, value = item.partition("=")
        params[key] = float(value)
    bot = RangeMultiwayBot(make_policy(base), **params)
    bot.name = name
    return bot


__all__ = ["DEFAULTS", "RangeMultiwayBot", "choose", "covered", "cuts", "from_name",
           "street_params"]
