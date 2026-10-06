"""Rule-bound concrete-combo priors and action likelihoods for AA shadow use."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType

from poker_engine.core.enums import Position
from poker_engine.core.errors import InvalidStateError
from poker_engine.core.value_objects import Card

from .contracts import PotState, RangeDistribution
from .range_tracker import (
    RangeUpdate,
    bayesian_action_update,
    filter_blocked_combos,
    parse_concrete_combo,
)


_STATUS = {"test_only", "simulation_only", "shadow_reviewed", "live_approved"}
_ACTIONS = {"fold", "check", "call", "aggressive", "all_in"}


def _sha(value, name):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be SHA-256") from exc
    if value != value.lower():
        raise ValueError(f"{name} must be lowercase SHA-256")
    return value


def _identity_token(value):
    return (isinstance(value, str) and bool(value)
            and value == value.strip() and ":" not in value and "@" not in value)


def parse_range_identity(source_version):
    """Read only the fixed asset header, never identity text in a suffix."""
    if not isinstance(source_version, str):
        return None
    parts = source_version.split(":")
    if len(parts) < 5 or parts[0] != "aa-ranges-v2":
        return None
    fingerprint, status, asset_id, version_hash = parts[1:5]
    version, separator, digest = version_hash.partition("@")
    if (status not in _STATUS or not _identity_token(asset_id)
            or not separator or not _identity_token(version)):
        return None
    if any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
           for value in (fingerprint, digest)):
        return None
    return fingerprint, status, asset_id, version, digest


def is_explicitly_unbound_range(distribution, rule_fingerprint):
    """Recognize a synthetic-only declaration, not a failed asset parse."""
    parts = distribution.source_version.split(":", 3)
    return (distribution.source == "unbound" and len(parts) == 4
            and parts[:3] == ["aa-ranges-v2", rule_fingerprint, "unbound"]
            and _identity_token(parts[3]))


def _probability(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be exact decimal string")
    result = Decimal(value)
    if not result.is_finite() or not Decimal("0") <= result <= 1:
        raise ValueError(f"{name} must be in [0,1]")
    return result


def _combo_rows(rows, *, probability_name, require_sum=False):
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{probability_name} rows must be non-empty list")
    result = {}
    holdings = set()
    previous = None
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"combo", probability_name}:
            raise ValueError(f"invalid {probability_name} row")
        combo = row["combo"]
        cards = parse_concrete_combo(combo)
        identity = frozenset(cards)
        if combo in result or identity in holdings:
            raise ValueError("duplicate concrete holding or reversed combo")
        if previous is not None and combo <= previous:
            raise ValueError("concrete combo rows must be sorted")
        previous = combo
        holdings.add(identity)
        result[combo] = _probability(row[probability_name], probability_name)
    if require_sum and sum(result.values(), Decimal("0")) != 1:
        raise ValueError("prior weights must sum exactly to 1")
    return MappingProxyType(result)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class AARangeNodeV2:
    node_id: str
    player_count: int
    position: Position
    stack_bb: Decimal
    action_line: str
    prior: MappingProxyType
    action_likelihoods: MappingProxyType
    confidence: float
    effective_sample_size: int
    evidence: tuple[str, ...]


class AARangeLookupState(str, Enum):
    HIT = "HIT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AARangeLookupV2:
    state: AARangeLookupState
    distribution: RangeDistribution | None = None
    node_id: str | None = None
    reasons: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.state, AARangeLookupState):
            raise TypeError("state must be AARangeLookupState")
        if (self.state is AARangeLookupState.HIT) != (
            self.distribution is not None
        ):
            raise ValueError("HIT must match distribution presence")
        if self.node_id is not None and (
            not isinstance(self.node_id, str) or not self.node_id
        ):
            raise ValueError("node_id must be non-empty or None")
        for name in ("reasons", "evidence"):
            values = tuple(getattr(self, name))
            if not all(isinstance(value, str) and value for value in values):
                raise TypeError(f"{name} must contain non-empty strings")
            object.__setattr__(self, name, values)


@dataclass(frozen=True)
class AARangeQueryV2:
    seat_id: int
    player_count: int
    position: Position
    stack_bb: Decimal
    action_line: str
    known_cards: tuple[Card, ...] = ()

    def __post_init__(self):
        if type(self.seat_id) is not int or not 0 <= self.seat_id < 8:
            raise ValueError("seat_id must be an AA physical seat")
        if type(self.player_count) is not int or self.player_count not in (6, 7, 8):
            raise ValueError("player_count must be 6,7,8")
        if not isinstance(self.position, Position) or self.position is Position.UNKNOWN:
            raise ValueError("position must be known")
        if not isinstance(self.stack_bb, Decimal) or not self.stack_bb.is_finite():
            raise ValueError("stack_bb must be finite Decimal")
        if (self.stack_bb < 0 or not isinstance(self.action_line, str)
                or not self.action_line):
            raise ValueError("invalid stack/action line")
        cards = tuple(self.known_cards)
        if (len(cards) != len(set(cards))
                or not all(isinstance(card, Card) for card in cards)):
            raise ValueError("known_cards must be distinct Cards")
        object.__setattr__(self, "known_cards", cards)


class AAConcreteRangeAssetV2:
    def __init__(self, path, *, expected_sha256, expected_rule_fingerprint):
        self.path = Path(path)
        raw = self.path.read_bytes()
        self.asset_sha256 = hashlib.sha256(raw).hexdigest()
        if self.asset_sha256 != _sha(expected_sha256, "expected_sha256"):
            raise ValueError("AA range asset SHA-256 mismatch")
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        required = {
            "schema_version", "asset_id", "asset_version", "asset_status",
            "rule_fingerprint", "source", "limitations", "nodes",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError("AA range asset requires exact schema fields")
        if payload["schema_version"] != 2:
            raise ValueError("unsupported AA range asset schema")
        self.rule_fingerprint = _sha(payload["rule_fingerprint"], "rule_fingerprint")
        if self.rule_fingerprint != _sha(
            expected_rule_fingerprint, "expected_rule_fingerprint"
        ):
            raise ValueError("AA range asset rule fingerprint mismatch")
        for name in ("asset_id", "asset_version"):
            if not _identity_token(payload[name]):
                raise ValueError(f"{name} must be a non-empty identity token")
        if payload["asset_status"] not in _STATUS:
            raise ValueError("invalid range asset status")
        source = payload["source"]
        if (not isinstance(source, dict)
                or set(source) != {"url", "revision", "license_spdx"}
                or any(not isinstance(value, str) or not value
                       for value in source.values())):
            raise ValueError("invalid range asset source")
        limitations = payload["limitations"]
        if not isinstance(limitations, list) or not limitations or not all(
            isinstance(value, str) and value for value in limitations
        ):
            raise ValueError("range asset limitations required")
        self.asset_id = payload["asset_id"]
        self.asset_version = payload["asset_version"]
        self.asset_status = payload["asset_status"]
        self.source = MappingProxyType(dict(source))
        self.limitations = tuple(limitations)
        self.nodes = self._nodes(payload["nodes"])

    def _nodes(self, rows):
        if not isinstance(rows, list) or not rows:
            raise ValueError("range asset nodes must be non-empty list")
        nodes = []
        identities = set()
        for row in rows:
            required = {
                "node_id", "player_count", "position", "stack_bb", "action_line",
                "prior", "action_likelihoods", "confidence",
                "effective_sample_size", "evidence",
            }
            if not isinstance(row, dict) or set(row) != required:
                raise ValueError("range node requires exact fields")
            position = Position(row["position"])
            stack = Decimal(row["stack_bb"])
            if (not isinstance(row["node_id"], str) or not row["node_id"]
                    or type(row["player_count"]) is not int
                    or row["player_count"] not in (6, 7, 8)
                    or position is Position.UNKNOWN
                    or not stack.is_finite() or stack < 0
                    or not isinstance(row["action_line"], str)
                    or not row["action_line"]):
                raise ValueError("invalid range node dimensions")
            identity = (
                row["player_count"], position, stack, row["action_line"],
            )
            if identity in identities:
                raise ValueError("duplicate AA range node dimensions")
            identities.add(identity)
            prior = _combo_rows(
                row["prior"], probability_name="weight", require_sum=True
            )
            likelihoods = {}
            raw_likelihoods = row["action_likelihoods"]
            if not isinstance(raw_likelihoods, dict) or set(
                raw_likelihoods
            ) - _ACTIONS:
                raise ValueError("invalid action likelihood names")
            for action, values in raw_likelihoods.items():
                parsed = _combo_rows(values, probability_name="likelihood")
                if set(parsed) - set(prior):
                    raise ValueError("likelihood combo absent from prior")
                likelihoods[action] = parsed
            confidence = row["confidence"]
            sample = row["effective_sample_size"]
            evidence = row["evidence"]
            if (not isinstance(confidence, (int, float))
                    or isinstance(confidence, bool)
                    or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                raise ValueError("invalid range node confidence")
            if type(sample) is not int or sample < 0:
                raise ValueError("invalid range node sample size")
            if not isinstance(evidence, list) or not evidence or not all(
                isinstance(value, str) and value for value in evidence
            ):
                raise ValueError("range node evidence required")
            nodes.append(AARangeNodeV2(
                row["node_id"], row["player_count"], position, stack,
                row["action_line"], prior, MappingProxyType(likelihoods),
                float(confidence), sample, tuple(evidence),
            ))
        return tuple(nodes)

    @property
    def shadow_permitted(self):
        return self.asset_status in ("shadow_reviewed", "live_approved")

    def _node(self, query):
        matches = [
            node for node in self.nodes
            if (node.player_count, node.position, node.stack_bb, node.action_line) == (
                query.player_count, query.position, query.stack_bb,
                query.action_line,
            )
        ]
        return matches[0] if len(matches) == 1 else None

    def lookup(self, query):
        if not isinstance(query, AARangeQueryV2):
            raise TypeError("query must be AARangeQueryV2")
        if not self.shadow_permitted:
            return AARangeLookupV2(
                AARangeLookupState.NOT_APPLICABLE,
                reasons=("range_asset_not_shadow_reviewed",),
            )
        node = self._node(query)
        if node is None:
            return AARangeLookupV2(
                AARangeLookupState.NOT_APPLICABLE,
                reasons=("exact_range_node_not_found",),
            )
        unit_source = (
            f"aa-ranges-v2:{self.rule_fingerprint}:{self.asset_status}:{self.asset_id}:"
            f"{self.asset_version}@{self.asset_sha256}"
        )
        distribution = RangeDistribution(
            query.seat_id, node.prior, self.asset_id, unit_source,
            entropy=Decimal(str(-sum(
                float(weight) * math.log(float(weight))
                for weight in node.prior.values() if weight > 0
            ))),
            effective_sample_size=node.effective_sample_size,
            confidence=node.confidence,
        )
        try:
            distribution = filter_blocked_combos(
                distribution, query.known_cards,
                source_version=unit_source + ":blockers",
            )
        except (InvalidStateError, ValueError) as exc:
            return AARangeLookupV2(
                AARangeLookupState.UNKNOWN, node_id=node.node_id,
                reasons=(f"range_blocker_failure:{exc}",),
            )
        return AARangeLookupV2(
            AARangeLookupState.HIT, distribution, node.node_id,
            evidence=(
                f"{self.source['url']}/tree/{self.source['revision']}",
                f"range_asset_sha256:{self.asset_sha256}",
                f"range_node:{node.node_id}",
                *node.evidence,
            ),
        )

    def update(self, prior, query, action):
        if not isinstance(prior, RangeDistribution):
            raise TypeError("prior must be RangeDistribution")
        if not isinstance(query, AARangeQueryV2):
            raise TypeError("query must be AARangeQueryV2")
        expected = (self.rule_fingerprint, self.asset_status, self.asset_id,
                    self.asset_version, self.asset_sha256)
        if (prior.seat_id != query.seat_id
                or prior.source != self.asset_id
                or parse_range_identity(prior.source_version) != expected):
            raise ValueError("prior is not bound to query and AA range asset")
        if action not in _ACTIONS:
            raise ValueError("unsupported observed action")
        node = self._node(query)
        if node is None or action not in node.action_likelihoods:
            return RangeUpdate(prior, False, Decimal("0"), tuple(
                sorted(prior.combo_weights)
            ))
        values = {
            combo: value for combo, value in node.action_likelihoods[action].items()
            if combo in prior.combo_weights
        }
        return bayesian_action_update(
            prior, values,
            source_version=prior.source_version + f":action/{action}",
        )


@dataclass(frozen=True)
class AARangeReadinessV2:
    permitted: bool
    reasons: tuple[str, ...]
    required_seats: tuple[int, ...]
    supplied_seats: tuple[int, ...]
    minimum_confidence: float | None
    cartesian_combinations: int


@dataclass(frozen=True)
class AARangeShadowSnapshotV2:
    version: int
    distributions: tuple[RangeDistribution, ...]
    blockers: tuple[str, ...]
    events: tuple[MappingProxyType, ...]
    readiness: AARangeReadinessV2
    equity_permitted: bool
    advice_emitted: bool = False
    strategy_eligible: bool = False
    # Old positional constructors remain valid, but incomplete identity does
    # not authorize equity. The tracker supplies all five bound fields.
    asset_id: str | None = None
    asset_version: str | None = None
    asset_sha256: str | None = None
    asset_status: str | None = None
    rule_fingerprint: str | None = None


class AARangeShadowTrackerV2:
    """Per-hand range state; missing action likelihoods taint equity readiness."""

    def __init__(self, asset, *, minimum_likelihood_coverage=Decimal("0.80")):
        if not isinstance(asset, AAConcreteRangeAssetV2):
            raise TypeError("asset must be AAConcreteRangeAssetV2")
        if (not isinstance(minimum_likelihood_coverage, Decimal)
                or not minimum_likelihood_coverage.is_finite()
                or not Decimal("0") <= minimum_likelihood_coverage <= 1):
            raise ValueError("minimum_likelihood_coverage must be Decimal in [0,1]")
        self.asset = asset
        self.minimum_likelihood_coverage = minimum_likelihood_coverage
        self.queries = {}
        self.distributions = {}
        self.blockers = []
        self.events = []
        self.version = 0
        self.last_frame = None

    def seed(self, queries):
        values = tuple(queries)
        if not values or len({query.seat_id for query in values}) != len(values):
            raise ValueError("seed queries must have unique seats")
        self.queries = {}
        self.distributions = {}
        self.blockers = []
        self.events = []
        self.version = 0
        self.last_frame = None
        for query in values:
            result = self.asset.lookup(query)
            if result.state is not AARangeLookupState.HIT:
                self.blockers.extend(
                    f"range_seed_failed:{query.seat_id}:{reason}"
                    for reason in result.reasons
                )
                continue
            self.queries[query.seat_id] = query
            self.distributions[query.seat_id] = result.distribution
        self.version = 1
        return tuple(dict.fromkeys(self.blockers))

    def observe_action(self, frame, seat, action, *, known_cards=()):
        if (type(frame) is not int or frame < 0
                or self.last_frame is not None and frame <= self.last_frame):
            raise ValueError("range action frames must be strictly increasing")
        self.last_frame = frame
        if seat not in self.distributions or seat not in self.queries:
            reason = f"range_action_without_seed:{seat}"
            self.blockers.append(reason)
            event = MappingProxyType({
                "frame": frame, "seat": seat, "action": action,
                "applied": False, "blocker": reason,
            })
            self.events.append(event)
            self.version += 1
            return event
        prior = self.distributions[seat]
        try:
            prior = filter_blocked_combos(
                prior, tuple(known_cards),
                source_version=prior.source_version + f":frame/{frame}/blockers",
            )
            update = self.asset.update(prior, self.queries[seat], action)
        except (InvalidStateError, TypeError, ValueError) as exc:
            reason = f"range_update_failed:{seat}:{exc}"
            self.blockers.append(reason)
            event = MappingProxyType({
                "frame": frame, "seat": seat, "action": action,
                "applied": False, "blocker": reason,
            })
            self.events.append(event)
            self.version += 1
            return event
        self.distributions[seat] = update.distribution
        blocker = None
        if not update.applied:
            blocker = f"range_action_likelihood_missing:{seat}:{action}"
        elif update.likelihood_coverage < self.minimum_likelihood_coverage:
            blocker = f"range_action_likelihood_coverage_low:{seat}:{action}"
        if blocker:
            self.blockers.append(blocker)
        self.version += 1
        event = MappingProxyType({
            "frame": frame,
            "seat": seat,
            "action": action,
            "applied": update.applied,
            "likelihood_coverage": str(update.likelihood_coverage),
            "missing_combo_count": len(update.missing_likelihood_combos),
            "confidence": update.distribution.confidence,
            "source_version": update.distribution.source_version,
            "blocker": blocker,
        })
        self.events.append(event)
        return event

    def snapshot(self, *, hero_seat, pots, minimum_confidence=.25):
        distributions = tuple(
            self.distributions[seat] for seat in sorted(self.distributions)
        )
        readiness = assess_aa_range_readiness(
            distributions,
            hero_seat=hero_seat,
            pots=pots,
            rule_fingerprint=self.asset.rule_fingerprint,
            minimum_confidence=minimum_confidence,
        )
        blockers = tuple(dict.fromkeys(self.blockers + list(readiness.reasons)))
        return AARangeShadowSnapshotV2(
            self.version, distributions, blockers, tuple(self.events), readiness,
            not blockers, advice_emitted=False, strategy_eligible=False,
            asset_id=self.asset.asset_id, asset_version=self.asset.asset_version,
            asset_sha256=self.asset.asset_sha256,
            asset_status=self.asset.asset_status,
            rule_fingerprint=self.asset.rule_fingerprint,
        )


def assess_aa_range_readiness(
    ranges, *, hero_seat, pots, rule_fingerprint, minimum_confidence=.25,
):
    values = tuple(ranges)
    pots = tuple(pots)
    if not all(isinstance(item, RangeDistribution) for item in values):
        raise TypeError("ranges must contain RangeDistribution values")
    if not pots or not all(isinstance(item, PotState) for item in pots):
        raise TypeError("pots must contain PotState values")
    _sha(rule_fingerprint, "rule_fingerprint")
    if (not isinstance(minimum_confidence, (int, float))
            or isinstance(minimum_confidence, bool)
            or not math.isfinite(minimum_confidence)
            or not 0 <= minimum_confidence <= 1):
        raise ValueError("minimum_confidence must be in [0,1]")
    if len({item.seat_id for item in values}) != len(values):
        raise ValueError("villain ranges must have unique seats")
    required = tuple(sorted({
        seat for pot in pots for seat in pot.eligible_seats if seat != hero_seat
    }))
    supplied = tuple(sorted(item.seat_id for item in values))
    reasons = []
    if not values:
        reasons.append("villain_ranges_missing")
    if supplied != required:
        reasons.append("villain_range_seats_do_not_match_pot_eligibility")
    expected = f"aa-ranges-v2:{rule_fingerprint}:"
    if any(not item.source_version.startswith(expected) for item in values):
        reasons.append("villain_range_rule_fingerprint_mismatch")
    confidences = [item.confidence for item in values]
    minimum = min(confidences) if confidences else None
    if minimum is None or minimum < minimum_confidence:
        reasons.append("villain_range_confidence_below_threshold")
    if any(not item.combo_weights for item in values):
        reasons.append("villain_range_empty")
    cartesian = math.prod(len(item.combo_weights) for item in values) if values else 0
    return AARangeReadinessV2(
        not reasons, tuple(dict.fromkeys(reasons)), required, supplied,
        minimum, cartesian,
    )


__all__ = [
    "AAConcreteRangeAssetV2", "AARangeLookupState", "AARangeLookupV2",
    "AARangeNodeV2", "AARangeQueryV2", "AARangeReadinessV2",
    "AARangeShadowSnapshotV2", "AARangeShadowTrackerV2",
    "assess_aa_range_readiness",
    "parse_range_identity", "is_explicitly_unbound_range",
]
