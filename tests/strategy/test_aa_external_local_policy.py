"""Development-only contract controls, never evidence of model playing strength."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_arena_evaluation import (  # noqa: E402
    check_call_policy, evaluate_paired,
)
from poker_engine.strategy.aa_external_local_policy import (  # noqa: E402
    ExternalLocalResearchPolicy, REQUEST_FORMAT, select_action,
)
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena  # noqa: E402
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2  # noqa: E402


DEVELOPMENT_SEEDS = (4441, 4442)


def rules(n=6):
    return AARuleProfileV2.from_dict({
        "schema_version": 2, "table_size": n, "small_blind": "1", "big_blind": "2",
        "ante": "0", "ante_mode": "none", "straddle_mode": "none",
        "straddle_amount": "0", "rake_percent": "0", "rake_cap_bb": "0",
        "rake_application": "all_pots", "rake_rounding": "exact",
        "rake_distribution": "proportional_all_pots", "minimum_chip": "0.01",
        "verification_status": "simulation",
        "source": "synthetic-contract-test-not-model-evidence",
    })


def observation(profile=None):
    arena = AAFullHandArena(profile or rules()).reset(DEVELOPMENT_SEEDS[0])
    return arena.observe(arena.actor)


def synthetic_check_call_scores(request):
    return {option["id"]: float(option["id"] == "check_call")
            for option in request["options"]}


def policy(profile=None, scorer=synthetic_check_call_scores, **kwargs):
    return ExternalLocalResearchPolicy(
        profile or rules(), scorer, model_id="synthetic-positive-control",
        model_revision="development-v1-not-a-model", **kwargs)


@pytest.mark.parametrize("n", (6, 7, 8))
def test_actual_evaluator_all_four_streets_matches_direct_check_call(n):
    profile = rules(n)
    requests = []

    def scorer(request):
        requests.append(deepcopy(request))
        return synthetic_check_call_scores(request)

    candidate = policy(profile, scorer)
    report = evaluate_paired(
        profile, candidate, check_call_policy, {"passive": check_call_policy},
        seeds=DEVELOPMENT_SEEDS, bootstrap_samples=100, record_diagnostics=True)
    assert report["complete_pairs"] == report["expected_pairs"] == n * 2
    assert report["blocked_pairs"] == 0
    assert {r["state"]["street"] for r in requests} == {
        "preflop", "flop", "turn", "river"}
    assert len(requests) == n * 2 * 4  # inspector and repeated calls never infer
    for row in report["rows"]:
        for key in ("trace_sha256", "return_chips", "terminal"):
            assert row["candidate"][key] == row["baseline"][key]
        for opportunity in row["candidate"]["hero_opportunities"]:
            assert opportunity["lookup_status"] == "INPUT_READY"
            assert opportunity["policy_latency_ms"] >= 0
    assert report["candidate_diagnostics"]["first_hero_hit"] == 0
    assert report["strategy_eligible"] is False


def test_request_retains_chronology_exact_money_and_off_grid_legal_option():
    profile = rules()
    arena = AAFullHandArena(profile).reset(DEVELOPMENT_SEEDS[0])
    arena.step("raise_to:5.37")  # engine-validated raise outside abstract menu
    obs = arena.observe(arena.actor)
    obs["legal_actions"].append({
        "id": "raise_to:12.13", "kind": "raise_to", "raise_to": "12.13"})
    request = policy(profile).prepare_request(obs)
    assert request["state"]["public_history"][0]["raise_to"] == "5.37"
    assert request["state"]["public_history"][0]["paid"] == "5.37"
    assert request["options"][-1]["id"] == "raise_to:12.13"
    assert request["options"][-1]["text"] == "Raise to 12.13 chips total this street"
    assert request["state"]["to_call"] == obs["to_call"]
    while arena.street != "river":
        arena.step("check_call")
    request = policy(profile).prepare_request(arena.observe(arena.actor))
    assert [row["street"] for row in request["state"]["board_history"]] == [
        "flop", "turn", "river"]
    assert [len(row["cards"]) for row in request["state"]["board_history"]] == [3, 1, 1]
    assert len(request["state"]["own_hole"]) == 2


def test_no_unknown_metadata_source_paths_or_salt_are_forwarded():
    profile = replace(rules(), source="C:/private/DO_NOT_SEND_SOURCE")
    obs = observation(profile)
    obs["metadata"] = {"arbitrary": "DO_NOT_SEND_META"}
    obs["betting"]["unused"] = "DO_NOT_SEND_BETTING_EXTRA"
    obs["legal_actions"][0]["description"] = "DO_NOT_SEND_OPTION_EXTRA"
    requests = []

    def scorer(request):
        requests.append(request)
        return synthetic_check_call_scores(request)

    candidate = policy(profile, scorer)
    salt = "abcdef12" * 8
    assert candidate.for_game(salt)(obs) == "check_call"
    text = json.dumps(requests)
    assert "DO_NOT_SEND" not in text and salt not in text
    assert "rules_fingerprint" not in text and "verification_status" not in text
    assert "schema_version" not in text
    assert set(requests[0]) == {"format", "question", "state", "rules", "options"}
    assert requests[0]["format"] == REQUEST_FORMAT


@pytest.mark.parametrize("field", [
    "seed", "deck_seed", "deal_seed", "rng_state", "opponent_hole",
    "opponent_cards", "all_holes", "future_board", "next_board", "showdown",
    "terminal_returns", "actual_action", "private_state", "unrevealed_cards",
])
@pytest.mark.parametrize("location", ("top", "nested"))
def test_private_future_seed_injections_refuse_before_scorer(field, location):
    obs = observation()
    if location == "top":
        obs[field] = "SECRET"
    else:
        obs["metadata"] = [{"anything": {field: "SECRET"}}]
    calls = []
    candidate = policy(scorer=lambda req: calls.append(req))
    diagnostic = candidate.inspect_lookup(obs)
    assert diagnostic["status"] == "INVALID_OBSERVATION"
    assert "private_or_future" in diagnostic["reason"]
    with pytest.raises(ValueError, match="private_or_future"):
        candidate(obs)
    assert calls == []


@pytest.mark.parametrize("field", ["simulation_only", "strategy_eligible"])
def test_missing_explicit_simulation_provenance_is_refused(field):
    obs = observation()
    del obs[field]
    with pytest.raises(ValueError, match="simulation_provenance"):
        policy()(obs)


def test_live_rules_and_live_observations_are_refused():
    with pytest.raises(ValueError, match="simulation_rules"):
        policy(replace(rules(), verification_status="live_verified"))
    candidate = policy()
    with pytest.raises(ValueError, match="no_live_admission"):
        candidate.require_live()
    for field, value in (("simulation_only", False), ("strategy_eligible", True),
                         ("advice_emitted", True)):
        obs = observation()
        obs[field] = value
        with pytest.raises(ValueError, match="simulation_provenance"):
            candidate(obs)


@pytest.mark.parametrize("alter", ["fingerprint", "embedded_rules", "table", "bb"])
def test_wrong_rules_binding_cannot_use_matching_fingerprint_string_alone(alter):
    obs = observation()
    if alter == "fingerprint":
        obs["rules_fingerprint"] = "1" * 64
    elif alter == "embedded_rules":
        obs["rules"]["rake_percent"] = "0.03"
    elif alter == "table":
        obs["table_size"] = 7
    else:
        obs["big_blind"] = "3"
    with pytest.raises(ValueError, match="rule_scope_mismatch"):
        policy()(obs)


@pytest.mark.parametrize("alter", ["missing", "duplicate", "illegal", "bounds"])
def test_malformed_and_out_of_bounds_legal_menus_fail_closed(alter):
    obs = observation()
    if alter == "missing":
        obs.pop("legal_actions")
    elif alter == "duplicate":
        obs["legal_actions"].append(deepcopy(obs["legal_actions"][0]))
    elif alter == "illegal":
        obs["legal_actions"][0]["id"] = "raise_to:9999"
    else:
        obs["legal_actions"].append({
            "id": "raise_to:9999", "kind": "raise_to", "raise_to": "9999"})
    with pytest.raises(ValueError, match="menu"):
        policy()(obs)


@pytest.mark.parametrize("field", [
    "rules", "own_hole", "board_history", "betting", "contributions", "public_history",
])
def test_missing_required_inputs_refuse_without_inference(field):
    obs = observation()
    del obs[field]
    candidate = policy(scorer=lambda req: pytest.fail("must not infer"))
    assert candidate.inspect_lookup(obs)["status"] == "INVALID_OBSERVATION"
    with pytest.raises(ValueError):
        candidate(obs)


def test_invalid_model_scores_keep_all_paired_failures_in_denominator():
    candidate = policy(scorer=lambda request: {"invented_action": 1})
    report = evaluate_paired(
        rules(), candidate, check_call_policy, {"passive": check_call_policy},
        seeds=DEVELOPMENT_SEEDS, bootstrap_samples=100, record_diagnostics=True)
    assert report["expected_pairs"] == report["blocked_pairs"] == 12
    assert report["groups"][0]["delta_net_bb100"] is None
    assert all(row["candidate"]["error"] == "external_scores_must_match_legal_menu"
               for row in report["rows"])
    assert all(row["candidate"]["return_chips"] is None for row in report["rows"])


@pytest.mark.parametrize("scores", [
    {}, {"fold": 1}, {"fold": 1, "check_call": 0, "extra": 2},
    {"fold": -1, "check_call": 2}, {"fold": float("nan"), "check_call": 1},
    {"fold": float("inf"), "check_call": 1}, {"fold": 0, "check_call": 0},
    {"fold": True, "check_call": 1}, {"fold": "1", "check_call": 1},
    {"fold": None, "check_call": 1},
])
def test_scores_require_exact_menu_finite_nonnegative_positive_mass(scores):
    with pytest.raises(ValueError, match="external_score"):
        select_action(scores, ("fold", "check_call"))


def test_scores_need_not_be_probabilities_and_ties_follow_declared_menu():
    assert select_action({"a": 1000, "b": Decimal("1000")}, ("b", "a")) == "b"
    assert select_action({"a": 1e308, "b": 1e308}, ("a", "b")) == "a"
    assert select_action({"a": Decimal("1e-1000"), "b": 0}, ("b", "a")) == "a"


def test_validation_is_not_inference_cache_preserves_first_latency_and_menu_order():
    calls = []

    def scorer(request):
        calls.append(deepcopy(request))
        # Equal scores intentionally exercise frozen original menu ordering.
        return {row["id"]: 5 for row in request["options"]}

    obs = observation()
    candidate = policy(scorer=scorer)
    assert candidate.inspect_lookup(obs)["status"] == "INPUT_READY"
    assert candidate.inspect_decision(obs) is None
    assert not calls
    expected = obs["legal_actions"][0]["id"]
    assert candidate.for_game("a" * 64)(obs) == expected
    first = candidate.inspect_decision(obs)
    assert first["cache_hits"] == 0 and first["last_cache_lookup_ms"] is None
    assert first["first_inference_latency_ms"] >= 0
    assert first["first_decision_latency_ms"] >= first["first_inference_latency_ms"]
    assert candidate.for_game("b" * 64)(obs) == expected
    repeated = candidate.inspect_decision(obs)
    assert repeated["cache_hits"] == 1 and repeated["last_cache_lookup_ms"] >= 0
    assert repeated["first_inference_latency_ms"] == first["first_inference_latency_ms"]
    assert len(calls) == 1
    changed = deepcopy(obs)
    changed["pot"] = str(Decimal(obs["pot"]) + Decimal("0.01"))
    assert candidate(changed) == expected
    assert len(calls) == 2
    reordered = deepcopy(obs)
    reordered["legal_actions"].reverse()
    assert candidate(reordered) == reordered["legal_actions"][0]["id"]
    assert len(calls) == 3
    identity = candidate.identity
    identity["model_revision"] = "different"
    assert candidate.identity["model_revision"] != "different"


def test_detached_scorer_request_cannot_mutate_source_or_selected_legal_ids():
    obs = observation()
    original = deepcopy(obs)

    def scorer(request):
        scores = synthetic_check_call_scores(request)
        request["state"]["stacks"].clear()
        request["options"][0]["id"] = "made-up-action"
        return scores

    candidate = policy(scorer=scorer)
    assert candidate(obs) == "check_call"
    assert obs == original
    receipt = candidate.inspect_decision(obs)
    receipt["action"] = "made-up-action"
    assert candidate(obs) == "check_call"


def test_scorer_errors_never_become_fallback_actions_or_cache_entries():
    calls = []

    def broken(request):
        calls.append(request)
        raise TimeoutError("external_model_deadline")

    candidate = policy(scorer=broken)
    obs = observation()
    for _ in range(2):
        with pytest.raises(TimeoutError, match="deadline"):
            candidate(obs)
        assert candidate.inspect_decision(obs) is None
    assert len(calls) == 2


def test_complete_context_count_is_checked_without_truncation_or_inference():
    obs = observation()
    expected = policy().prepare_request(obs)
    seen = []

    def count(request):
        seen.append(request)
        assert request == expected
        return 1540

    candidate = policy(context_token_limit=1536, token_counter=count,
                       scorer=lambda req: pytest.fail("must not infer"))
    diagnostic = candidate.inspect_lookup(obs)
    assert diagnostic["reason"] == "external_policy_context_overflow"
    with pytest.raises(ValueError, match="context_overflow"):
        candidate(obs)
    assert len(seen) == 2
    assert policy(context_token_limit=1540, token_counter=count)(obs) == "check_call"


@pytest.mark.parametrize("count", [-1, 1.5, True, None])
def test_invalid_token_count_fails_closed(count):
    candidate = policy(context_token_limit=1536, token_counter=lambda req: count)
    with pytest.raises(ValueError, match="context_token_count"):
        candidate(observation())


@pytest.mark.parametrize("kwargs", [
    {"context_token_limit": 100},
    {"context_token_limit": 0, "token_counter": len},
    {"context_token_limit": True, "token_counter": len},
    {"token_counter": len}, {"request_format": "unversioned"},
])
def test_constructor_refuses_incomplete_contract(kwargs):
    with pytest.raises(ValueError):
        policy(**kwargs)


@pytest.mark.parametrize("salt", [None, 1, True, "a" * 63, "a" * 65,
                                  "A" * 64, "x" * 64])
def test_evaluation_salt_is_strict_lowercase_hex64(salt):
    with pytest.raises(ValueError, match="independent_policy_salt_required"):
        policy().for_game(salt)
