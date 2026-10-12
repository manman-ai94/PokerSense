"""Process-level protocol, failure, budget, and Slow Path resolver tests."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from poker_engine.core.enums import ActionType
from poker_engine.core.request_context import RequestContext
from poker_engine.core.value_objects import ChipAmount, ChipDelta
from poker_engine.strategy.advice import AdviceStatus
from poker_engine.strategy.local_resolver import (
    LocalResolverConfig,
    LocalResolverProvider,
)
from poker_engine.strategy.orchestration import (
    RefinementState,
    StrategyOrchestrator,
    ThreadedSlowResolver,
)
from poker_engine.strategy.provider import LookupState, MatchKind
from poker_engine.strategy.router import StrategyRouter

from .helpers import capability, context


SCRIPT = (
    Path(__file__).parents[1]
    / "fixtures" / "strategy" / "resolver" / "fake_resolver.py"
)


# The protocol checks are not about speed: on a busy CI machine the fake
# resolver's interpreter start alone took over the old 0.5 s. They get a budget
# far from the point; the timeout tests below set tight ones of their own.
ROOMY_MS = 30_000


def _context(player_count=2, *, lifetime_ms=2 * ROOMY_MS):
    value = context(player_count)
    now = datetime.now(timezone.utc)
    request = RequestContext(
        hand_id=value.hand_id,
        state_version=value.state_version,
        request_id=value.request_id,
        requested_at=now,
        expires_at=now + timedelta(milliseconds=lifetime_ms),
        deadline_ms=lifetime_ms,
    )
    return replace(value, request=request)


def _provider(mode="success", **kwargs):
    return LocalResolverProvider(LocalResolverConfig(
        provider_id="local-cfr",
        source_version="solver-v3",
        command=(sys.executable, str(SCRIPT), mode),
        capability=capability(),
        result_match_kind=MatchKind.INTERPOLATED,
        timeout_ms=kwargs.pop("timeout_ms", ROOMY_MS),
        maximum_output_bytes=kwargs.pop("maximum_output_bytes", 50_000),
        **kwargs,
    ))


def test_converged_process_response_becomes_versioned_candidate():
    ctx = _context()
    result = _provider().query(ctx)

    assert result.state is LookupState.HIT_APPROXIMATE
    value = result.candidate
    assert value.provider_id == "local-cfr"
    assert value.provider_version == "solver-v3"
    assert value.match_kind is MatchKind.INTERPOLATED
    assert value.state_match_score == 0.9
    assert len(value.match_dimensions) == 1
    assert value.match_dimensions[0].name == "resolver_tree_abstraction"
    assert value.match_dimensions[0].score == 0.9
    assert value.action_probabilities == {
        ActionType.CHECK: Decimal("0.25"),
        ActionType.RAISE: Decimal("0.75"),
    }
    assert value.recommended_sizes == {
        ActionType.RAISE: (ChipAmount("2.5"),),
    }
    assert value.action_ev[ActionType.RAISE] == ChipDelta("1.5")
    assert value.expires_at == ctx.request.expires_at
    assert "resolver_iterations:1200" in value.evidence


@pytest.mark.parametrize(
    ("mode", "reason"),
    (
        ("not-converged", "resolver_not_converged"),
        ("wrong-identity", "resolver_invalid_response:ValueError"),
        ("wrong-version", "resolver_invalid_response:ValueError"),
        ("bad-probabilities", "resolver_invalid_response:ValueError"),
        ("missing-match-dimensions", "resolver_invalid_response:ValueError"),
        ("overstated-match-score", "resolver_invalid_response:ValueError"),
        ("bad-json", "resolver_invalid_json"),
        ("exit", "resolver_exit:7"),
    ),
)
def test_process_and_protocol_failures_are_recoverable_rejections(mode, reason):
    result = _provider(mode).query(_context())

    assert result.state is LookupState.REJECTED
    assert result.candidate is None
    assert result.reasons == (reason,)


def test_no_strategy_is_a_not_found_result_not_a_crash():
    result = _provider("no-strategy").query(_context())

    assert result.state is LookupState.NOT_FOUND
    assert result.reasons == ("resolver_no_strategy",)


def test_process_timeout_obeys_the_smaller_configured_budget():
    result = _provider("sleep", timeout_ms=20).query(_context())

    assert result.state is LookupState.REJECTED
    assert result.reasons == ("resolver_timeout",)


def test_request_deadline_can_tighten_process_timeout():
    result = _provider("sleep", timeout_ms=1_000).query(
        _context(lifetime_ms=20)
    )

    assert result.state is LookupState.REJECTED
    assert result.reasons == ("resolver_timeout",)


def test_expired_request_is_rejected_before_starting_process():
    ctx = _context()
    ctx = replace(ctx, request=replace(
        ctx.request,
        requested_at=datetime.now(timezone.utc) - timedelta(seconds=2),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    ))
    result = _provider().query(ctx)

    assert result.state is LookupState.REJECTED
    assert result.reasons == ("resolver_request_expired",)


def test_output_limit_rejects_oversized_stdout():
    result = _provider("large", maximum_output_bytes=100).query(_context())

    assert result.state is LookupState.REJECTED
    assert result.reasons == ("resolver_output_too_large",)


@pytest.mark.parametrize("mode", ("high-exploitability", "missing-exploitability"))
def test_configured_convergence_threshold_is_fail_closed(mode):
    result = _provider(
        mode,
        maximum_exploitability_bb100=Decimal("0.1"),
    ).query(_context())

    assert result.state is LookupState.REJECTED
    assert result.reasons == ("resolver_convergence_threshold_not_met",)


def test_capability_mismatch_does_not_start_invalid_command():
    provider = LocalResolverProvider(LocalResolverConfig(
        "local-cfr",
        "solver-v3",
        ("/definitely/missing/executable",),
        capability(),
        result_match_kind=MatchKind.INTERPOLATED,
    ))
    result = provider.query(_context(3))

    assert result.state is LookupState.NOT_APPLICABLE
    assert result.reasons == ("unsupported_player_count",)


def test_local_provider_runs_through_existing_async_slow_path():
    ctx = _context()
    with ThreadPoolExecutor(max_workers=1) as executor:
        slow = ThreadedSlowResolver(_provider(), executor)
        orchestrator = StrategyOrchestrator(StrategyRouter(), slow)
        cycle = orchestrator.request(ctx, now=datetime.now(timezone.utc))
        assert cycle.fast_advice.status is AdviceStatus.ABSTAIN
        assert cycle.slow_handle is not None
        cycle.slow_handle.future.result(timeout=ROOMY_MS / 1000)
        refinement = orchestrator.collect(
            cycle.slow_handle,
            ctx,
            now=datetime.now(timezone.utc),
        )

    assert refinement.state is RefinementState.APPLIED
    assert refinement.advice.status is AdviceStatus.READY
    assert refinement.advice.strategy_source == "local-cfr"


@pytest.mark.parametrize(
    "kwargs",
    (
        {"command": ()},
        {"timeout_ms": 0},
        {"maximum_output_bytes": 0},
        {"maximum_exploitability_bb100": Decimal("-1")},
    ),
)
def test_invalid_resolver_config_is_rejected(kwargs):
    values = {
        "provider_id": "local-cfr",
        "source_version": "v1",
        "command": (sys.executable, str(SCRIPT), "success"),
        "capability": capability(),
    }
    values.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        LocalResolverConfig(**values)
