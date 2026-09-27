"""Public-only strategic labels checked against actual full arena trajectories."""
from copy import deepcopy
from fractions import Fraction
import json

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_external_local_policy import (  # noqa: E402
    ExternalLocalResearchPolicy,
)
from poker_engine.strategy.aa_local_sanity import (  # noqa: E402
    CASE_KINDS, FEE_STRESS, SOURCE, build_sanity_arena, build_sanity_cases,
    sanity_deck,
)
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2  # noqa: E402


def fraction(value):
    return Fraction(value["numerator"], value["denominator"])


@pytest.fixture(scope="module")
def cases():
    return build_sanity_cases()


def test_exact_nine_cases_fixed_actions_and_reproducible_serialization(cases):
    assert len(cases) == 9
    assert len({case["id"] for case in cases}) == 9
    assert cases == build_sanity_cases()
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert [case["expected_action"] for case in cases] == [
        "check_call", "fold", "check_call"] * 3


@pytest.mark.parametrize("players", [6, 7, 8])
@pytest.mark.parametrize("kind", CASE_KINDS)
def test_real_four_streets_last_actor_and_two_terminal_branches(players, kind):
    arena = build_sanity_arena(players, kind)
    obs = arena.observe(arena.actor)
    assert arena.actor == players - 1 == arena.dealer_seat
    assert obs["all_in"] == list(range(players - 1))
    assert obs["folded"] == []
    assert obs["to_call"] == "194"
    assert obs["contributions"][str(arena.actor)] == "6"
    assert {row["street"] for row in obs["public_history"]} == {
        "preflop", "flop", "turn", "river"}
    assert [row["street"] for row in obs["board_history"]] == ["flop", "turn", "river"]
    assert [row["id"] for row in obs["legal_actions"]] == ["fold", "check_call"]
    for action in ("fold", "check_call"):
        branch = arena.clone().step(action)
        assert branch.terminal
        terminal = branch.terminal_result()
        assert sum(branch.terminal_returns().values()) == -fraction(terminal["rake"])
        assert set(branch.terminal_returns()) == set(range(players))


def test_closed_form_margins_and_each_actual_hero_branch(cases):
    for case in cases:
        n = case["observation"]["table_size"]
        oracle = case["oracle"]
        expected_delta = {"board_royal_no_rake": 6,
                          "board_royal_fee_stress": -94,
                          "private_royal": 200 * (n - 1) + 2}[case["kind"]]
        assert (fraction(oracle["incremental_returns_vs_fold"]["check_call"])
                == expected_delta)
        assert fraction(oracle["strict_margin"]) == abs(expected_delta)
        assert fraction(oracle["terminal_hero_returns"]["fold"]) == -6
        for action, terminal in case["branch_evidence"].items():
            assert (terminal["returns"][str(n - 1)]
                    == oracle["terminal_hero_returns"][action])
        assert oracle["hidden_information_used"] is False
        assert oracle["future_decisions"] == 0


@pytest.mark.parametrize("players", [6, 7, 8])
@pytest.mark.parametrize("kind", CASE_KINDS)
def test_hidden_permutations_preserve_observation_and_hero_returns(players, kind):
    original = build_sanity_arena(players, kind)
    deck = sanity_deck(players, kind)
    # Permute across seats AND substitute held cards from undealt positions.
    # Protected Hero/board slots are unchanged; the complete 52-card deck stays valid.
    hidden_slots = [*range(2 * (players - 1)), *range(2 * players + 8, 52)]
    cards = [deck[i] for i in hidden_slots]
    for shift in (1, 7, 17):
        changed = list(deck)
        rotated = cards[shift:] + cards[:shift]
        for slot, card in zip(hidden_slots, rotated):
            changed[slot] = card
        altered = build_sanity_arena(players, kind, deck=changed)
        hero = players - 1
        assert altered.observe(hero) == original.observe(hero)
        for action in ("fold", "check_call"):
            assert (altered.clone().step(action).terminal_returns()[hero]
                    == original.clone().step(action).terminal_returns()[hero])


def test_no_oracle_leak_in_real_external_adapter_and_explicit_simulation_flags(cases):
    for case in cases:
        seen = []

        def scorer(request):
            seen.append(deepcopy(request))
            return {"fold": 1.0, "check_call": 1.0}

        obs = case["observation"]
        policy = ExternalLocalResearchPolicy(
            AARuleProfileV2.from_dict(obs["rules"]), scorer,
            model_id="test-input-isolation", model_revision="fixed-v1")
        policy(obs)
        encoded = json.dumps(seen, sort_keys=True)
        for forbidden in ("expected_action", "terminal_hero_returns", "oracle",
                          "branch_evidence", "BOARD_ROYAL_TIES", "UNBEATABLE",
                          "terminal_returns", "strict_margin"):
            assert forbidden not in encoded
        assert case["source_kind"] == SOURCE
        assert case["simulation_only"] is True
        assert case["strategy_eligible"] is False
        assert case["advice_emitted"] is False
        assert case["empirical_strength"] == "NOT_ASSESSED"
        assert obs["rules"]["verification_status"] == "simulation"
        assert "aa_rules_not_live_verified" in policy._rules.live_strategy_blockers
        if case["kind"] == "board_royal_fee_stress":
            assert case["scope"] == FEE_STRESS
            assert FEE_STRESS in obs["rules"]["source"]
            assert obs["rules"]["rake_percent"] == "0.5"


@pytest.mark.parametrize("players,kind", [
    (5, CASE_KINDS[0]), (True, CASE_KINDS[0]), (9, CASE_KINDS[0]), (6, "unknown")])
def test_invalid_case_spec_refused(players, kind):
    with pytest.raises(ValueError):
        build_sanity_arena(players, kind)


def test_changed_hero_cards_cannot_keep_the_declared_oracle():
    deck = sanity_deck(6, "private_royal")
    deck[10], deck[30] = deck[30], deck[10]
    with pytest.raises(ValueError, match="changed_public_or_hero"):
        build_sanity_arena(6, "private_royal", deck=deck)
