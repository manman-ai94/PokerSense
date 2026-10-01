"""Four fixed contract probes, with no iterate, export, fitting or sampling.

Source of the invariant (read only; no external implementation copied):
OpenSpiel Apache-2.0 pin 48401890ee9857e611678302371378175a8e4c6b,
open_spiel/python/algorithms/external_sampling_mccfr.py: an information set
has one legal action menu. This test uses PokerSense's public custom-encoder
contract and exercises its existing information_set_menu_changed guard.

The deliberately inconsistent arena/encoder is a negative input witness,
not proof that the native V2 encoder creates this collision. Both decision
nodes have the same player's cards and public prefix. Only their legal menu
changes. Utilities are zero and the walker is called directly; no training
sweep or checkpoint is created. The four cases are frozen before execution.
"""

import pytest

from poker_engine.strategy.aa_mccfr import ExternalSamplingMCCFR, TrainingBudget


FROZEN_CASES = (
    "consistent_new", "mismatch_existing", "mismatch_new",
    "mismatch_new_without_regret",
)
KEY = "P0/AsKd/public-prefix-empty"


class OneDecision:
    def __init__(self, actions=("L", "R"), terminal=False):
        self.actions, self.terminal = actions, terminal
        self.actor = 0

    def observe(self, seat):
        assert seat == self.actor == 0
        return {"key": KEY, "actions": self.actions}

    def clone(self):
        return OneDecision(self.actions, self.terminal)

    def step(self, action):
        assert not self.terminal and action in self.actions
        self.terminal = True

    def terminal_returns(self):
        assert self.terminal
        return {0: 0, 1: 0}


@pytest.mark.parametrize("case", FROZEN_CASES, ids=FROZEN_CASES)
def test_same_infoset_menu_before_and_after_first_commit(case, record_property):
    walker = ExternalSamplingMCCFR(
        (0, 1), encoder=lambda obs: obs["key"],
        menu=lambda obs: obs["actions"],
        budget=TrainingBudget(max_nodes=10, seconds=2),
        update_regrets=case != "mismatch_new_without_regret",
    )
    if case == "mismatch_existing":
        walker.regrets[KEY] = {"L": 0.0, "R": 0.0}
    deltas, sums, visits = {}, {}, {}
    deadline = walker.clock() + 2

    def walk(actions):
        return walker._walk(
            OneDecision(actions), 0, deltas, sums, visits, deadline, 0)

    assert walk(("L", "R")) == 0
    assert set(deltas[KEY]) == {"L", "R"}
    try:
        if case == "consistent_new":
            assert walk(("L", "R")) == 0
            assert visits[KEY] == 2
        else:
            with pytest.raises(ValueError, match="information_set_menu_changed"):
                walk(("L",))
    finally:
        record_property("frozen_case", case)
        record_property("walker_nodes", walker.last_attempt_nodes)
        record_property("scratch_visits", visits[KEY])
        record_property("scratch_menu", ",".join(sorted(deltas[KEY])))
        assert walker.iterations == walker.total_nodes == 0
        assert walker.average == {}
        assert sums == {}
