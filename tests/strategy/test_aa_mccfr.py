"""Independent small-game correctness, transaction and continuation checks."""
from copy import deepcopy
import itertools
import json
import random

import pytest

from poker_engine.strategy.aa_mccfr import (
    ExternalSamplingMCCFR, TrainingBudget, TrainingBudgetExceeded,
)
from poker_engine.strategy.aa_frozen_policy import canonical_hash


class Kuhn:
    def __init__(self, seed):
        self.cards = random.Random(seed).sample(range(3), 2)
        self.history = ""

    @property
    def terminal(self):
        return self.history in ("cc", "bf", "bk", "cbf", "cbk")

    @property
    def actor(self):
        return len(self.history) % 2

    def observe(self, seat):
        return {"key": f"{seat}:{self.cards[seat]}:{self.history}",
                "actions": tuple("fk" if self.history.endswith("b") else "cb")}

    def clone(self):
        return deepcopy(self)

    def step(self, action):
        assert action in self.observe(self.actor)["actions"]
        self.history += action

    def terminal_returns(self):
        if self.history == "bf":
            value = 1
        elif self.history == "cbf":
            value = -1
        else:
            value = (1 if self.cards[0] > self.cards[1] else -1)
            value *= 1 if self.history == "cc" else 2
        return {0: value, 1: -value}


def trainer(seed=42, **kwargs):
    return ExternalSamplingMCCFR(
        (0, 1), seed=seed, encoder=lambda obs: obs["key"],
        menu=lambda obs: obs["actions"], **kwargs,
    )


def value(arena, policy, override_player=None, overrides=None):
    if arena.terminal:
        return arena.terminal_returns()[0]
    obs = arena.observe(arena.actor)
    dist = policy.get(obs["key"], {a: 0.5 for a in obs["actions"]})
    if arena.actor == override_player:
        dist = {overrides[obs["key"]]: 1.0}
    total = 0.0
    for action, probability in dist.items():
        child = arena.clone()
        child.step(action)
        total += probability * value(child, policy, override_player, overrides)
    return total


def best_response_values(policy):
    deals = list(itertools.permutations(range(3), 2))
    best = []
    for player in (0, 1):
        keys = [(f"{player}:{rank}:{history}", "fk" if history.endswith("b") else "cb")
                for rank in range(3)
                for history in (("", "cb") if player == 0 else ("c", "b"))]
        vals = []
        for choices in itertools.product(*(actions for _, actions in keys)):
            overrides = dict(zip((key for key, _ in keys), choices))
            total = 0.0
            for deal in deals:
                arena = Kuhn(0)
                arena.cards = list(deal)
                total += value(arena, policy, player, overrides) / len(deals)
            vals.append(total)
        best.append(max(vals) if player == 0 else min(vals))
    return best


def test_kuhn_reduces_exploitability_against_exhaustive_pure_best_responses():
    learning = trainer(budget=TrainingBudget(seconds=5))
    for _ in range(4000):
        learning.iterate(Kuhn)
    br0, br1 = best_response_values(learning.average_policy())
    assert br0 - br1 < 0.10
    assert br1 <= -1 / 18 <= br0


def test_resume_is_identical_to_uninterrupted_training():
    learning = trainer()
    for _ in range(25):
        learning.iterate(Kuhn)
    checkpoint = json.loads(json.dumps(learning.checkpoint()))
    resumed = ExternalSamplingMCCFR.restore(
        checkpoint, encoder=lambda obs: obs["key"], menu=lambda obs: obs["actions"],
    )
    for _ in range(25):
        learning.iterate(Kuhn)
        resumed.iterate(Kuhn)
    assert learning.checkpoint() == resumed.checkpoint()


@pytest.mark.parametrize("budget", [
    TrainingBudget(max_nodes=1), TrainingBudget(max_infosets=1),
    TrainingBudget(max_depth=1),
])
def test_failed_whole_sweep_does_not_commit_partial_updates_or_rng(budget):
    learning = trainer(budget=budget)
    before = learning.checkpoint()
    with pytest.raises(TrainingBudgetExceeded):
        learning.iterate(Kuhn)
    assert learning.checkpoint() == before


def test_monotonic_deadline_covers_entire_sweep():
    ticks = iter(range(10000))
    learning = trainer(clock=lambda: next(ticks), budget=TrainingBudget(seconds=3))
    with pytest.raises(TrainingBudgetExceeded):
        learning.iterate(Kuhn)
    assert not learning.regrets and learning.iterations == 0


def test_checkpoint_tampering_rejected():
    doc = trainer().checkpoint()
    doc["iterations"] = 90
    with pytest.raises(ValueError, match="digest"):
        ExternalSamplingMCCFR.restore(doc)


def test_self_rehashed_inconsistent_average_menu_rejected_at_restore():
    learning = trainer()
    for _ in range(25):
        learning.iterate(Kuhn)
    doc = learning.checkpoint()
    doc["average"] = {key: {"bogus": 1.0} for key in doc["average"]}
    doc.pop("sha256")
    doc["sha256"] = canonical_hash(doc)
    with pytest.raises(ValueError, match="menu_mismatch"):
        ExternalSamplingMCCFR.restore(doc)


def test_checkpoint_embeds_binding_and_requires_exact_caller_scope():
    learning = trainer(binding={"rules": "original"}, encoder_id="kuhn-v1")
    learning.iterate(Kuhn)
    doc = learning.checkpoint()
    with pytest.raises(ValueError, match="binding"):
        ExternalSamplingMCCFR.restore(
            doc, expected_binding={"rules": "changed"}, expected_encoder="kuhn-v1",
        )
    restored = ExternalSamplingMCCFR.restore(
        doc, expected_binding={"rules": "original"}, expected_encoder="kuhn-v1",
    )
    assert restored.checkpoint() == doc


def test_commit_exception_rolls_back_rng_and_entire_state(monkeypatch):
    learning = trainer()
    learning.iterate(Kuhn)
    before = learning.checkpoint()

    def fail(base, delta):
        raise ValueError("injected commit failure")

    monkeypatch.setattr(learning, "_merge", fail)
    with pytest.raises(ValueError, match="commit"):
        learning.iterate(Kuhn)
    assert learning.checkpoint() == before
