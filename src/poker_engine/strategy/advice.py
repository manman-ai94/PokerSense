"""Advice contract, candidate legalization, and refusal/stale gates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from poker_engine.core._freeze import _require_aware_dt, freeze_mapping, utc_now
from poker_engine.core.enums import ActionType
from poker_engine.core.request_context import RequestContext
from poker_engine.core.value_objects import ChipAmount, ChipDelta

from .contracts import DecisionContext, InputProvenance
from .confidence import aggregate_confidence
from .ev import calculate_ev_gap
from .evidence import audit_evidence_chain
from .provider import ActionOption, MatchDimension, MatchKind, StrategyCandidate
from .router import RouteResult
from .safety import GateResult, GateStatus, validate_gate_set


_BUILTIN_GATE_NAMES = frozenset({
    "request_freshness",
    "confidence_components",
    "decision_context",
    "strategy_source",
    "legal_strategy_actions",
})


class AdviceStatus(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    ABSTAIN = "ABSTAIN"
    STALE = "STALE"


@dataclass(frozen=True)
class Advice:
    hand_id: str
    state_version: int
    request_id: str
    player_count: int
    active_player_count: int
    status: AdviceStatus
    action_probabilities: Mapping[ActionType, Decimal] = field(
        default_factory=dict
    )
    recommended_sizes: Mapping[ActionType, tuple[ChipAmount, ...]] = field(
        default_factory=dict
    )
    action_options: tuple[ActionOption, ...] = ()
    action_ev: Mapping[ActionType, ChipDelta] = field(default_factory=dict)
    ev_gap: ChipDelta | None = None
    preferred_action: ActionType | None = None
    math_report: Mapping[str, Any] = field(default_factory=dict)
    strategy_source: str | None = None
    strategy_version: str | None = None
    match_kind: MatchKind | None = None
    state_match_score: float | None = None
    match_dimensions: tuple[MatchDimension, ...] = ()
    confidence: float = 0.0
    confidence_factors: Mapping[str, float] = field(default_factory=dict)
    missing_confidence_factors: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    input_provenance: tuple[InputProvenance, ...] = ()
    evidence_chain_id: str | None = None
    evidence_complete: bool = False
    missing_evidence: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    gate_results: tuple[GateResult, ...] = ()
    expires_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("hand_id", "request_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty str")
        if not isinstance(self.state_version, int) or isinstance(
            self.state_version, bool
        ):
            raise TypeError("state_version must be an int")
        if self.state_version < 0:
            raise ValueError("state_version must be >= 0")
        for name in ("player_count", "active_player_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int")
            if not 2 <= value <= 9:
                raise ValueError(f"{name} must be in [2, 9]")
        if self.active_player_count > self.player_count:
            raise ValueError("active_player_count cannot exceed player_count")
        if not isinstance(self.status, AdviceStatus):
            raise TypeError("status must be an AdviceStatus")

        probabilities = dict(self.action_probabilities)
        for action, probability in probabilities.items():
            if not isinstance(action, ActionType):
                raise TypeError("action probability keys must be ActionType")
            if not isinstance(probability, Decimal):
                raise TypeError("action probabilities must be Decimal")
            if not probability.is_finite() or not (
                Decimal("0") <= probability <= Decimal("1")
            ):
                raise ValueError("action probabilities must be in [0, 1]")
        if probabilities and sum(
            probabilities.values(), Decimal("0")
        ) != Decimal("1"):
            raise ValueError("action probabilities must sum exactly to 1")
        object.__setattr__(self, "action_probabilities", freeze_mapping(probabilities))

        sizes = {}
        for action, values in dict(self.recommended_sizes).items():
            if not isinstance(action, ActionType):
                raise TypeError("recommended_sizes keys must be ActionType")
            values = tuple(values)
            if not all(isinstance(value, ChipAmount) for value in values):
                raise TypeError("recommended sizes must be ChipAmount values")
            if action not in probabilities:
                raise ValueError("recommended size action must have probability")
            sizes[action] = values
        object.__setattr__(self, "recommended_sizes", freeze_mapping(sizes))

        options = tuple(self.action_options)
        if not all(isinstance(option, ActionOption) for option in options):
            raise TypeError("action_options must contain ActionOption values")
        if options:
            if sum(
                (option.probability for option in options), Decimal("0")
            ) != Decimal("1"):
                raise ValueError("action option probabilities must sum to 1")
            totals: dict[ActionType, Decimal] = {}
            for option in options:
                totals[option.action] = (
                    totals.get(option.action, Decimal("0"))
                    + option.probability
                )
            if totals != probabilities:
                raise ValueError(
                    "action options must aggregate to action_probabilities"
                )
        object.__setattr__(self, "action_options", options)

        action_ev = dict(self.action_ev)
        if not all(isinstance(action, ActionType) for action in action_ev):
            raise TypeError("action_ev keys must be ActionType")
        if not all(isinstance(value, ChipDelta) for value in action_ev.values()):
            raise TypeError("action_ev values must be ChipDelta")
        if not set(action_ev) <= set(probabilities):
            raise ValueError("action_ev can only describe advised actions")
        object.__setattr__(self, "action_ev", freeze_mapping(action_ev))

        input_provenance = tuple(self.input_provenance)
        if not all(
            isinstance(item, InputProvenance) for item in input_provenance
        ):
            raise TypeError(
                "input_provenance must contain InputProvenance values"
            )
        fields = [item.field_name for item in input_provenance]
        if len(fields) != len(set(fields)):
            raise ValueError("input_provenance fields must be unique")
        object.__setattr__(self, "input_provenance", input_provenance)
        if self.ev_gap is not None and not isinstance(self.ev_gap, ChipDelta):
            raise TypeError("ev_gap must be a ChipDelta or None")
        if self.ev_gap is not None and self.ev_gap.value < 0:
            raise ValueError("ev_gap must be non-negative")
        if self.preferred_action is not None:
            if not isinstance(self.preferred_action, ActionType):
                raise TypeError("preferred_action must be an ActionType or None")
            if self.preferred_action not in probabilities:
                raise ValueError("preferred_action must be an advised action")
        object.__setattr__(self, "math_report", freeze_mapping(self.math_report))
        if (self.strategy_source is None) != (self.strategy_version is None):
            raise ValueError("strategy source and version must appear together")
        if self.match_kind is not None and not isinstance(
            self.match_kind, MatchKind
        ):
            raise TypeError("match_kind must be a MatchKind or None")
        if self.state_match_score is not None:
            if not isinstance(self.state_match_score, (int, float)) or isinstance(
                self.state_match_score, bool
            ):
                raise TypeError("state_match_score must be a float or None")
            if not math.isfinite(self.state_match_score) or not (
                0 <= self.state_match_score <= 1
            ):
                raise ValueError("state_match_score must be in [0, 1]")
        dimensions = tuple(self.match_dimensions)
        if not all(isinstance(value, MatchDimension) for value in dimensions):
            raise TypeError("match_dimensions must contain MatchDimension values")
        names = [value.name for value in dimensions]
        if len(names) != len(set(names)):
            raise ValueError("match dimension names must be unique")
        object.__setattr__(self, "match_dimensions", dimensions)
        if not isinstance(self.confidence, (int, float)) or isinstance(
            self.confidence, bool
        ):
            raise TypeError("confidence must be a float")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        factors = dict(self.confidence_factors)
        if not all(isinstance(name, str) and name for name in factors):
            raise TypeError("confidence factor names must be non-empty strings")
        for name, value in factors.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"confidence factor {name!r} must be a float")
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("confidence factors must be in [0, 1]")
        missing_confidence = tuple(self.missing_confidence_factors)
        if not all(
            isinstance(name, str) and name for name in missing_confidence
        ):
            raise TypeError(
                "missing_confidence_factors must contain non-empty strings"
            )
        object.__setattr__(
            self, "missing_confidence_factors", missing_confidence
        )
        if missing_confidence and self.confidence != 0:
            raise ValueError("missing confidence factors require confidence 0")
        if (not missing_confidence and factors
                and self.confidence != min(factors.values())):
            raise ValueError("confidence must equal the minimum confidence factor")
        object.__setattr__(self, "confidence_factors", freeze_mapping(factors))
        for name in (
            "evidence", "missing_evidence", "assumptions", "missing_inputs",
            "rejection_reasons",
        ):
            values = tuple(getattr(self, name))
            if not all(isinstance(value, str) and value for value in values):
                raise TypeError(f"{name} must contain non-empty strings")
            object.__setattr__(self, name, values)
        gates = validate_gate_set(tuple(self.gate_results))
        object.__setattr__(self, "gate_results", gates)
        if self.status is AdviceStatus.READY and any(
            item.status is GateStatus.FAIL for item in gates
        ):
            raise ValueError("READY Advice cannot contain a failed gate")
        if self.evidence_chain_id is not None:
            if not isinstance(self.evidence_chain_id, str) or (
                len(self.evidence_chain_id) != 64
                or any(char not in "0123456789abcdef"
                       for char in self.evidence_chain_id.lower())
            ):
                raise ValueError("evidence_chain_id must be a SHA-256 hex digest")
            if not isinstance(self.evidence_complete, bool):
                raise TypeError("evidence_complete must be a bool")
            if self.evidence_complete == bool(self.missing_evidence):
                raise ValueError("evidence_complete and missing_evidence disagree")
            if (
                self.status is AdviceStatus.READY
                and not self.evidence_complete
                and self.confidence > 0.49
            ):
                raise ValueError(
                    "incomplete READY evidence cannot have high confidence"
                )
        if not isinstance(self.expires_at, datetime):
            raise TypeError("expires_at must be a datetime")
        _require_aware_dt(self.expires_at)
        self._validate_status_contract()

    def _validate_status_contract(self) -> None:
        if self.status is AdviceStatus.READY:
            if not self.action_probabilities:
                raise ValueError("READY Advice requires action probabilities")
            if self.strategy_source is None or self.match_kind is None:
                raise ValueError("READY Advice requires strategy source and match")
            if not self.evidence:
                raise ValueError("READY Advice requires evidence")
            if self.rejection_reasons:
                raise ValueError("READY Advice cannot have rejection reasons")
        elif self.status in (AdviceStatus.ABSTAIN, AdviceStatus.STALE):
            if (self.action_probabilities or self.recommended_sizes
                    or self.action_options or self.action_ev):
                raise ValueError("ABSTAIN/STALE cannot expose strategy actions")
            if self.preferred_action is not None or self.ev_gap is not None:
                raise ValueError("ABSTAIN/STALE cannot expose preferences or EV gap")
            if not self.rejection_reasons:
                raise ValueError("ABSTAIN/STALE requires rejection reasons")


def legalize_candidate(
    context: DecisionContext,
    candidate: StrategyCandidate,
) -> tuple[
    Mapping[ActionType, Decimal],
    Mapping[ActionType, tuple[ChipAmount, ...]],
    tuple[ActionOption, ...],
    Mapping[ActionType, ChipDelta],
]:
    legal_by_type = {item.action: item for item in context.legal_actions}
    if candidate.action_options:
        kept_options = []
        for option in candidate.action_options:
            bounds = legal_by_type.get(option.action)
            if bounds is None:
                continue
            if option.amount is not None and not (
                bounds.min_amount <= option.amount <= bounds.max_amount
            ):
                continue
            kept_options.append(option)
        option_total = sum(
            (option.probability for option in kept_options), Decimal("0")
        )
        if option_total <= 0:
            return (
                freeze_mapping({}), freeze_mapping({}), (), freeze_mapping({})
            )
        normalized_options = tuple(
            ActionOption(
                action=option.action,
                probability=option.probability / option_total,
                amount=option.amount,
                source_label=option.source_label,
            )
            for option in kept_options
        )
        last = normalized_options[-1]
        normalized_options = normalized_options[:-1] + (ActionOption(
            action=last.action,
            probability=Decimal("1") - sum(
                (option.probability for option in normalized_options[:-1]),
                Decimal("0"),
            ),
            amount=last.amount,
            source_label=last.source_label,
        ),)
        normalized: dict[ActionType, Decimal] = {}
        sizes: dict[ActionType, list[ChipAmount]] = {}
        for option in normalized_options:
            normalized[option.action] = (
                normalized.get(option.action, Decimal("0"))
                + option.probability
            )
            if option.amount is not None:
                sizes.setdefault(option.action, []).append(option.amount)
        action_ev = {
            action: value for action, value in candidate.action_ev.items()
            if action in normalized
        }
        return (
            freeze_mapping(normalized),
            freeze_mapping({
                action: tuple(dict.fromkeys(values))
                for action, values in sizes.items()
            }),
            normalized_options,
            freeze_mapping(action_ev),
        )
    kept = {
        action: probability
        for action, probability in candidate.action_probabilities.items()
        if action in legal_by_type and probability > 0
    }
    total = sum(kept.values(), Decimal("0"))
    if total <= 0:
        return (
            freeze_mapping({}), freeze_mapping({}), (), freeze_mapping({})
        )
    normalized = {
        action: probability / total for action, probability in kept.items()
    }
    sizes = {}
    for action, values in candidate.recommended_sizes.items():
        if action not in normalized:
            continue
        bounds = legal_by_type[action]
        valid = tuple(
            value for value in values
            if bounds.min_amount <= value <= bounds.max_amount
        )
        if valid:
            sizes[action] = valid
    action_ev = {
        action: value for action, value in candidate.action_ev.items()
        if action in normalized
    }
    return (
        freeze_mapping(normalized),
        freeze_mapping(sizes),
        (),
        freeze_mapping(action_ev),
    )


def build_advice(
    context: DecisionContext,
    route: RouteResult,
    *,
    math_report: Mapping[str, Any] | None = None,
    confidence_components: Mapping[str, float | None] | None = None,
    hard_gates: tuple[GateResult, ...] = (),
    now: datetime | None = None,
) -> Advice:
    if not isinstance(context, DecisionContext):
        raise TypeError("context must be a DecisionContext")
    if not isinstance(route, RouteResult):
        raise TypeError("route must be a RouteResult")
    now = now or utc_now()
    if not isinstance(now, datetime):
        raise TypeError("now must be a datetime")
    _require_aware_dt(now)
    expires_at = _expiry(context.request, now)
    candidate = route.selected
    candidate_restrictions = (
        ("declared_model_frequency_only",)
        if candidate is not None
        and "frequency_only_not_execution" in candidate.assumptions else ()
    )
    external_gates = validate_gate_set(
        tuple(hard_gates), reserved_names=_BUILTIN_GATE_NAMES
    )
    evidence_audit = audit_evidence_chain(context, candidate)
    base_components = {
        "input_quality": context.input_quality.overall_confidence,
        **dict(confidence_components or {}),
        "evidence_chain": evidence_audit.confidence_limit,
    }
    base_confidence = aggregate_confidence(base_components)
    context_reasons = list(context.missing_fields)
    context_reasons.extend(context.input_quality.hard_failures)
    if context.actor_seat != context.hero_seat:
        context_reasons.append("hero_not_actor")
    context_reasons = list(dict.fromkeys(context_reasons))
    gates = [
        GateResult(
            "request_freshness",
            GateStatus.FAIL if now >= expires_at else GateStatus.PASS,
            ("expired_request",) if now >= expires_at else (),
        ),
        GateResult(
            "confidence_components",
            GateStatus.PASS if base_confidence.complete else GateStatus.FAIL,
            tuple(
                f"missing_confidence_component:{name}"
                for name in base_confidence.missing_components
            ),
        ),
        GateResult(
            "decision_context",
            GateStatus.PASS if context.is_decision_ready else GateStatus.FAIL,
            tuple(context_reasons) if not context.is_decision_ready else (),
        ),
        *external_gates,
    ]
    if candidate is not None:
        strategy_gate = GateResult(
            "strategy_source",
            GateStatus.FAIL if candidate_restrictions else GateStatus.PASS,
            candidate_restrictions,
        )
        probabilities, sizes, options, action_ev = legalize_candidate(
            context, candidate
        )
        legal_gate = GateResult(
            "legal_strategy_actions",
            GateStatus.PASS if probabilities else GateStatus.FAIL,
            () if probabilities else ("no_legal_strategy_actions",),
        )
    elif math_report:
        strategy_gate = GateResult("strategy_source", GateStatus.SKIPPED)
        legal_gate = GateResult("legal_strategy_actions", GateStatus.SKIPPED)
        probabilities, sizes, options, action_ev = {}, {}, (), {}
    else:
        strategy_gate = GateResult(
            "strategy_source",
            GateStatus.FAIL,
            route.reasons or ("no_strategy",),
        )
        legal_gate = GateResult("legal_strategy_actions", GateStatus.SKIPPED)
        probabilities, sizes, options, action_ev = {}, {}, (), {}
    gates.extend((strategy_gate, legal_gate))
    common = dict(
        hand_id=context.hand_id,
        state_version=context.state_version,
        request_id=context.request_id,
        player_count=context.game_config.dealt_player_count,
        active_player_count=len(context.active_seats),
        confidence=base_confidence.overall,
        confidence_factors=base_confidence.components,
        missing_confidence_factors=base_confidence.missing_components,
        assumptions=context.assumptions,
        evidence=evidence_audit.evidence_uris,
        input_provenance=context.input_provenance,
        evidence_chain_id=evidence_audit.chain_id,
        evidence_complete=evidence_audit.complete,
        missing_evidence=evidence_audit.missing,
        missing_inputs=context.missing_fields,
        math_report=math_report or {},
        gate_results=tuple(gates),
        expires_at=expires_at,
    )
    if now >= expires_at:
        return Advice(
            status=AdviceStatus.STALE,
            rejection_reasons=("expired_request",),
            **common,
        )
    if not base_confidence.complete:
        return Advice(
            status=AdviceStatus.ABSTAIN,
            rejection_reasons=tuple(
                f"missing_confidence_component:{name}"
                for name in base_confidence.missing_components
            ),
            **common,
        )
    if not context.is_decision_ready:
        return Advice(
            status=AdviceStatus.ABSTAIN,
            rejection_reasons=tuple(context_reasons),
            **common,
        )
    external_failures = tuple(
        reason
        for gate in external_gates if gate.status is GateStatus.FAIL
        for reason in gate.reasons
    )
    admission_failures = external_failures + candidate_restrictions
    if admission_failures:
        return Advice(
            status=AdviceStatus.ABSTAIN,
            rejection_reasons=tuple(dict.fromkeys(admission_failures)),
            **common,
        )
    if candidate is None:
        if math_report:
            return Advice(
                status=AdviceStatus.PARTIAL,
                match_kind=MatchKind.EQUITY_ONLY,
                rejection_reasons=route.reasons,
                **common,
            )
        return Advice(
            status=AdviceStatus.ABSTAIN,
            rejection_reasons=route.reasons or ("no_strategy",),
            **common,
        )
    if not probabilities:
        return Advice(
            status=AdviceStatus.ABSTAIN,
            rejection_reasons=("no_legal_strategy_actions",),
            **common,
        )
    preferred = max(
        probabilities,
        key=lambda action: (probabilities[action], action.value),
    )
    gap_result = calculate_ev_gap(
        tuple(action.action for action in context.legal_actions), action_ev
    )
    ev_gap = gap_result.gap if gap_result.complete else None
    candidate_expiry = candidate.expires_at
    if candidate_expiry is not None and candidate_expiry < expires_at:
        common["expires_at"] = candidate_expiry
    ready_confidence = aggregate_confidence({
        **base_components,
        "provider": candidate.confidence,
        "state_match": candidate.state_match_score,
    })
    return Advice(
        status=AdviceStatus.READY,
        action_probabilities=probabilities,
        recommended_sizes=sizes,
        action_options=options,
        action_ev=action_ev,
        ev_gap=ev_gap,
        preferred_action=preferred,
        strategy_source=candidate.provider_id,
        strategy_version=candidate.provider_version,
        match_kind=candidate.match_kind,
        state_match_score=candidate.state_match_score,
        match_dimensions=candidate.match_dimensions,
        confidence=ready_confidence.overall,
        confidence_factors=ready_confidence.components,
        missing_confidence_factors=ready_confidence.missing_components,
        assumptions=tuple(dict.fromkeys(
            context.assumptions
            + candidate.assumptions
            + (() if evidence_audit.complete else ("evidence_chain_incomplete",))
        )),
        **{key: value for key, value in common.items()
           if key not in (
               "confidence", "confidence_factors",
               "missing_confidence_factors", "assumptions",
           )},
    )


def mark_stale(
    advice: Advice,
    *,
    reason: str = "stale_context",
    now: datetime | None = None,
) -> Advice:
    if not isinstance(advice, Advice):
        raise TypeError("advice must be an Advice")
    if not isinstance(reason, str) or not reason:
        raise ValueError("reason must be a non-empty str")
    now = now or utc_now()
    _require_aware_dt(now)
    return Advice(
        hand_id=advice.hand_id,
        state_version=advice.state_version,
        request_id=advice.request_id,
        player_count=advice.player_count,
        active_player_count=advice.active_player_count,
        status=AdviceStatus.STALE,
        math_report=advice.math_report,
        strategy_source=advice.strategy_source,
        strategy_version=advice.strategy_version,
        match_kind=advice.match_kind,
        state_match_score=advice.state_match_score,
        match_dimensions=advice.match_dimensions,
        confidence=advice.confidence,
        confidence_factors=advice.confidence_factors,
        missing_confidence_factors=advice.missing_confidence_factors,
        evidence=advice.evidence,
        input_provenance=advice.input_provenance,
        evidence_chain_id=advice.evidence_chain_id,
        evidence_complete=advice.evidence_complete,
        missing_evidence=advice.missing_evidence,
        assumptions=advice.assumptions,
        missing_inputs=advice.missing_inputs,
        rejection_reasons=(reason,),
        gate_results=advice.gate_results,
        expires_at=min(advice.expires_at, now),
    )


def _expiry(request: RequestContext, now: datetime) -> datetime:
    if request.expires_at is not None:
        return request.expires_at
    return request.requested_at + timedelta(
        milliseconds=request.deadline_ms or 300
    )


def _context_evidence(context: DecisionContext) -> tuple[str, ...]:
    return tuple(item.evidence_ref for item in context.input_provenance)


def _candidate_evidence(
    context: DecisionContext,
    candidate: StrategyCandidate,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_context_evidence(context) + candidate.evidence))


__all__ = [
    "Advice",
    "AdviceStatus",
    "build_advice",
    "legalize_candidate",
    "mark_stale",
]
