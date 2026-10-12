"""How a seat's preflop actions narrow its range, for reading it.

The population model (``population``) plays "honestly": in a spot where a
share r of players raise and c call, it raises with its strongest r of hands,
calls with the next c and folds the rest. Reading a real player with it, a
call keeps only that middle band: the strongest hands, which the model always
raises, are gone for the rest of the hand. A player who limps (or flats) and
then re-raises was therefore read as the top of his calling band only (with
AA players' shares: A7s, A8s, A9o, KQo), never AA, KK, QQ or AK, though the
limp-raise is the classic slow-played big hand; against such a re-raise the
AI pushed medium hands all in.

The reading here keeps two things the model leaves out:

* **slow play**: at a call (or a check), the hands the model would have
  raised stay in with weight ``SLOWPLAY`` instead of 0;
* **bluffs after calling**: a raise by a seat that has already called on
  this round (``AFTER_CALL``: limp then raise, call then re-raise) holds,
  next to the strongest hands of its range, a share ``BLUFF`` of hands its
  range would otherwise fold.

Everything else is the model as it was: the measured shares of each spot and
position (and the reads' scaling of a seat's first decision) are applied to
the range the seat has, strongest first by weight, so the share of a range
that re-raises after a limp is still the measured one; it is just made of the
slow-played hands first.

``SLOWPLAY`` and ``BLUFF``. With the AA players' shares (a first-in player
raises 16% of hands and limps 34%; 4 of 71 limpers re-raised when raised,
``aa_preflop_stats_v1.json``) a limp-raise is about 2% of all hands. Slow
play of a share s of the raising hands puts 16% x s of all hands in the limp
range, so s = 0.1 is the least for slow-played hands alone to make up the
limp-raises, and then they are the whole raising range down to its weakest
(A8o, K9s). A larger s keeps the measured share and makes it the top of
that range: the re-raises are the top 2% / s of hands, and the other
slow-played hands just call the raise. At 0.4 that is the top 5.6% (77+,
AK, AQs, AJs) and aces, kings, queens and AK are about a third of a
limp-raise range; at 0.3 the top 7% and a quarter. The 2009 games' calls of
an open followed by a re-raise fit s of about 0.1 the same way. ``BLUFF``: a
fifth of the raises are weak hands, "a few bluffs". On synthetic 2/4/8 hands
at 100 big blinds (``tests/scoreboard/test_preflop_reading.py``) 0.4 is the
least slow play (of 0.1 to 0.5) at which no medium hand (AQs, KQo, A9o, QJo,
A3s) shoves into a limp-raise from the button, while AA and KK still do.

Ranges are weights over hand percentiles (0 = strongest, as
``strength.combo_percentile``): ``Range``. ``seat_range`` is the range a
seat's actions so far leave it with, ``split`` how a range plays a spot.
The population model itself (the scoreboard's ``aa_population`` players) is
not changed: it still plays honestly. ``PopulationReader`` is the model as a
reader, for ``ranges.opponent_ranges`` and the solver strategies.
"""

from __future__ import annotations

from functools import lru_cache

from .population import (PopulationBot, actions, preflop_shares, read_shares,
                         stats_position)
from .spots import preflop_spot
from .strength import combo_percentile

SLOWPLAY = 0.4      # weight a call keeps on the hands the model raises
BLUFF = 0.2         # share of bluffs in a raise after calling
AFTER_CALL = ("limp_vs_raise", "call_vs_3bet")
HONEST = (0.0, 0.0)


class Range:
    """Weights over hand percentiles: ``parts`` are (low, high, weight),
    disjoint and strongest first. The weight of a band is its width times
    its weight (the width is a share of all 1326 hands)."""

    __slots__ = ("parts",)

    def __init__(self, parts=((0.0, 1.0, 1.0),)):
        self.parts = tuple(sorted((float(low), float(high), float(weight))
                                  for low, high, weight in parts
                                  if high > low and weight > 0))

    def __repr__(self):
        return f"Range({list(self.parts)})"

    def __eq__(self, other):
        return isinstance(other, Range) and self.parts == other.parts

    def __hash__(self):
        return hash(self.parts)

    def __add__(self, other):
        return Range(self.parts + other.parts)

    def mass(self):
        return sum((high - low) * weight for low, high, weight in self.parts)

    def cut(self, start, end):
        """The hands between ``start`` and ``end`` of the mass, counted from
        the strongest."""
        parts, before = [], 0.0
        for low, high, weight in self.parts:
            size = (high - low) * weight
            first, last = max(start, before), min(end, before + size)
            if last > first:
                parts.append((low + (first - before) / weight,
                              low + (last - before) / weight, weight))
            before += size
        return Range(parts)

    def scaled(self, factor):
        return Range((low, high, weight * factor) for low, high, weight in self.parts)

    def weight(self, point):
        for low, high, weight in self.parts:
            if low <= point < high:
                return weight
        return 0.0

    @property
    def low(self):
        return self.parts[0][0] if self.parts else 0.0

    @property
    def high(self):
        return self.parts[-1][1] if self.parts else 0.0


EVERY_HAND = Range()


def split(hands, raise_share, call_share, *, slowplay=SLOWPLAY, bluff=0.0):
    """{kind: Range} of ``hands`` that raise ("r"), call ("c") and fold ("f")
    where a share ``raise_share`` raises and ``call_share`` calls.

    The strongest ``raise_share`` of the weight raises, the next
    ``call_share`` calls; the calls also hold the raising hands at
    ``slowplay`` of their weight, and with ``bluff`` the raises hold that
    share of bluffs, spread over the hands that fold."""
    total = hands.mass()
    top = hands.cut(0.0, raise_share * total)
    middle = hands.cut(raise_share * total, (raise_share + call_share) * total)
    rest = hands.cut((raise_share + call_share) * total, total)
    raised = top
    if bluff and top.mass() > 0 and rest.mass() > 0:
        share = min(1.0, bluff / (1 - bluff) * top.mass() / rest.mass())
        raised = top + rest.scaled(share)
    return {"r": raised, "c": middle + top.scaled(slowplay), "f": rest}


@lru_cache(maxsize=20_000)
def _parts(history, seat, name, adjusted, read, reading):
    """``split`` of ``seat``'s range at its decision after ``history``."""
    slowplay, bluff = reading
    hands = EVERY_HAND
    for index, (player, kind) in enumerate(history + ((seat, None),)):
        if player != seat:
            continue
        spot = preflop_spot(history[:index], seat)
        raise_share, call_share = read_shares(
            *preflop_shares(name, spot, adjusted), read)
        read = (1.0, 1.0)
        parts = split(hands, raise_share, call_share, slowplay=slowplay,
                      bluff=bluff if spot in AFTER_CALL else 0.0)
        if kind is None:
            return parts
        hands = parts[kind]
    raise AssertionError("unreachable")


def decision_parts(history, seat, name, adjusted=True, read=(1.0, 1.0),
                   reading=(SLOWPLAY, BLUFF)):
    """{kind: Range} of how ``seat`` plays its next decision after
    ``history`` ((player, kind) pairs, ``population.actions``).

    ``name``: the position whose shares it uses (``stats_position``);
    ``read``: its (raise, call) factors from ``reads.factors``, for its first
    decision; ``reading``: (slow play, bluff), ``HONEST`` for the model's
    own play."""
    return _parts(tuple(history), seat, name, adjusted, tuple(read), tuple(reading))


def seat_range(history, seat, name, adjusted=True, read=(1.0, 1.0),
               reading=(SLOWPLAY, BLUFF)):
    """The Range ``seat``'s actions in ``history`` leave it with."""
    mine = [index for index, (player, _) in enumerate(history) if player == seat]
    if not mine:
        return EVERY_HAND
    last = mine[-1]
    kind = history[last][1]
    return decision_parts(history[:last], seat, name, adjusted, read, reading)[kind]


class PopulationReader(PopulationBot):
    """The population model as a reader of ranges, not a player.

    Before the flop ``decide`` returns {kind: chance}: how often the hand
    takes each action in this reading (``solver_bot.kept`` multiplies a
    range by it). After the flop it is the population model."""

    name = "population_reader"

    def __init__(self, adjusted=False, slowplay=SLOWPLAY, bluff=BLUFF):
        super().__init__(adjusted=adjusted)
        self.name = "aa_population_reader" if adjusted else "population_reader"
        self.reading = (slowplay, bluff)

    def preflop(self, observation):
        me = observation["observing_seat"]
        read = tuple(observation.get("read_factors") or (1.0, 1.0))
        parts = decision_parts(actions(observation, "preflop"), me,
                               stats_position(observation), self.adjusted, read,
                               self.reading)
        point = combo_percentile(observation["own_hole"])
        weights = {kind: part.weight(point) for kind, part in parts.items()}
        if not float(observation["to_call"] or 0):
            # Nothing to call: the model checks the hands it would fold.
            weights["c"] = max(weights["c"], weights.pop("f"))
        # The parts split the range by region, so the hand's weight before
        # the decision is its largest weight in them.
        before = max(weights.values())
        return {kind: weight / before for kind, weight in weights.items()
                if before and weight}


def reading_of(policy):
    """(slow play, bluff) a policy reads ranges with: its preflop parameters'
    (``aa_preflop@slowplay=0:bluff=0`` reads as the model plays), else the
    defaults."""
    params = getattr(policy, "params", None)
    if hasattr(params, "slowplay"):
        return params.slowplay, params.bluff
    return SLOWPLAY, BLUFF


def reading_model(adjusted=False, reading=(SLOWPLAY, BLUFF)):
    """The model that reads opponents' ranges: honest reading is the
    population model itself."""
    if tuple(reading) == HONEST:
        return PopulationBot(adjusted=adjusted)
    return PopulationReader(adjusted, *reading)


__all__ = ["AFTER_CALL", "BLUFF", "EVERY_HAND", "HONEST", "PopulationReader", "Range",
           "SLOWPLAY", "decision_parts", "reading_model", "reading_of", "seat_range",
           "split"]
