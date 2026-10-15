"""The simulation's order of strategy variants against the shown cards' order."""

from decimal import Decimal

import pytest

from tests.tools.test_aa_compare_advice import rows
from tools import sim_real_rank
from tools.aa_compare_advice import chips


def shown_rows(cards=("Kc", "Kd")):
    """The limp, raise, re-raise hand; seat 0 shows ``cards`` at the end."""
    found = rows()
    found[-1]["fields"]["shown_cards"] = {"seats": {"0": {"cards": list(cards)}}}
    return found


class Serial:
    def __init__(self, workers=1):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, function, items, chunksize=1):
        return map(function, items)


def test_your_turn_is_priced_against_the_cards_shown():
    assert sim_real_rank.spots("log", rows()) == []          # nobody showed
    ((where, observation, share),) = sim_real_rank.spots("log", shown_rows())
    assert where == {"log": "log", "hand_id": "hand_1", "row": 20}
    assert observation["actor"] == 4 and Decimal(observation["to_call"]) == 130
    assert 0.25 < share < 0.35                                 # A♦Q♦ against K♣K♦
    ((call, worth),) = sim_real_rank.decide(("always_call", [(where, observation,
                                                              share)]))
    assert call == {"action": "call"}
    assert worth == pytest.approx(chips(call, observation, share) / 4)
    assert worth < 0


def test_table_actions_read_as_answers():
    observation = sim_real_rank.spots("log", shown_rows())[0][1]
    raises = [item for item in observation["legal_actions"]
              if item["kind"] == "raise_to"]
    assert sim_real_rank.answer(observation, "fold") == {"action": "fold"}
    assert sim_real_rank.answer(observation, "check_call") == {"action": "call"}
    assert sim_real_rank.answer(observation, raises[0]["id"]) == {
        "action": "raise", "to": raises[0]["raise_to"]}


def test_kendall_counts_pairs_in_the_same_and_the_other_order():
    assert sim_real_rank.kendall([(1, 1), (2, 2), (3, 3)]) == (1.0, 3, 0)
    assert sim_real_rank.kendall([(1, 3), (2, 2), (3, 1)]) == (-1.0, 0, 3)
    assert sim_real_rank.kendall([(1, 1), (2, 1)]) == (0.0, 0, 0)
    assert sim_real_rank.kendall([(1, 1)]) == (None, 0, 0)


def ranked(monkeypatch, variants, shown, turns=40, differ=40):
    """``rank`` with each variant worth ``shown[name]`` more than the reference
    on each of ``differ`` turns (and answering otherwise there)."""
    def decide(job):
        name, found = job
        return [({"action": name if index < differ and name != "ref" else "ref"},
                 shown.get(name, 0.0) / differ if index < differ else 0.0)
                for index in range(len(found))]

    monkeypatch.setattr(sim_real_rank, "ProcessPoolExecutor", Serial)
    monkeypatch.setattr(sim_real_rank, "decide", decide)
    sim = {"reference": "ref", "pool": ["aa_cal"],
           "strategies": {name: {} for name in ["ref", *variants]},
           "versus_reference": {name: {"delta_bb_per_100": gain}
                                for name, gain in variants.items()}}
    return sim_real_rank.rank(sim, [None] * turns)


def test_the_same_order_agrees(monkeypatch):
    variants = {f"v{index}": float(index) for index in range(1, 9)}
    result = ranked(monkeypatch, variants, {name: gain * 2 for name, gain
                                            in variants.items()})
    assert result["verdict"] == "agree" and result["tau"] == 1.0
    assert result["variants"]["v3"] == {"sim": 3.0, "shown": 6.0, "differ": 40}
    assert result["turns_differ"] == 40
    assert "agree (tau +1.00" in sim_real_rank.summary(result)


def test_the_other_order_disagrees(monkeypatch):
    variants = {f"v{index}": float(index) for index in range(1, 9)}
    result = ranked(monkeypatch, variants, {name: -gain for name, gain
                                            in variants.items()})
    assert result["verdict"] == "disagree" and result["tau"] == -1.0


def test_too_few_variants_or_turns_are_not_enough(monkeypatch):
    few = {f"v{index}": float(index) for index in range(1, 4)}
    assert ranked(monkeypatch, few, few)["verdict"] == "not enough data"
    many = {f"v{index}": float(index) for index in range(1, 9)}
    result = ranked(monkeypatch, many, many, differ=10)
    assert result["verdict"] == "not enough data" and result["tau"] == 1.0
