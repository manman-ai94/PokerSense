from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
import json

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_full_hand_arena import (  # noqa: E402
    AAFullHandArena, ArenaAction, SETTLEMENT_MODEL,
)
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2  # noqa: E402


def rules(n=6, **changes):
    fields = dict(schema_version=2, table_size=n, small_blind="1", big_blind="2",
                  ante="0", ante_mode="none", straddle_mode="none",
                  straddle_amount="0", rake_percent="0", rake_cap_bb="0",
                  rake_application="all_pots", rake_rounding="exact",
                  rake_distribution="proportional_all_pots", minimum_chip="1",
                  verification_status="simulation", source="synthetic-unit-test")
    fields.update(changes)
    return AARuleProfileV2.from_dict(fields)


def deck_with(prefix):
    from pokerkit import Deck
    prefix = prefix.split()
    return prefix + [repr(card) for card in Deck.STANDARD if repr(card) not in prefix]


def finish(arena):
    while not arena.terminal:
        arena.step("check_call")
    return arena.terminal_returns()


@pytest.mark.parametrize("count", [6, 7, 8])
def test_full_four_streets_seed_and_clone(count):
    arena = AAFullHandArena(rules(count)).reset(73)
    clone = arena.clone()
    streets = set()
    while not arena.terminal:
        streets.add(arena.street)
        assert arena.observe(arena.actor) == clone.observe(clone.actor)
        arena.step("check_call")
        clone.step("check_call")
    assert streets == {"preflop", "flop", "turn", "river"}
    assert arena.terminal_result() == clone.terminal_result()
    assert sum(arena.terminal_returns().values()) == 0
    assert finish(AAFullHandArena(rules(count)).reset(73)) == arena.terminal_returns()


def test_information_isolation_and_no_mutable_aliases():
    arena = AAFullHandArena(rules()).reset(14)
    obs = arena.observe(arena.actor)
    assert len(obs["own_hole"]) == 2 and obs["board"] == []
    assert not ({"seed", "deck", "hole_cards", "terminal_returns"} & set(obs))
    assert obs["settlement_model"] == SETTLEMENT_MODEL
    assert obs["strategy_eligible"] is False
    assert obs["simulation_only"] is True
    for seat in arena.occupied_seats:
        assert len(arena.observe(seat)["own_hole"]) == 2
    obs["public_history"].append({"injected": True})
    obs["stacks"]["0"] = "9000"
    obs["legal_actions"].clear()
    assert arena.observe(arena.actor)["public_history"] == []
    assert arena.observe(arena.actor)["stacks"]["0"] != "9000"
    json.dumps(arena.observe(arena.actor))
    with pytest.raises(ValueError, match="before settlement"):
        arena.terminal_returns()


def test_changing_opponent_holes_or_future_keeps_observation_identical():
    first = deck_with("Ac Ad Kc Kd Qc Qd Jc Jd Tc Td 9c 9d")
    second = list(first)
    second[0], second[12] = second[12], second[0]
    second[19], second[20] = second[20], second[19]
    left = AAFullHandArena(rules()).reset(1, deck=first)
    right = AAFullHandArena(rules()).reset(1, deck=second)
    assert left.actor == right.actor == 2
    assert left.observe(2) == right.observe(2)


def test_illegal_offgrid_misaligned_action_cannot_mutate():
    arena = AAFullHandArena(rules()).reset(1)
    original = arena.observe(arena.actor)
    for action in ("raise_to:3", "raise_to:0", "raise_to:300", "raise_to:4.5",
                   "all_in", "raise_to:NaN"):
        with pytest.raises(ValueError):
            arena.step(action)
        assert arena.observe(arena.actor) == original
    # Legal arbitrary non-grid wager is applied exactly, never silently rounded.
    assert "raise_to:9" not in [a.id for a in arena.legal_actions()]
    arena.step(ArenaAction("raise_to", Decimal("9")))
    assert arena.observe(arena.actor)["bets"]["2"] == "9"


def test_short_allin_does_not_reopen_previous_actor():
    arena = AAFullHandArena(rules(), {0: 200, 1: 200, 2: 200, 3: 15,
                                      4: 200, 5: 200}).reset(1)
    arena.step("raise_to:10")  # seat2 full increment8
    arena.step("raise_to:15")  # seat3 allin +5, cannot reopen
    for _ in range(4):
        arena.step("check_call")
    assert arena.actor == 2
    assert {a.kind for a in arena.legal_actions()} == {"fold", "check_call"}
    with pytest.raises(ValueError):
        arena.step("raise_to:30")
    finish(arena)


def test_live_straddle_actor_minraise_and_postflop_minimum():
    arena = AAFullHandArena(rules(8, ante="1", ante_mode="per_dealt_player",
                                  straddle_mode="mandatory_utg",
                                  straddle_amount="4")).reset(3)
    assert arena.actor == 3
    assert arena.observe(3)["pot"] == "15"  # 8 antes + 1 + 2 + 4
    assert min(a.raise_to for a in arena.legal_actions()
               if a.kind == "raise_to") == 8
    with pytest.raises(ValueError):
        arena.step("raise_to:6")
    while arena.street == "preflop":
        arena.step("check_call")
    assert arena.street == "flop" and arena.actor == 0
    assert min(a.raise_to for a in arena.legal_actions()
               if a.kind == "raise_to") == 2
    finish(arena)


def test_optional_straddle_requires_explicit_seat_and_physical_mapping():
    rule = rules(straddle_mode="optional_explicit_utg", straddle_amount="4")
    occupied = (0, 1, 3, 4, 6, 7)
    arena = AAFullHandArena(rule, occupied_seats=occupied, dealer_seat=7,
                            optional_straddler=3).reset(0)
    assert arena.actor == 4
    assert arena.observe(4)["occupied_seats"] == list(occupied)
    assert set(arena.observe(4)["stacks"]) == {str(s) for s in occupied}
    with pytest.raises(ValueError):
        AAFullHandArena(rule, occupied_seats=occupied, optional_straddler=4)


@pytest.mark.parametrize("distribution", ["proportional_all_pots", "main_pot_first"])
def test_handcomputed_allin_sidepots_refund_and_single_hand_rake_cap(distribution):
    arena = AAFullHandArena(rules(rake_percent="0.1", rake_cap_bb="2",
                                  rake_distribution=distribution),
                            [10, 20, 60, 30, 40, 50]).reset(
        0, deck=deck_with("Ac Ad Kc Kd 9c 9d Qc Qd Jc Jd Tc Td "
                          "5c 2c 3d 4h 5d 6s 5h 8c"))
    while not arena.terminal:
        raises = [a for a in arena.legal_actions() if a.kind == "raise_to"]
        arena.step(raises[-1] if raises else "check_call")
    gross = [50, 30, -50, 10, -10, -30]
    deductions = ([Fraction(6, 5), 1, 0, Fraction(4, 5), Fraction(3, 5),
                   Fraction(2, 5)] if distribution == "proportional_all_pots"
                  else [4, 0, 0, 0, 0, 0])
    assert arena.terminal_returns() == {i: gross[i] - deductions[i] for i in range(6)}
    result = arena.terminal_result()
    assert result["rake"] == {"numerator": 4, "denominator": 1}
    assert result["refunds"]["2"] == {"numerator": 10, "denominator": 1}
    assert [p["amount"]["numerator"] for p in result["pots"]] == [60, 50, 40, 30, 20]
    assert sum(arena.terminal_returns().values()) == -4


def test_fold_terminal_rakes_matched_contribution_not_uncalled_raise():
    arena = AAFullHandArena(rules(rake_percent="0.5", rake_cap_bb="100")).reset(7)
    arena.step("raise_to:20")
    while not arena.terminal:
        arena.step("fold")
    # UTG contributes matched2, SB1, BB2: pot5; uncalled18 is returned.
    assert arena.terminal_returns()[2] == Fraction(1, 2)
    assert arena.terminal_result()["rake"] == {"numerator": 5, "denominator": 2}
    assert arena.terminal_result()["refunds"]["2"] == {
        "numerator": 18, "denominator": 1}


def test_no_flop_no_drop_and_rake_rounding():
    rule = rules(rake_percent="0.1", rake_cap_bb="5", rake_application="postflop_only",
                 rake_rounding="ceil_to_chip")
    arena = AAFullHandArena(rule).reset(4)
    while not arena.terminal:
        arena.step("fold")
    assert sum(arena.terminal_returns().values()) == 0
    arena.reset(4)
    finish(arena)
    assert sum(arena.terminal_returns().values()) == -2  # ceil(12 * .1)


def test_reject_unknown_rake_bad_stacks_deck_and_clone_independence():
    with pytest.raises(ValueError, match="unverified"):
        AAFullHandArena(replace(rules(), rake_distribution="unverified"))
    for stacks in ([0] * 6, [100] * 5, [Decimal("100.5")] * 6):
        with pytest.raises(ValueError):
            AAFullHandArena(rules(), stacks)
    arena = AAFullHandArena(rules()).reset(2)
    with pytest.raises(ValueError, match="52 unique"):
        arena.reset(2, deck=["Ac"] * 52)
    before = arena.observe(arena.actor)
    clone = arena.clone()
    clone.step("raise_to:100")
    assert arena.observe(arena.actor) == before


def test_short_forced_blind_refused_instead_of_reducing_nominal_call_price():
    # PokerKit would offer call1 when nominal BB2 has stack1. Until that
    # platform rule is adapted, refuse rather than silently model a 1chip BB.
    with pytest.raises(ValueError, match="short forced blind"):
        AAFullHandArena(rules(), {0: 200, 1: 1, 2: 200, 3: 200, 4: 200, 5: 200})


def test_handcomputed_threeway_board_tie_preserves_fractional_thirds():
    arena = AAFullHandArena(rules()).reset(
        1, deck=deck_with("2d 2h 3d 3h 4d 4h 5d 5h 6d 6h 7d 7h "
                          "8d Tc Jc Qc 8h Kc 8s Ac"))
    for action in ("check_call", "check_call", "fold", "fold", "fold", "check_call"):
        arena.step(action)
    returns = finish(arena)
    # SB's folded1 plus three players'2 = pot7, boardroyal splits7/3 each.
    assert returns == {0: -1, 1: Fraction(1, 3), 2: Fraction(1, 3),
                       3: Fraction(1, 3), 4: 0, 5: 0}
    assert arena.terminal_result()["returns"]["1"] == {"numerator": 1, "denominator": 3}
    assert arena.observe(1)["stacks"]["1"] == "601/3"
    assert sum(returns.values()) == 0
