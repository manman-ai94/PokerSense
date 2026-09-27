"""Offline local-model adapter over validated, decision-time public state.

The caller owns process isolation, model loading and the external deadline.
Scores are model option scores, not GTO frequencies or probabilities of winning.
This adapter has no live admission, training, fallback or input truncation.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
import time

from .aa_frozen_policy import canonical_hash
from .aa_policy_encoding_v2 import (
    ENCODER_VERSION_V2, encode_decision_v2, exact_money,
)
from .aa_rules_v2 import AARuleProfileV2


REQUEST_FORMAT = "aa-local-options-v1"
POLICY_KIND = "AA_EXTERNAL_LOCAL_RESEARCH_V1"
QUESTION = (
    "Choose one legal action for the acting player in this simulated no-limit "
    "Texas Hold'em cash hand. Maximize expected net chip return under the stated "
    "rules. Only this player's hole cards and public information are available. "
    "Money amounts are exact chips unless marked BB; rake_percent is a fraction "
    "(0.03 means 3%). raise_to is the total street contribution, not an increment. "
    "Physical seats are numbered 0-7. "
    "Board history is chronological. Return scores for every listed option."
)
_RULE_MONEY = (
    "small_blind", "big_blind", "ante", "straddle_amount", "rake_percent",
    "rake_cap_bb", "minimum_chip",
)
_RULE_ENUMS = (
    "ante_mode", "straddle_mode", "rake_application", "rake_rounding",
    "rake_distribution",
)


def select_action(scores, legal_ids):
    """Strict exact-menu argmax; equal scores follow the supplied menu order."""
    if (not isinstance(legal_ids, (list, tuple)) or not legal_ids
            or any(not isinstance(item, str) for item in legal_ids)
            or len(set(legal_ids)) != len(legal_ids)):
        raise ValueError("invalid_external_legal_menu")
    if not isinstance(scores, Mapping) or set(scores) != set(legal_ids):
        raise ValueError("external_scores_must_match_legal_menu")
    values = {}
    for key in legal_ids:
        value = scores[key]
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError("invalid_external_score")
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("invalid_external_score") from exc
        if not number.is_finite() or number < 0:
            raise ValueError("invalid_external_score")
        values[key] = number
    # Nonnegative scores have positive sum iff at least one is positive; no
    # floating-point overflow or rounded probability normalization is needed.
    if not any(value > 0 for value in values.values()):
        raise ValueError("external_scores_have_no_positive_mass")
    return max(legal_ids, key=values.__getitem__)


class ExternalLocalResearchPolicy:
    """One frozen model/rules contract with exact-state-bound decision caching.

    ``scorer(request)`` must be a pure, externally bounded callable returning an
    exact ``legal option id -> finite nonnegative score`` mapping. A supplied
    token counter must count the *complete rendered model input*, including all
    options and special tokens. Context excess is refused, never truncated.
    ``inspect_lookup`` performs validation only; INPUT_READY is not a model hit.
    """

    strategy_eligible = False
    advice_emitted = False
    live_admission = False

    def __init__(self, rules, scorer, *, model_id, model_revision,
                 request_format=REQUEST_FORMAT, context_token_limit=None,
                 token_counter=None):
        if not isinstance(rules, AARuleProfileV2):
            raise ValueError("typed_aa_rules_required")
        if rules.verification_status != "simulation":
            raise ValueError("external_policy_requires_simulation_rules")
        if (not callable(scorer)
                or not isinstance(model_id, str) or not model_id.strip()
                or not isinstance(model_revision, str) or not model_revision.strip()
                or request_format != REQUEST_FORMAT):
            raise ValueError("invalid_external_policy_identity")
        if context_token_limit is not None:
            if (type(context_token_limit) is not int or context_token_limit < 1
                    or not callable(token_counter)):
                raise ValueError("context_limit_requires_complete_token_counter")
        elif token_counter is not None:
            raise ValueError("token_counter_requires_context_limit")
        self._rules = rules
        self._scorer = scorer
        self._token_counter = token_counter
        self._identity = {
            "policy_version": POLICY_KIND, "model_id": model_id,
            "model_revision": model_revision, "request_format": request_format,
            "encoder_version": ENCODER_VERSION_V2,
            "rules_fingerprint": rules.fingerprint,
            "context_token_limit": context_token_limit,
            "selection": "argmax_ties_in_declared_menu_order",
            "strategy_eligible": False, "advice_emitted": False,
        }
        self._sha256 = canonical_hash(self._identity)
        self._cache = {}

    @property
    def sha256(self):
        return self._sha256

    @property
    def identity(self):
        return deepcopy(self._identity)

    def _prepare(self, observation):
        if (not isinstance(observation, dict)
                or observation.get("rules_fingerprint") != self._rules.fingerprint
                or observation.get("table_size") != self._rules.table_size):
            raise ValueError("external_policy_rule_scope_mismatch")
        if (observation.get("simulation_only") is not True
                or observation.get("strategy_eligible") is not False
                or observation.get("advice_emitted", False) is not False):
            raise ValueError("external_policy_requires_simulation_provenance")
        # The shared encoder recursively rejects known private/future/seed keys
        # and copies only typed, public decision fields into exact_view.
        encoded = encode_decision_v2(observation)
        try:
            supplied_rules = AARuleProfileV2.from_dict(observation["rules"])
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ValueError("external_policy_rule_scope_mismatch") from exc
        if supplied_rules.fingerprint != self._rules.fingerprint:
            raise ValueError("external_policy_rule_scope_mismatch")
        view = encoded["exact_view"]
        if view["big_blind"] != exact_money(self._rules.big_blind):
            raise ValueError("external_policy_rule_scope_mismatch")
        menu_by_id = {row["id"]: row for row in view["legal_actions"]}
        # V2 sorts menu rows for state identity; preserve the *declared* order
        # for ties and bind that order into our distinct decision cache key.
        menu = [menu_by_id[row["id"]] for row in observation["legal_actions"]]
        for row in menu:
            if row["kind"] != "raise_to":
                continue
            betting = view["betting"]
            if (not betting["can_raise"] or betting["min_raise_to"] is None
                    or betting["max_raise_to"] is None):
                raise ValueError("invalid_external_legal_menu")
            amount = Decimal(row["raise_to"])
            if (amount < Decimal(betting["min_raise_to"])
                    or amount > Decimal(betting["max_raise_to"])
                    or amount % self._rules.minimum_chip != 0):
                raise ValueError("invalid_external_legal_menu")
        public_rules = {name: exact_money(getattr(self._rules, name))
                        for name in _RULE_MONEY}
        public_rules.update({name: getattr(self._rules, name) for name in _RULE_ENUMS})
        public_rules["table_size"] = self._rules.table_size
        state = {key: deepcopy(value) for key, value in view.items()
                 if key not in ("rules_fingerprint", "legal_actions")}
        options = []
        for row in menu:
            text = ("Fold" if row["kind"] == "fold" else
                    "Check" if row["kind"] == "check_call" and
                    state["to_call"] == "0" else
                    "Call " + state["to_call"] + " chips" if
                    row["kind"] == "check_call" else
                    "Raise to " + row["raise_to"] + " chips total this street")
            options.append({"id": row["id"], "text": text})
        request = {"format": REQUEST_FORMAT, "question": QUESTION,
                   "state": state, "rules": public_rules, "options": options}
        if self._token_counter is not None:
            count = self._token_counter(deepcopy(request))
            if type(count) is not int or count < 0:
                raise ValueError("invalid_external_context_token_count")
            if count > self._identity["context_token_limit"]:
                raise ValueError("external_policy_context_overflow")
        key = canonical_hash({"identity": self.sha256,
                              "exact_key": encoded["exact_key"],
                              "menu_order": [row["id"] for row in menu]})
        return request, key, encoded["exact_key"]

    def prepare_request(self, observation):
        """Validated detached model request; no inference or hidden metadata."""
        return self._prepare(observation)[0]

    def inspect_lookup(self, observation):
        report = {"policy_version": POLICY_KIND, "policy_sha256": self.sha256,
                  "encoder_version": ENCODER_VERSION_V2,
                  "status": "INVALID_OBSERVATION", "information_key": None,
                  "strategy_eligible": False, "advice_emitted": False}
        try:
            _, key, exact = self._prepare(observation)
            report.update(status="INPUT_READY", information_key=key,
                          exact_key=exact, reason=None)
        except ValueError as exc:
            report["reason"] = str(exc)
        return report

    def inspect_decision(self, observation):
        """Prior measured inference/cache evidence, or None; never infers."""
        _, key, _ = self._prepare(observation)
        return deepcopy(self._cache.get(key))

    def __call__(self, observation):
        started = time.perf_counter()
        request, key, exact = self._prepare(observation)
        cached = self._cache.get(key)
        if cached is not None:
            cached["cache_hits"] += 1
            cached["last_cache_lookup_ms"] = (time.perf_counter() - started) * 1000
            return cached["action"]
        inference_started = time.perf_counter()
        scores = self._scorer(deepcopy(request))
        inference_ms = (time.perf_counter() - inference_started) * 1000
        legal_ids = tuple(option["id"] for option in request["options"])
        action = select_action(scores, legal_ids)
        self._cache[key] = {
            "action": action, "exact_key": exact,
            "first_inference_latency_ms": inference_ms,
            "first_decision_latency_ms": (time.perf_counter() - started) * 1000,
            "cache_hits": 0, "last_cache_lookup_ms": None,
            "strategy_eligible": False, "advice_emitted": False,
        }
        return action

    def for_game(self, salt):
        if not isinstance(salt, str) or re.fullmatch(r"[0-9a-f]{64}", salt) is None:
            raise ValueError("independent_policy_salt_required")
        # Deterministic argmax does not need randomness. Salt is accepted solely
        # for evaluator binding and never enters the model input or cache key.
        return self

    def require_live(self):
        raise ValueError("research_policy_has_no_live_admission")
