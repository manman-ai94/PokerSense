from copy import deepcopy

from poker_engine.strategy.aa_frozen_policy_v2 import (
    FrozenResearchPolicyV2, make_policy_v2,
)
from poker_engine.strategy.aa_policy_encoding_v2 import information_key_v2
from tools.aa_full_hand_lab import DEFAULT_RULES, rules_for
from tools.aa_policy_street_challenges import (
    CHALLENGE_SPEC, DEVELOPMENT_SPEC, challenge_observations, evaluate_queries,
    hidden_input_rejection_probe,
)


def fixture_policy(rules):
    table = {}
    for kind in DEVELOPMENT_SPEC["kinds"]:
        if kind == "side_pot_scope":
            continue
        for seed in DEVELOPMENT_SPEC["seeds"]:
            for obs in challenge_observations(rules, kind, seed):
                table[information_key_v2(obs)] = {
                    row["id"]: float(row["id"] == "check_call")
                    for row in obs["legal_actions"]}
    document = make_policy_v2(
        rules_fingerprint=rules.fingerprint, table_size=rules.table_size,
        stack_depth_bb=100, policy=table,
        training={"kind": "DECLARED_QUERY_CONTROL_NOT_LEARNED"},
    )
    return FrozenResearchPolicyV2(document)


def test_actual_frozen_query_positive_control_and_explicit_sidepot_scope():
    rules = rules_for(DEFAULT_RULES, 6)
    policy = fixture_policy(rules)
    report = evaluate_queries(rules, policy, spec=DEVELOPMENT_SPEC)
    assert report["status"] == "COMPLETE_QUERY_DIAGNOSTIC"
    assert report["development_only"]
    assert report["all_streets_have_positive"]
    assert report["side_pot_scope_failures"] == 0
    assert sum(row["illegal"] for row in report["by_street"].values()) == 0
    assert all(row["action"] is None for row in report["rows"]
               if not row["scope_expected"])
    assert report["ev"] is None and not report["strategy_eligible"]
    assert hidden_input_rejection_probe(rules, policy)["passed"]


def test_query_prefixes_include_real_off_grid_and_allin_history():
    rules = rules_for(DEFAULT_RULES, 8)
    ordinary = list(challenge_observations(rules, "check_call_path", 3100000))
    off_grid = list(challenge_observations(rules, "off_grid_prefix", 3100000))
    first_actions = {row["id"] for row in off_grid[0]["legal_actions"]}
    assert off_grid[1]["public_history"][0]["id"] not in first_actions
    assert {obs["street"] for obs in ordinary} == {
        "preflop", "flop", "turn", "river"}
    all_in = list(challenge_observations(rules, "all_in_price", 3100000))
    assert all_in[1]["all_in"]
    assert all_in[1]["to_call"] != "0"


def test_empty_actual_policy_keeps_query_misses_and_unseen_suffix_unknown():
    rules = rules_for(DEFAULT_RULES, 6)
    document = make_policy_v2(
        rules_fingerprint=rules.fingerprint, table_size=6,
        stack_depth_bb=100, policy={}, training={"kind": "empty_probe"},
    )
    policy = FrozenResearchPolicyV2(document)
    report = evaluate_queries(rules, policy, spec=DEVELOPMENT_SPEC)
    assert not report["all_streets_have_positive"]
    assert all(row["hit"] == 0 for row in report["by_street"].values())
    assert all(row["opportunities"] > 0 for row in report["by_street"].values())
    short = evaluate_queries(rules, policy, spec=DEVELOPMENT_SPEC, deadline=0)
    assert short["status"] == "UNREPORTED_SUFFIX_BUDGET"
    assert short["remaining_opportunities"] is None
    assert CHALLENGE_SPEC == deepcopy(CHALLENGE_SPEC)
