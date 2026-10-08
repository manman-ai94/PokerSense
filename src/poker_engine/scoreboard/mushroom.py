"""The AA mushroom pool (蘑菇) on the scoreboard.

AA's rule: in a hand with four or more players the dealer puts a set amount
(the table setting, "蘑菇:3BB") into a pool before the flop. When the small
blind wins the hand's pot it takes the whole pool; otherwise the pool carries
to the next hand. The pool is shown on the table, so everyone knows it.

The scoreboard plays deals independently, so the pool carried in from
earlier hands is drawn for each deal (the same for every strategy and seat):
after each hand the small blind took it with chance ``take``, so the carry is
``k`` posts with chance ``take * (1 - take) ** k``, its long-run spread. The
default ``take`` is how often the small blind wins the main pot on the
simulated AA table (13.5% over 3000 hands of the AA pool), which makes the
pool worth about 7 posts (22 big blinds) to the small blind on average.

The strategy in a seat changes how often the small blind wins, so each
strategy is scored with its own share (``takes``, measured by
``runner.calibrate_takes``): one share for all of them made a strategy that
wins the small blind more often look about 3-7 bb/100 better than it is. The
carry is drawn from one random number per deal through each share's
distribution, so strategies with nearly the same share still get nearly the
same pools (the comparison stays paired).

A hand's result then changes by the pool alone: the dealer pays the post,
and the small blind gets the pool (carry plus post) times its share of the
main pot (the pot every player still in can win; its expected share when the
hand is scored by all-in EV). The post does not come off the dealer's stack
during the hand (3 of 100 big blinds). Every player's observations carry the
pool as ``mushroom_pool`` (chips), as a live table shows it; ``aa_preflop``
counts it as extra pot when it is the small blind, the other bots ignore it.
``nomushroom+<policy>`` plays a policy without seeing the pool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random

from .bots import _Policy

TAKE = 0.135                # the small blind's main-pot share, simulated AA table
MIN_PLAYERS = 4
MAX_CARRY = 200             # posts; the chance of more is far below a millionth


@dataclass(frozen=True)
class Mushroom:
    post: float = 3.0       # big blinds the dealer puts in
    take: float = TAKE      # chance a hand's small blind takes the pool
    takes: dict = field(default_factory=dict)   # per strategy, where measured

    def __post_init__(self):
        if self.post <= 0 or not all(
                0 < take <= 1 for take in (self.take, *self.takes.values())):
            raise ValueError("mushroom needs a positive post and 0 < take <= 1")

    def for_strategy(self, name):
        """The same pool with ``name``'s own take, when it has one."""
        return Mushroom(self.post, self.takes.get(name, self.take))

    def pool(self, seed, big_blind):
        """(the dealer's post, the pool carried in) in chips for one deal.

        The carry is ``k`` posts with chance ``take * (1 - take) ** k``,
        drawn by inverting that distribution at one number per deal.
        """
        draw = random.Random(seed * 7_919 + 3).random()
        carry = 0
        if self.take < 1:
            carry = min(MAX_CARRY, math.floor(math.log1p(-draw)
                                              / math.log1p(-self.take)))
        post = self.post * big_blind
        return post, carry * post

    def to_dict(self):
        result = {"post_big_blinds": self.post, "take": self.take}
        if self.takes:
            result["takes"] = dict(self.takes)
        return result


def small_blind(arena):
    return arena._seats[0]          # PokerKit's index 0 is the small blind


def main_pot_shares(arena):
    """Each seat's share of the main pot after a hand played to the end."""
    pots = arena._settlement["pots"]
    winners = pots[0]["winners"] if pots else []
    return {seat: 1 / len(winners) for seat in winners}


def pool_result(arena, mushroom, carried, post, hero, shares):
    """What the pool adds to ``hero``'s result in chips (``shares``: each
    seat's share of the main pot)."""
    if len(arena.occupied_seats) < MIN_PLAYERS:
        return 0.0
    value = 0.0
    if hero == arena.dealer_seat:
        value -= post
    if hero == small_blind(arena):
        value += (carried + post) * shares.get(hero, 0.0)
    return value


class Blind(_Policy):
    """A policy that does not see the mushroom pool."""

    def __init__(self, base, name):
        self.base, self.name = base, name

    def decide(self, observation, rng):
        if "mushroom_pool" in observation:
            observation = {key: value for key, value in observation.items()
                           if key != "mushroom_pool"}
        return self.base.decide(observation, rng)


__all__ = ["Blind", "Mushroom", "TAKE", "main_pot_shares", "pool_result",
           "small_blind"]
