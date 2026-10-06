"""Monotonic AA turn deadlines and an intentionally closed live-policy gate.

Timing evidence must come from a separately validated source adapter. Merely
seeing Hero, completing recognition, or refreshing a request is not onset proof.
This module never promotes an observation or an offline policy to live advice.
"""

from dataclasses import dataclass
import math


def _seconds(value, name):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError(f"{name} must be finite nonnegative seconds")
    return float(value)


@dataclass(frozen=True)
class TurnIdentity:
    instance_id: str
    generation: int
    hand_id: str
    turn_id: str

    def __post_init__(self):
        if (any(not isinstance(value, str) or not value for value in (
                self.instance_id, self.hand_id, self.turn_id))
                or type(self.generation) is not int or self.generation < 0):
            raise ValueError("complete turn identity required")


@dataclass(frozen=True)
class TurnEvidence:
    """Explicit onset or lower-bound countdown, in the host monotonic domain.

    The producer owns validation and physical-to-host time mapping. Countdown
    must be a conservative lower bound, never an unadjusted rounded display.
    No browser endpoint accepts this object and the AA reader does not emit it.
    """

    evidence_id: str
    kind: str
    observed_at: float
    remaining_seconds: float

    def __post_init__(self):
        if not isinstance(self.evidence_id, str) or not self.evidence_id:
            raise ValueError("timing evidence identity required")
        if self.kind not in {"verified_onset", "verified_countdown_lower_bound"}:
            raise ValueError("verified timing evidence kind required")
        _seconds(self.observed_at, "observed_at")
        _seconds(self.remaining_seconds, "remaining_seconds")
        if self.remaining_seconds > 10 or (
                self.kind == "verified_onset" and self.remaining_seconds != 10):
            raise ValueError("timing evidence exceeds ten-second window")


class AATurnWindow:
    """One turn; state corrections and retries cannot extend its deadline."""

    def __init__(self, identity, evidence, *, now, source_max_age=1.0):
        if (not isinstance(identity, TurnIdentity)
                or not isinstance(evidence, TurnEvidence)):
            raise ValueError("identity and explicit timing evidence required")
        now = _seconds(now, "now")
        if evidence.observed_at > now:
            raise ValueError("future turn evidence")
        self.identity = identity
        self.evidence_id = evidence.evidence_id
        self.evidence_kind = evidence.kind
        self.deadline = evidence.observed_at + evidence.remaining_seconds
        # Countdown joins retain elapsed time: six seconds left means the
        # first-result deadline already passed, not a new two-second allowance.
        self.first_result_deadline = self.deadline - 8.0
        self.source_max_age = _seconds(source_max_age, "source_max_age")
        if not self.source_max_age:
            raise ValueError("source_max_age must be positive")
        self._last_now = now
        self._invalid_reason = None
        self._first_result_at = None

    def _now(self, now):
        now = _seconds(now, "now")
        if now < self._last_now:
            self.invalidate("CLOCK_REGRESSION")
        self._last_now = max(now, self._last_now)
        return self._last_now

    def invalidate(self, reason):
        self._invalid_reason = self._invalid_reason or reason

    def tighten(self, evidence, *, now):
        """Further countdown evidence may shorten a turn, never restart it."""
        now = self._now(now)
        if not isinstance(evidence, TurnEvidence) or evidence.observed_at > now:
            self.invalidate("INVALID_TURN_EVIDENCE")
            return
        self.deadline = min(self.deadline,
                            evidence.observed_at + evidence.remaining_seconds)
        self.first_result_deadline = min(self.first_result_deadline,
                                         self.deadline - 8.0)

    def check(self, *, now, identity, source_at, state_matches=True,
              legal=True, for_new_result=True):
        now = self._now(now)
        if identity != self.identity:
            self.invalidate("TURN_IDENTITY_CHANGED")
        if self._invalid_reason:
            return self._invalid_reason
        if not state_matches:
            return "STATE_CHANGED"
        if not legal:
            return "ILLEGAL_ACTION"
        if source_at is None:
            return "SOURCE_TIME_UNKNOWN"
        source_at = _seconds(source_at, "source_at")
        if source_at > now:
            return "SOURCE_TIME_INVALID"
        if now - source_at >= self.source_max_age:
            return "SOURCE_STALE"
        if now >= self.deadline:
            return "TURN_EXPIRED"
        if now >= self.deadline - 3.0:
            return "OPERATION_RESERVE"
        if (for_new_result and self._first_result_at is None
                and now >= self.first_result_deadline):
            return "FIRST_RESULT_DEADLINE"
        return "WITHIN_BUDGET"

    def record_first_result(self, *, now, identity, source_at,
                            state_matches=True, legal=True):
        reason = self.check(now=now, identity=identity, source_at=source_at,
                            state_matches=state_matches, legal=legal)
        if reason == "WITHIN_BUDGET" and self._first_result_at is None:
            self._first_result_at = now
        return reason

    def computation_budget_seconds(self, *, now, identity, source_at):
        if self.check(now=now, identity=identity,
                      source_at=source_at) != "WITHIN_BUDGET":
            return 0.0
        limit = min(self.deadline - 3.0, source_at + self.source_max_age)
        if self._first_result_at is None:
            limit = min(limit, self.first_result_deadline)
        return max(0.0, min(0.3, limit - now))


def observation_runtime_status(snapshot, *, now):
    """Real status endpoint gate: no approved timing adapter or live policy.

    Deliberately ignores payload-supplied deadline/advice fields. A recognized
    actor and a local host receipt cannot prove remaining physical turn time.
    """
    now = _seconds(now, "now")
    timing = snapshot.get("timing") or {}
    source_at = timing.get("host_source_started_at")
    source_age = None if source_at is None else max(0.0, now - source_at)
    running = snapshot.get("status") == "RUNNING" and bool(snapshot.get("payload"))
    if not running:
        reason = "NO_CURRENT_OBSERVATION"
    elif source_age is None:
        reason = "SOURCE_TIME_UNKNOWN"
    elif source_age >= 1.0:
        reason = "SOURCE_STALE"
    else:
        reason = "NO_VERIFIED_TURN_EVIDENCE"
    return {
        "schema_version": 1, "mode": "OBSERVATION_ONLY",
        "status": "ABSTAIN", "reason": reason,
        "blockers": [reason, "NO_QUALIFIED_LIVE_POLICY"],
        "strategy_eligible": False, "advice_emitted": False, "advice": None,
        "identity": {"instance_id": snapshot.get("instance_id"),
                     "generation": snapshot.get("generation"),
                     "sequence": snapshot.get("sequence")},
        "turn_id": None, "turn_evidence": None, "action_deadline": None,
        "remaining_ms": None, "source_host_age_ms": (
            None if source_age is None else source_age * 1000),
        "physical_source_age_ms": None, "end_to_end_latency_ms": None,
        "status_ttl_ms": 500, "advice_ttl_ms": 0,
        "limits": {"turn_ms": 10000, "first_result_ms": 2000,
                   "computation_ms": 300, "operation_reserve_ms": 3000,
                   "source_max_age_ms": 1000},
    }
