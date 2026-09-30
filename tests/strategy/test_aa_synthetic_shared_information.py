"""Small perfect-recall regression; OWN remains a test-only component."""
from fractions import Fraction
import math

import pytest

from tests.strategy.aa_synthetic_regression_support import Counter
from tests.strategy.aa_synthetic_shared_component import SharedInfoContract, collect
from tests.strategy.aa_synthetic_shared_reference import reference


FROZEN = (("FULL", 1), ("FULL", 2), ("FULL", 3), ("ZERO_OPPONENT", 2),
          ("ZERO_SELF", 2), ("CHANCE_SKEW", 2))


@pytest.mark.parametrize("case,weight", FROZEN)
def test_own_quantities_count_shared_information_once(case, weight, record_property):
    counter = Counter()
    oracle = reference(case, "A", weight, counter.tick)
    forward = collect(case, "A", weight, counter.tick)
    reverse = collect(case, "A", weight, counter.tick, reverse=True)
    expected = {k: v for k, v in oracle["expected_averages"].items()
                if sum(v.values(), Fraction(0)) > 0}
    assert set(forward["average"]) == set(reverse["average"]) == set(expected)
    assert forward["average"] == reverse["average"]
    for result in (forward, reverse):
        assert len(result["arrivals"]) == 124
        assert len(result["registry"]) == 16
        assert all(r["status"] == "PASS" and "reason" not in r
                   for r in result["planned_arrivals"])
        assert len(result["positive_keys"]) == (14 if case == "ZERO_SELF" else 16)
        for key, observed in result["registry"].items():
            assert observed["signature"] == oracle["info_signatures"][key]
            assert observed["physical_occurrences"] == oracle[
                "physical_occurrences"][key]
            assert abs(observed["own_reach"] - float(oracle["masses"][key])) <= 1e-12
            assert set(observed["policy"]) == set(oracle["policy"][key]) == {"L", "R"}
            for action, value in oracle["policy"][key].items():
                assert abs(observed["policy"][action] - float(value)) <= 1e-12
        for key, quantities in expected.items():
            assert set(result["average"][key]) == {"L", "R"}
            for action, value in quantities.items():
                assert abs(result["average"][key][action] - float(value)) <= 1e-10
        total = math.fsum(v for row in result["average"].values() for v in row.values())
        assert abs(total - 14 * weight) <= 1e-10
    assert counter.nodes == 264
    record_property("synthetic_nodes", counter.nodes)


def test_raw_duplicate_error_can_disappear_after_normalization(record_property):
    counter = Counter()
    proper = collect("FULL", "A", 1, counter.tick)["average"]
    naive = collect("FULL", "A", 1, counter.tick,
                    mutation="SUM_EVERY_HISTORY")["average"]
    proper_mass = math.fsum(v for row in proper.values() for v in row.values())
    naive_mass = math.fsum(v for row in naive.values() for v in row.values())
    assert abs(proper_mass - 14) <= 1e-10
    assert abs(naive_mass - 44) <= 1e-10
    for key, quantities in proper.items():
        for action, value in quantities.items():
            assert abs(value / math.fsum(quantities.values())
                       - naive[key][action] / math.fsum(naive[key].values())) <= 1e-12
    record_property("synthetic_nodes", counter.nodes)


@pytest.mark.parametrize("mutation,reason,nodes", (
    ("LEAK_CHANCE", "hidden_information_in_key", 64),
    ("LEAK_OPPONENT", "hidden_information_in_key", 17),
    ("FORGET_OWN", "imperfect_recall_or_private_merge", 11),
    ("FORGET_PRIVATE", "imperfect_recall_or_private_merge", 33),
    ("MENU_MISMATCH", "menu_mismatch", 64),
    ("POLICY_MISMATCH", "same_info_policy_changed", 64),
))
def test_shared_information_conflicts_are_refused(mutation, reason, nodes,
                                                  record_property):
    counter = Counter()
    progress = {}
    with pytest.raises(SharedInfoContract, match=reason):
        collect("FULL", "A", 1, counter.tick, mutation=mutation, progress=progress)
    assert counter.nodes == nodes
    assert len(progress["planned_arrivals"]) == 124
    assert len(progress["arrivals"]) == nodes
    assert progress["arrivals"][-1]["status"] == "FAIL"
    assert progress["arrivals"][-1]["reason"] == reason
    assert sum(r["status"] == "NOT_RUN" for r in progress["planned_arrivals"]) == (
        124 - nodes)
    record_property("synthetic_nodes", counter.nodes)
