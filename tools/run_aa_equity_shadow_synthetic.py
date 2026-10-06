"""Exercise AA rule-aware equity for 6-8 players on synthetic river states."""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from poker_engine.core.enums import (
    ActionType, PlayerStatus, Position, Rank, Street, Suit,
)
from poker_engine.core.request_context import RequestContext
from poker_engine.core.value_objects import Card, ChipAmount
from poker_engine.strategy.aa_equity_shadow_v2 import evaluate_aa_equity_shadow
from poker_engine.strategy.aa_rules_v2 import (
    AARuleProfileV2,
    build_forced_bet_plan,
    reconcile_opening_debits,
)
from poker_engine.strategy.contracts import (
    ContextQuality,
    DecisionContext,
    DecisionSeat,
    EffectiveStack,
    LegalAction,
    PotState,
    RangeDistribution,
)
from tools.aa8_action_transfer import sha


NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def card(value):
    return Card(Rank(value[0]), Suit(value[1]))


def rules(count):
    return AARuleProfileV2.from_dict({
        "schema_version": 2, "table_size": count,
        "small_blind": "1", "big_blind": "2", "ante": "2",
        "ante_mode": "per_dealt_player", "straddle_mode": "mandatory_utg",
        "straddle_amount": "4", "rake_percent": "0.03",
        "rake_cap_bb": "2", "rake_application": "all_pots",
        "rake_rounding": "floor_to_chip",
        "rake_distribution": "proportional_all_pots", "minimum_chip": "1",
        "verification_status": "simulation",
        "source": "synthetic engine exercise only",
    })


def build_case(count):
    profile = rules(count)
    occupied = tuple(range(count))
    plan = build_forced_bet_plan(profile, occupied, dealer_seat=0)
    observed = {str(seat): str(plan.contributions[seat]) for seat in range(8)}
    opening = reconcile_opening_debits(profile, plan, observed)
    active = (2, 3, 4)
    seats = tuple(
        DecisionSeat(
            seat, "hero" if seat == 4 else f"p{seat}",
            plan.positions.get(seat, Position.UNKNOWN), ChipAmount("100"),
            ChipAmount("0"),
            ChipAmount("0"),
            PlayerStatus.ACTIVE if seat in active else PlayerStatus.FOLDED
            if seat in occupied else PlayerStatus.SITTING_OUT,
            occupied=seat in occupied, is_hero=seat == 4, is_dealer=seat == 0,
        )
        for seat in range(8)
    )
    request = RequestContext(
        f"synthetic-aa-{count}", 1, f"request-{count}", NOW,
        expires_at=NOW + timedelta(seconds=5), deadline_ms=300,
    )
    context = DecisionContext(
        request=request,
        game_config=profile.game_config(),
        seats=seats,
        hero_seat=4,
        actor_seat=4,
        active_seats=active,
        hero_cards=(card("As"), card("Ah")),
        board_cards=(card("2c"), card("7d"), card("9h"), card("Ts"), card("3h")),
        street=Street.RIVER,
        pots=(PotState("main", ChipAmount("150"), active),),
        legal_actions=(
            LegalAction(ActionType.CHECK, ChipAmount("0"), ChipAmount("0")),
            LegalAction(ActionType.BET, ChipAmount("2"), ChipAmount("100")),
        ),
        action_history=(),
        effective_stacks=(
            EffectiveStack(2, ChipAmount("100")),
            EffectiveStack(3, ChipAmount("100")),
        ),
        hero_range=None,
        villain_ranges=(
            RangeDistribution(
                2, {"QcQd": Decimal("1")}, "unbound",
                f"aa-ranges-v2:{profile.fingerprint}:unbound:synthetic", confidence=1.0,
            ),
            RangeDistribution(
                3, {"JcJd": Decimal("1")}, "unbound",
                f"aa-ranges-v2:{profile.fingerprint}:unbound:synthetic", confidence=1.0,
            ),
        ),
        input_quality=ContextQuality(1.0),
        input_provenance=(),
        action_line="unopened",
        assumptions=("synthetic_engine_exercise_not_strategy_asset",),
        effective_stack_bb=Decimal("50"),
    )
    return evaluate_aa_equity_shadow(
        context, profile, plan, opening, now=NOW, allow_untracked_ranges=True,
        allow_simulation=True,
    )


def run(output):
    results = []
    for count in (6, 7, 8):
        value = build_case(count)
        results.append({
            "player_count": count,
            "status": value.status.value,
            "reasons": list(value.reasons),
            "method": value.equity_report.method.value,
            "gross_expected_chips": str(value.gross_expected_chips),
            "configured_net_expected_chips": str(
                value.configured_net_expected_chips
            ),
            "rake": str(value.rake.amount),
            "pot_equity": str(value.equity_report.result.pot_equity),
            "elapsed_ms": value.elapsed_ms,
            "rule_fingerprint": value.rule_fingerprint,
            "advice_emitted": value.advice_emitted,
        })
    report = {
        "schema_version": 1,
        "scope": "synthetic_exact_river_engine_exercise_not_strategy_accuracy",
        "results": results,
        "implementation_sha256": {
            "equity": sha(Path(__file__).parents[1] /
                          "src/poker_engine/strategy/aa_equity_shadow_v2.py"),
            "rules": sha(Path(__file__).parents[1] /
                         "src/poker_engine/strategy/aa_rules_v2.py"),
            "runner": sha(Path(__file__)),
        },
        "provider_executed": False,
        "advice_emitted": False,
        "real_visual_input": False,
        "strategy_eligible": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
