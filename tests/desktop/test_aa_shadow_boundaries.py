"""Fixed public synthetic clocks and IPC; no capture, fitting or real waiting.

Parent encoding shares the absolute source/turn window. The worker's separate
300ms allowance starts at worker entry and includes binding and acceptance.
These tests establish admission timestamps, not hard real-time return latency.
"""

from copy import deepcopy

import pytest

from poker_engine.desktop import aa_frozen_shadow as shadow
from poker_engine.desktop import aa_policy_worker as workers
from poker_engine.desktop.aa_turn_runtime import (
    AATurnWindow, TurnEvidence, TurnIdentity,
)
from poker_engine.strategy import aa_frozen_policy as v1
from poker_engine.strategy import aa_frozen_policy_v2 as v2
from poker_engine.strategy import aa_policy_encoding_v2 as encoding
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from tools.aa_full_hand_lab import DEFAULT_RULES, rules_for


IDENTITY = TurnIdentity("public-synthetic", 0, "hand", "turn")
START = 100.0


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


class Connection:
    """A reply transport with time advanced only at named semantic events."""

    def __init__(self, clock, *, action="check_call", reply_key=None, on_recv=None):
        self.clock = clock
        self.action = action
        self.reply_key = reply_key
        self.on_recv = on_recv
        self.sent = []
        self.sent_at = []
        self.poll_timeouts = []
        self.closed = False

    def send(self, request):
        self.sent.append(request)
        self.sent_at.append(self.clock.now)

    def poll(self, timeout):
        self.poll_timeouts.append(timeout)
        return True

    def recv(self):
        if self.on_recv is not None:
            self.on_recv()
        key = self.sent[-1][0] if self.reply_key is None else self.reply_key
        return key, self.action

    def close(self):
        self.closed = True


@pytest.fixture(scope="module")
def public_case():
    rules = rules_for(DEFAULT_RULES, 6)
    arena = AAFullHandArena(rules).reset(11)
    observation = arena.observe(arena.actor)
    distribution = {row["id"]: float(row["id"] == "check_call")
                    for row in observation["legal_actions"]}
    return rules.fingerprint, observation, distribution


def make_session(version, public_case, *, coverage=True, key_observation=None):
    fingerprint, observation, distribution = public_case
    observation = deepcopy(observation)
    key_function, factory = (v1.information_key, v1.make_policy) if version == 1 else (
        encoding.information_key_v2, v2.make_policy_v2)
    key = key_function(observation if key_observation is None else key_observation)
    artifact = factory(
        rules_fingerprint=fingerprint, table_size=6, stack_depth_bb=100,
        policy={key: distribution} if coverage else {},
        training={"kind": "public_synthetic_wiring_not_learned"},
    )
    return shadow.AAFrozenShadowSession(artifact), observation, key, distribution


def count_encoder(monkeypatch, session, version, *, before=None):
    calls = []
    original = v1.information_key if version == 1 else v2.encode_decision_v2

    def counted(observation):
        calls.append(1)
        if before is not None:
            before()
        return original(observation)

    if version == 1:
        monkeypatch.setattr(v1, "information_key", counted)
        if hasattr(shadow, "information_key"):
            monkeypatch.setattr(shadow, "information_key", counted)
    else:
        monkeypatch.setattr(v2, "encode_decision_v2", counted)
        monkeypatch.setattr(encoding, "encode_decision_v2", counted)
    # If the old second-encoder adapter is reintroduced, count that alias too.
    if hasattr(session, "_information_key"):
        monkeypatch.setattr(session, "_information_key", counted)
    return calls


def lookup_fields(clock):
    window = AATurnWindow(
        IDENTITY, TurnEvidence("public", "verified_onset", START, 10), now=START,
    )
    return dict(identity=IDENTITY, window=window, source_at=START,
                is_current=lambda binding: True, clock=clock), window


def ready_worker(clock, **connection_fields):
    worker = workers.AAIsolatedPolicyWorker({"key": {"check_call": 1}}, seed=17)
    connection = Connection(clock, **connection_fields)
    worker._ready, worker._connection = True, connection
    return worker, connection


def worker_lookup(worker, fields):
    return worker.lookup("key", state_key="state", rules_fingerprint="rules",
                         legal_actions=["check_call"], **fields)


def assert_shadow_boundary(result):
    assert result["strategy_eligible"] is False
    assert result["advice_emitted"] is False
    if result["status"] == "ABSTAIN":
        assert result["action"] is None


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("milliseconds,budget,reason", [
    (0, .3, None), (400, .3, None), (950, .05, None),
    (1050, None, "SOURCE_STALE"),
])
def test_parent_encoding_uses_absolute_window_and_separate_worker_allowance(
        monkeypatch, public_case, version, milliseconds, budget, reason):
    session, observation, key, _ = make_session(version, public_case)
    clock = Clock()
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(
        monkeypatch, session, version,
        before=lambda: setattr(clock, "now", START + milliseconds / 1000),
    )
    fields, window = lookup_fields(clock)

    result = session.lookup(observation, **fields)

    assert len(calls) == 1
    assert_shadow_boundary(result)
    if reason is None:
        assert result["status"] == "SHADOW_RESULT"
        assert result["action"] == "check_call"
        assert connection.sent == [(result["request_key"], key)]
        assert connection.poll_timeouts == pytest.approx([budget])
        assert window._first_result_at == START + milliseconds / 1000
    else:
        assert result["reason"] == reason
        assert connection.sent == connection.poll_timeouts == []
        assert window._first_result_at is None


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("coverage", [True, False], ids=["hit", "miss"])
def test_hit_and_miss_encode_once_without_inventing_coverage(
        monkeypatch, public_case, version, coverage):
    session, observation, _, _ = make_session(version, public_case, coverage=coverage)
    clock = Clock()
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(monkeypatch, session, version)
    fields, window = lookup_fields(clock)

    result = session.lookup(observation, **fields)

    assert len(calls) == 1
    assert_shadow_boundary(result)
    assert result["status"] == ("SHADOW_RESULT" if coverage else "ABSTAIN")
    if not coverage:
        assert result["reason"] == "POLICY_COVERAGE_MISS"
        assert connection.sent == []
        assert window._first_result_at is None


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("failure", ["scope", "menu", "encoder"])
def test_scope_menu_and_encoder_errors_do_not_dispatch(
        monkeypatch, public_case, version, failure):
    invalid_menu = deepcopy(public_case[1])
    invalid_menu["legal_actions"] = []
    # V1 preserves its existing encode -> hit -> menu ordering. Give the invalid
    # observation a real covered key; V2 validates the menu before encoding.
    key_observation = invalid_menu if failure == "menu" and version == 1 else None
    session, observation, _, _ = make_session(
        version, public_case, key_observation=key_observation)
    clock = Clock()
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    if failure == "scope":
        observation["table_size"] = 7
        expected, expected_calls = "policy_rule_scope_mismatch", 0
    elif failure == "menu":
        observation["legal_actions"] = []
        expected, expected_calls = "invalid_legal_menu", int(version == 1)
    else:
        expected, expected_calls = "synthetic_encoder_failure", 1

    def fail_encoder():
        if failure == "encoder":
            raise ValueError(expected)

    calls = count_encoder(monkeypatch, session, version, before=fail_encoder)
    fields, window = lookup_fields(clock)
    with pytest.raises(ValueError, match=expected):
        session.lookup(observation, **fields)
    assert len(calls) == expected_calls
    assert connection.sent == []
    assert window._first_result_at is None


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("coverage", [True, False], ids=["hit", "miss"])
def test_key_distribution_api_preserves_legacy_result_and_detaches_maps(
        monkeypatch, public_case, version, coverage):
    session, observation, expected_key, expected = make_session(
        version, public_case, coverage=coverage)
    calls = count_encoder(monkeypatch, session, version)

    key, distribution = session.policy.distribution_with_key(observation)

    assert key == expected_key
    assert len(calls) == 1
    assert distribution == (expected if coverage else None)
    if coverage:
        distribution["check_call"] = 0
        assert session.policy.frozen_map()[key] == expected
    assert session.policy.distribution(observation) == (expected if coverage else None)
    assert len(calls) == 2


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("milliseconds", [1000, 1050])
def test_expired_source_at_entry_skips_encoding_and_dispatch(
        monkeypatch, public_case, version, milliseconds):
    session, observation, _, _ = make_session(version, public_case)
    clock = Clock()
    fields, window = lookup_fields(clock)
    clock.now = START + milliseconds / 1000
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(monkeypatch, session, version)

    result = session.lookup(observation, **fields)

    assert result["reason"] == "SOURCE_STALE"
    assert_shadow_boundary(result)
    assert calls == connection.sent == []
    assert window._first_result_at is None


@pytest.mark.parametrize("version", [1, 2])
def test_coverage_miss_after_source_expiry_preserves_temporal_refusal(
        monkeypatch, public_case, version):
    session, observation, _, _ = make_session(version, public_case, coverage=False)
    clock = Clock()
    fields, window = lookup_fields(clock)
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(monkeypatch, session, version,
                          before=lambda: setattr(clock, "now", START + 1.05))

    result = session.lookup(observation, **fields)

    assert result["reason"] == "SOURCE_STALE"
    assert_shadow_boundary(result)
    assert len(calls) == 1
    assert connection.sent == []
    assert window._first_result_at is None


@pytest.mark.parametrize("version", [1, 2])
def test_expired_entry_precedes_scope_validation_without_encoding(
        monkeypatch, public_case, version):
    session, observation, _, _ = make_session(version, public_case)
    observation["table_size"] = 7
    clock = Clock()
    fields, window = lookup_fields(clock)
    clock.now = START + 1
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(monkeypatch, session, version)

    result = session.lookup(observation, **fields)

    assert result["reason"] == "SOURCE_STALE"
    assert_shadow_boundary(result)
    assert calls == connection.sent == []
    assert window._first_result_at is None


@pytest.mark.parametrize("milliseconds,reason", [
    (0, None), (100, None), (299, None), (300, "COMPUTATION_DEADLINE"),
    (400, "COMPUTATION_DEADLINE"), (950, "COMPUTATION_DEADLINE"),
    (1050, "SOURCE_STALE"),
])
def test_binding_cost_is_inside_worker_budget_and_expiry_prevents_send(
        monkeypatch, milliseconds, reason):
    clock = Clock()
    worker, connection = ready_worker(clock)
    fields, window = lookup_fields(clock)
    original = workers._canonical

    def delayed_binding(value):
        clock.now = START + milliseconds / 1000
        return original(value)

    monkeypatch.setattr(workers, "_canonical", delayed_binding)
    result = worker_lookup(worker, fields)

    assert_shadow_boundary(result)
    if reason is None:
        assert result["status"] == "SHADOW_RESULT"
        assert len(connection.sent) == 1
        assert connection.poll_timeouts == pytest.approx([.3 - milliseconds / 1000])
    else:
        assert result["reason"] == reason
        assert connection.sent == connection.poll_timeouts == []
        assert window._first_result_at is None
        assert worker._ready is True  # An idle worker was never dispatched.


def test_tightened_window_during_binding_reduces_poll_without_restarting_budget(
        monkeypatch):
    clock = Clock()
    worker, connection = ready_worker(clock)
    fields, window = lookup_fields(clock)
    original = workers._canonical

    def tighten_during_binding(value):
        clock.now = START + .1
        window.tighten(TurnEvidence(
            "later-public-countdown", "verified_countdown_lower_bound", clock.now, 8.05,
        ), now=clock.now)
        return original(value)

    monkeypatch.setattr(workers, "_canonical", tighten_during_binding)
    result = worker_lookup(worker, fields)

    assert result["status"] == "SHADOW_RESULT"
    assert len(connection.sent) == 1
    assert window.first_result_deadline == pytest.approx(START + .15)
    assert connection.poll_timeouts == pytest.approx([.05])
    assert window._first_result_at == START + .1
    assert_shadow_boundary(result)


@pytest.mark.parametrize("milliseconds", [0, 299, 300, 301])
def test_received_result_requires_strictly_before_absolute_worker_deadline(
        milliseconds):
    clock = Clock()
    worker, connection = ready_worker(
        clock, on_recv=lambda: setattr(clock, "now", START + milliseconds / 1000))
    fields, window = lookup_fields(clock)

    result = worker_lookup(worker, fields)

    assert len(connection.sent) == 1
    assert_shadow_boundary(result)
    if milliseconds < 300:
        assert result["status"] == "SHADOW_RESULT"
        assert window._first_result_at < START + .3
    else:
        assert result["reason"] == "COMPUTATION_DEADLINE"
        assert window._first_result_at is None
        assert worker._ready is False


@pytest.mark.parametrize("milliseconds", [0, 299, 300, 301])
def test_state_recheck_cost_cannot_extend_worker_deadline(milliseconds):
    clock = Clock()
    worker, connection = ready_worker(clock)
    fields, window = lookup_fields(clock)

    def current(binding):
        assert binding["state"] == "state"
        clock.now = START + milliseconds / 1000
        return True

    fields["is_current"] = current
    result = worker_lookup(worker, fields)

    assert len(connection.sent) == 1
    assert_shadow_boundary(result)
    if milliseconds < 300:
        assert result["status"] == "SHADOW_RESULT"
        assert window._first_result_at < START + .3
    else:
        assert result["reason"] == "COMPUTATION_DEADLINE"
        assert window._first_result_at is None


@pytest.mark.parametrize("failure,reason", [
    ("missing", "POLICY_COVERAGE_MISS"), ("illegal", "ILLEGAL_ACTION"),
    ("changed", "STATE_CHANGED"), ("wrong_reply", "RESPONSE_IDENTITY_MISMATCH"),
])
def test_response_coverage_action_state_and_binding_gates_remain_closed(
        failure, reason):
    clock = Clock()
    action = None if failure == "missing" else (
        "raise_to:999" if failure == "illegal" else "check_call")
    worker, connection = ready_worker(
        clock, action=action, reply_key="wrong" if failure == "wrong_reply" else None)
    fields, window = lookup_fields(clock)
    fields["is_current"] = lambda binding: failure != "changed"

    result = worker_lookup(worker, fields)

    assert result["reason"] == reason
    assert_shadow_boundary(result)
    assert len(connection.sent) == 1
    assert window._first_result_at is None


@pytest.mark.parametrize("version", [1, 2])
def test_repeated_requests_reencode_without_rerolling_bound_request_identity(
        monkeypatch, public_case, version):
    session, observation, key, _ = make_session(version, public_case)
    clock = Clock()
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(monkeypatch, session, version)
    fields, window = lookup_fields(clock)

    first = session.lookup(observation, **fields)
    clock.now += .1
    second = session.lookup(observation, **fields)

    assert len(calls) == 2
    assert first["request_key"] == second["request_key"]
    assert first["binding"] == second["binding"]
    assert first["action"] == second["action"] == "check_call"
    binding = first["binding"]
    assert binding["information"] == key
    assert binding["state"] == v1.canonical_hash(observation)
    assert binding["rules"] == observation["rules_fingerprint"]
    assert binding["policy"] == session.worker.policy_sha256
    assert binding["legal"] == sorted(row["id"] for row in observation["legal_actions"])
    assert window._first_result_at == START
    assert len(connection.sent) == 2
    assert_shadow_boundary(first)
    assert_shadow_boundary(second)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("gate,reason", [
    ("first", "FIRST_RESULT_DEADLINE"), ("reserve", "OPERATION_RESERVE"),
    ("identity", "TURN_IDENTITY_CHANGED"),
])
def test_absolute_first_reserve_and_identity_gates_are_not_reset_by_encoding(
        monkeypatch, public_case, version, gate, reason):
    session, observation, _, _ = make_session(version, public_case)
    clock = Clock()
    fields, window = lookup_fields(clock)
    expected_calls = 1
    if gate == "first":
        clock.now = window.first_result_deadline - .05
        fields["source_at"] = clock.now
        after_encoding = window.first_result_deadline
    elif gate == "reserve":
        assert window.record_first_result(now=START, identity=IDENTITY,
                                          source_at=START) == "WITHIN_BUDGET"
        clock.now = window.deadline - 3 - .05
        fields["source_at"] = clock.now
        after_encoding = window.deadline - 3
    else:
        fields["identity"] = TurnIdentity("public-synthetic", 0, "hand", "other-turn")
        after_encoding, expected_calls = START, 0
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(monkeypatch, session, version,
                          before=lambda: setattr(clock, "now", after_encoding))

    result = session.lookup(observation, **fields)

    assert result["reason"] == reason
    assert_shadow_boundary(result)
    assert len(calls) == expected_calls
    assert connection.sent == []
    assert window._first_result_at == (START if gate == "reserve" else None)


@pytest.mark.parametrize("version", [1, 2])
def test_state_hash_after_encoding_cannot_dispatch_with_expired_source(
        monkeypatch, public_case, version):
    session, observation, _, _ = make_session(version, public_case)
    clock = Clock()
    fields, window = lookup_fields(clock)
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(monkeypatch, session, version)
    original = shadow.canonical_hash

    def delayed_state_hash(value):
        clock.now = START + 1.05
        return original(value)

    monkeypatch.setattr(shadow, "canonical_hash", delayed_state_hash)
    result = session.lookup(observation, **fields)

    assert len(calls) == 1
    assert result["reason"] == "SOURCE_STALE"
    assert_shadow_boundary(result)
    assert connection.sent == []
    assert window._first_result_at is None


def test_acceptance_uses_the_timestamp_that_passed_the_worker_deadline_check():
    class AdvancingClock(Clock):
        advancing = False

        def __call__(self):
            sampled_at = self.now
            if self.advancing:
                self.now += .004
            return sampled_at

    clock = AdvancingClock()
    worker, _ = ready_worker(clock)
    fields, window = lookup_fields(clock)
    absolute_deadline = START + .3

    def current(binding):
        # A final sample just before D is valid. A second read solely to record
        # the result would cross D and use a timestamp that was never admitted.
        clock.now = absolute_deadline - .001
        clock.advancing = True
        return True

    fields["is_current"] = current
    result = worker_lookup(worker, fields)

    assert result["status"] == "SHADOW_RESULT"
    assert window._first_result_at == absolute_deadline - .001
    assert window._first_result_at < absolute_deadline
    assert_shadow_boundary(result)


@pytest.mark.parametrize("version", [1, 2])
def test_synthetic_guard_still_rejects_promoted_input_before_any_encoding(
        monkeypatch, public_case, version):
    session, observation, _, _ = make_session(version, public_case)
    observation["simulation_only"] = False
    clock = Clock()
    fields, window = lookup_fields(clock)
    connection = Connection(clock)
    session.worker._ready, session.worker._connection = True, connection
    calls = count_encoder(monkeypatch, session, version)

    with pytest.raises(ValueError, match="shadow_adapter_requires_synthetic_arena"):
        session.lookup(observation, **fields)
    assert calls == connection.sent == []
    assert window._first_result_at is None
