"""Portable test fixtures for the frozen public four-action finite game.

These helpers observe the production external-sampling walk. They do not
implement a sampler, regret updater, or average collector. Counters belong to
one caller and never read or write an external research ledger.
"""
from fractions import Fraction
import hashlib
import itertools
import time

from poker_engine.strategy.aa_mccfr import (
    ExternalSamplingMCCFR, TrainingBudget,
)
from tests.strategy.aa_synthetic_status import SyntheticInterrupted


ACTORS = (1, 0, 2, 0)
ACTIONS = ("L", "R")
CASES = ("FULL_POSITIVE", "ZERO_PREFIX", "SMALL_PREFIX", "ZERO_SELF")
# Sampling calls in the production depth-first walk, including calls in
# separately enumerated traverser branches. A tape represents their joint law.
EVENT_STAGES = {0: (0, 2, 2), 1: (1, 2, 3, 1, 2, 3), 2: (0, 1, 3, 3)}
ENCODER_ID = "four-stage-synthetic-v1"


class Counter:
    """Bound one portable regression locally, including reference summands."""
    def __init__(self, max_nodes=20000, seconds=5):
        self.max_nodes, self.seconds = max_nodes, seconds
        self.started = time.monotonic()
        self.nodes, self.labels = 0, {}

    def tick(self, label):
        if (self.nodes >= self.max_nodes
                or time.monotonic() - self.started >= self.seconds):
            raise SyntheticInterrupted("portable_synthetic_counter_budget_exceeded")
        self.nodes += 1
        self.labels[label] = self.labels.get(label, 0) + 1


def record_cost_once(counters, record_property):
    """Charge eager fixture work to the first selected test that uses it.

    Repeated callers record zero until a counter performs additional work.
    Reporting adds no budget ticks and changes only local metric metadata.
    """
    unique = {id(counter): counter for counter in counters}.values()
    cost = sum(counter.nodes - getattr(counter, "_reported_nodes", 0)
               for counter in unique)
    record_property("synthetic_nodes", cost)
    for counter in unique:
        counter._reported_nodes = counter.nodes


def label(chance, history):
    return f"{chance}:{history}"


def key(chance, history):
    return hashlib.sha256(label(chance, history).encode()).hexdigest()


def nodes():
    return [(chance, "".join(history)) for chance in (0, 1)
            for stage in range(4)
            for history in itertools.product(ACTIONS, repeat=stage)]


def probabilities(case, profile="A"):
    """Frozen A policy; the independent reference defines its own constants."""
    if case not in CASES or profile != "A":
        raise ValueError("unknown frozen case or profile")
    values = [Fraction(1, 2), Fraction(1, 3), Fraction(2, 3), Fraction(3, 4)]
    if case == "ZERO_PREFIX":
        values[0] = Fraction(0)
    elif case == "SMALL_PREFIX":
        values[0] = Fraction(1, 1024)
    elif case == "ZERO_SELF":
        values[1] = Fraction(0)
    return values


class FiniteArena:
    """Perfect recall: visible chance and the full prefix identify each key."""
    def __init__(self, chance, history=""):
        self.chance, self.history = chance, history

    @property
    def terminal(self):
        return len(self.history) == 4

    @property
    def actor(self):
        return ACTORS[len(self.history)]

    def observe(self, seat):
        assert seat == self.actor
        return {"key": key(self.chance, self.history), "actions": ACTIONS}

    def clone(self):
        return FiniteArena(self.chance, self.history)

    def step(self, action):
        assert not self.terminal and action in ACTIONS
        self.history += action

    def terminal_returns(self):
        assert self.terminal
        a, b, c, d = [int(action == "R") for action in self.history]
        u0 = ((2 * self.chance - 1) * (1 + 2 * b - 3 * d)
              + 2 * a * d - c + b * c)
        u1 = (1 - 2 * self.chance) * (2 * a - 1) + c * (1 + d) - 2 * b
        return {0: u0, 1: u1, 2: -u0 - u1}


class TraceTrainer(ExternalSamplingMCCFR):
    """Observe entry and temporary updates; delegate accounting to production."""
    def __init__(self, players=(0, 1, 2), *, limiter, **kwargs):
        super().__init__(
            players,
            encoder=kwargs.pop("encoder", lambda obs: obs["key"]),
            menu=kwargs.pop("menu", lambda obs: obs["actions"]),
            encoder_id=kwargs.pop("encoder_id", ENCODER_ID),
            budget=kwargs.pop("budget", TrainingBudget(max_nodes=1000, seconds=5)),
            **kwargs,
        )
        self.limiter, self.trace, self.temporary = limiter, [], None

    def _walk(self, arena, traverser, deltas, sums, visits, deadline, depth):
        self.limiter.tick("production_walk")
        self.temporary = deltas, sums, visits
        row = {"traverser": traverser, "chance": arena.chance,
               "history": arena.history, "terminal": arena.terminal,
               "attempt_node": self.last_attempt_nodes + 1}
        if not arena.terminal:
            designated = self.players[(self.players.index(traverser) + 1)
                                      % len(self.players)]
            row.update(actor=arena.actor, label=label(arena.chance, arena.history),
                       key=key(arena.chance, arena.history),
                       average_eligible=arena.actor == designated)
        self.trace.append(row)
        return super()._walk(arena, traverser, deltas, sums, visits, deadline, depth)


def seeded(limiter, case="FULL_POSITIVE", profile="A", weight=1, **kwargs):
    if type(weight) is not int or weight <= 0:
        raise ValueError("weight must be a positive integer")
    result = TraceTrainer(limiter=limiter, **kwargs)
    result.iterations = weight - 1
    values = probabilities(case, profile)
    for chance, history in nodes():
        p = values[len(history)]
        result.regrets[key(chance, history)] = {
            "L": p.numerator, "R": p.denominator - p.numerator}
    return result


class Tape:
    """Supply one categorical outcome, checking the actual production weights."""
    def __init__(self, choices, probabilities, stages):
        self.bits, self.probabilities, self.stages = choices, probabilities, stages
        self.position = 0

    def choices(self, actions, weights):
        stage, bit = self.stages[self.position], self.bits[self.position]
        p = self.probabilities[stage]
        assert tuple(actions) == ACTIONS
        assert weights == [float(p), float(1 - p)]
        assert (p if bit == "L" else 1 - p) > 0
        self.position += 1
        return [bit]


def rational_table(table):
    labels = {key(c, h): label(c, h) for c, h in nodes()}
    return {labels[k]: {a: Fraction.from_float(float(v)) for a, v in row.items()}
            for k, row in table.items()}


def add_weighted(target, table, probability):
    for name, values in table.items():
        row = target.setdefault(name, {a: Fraction(0) for a in ACTIONS})
        for action, value in values.items():
            row[action] += probability * value


def normalize(table):
    return {name: {a: value / sum(row.values()) for a, value in row.items()}
            for name, row in table.items() if sum(row.values()) > 0}
