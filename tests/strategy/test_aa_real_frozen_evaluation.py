"""The actual artifact-loader/binder/evaluator path, not a stand-in policy."""
from copy import deepcopy
import json

import pytest

from poker_engine.strategy.aa_arena_evaluation import check_call_policy, evaluate_paired
from poker_engine.strategy.aa_frozen_policy import (
    FrozenResearchPolicy, canonical_hash,
)
from tools.diagnose_aa_frozen_evaluation import (
    CONTROL_SEEDS, DEFAULT_RULES, diagnose, known_control, rules_for,
)


def load(document):
    data = deepcopy(document)
    data.pop("sha256")
    data["sha256"] = canonical_hash(data)
    return FrozenResearchPolicy(json.loads(json.dumps(data)))


@pytest.mark.parametrize("n", (6, 7, 8))
def test_real_frozen_asset_completes_all_four_streets_and_matches_direct_policy(n):
    rules = rules_for(DEFAULT_RULES, n)
    policy = load(known_control(rules))
    report = evaluate_paired(rules, policy, check_call_policy,
                             {"passive": check_call_policy}, seeds=CONTROL_SEEDS,
                             bootstrap_samples=100, record_diagnostics=True)
    assert report["complete_pairs"] == report["expected_pairs"] == n * 2
    assert report["candidate_diagnostics"]["first_hero_hit"] == n * 2
    for street in report["candidate_diagnostics"]["streets"].values():
        assert street == {"observed": n * 2, "hit": n * 2, "miss": 0, "other": 0}
    for row in report["rows"]:
        candidate, baseline = row["candidate"], row["baseline"]
        assert candidate["binding_success"] and candidate["first_failure"] is None
        assert len(candidate["hero_opportunities"]) == 4  # not double counted
        for key in ("trace_sha256", "terminal", "return_chips"):
            assert candidate[key] == baseline[key]


@pytest.mark.parametrize("salt", [0, True, None, "a" * 63, "a" * 65,
                                  "z" * 64, "A" * 64])
def test_real_policy_rejects_malformed_independent_salt(salt):
    with pytest.raises(ValueError, match="independent_policy_salt_required"):
        load(known_control(rules_for(DEFAULT_RULES, 6))).for_game(salt)


@pytest.mark.parametrize("change,category", [
    ("empty", "UNKNOWN_INFORMATION_SET"), ("rules", "SCOPE_MISMATCH"),
    ("depth", "SCOPE_MISMATCH"), ("menu", "INVALID_MENU"),
])
def test_real_asset_failure_diagnoses_reason_and_keeps_denominator(change, category):
    rules = rules_for(DEFAULT_RULES, 6)
    doc = known_control(rules)
    if change == "empty":
        doc["policy"] = {}
    elif change == "rules":
        doc["rules_fingerprint"] = "b" * 64
    elif change == "depth":
        doc["stack_depth_bb"] = "200"
    else:
        doc["policy"] = {key: {"bogus": 1.0} for key in doc["policy"]}
    report = evaluate_paired(rules, load(doc), check_call_policy,
                             {"passive": check_call_policy}, seeds=CONTROL_SEEDS,
                             bootstrap_samples=100, record_diagnostics=True)
    assert report["expected_pairs"] == report["blocked_pairs"] == 12
    assert report["groups"][0]["delta_net_bb100"] is None
    for row in report["rows"]:
        branch = row["candidate"]
        assert branch["binding_success"]
        assert branch["first_failure"]["category"] == category
        assert branch["first_failure"]["actor_is_hero"]
        assert len(branch["hero_opportunities"]) == 1
        assert branch["hero_opportunities"][0]["lookup_status"] == category
    assert report["candidate_diagnostics"]["streets"]["flop"]["observed"] == 0


def test_opponent_binding_error_is_not_mislabeled_as_hero_coverage():
    class InvalidOpponent:
        def for_game(self, salt):
            raise ValueError("independent_policy_salt_required")
    rules = rules_for(DEFAULT_RULES, 6)
    report = evaluate_paired(rules, load(known_control(rules)), check_call_policy,
                             {"bad": InvalidOpponent()}, seeds=CONTROL_SEEDS,
                             bootstrap_samples=100, record_diagnostics=True)
    for row in report["rows"]:
        branch = row["candidate"]
        assert not branch["binding_success"] and not branch["hero_opportunities"]
        assert branch["first_failure"]["phase"] == "BIND"
        assert branch["first_failure"]["actor_is_hero"] is False


def test_budget_and_illegal_attempt_index_are_unambiguous():
    rules = rules_for(DEFAULT_RULES, 6)
    policy = load(known_control(rules))
    report = evaluate_paired(rules, policy, check_call_policy,
                             {"passive": check_call_policy}, seeds=CONTROL_SEEDS,
                             bootstrap_samples=100, max_actions=1,
                             record_diagnostics=True)
    for row in report["rows"]:
        failure = row["candidate"]["first_failure"]
        assert failure["category"] == "BUDGET_EXHAUSTED"
        assert failure["street"] == "preflop" and failure["action_index"] == 1
    report = evaluate_paired(rules, lambda obs: "raise_to:999999", check_call_policy,
                             {"passive": check_call_policy}, seeds=CONTROL_SEEDS,
                             bootstrap_samples=100, record_diagnostics=True)
    for row in report["rows"]:
        branch = row["candidate"]
        assert branch["first_failure"]["category"] == "ILLEGAL_ACTION"
        assert branch["first_failure"]["action_index"] == (
            branch["hero_opportunities"][0]["action_index"])


def test_diagnostic_output_cannot_change_original_dataset(tmp_path):
    with pytest.raises(ValueError, match="original_source"):
        diagnose(tmp_path, tmp_path / "new-report")
    assert list(tmp_path.iterdir()) == []
