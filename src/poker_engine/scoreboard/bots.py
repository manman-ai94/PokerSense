"""Scoreboard policies: simple baselines and four player styles.

Every policy follows the arena contract: ``for_game(salt)`` returns a pure
function from one observation to an action id. Random choices are drawn from
the salt and the public state, so the same observation always gets the same
action and paired runs stay paired.

Styles (shares are of all starting hands, by combinations):

| style   | opens | 3-bets | plays postflop                                 |
|---------|-------|--------|------------------------------------------------|
| tag     | 16%   | 5%     | bets with good equity, folds without odds      |
| lag     | 32%   | 10%    | bets and bluffs often                          |
| rock    | 10%   | 2.5%   | bets only very strong hands                    |
| station | 6%    | 2%     | limps and calls far too much, rarely raises   |
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random

from poker_engine.core.enums import Position
from poker_engine.strategy.aa_rules_v2 import _POSITIONS
from poker_engine.strategy.heuristic_provider import PreflopRfiHeuristicProvider

from .strength import equity, hand_class, preflop_percentile

POSTFLOP_TRIALS = 150
MAX_EQUITY_OPPONENTS = 3


def _rng(salt, observation):
    key = "|".join((salt, observation["street"],
                    str(len(observation["public_history"])),
                    ",".join(observation["board"]), ",".join(observation["own_hole"])))
    digest = hashlib.sha256(key.encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def position(observation, seat=None):
    seat = observation["observing_seat"] if seat is None else seat
    occupied = observation["occupied_seats"]
    start = occupied.index(observation["dealer_seat"])
    clockwise = occupied[start:] + occupied[:start]
    return _POSITIONS[len(occupied)][clockwise.index(seat)]


def raises_this_street(observation):
    return sum(1 for row in observation["public_history"]
               if row["street"] == observation["street"] and row["kind"] == "raise_to")


def opponents_in_hand(observation):
    return len(observation["occupied_seats"]) - len(observation["folded"]) - 1


def _sizes(observation):
    return [action for action in observation["legal_actions"]
            if action["kind"] == "raise_to"]


def raise_toward(observation, pot_fraction):
    """Legal raise closest to a bet of ``pot_fraction`` of the pot after calling."""
    raises = _sizes(observation)
    if not raises:
        return None
    to_call = float(observation["to_call"] or 0)
    current = max(float(value) for value in observation["bets"].values())
    target = current + pot_fraction * (float(observation["pot"]) + to_call)
    return min(raises, key=lambda action: abs(float(action["raise_to"]) - target))["id"]


def passive(observation):
    """Check if possible, otherwise fold."""
    return "check_call" if float(observation["to_call"] or 0) == 0 else "fold"


class _Policy:
    name = "policy"

    def for_game(self, salt):
        def policy(observation):
            return self.decide(observation, _rng(salt, observation))
        return policy

    def decide(self, observation, rng):
        raise NotImplementedError


class AlwaysCall(_Policy):
    """Never folds, never raises: calls or checks every time."""
    name = "always_call"

    def decide(self, observation, rng):
        return "check_call"


class RandomPolicy(_Policy):
    """Folds, calls or raises (any size) with equal chance."""
    name = "random"

    def decide(self, observation, rng):
        choice = rng.choice(("fold", "call", "raise"))
        if choice == "fold" and float(observation["to_call"] or 0) > 0:
            return "fold"
        raises = _sizes(observation)
        if choice == "raise" and raises:
            return rng.choice(raises)["id"]
        return "check_call"


@dataclass(frozen=True)
class Style:
    open: float          # unopened pot: raise with this share of hands
    limp: float          # unopened pot: call (limp) up to this share
    three_bet: float     # facing one raise: re-raise
    flat: float          # facing one raise: call
    four_bet: float      # facing two or more raises: raise
    call_three_bet: float
    value: float         # postflop equity to bet when checked to
    raise_equity: float  # postflop equity to raise a bet
    bluff: float         # chance to bet when checked to without value
    call_margin: float   # call when equity >= pot odds + margin


STYLES = {
    "tag": Style(.16, .16, .05, .10, .02, .03, .62, .78, .12, .00),
    "lag": Style(.32, .32, .10, .18, .04, .06, .55, .72, .25, -.03),
    "rock": Style(.10, .10, .025, .08, .015, .02, .72, .85, .03, .05),
    "station": Style(.06, .50, .02, .40, .01, .25, .80, .90, .02, -.12),
}


class StyleBot(_Policy):
    def __init__(self, name):
        self.name = name
        self.style = STYLES[name]

    def decide(self, observation, rng):
        if observation["street"] == "preflop":
            return self.preflop(observation, rng)
        return self.postflop(observation, rng)

    def preflop(self, observation, rng):
        style, share = self.style, preflop_percentile(observation["own_hole"])
        raises = raises_this_street(observation)
        if raises == 0:
            if share <= style.open:
                return raise_toward(observation, 0.5) or "check_call"
            return "check_call" if share <= style.limp else passive(observation)
        if raises == 1:
            if share <= style.three_bet:
                return raise_toward(observation, 1.0) or "check_call"
            return "check_call" if share <= style.flat else passive(observation)
        if share <= style.four_bet:
            return raise_toward(observation, 2.0) or "check_call"
        return "check_call" if share <= style.call_three_bet else passive(observation)

    def postflop(self, observation, rng):
        style = self.style
        win = equity(observation["own_hole"], observation["board"],
                     min(opponents_in_hand(observation), MAX_EQUITY_OPPONENTS),
                     POSTFLOP_TRIALS, rng)
        to_call = float(observation["to_call"] or 0)
        if to_call == 0:
            if win >= style.value or rng.random() < style.bluff:
                return raise_toward(observation, 0.66) or "check_call"
            return "check_call"
        odds = to_call / (float(observation["pot"]) + to_call)
        if win >= style.raise_equity:
            return raise_toward(observation, 1.0) or "check_call"
        if win >= odds + style.call_margin:
            return "check_call"
        if rng.random() < style.bluff / 3:
            return raise_toward(observation, 1.0) or "fold"
        return "fold"


class RfiTablePolicy(StyleBot):
    """Current project preflop open-raise table, completed with simple rules.

    Unopened pots follow the repository's 8-handed open-raise chart (derived
    from its 9-handed chart). Facing raises and postflop play are not covered
    by that chart, so they follow the tag style's rules.
    """

    def __init__(self):
        super().__init__("tag")
        self.name = "rfi_table"
        self.provider = PreflopRfiHeuristicProvider.from_builtin()

    def preflop(self, observation, rng):
        if raises_this_street(observation) == 0:
            seat_position = position(observation)
            resolved = self.provider.resolve_range(len(observation["occupied_seats"]),
                                                   seat_position)
            if resolved is not None:
                if hand_class(observation["own_hole"]) in resolved[0]:
                    return raise_toward(observation, 0.5) or "check_call"
                return passive(observation)
            if seat_position == Position.BB:
                return passive(observation)
        return super().preflop(observation, rng)


class Split(_Policy):
    """One policy before the flop and another after it, named ``before/after``.

    Scoring ``rfi_table/population`` next to ``rfi_table`` shows how much of a
    strategy's result comes from its play after the flop.
    """

    def __init__(self, before, after):
        self.name = f"{before.name}/{after.name}"
        self.before, self.after = before, after

    def decide(self, observation, rng):
        part = self.before if observation["street"] == "preflop" else self.after
        return part.decide(observation, rng)


def make_policy(name):
    if name.startswith("nomushroom+"):
        from .mushroom import Blind              # imports this module
        return Blind(make_policy(name.partition("+")[2]), name)
    if name.startswith("range_multiway") and "+" in name:
        from .multiway_bot import from_name      # imports this module
        return from_name(name, make_policy)
    if name.startswith("solver_") and "+" in name:
        # "solver_flop+aa_preflop": the solver strategy on another base policy
        from .solver_bot import SolverBot       # needs TexasSolver installed
        streets, _, base = name.partition("+")
        bot = SolverBot(streets, base=make_policy(base))
        bot.name = name
        return bot
    if "/" in name:
        before, after = name.split("/", 1)
        return Split(make_policy(before), make_policy(after))
    if name == "aa_real":
        from .aa_real import AARealBot          # imports this module
        return AARealBot()
    if name in OPPONENT_NAMES:
        from .opponents import ToughBot         # imports this module
        return ToughBot(name)
    if name in ("population", "aa_population"):
        from .population import PopulationBot   # imports this module
        return PopulationBot(adjusted=name == "aa_population")
    if name.startswith("aa_preflop"):
        from .preflop_policy import from_name    # imports this module
        return from_name(name)
    if name.startswith("solver_"):
        from .solver_bot import SolverBot       # needs TexasSolver installed
        return SolverBot(name)
    if name == "always_call":
        return AlwaysCall()
    if name == "random":
        return RandomPolicy()
    if name == "rfi_table":
        return RfiTablePolicy()
    if name in STYLES:
        return StyleBot(name)
    raise ValueError(f"unknown policy: {name}")


POLICY_NAMES = ("always_call", "random", "rfi_table", "aa_preflop", *STYLES,
                "population", "aa_population")
# Tougher opponents (see opponents.py), kept out of the default strategy list;
# "aa_real" (aa_real.py) plays like the AA players measured on recordings.
OPPONENT_NAMES = ("reg", "maniac", "nit")

__all__ = ["OPPONENT_NAMES", "POLICY_NAMES", "STYLES", "Split", "StyleBot",
           "make_policy", "position", "raise_toward"]
