"""Advice construction, refusal, legal-action, and stale tests."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from poker_engine.core.enums import ActionType
from poker_engine.core.value_objects import ChipAmount, ChipDelta
from poker_engine.strategy.advice import (
    Advice,
    AdviceStatus,
    build_advice,
    mark_stale,
)
from poker_engine.strategy.provider import (
    LookupState,
    MatchDimension,
    MatchKind,
)
from poker_engine.strategy.router import RouteResult
from poker_engine.strategy.safety import GateResult, GateStatus
from poker_engine.strategy.serialization import (
    strategy_deserialize,
    strategy_serialize,
)

from .helpers import NOW, candidate, context


def _route(value):
    return RouteResult(LookupState.HIT_EXACT, value, ())


def test_ready_advice_contains_source_actions_evidence_and_expiry():
    ctx = context()
    advice = build_advice(ctx, _route(candidate(ctx)), now=NOW)
    assert advice.status is AdviceStatus.READY
    assert advice.strategy_source == "mock-2p"
    assert sum(advice.action_probabilities.values()) == Decimal("1")
    assert advice.preferred_action is ActionType.RAISE
    assert advice.ev_gap.value == Decimal("1.25")
    assert advice.evidence
    assert advice.expires_at == ctx.request.expires_at


@pytest.mark.parametrize("with_math", [False, True])
def test_frequency_only_source_abstains_at_shared_advice_gate(with_math):
    ctx = context()
    value = replace(candidate(ctx), assumptions=("frequency_only_not_execution",))
    advice = build_advice(
        ctx, _route(value), now=NOW,
        math_report={"equity": Decimal("0.47")} if with_math else None,
        hard_gates=(GateResult("caller_qualification", GateStatus.PASS),),
    )
    assert advice.status is AdviceStatus.ABSTAIN
    assert advice.rejection_reasons == ("declared_model_frequency_only",)
    assert not advice.action_probabilities and not advice.action_options
    assert not advice.recommended_sizes and not advice.action_ev
    assert advice.preferred_action is None and advice.ev_gap is None
    assert next(g for g in advice.gate_results if g.name == "strategy_source") == (
        GateResult("strategy_source", GateStatus.FAIL,
                   ("declared_model_frequency_only",))
    )
    assert strategy_deserialize(Advice, strategy_serialize(advice)) == advice


def test_unrestricted_zero_confidence_source_keeps_existing_advice_behavior():
    ctx = context()
    value = replace(candidate(ctx), confidence=0, state_match_score=0,
                    match_kind=MatchKind.HEURISTIC)
    advice = build_advice(
        ctx, RouteResult(LookupState.HIT_APPROXIMATE, value, ()), now=NOW,
    )
    assert advice.status is AdviceStatus.READY
    assert advice.action_probabilities and advice.preferred_action is not None
    assert advice.confidence == 0


def test_frequency_only_source_preserves_stale_request_precedence():
    ctx = context()
    value = replace(candidate(ctx), assumptions=("frequency_only_not_execution",))
    advice = build_advice(ctx, _route(value), now=ctx.request.expires_at)
    assert advice.status is AdviceStatus.STALE
    assert advice.rejection_reasons == ("expired_request",)
    assert not advice.action_options and advice.preferred_action is None


def test_match_dimensions_survive_advice_serialization_round_trip():
    ctx = context()
    dimension = MatchDimension(
        "effective_stack_bb", "95", "100", Decimal("5"), Decimal("10")
    )
    value = candidate(
        ctx,
        match_kind=MatchKind.INTERPOLATED,
        score=0.5,
        match_dimensions=(dimension,),
    )
    advice = build_advice(
        ctx,
        RouteResult(LookupState.HIT_APPROXIMATE, value, ()),
        now=NOW,
    )

    restored = strategy_deserialize(Advice, strategy_serialize(advice))

    assert restored == advice
    assert restored.match_dimensions == (dimension,)


def test_ready_advice_ev_gap_is_unknown_if_any_legal_action_ev_is_missing():
    ctx = context()
    value = replace(
        candidate(ctx), action_ev={ActionType.RAISE: ChipDelta("1.25")}
    )
    advice = build_advice(ctx, _route(value), now=NOW)
    assert advice.status is AdviceStatus.READY
    assert advice.ev_gap is None


def test_illegal_actions_and_sizes_are_removed_then_renormalized():
    ctx = context()
    value = candidate(
        ctx,
        probabilities={
            ActionType.CHECK: Decimal("0.2"),
            ActionType.RAISE: Decimal("0.3"),
            ActionType.BET: Decimal("0.5"),
        },
    )
    args = dict(value.__dict__)
    args["recommended_sizes"] = {
        ActionType.RAISE: (ChipAmount("1"), ChipAmount("2.5")),
        ActionType.BET: (ChipAmount("10"),),
    }
    value = type(value)(**args)
    advice = build_advice(ctx, _route(value), now=NOW)
    assert advice.action_probabilities == {
        ActionType.CHECK: Decimal("0.4"),
        ActionType.RAISE: Decimal("0.6"),
    }
    assert advice.recommended_sizes == {
        ActionType.RAISE: (ChipAmount("2.5"),),
    }


def test_all_illegal_candidate_actions_produce_abstain():
    ctx = context()
    value = candidate(
        ctx, probabilities={ActionType.BET: Decimal("1")},
    )
    advice = build_advice(ctx, _route(value), now=NOW)
    assert advice.status is AdviceStatus.ABSTAIN
    assert advice.rejection_reasons == ("no_legal_strategy_actions",)


def test_equity_only_fallback_is_partial_without_action_frequencies():
    ctx = context()
    route = RouteResult(
        LookupState.NO_STRATEGY, None, (), ("no_strategy",),
    )
    advice = build_advice(
        ctx, route, math_report={"equity": Decimal("0.47")}, now=NOW,
    )
    assert advice.status is AdviceStatus.PARTIAL
    assert advice.match_kind is MatchKind.EQUITY_ONLY
    assert advice.action_probabilities == {}
    assert advice.math_report["equity"] == Decimal("0.47")


def test_missing_input_produces_abstain_before_strategy():
    ctx = context(missing_fields=("position",))
    route = RouteResult(
        LookupState.NO_STRATEGY, None, (), ("context_not_ready",),
    )
    advice = build_advice(ctx, route, now=NOW)
    assert advice.status is AdviceStatus.ABSTAIN
    assert advice.missing_inputs == ("position",)
    assert advice.rejection_reasons == ("position",)


def test_expired_request_produces_stale():
    ctx = context(expires_at=NOW - timedelta(seconds=1))
    advice = build_advice(ctx, _route(candidate(ctx)), now=NOW)
    assert advice.status is AdviceStatus.STALE
    assert advice.action_probabilities == {}
    assert advice.rejection_reasons == ("expired_request",)


def test_mark_stale_hides_previous_actions():
    ctx = context()
    ready = build_advice(ctx, _route(candidate(ctx)), now=NOW)
    stale = mark_stale(ready, reason="state_changed", now=NOW)
    assert stale.status is AdviceStatus.STALE
    assert stale.action_probabilities == {}
    assert stale.strategy_source == ready.strategy_source
    assert stale.rejection_reasons == ("state_changed",)


@pytest.mark.parametrize(
    "status", (AdviceStatus.ABSTAIN, AdviceStatus.STALE),
)
def test_refusal_status_cannot_expose_actions(status):
    with pytest.raises(ValueError, match="cannot expose"):
        Advice(
            hand_id="h", state_version=1, request_id="r",
            player_count=2, active_player_count=2, status=status,
            action_probabilities={ActionType.CHECK: Decimal("1")},
            rejection_reasons=("reason",), expires_at=NOW,
        )


def test_advice_round_trip_preserves_decimal_money_and_status():
    ctx = context()
    advice = build_advice(
        ctx, _route(candidate(ctx)),
        math_report={"equity": Decimal("0.4700000001")}, now=NOW,
    )
    payload = strategy_serialize(advice)
    restored = strategy_deserialize(Advice, payload)
    assert restored == advice
    assert payload["action_probabilities"]["raise"] == "0.6"
    assert payload["input_provenance"][0]["field_name"] == "hero_cards"
    assert payload["input_provenance"][1]["source"] == "manual"
    assert restored.math_report["equity"] == Decimal("0.4700000001")
