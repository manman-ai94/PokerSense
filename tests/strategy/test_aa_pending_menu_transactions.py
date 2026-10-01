"""Sixteen fixed synthetic transactions: eight conflicts and eight legal menus.

The custom encoder deliberately aliases inconsistent opponent menus; these
counterexamples do not claim that native V2 can reach such a collision. Menu
reordering is legal under the current set contract, and the original action
sequence remains the sampling sequence. These checks make no strength claim.
"""
from copy import deepcopy

import pytest

from poker_engine.strategy.aa_mccfr import (
    ExternalSamplingMCCFR, TrainingBudget,
)


class PendingMenuArena:
    """Actor 0 enumerates A/B, actor 1 samples, then actor 0 enumerates Q/W."""

    def __init__(self, prefix, second_menu):
        self.prefix = prefix
        self.second_menu = second_menu
        self.history = ()

    @property
    def terminal(self):
        return len(self.history) == 3

    @property
    def actor(self):
        return 1 if len(self.history) == 1 else 0

    def observe(self, seat):
        assert seat == self.actor
        if not self.history:
            key, actions = "root", ("A", "B")
        elif len(self.history) == 1:
            key = "opponent"
            actions = (("L", "R") if self.history[0] == "A"
                       else self.second_menu)
        else:
            key = f"tail:{self.history[0]}:{self.history[1]}"
            actions = ("Q", "W")
        return {"key": self.prefix + key, "actions": actions}

    def clone(self):
        return deepcopy(self)

    def step(self, action):
        assert action in self.observe(self.actor)["actions"]
        self.history += (action,)

    def terminal_returns(self):
        branch, opponent, tail = self.history
        value = ({"A": 2, "B": 5}[branch]
                 + {"L": 1, "R": 3, "X": 7}[opponent]
                 + {"Q": -2, "W": 4}[tail])
        assert value != 0
        return {0: value, 1: -value}


class TraceTrainer(ExternalSamplingMCCFR):
    """Observe actual iterate scratch and delegate all computation."""

    def __init__(self, **kwargs):
        super().__init__((0, 1), **kwargs)
        self.attempts = []

    def _walk(self, arena, traverser, deltas, sums, visits, deadline, depth):
        scratch = (deltas, sums, visits)
        if depth == 0 and traverser == 0:
            self.attempts.append({"scratch": scratch, "same_scratch": True})
        attempt = self.attempts[-1]
        attempt["same_scratch"] &= all(
            original is current
            for original, current in zip(attempt["scratch"], scratch)
        )
        if traverser == 0 and arena.history == ("B",):
            attempt["before_second_menu"] = {
                "regrets": deepcopy(deltas), "average": deepcopy(sums),
                "visits": deepcopy(visits), "checkpoint": self.checkpoint(),
                "rng_state": self.rng.getstate(),
            }
        return super()._walk(
            arena, traverser, deltas, sums, visits, deadline, depth,
        )


def arena_factory(prefix, second_menu=("L", "R")):
    return lambda deal_seed: PendingMenuArena(prefix, second_menu)


def assert_work_precedes_second_menu(attempt, before, update_regrets):
    assert attempt["same_scratch"]
    observed = attempt["before_second_menu"]
    for field in before.keys() - {"rng_state", "sha256"}:
        assert observed["checkpoint"][field] == before[field]
    assert observed["rng_state"] != before["rng_state"]
    assert set(observed["regrets"]["probe:opponent"]) == {"L", "R"}
    weight = (before["iterations"] + 1) / 2
    assert observed["average"] == {
        "probe:opponent": {"L": weight, "R": weight},
    }
    tails = [key for key in observed["regrets"]
             if key.startswith("probe:tail:A:")]
    assert len(tails) == 1
    assert observed["visits"] == {
        "probe:root": 1, "probe:opponent": 1, tails[0]: 1,
    }
    expected = {"Q": -3.0, "W": 3.0} if update_regrets else {
        "Q": 0.0, "W": 0.0,
    }
    assert observed["regrets"][tails[0]] == expected
    if not update_regrets:
        assert all(value == 0 for values in observed["regrets"].values()
                   for value in values.values())


@pytest.mark.parametrize("prior_commit", [False, True],
                         ids=["empty", "populated"])
@pytest.mark.parametrize("update_regrets", [False, True],
                         ids=["no-regrets", "regrets"])
@pytest.mark.parametrize("menu_case,second_menu", [
    pytest.param("subset", ("L",), id="subset"),
    pytest.param("superset", ("L", "R", "X"), id="superset"),
    pytest.param("same", ("L", "R"), id="same"),
    pytest.param("reordered", ("R", "L"), id="reordered"),
])
def test_pending_menu_transaction(prior_commit, update_regrets, menu_case,
                                  second_menu, record_property):
    learning = TraceTrainer(
        seed=20261001, update_regrets=update_regrets,
        encoder=lambda obs: obs["key"], menu=lambda obs: obs["actions"],
        encoder_id="synthetic_pending_menu_v1", clock=lambda: 0.0,
        budget=TrainingBudget(max_nodes=64, max_infosets=32, max_depth=8,
                              seconds=1),
    )
    initial_rng = learning.rng.getstate()
    if prior_commit:
        learning.iterate(arena_factory("warm:"))
        assert learning.regrets and learning.average and learning.visits
        assert learning.iterations == 1 and learning.total_nodes > 0
        assert learning.rng.getstate() != initial_rng
        assert all(key.startswith("warm:") for key in learning.regrets)
        assert any(value != 0 for values in learning.regrets.values()
                   for value in values.values()) == update_regrets

    before = learning.checkpoint()
    rng_before = learning.rng.getstate()
    if menu_case in ("subset", "superset"):
        # Reject KeyError so the old superset path stays a baseline failure.
        with pytest.raises(ValueError, match="^information_set_menu_changed$"):
            learning.iterate(arena_factory("probe:", second_menu))
        assert_work_precedes_second_menu(
            learning.attempts[-1], before, update_regrets,
        )
        assert learning.checkpoint() == before
        assert learning.rng.getstate() == rng_before
        assert learning.last_attempt_nodes > 0
    else:
        result = learning.iterate(arena_factory("probe:", second_menu))
        assert_work_precedes_second_menu(
            learning.attempts[-1], before, update_regrets,
        )
        checkpoint = learning.checkpoint()
        expected_iteration = int(prior_commit) + 1
        assert learning.iterations == result["iteration"] == expected_iteration
        assert learning.total_nodes == before["total_nodes"] + result["nodes"]
        assert learning.rng.getstate() != rng_before
        assert learning.visits["probe:root"] == 2
        assert learning.visits["probe:opponent"] == 3
        assert learning.average["probe:opponent"] == {
            "L": float(expected_iteration), "R": float(expected_iteration),
        }
        assert set(learning.visits) == set(learning.regrets)
        for key, values in learning.regrets.items():
            suffix = key.split(":", 1)[1]
            expected_menu = ({"A", "B"} if suffix == "root" else
                             {"L", "R"} if suffix == "opponent" else
                             {"Q", "W"})
            assert set(values) == expected_menu
        for key, values in learning.average.items():
            assert set(values) == set(learning.regrets[key])
        record_property("checkpoint_sha256", checkpoint["sha256"])
    assert len(learning.attempts) == int(prior_commit) + 1
    record_property("last_attempt_nodes", learning.last_attempt_nodes)
