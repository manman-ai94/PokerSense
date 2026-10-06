"""Offline Jev request/receipt adapter. No HTTP client or live registration.

Transport must be explicitly supplied by an authorized offline caller. Recorded
response transports make experiments repeatable without paid inference. There
is no automatic retry, probability repair, hidden-information or Advice path.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import time

from .aa_frozen_policy import action_ids, canonical_hash, information_key


JEV_MODEL = "jev-1.13.0"


def synthetic_request(observation, *, provenance):
    if (provenance != "AA_ARENA_SYNTHETIC_V1"
            or observation.get("simulation_only") is not True
            or observation.get("strategy_eligible") is not False
            or observation.get("arena_version") != "aa-full-hand-arena-v1"):
        raise ValueError("jev_requires_explicit_synthetic_source")
    information_key(observation)  # same information boundary as local policies
    ids = action_ids(observation)
    keys = ("own_hole", "board", "street", "actor", "observing_seat",
            "occupied_seats", "dealer_seat", "stacks", "bets", "folded",
            "pot", "public_history", "legal_actions", "table_size", "big_blind",
            "starting_stacks", "rules", "rules_fingerprint", "straddler_seat",
            "to_call")
    state = {key: deepcopy(observation[key]) for key in keys}
    payload = {
        "model": JEV_MODEL, "state": state,
        "questions": {"action": {
            "type": "choice",
            "instructions": "Select one legal action for the current player.",
            "criteria": {action: action for action in ids},
        }},
    }
    if len(json.dumps(payload).encode("utf-8")) > 100000:
        raise ValueError("jev_request_too_large")
    return payload


def validate_response(payload, response):
    if not isinstance(response, dict) or response.get("model") != JEV_MODEL:
        raise ValueError("jev_model_not_pinned")
    answers = response.get("answers")
    if not isinstance(answers, dict) or set(answers) != {"action"}:
        raise ValueError("jev_answer_set_mismatch")
    answer = answers["action"]
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError("jev_requires_choice_answer")
    probabilities = answer.get("probabilities")
    labels = payload["questions"]["action"]["criteria"]
    # Jev may return an abstention category; retain it rather than silently
    # conditioning away its probability to force an action.
    allowed = set(labels) | {"__insufficient_evidence__"}
    if (not isinstance(probabilities, dict) or not set(labels) <= set(probabilities)
            or not set(probabilities) <= allowed):
        raise ValueError("jev_legal_menu_mismatch")
    values = list(probabilities.values())
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
           for v in values):
        raise ValueError("jev_invalid_probabilities")
    if not math.isclose(sum(values), 1, abs_tol=1e-6):
        raise ValueError("jev_probability_mass")
    choice = answer.get("choice")
    if choice not in probabilities or probabilities[choice] < max(values) - 1e-8:
        raise ValueError("jev_choice_not_argmax")
    if answer.get("is_abstention") or choice == "__insufficient_evidence__":
        return None
    return choice


class JevShadowAdapter:
    def __init__(self, transport, *, max_calls=100, clock=time.monotonic):
        if not callable(transport) or type(max_calls) is not int or max_calls <= 0:
            raise ValueError("explicit_bounded_transport_required")
        self.transport, self.max_calls, self.clock = transport, max_calls, clock
        self.receipts = []

    def decide(self, observation, *, provenance):
        payload = synthetic_request(observation, provenance=provenance)
        if len(self.receipts) >= self.max_calls:
            raise ValueError("jev_call_budget_exceeded")
        receipt = {
            "input_sha256": canonical_hash(payload), "requested_model": JEV_MODEL,
            "status": "PENDING", "strategy_eligible": False, "advice_emitted": False,
            "probability_semantics": "MODEL_CHOICES_NOT_GTO_OR_EV",
        }
        self.receipts.append(receipt)
        start = self.clock()
        try:
            response = self.transport(deepcopy(payload))
            receipt["raw_response"] = deepcopy(response)
            choice = validate_response(payload, response)
            receipt.update(status="ABSTAIN" if choice is None else "SHADOW_RESULT",
                           action=choice, resolved_model=response["model"],
                           usage=deepcopy(response.get("usage")))
            return choice
        except Exception as exc:
            receipt.update(status="ERROR", error_type=type(exc).__name__)
            raise
        finally:
            receipt["elapsed_ms_including_transport"] = (self.clock() - start) * 1000


class RecordedJevTransport:
    def __init__(self, records):
        self.records = deepcopy(records)

    def __call__(self, payload):
        key = canonical_hash(payload)
        if key not in self.records:
            raise ValueError("no_recorded_jev_response_for_exact_input")
        return deepcopy(self.records[key])
