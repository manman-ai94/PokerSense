"""Portable retained-mass and transaction regressions on one fixed toy corpus."""
from copy import deepcopy
from fractions import Fraction
import json
import math

import pytest

from poker_engine.strategy.aa_frozen_policy import canonical_hash
from poker_engine.strategy.aa_mccfr import TrainingBudget, TrainingBudgetExceeded
from tests.strategy.aa_regression_own_component import CollectorAbort, OwnReachArm
from tests.strategy.aa_synthetic_regression_support import (
    Counter, key, nodes, record_cost_once, seeded,
)
from tests.strategy.aa_synthetic_status import execute_case


FAULTS = ("MID_COLLECTOR", "WALK_AFTER_UPDATES")
ARMS = ("control", "failure_continue", "json_restore_continue")


def _mass(table):
    return math.fsum(value for row in table.values() for value in row.values())


def _assert_normalization(quantities, exported):
    """Normalize actual binary quantities independently with exact rationals."""
    expected = {}
    for k, row in quantities.items():
        assert set(row) == {"L", "R"}
        assert all(math.isfinite(v) and v >= 0 for v in row.values())
        amounts = {a: Fraction.from_float(float(v)) for a, v in row.items()}
        total = sum(amounts.values(), Fraction())
        if total:
            expected[k] = {a: v / total for a, v in amounts.items()}
    assert set(exported) == set(expected), "EXPORT_KEYS_CHANGED_OR_FILLED"
    for k, row in exported.items():
        if set(row) != set(expected[k]):
            raise AssertionError("EXPORT_ACTION_MENU_CHANGED")
        assert all(math.isfinite(v) and 0 <= v <= 1 for v in row.values())
        assert abs(math.fsum(row.values()) - 1) <= 1e-12
        assert all(abs(v - float(expected[k][a])) <= 1e-12
                   for a, v in row.items())


def _synthetic_policy_factory(*, rules_fingerprint, table_size, stack_depth_bb,
                              policy, training):
    """Pure factory exercises public export without creating a poker artifact."""
    assert rules_fingerprint == "synthetic-four-stage"
    assert table_size == 3 and stack_depth_bb == 100
    assert set(policy) <= {key(c, h) for c, h in nodes()}
    for row in policy.values():
        assert set(row) == {"L", "R"}
        assert all(math.isfinite(v) and 0 <= v <= 1 for v in row.values())
        assert abs(math.fsum(row.values()) - 1) <= 1e-12
    return {"kind": "SYNTHETIC_SIMPLE_EXPORT_FOR_TESTS",
            "status": "synthetic_test_only", "encoder": "four-stage-synthetic-v1",
            "policy": deepcopy(policy), "training": deepcopy(training)}


def _exports(arm):
    checkpoint = arm.checkpoint()
    own = arm.export()
    simple = arm.trainer.average_policy()
    document = arm.trainer.export(
        rules_fingerprint="synthetic-four-stage", table_size=3, stack_depth_bb=100,
        policy_factory=_synthetic_policy_factory)
    _assert_normalization(checkpoint["own_average"], own["policy"])
    _assert_normalization(checkpoint["production"]["average"], simple)
    assert document["policy"] == simple
    assert (document["training"]["checkpoint_sha256"]
            == checkpoint["production"]["sha256"])
    assert arm.checkpoint() == checkpoint, "EXPORT_MUTATED_CHECKPOINT"
    return {"own": own, "simple": simple, "production_export": document}


def assert_populated_checkpoint_equal(before, after):
    """Compare committed quantities before digest/full-document equality."""
    assert before["own_average"] and before["production"]["average"]
    if before["own_average"] != after.get("own_average"):
        raise AssertionError("POPULATED_OWN_AVERAGE_CHANGED")
    if before["collector_visits"] != after.get("collector_visits"):
        raise AssertionError("POPULATED_COLLECTOR_VISITS_CHANGED")
    if before["collector_sweeps"] != after.get("collector_sweeps"):
        raise AssertionError("POPULATED_COLLECTOR_COUNTER_CHANGED")
    for field in ("regrets", "average", "committed_visits", "iterations",
                  "total_nodes", "rng_state"):
        if before["production"][field] != after["production"].get(field):
            raise AssertionError("POPULATED_PRODUCTION_CHANGED:" + field)
    if before != after:
        raise AssertionError("POPULATED_FULL_CHECKPOINT_CHANGED")


def _assert_retained_quantities(before, after):
    for old, current in (
            (before["own_average"], after["own_average"]),
            (before["production"]["average"], after["production"]["average"])):
        assert set(old) <= set(current)
        for k, row in old.items():
            assert set(row) == set(current[k])
            assert all(current[k][action] >= value for action, value in row.items())


@pytest.fixture(scope="module")
def transaction_evidence():
    """Run the two frozen faults once; every rejected callback is counted."""
    counter = Counter()
    valid = TrainingBudget(max_nodes=1000, seconds=5)
    warm = OwnReachArm(seeded(counter, seed=17, budget=valid), counter)
    initial = warm.checkpoint()
    warmup_steps = []
    for _ in range(2):
        warm.iterate()
        warmup_steps.append(warm.checkpoint())
    populated, exports = warm.checkpoint(), _exports(warm)
    evidence = {"counter": counter, "initial": initial, "populated": populated,
                "warmup_steps": warmup_steps, "exports": exports, "faults": {}}
    for fault in FAULTS:
        arms = {
            "control": OwnReachArm.restore(populated, counter, valid),
            "failure_continue": OwnReachArm.restore(populated, counter, valid),
            "json_restore_continue": OwnReachArm.restore(
                json.loads(json.dumps(populated, sort_keys=True, allow_nan=False)),
                counter, valid),
        }
        starts = {name: arm.checkpoint() for name, arm in arms.items()}
        failed = arms["failure_continue"]
        failed.abort_collector_at = 3 if fault == "MID_COLLECTOR" else None
        failed.trainer.budget = (valid if fault == "MID_COLLECTOR" else
                                 TrainingBudget(max_nodes=6, seconds=5))
        expected = (CollectorAbort if fault == "MID_COLLECTOR" else
                    TrainingBudgetExceeded)
        before_fault = failed.checkpoint()
        labels_before = dict(counter.labels)
        try:
            failed.iterate()
        except expected as exc:
            assert type(exc) is expected
            exception = type(exc).__name__, str(exc)
        else:
            raise AssertionError("FROZEN_FAULT_DID_NOT_OCCUR")
        row = {"starts": starts, "before": before_fault, "after": failed.checkpoint(),
               "exception": exception,
               "collector": deepcopy(failed.temporary_collector),
               "pending": deepcopy(failed.temporary_walk),
               "arrivals": deepcopy(failed.sampled_arrivals),
               "rng_before_inner_rollback": deepcopy(failed.temporary_rng),
               "rng_at_rejected_entry": deepcopy(failed.rng_at_rejected_entry),
               "rejected_walk_entry": failed.rejected_walk_entry,
               "attempted_walk_entries": failed.attempted_walk_entries,
               "fault_nodes": {k: counter.labels.get(k, 0) - labels_before.get(k, 0)
                               for k in ("own_collector_state", "production_walk")},
               "exports_after_failure": _exports(failed), "continuations": []}
        failed.abort_collector_at, failed.trainer.budget = None, valid
        for _ in range(2):
            for arm in arms.values():
                arm.iterate()
                _assert_retained_quantities(populated, arm.checkpoint())
            row["continuations"].append({
                "checkpoints": {name: arm.checkpoint() for name, arm in arms.items()},
                "exports": {name: _exports(arm) for name, arm in arms.items()},
            })
        evidence["faults"][fault] = row
    return evidence


def test_seed17_two_warmups_have_nonempty_committed_own_and_simple_state(
        transaction_evidence, record_property):
    evidence = transaction_evidence
    record_cost_once([evidence["counter"]], record_property)
    checkpoint, initial = evidence["populated"], evidence["initial"]
    production = checkpoint["production"]
    assert len(evidence["warmup_steps"]) == 2
    assert len(checkpoint["own_average"]) == len(checkpoint["collector_visits"]) == 30
    assert sum(v > 0 for row in checkpoint["own_average"].values()
               for v in row.values()) == 60
    assert _mass(checkpoint["own_average"]) == 66
    assert len(production["regrets"]) == 30 and len(production["average"]) == 12
    assert _mass(production["average"]) == 18
    assert production["iterations"] == checkpoint["collector_sweeps"] == 2
    assert production["total_nodes"] == 52
    assert sum(production["committed_visits"].values()) == 36
    assert production["regrets"] != initial["production"]["regrets"]
    assert production["rng_state"] != initial["production"]["rng_state"]
    assert evidence["counter"].labels == {
        "own_collector_state": 933, "production_walk": 371}
    assert evidence["counter"].nodes == 1304


@pytest.mark.parametrize("fault", FAULTS)
def test_populated_fault_rolls_back_full_state_and_temporary_rng(
        transaction_evidence, record_property, fault):
    record_cost_once([transaction_evidence["counter"]], record_property)
    evidence, row = transaction_evidence, transaction_evidence["faults"][fault]
    before = evidence["populated"]
    assert all(checkpoint == before for checkpoint in row["starts"].values())
    assert row["before"] == before
    assert_populated_checkpoint_equal(before, row["after"])
    assert _mass(row["collector"]["average"]) > 0
    assert row["exports_after_failure"] == evidence["exports"]
    if fault == "MID_COLLECTOR":
        assert row["exception"] == ("CollectorAbort", "frozen_mid_collector_abort")
        assert len(row["collector"]["arrivals"]) == 3
        assert row["fault_nodes"] == {"own_collector_state": 3, "production_walk": 0}
        assert row["attempted_walk_entries"] == 0 and not row["arrivals"]
        assert row["pending"] is None and row["rejected_walk_entry"] == 0
        assert row["rng_before_inner_rollback"] == before["production"]["rng_state"]
    else:
        assert row["exception"] == (
            "TrainingBudgetExceeded", "whole_sweep_budget_exceeded")
        assert len(row["collector"]["arrivals"]) == 62
        assert row["fault_nodes"] == {"own_collector_state": 62, "production_walk": 7}
        assert row["attempted_walk_entries"] == row["rejected_walk_entry"] == 7
        assert len(row["arrivals"]) == 7 and row["arrivals"][-1]["attempt_node"] == 7
        regret, simple, visits = row["pending"]
        assert any(v != 0 for values in regret.values() for v in values.values())
        assert _mass(simple) > 0 and visits and sum(visits.values()) > 0
        assert row["rng_before_inner_rollback"] != before["production"]["rng_state"]
        assert row["rng_before_inner_rollback"] == row["rng_at_rejected_entry"]


@pytest.mark.parametrize("fault", FAULTS)
def test_two_continuations_match_control_failure_and_json_restore(
        transaction_evidence, record_property, fault):
    record_cost_once([transaction_evidence["counter"]], record_property)
    before = transaction_evidence["populated"]
    row = transaction_evidence["faults"][fault]
    assert len(row["continuations"]) == 2
    for step, continuation in enumerate(row["continuations"], 1):
        checkpoints = [continuation["checkpoints"][name] for name in ARMS]
        assert checkpoints[0] == checkpoints[1] == checkpoints[2]
        exports = [continuation["exports"][name] for name in ARMS]
        assert exports[0] == exports[1] == exports[2]
        for checkpoint in checkpoints:
            _assert_retained_quantities(before, checkpoint)
            assert (checkpoint["collector_sweeps"]
                    == checkpoint["production"]["iterations"] == 2 + step)
            # Each weight adds OWN mass22 and sampled SIMPLE mass6; cumulative
            # linear weights are 1+2+3=6 and 1+2+3+4=10 for these fixed steps.
            assert math.isclose(_mass(checkpoint["own_average"]),
                                (132, 220)[step - 1], rel_tol=0, abs_tol=1e-10)
            assert math.isclose(_mass(checkpoint["production"]["average"]),
                                (36, 60)[step - 1], rel_tol=0, abs_tol=1e-10)


def test_exports_normalize_actual_quantities_and_preserve_sparse_simple_keys(
        transaction_evidence, record_property):
    record_cost_once([transaction_evidence["counter"]], record_property)
    before, exports = transaction_evidence["populated"], transaction_evidence["exports"]
    _assert_normalization(before["own_average"], exports["own"]["policy"])
    _assert_normalization(before["production"]["average"], exports["simple"])
    assert set(exports["simple"]) == set(before["production"]["average"])
    assert len(exports["own"]["policy"]) == 30 and len(exports["simple"]) == 12
    assert set(exports["simple"]) < set(exports["own"]["policy"])
    training = exports["production_export"]["training"]
    assert training["algorithm"] == "external_sampling_simple_linear_v1"
    assert training["multiplayer_averaging"] == "SIMPLE_APPROXIMATION"
    assert training["seed"] == 17 and training["iterations"] == 2
    assert training["nodes"] == 52 and training["empirical_strength"] == "NOT_ASSESSED"


@pytest.mark.parametrize("mutation,reason", (
    ("DROP_OLD_OWN", "POPULATED_OWN_AVERAGE_CHANGED"),
    ("RETAIN_PENDING_OWN", "POPULATED_OWN_AVERAGE_CHANGED"),
    ("ALTER_RNG", "POPULATED_PRODUCTION_CHANGED:rng_state"),
))
def test_rehashed_corruptions_cannot_hide_lost_mass_pending_delta_or_rng_change(
        transaction_evidence, record_property, mutation, reason):
    record_cost_once([transaction_evidence["counter"]], record_property)
    before = transaction_evidence["populated"]
    baseline = deepcopy(before)
    after = deepcopy(before)
    if mutation == "DROP_OLD_OWN":
        del after["own_average"][sorted(before["own_average"])[0]]
    elif mutation == "RETAIN_PENDING_OWN":
        pending = transaction_evidence["faults"]["WALK_AFTER_UPDATES"][
            "collector"]["average"]
        k, action = next((k, a) for k in sorted(pending) for a in ("L", "R")
                         if pending[k][a] > 0)
        after["own_average"][k][action] += pending[k][action]
        assert after["own_average"][k][action] > before["own_average"][k][action]
    else:
        after["production"]["rng_state"] = deepcopy(
            transaction_evidence["initial"]["production"]["rng_state"])
        after["production"].pop("sha256")
        after["production"]["sha256"] = canonical_hash(after["production"])
    after.pop("sha256")
    after["sha256"] = canonical_hash(after)
    row = execute_case(
        {"id": mutation, "status": "NOT_RUN", "reason": "NOT_REACHED",
         "before": deepcopy(before), "mutated_after": deepcopy(after)},
        lambda evidence: assert_populated_checkpoint_equal(
            evidence["before"], evidence["mutated_after"]))
    assert row["status"] == "FAIL"
    assert row["reason"] == "AssertionError: " + reason
    assert row["before"] == baseline and row["mutated_after"] == after
    assert transaction_evidence["populated"] == baseline


def test_malformed_actual_export_menu_is_a_contract_failure(
        transaction_evidence, record_property):
    record_cost_once([transaction_evidence["counter"]], record_property)
    before, exports = transaction_evidence["populated"], transaction_evidence["exports"]
    baseline, baseline_exports = deepcopy(before), deepcopy(exports)
    malformed = deepcopy(exports["simple"])
    k = sorted(malformed)[0]
    malformed[k]["X"] = malformed[k].pop("L")
    row = execute_case(
        {"id": "MALFORMED_SIMPLE_EXPORT_MENU", "status": "NOT_RUN",
         "reason": "NOT_REACHED", "export": malformed,
         "quantities": deepcopy(before["production"]["average"])},
        lambda evidence: _assert_normalization(
            evidence["quantities"], evidence["export"]))
    assert row["status"] == "FAIL"
    assert row["reason"] == "AssertionError: EXPORT_ACTION_MENU_CHANGED"
    assert row["export"] == malformed
    assert row["quantities"] == before["production"]["average"]
    assert transaction_evidence["populated"] == baseline
    assert transaction_evidence["exports"] == baseline_exports
