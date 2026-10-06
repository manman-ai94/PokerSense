from copy import deepcopy
from decimal import Decimal, localcontext
from itertools import permutations

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena  # noqa: E402
from poker_engine.strategy.aa_frozen_policy import information_key  # noqa: E402
from poker_engine.strategy.aa_policy_encoding_v2 import (  # noqa: E402
    ENCODER_VERSION_V2, encode_decision_v2, exact_money, information_key_v2,
)
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2  # noqa: E402


def rules(n=6):
    return AARuleProfileV2.from_dict({
        "schema_version": 2, "table_size": n, "small_blind": "1", "big_blind": "2",
        "ante": "0", "ante_mode": "none", "straddle_mode": "none",
        "straddle_amount": "0", "rake_percent": "0", "rake_cap_bb": "0",
        "rake_application": "all_pots", "rake_rounding": "exact",
        "rake_distribution": "proportional_all_pots", "minimum_chip": "1",
        "verification_status": "simulation", "source": "synthetic-v2-unit-test",
    })


def observation(n=6):
    arena = AAFullHandArena(rules(n)).reset(17)
    return arena.observe(arena.actor)


def with_cards(obs, hole, board):
    result = deepcopy(obs)
    result["own_hole"] = hole.split()
    result["board"] = board.split()
    count = len(result["board"])
    result["street"] = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[count]
    result["board_history"] = []
    if count >= 3:
        result["board_history"].append({
            "street": "flop", "cards": result["board"][:3]})
    if count >= 4:
        result["board_history"].append({
            "street": "turn", "cards": result["board"][3:4]})
    if count == 5:
        result["board_history"].append({
            "street": "river", "cards": result["board"][4:]})
    return result


@pytest.mark.parametrize("n", [6, 7, 8])
def test_actual_arena_every_street_has_explicit_history_and_public_betting(n):
    arena = AAFullHandArena(rules(n)).reset(91)
    streets = set()
    while not arena.terminal:
        obs = arena.observe(arena.actor)
        encoded = encode_decision_v2(obs)
        assert encoded["encoder"] == ENCODER_VERSION_V2
        assert len(encoded["exact_key"]) == len(encoded["abstract_key"]) == 64
        assert encoded["features"]["betting"]["pending_actors"][0] == arena.actor
        assert [card for row in obs["board_history"] for card in row["cards"]] == (
            obs["board"])
        assert len(obs["board_history"]) == ("preflop", "flop", "turn", "river").index(
            arena.street)
        streets.add(arena.street)
        arena.step("check_call")
    assert streets == {"preflop", "flop", "turn", "river"}


def test_prior_encoder_false_flush_draw_equivalence_is_removed():
    left = with_cards(observation(), "As Kd", "2s 7s Ts")
    right = with_cards(left, "Ah Kd", "2s 7s Ts")
    assert information_key(left) == information_key(right)  # retained V1 counterexample
    a, b = encode_decision_v2(left), encode_decision_v2(right)
    assert a["exact_key"] != b["exact_key"]
    assert a["abstract_key"] != b["abstract_key"]
    assert any(row["flush_draw_uses_private"] and
               row["holds_highest_rank_absent_from_board"]
               for row in a["features"]["cards"]["suit_relations"])
    assert not any(row["one_card_flush_draw"]
                   for row in b["features"]["cards"]["suit_relations"])


@pytest.mark.parametrize("board", ["", "2s 7s Ts", "2s 7s Ts Jh", "2s 7s Ts Jh 6c"])
def test_all_24_global_suit_permutations_keep_both_identities(board):
    obs = with_cards(observation(), "As Kd", board)
    reference = encode_decision_v2(obs)
    for permutation in permutations("cdhs"):
        mapping = dict(zip("cdhs", permutation))

        def mapped(card):
            return card[0] + mapping[card[1]]

        changed = deepcopy(obs)
        changed["own_hole"] = [mapped(card) for card in obs["own_hole"]]
        changed["board"] = [mapped(card) for card in obs["board"]]
        changed["board_history"] = [
            {"street": row["street"], "cards": [mapped(card) for card in row["cards"]]}
            for row in obs["board_history"]
        ]
        assert encode_decision_v2(changed) == reference


def test_chronological_board_paths_not_reconstructed_from_final_set():
    left = with_cards(observation(), "As Kd", "2s 7s Ts Jh 6c")
    right = with_cards(left, "As Kd", "2s 7s Jh Ts 6c")
    assert set(left["board"]) == set(right["board"])
    assert (encode_decision_v2(left)["exact_key"]
            != encode_decision_v2(right)["exact_key"])
    assert information_key_v2(left) != information_key_v2(right)
    missing = deepcopy(left)
    missing.pop("board_history")
    with pytest.raises(ValueError, match="observation_field"):
        information_key_v2(missing)
    missing["board_history"] = []
    with pytest.raises(ValueError, match="incomplete_board_history"):
        information_key_v2(missing)


def test_explicit_history_cannot_disagree_or_include_future_card():
    obs = with_cards(observation(), "As Kd", "2s 7s Ts Jh")
    obs["board_history"][1]["cards"] = ["Qh"]
    with pytest.raises(ValueError, match="current_board_mismatch"):
        information_key_v2(obs)
    obs = with_cards(observation(), "As Kd", "2s 7s Ts")
    obs["board_history"].append({"street": "turn", "cards": ["Qh"]})
    with pytest.raises(ValueError, match="incomplete_board_history"):
        information_key_v2(obs)


def test_hole_and_flop_order_are_unordered_but_turn_river_are_ordered():
    obs = with_cards(observation(), "As Kd", "2s 7s Ts Jh 6c")
    swapped = with_cards(obs, "Kd As", "Ts 2s 7s Jh 6c")
    assert encode_decision_v2(obs) == encode_decision_v2(swapped)
    swapped = with_cards(obs, "As Kd", "2s 7s Ts 6c Jh")
    assert (encode_decision_v2(obs)["exact_key"]
            != encode_decision_v2(swapped)["exact_key"])


def test_money_spelling_is_exact_even_beyond_decimal_context_precision():
    large = "123456789012345678901234567890.12345678900"
    with localcontext() as context:
        context.prec = 4
        assert exact_money(large) == large[:-2]
    assert exact_money(Decimal("2.000")) == "2"
    assert exact_money("-0.000") == "0"
    obs = observation()
    equal = deepcopy(obs)
    for field in ("pot", "big_blind", "to_call"):
        equal[field] = obs[field] + ".000"
    for field in ("stacks", "bets", "starting_stacks", "contributions"):
        equal[field] = {seat: value + ".000" for seat, value in obs[field].items()}
    assert encode_decision_v2(obs) == encode_decision_v2(equal)


@pytest.mark.parametrize("value", [True, 1.0, float("inf"), "NaN", "Infinity", "-1"])
def test_inexact_or_invalid_money_is_refused(value):
    with pytest.raises(ValueError, match="exact_money"):
        exact_money(value)


@pytest.mark.parametrize("field", [
    "to_call", "pot", "stacks", "bets", "contributions", "starting_stacks",
])
def test_exact_price_stack_and_contributions_never_rounded(field):
    obs = observation()
    changed = deepcopy(obs)
    if isinstance(changed[field], dict):
        seat = str(obs["actor"])
        changed[field][seat] = str(
            Decimal(changed[field][seat]) + Decimal("0.00000001"))
    else:
        changed[field] = str(Decimal(changed[field]) + Decimal("0.00000001"))
    a, b = encode_decision_v2(obs), encode_decision_v2(changed)
    assert a["exact_key"] != b["exact_key"]
    assert a["abstract_key"] != b["abstract_key"]


@pytest.mark.parametrize("field,value", [
    ("last_full_raise_increment", "9"), ("acted_since_full_raise", [3]),
    ("pending_actors", [2, 4, 3, 5, 0, 1]),
    ("consecutive_short_raise_increments", ["1", "1"]),
])
def test_public_reopening_and_action_order_are_bound(field, value):
    obs = observation()
    changed = deepcopy(obs)
    changed["betting"][field] = value
    assert (encode_decision_v2(obs)["exact_key"]
            != encode_decision_v2(changed)["exact_key"])


def test_physical_seats_are_retained_and_not_claimed_equivalent():
    obs = observation()
    changed = deepcopy(obs)
    changed["dealer_seat"] = 4
    assert information_key_v2(obs) != information_key_v2(changed)
    assert "Physical seats" in encode_decision_v2(obs)["abstraction_disclosure"]


def test_legitimate_lossy_collision_is_visible_in_exact_identity():
    left = with_cards(observation(), "Kh 9h", "2c 5d Ts")
    right = with_cards(left, "Kh 8h", "2c 5d Ts")
    a, b = encode_decision_v2(left), encode_decision_v2(right)
    assert a["exact_key"] != b["exact_key"]
    assert a["abstract_key"] == b["abstract_key"]
    assert "lossy" in a["abstraction_disclosure"]
    assert "not proven strategic equivalence" in a["abstraction_disclosure"]


def test_board_only_hand_and_private_improvement_are_distinguished():
    board_only = with_cards(observation(), "Ac Kd", "2s 3s 4s 5s 6s")
    improves = with_cards(board_only, "7s Kd", "2s 3s 4s 5s 6s")
    a = encode_decision_v2(board_only)["features"]["cards"]
    b = encode_decision_v2(improves)["features"]["cards"]
    assert a["made_category"] == b["made_category"] == a["board_only_category"] == 8
    assert a["private_improves_board_five"] is False
    assert b["private_improves_board_five"] is True


def test_geometric_straight_draw_retains_private_participation():
    obs = with_cards(observation(), "9h 8d", "6c 7s Kc")
    rows = encode_decision_v2(obs)["features"]["cards"]["one_card_straight_completions"]
    assert {row["missing_rank"] for row in rows} == {5, 10}
    assert all(row["private_required_ranks"] == [8, 9] for row in rows)


@pytest.mark.parametrize("field", [
    "seed", "deck", "opponent_hole", "hole_cards", "future_board", "terminal_returns",
    "rng_state",
])
def test_hidden_and_future_information_is_rejected_recursively(field):
    obs = observation()
    obs["provenance"] = {"nested": {field: "not-admitted"}}
    with pytest.raises(ValueError, match="private_or_future"):
        information_key_v2(obs)


def test_source_references_do_not_enter_model_or_exact_identity():
    obs = observation()
    changed = deepcopy(obs)
    changed["source_ref"] = "another-local-source"
    changed["rules"]["source"] = "metadata-only-not-a-feature"
    assert encode_decision_v2(obs) == encode_decision_v2(changed)


def test_actual_future_or_opponent_hole_changes_cannot_change_decision_view():
    arena = AAFullHandArena(rules()).reset(99)
    clone = arena.clone()
    other_index = next(i for i, seat in enumerate(clone._seats) if seat != clone.actor)
    clone._holes[other_index] = tuple(reversed(clone._holes[other_index]))
    clone._deck[clone._deck_cursor:] = reversed(clone._deck[clone._deck_cursor:])
    assert encode_decision_v2(arena.observe(arena.actor)) == encode_decision_v2(
        clone.observe(clone.actor))


def test_observation_board_history_does_not_alias_arena():
    arena = AAFullHandArena(rules()).reset(8)
    while arena.street == "preflop":
        arena.step("check_call")
    obs = arena.observe(arena.actor)
    obs["board_history"][0]["cards"].clear()
    assert len(arena.observe(arena.actor)["board_history"][0]["cards"]) == 3


def test_actual_short_allin_exposes_non_reopening_not_hidden_opponent_cards():
    arena = AAFullHandArena(rules(), {0: 200, 1: 200, 2: 200, 3: 15,
                                      4: 200, 5: 200}).reset(1)
    arena.step("raise_to:10")
    arena.step("raise_to:15")
    for _ in range(4):
        arena.step("check_call")
    obs = arena.observe(arena.actor)
    encoded = encode_decision_v2(obs)
    view = encoded["exact_view"]
    assert arena.actor == 2
    assert view["all_in"] == [3]
    assert view["contributions"]["3"] == "15"
    assert view["betting"]["can_raise"] is False
    assert view["betting"]["last_full_raise_increment"] == "8"
    assert view["betting"]["consecutive_short_raise_increments"] == ["5"]
    assert {row["kind"] for row in view["legal_actions"]} == {"fold", "check_call"}
    changed = deepcopy(obs)
    changed["all_in"] = []
    assert encode_decision_v2(changed)["exact_key"] != encoded["exact_key"]


def test_exact_legal_total_raise_and_minimum_bound_change_both_keys():
    obs = observation()
    changed = deepcopy(obs)
    row = next(row for row in changed["legal_actions"] if row["kind"] == "raise_to")
    row["raise_to"], row["id"] = "9", "raise_to:9"
    assert (encode_decision_v2(changed)["exact_key"]
            != encode_decision_v2(obs)["exact_key"])
    assert information_key_v2(changed) != information_key_v2(obs)
    changed = deepcopy(obs)
    changed["betting"]["min_raise_to"] = "9"
    assert information_key_v2(changed) != information_key_v2(obs)


def test_same_rank_swapped_suits_across_streets_keep_public_path_distinct():
    # Same final board and rank-per-street path; each street's flush texture differs.
    left = with_cards(observation(), "As Kd", "2s 2h Ts 7s 7h")
    right = with_cards(left, "As Kd", "2s 2h Ts 7h 7s")
    assert information_key_v2(left) != information_key_v2(right)


def test_out_of_order_public_streets_are_not_admitted():
    obs = with_cards(observation(), "As Kd", "2s 7s Ts Jh")
    obs["public_history"] = [
        {"index": i, "street": street, "actor": 2, "id": "check_call",
         "kind": "check_call", "raise_to": None, "paid": "0"}
        for i, street in enumerate(("turn", "flop"))
    ]
    with pytest.raises(ValueError, match="public_history_order"):
        information_key_v2(obs)
