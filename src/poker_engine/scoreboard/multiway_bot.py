"""After the flop with two or more opponents: play by equity against their ranges.

``range_multiway+aa_preflop`` plays like its base policy everywhere except
postflop decisions with more than one opponent. There every opponent's range
is read from their actions with the population model and your share of the
pot against those ranges is worked out (``ranges``); then

- facing a bet: raise about the pot when the share is at least ``raise``,
  call when it beats the price (``to_call / (pot + to_call)``) by ``margin``,
  otherwise fold;
- with nothing to call: bet about two thirds of the pot when the share is at
  least ``bet``, otherwise check.

Parameters can follow the name, for example
``range_multiway@bet=0.55:raise=0.7:margin=0.05+aa_preflop`` (":" between
them: "," separates strategies on the command line).
"""

from __future__ import annotations

from collections import Counter

from .bots import _Policy, opponents_in_hand, raise_toward
from .population import PopulationBot
from .ranges import opponent_ranges, ranges_equity

DEFAULTS = {"bet": 0.4, "raise": 0.6, "margin": 0.0, "trials": 600}


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
        if observation["street"] == "preflop" or opponents_in_hand(observation) < 2:
            return self.base.decide(observation, rng)
        ranges = opponent_ranges(observation, self.model)
        share, _ = ranges_equity(observation["own_hole"], observation["board"], ranges,
                                 trials=int(self.params["trials"]),
                                 seed=rng.randrange(2 ** 31))
        if share is None:
            self.counts["no_equity"] += 1
            return self.base.decide(observation, rng)
        self.counts["decided"] += 1
        to_call = float(observation["to_call"] or 0)
        if to_call == 0:
            if share >= self.params["bet"]:
                return raise_toward(observation, 0.66) or "check_call"
            return "check_call"
        if share >= self.params["raise"]:
            return raise_toward(observation, 1.0) or "check_call"
        price = to_call / (float(observation["pot"]) + to_call)
        return "check_call" if share >= price + self.params["margin"] else "fold"


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


__all__ = ["DEFAULTS", "RangeMultiwayBot", "from_name"]
