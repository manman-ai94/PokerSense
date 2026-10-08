"""Preflop play for the AA table from expected values, not a fixed chart.

At every preflop decision the policy works out, in chips, what folding (or
checking), calling and raising are worth from the table as it is: the pot
with its antes, straddle and bets, the price to call, the stacks, how many
players are still to act and from where. So the same policy plays a 1/2/4
table, a 2/4/8 one, six or eight players, or a deeper stack without new
charts. Postflop it plays like the population bot: on the scoreboard that
beats the tag rules ``rfi_table`` uses by about 125 bb/100, and the tag rules
lose badly with the wider ranges this policy plays.

How the other players respond comes from the real-player statistics the
population bot uses: in each spot and position a share of hands raises, the
next share calls, the rest folds, and a player's range is the band of hands
its own earlier actions leave it with. ``aa_preflop`` expects the AA players'
shares (``aa_population``: far looser than the 2009 games), ``aa_preflop_phh``
the 2009 players' (``population``).
The policy's own hand is compared with those ranges through a heads-up
equity table between the 169 hand classes (``preflop_equity_v1.json``).

The values (all relative to folding now, whose value is 0):

* raise to T: if nobody re-raises, every combination of who calls and who
  folds is counted (players act independently, by their shares); when all
  fold the pot is won (less rake), otherwise the hand is worth
  ``R x equity x pot`` minus the chips put in, against the callers' ranges.
  If someone re-raises, the policy folds or calls, whichever is worth more.
  An all-in raise is not re-raised and is worth its equity in full.
* call (or limp): the same against the players already in for the full bet
  and every combination of players behind who call too. A raise behind (by
  their raise shares) is assumed to make the policy fold and lose the call.
* check (when free): ``R x equity x pot``.

Equity against several players combines the heads-up equities (see
``multiway``).

``R`` is equity realisation: how much of its showdown equity a hand keeps
when the hand is played out after the flop. It is higher in position and for
suited hands and pairs, lower with more opponents; its values are the
policy's few tuned parameters
(``PreflopParams``), set on the scoreboard.

A live table can pass ``mushroom_pool`` (chips) in the observation: the small
blind wins that pool with the pot, so it counts as extra pot for that seat.

It can also pass ``reads`` ({seat: {"hands", "vpip", "pfr"}}, see ``reads``):
how often each opponent has put chips in and raised so far. A seat that
raises more often than the statistics say gets its raise shares (and the
ranges its raises leave it with) widened by that much, and the same for
its calls, so a maniac's raise is not read as a regular's. Only a seat's
first decision of the hand is scaled: what share of its range continues
after that (against a re-raise, say) stays the statistics' own, so a tight
player's narrower range also continues with stronger hands.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, fields, replace
from functools import lru_cache
from importlib import resources
from itertools import accumulate
import json
import math

from poker_engine.core.enums import Position

from .bots import _Policy, position, raise_toward, raises_this_street
from .population import MAX_CONTINUE, NAMES, PopulationBot, actions, preflop_shares
from .reads import MODEL, factors
from .spots import preflop_spot
from .strength import class_combos, hand_class, preflop_table

EQUITY_FILE = "preflop_equity_v1.json"
COMBOS = 1326
MIN_CHANCE = 0.005      # a player calling less often than this is left out
CACHE_SIZE = 50_000     # decisions kept (per public state and hand class)


@dataclass(frozen=True)
class PreflopParams:
    realize_ip: float = 1.0     # equity realisation in position after the flop
    realize_oop: float = 0.8    # out of position
    suited: float = 0.05        # added for suited hands
    pair: float = 0.0           # added for pairs
    crowd: float = 0.05         # taken off for each opponent after the first
    open_size: float = 0.5      # first raise: pot fraction (as the other bots)
    raise_size: float = 1.0     # re-raises
    jam_share: float = 0.4      # raise all in when a raise would put in this
    #                             share of the stack anyway


class EquityTable:
    """Heads-up equity of a hand class against a band of hand percentiles."""

    def __init__(self, data):
        self.classes = data["classes"]
        self.index = {name: i for i, name in enumerate(self.classes)}
        # Villain classes in strength order, each covering a band of percentiles
        # (the stored percentiles are rounded; the bands add up exactly).
        strength = preflop_table()["classes"]
        if self.classes != sorted(self.classes, key=lambda n: strength[n]["rank"]):
            raise ValueError("equity table classes are not in strength order")
        self.widths = [class_combos(name) / COMBOS for name in self.classes]
        self.tops = list(accumulate(self.widths))
        self.equity = data["equity"]
        self.weights = data["compatible_combos"]
        self.prefix = []
        for i in range(len(self.classes)):
            weight, value, rows = 0.0, 0.0, [(0.0, 0.0)]
            for j in range(len(self.classes)):
                weight += self.weights[i][j]
                value += self.weights[i][j] * self.equity[i][j]
                rows.append((weight, value))
            self.prefix.append(rows)

    def _cumulative(self, i, point):
        """(weight, weight x equity) of villain hands with percentile below point."""
        point = min(max(point, 0.0), 1.0)
        k = bisect_right(self.tops, point)
        weight, value = self.prefix[i][k]
        if k < len(self.classes):
            start = self.tops[k] - self.widths[k]
            part = max(0.0, point - start) / self.widths[k]
            weight += part * self.weights[i][k]
            value += part * self.weights[i][k] * self.equity[i][k]
        return weight, value

    def versus(self, name, low, high):
        i = self.index[name]
        if high <= low:
            high = min(1.0, low + 1.0 / COMBOS)
        w0, v0 = self._cumulative(i, low)
        w1, v1 = self._cumulative(i, high)
        return (v1 - v0) / (w1 - w0) if w1 > w0 else 0.5


@lru_cache(maxsize=1)
def equity_table():
    data = resources.files("poker_engine.scoreboard").joinpath(EQUITY_FILE)
    return EquityTable(json.loads(data.read_text(encoding="utf-8")))


def _odds(value):
    value = min(max(value, 1e-6), 1 - 1e-6)
    return (1 - value) / value


def multiway(equities):
    """Share of the pot against several players from the heads-up equities.

    Each opponent's strength relative to the hand is its odds of winning heads
    up; the hand's share is 1 / (1 + the sum). Exact heads up, and close for
    three-way pots (any two hands against two random ones: 1/3).
    """
    return 1 / (1 + sum(_odds(value) for value in equities))


def stats_name(observation, seat):
    """Position whose real-player frequencies ``seat`` uses (as the population bot)."""
    seat_position = position(observation, seat)
    if observation.get("straddler_seat") is not None:
        if seat == observation["straddler_seat"]:
            return "BB"
        if seat_position == Position.BB:
            return "SB"
    return NAMES[seat_position]


def read_shares(raise_share, call_share, read=(1.0, 1.0)):
    """(raise, call) shares scaled by a seat's read factors (see ``reads``)."""
    raise_factor, call_factor = read
    if raise_factor == call_factor == 1.0:
        return raise_share, call_share
    raise_share = min(raise_share * raise_factor, MAX_CONTINUE)
    return raise_share, min(call_share * call_factor, MAX_CONTINUE - raise_share)


def band(history, seat, name, adjusted=True, read=(1.0, 1.0)):
    """The band of hand percentiles ``seat``'s preflop actions leave it with.

    ``read``: the seat's (raise, call) factors from ``reads.factors``, for
    its first decision.
    """
    low, high = 0.0, 1.0
    for index, (player, kind) in enumerate(history):
        if player != seat:
            continue
        raise_share, call_share = read_shares(*preflop_shares(
            name, preflop_spot(history[:index], seat), adjusted), read)
        read = (1.0, 1.0)
        width = high - low
        if kind == "r":
            high = low + raise_share * width
        elif kind == "c":
            low, high = (low + raise_share * width,
                         low + (raise_share + call_share) * width)
    return low, high


def situation(observation):
    """Everything public a preflop decision depends on, as a hashable key."""
    rules = (observation.get("rules_fingerprint")
             or json.dumps(observation["rules"], sort_keys=True))
    return (rules, observation["observing_seat"], observation["dealer_seat"],
            observation.get("straddler_seat"), tuple(observation["occupied_seats"]),
            tuple(sorted(observation["folded"])), observation["pot"],
            observation["to_call"], tuple(sorted(observation["bets"].items())),
            tuple(sorted(observation["stacks"].items())),
            tuple((row["actor"], row["id"]) for row in observation["public_history"]),
            tuple(a["id"] for a in observation["legal_actions"]),
            observation.get("mushroom_pool"),
            json.dumps(observation.get("reads"), sort_keys=True))


def postflop_order(observation, seat):
    """Place in the postflop order: 0 acts first (small blind), larger acts later."""
    occupied = observation["occupied_seats"]
    start = occupied.index(observation["dealer_seat"])
    clockwise = occupied[start + 1:] + occupied[:start + 1]
    return clockwise.index(seat)


def rake(observation, pot):
    rules = observation["rules"]
    percent = float(rules["rake_percent"])
    if not percent:
        return 0.0
    chip = float(rules["minimum_chip"])
    cap = float(rules["rake_cap_bb"]) * float(rules["big_blind"])
    taken = math.floor(percent * pot / chip + 1e-9) * chip
    return min(taken, cap)


class AAPreflopPolicy(_Policy):
    """Preflop by expected value against the population's ranges."""

    def __init__(self, params=None, name="aa_preflop", adjusted=True):
        self.name = name
        self.params = params or PreflopParams()
        self.adjusted = adjusted        # expect AA players (else 2009 players)
        self.postflop = PopulationBot()
        self._choices = {}

    def decide(self, observation, rng):
        if observation["street"] == "preflop":
            return self.choose(observation)["action"]
        return self.postflop.decide(observation, rng)

    def choose(self, observation):
        """The action taken, the value of each option (chips) and the amount
        a raise would raise to (None when no raise is possible).

        Decisions depend on the hand only through its class, so they are kept
        per public state and class: a solver strategy replaying its own
        range asks about all 1326 hands at each of its decisions.
        """
        key = (situation(observation), hand_class(observation["own_hole"]))
        if key not in self._choices:
            if len(self._choices) >= CACHE_SIZE:
                self._choices.clear()
            self._choices[key] = self._choose(observation)
        kept = self._choices[key]
        return {**kept, "values": dict(kept["values"])}

    def _choose(self, observation):
        table = Table(observation, self.params, self.adjusted)
        values = {"fold" if table.to_call else "check": table.passive_value()}
        if table.to_call:
            values["call"] = table.call_value()
        raise_action = table.raise_action()
        if raise_action is not None:
            values["raise"] = table.raise_value(raise_action[1])
        best = max(values, key=lambda key: (values[key], key in ("fold", "check")))
        action = {"fold": "fold", "check": "check_call", "call": "check_call"}.get(best)
        if best == "raise":
            action = raise_action[0]
        return {"action": action, "values": values,
                "raise_to": raise_action[1] if raise_action else None}


class Table:
    """One preflop decision: the public state as numbers, and its values."""

    def __init__(self, observation, params, adjusted=True):
        self.o = observation
        self.p = params
        self.adjusted = adjusted
        self.me = observation["observing_seat"]
        self.hand = hand_class(observation["own_hole"])
        self.pot = float(observation["pot"])
        self.bets = {int(seat): float(value)
                     for seat, value in observation["bets"].items()}
        self.stacks = {int(seat): float(value)
                       for seat, value in observation["stacks"].items()}
        self.to_call = float(observation["to_call"] or 0)
        self.top = max(self.bets.values())
        self.history = actions(observation, "preflop")
        self.raised = raises_this_street(observation) > 0
        folded = set(observation["folded"])
        self.live = [seat for seat in observation["occupied_seats"]
                     if seat not in folded and seat != self.me]
        self.acted = {player for player, _ in self.history}
        self.equities = equity_table()
        self.bonus = 0.0
        if (observation.get("mushroom_pool")
                and position(observation) == Position.SB):
            self.bonus = float(observation["mushroom_pool"])
        model = MODEL["aa_population" if adjusted else "population"]
        reads = observation.get("reads") or {}
        self.reads = {seat: factors(reads.get(str(seat)), model)
                      for seat in observation["occupied_seats"]}

    # -- pieces ---------------------------------------------------------------

    def name(self, seat):
        return stats_name(self.o, seat)

    def shares(self, seat, history):
        first = all(player != seat for player, _ in history)
        raise_share, call_share = read_shares(*preflop_shares(
            self.name(seat), preflop_spot(history, seat), self.adjusted),
            self.reads[seat] if first else (1.0, 1.0))
        return raise_share, call_share, max(0.0, 1 - raise_share - call_share)

    def band(self, seat):
        return band(self.history, seat, self.name(seat), self.adjusted,
                    self.reads[seat])

    def equity(self, low, high):
        return self.equities.versus(self.hand, low, high)

    def realize(self, opponents, all_in=False):
        if all_in:
            return 1.0
        mine = postflop_order(self.o, self.me)
        last = all(mine > postflop_order(self.o, seat) for seat in opponents)
        value = self.p.realize_ip if last else self.p.realize_oop
        value -= self.p.crowd * max(0, len(opponents) - 1)
        if len(self.hand) == 2:
            value += self.p.pair
        elif self.hand.endswith("s"):
            value += self.p.suited
        return value

    def won(self, pot, share):
        """Chips back from a pot the hand wins ``share`` of (less rake)."""
        return share * (pot - rake(self.o, pot) + self.bonus)

    def joins(self, seat, level):
        """Chips ``seat`` adds to call up to ``level`` (all of it if short)."""
        return min(level, self.bets[seat] + self.stacks[seat]) - self.bets[seat]

    def behind(self):
        """Players who still act on this round if nobody raises again."""
        return [seat for seat in self.live
                if self.stacks.get(seat, 0) > 0
                and (self.bets[seat] < self.top or seat not in self.acted)]

    # -- values ---------------------------------------------------------------

    def passive_value(self):
        if self.to_call:
            return 0.0
        # A free check closes the round: see the flop against everyone in.
        return self.field({seat: self.band(seat) for seat in self.live}, [],
                          self.pot, 0.0, False)

    def call_value(self):
        price = min(self.to_call, self.stacks[self.me])
        fixed = {seat: self.band(seat) for seat in self.live
                 if self.bets[seat] >= self.top}
        all_in = price >= self.stacks[self.me] or all(
            self.stacks.get(seat, 0) == 0 for seat in fixed)
        after = self.history + [(self.me, "c")]
        clear, chances = 1.0, []
        for seat in self.behind():
            if seat in fixed:
                continue
            raise_share, call_share, _ = self.shares(seat, after)
            clear *= 1 - raise_share
            if call_share > MIN_CHANCE and raise_share < 1:
                low, high = self.band(seat)
                width = high - low
                chips = self.joins(seat, self.top)
                chances.append((seat, call_share / (1 - raise_share),
                                (low + raise_share * width,
                                 low + (raise_share + call_share) * width), chips))
        called = self.field(fixed, chances, self.pot + price, price, all_in)
        return clear * called - (1 - clear) * price

    def raise_action(self):
        raises = [a for a in self.o["legal_actions"] if a["kind"] == "raise_to"]
        if not raises:
            return None
        size = self.p.raise_size if self.raised else self.p.open_size
        chosen = raise_toward(self.o, size)
        amount = float(next(a["raise_to"] for a in raises if a["id"] == chosen))
        mine = self.bets[self.me] + self.stacks[self.me]
        if amount - self.bets[self.me] >= self.p.jam_share * mine:
            top = max(raises, key=lambda a: float(a["raise_to"]))
            chosen, amount = top["id"], float(top["raise_to"])
        return chosen, amount

    def raise_value(self, target):
        mine = self.bets[self.me]
        added = target - mine
        all_in = added >= self.stacks[self.me]
        after = self.history + [(self.me, "r")]
        uncalled = self.pot + self.to_call
        won_now = self.won(uncalled, 1.0) - (uncalled - self.pot)
        no_raise, chances, reraises = 1.0, [], []
        for seat in self.live:
            if self.stacks.get(seat, 0) <= 0:
                continue
            raise_share, call_share, _ = self.shares(seat, after)
            low, high = self.band(seat)
            width = high - low
            if all_in:      # nobody re-raises an all in: both parts call
                raise_share, call_share = 0.0, raise_share + call_share
                cut = (low, low + call_share * width)
            else:
                cut = (low + raise_share * width,
                       low + (raise_share + call_share) * width)
            no_raise *= 1 - raise_share
            if raise_share > 0:
                reraises.append((raise_share, seat,
                                 (low, low + raise_share * width)))
            if call_share > MIN_CHANCE and raise_share < 1:
                chips = self.joins(seat, target)
                chances.append((seat, call_share / (1 - raise_share), cut, chips))
        value = self.field({}, chances, self.pot + added, added, all_in, won_now)
        if not reraises:
            return value
        weight = sum(share for share, _, _ in reraises)
        facing = sum(share * self.reraised(seat, target, cut)
                     for share, seat, cut in reraises) / weight
        return no_raise * value + (1 - no_raise) * facing

    def field(self, fixed, chances, pot, cost, all_in, alone=0.0):
        """Expected value of putting in ``cost`` more chips, for a pot of ``pot``.

        The players in ``fixed`` ({seat: band}) are in the pot; each of
        ``chances`` ((seat, chance, band, chips)) joins it with its chance,
        independently, adding its chips. Every combination of who joins is
        counted; ``alone`` is the value if nobody is in.
        """
        odds = {}
        for seat, cut in fixed.items():
            odds[seat] = _odds(self.equity(*cut))
        for seat, _, cut, _ in chances:
            odds[seat] = _odds(self.equity(*cut))
        total = 0.0
        for mask in range(1 << len(chances)):
            chance, extra, seats = 1.0, 0.0, list(fixed)
            for index, (seat, joins, _, chips) in enumerate(chances):
                if mask >> index & 1:
                    chance *= joins
                    extra += chips
                    seats.append(seat)
                else:
                    chance *= 1 - joins
            if chance < 1e-7:
                continue
            if not seats:
                total += chance * alone
                continue
            share = 1 / (1 + sum(odds[seat] for seat in seats))
            total += chance * (self.won(pot + extra,
                                        self.realize(seats, all_in) * share) - cost)
        return total

    def reraised(self, seat, target, cut):
        """Value when ``seat`` re-raises: fold, or call if that is worth more."""
        mine = self.bets[self.me]
        pot = self.pot + (target - mine) + (target - self.bets[seat])
        cap = min(self.bets[seat] + self.stacks[seat],
                  mine + self.stacks[self.me])
        again = min(cap, target + pot)            # a pot-size re-raise
        total = (self.pot + (target - mine) + (again - self.bets[seat])
                 + (again - target))
        all_in = again >= cap
        share = self.realize([seat], all_in) * self.equity(*cut)
        calling = self.won(total, share) - (again - mine)
        return max(-(target - mine), calling)


def from_name(name):
    """``aa_preflop`` (or ``aa_preflop_phh``), with parameters for tuning runs:
    ``aa_preflop@realize_ip=0.9:suited=0.1``."""
    base, _, settings = name.partition("@")
    if base not in ("aa_preflop", "aa_preflop_phh"):
        raise ValueError(f"unknown policy: {name}")
    known = {field.name for field in fields(PreflopParams)}
    changes = {}
    for item in filter(None, settings.split(":")):
        key, _, value = item.partition("=")
        if key not in known:
            raise ValueError(f"unknown preflop parameter: {key}")
        changes[key] = float(value)
    return AAPreflopPolicy(replace(PreflopParams(), **changes), name=name,
                           adjusted=base == "aa_preflop")


__all__ = ["AAPreflopPolicy", "EquityTable", "PreflopParams", "band", "equity_table",
           "from_name", "multiway", "postflop_order", "rake", "read_shares",
           "stats_name"]
