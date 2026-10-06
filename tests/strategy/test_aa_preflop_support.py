"""Actual-arena support, non-existent decisions and averaging counterexample."""
from copy import deepcopy
from itertools import combinations

import pytest

from poker_engine.strategy.aa_mccfr import ExternalSamplingMCCFR, TrainingBudget
from poker_engine.strategy.aa_policy_encoding_v2 import encode_decision_v2
from poker_engine.strategy.aa_preflop_support import (
    RANKS, holding_classes, paired_query, support_specs,
)
from tools.aa_full_hand_lab import DEFAULT_RULES, rules_for


def test_support_matrix_is_full_and_does_not_confuse_classes_with_combos():
    classes = holding_classes()
    assert len(classes) == len({r["class"] for r in classes}) == 169
    assert sum(len(support_specs(n)) for n in (6, 7, 8)) == 10647
    assert all(len(set(r["holding"])) == 2 for r in classes)


@pytest.mark.parametrize("n", (6, 7, 8))
def test_all_prefix_roles_use_real_decisions_or_explicit_not_applicable(n):
    rules = rules_for(DEFAULT_RULES, n)
    for spec in support_specs(n):
        if spec["class"] != "95o":
            continue
        query = paired_query(rules, spec)
        if spec["hero"] == 2 and spec["scenario"] != "call_to_first":
            assert query["status"] == "NOT_APPLICABLE"
            assert query["observation"] is None
        else:
            assert query["status"] == "READY"
            obs = query["observation"]
            assert obs["actor"] == obs["observing_seat"] == spec["hero"]
            assert obs["street"] == "preflop"
            assert set(obs["own_hole"]) == {"9c", "5d"}
            prior = [r for r in obs["public_history"] if r["actor"] == spec["hero"]]
            assert len(prior) == (spec["scenario"] == "limp_then_min_raise")
            assert sum(r["kind"] == "raise_to" for r in obs["public_history"]) == (
                spec["scenario"] == "limp_then_min_raise")


@pytest.mark.parametrize("n", (6, 7, 8))
def test_first_actor_duplicate_prefixes_are_not_independent_keys(n):
    rules = rules_for(DEFAULT_RULES, n)
    specs = [s for s in support_specs(n) if s["hero"] == 3 and s["class"] == "AA"]
    first, second = [paired_query(rules, s) for s in specs[:2]]
    assert first == second


def test_all_1326_preflop_combos_form_169_joint_suit_orbits():
    rules = rules_for(DEFAULT_RULES, 6)
    template = paired_query(rules, support_specs(6)[0])["observation"]
    groups = {}
    for hand in combinations([r + s for r in RANKS for s in "cdhs"], 2):
        obs = deepcopy(template)
        obs["own_hole"] = list(hand)
        encoded = encode_decision_v2(obs)
        groups.setdefault(encoded["features"]["cards"]["preflop_class"], set()).add(
            (encoded["exact_key"], encoded["abstract_key"]))
    assert len(groups) == 169
    assert all(len(keys) == 1 for keys in groups.values())
    assert len(set.union(*groups.values())) == 169


def test_invalid_support_spec_rejects_instead_of_guessing_a_node():
    spec = support_specs(6)[0]
    spec["hero"] = 7
    with pytest.raises(ValueError, match="invalid_support_spec"):
        paired_query(rules_for(DEFAULT_RULES, 6), spec)


class AveragingWitness:
    """Engine-control toy, not a poker policy or empirical training result."""
    def __init__(self, key):
        self.key, self.action = key, None

    @property
    def terminal(self):
        return self.action is not None

    actor = 0

    def observe(self, seat):
        return {"key": self.key, "actions": ("a", "b")}

    def step(self, action):
        self.action = action

    def clone(self):
        return deepcopy(self)

    def terminal_returns(self):
        return {seat: (1 if self.action == "a" else -1) for seat in range(6)}


def test_nonzero_regret_without_average_is_reachable_under_declared_sampler():
    calls = 0

    def factory(seed):
        nonlocal calls
        # A possible chance realization: this information set is seen only in
        # traverser 0's walk. It is not a proposed poker chance sampler.
        key = "witness" if calls % 6 == 0 else "other"
        calls += 1
        return AveragingWitness(key)

    trainer = ExternalSamplingMCCFR(
        range(6), encoder=lambda o: o["key"], menu=lambda o: o["actions"],
        budget=TrainingBudget(seconds=5))
    for _ in range(2):
        trainer.iterate(factory)
    assert trainer.visits["witness"] == 2
    assert any(trainer.regrets["witness"].values())
    assert "witness" not in trainer.average
    assert "witness" not in trainer.average_policy()
    assert "other" in trainer.average_policy()
