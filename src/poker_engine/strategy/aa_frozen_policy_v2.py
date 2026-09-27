"""Versioned V2 synthetic research lookup; no live strategy admission."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import random
import re

from .aa_frozen_policy import canonical_hash, validate_distribution
from .aa_policy_encoding_v2 import (
    ABSTRACTION_DISCLOSURE, ENCODER_VERSION_V2, encode_decision_v2, exact_money,
    information_key_v2, validated_menu_v2,
)


POLICY_KIND_V2 = "AA_FROZEN_POLICY_V2"
_HEX64 = re.compile(r"[0-9a-fA-F]{64}\Z")


def _hex64(value):
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def make_policy_v2(*, rules_fingerprint, table_size, stack_depth_bb,
                   policy, training):
    document = {
        "schema_version": 2, "kind": POLICY_KIND_V2, "status": "research_only",
        "rules_fingerprint": rules_fingerprint, "table_size": table_size,
        "stack_depth_bb": exact_money(stack_depth_bb), "encoder": ENCODER_VERSION_V2,
        "policy": deepcopy(policy), "training": deepcopy(training),
        "strategy_eligible": False, "advice_emitted": False,
        "abstraction": ABSTRACTION_DISCLOSURE, "unknown_history": "ABSTAIN",
        "live_admission": "NOT_IMPLEMENTED",
    }
    document["sha256"] = canonical_hash(document)
    FrozenResearchPolicyV2(document)
    return document


class FrozenResearchPolicyV2:
    """Strict scope-bound lookup. A policy digest is not evidence of strength."""

    def __init__(self, document):
        if not isinstance(document, dict):
            raise ValueError("invalid_policy_document")
        data = deepcopy(document)
        checksum = data.pop("sha256", None)
        if checksum != canonical_hash(data):
            raise ValueError("policy_digest_mismatch")
        if (data.get("schema_version") != 2 or data.get("kind") != POLICY_KIND_V2
                or data.get("status") != "research_only"
                or data.get("encoder") != ENCODER_VERSION_V2
                or type(data.get("table_size")) is not int
                or data.get("table_size") not in (6, 7, 8)
                or not _hex64(data.get("rules_fingerprint"))
                or data.get("strategy_eligible") is not False
                or data.get("advice_emitted") is not False
                or data.get("live_admission") != "NOT_IMPLEMENTED"
                or data.get("unknown_history") != "ABSTAIN"
                or data.get("abstraction") != ABSTRACTION_DISCLOSURE):
            raise ValueError("unsupported_or_promoted_research_policy")
        if not isinstance(data.get("policy"), dict):
            raise ValueError("invalid_policy_table")
        try:
            depth = Decimal(data["stack_depth_bb"])
            if not depth.is_finite() or depth <= 0:
                raise ValueError("invalid_policy_depth")
        except (InvalidOperation, TypeError, KeyError) as exc:
            raise ValueError("invalid_policy_depth") from exc
        for key, dist in data["policy"].items():
            if not _hex64(key):
                raise ValueError("invalid_information_key")
            if not isinstance(dist, dict) or not dist:
                raise ValueError("invalid_policy_distribution")
            for action in dist:
                if action not in ("fold", "check_call"):
                    if (not isinstance(action, str)
                            or not action.startswith("raise_to:")):
                        raise ValueError("invalid_policy_action")
                    amount = action[len("raise_to:"):]
                    if exact_money(amount) != amount or Decimal(amount) <= 0:
                        raise ValueError("invalid_policy_action")
            validate_distribution(dist, tuple(dist))
        self._data, self.sha256 = data, checksum

    def _check_scope(self, observation):
        if (not isinstance(observation, dict)
                or observation.get("rules_fingerprint")
                != self._data["rules_fingerprint"]
                or observation.get("table_size") != self._data["table_size"]):
            raise ValueError("policy_rule_scope_mismatch")
        try:
            expected = (Fraction(self._data["stack_depth_bb"])
                        * Fraction(exact_money(observation["big_blind"])))
            initial = observation["starting_stacks"]
            if (set(initial) != {str(s) for s in observation["occupied_seats"]}
                    or expected <= 0
                    or any(Fraction(exact_money(v)) != expected
                           for v in initial.values())):
                raise ValueError("policy_stack_scope_mismatch")
        except (KeyError, TypeError, InvalidOperation, ZeroDivisionError) as exc:
            raise ValueError("policy_stack_scope_mismatch") from exc

    def inspect_lookup(self, observation):
        """Return detached evidence, preserving misses instead of inventing moves."""
        report = {
            "policy_version": POLICY_KIND_V2, "policy_sha256": self.sha256,
            "encoder": ENCODER_VERSION_V2, "status": None, "distribution": None,
            "encoder_version": ENCODER_VERSION_V2, "information_key": None,
            "exact_key": None, "abstract_key": None, "features": None,
            "strategy_eligible": False, "advice_emitted": False,
        }
        try:
            self._check_scope(observation)
        except ValueError as exc:
            report.update(status="SCOPE_MISMATCH", reason=str(exc))
            return report
        try:
            menu = validated_menu_v2(observation)
        except ValueError as exc:
            report.update(status="INVALID_MENU", reason=str(exc))
            return report
        try:
            encoded = encode_decision_v2(observation)
        except ValueError as exc:
            report.update(status="INVALID_OBSERVATION", reason=str(exc))
            return report
        report.update({key: encoded[key] for key in ("exact_key", "abstract_key",
                                                     "features")})
        report["information_key"] = encoded["abstract_key"]
        dist = self._data["policy"].get(encoded["abstract_key"])
        if dist is None:
            report.update(status="UNKNOWN_INFORMATION_SET",
                          reason="unknown_policy_information_set")
            return report
        try:
            validate_distribution(dist, tuple(row["id"] for row in menu))
        except ValueError as exc:
            report.update(status="INVALID_MENU", reason=str(exc))
            return report
        report.update(status="HIT", reason=None, distribution=dict(dist))
        return report

    def distribution(self, observation):
        result = self.inspect_lookup(observation)
        if result["status"] in ("HIT", "UNKNOWN_INFORMATION_SET"):
            return result["distribution"]
        raise ValueError(result["reason"])

    def sample(self, observation, rng: random.Random):
        distribution = self.distribution(observation)
        if distribution is None:
            return None
        actions = sorted(distribution)
        weights = [distribution[action] for action in actions]
        return rng.choices(actions, weights, k=1)[0]

    def require_live(self):
        raise ValueError("research_policy_has_no_live_admission")

    def frozen_map(self):
        return deepcopy(self._data["policy"])

    def __call__(self, observation):
        raise ValueError("frozen_mixture_requires_independent_evaluation_salt")

    def for_game(self, salt):
        if not _hex64(salt) or salt != salt.lower():
            raise ValueError("independent_policy_salt_required")

        def decide(observation):
            key = information_key_v2(observation)
            seed = int(canonical_hash({"salt": salt, "policy": self.sha256,
                                       "information": key}), 16)
            choice = self.sample(observation, random.Random(seed))
            if choice is None:
                raise ValueError("unknown_policy_information_set")
            return choice
        return decide
