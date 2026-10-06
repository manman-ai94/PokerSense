"""Opt-in lookup of one reviewed, synthetic HU river solution; no solving."""

from __future__ import annotations

import hashlib
import json
from decimal import (
    Context, Decimal, DivisionByZero, InvalidOperation, Overflow,
    ROUND_HALF_EVEN, localcontext,
)
from pathlib import Path

from poker_engine.core.enums import ActionType, Rank, Suit
from poker_engine.core.errors import InvalidStateError
from poker_engine.core.value_objects import Card, ChipAmount

from .provider import ActionOption, LookupState, MatchKind, ProviderResult
from .provider import StrategyCandidate


SOURCE_ENGINE = "ucsandman/postflop"
ENGINE_PIN = "5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de"
SOLUTION_SHA256 = "17144742e1597990b74070d3652f47fad015a74a2c00e357a7cbe8f36c72314b"
DEFAULT_SOLUTION = (
    Path(__file__).parent / "assets" / "postflop_synthetic_river_5fc7ee3.json"
)
PROVIDER_ID = "postflop-frozen-synthetic-river"
SOURCE_VERSION = f"{ENGINE_PIN}/frozen-v1/sha256:{SOLUTION_SHA256}"
MAX_REQUEST_BYTES = 16_384
MASS_TOLERANCE = Decimal("0.0000001")


def _fixed_decimal_context() -> Context:
    """Fresh complete context, independent of caller and DefaultContext."""
    return Context(
        prec=40, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
        capitals=1, clamp=0, flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow],
    )


# Explicit decision catalogue for this reviewed model, not a tree generator.
# path: (saved node, actor, pot, remaining stacks, river contributions)
_DECISIONS = {
    (): (0, 0, "10", ("20", "20"), ("0", "0")),
    ("CHECK",): (1, 1, "10", ("20", "20"), ("0", "0")),
    ("CHECK", "BET:5"): (3, 0, "15", ("20", "15"), ("0", "5")),
    ("BET:5",): (6, 1, "15", ("15", "20"), ("5", "0")),
}
_EXPECTED_RANGES = {
    "oop": {"6c8c": Decimal("1"), "AhAs": Decimal("1")},
    "ip": {"ThTs": Decimal("1"), "KdAs": Decimal("1")},
}


class FrozenLookupError(ValueError):
    """Stable refusal reason without caller data or local paths."""


def _keys(value, names, reason):
    if type(value) is not dict or set(value) != set(names.split()):
        raise FrozenLookupError(reason)


def _money(value):
    try:
        return ChipAmount(value).value
    except (InvalidStateError, InvalidOperation, TypeError, ValueError):
        raise FrozenLookupError("invalid_chips_or_weight") from None


def _combo(value):
    if not isinstance(value, str) or len(value) != 4:
        raise FrozenLookupError("invalid_combo")
    try:
        cards = [Card(Rank(value[i]), Suit(value[i + 1])) for i in (0, 2)]
    except (TypeError, ValueError):
        raise FrozenLookupError("invalid_combo") from None
    if cards[0] == cards[1]:
        raise FrozenLookupError("duplicate_combo_card")
    return "".join(str(card) for card in sorted(cards))


def _weighted_range(values):
    if type(values) is not list or len(values) != 2:
        raise FrozenLookupError("weighted_range_mismatch")
    result = {}
    for item in values:
        _keys(item, "combo weight", "invalid_weighted_range")
        combo, weight = _combo(item["combo"]), _money(item["weight"])
        if combo in result or weight <= 0:
            raise FrozenLookupError("invalid_weighted_range")
        result[combo] = weight
    return result


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FrozenLookupError("duplicate_json_key")
        result[key] = value
    return result


def decode_request(raw: bytes):
    """Bounded, strict JSON input; monetary floats remain disallowed."""
    if len(raw) > MAX_REQUEST_BYTES:
        raise FrozenLookupError("request_too_large")

    def reject_constant(_):
        raise FrozenLookupError("nonfinite_json_number")

    try:
        decoded = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
            parse_constant=reject_constant,
        )
        if type(decoded) is not dict:
            raise FrozenLookupError("request_must_be_object")
        return decoded
    except FrozenLookupError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise FrozenLookupError("invalid_request_json") from None


class FrozenPostflopProvider:
    """Reuse ProviderResult/StrategyCandidate without inventing a BB context.

    This is deliberately not registered as a production StrategyProvider.
    The standard DecisionContext requires positive blinds; this asset has no
    BB definition. Only an explicit chips-based offline/simulation request fits.
    """

    provider_id = PROVIDER_ID
    source_version = SOURCE_VERSION

    def __init__(self, solution_path: Path = DEFAULT_SOLUTION):
        try:
            with Path(solution_path).open("rb") as stream:
                raw = stream.read(2_154)
        except OSError:
            raise FrozenLookupError("solution_unavailable") from None
        if len(raw) != 2_153 or hashlib.sha256(raw).hexdigest() != SOLUTION_SHA256:
            raise FrozenLookupError("solution_digest_mismatch")
        self._solution = json.loads(raw, parse_float=Decimal)
        self._nodes = {node["node"]: node for node in self._solution["nodes"]}

    def _locate(self, request):
        _keys(request, "schema_version type execution_mode identity source_engine "
              "engine_pin solution_sha256 model decision", "request_schema_mismatch")
        if (type(request["schema_version"]) is not int
                or request["schema_version"] != 1
                or request["type"] != "FrozenPostflopRequest"):
            raise FrozenLookupError("request_schema_mismatch")
        if request["execution_mode"] not in ("offline", "simulation"):
            raise FrozenLookupError("offline_or_simulation_only")
        if (request["source_engine"] != SOURCE_ENGINE
                or request["engine_pin"] != ENGINE_PIN
                or request["solution_sha256"] != SOLUTION_SHA256):
            raise FrozenLookupError("source_binding_mismatch")
        identity = request["identity"]
        _keys(identity, "hand_id state_version request_id", "invalid_identity")
        if (not all(isinstance(identity[k], str) and identity[k]
                    for k in ("hand_id", "request_id"))
                or type(identity["state_version"]) is not int
                or identity["state_version"] < 0):
            raise FrozenLookupError("invalid_identity")
        model = request["model"]
        _keys(model, "street board unit big_blind_chips dealt_player_count "
              "active_player_count oop_seat ip_seat starting_pot_chips "
              "initial_stacks_chips ranges rules", "model_schema_mismatch")
        if (model["street"] != "river" or model["unit"] != "chips"
                or model["board"] != ["2c", "3d", "7h", "9s", "Jc"]
                or model["big_blind_chips"] is not None):
            raise FrozenLookupError("board_street_or_unit_mismatch")
        for name, expected in (("dealt_player_count", 2), ("active_player_count", 2),
                               ("oop_seat", 0), ("ip_seat", 1)):
            if type(model[name]) is not int or model[name] != expected:
                raise FrozenLookupError("heads_up_seat_scope_mismatch")
        if (_money(model["starting_pot_chips"]) != 10
                or self._amounts(model["initial_stacks_chips"]) != (20, 20)):
            raise FrozenLookupError("initial_pot_or_stacks_mismatch")
        ranges = model["ranges"]
        _keys(ranges, "oop ip", "weighted_range_mismatch")
        if any(_weighted_range(ranges[k]) != v for k, v in _EXPECTED_RANGES.items()):
            raise FrozenLookupError("weighted_range_mismatch")
        rules = model["rules"]
        _keys(rules, "variant rake_percent rake_cap_chips ante_chips straddle icm "
              "locks raise_cap allow_all_in", "unknown_or_unsupported_rules")
        if (rules["variant"] != "NLHE"
                or any(_money(rules[k]) != 0 for k in
                       ("rake_percent", "rake_cap_chips", "ante_chips"))
                or any(rules[k] is not False for k in
                       ("straddle", "icm", "allow_all_in"))
                or type(rules["raise_cap"]) is not int or rules["raise_cap"] != 0
                or type(rules["locks"]) is not list or rules["locks"]):
            raise FrozenLookupError("unknown_or_unsupported_rules")
        decision = request["decision"]
        _keys(decision, "path hero_seat hero_combo pot_chips stacks_chips "
              "street_committed_chips legal_actions", "decision_schema_mismatch")
        path = decision["path"]
        if type(path) is not list or not all(isinstance(v, str) for v in path):
            raise FrozenLookupError("unsupported_decision_path")
        spec = _DECISIONS.get(tuple(path))
        if spec is None:
            raise FrozenLookupError("unsupported_decision_path")
        node_id, actor, pot, stacks, committed = spec
        if type(decision["hero_seat"]) is not int or decision["hero_seat"] != actor:
            raise FrozenLookupError("hero_not_current_actor")
        if (_money(decision["pot_chips"]) != Decimal(pot)
                or self._amounts(decision["stacks_chips"])
                != tuple(map(Decimal, stacks))
                or self._amounts(decision["street_committed_chips"])
                != tuple(map(Decimal, committed))):
            raise FrozenLookupError("decision_accounting_mismatch")
        node = self._nodes[node_id]
        menu = self._menu(node)
        actions = decision["legal_actions"]
        if type(actions) is not list or len(actions) != len(menu):
            raise FrozenLookupError("action_menu_mismatch")
        for supplied, expected in zip(actions, menu):
            _keys(supplied, "action amount_chips amount_semantics",
                  "action_menu_mismatch")
            if (supplied["action"] != expected["action"]
                    or _money(supplied["amount_chips"])
                    != Decimal(expected["amount_chips"])
                    or supplied["amount_semantics"] != expected["amount_semantics"]):
                raise FrozenLookupError("action_menu_mismatch")
        combo = _combo(decision["hero_combo"])
        combos = [_combo(v["cards"]) for v in self._solution["root_combos"][actor]]
        if combo not in combos:
            raise FrozenLookupError("hero_combo_not_in_frozen_range")
        return identity, node, combos.index(combo), menu

    @staticmethod
    def _amounts(values):
        if type(values) is not list or len(values) != 2:
            raise FrozenLookupError("invalid_two_player_amounts")
        return tuple(_money(v) for v in values)

    @staticmethod
    def _menu(node):
        result = []
        for action in node["actions"]:
            name = action["kind"].upper()
            amount = action.get("amount", Decimal("5") if name == "CALL" else 0)
            semantics = {"BET": "total_street", "CALL": "additional"}.get(name, "none")
            result.append({"action": name, "amount_chips": str(amount),
                           "amount_semantics": semantics})
        return result

    def _lookup(self, request):
        try:
            identity, node, slot, menu = self._locate(request)
            raw = [node["strategy"][i * node["combo_count"] + slot]
                   for i in range(len(menu))]
            mass = sum(raw, Decimal("0"))
            if (mass <= 0 or abs(mass - 1) > MASS_TOLERANCE
                    or any(not p.is_finite() or p < 0 or p > 1 for p in raw)):
                raise FrozenLookupError("invalid_saved_probability_mass")
            probabilities = [p / mass for p in raw[:-1]]
            probabilities.append(Decimal("1") - sum(probabilities, Decimal("0")))
            options = tuple(ActionOption(
                ActionType[v["action"]], probability,
                ChipAmount(v["amount_chips"]) if v["action"] == "BET" else None,
                source_label=f"frozen_node:{node['node']}",
            ) for v, probability in zip(menu, probabilities))
            candidate = StrategyCandidate(
                **identity, provider_id=self.provider_id,
                provider_version=self.source_version,
                match_kind=MatchKind.EXACT, state_match_score=1.0,
                action_probabilities={v.action: v.probability for v in options},
                action_options=options,
                recommended_sizes={v.action: (v.amount,) for v in options
                                   if v.amount is not None},
                action_ev={}, confidence=0.0,
                evidence=(f"source_engine:{SOURCE_ENGINE}",
                          f"engine_pin:{ENGINE_PIN}",
                          f"solution_sha256:{SOLUTION_SHA256}",
                          f"saved_node:{node['node']}"),
                assumptions=("synthetic_hu_river_only", "offline_or_simulation_only",
                             "no_bb_definition", "confidence_uncalibrated",
                             "saved_f32_mass_normalized", "no_action_ev_export"),
            )
            detail = {"saved_node": node["node"], "saved_combo_slot": slot,
                      "raw_probability_mass": str(mass),
                      "actions": [dict(v, probability=str(p), saved_probability=str(r))
                                  for v, p, r in zip(menu, probabilities, raw)]}
            return (
                ProviderResult(LookupState.HIT_EXACT, self.provider_id, candidate),
                detail,
            )
        except FrozenLookupError as exc:
            return ProviderResult(LookupState.REJECTED, self.provider_id,
                                  reasons=(str(exc),)), {}

    def query(self, request) -> ProviderResult:
        with localcontext(_fixed_decimal_context()):
            return self._lookup(request)[0]

    def query_json(self, request) -> dict:
        with localcontext(_fixed_decimal_context()):
            return self._query_json_in_context(request)

    def _query_json_in_context(self, request) -> dict:
        result, detail = self._lookup(request)
        candidate = result.candidate
        response = {
            "schema_version": 1, "type": "FrozenPostflopResponse",
            "status": result.state.value, "provider_id": self.provider_id,
            "source_engine": SOURCE_ENGINE, "engine_pin": ENGINE_PIN,
            "solution_sha256": SOLUTION_SHA256, "source_version": self.source_version,
            "reasons": list(result.reasons), "candidate": None,
            "live_eligible": False, "advice_emitted": False,
            "strategy_eligible": False, "action_ev_status": "NOT_SUPPORTED",
            "exploitability_bb100": None,
        }
        if candidate is not None:
            response["candidate"] = {
                "hand_id": candidate.hand_id, "state_version": candidate.state_version,
                "request_id": candidate.request_id,
                "match_kind": candidate.match_kind.value,
                "action_probabilities": {k.value: str(v) for k, v in
                                         candidate.action_probabilities.items()},
                "recommended_sizes": {k.value: [str(v.value) for v in values]
                                      for k, values
                                      in candidate.recommended_sizes.items()},
                "action_ev": {}, "confidence": candidate.confidence,
                "evidence": list(candidate.evidence),
                "assumptions": list(candidate.assumptions),
            }
            response.update(detail)
            meta = self._solution["meta"]
            response["model_metrics"] = {
                "scope": "range_aggregate_saved_profile_not_action_ev",
                "iterations": meta["iterations"],
                "profile_root_ev_chips": [str(v) for v in meta["root_evs"]["zero_sum"]],
                "raw_br_chips": [str(v) for v in meta["gain"]],
                "total_deviation_chips": str(meta["exploitability_chips"]),
                "total_deviation_pct_of_starting_pot": str(
                    meta["exploitability_pct_of_pot"]),
                "bb_chips": None, "exploitability_bb100": None,
            }
        return response
