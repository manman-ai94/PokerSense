import json

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_arena_evaluation import (  # noqa: E402
    check_call_policy, check_fold_policy, evaluate_paired, min_raise_policy,
    pot_raise_policy,
)
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2  # noqa: E402


def rules(n=6):
    return AARuleProfileV2.from_dict(dict(
        schema_version=2, table_size=n, small_blind="1", big_blind="2",
        ante="0", ante_mode="none", straddle_mode="none", straddle_amount="0",
        rake_percent="0.03", rake_cap_bb="2", rake_application="all_pots",
        rake_rounding="exact", rake_distribution="proportional_all_pots",
        minimum_chip="1", verification_status="simulation", source="synthetic"))


@pytest.mark.parametrize("count", [6, 7, 8])
def test_identity_comparison_rotates_all_seats_and_clusters_whole_deals(count):
    kwargs = dict(seeds=[3, 8], bootstrap_samples=100)
    report = evaluate_paired(rules(count), check_call_policy, check_call_policy,
                             {"passive": check_call_policy}, **kwargs)
    assert report["status"] == "COMPLETE"
    assert report["expected_pairs"] == 2 * count
    assert report["complete_pairs"] == 2 * count
    assert report["promotion"] == "NOT_ASSESSED"
    assert report["strategy_eligible"] is False
    assert {r["hero"] for r in report["rows"]} == set(range(count))
    assert {r["table_size"] for r in report["rows"]} == {count}
    group = report["groups"][0]
    assert group["complete_clusters"] == 2  # NOT 2*count independent samples
    assert group["delta_net_bb100"] == 0
    assert group["ci95_delta_net_bb100"] == [0, 0]
    assert report == evaluate_paired(rules(count), check_call_policy, check_call_policy,
                                     {"passive": check_call_policy}, **kwargs)
    json.dumps(report, allow_nan=False)


def test_blocked_candidate_keeps_whole_denominator_and_no_partial_ev():
    def invalid_policy(_):
        return "raise_to:999999"
    result = evaluate_paired(rules(), invalid_policy, check_call_policy,
                             {"passive": check_call_policy}, seeds=[2, 3],
                             bootstrap_samples=100)
    assert result["status"] == "BLOCKED"
    assert result["expected_pairs"] == result["blocked_pairs"] == 12
    assert len(result["rows"]) == 12
    assert all(row["delta_bb"] is None for row in result["rows"])
    assert all(row["baseline"]["status"] == "COMPLETE" for row in result["rows"])
    group = result["groups"][0]
    assert group["delta_net_bb100"] is None
    assert group["ci95_delta_net_bb100"] is None
    assert group["evidence_status"] == "INSUFFICIENT_DATA"


def test_selective_failure_cannot_be_ignored_and_other_groups_remain_visible():
    def fails_for_one_hero(obs):
        if obs["observing_seat"] == 2:
            raise RuntimeError("deliberate refusal")
        return "check_call"
    report = evaluate_paired(rules(), fails_for_one_hero, check_call_policy,
                             {"passive": check_call_policy}, seeds=[3, 4],
                             bootstrap_samples=100)
    assert report["expected_pairs"] == 12
    assert report["blocked_pairs"] == 2
    assert report["complete_pairs"] == 10
    assert report["groups"][0]["delta_net_bb100"] is None
    assert report["groups"][0]["complete_clusters"] == 0


def test_action_budget_failure_keeps_both_branches():
    report = evaluate_paired(rules(), min_raise_policy, check_call_policy,
                             {"passive": check_call_policy}, seeds=[9],
                             bootstrap_samples=100, max_actions=1)
    assert report["blocked_pairs"] == 6
    assert all(row["candidate"]["error"] == "max_actions_exceeded"
               and row["baseline"]["error"] == "max_actions_exceeded"
               for row in report["rows"])


def test_one_deal_cannot_generate_confidence_interval():
    report = evaluate_paired(rules(), check_call_policy, check_call_policy,
                             {"passive": check_call_policy}, seeds=[8],
                             bootstrap_samples=100)
    assert report["groups"][0]["ci95_delta_net_bb100"] is None
    assert report["groups"][0]["evidence_status"] == "INSUFFICIENT_DATA"


def test_nontrivial_policies_and_protocol_identity():
    kwargs = dict(seeds=[1, 2], bootstrap_samples=100)
    report = evaluate_paired(rules(), check_fold_policy, check_call_policy,
                             {"aggressive": pot_raise_policy,
                              "passive": check_call_policy}, **kwargs)
    assert report["status"] == "COMPLETE"
    assert report["expected_pairs"] == 24
    assert len(report["groups"]) == 2
    changed = evaluate_paired(rules(), check_fold_policy, check_call_policy,
                              {"aggressive": pot_raise_policy,
                               "passive": check_call_policy},
                              candidate_id="new-version", **kwargs)
    assert changed["protocol_sha256"] != report["protocol_sha256"]
    assert changed["rows"] == report["rows"]


def test_stateful_policy_is_not_silently_used_as_paired_reference():
    count = 0

    def unstable(_):
        nonlocal count
        count += 1
        return "check_call" if count % 2 else "fold"

    result = evaluate_paired(rules(), unstable, check_call_policy,
                             {"passive": check_call_policy}, seeds=[1],
                             bootstrap_samples=100)
    assert result["blocked_pairs"] == 6
    assert all(row["candidate"]["error"] == "policy_not_deterministic_for_observation"
               for row in result["rows"])


@pytest.mark.parametrize("seeds", [[], [1, 1], [1.0], [True]])
def test_bad_protocol_seeds_rejected(seeds):
    with pytest.raises(ValueError):
        evaluate_paired(rules(), check_call_policy, check_call_policy,
                        {"passive": check_call_policy}, seeds=seeds)


class SaltedMix:
    def __init__(self):
        self.salts = []

    def for_game(self, salt):
        self.salts.append(salt)
        fold = int(salt, 16) % 2 == 0

        def choose(observation):
            ids = {action["id"] for action in observation["legal_actions"]}
            return "fold" if fold and "fold" in ids else "check_call"

        return choose


def test_mixed_policy_salts_are_fresh_per_trial_and_replayed_for_paired_branches():
    from collections import Counter
    from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
    hero, opponent = SaltedMix(), SaltedMix()
    report = evaluate_paired(rules(), hero, hero, {"mixed": opponent},
                             seeds=[11, 22], bootstrap_samples=100, policy_seed=7719)
    assert report["status"] == "COMPLETE"
    assert report["groups"][0]["delta_net_bb100"] == 0
    assert report["groups"][0]["ci95_delta_net_bb100"] == [0, 0]
    assert all(row["candidate"]["trace_sha256"] == row["baseline"]["trace_sha256"]
               for row in report["rows"])
    assert set(Counter(hero.salts).values()) == {2}
    assert len(set(hero.salts)) == 12
    assert set(Counter(opponent.salts).values()) == {2}
    assert len(set(opponent.salts)) == 12 * 5
    assert not set(hero.salts) & set(opponent.salts)
    assert all(isinstance(salt, str) and len(salt) == 64 for salt in hero.salts)
    assert report["protocol"]["policy_seed"] == 7719
    # The *same* decision receives differing choices across separately bound
    # games, while re-reading one decision cannot advance RNG or resample.
    arena = AAFullHandArena(rules()).reset(9)
    observation = arena.observe(arena.actor)
    probe = SaltedMix()
    choices = set()
    for salt in set(hero.salts):
        bound = probe.for_game(salt)
        choice = bound(observation)
        assert bound(observation) == choice
        choices.add(choice)
    assert choices == {"fold", "check_call"}
    assert report == evaluate_paired(rules(), SaltedMix(), SaltedMix(),
                                     {"mixed": SaltedMix()}, seeds=[11, 22],
                                     bootstrap_samples=100, policy_seed=7719)


def test_bad_bound_policy_is_a_retained_game_failure():
    class BadFactory:
        def for_game(self, salt):
            return None
    report = evaluate_paired(rules(), BadFactory(), check_call_policy,
                             {"passive": check_call_policy}, seeds=[1],
                             bootstrap_samples=100)
    assert report["blocked_pairs"] == report["expected_pairs"] == 6
    assert all(row["candidate"]["error"] == "policy_for_game_must_return_callable"
               for row in report["rows"])
