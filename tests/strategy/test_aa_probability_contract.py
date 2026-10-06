"""Shared loader/worker boundaries using public synthetic documents only."""

from copy import deepcopy
from decimal import Decimal
import math
import time

import pytest

from poker_engine.desktop.aa_frozen_shadow import AAFrozenShadowSession
from poker_engine.desktop.aa_policy_worker import AAIsolatedPolicyWorker
from poker_engine.desktop.aa_turn_runtime import (
    AATurnWindow, TurnEvidence, TurnIdentity,
)
from poker_engine.strategy.aa_frozen_policy import (
    FrozenResearchPolicy, canonical_hash, information_key, make_policy,
    validate_distribution,
)
from poker_engine.strategy.aa_frozen_policy_v2 import (
    FrozenResearchPolicyV2, make_policy_v2,
)
from poker_engine.strategy.aa_policy_encoding_v2 import information_key_v2


def observation():
    return {
        "own_hole": ["As", "Kd"], "board": [], "board_history": [],
        "street": "preflop", "actor": 3, "observing_seat": 3,
        "occupied_seats": list(range(6)), "dealer_seat": 5,
        "stacks": {str(i): "200" for i in range(6)},
        "starting_stacks": {str(i): "200" for i in range(6)},
        "bets": {str(i): "0" for i in range(6)},
        "contributions": {str(i): "0" for i in range(6)},
        "straddler_seat": None, "to_call": "2", "big_blind": "2",
        "pot": "3", "folded": [], "all_in": [], "public_history": [],
        "rules_fingerprint": "a" * 64, "table_size": 6,
        "arena_version": "aa-full-hand-arena-v1", "simulation_only": True,
        "strategy_eligible": False, "terminal": False,
        "legal_actions": [
            {"id": "fold", "kind": "fold", "raise_to": None},
            {"id": "check_call", "kind": "check_call", "raise_to": None}],
        "betting": {
            "can_raise": True, "min_raise_to": "4", "max_raise_to": "200",
            "last_full_raise_increment": "2", "acted_since_full_raise": [],
            "pending_actors": list(range(6)),
            "consecutive_short_raise_increments": []},
    }


def artifact(version, distribution):
    obs = observation()
    factory, encode, load = (make_policy, information_key, FrozenResearchPolicy)
    if version == 2:
        factory, encode, load = (
            make_policy_v2, information_key_v2, FrozenResearchPolicyV2)
    document = factory(
        rules_fingerprint=obs["rules_fingerprint"], table_size=6,
        stack_depth_bb=100, policy={encode(obs): {"fold": .5, "check_call": .5}},
        training={"kind": "synthetic_contract_fixture_no_training"})
    # Rehash to ensure a refusal tests the distribution rather than its digest.
    document["policy"][encode(obs)] = deepcopy(distribution)
    document.pop("sha256")
    document["sha256"] = canonical_hash(document)
    return document, obs, load


def edge_masses():
    tolerance = 1e-12
    upper = 1 + tolerance
    if upper - 1 > tolerance:
        upper = math.nextafter(upper, 1)
    lower = 1 - tolerance
    if 1 - lower > tolerance:
        lower = math.nextafter(lower, 1)
    return [(1.0, True), (1 + 5e-13, True), (1 - 5e-13, True),
            (upper, True), (lower, True),
            (math.nextafter(upper, math.inf), False),
            (math.nextafter(lower, -math.inf), False),
            (1 + 5e-10, False), (1 - 5e-10, False)]


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("mass,accepted", edge_masses())
def test_mass_edges_loader_worker_and_session_agree_without_repair(
        version, mass, accepted):
    distribution = {"fold": mass / 2, "check_call": mass / 2}
    assert (abs(math.fsum(distribution.values()) - 1) <= 1e-12) is accepted
    document, obs, load = artifact(version, distribution)
    original = deepcopy(document)
    if accepted:
        frozen = load(document)
        assert frozen.distribution(obs) == distribution
        assert frozen.inspect_lookup(obs)["status"] == "HIT"
        worker = AAIsolatedPolicyWorker(frozen.frozen_map())
        assert worker._policy == document["policy"]
        assert worker.policy_sha256 == canonical_hash(document["policy"])
        session = AAFrozenShadowSession(document)
        session.close()
    else:
        with pytest.raises(ValueError, match="policy_probability_mass"):
            load(document)
        with pytest.raises(ValueError, match="policy_probability_mass"):
            AAIsolatedPolicyWorker(document["policy"])
        with pytest.raises(ValueError, match="policy_probability_mass"):
            AAFrozenShadowSession(document)
    assert document == original


@pytest.mark.parametrize("bad", [
    float("nan"), float("inf"), float("-inf"), -1e-16, 1 + 5e-13,
    2, 10**1000, True, "1", None, Decimal("1"),
])
def test_invalid_probability_is_rejected_before_serialization_or_spawn(bad):
    distribution = {"check_call": bad}
    with pytest.raises(ValueError, match="invalid_policy_probability"):
        validate_distribution(distribution, ("check_call",))
    with pytest.raises(ValueError, match="invalid_policy_probability"):
        AAIsolatedPolicyWorker({"a" * 64: distribution})
    # Nonfinite/unsupported JSON values may be rejected by the digest layer.
    for factory in (make_policy, make_policy_v2):
        with pytest.raises((ValueError, TypeError)):
            factory(rules_fingerprint="a" * 64, table_size=6, stack_depth_bb=100,
                    policy={"b" * 64: distribution}, training={})


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("distribution", [
    {"fold": -1e-16, "check_call": 1.0},
    {"fold": 0, "check_call": 1 + 5e-13}, {}, {"": 1.0}, {1: 1.0},
    {True: 1.0},
])
def test_invalid_rehashed_artifact_and_original_worker_keys_refuse(
        version, distribution):
    document, _, load = artifact(version, distribution)
    with pytest.raises(ValueError):
        load(document)
    with pytest.raises(ValueError):
        AAIsolatedPolicyWorker(document["policy"])


@pytest.mark.parametrize("ids", [(), ("",), (1,), ("fold", "fold"), None])
def test_empty_invalid_or_duplicate_expected_menu_is_rejected(ids):
    with pytest.raises(ValueError, match="invalid_legal_menu"):
        validate_distribution({"fold": 1.0}, ids)


def test_missing_or_extra_action_cannot_hide_behind_probability_mass():
    for distribution in ({"fold": 1}, {"fold": .5, "extra": .5}):
        with pytest.raises(ValueError, match="policy_action_menu_mismatch"):
            validate_distribution(distribution, ("fold", "check_call"))


@pytest.mark.parametrize("key", [1, True, ""])
def test_worker_information_key_is_not_coerced_by_json(key):
    with pytest.raises(ValueError, match="information key"):
        AAIsolatedPolicyWorker({key: {"call": 1}})


def test_native_zero_one_generic_actions_and_empty_policy_remain_compatible():
    validate_distribution({"call": 1, "fold": 0}, ("fold", "call"))
    assert AAIsolatedPolicyWorker({"i": {"call": 1, "fold": 0}})._policy == {
        "i": {"call": 1, "fold": 0}}
    assert AAIsolatedPolicyWorker({})._policy == {}


def test_stable_mass_and_digest_do_not_depend_on_dictionary_order():
    pairs = [("main", 1 - 63e-16)] + [(f"tiny{i}", 1e-16) for i in range(63)]
    distributions = [dict(pairs), dict(reversed(pairs))]
    hashes = []
    for distribution in distributions:
        validate_distribution(distribution, tuple(distribution))
        worker = AAIsolatedPolicyWorker({"i": distribution})
        assert worker._policy["i"] == distribution
        hashes.append(worker.policy_sha256)
    assert hashes[0] == hashes[1]


@pytest.mark.parametrize("version", [1, 2])
def test_valid_policy_actual_spawn_and_unknown_or_illegal_refusal(version):
    document, obs, _ = artifact(version, {"fold": 0, "check_call": 1})
    session = AAFrozenShadowSession(document)
    try:
        session.preload()
        now = time.monotonic()
        identity = TurnIdentity("contract-synthetic", 0, "hand", "turn")
        window = AATurnWindow(
            identity, TurnEvidence("synthetic-only", "verified_onset", now, 10),
            now=now)
        fields = dict(identity=identity, window=window, source_at=now,
                      is_current=lambda binding: True, clock=time.monotonic)
        result = session.lookup(obs, **fields)
        assert result["status"] == "SHADOW_RESULT"
        assert result["action"] == "check_call"
        assert not result["strategy_eligible"] and not result["advice_emitted"]
        unknown = deepcopy(obs)
        unknown["pot"] = "4"
        assert session.lookup(unknown, **fields)["reason"] == "POLICY_COVERAGE_MISS"
        worker_fields = {**fields, "state_key": "state", "rules_fingerprint": "a" * 64,
                         "legal_actions": ["fold"]}
        key = next(iter(document["policy"]))
        illegal = session.worker.lookup(key, **worker_fields)
        assert illegal["reason"] == "ILLEGAL_ACTION" and illegal["action"] is None
    finally:
        session.close()
