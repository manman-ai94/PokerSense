"""Versioned research policy, deterministic public encoder, no live admission.

The coarse rank/texture abstraction is an experiment, not a learned range or
equity estimate. It uses no Monte Carlo, network, hidden cards or future board.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation


ENCODER_VERSION = "aa_rank_texture_v1"
POLICY_KIND = "AA_FROZEN_POLICY_V1"
FORBIDDEN = {"seed", "deck", "opponent_hole", "all_hole_cards", "future_board",
             "terminal_returns", "actual_action", "showdown"}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _cards(values):
    ranks = "23456789TJQKA"
    result = []
    for card in values:
        if (not isinstance(card, str) or len(card) != 2
                or card[0] not in ranks or card[1] not in "cdhs"):
            raise ValueError("invalid_public_card")
        result.append((ranks.index(card[0]), card[1]))
    return result


def card_bucket(own_hole, board):
    """169 preflop classes; 64 deterministic rank/texture research buckets."""
    hole = _cards(own_hole)
    public = _cards(board)
    if len(hole) != 2 or len(public) not in (0, 3, 4, 5):
        raise ValueError("invalid_street_card_count")
    if len(set(hole + public)) != len(hole + public):
        raise ValueError("duplicate_cards")
    a, b = sorted((hole[0][0], hole[1][0]), reverse=True)
    if not board:
        if a == b:
            return a
        pair_index = a * (a - 1) // 2 + b
        return 13 + pair_index + (0 if hole[0][1] == hole[1][1] else 78)
    # Eight made/draw texture categories x eight high-card bins. Deliberately
    # coarse; this is NOT 64 calibrated equity/potential-strength buckets.
    counts = sorted(Counter(rank for rank, _ in hole + public).values(), reverse=True)
    suits = Counter(suit for _, suit in hole + public)
    ranks = {rank + 2 for rank, _ in hole + public}
    if 14 in ranks:
        ranks.add(1)
    straight = any(set(range(low, low + 5)) <= ranks for low in range(1, 11))
    flush = max(suits.values()) >= 5
    category = (7 if counts[0] >= 4 else 6 if counts[0] >= 3 and counts[1] >= 2
                else 5 if flush else 4 if straight else 3 if counts[0] >= 3
                else 2 if counts[:2] == [2, 2] else 1 if counts[0] == 2 else 0)
    return category * 8 + min(7, a * 8 // 13)


def information_key(observation):
    def forbidden(value):
        if isinstance(value, dict):
            return bool(FORBIDDEN.intersection(value)) or any(
                forbidden(item) for item in value.values())
        return isinstance(value, (list, tuple)) and any(forbidden(x) for x in value)
    if not isinstance(observation, dict) or forbidden(observation):
        raise ValueError("private_or_future_policy_input")
    if observation.get("actor") != observation.get("observing_seat"):
        raise ValueError("policy_must_observe_current_actor")
    keys = ("rules_fingerprint", "table_size", "street", "actor",
            "observing_seat", "occupied_seats", "dealer_seat", "stacks",
            "starting_stacks", "straddler_seat", "bets",
            "folded", "pot", "public_history", "legal_actions")
    try:
        view = {key: observation[key] for key in keys}
        view["card_bucket"] = card_bucket(observation["own_hole"], observation["board"])
        # Public texture is shared information; suit names are retained to avoid
        # an unsound suit remapping between private and public cards.
        view["board_texture"] = {
            "ranks": sorted(card[0] for card in observation["board"]),
            "suits": sorted(Counter(card[1] for card in observation["board"]).items()),
        }
    except KeyError as exc:
        raise ValueError("missing_policy_observation_field") from exc
    return canonical_hash({"encoder": ENCODER_VERSION, "observation": view})


def action_ids(observation):
    actions = observation.get("legal_actions", ())
    ids = tuple(row["id"] for row in actions)
    if not ids or len(ids) != len(set(ids)) or any(not isinstance(x, str) for x in ids):
        raise ValueError("invalid_legal_menu")
    return ids


def validate_distribution(distribution, ids):
    if not isinstance(distribution, dict) or set(distribution) != set(ids):
        raise ValueError("policy_action_menu_mismatch")
    values = list(distribution.values())
    if any(type(value) not in (float, int) or not math.isfinite(value)
           or value < 0 for value in values):
        raise ValueError("invalid_policy_probability")
    if not math.isclose(sum(values), 1, abs_tol=1e-9):
        raise ValueError("policy_probability_mass")


def make_policy(*, rules_fingerprint, table_size, stack_depth_bb,
                policy, training):
    document = {
        "schema_version": 1, "kind": POLICY_KIND, "status": "research_only",
        "rules_fingerprint": rules_fingerprint, "table_size": table_size,
        "stack_depth_bb": str(stack_depth_bb), "encoder": ENCODER_VERSION,
        "policy": deepcopy(policy), "training": deepcopy(training),
        "strategy_eligible": False, "advice_emitted": False,
        "abstraction": "169 preflop / 64 rank-texture; not equity buckets",
        "unknown_history": "ABSTAIN", "live_admission": "NOT_IMPLEMENTED",
    }
    document["sha256"] = canonical_hash(document)
    FrozenResearchPolicy(document)
    return document


class FrozenResearchPolicy:
    """Research lookup only. A valid digest is integrity, never live approval."""

    def __init__(self, document):
        data = deepcopy(document)
        checksum = data.pop("sha256", None)
        if checksum != canonical_hash(data):
            raise ValueError("policy_digest_mismatch")
        if (data.get("schema_version") != 1 or data.get("kind") != POLICY_KIND
                or data.get("status") != "research_only"
                or data.get("encoder") != ENCODER_VERSION
                or data.get("table_size") not in (6, 7, 8)
                or data.get("strategy_eligible") is not False
                or data.get("advice_emitted") is not False
                or data.get("live_admission") != "NOT_IMPLEMENTED"):
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
            if not isinstance(key, str) or len(key) != 64:
                raise ValueError("invalid_information_key")
            validate_distribution(dist, tuple(dist))
        self._data = data
        self.sha256 = checksum

    def distribution(self, observation):
        if (observation.get("rules_fingerprint") != self._data["rules_fingerprint"]
                or observation.get("table_size") != self._data["table_size"]):
            raise ValueError("policy_rule_scope_mismatch")
        try:
            expected = Decimal(self._data["stack_depth_bb"]) * Decimal(
                observation["big_blind"])
            initial = observation["starting_stacks"]
            if (set(initial) != {str(s) for s in observation["occupied_seats"]}
                    or any(Decimal(value) != expected for value in initial.values())):
                raise ValueError("policy_stack_scope_mismatch")
        except (KeyError, TypeError, InvalidOperation) as exc:
            raise ValueError("policy_stack_scope_mismatch") from exc
        dist = self._data["policy"].get(information_key(observation))
        if dist is None:
            return None
        validate_distribution(dist, action_ids(observation))
        return dict(dist)

    def sample(self, observation, rng: random.Random):
        dist = self.distribution(observation)
        if dist is None:
            return None
        ids = action_ids(observation)
        return rng.choices(ids, [dist[action] for action in ids], k=1)[0]

    def require_live(self):
        raise ValueError("research_policy_has_no_live_admission")

    def frozen_map(self):
        """Detached preloading payload; does not grant live admission."""
        return deepcopy(self._data["policy"])

    def __call__(self, observation):
        raise ValueError("frozen_mixture_requires_independent_evaluation_salt")

    def for_game(self, salt):
        if not isinstance(salt, str) or re.fullmatch(r"[0-9a-f]{64}", salt) is None:
            raise ValueError("independent_policy_salt_required")

        def decide(observation):
            key = information_key(observation)
            seed = int(canonical_hash({"salt": salt, "policy": self.sha256,
                                       "information": key}), 16)
            choice = self.sample(observation, random.Random(seed))
            if choice is None:
                raise ValueError("unknown_policy_information_set")
            return choice
        return decide

    def inspect_lookup(self, observation):
        """Explain one lookup without sampling or simulator-private fields."""
        from .aa_policy_diagnostics import failure_category

        result = {"policy_sha256": self.sha256,
                  "encoder_version": self._data["encoder"],
                  "information_key": None, "status": "ADAPTER_ERROR"}
        try:
            result["information_key"] = information_key(observation)
            result["feature_summary"] = {
                "street": observation["street"], "actor": observation["actor"],
                "table_size": observation["table_size"],
                "legal_action_ids": list(action_ids(observation)),
                "card_bucket": card_bucket(observation["own_hole"],
                                           observation["board"]),
            }
            distribution = self.distribution(observation)
            result["status"] = "HIT" if distribution is not None else (
                "UNKNOWN_INFORMATION_SET")
        except (ValueError, TypeError, KeyError) as exc:
            result.update(status=failure_category(exc, "LOOKUP"), reason=str(exc))
        return result
