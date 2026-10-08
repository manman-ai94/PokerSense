import json
from decimal import Decimal
from pathlib import Path

import pytest

from poker_engine.core.enums import Position
from poker_engine.strategy.aa_rules_v2 import (
    AARuleProfileV2,
    build_forced_bet_plan,
    estimate_rake,
    reconcile_opening_debits,
)


ROOT = Path(__file__).resolve().parents[2]


def profile(**changes):
    values = {
        "schema_version": 2,
        "table_size": 8,
        "small_blind": "1",
        "big_blind": "2",
        "ante": "2",
        "ante_mode": "per_dealt_player",
        "straddle_mode": "mandatory_utg",
        "straddle_amount": "4",
        "rake_percent": "0.03",
        "rake_cap_bb": "2",
        "rake_application": "all_pots",
        "rake_rounding": "floor_to_chip",
        "rake_distribution": "proportional_all_pots",
        "minimum_chip": "1",
        "verification_status": "simulation",
        "source": "test",
    }
    values.update(changes)
    return AARuleProfileV2.from_dict(values)


@pytest.mark.parametrize("count", (5, 6, 7, 8))
def test_mandatory_utg_straddle_and_positions_are_parameterized(count):
    rules = profile(table_size=count)
    occupied = tuple(range(count))
    plan = build_forced_bet_plan(rules, occupied, dealer_seat=0)
    assert plan.positions[0] is Position.BTN
    assert plan.positions[1] is Position.SB
    assert plan.positions[2] is Position.BB
    assert plan.positions[3] is Position.UTG
    assert plan.straddler_seat == 3
    assert plan.first_actor_seat == 4
    assert plan.current_bet == Decimal("4")
    assert plan.minimum_raise_to == Decimal("8")
    assert plan.contributions[1] == 3
    assert plan.contributions[2] == 4
    assert plan.contributions[3] == 6
    assert plan.expected_total == Decimal(2 * count + 7)
    assert plan.positions[count - 1] is Position.CO


def test_real_development_opening_difference_stays_unallocated():
    rules = profile(table_size=7)
    plan = build_forced_bet_plan(rules, (0, 1, 2, 3, 4, 5, 7), dealer_seat=7)
    observed = {
        "0": "3", "1": "4", "2": "6", "3": "2",
        "4": "4", "5": "2", "6": "0", "7": "8",
    }
    result = reconcile_opening_debits(rules, plan, observed)
    assert result.status == "UNALLOCATED_OPENING_DIFFERENCE"
    assert result.differences[4] == 2
    assert result.differences[7] == 6
    assert result.total_difference == 8
    assert not result.automatic_fee_attribution
    assert not result.strategy_eligible


def test_exact_live_profile_can_authorize_reconciled_forced_bets():
    rules = profile(
        table_size=6, verification_status="live_verified",
        rake_application="postflop_only", rake_rounding="exact",
    )
    plan = build_forced_bet_plan(rules, tuple(range(6)), dealer_seat=0)
    observed = {str(seat): str(plan.contributions[seat]) for seat in range(8)}
    result = reconcile_opening_debits(rules, plan, observed)
    assert result.status == "EXACT_FORCED_BETS"
    assert result.strategy_eligible


def test_simulation_profile_never_authorizes_live_strategy():
    rules = profile()
    assert rules.live_strategy_blockers == ("aa_rules_not_live_verified",)
    assert rules.game_config().dealt_player_count == 8
    assert rules.game_config().rake_cap.value == 4


def test_profile_fingerprint_changes_with_every_material_rule():
    base = profile().fingerprint
    for change in (
        {"ante": "1"}, {"rake_percent": "0.02"}, {"straddle_amount": "5"},
        {"rake_rounding": "exact"}, {"table_size": 7},
        {"rake_distribution": "main_pot_first"},
    ):
        assert profile(**change).fingerprint != base


def test_rake_is_exactly_capped_and_rounded_by_config():
    rules = profile(
        verification_status="live_verified", rake_application="all_pots",
        rake_rounding="floor_to_chip",
    )
    small = estimate_rake(rules, "99", saw_flop=True)
    assert small.uncapped == Decimal("2.97")
    assert small.amount == Decimal("2")
    assert small.strategy_eligible
    capped = estimate_rake(rules, "1000", saw_flop=True)
    assert capped.uncapped == Decimal("30.00")
    assert capped.amount == Decimal("4")
    fractional_cap = profile(
        verification_status="live_verified", rake_application="all_pots",
        rake_rounding="ceil_to_chip", rake_cap_bb="1.75", minimum_chip="0.5",
    )
    assert estimate_rake(fractional_cap, "1000", saw_flop=True).amount == (
        Decimal("3.50")
    )


def test_no_flop_no_drop_requires_explicit_policy_and_evidence():
    rules = profile(
        verification_status="live_verified", rake_application="postflop_only",
        rake_rounding="exact",
    )
    assert estimate_rake(rules, "100", saw_flop=False).amount == 0
    assert estimate_rake(rules, "100", saw_flop=None).status == "UNKNOWN"
    unknown = profile(rake_application="unverified", rake_rounding="unverified")
    result = estimate_rake(unknown, "100", saw_flop=True)
    assert result.status == "UNKNOWN" and result.amount is None


@pytest.mark.parametrize("change", (
    {"table_size": 4}, {"table_size": 9}, {"small_blind": "2"}, {"big_blind": "1"},
    {"straddle_amount": "2"}, {"rake_percent": "1.1"},
    {"minimum_chip": "0"}, {"small_blind": 1},
    {"minimum_chip": "0.6"},
))
def test_invalid_rules_rejected(change):
    with pytest.raises(ValueError):
        profile(**change)


def test_optional_straddle_requires_explicit_utg_and_none_rejects_it():
    optional = profile(
        straddle_mode="optional_explicit_utg", verification_status="simulation",
    )
    no_straddle = build_forced_bet_plan(optional, tuple(range(8)), 0)
    assert no_straddle.straddler_seat is None
    with_straddle = build_forced_bet_plan(
        optional, tuple(range(8)), 0, observed_optional_straddler=3
    )
    assert with_straddle.straddler_seat == 3
    with pytest.raises(ValueError, match="explicit UTG"):
        build_forced_bet_plan(
            optional, tuple(range(8)), 0, observed_optional_straddler=4
        )
    disabled = profile(straddle_mode="none", straddle_amount="0")
    with pytest.raises(ValueError, match="conflicts"):
        build_forced_bet_plan(
            disabled, tuple(range(8)), 0, observed_optional_straddler=3
        )


def test_checked_in_profile_is_explicit_simulation_not_live():
    path = ROOT / "configs/game/aa-shadow-rules-v2.json"
    rules = AARuleProfileV2.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert rules.table_size == 8
    assert rules.verification_status == "simulation"
    assert rules.game_config().game_type.value == "cash"
