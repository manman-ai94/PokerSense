"""Reads on opponents: how often each one has put chips in and raised.

A player at a real table watches the others for a while: after a hundred
hands a seat that raised 40% of them is not the 11% raiser the statistics
describe. ``aa_preflop`` uses such reads (``observation["reads"]``,
{seat: {"hands", "vpip", "pfr"}}) to widen or narrow the ranges it expects
from that seat. A read may also say how the seat plays after the flop:
``postflop`` decisions seen there and the share of them that bet or raised
(``aggression``); the range reading (``ranges``) uses it to tell a player
who bets more than the model from one who only raises more before the flop.

On the scoreboard every deal is played on its own, so the reads a hero
would have built are simulated: each kind of opponent's long-run shares are
measured once by self-play of the pool (``measure``), and every deal gives
each opponent seat a sample of ``hands`` hands from them (``sample``), so the
reads carry the noise of a short session.

``factors`` turns a seat's read into how much more (or less) often than the
model that seat raises and calls: the read is first pulled toward the
model's own long-run shares (``MODEL``) by ``READ_PRIOR`` hands, so a few
hands move little and a long session decides. ``aggression_factor`` does the
same for the postflop share, pulled by ``AGGRESSION_PRIOR`` decisions; a read
without postflop numbers has none.
"""

from __future__ import annotations

import random

from .bots import _Policy

MEASURE_DEALS = 300
POSTFLOP_SLOTS = 4      # postflop decisions a sampled hand can have at most
READ_PRIOR = 50         # hands of the model's own shares a read is pulled toward
FACTOR_RANGE = (0.25, 4.0)
AGGRESSION_PRIOR = 30   # postflop decisions of the model's share a read is pulled to
# Long-run shares of the players each model expects, at a table of such
# players (``measure`` on the "aa" and "population" pools, 2400 hands;
# aggression: share of postflop decisions that bet or raise).
MODEL = {"aa_population": {"vpip": 0.37, "pfr": 0.115, "aggression": 0.21},
         "population": {"vpip": 0.22, "pfr": 0.10, "aggression": 0.24}}


def measure(rules, pool, deals=MEASURE_DEALS, base_seed=0):
    """{policy name: {"vpip", "pfr", "postflop", "aggression"}} from self-play
    of ``pool``: preflop shares per hand dealt, postflop decisions per hand
    dealt and the share of them that bet or raised."""
    from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena

    from .bots import make_policy
    from .runner import lineup           # imports this module

    arena = AAFullHandArena(rules)
    seats = arena.occupied_seats
    bots = {name: make_policy(name) for name in set(pool)}
    dealt, played, raised, acted, aggressive = {}, {}, {}, {}, {}
    for seed in range(base_seed * 1_000_000 + 500_000,
                      base_seed * 1_000_000 + 500_000 + deals):
        styles = lineup(seed, pool, seats)
        deciders = {seat: bots[styles[seat]].for_game(f"reads:{seed}:{seat}")
                    for seat in seats}
        arena.reset(seed)
        entered, raising = set(), set()
        while not arena.terminal:
            seat = arena.actor
            observation = arena.observe(seat)
            action = deciders[seat](observation)
            name = styles[seat]
            if observation["street"] == "preflop":
                if action.startswith("raise_to"):
                    entered.add(seat)
                    raising.add(seat)
                elif action == "check_call" and float(observation["to_call"] or 0):
                    entered.add(seat)
            else:
                acted[name] = acted.get(name, 0) + 1
                aggressive[name] = (aggressive.get(name, 0)
                                    + action.startswith("raise_to"))
            arena.step(action)
        for seat in seats:
            name = styles[seat]
            dealt[name] = dealt.get(name, 0) + 1
            played[name] = played.get(name, 0) + (seat in entered)
            raised[name] = raised.get(name, 0) + (seat in raising)
    return {name: {"vpip": played[name] / dealt[name],
                   "pfr": raised[name] / dealt[name],
                   "postflop": acted.get(name, 0) / dealt[name],
                   "aggression": aggressive.get(name, 0) / max(1, acted.get(name, 0))}
            for name in dealt}


def sample(shares, styles, hero, seed, hands):
    """Reads of every seat but ``hero`` after ``hands`` hands of watching.

    The postflop numbers come from their own draws, so the preflop ones are
    the same with or without them."""
    rng = random.Random(seed * 7_727 + 11)
    later = random.Random(seed * 7_727 + 13)
    reads = {}
    for seat, name in sorted(styles.items()):
        if seat == hero:
            continue
        vpip, pfr = shares[name]["vpip"], shares[name]["pfr"]
        played = raised = 0
        for _ in range(hands):
            draw = rng.random()
            raised += draw < pfr
            played += draw < vpip
        reads[str(seat)] = {"hands": hands, "vpip": played / hands,
                            "pfr": raised / hands}
        if "aggression" in shares[name]:
            # up to POSTFLOP_SLOTS postflop decisions a hand, the measured number
            # on average
            chance = shares[name]["postflop"] / POSTFLOP_SLOTS
            decisions = sum(later.random() < chance
                            for _ in range(hands * POSTFLOP_SLOTS))
            bets = sum(later.random() < shares[name]["aggression"]
                       for _ in range(decisions))
            reads[str(seat)].update(postflop=decisions,
                                    aggression=bets / decisions if decisions else 0.0)
    return reads


def factors(read, model):
    """(raise factor, call factor) of a seat with ``read`` against ``model``."""
    if not read:
        return 1.0, 1.0
    hands = float(read["hands"])
    weight = hands / (hands + READ_PRIOR)

    def pulled(key):
        return weight * float(read[key]) + (1 - weight) * model[key]

    low, high = FACTOR_RANGE
    pfr, vpip = pulled("pfr"), pulled("vpip")
    raise_factor = pfr / model["pfr"]
    call_factor = max(0.0, vpip - pfr) / (model["vpip"] - model["pfr"])
    return (min(max(raise_factor, low), high), min(max(call_factor, low), high))


def aggression_factor(read, model):
    """How much more often than ``model`` the seat with ``read`` bets or raises
    after the flop, or None when the read has no postflop numbers."""
    if not read or "postflop" not in read or "aggression" not in model:
        return None
    seen = float(read["postflop"])
    weight = seen / (seen + AGGRESSION_PRIOR)
    share = weight * float(read["aggression"]) + (1 - weight) * model["aggression"]
    low, high = FACTOR_RANGE
    return min(max(share / model["aggression"], low), high)


class Unread(_Policy):
    """A policy that does not see the reads (``noreads+name``)."""

    def __init__(self, base, name):
        self.base, self.name = base, name

    def decide(self, observation, rng):
        if "reads" in observation:
            observation = {key: value for key, value in observation.items()
                           if key != "reads"}
        return self.base.decide(observation, rng)


__all__ = ["AGGRESSION_PRIOR", "FACTOR_RANGE", "MEASURE_DEALS", "MODEL", "READ_PRIOR",
           "aggression_factor", "factors", "measure", "sample", "Unread"]
