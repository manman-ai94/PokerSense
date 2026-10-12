"""Starting stacks of different depths on the scoreboard.

The standard scoreboard starts every player of every hand with 100 big
blinds, so every all-in is for the same amount and there are never side
pots: a change to how all-ins and side pots are valued cannot show there.
With ``Stacks`` every deal gives each seat its own starting stack, drawn from
the deal's seed, so every strategy and every hero seat of a deal plays the
same stacks and runs are reproducible:

* ``Stacks(25, 250)``: each seat independently uniform between 25 and 250
  big blinds, in whole chips;
* ``Stacks(choices=(25, 40, 60, 100, 150, 250))``: each seat one of these.

Results stay in big blinds of the table; the deeper stacks make them vary
more. Opponent reads (``reads.measure``) are still measured at 100 big blinds.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
import random


@dataclass(frozen=True)
class Stacks:
    low: float = 25.0       # big blinds, inclusive
    high: float = 250.0
    choices: tuple = ()     # big blinds to pick from instead of low..high

    def __post_init__(self):
        object.__setattr__(self, "choices", tuple(self.choices))
        if self.choices:
            if any(value <= 0 for value in self.choices):
                raise ValueError("stack choices must be positive")
        elif not 0 < self.low <= self.high:
            raise ValueError("stacks need 0 < low <= high")

    @classmethod
    def parse(cls, text):
        """``"25-250"`` (uniform) or ``"25,40,100"`` (choices), in big blinds."""
        if "-" in text:
            low, high = text.split("-", 1)
            return cls(float(low), float(high))
        return cls(choices=tuple(float(value) for value in text.split(",")))

    @property
    def smallest(self):
        return min(self.choices) if self.choices else self.low

    def chips(self, seed, seats, big_blind, minimum_chip=1):
        """{seat: starting stack in chips (a string, as the arena takes money)}
        for deal ``seed``."""
        big_blind, chip = Decimal(str(big_blind)), Decimal(str(minimum_chip))
        rng = random.Random(seed * 7_919 + 29)
        stacks = {}
        for seat in seats:
            if self.choices:
                amount = Decimal(str(rng.choice(self.choices))) * big_blind
                if amount % chip:
                    raise ValueError("a stack choice is not a whole chip")
            else:
                low = (Decimal(str(self.low)) * big_blind / chip).to_integral_value(
                    ROUND_CEILING)
                high = (Decimal(str(self.high)) * big_blind / chip).to_integral_value(
                    ROUND_FLOOR)
                if low > high:
                    raise ValueError("no whole-chip stack between low and high")
                amount = rng.randint(int(low), int(high)) * chip
            stacks[seat] = f"{amount.normalize():f}"
        return stacks

    def to_dict(self):
        if self.choices:
            return {"choices_big_blinds": list(self.choices)}
        return {"low_big_blinds": self.low, "high_big_blinds": self.high}

    @classmethod
    def from_dict(cls, data):
        if "choices_big_blinds" in data:
            return cls(choices=tuple(data["choices_big_blinds"]))
        return cls(data["low_big_blinds"], data["high_big_blinds"])


__all__ = ["Stacks"]
