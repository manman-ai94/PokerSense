"""Rule-aware gross and configured-net equity for AA shadow evaluation only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import math
from time import perf_counter
from types import MappingProxyType
from typing import Mapping

from poker_engine.core.enums import Street
from poker_engine.core.errors import InvalidStateError
from poker_engine.core._freeze import _require_aware_dt

from .aa_rules_v2 import (
    AARuleProfileV2,
    ForcedBetPlan,
    OpeningReconciliation,
    RakeEstimate,
    estimate_rake,
)
from .adaptive_equity import (
    AdaptiveEquityPolicy,
    AdaptiveEquityReport,
    EquityComputationStatus,
    calculate_adaptive_equity,
)
from .contracts import DecisionContext
from .equity_cache import EquityCache
from .aa_range_assets_v2 import (
    AARangeReadinessV2,
    AARangeShadowSnapshotV2,
    assess_aa_range_readiness,
    is_explicitly_unbound_range,
    parse_range_identity,
)


class AAEquityShadowStatus(str, Enum):
    BLOCKED = "BLOCKED"
    SIMULATION = "SIMULATION"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True)
class AAEquityShadowResult:
    status: AAEquityShadowStatus
    rule_fingerprint: str
    reasons: tuple[str, ...]
    gross_expected_chips: Decimal | None = None
    configured_net_expected_chips: Decimal | None = None
    rake: RakeEstimate | None = None
    rake_allocations: Mapping[str, Decimal] | None = None
    equity_report: AdaptiveEquityReport | None = None
    elapsed_ms: float = 0.0
    advice_emitted: bool = False
    strategy_eligible: bool = False
    range_readiness: AARangeReadinessV2 | None = None

    def __post_init__(self):
        if not isinstance(self.status, AAEquityShadowStatus):
            raise TypeError("status must be AAEquityShadowStatus")
        if not isinstance(self.rule_fingerprint, str) or len(
            self.rule_fingerprint
        ) != 64:
            raise ValueError("rule_fingerprint must be SHA-256")
        reasons = tuple(self.reasons)
        if not all(isinstance(reason, str) and reason for reason in reasons):
            raise TypeError("reasons must contain non-empty strings")
        object.__setattr__(self, "reasons", reasons)
        allocations = dict(self.rake_allocations or {})
        if not all(
            isinstance(key, str) and key and isinstance(value, Decimal)
            and value.is_finite() and value >= 0
            for key, value in allocations.items()
        ):
            raise ValueError("rake allocations must be non-negative Decimals")
        object.__setattr__(self, "rake_allocations", MappingProxyType(allocations))
        if (not isinstance(self.elapsed_ms, (int, float))
                or isinstance(self.elapsed_ms, bool)
                or not math.isfinite(self.elapsed_ms) or self.elapsed_ms < 0):
            raise ValueError("elapsed_ms must be finite and non-negative")
        if (self.status is not AAEquityShadowStatus.BLOCKED
                and self.equity_report is None):
            raise ValueError("non-blocked shadow equity requires a report")
        if self.equity_report is not None:
            if not isinstance(self.rake, RakeEstimate) or any(
                not isinstance(value, Decimal) or not value.is_finite()
                for value in (
                    self.gross_expected_chips, self.configured_net_expected_chips,
                )
            ):
                raise TypeError("completed shadow equity requires Decimal outputs")
            pot_ids = {pot.pot_id for pot in self.equity_report.result.pots}
            if set(allocations) != pot_ids or sum(
                allocations.values(), Decimal("0")
            ) != self.rake.amount:
                raise ValueError("rake allocations must cover report pots exactly")
        if self.advice_emitted or self.strategy_eligible:
            raise ValueError("shadow equity cannot become live strategy")


def _opening_exact(plan, opening):
    return (
        opening.status == "EXACT_FORCED_BETS"
        and dict(opening.expected) == dict(plan.contributions)
        and all(value == 0 for value in opening.differences.values())
        and opening.total_difference == 0
    )


def _allocate_rake(context, rules, amount):
    if amount < 0:
        raise ValueError("rake amount cannot be negative")
    pots = context.pots
    total = sum((pot.amount.value for pot in pots), Decimal("0"))
    if amount > total:
        raise ValueError("rake cannot exceed total pot")
    allocations = {pot.pot_id: Decimal("0") for pot in pots}
    if amount == 0:
        return allocations
    if rules.rake_distribution == "proportional_all_pots":
        remaining = amount
        for pot in pots[:-1]:
            value = amount * pot.amount.value / total
            allocations[pot.pot_id] = value
            remaining -= value
        allocations[pots[-1].pot_id] = remaining
    elif rules.rake_distribution == "main_pot_first":
        remaining = amount
        for pot in pots:
            value = min(remaining, pot.amount.value)
            allocations[pot.pot_id] = value
            remaining -= value
    else:
        raise ValueError("rake distribution is unverified")
    return allocations


def evaluate_aa_equity_shadow(
    context: DecisionContext,
    rules: AARuleProfileV2,
    plan: ForcedBetPlan,
    opening: OpeningReconciliation,
    *,
    now,
    allow_simulation=False,
    policy: AdaptiveEquityPolicy | None = None,
    cache: EquityCache | None = None,
    minimum_range_confidence: float = .25,
    range_snapshot: AARangeShadowSnapshotV2 | None = None,
    allow_untracked_ranges: bool = False,
):
    if not isinstance(context, DecisionContext):
        raise TypeError("context must be DecisionContext")
    if not isinstance(rules, AARuleProfileV2):
        raise TypeError("rules must be AARuleProfileV2")
    if not isinstance(plan, ForcedBetPlan):
        raise TypeError("plan must be ForcedBetPlan")
    if not isinstance(opening, OpeningReconciliation):
        raise TypeError("opening must be OpeningReconciliation")
    if not isinstance(allow_simulation, bool):
        raise TypeError("allow_simulation must be bool")
    if not isinstance(allow_untracked_ranges, bool):
        raise TypeError("allow_untracked_ranges must be bool")
    started = perf_counter()
    reasons = []
    simulation = rules.verification_status == "simulation"
    if simulation and not allow_simulation:
        reasons.append("simulation_rules_not_explicitly_enabled")
    elif not simulation:
        reasons.extend(rules.live_strategy_blockers)
    if context.game_config != rules.game_config():
        reasons.append("decision_context_rule_profile_mismatch")
    if plan.rules_fingerprint != rules.fingerprint:
        reasons.append("forced_bet_plan_rule_fingerprint_mismatch")
    if not _opening_exact(plan, opening):
        reasons.append("opening_forced_bets_not_exact")
    if not context.is_decision_ready:
        reasons.append("decision_context_not_ready")
    # Mirror the existing adaptive-equity expiry predicate before any math;
    # deadline_ms and sampling budgets keep their existing semantics.
    try:
        if not isinstance(now, datetime):
            raise TypeError("now must be a datetime")
        _require_aware_dt(now)
        if (context.request.expires_at is not None
                and now >= context.request.expires_at):
            reasons.append(
                "equity_input_or_computation_error:equity_deadline_expired"
            )
    except (TypeError, ValueError) as exc:
        reasons.append(f"equity_input_or_computation_error:{exc}")
    readiness = assess_aa_range_readiness(
        context.villain_ranges,
        hero_seat=context.hero_seat,
        pots=context.pots,
        rule_fingerprint=rules.fingerprint,
        minimum_confidence=minimum_range_confidence,
    )
    reasons.extend(readiness.reasons)
    explicitly_unbound = bool(context.villain_ranges) and all(
        is_explicitly_unbound_range(item, rules.fingerprint)
        for item in context.villain_ranges
    )
    if range_snapshot is None:
        if not allow_untracked_ranges:
            reasons.append("range_tracker_snapshot_missing")
        if not simulation:
            reasons.append("missing_range_snapshot_with_non_simulation_rules")
        if not explicitly_unbound:
            reasons.append("missing_snapshot_cannot_wrap_bound_ranges")
            reasons.append("untracked_range_source_not_explicitly_unbound")
    elif not isinstance(range_snapshot, AARangeShadowSnapshotV2):
        raise TypeError("range_snapshot must be AARangeShadowSnapshotV2 or None")
    else:
        if range_snapshot.asset_status == "unbound":
            if not simulation:
                reasons.append("unbound_range_snapshot_with_non_simulation_rules")
            if not allow_untracked_ranges:
                reasons.append("unbound_range_snapshot_requires_test_opt_in")
            if any(getattr(range_snapshot, name) is not None for name in (
                "asset_id", "asset_version", "asset_sha256", "rule_fingerprint",
            )) or not explicitly_unbound:
                reasons.append("unbound_snapshot_cannot_wrap_bound_ranges")
        else:
            identity = (
                range_snapshot.rule_fingerprint, range_snapshot.asset_status,
                range_snapshot.asset_id, range_snapshot.asset_version,
                range_snapshot.asset_sha256,
            )
            if any(value is None for value in identity):
                reasons.append("range_snapshot_asset_identity_missing")
            if range_snapshot.asset_status not in ("shadow_reviewed", "live_approved"):
                reasons.append("snapshot_asset_status_not_shadow_permitted")
            if (not context.villain_ranges or any(
                parse_range_identity(item.source_version) != identity
                or item.source != range_snapshot.asset_id
                for item in context.villain_ranges
            )):
                reasons.append("range_snapshot_asset_identity_mismatch")
            if range_snapshot.rule_fingerprint != rules.fingerprint:
                reasons.append("range_snapshot_rule_fingerprint_mismatch")
        if not range_snapshot.equity_permitted or range_snapshot.blockers:
            reasons.append("range_tracker_snapshot_not_permitted")
        if range_snapshot.distributions != context.villain_ranges:
            reasons.append("range_tracker_context_mismatch")
        if range_snapshot.advice_emitted or range_snapshot.strategy_eligible:
            reasons.append("range_tracker_snapshot_claims_strategy")
    if reasons:
        return AAEquityShadowResult(
            AAEquityShadowStatus.BLOCKED, rules.fingerprint,
            tuple(dict.fromkeys(reasons)),
            elapsed_ms=(perf_counter() - started) * 1000,
            range_readiness=readiness,
        )
    saw_flop = context.street is not Street.PREFLOP
    rake = estimate_rake(rules, str(sum(
        (pot.amount.value for pot in context.pots), Decimal("0")
    )), saw_flop=saw_flop)
    if rake.amount is None:
        return AAEquityShadowResult(
            AAEquityShadowStatus.BLOCKED, rules.fingerprint,
            (rake.reason,), rake=rake,
            elapsed_ms=(perf_counter() - started) * 1000,
            range_readiness=readiness,
        )
    try:
        report = calculate_adaptive_equity(
            context, now=now, policy=policy, cache=cache
        )
        allocations = _allocate_rake(context, rules, rake.amount)
    except (InvalidStateError, TypeError, ValueError) as exc:
        return AAEquityShadowResult(
            AAEquityShadowStatus.BLOCKED, rules.fingerprint,
            (f"equity_input_or_computation_error:{exc}",), rake=rake,
            elapsed_ms=(perf_counter() - started) * 1000,
            range_readiness=readiness,
        )
    by_id = {pot.pot_id: pot for pot in report.result.pots}
    net = sum((
        (by_id[pot.pot_id].amount.value - allocations[pot.pot_id])
        * by_id[pot.pot_id].expected_share for pot in context.pots
    ), Decimal("0"))
    status = AAEquityShadowStatus.SIMULATION if simulation else (
        AAEquityShadowStatus.COMPLETE
        if report.status is EquityComputationStatus.COMPLETE
        else AAEquityShadowStatus.PARTIAL
    )
    disclosures = []
    if simulation:
        disclosures.append("simulation_rules_only")
    if range_snapshot is None or range_snapshot.asset_status == "unbound":
        disclosures.append("untracked_ranges_explicit_test_only")
    return AAEquityShadowResult(
        status=status,
        rule_fingerprint=rules.fingerprint,
        reasons=tuple(disclosures),
        gross_expected_chips=report.result.expected_chips.value,
        configured_net_expected_chips=net,
        rake=rake,
        rake_allocations=allocations,
        equity_report=report,
        elapsed_ms=(perf_counter() - started) * 1000,
        range_readiness=readiness,
    )


__all__ = [
    "AAEquityShadowResult", "AAEquityShadowStatus", "evaluate_aa_equity_shadow",
]
