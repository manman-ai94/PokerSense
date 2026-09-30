"""Production SIMPLE accounting on six frozen, portable synthetic profiles.

Every categorical tape is planned before execution. Zero-probability tapes
remain NOT_RUN rows; assertions compare all positive-probability production
walks with independent terminal sums. This is finite accounting evidence,
including the SIMPLE collector's own-reach limitation, not poker training.
"""
from fractions import Fraction
import itertools

import pytest

from tests.strategy.aa_synthetic_exact_reference import reference
from tests.strategy.aa_synthetic_regression_support import (
    ACTIONS, EVENT_STAGES, Counter, FiniteArena, Tape, add_weighted,
    normalize, probabilities, rational_table, record_cost_once, seeded,
)
from tests.strategy.aa_synthetic_status import classify_exception, finish


FROZEN_PROFILES = (
    ("FULL_POSITIVE", "A", 2), ("ZERO_PREFIX", "A", 2),
    ("SMALL_PREFIX", "A", 2), ("ZERO_SELF", "A", 2),
    ("FULL_POSITIVE", "A", 1), ("FULL_POSITIVE", "A", 3),
)
PROFILE_IDS = tuple(f"{case}-{profile}-weight{weight}"
                    for case, profile, weight in FROZEN_PROFILES)
TOLERANCE = 1e-10
EXPECTED_EXECUTED = {
    "FULL_POSITIVE": (16, 128, 32), "ZERO_PREFIX": (8, 128, 16),
    "SMALL_PREFIX": (16, 128, 32), "ZERO_SELF": (16, 32, 16),
}
EXPECTED_SUPPORT = {
    # visited, average-eligible/positive SIMPLE, positive own, own missing SIMPLE
    "FULL_POSITIVE": (30, 30, 30, 0), "ZERO_PREFIX": (30, 20, 30, 10),
    "SMALL_PREFIX": (30, 30, 30, 0), "ZERO_SELF": (30, 18, 22, 4),
}


def _planned_profile(case, profile, weight):
    p = probabilities(case, profile)
    trajectories = []
    for traverser, stages in EVENT_STAGES.items():
        for chance in (0, 1):
            for choices in itertools.product(ACTIONS, repeat=len(stages)):
                probability = Fraction(1, 2)
                for stage, choice in zip(stages, choices):
                    probability *= p[stage] if choice == "L" else 1 - p[stage]
                trajectories.append({
                    "traverser": traverser, "chance": chance,
                    "choices": choices, "probability": probability,
                    "status": "NOT_RUN",
                    "reason": ("ZERO_PROBABILITY_TRACE" if not probability
                               else "NOT_REACHED"),
                })
    return {"case": case, "profile": profile, "weight": weight,
            "status": "NOT_RUN", "trajectories": trajectories}


def _enumerate_profile(result):
    finish(result, "INTERRUPTED", "CASE_IN_PROGRESS")
    try:
        _collect_profile(result)
    except BaseException as exc:
        finish(result, classify_exception(exc), f"{type(exc).__name__}: {exc}")
        raise
    finish(result, "PASS")


def _collect_profile(result):
    case, profile, weight = result["case"], result["profile"], result["weight"]
    counter = result["counter"] = Counter()
    result["independent_reference"] = reference(case, profile, weight, counter.tick)
    p = probabilities(case, profile)
    regrets, average, visited, eligible = {}, {}, set(), set()
    denominators = {}
    for traverser, stages in EVENT_STAGES.items():
        rows = [row for row in result["trajectories"]
                if row["traverser"] == traverser]
        denominator = denominators[traverser] = {
            "planned": len(rows), "executed": 0,
            "zero_probability_not_run": sum(not row["probability"] for row in rows),
            "planned_probability_mass": sum(row["probability"] for row in rows),
            "executed_probability_mass": Fraction(0),
        }
        assert denominator["planned_probability_mass"] == 1
        for row in rows:
            counter.tick("categorical_trace")
            probability = row["probability"]
            if not probability:
                continue
            finish(row, "INTERRUPTED", "TRACE_IN_PROGRESS")
            trial = seeded(counter, case, profile, weight)
            trial.rng = tape = Tape(row["choices"], p, stages)
            deltas, sums, visits = {}, {}, {}
            row.update(arrivals=trial.trace, raw_regret_delta=deltas,
                       raw_average_delta=sums, visits=visits)
            try:
                trial._walk(FiniteArena(row["chance"]), traverser,
                            deltas, sums, visits,
                            trial.clock() + trial.budget.seconds, 0)
                assert tape.position == len(row["choices"])
            except BaseException as exc:
                finish(row, classify_exception(exc), f"{type(exc).__name__}: {exc}")
                raise
            actual_regrets = rational_table(deltas)
            actual_average = rational_table(sums)
            add_weighted(regrets, actual_regrets, probability)
            add_weighted(average, actual_average, probability)
            visited.update(rational_table({name: {"L": 0} for name in visits}))
            eligible.update(arrival["label"] for arrival in trial.trace
                            if arrival.get("average_eligible"))
            row.update(nodes=trial.last_attempt_nodes,
                       regret_delta=actual_regrets, average_delta=actual_average)
            finish(row, "PASS")
            denominator["executed"] += 1
            denominator["executed_probability_mass"] += probability
        assert denominator["executed_probability_mass"] == 1
    result.update(actual_regret_expectation=regrets,
                  actual_simple_expectation=average, denominators=denominators,
                  visited_keys=visited, average_eligible_keys=eligible,
                  positive_average_keys=set(normalize(average)))


@pytest.fixture(scope="module")
def accounting_results():
    # Allocate the entire six-profile denominator before any walk or reference.
    planned = [_planned_profile(*profile) for profile in FROZEN_PROFILES]
    assert sum(len(row["trajectories"]) for row in planned) == 1056
    for row in planned:
        _enumerate_profile(row)
    return planned


def _assert_table(actual, expected):
    assert set(actual) == set(expected)
    for name, row in expected.items():
        assert set(actual[name]) == set(row) == set(ACTIONS)
        for action, value in row.items():
            assert abs(actual[name][action] - value) <= TOLERANCE, (name, action)


def _positive(table):
    return {name: row for name, row in table.items() if sum(row.values()) > 0}


@pytest.mark.parametrize("index", range(6), ids=PROFILE_IDS)
def test_production_expectations_and_simple_own_reach_limit(
        index, accounting_results, record_property):
    result = accounting_results[index]
    counter = result["counter"]
    record_cost_once([row["counter"] for row in accounting_results], record_property)
    record_property("synthetic_profile_nodes", counter.nodes)
    rows = result["trajectories"]
    executed = [row for row in rows if row["status"] == "PASS"]
    zero = [row for row in rows if row["status"] == "NOT_RUN"]
    record_property("synthetic_trace_planned", len(rows))
    record_property("synthetic_trace_executed", len(executed))
    record_property("synthetic_trace_zero_NOT_RUN", len(zero))
    try:
        _assert_profile(result)
    except BaseException as exc:
        finish(result, classify_exception(exc), f"{type(exc).__name__}: {exc}")
        raise
    finish(result, "PASS")


def _assert_profile(result):
    counter = result["counter"]
    rows = result["trajectories"]
    executed = [row for row in rows if row["status"] == "PASS"]
    zero = [row for row in rows if row["status"] == "NOT_RUN"]
    assert len(rows) == 176
    assert len(rows) == len(executed) + len(zero)
    assert all(row["probability"] > 0 and "reason" not in row for row in executed)
    assert all(not row["probability"] and row["reason"] == "ZERO_PROBABILITY_TRACE"
               for row in zero)
    assert counter.nodes == sum(counter.labels.values())
    assert counter.labels["categorical_trace"] == 176
    assert counter.labels["production_walk"] == sum(row["nodes"] for row in executed)
    for traverser, expected_executed in enumerate(EXPECTED_EXECUTED[result["case"]]):
        counts = result["denominators"][traverser]
        assert counts["planned"] == (16, 128, 32)[traverser]
        assert counts["executed"] == expected_executed
        assert counts["zero_probability_not_run"] == (
            counts["planned"] - expected_executed)
        assert counts["planned_probability_mass"] == 1
        assert counts["executed_probability_mass"] == 1

    frozen = result["independent_reference"]
    _assert_table(result["actual_regret_expectation"], frozen["expected_regrets"])
    simple = result["actual_simple_expectation"]
    _assert_table(simple, _positive(frozen["simple_average"]))
    expected_visited, expected_simple, expected_own, expected_missing = (
        EXPECTED_SUPPORT[result["case"]])
    all_keys = set(frozen["infosets"])
    own = _positive(frozen["own_reach_average"])
    assert result["visited_keys"] == all_keys
    assert set(result["actual_regret_expectation"]) == all_keys
    assert len(all_keys) == expected_visited
    assert result["average_eligible_keys"] == set(simple)
    assert result["positive_average_keys"] == set(simple)
    assert len(simple) == expected_simple
    assert len(own) == expected_own
    assert set(simple) <= set(own) <= all_keys
    assert len(set(own) - set(simple)) == expected_missing

    # Successful limitation regression: production matches SIMPLE exactly;
    # its raw weights differ from own reach at every positive-own key.
    differing = {name for name, row in own.items() if any(
        abs(row[action] - simple.get(name, {}).get(action, 0)) > TOLERANCE
        for action in ACTIONS)}
    assert differing == set(own)
    assert sum(sum(row.values()) for row in own.values()) == 22 * result["weight"]
    assert abs(sum(sum(row.values()) for row in simple.values())
               - 6 * result["weight"]) <= TOLERANCE
    # One fixed policy normalizes identically on common support. The limitation
    # here is unequal raw weights and, in zero cases, the stated missing keys.
    common_own = {name: row for name, row in normalize(own).items() if name in simple}
    _assert_table(normalize(simple), common_own)


def test_linear_weights_change_only_average_expectations(
        accounting_results, record_property):
    record_cost_once([row["counter"] for row in accounting_results], record_property)
    full = {row["weight"]: row for row in accounting_results
            if row["case"] == "FULL_POSITIVE"}
    assert set(full) == {1, 2, 3}
    for weight in (2, 3):
        _assert_table(full[weight]["actual_regret_expectation"],
                      full[1]["actual_regret_expectation"])
        scaled = {name: {action: weight * value for action, value in row.items()}
                  for name, row in full[1]["actual_simple_expectation"].items()}
        _assert_table(full[weight]["actual_simple_expectation"], scaled)
    assert sum(len(row["trajectories"]) for row in accounting_results) == 1056
    assert sum(row["counter"].nodes for row in accounting_results) == 10244
    assert sum(row["counter"].labels["production_walk"]
               for row in accounting_results) == 8048
