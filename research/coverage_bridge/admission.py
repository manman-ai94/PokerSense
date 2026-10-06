"""Source-preserving, all-street observation-to-menu admission contract.

This module imports only state/contract utilities, never a learner or provider.
Mapping completeness is separate from strategy admission. Every result abstains.
Unknown facts and ranges are retained; nothing is assigned to opponent hands.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
import hashlib
import json

from poker_engine.core.enums import (
    ActionType, PlayerStatus, Position, Rank, Street, Suit,
)
from poker_engine.core.errors import InvalidStateError
from poker_engine.core.opponents import PlayerState
from poker_engine.core.state import PokerState
from poker_engine.core.value_objects import Card, ChipAmount
from poker_engine.strategy.contracts import (
    DecisionSeat, GameConfig, GameType, InputProvenance, InputSource, QualityStatus,
)
from poker_engine.strategy.context_factory import (
    ContextQualityPolicy, aggregate_context_quality,
)
from poker_engine.strategy.state import calculate_legal_actions, calculate_side_pots

SCHEMA = "offline-coverage-decision-v1"
MAPPING_SCOPE = "cash-nlhe-explicit-canonical-menu-v1"
HEURISTIC_SCOPE = "rfi-heuristic-100bb-unopened-v1"
REQUIRED = (
    "hand_id", "state_version", "street", "hero_seat", "actor_seat",
    "dealer_seat", "table_size", "dealt_player_count", "hero_cards", "board_cards",
    "players", "pot", "current_bet", "to_call", "minimum_raise_increment",
    "betting_reopened", "rules", "history", "history_complete", "legal_menu",
    "legal_menu_kind", "complete_legal_state",
    "actions_complete_and_canonical_verified",
)
FORBIDDEN = {"opponent_cards", "villain_cards", "all_hole_cards", "future_board",
             "future_cards", "sampled_joint", "opponent_private_cards"}


class Refusal(ValueError):
    pass


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def known(value, evidence="synthetic-contract"):
    return {"status": "KNOWN", "value": value, "confidence": 1.0,
            "evidence_ref": evidence}


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise Refusal("INVALID_INTEGER:" + label)
    return value


def _money(value, label, quantum=None):
    try:
        amount = ChipAmount(value)
    except (ValueError, TypeError, ArithmeticError, InvalidStateError) as exc:
        raise Refusal("INVALID_MONEY:" + label) from exc
    if quantum is not None and amount.value % quantum:
        raise Refusal("CHIP_UNIT_MISMATCH:" + label)
    return amount


def _bool(value, label):
    if type(value) is not bool:
        raise Refusal("INVALID_BOOLEAN:" + label)
    return value


def _cards(value, expected, label):
    if not isinstance(value, list) or len(value) != expected:
        raise Refusal("CARD_COUNT:" + label)
    try:
        if any(type(c) is not str or len(c) != 2 for c in value):
            raise ValueError("card")
        cards = tuple(Card(Rank(c[0]), Suit(c[1])) for c in value)
    except (TypeError, ValueError) as exc:
        raise Refusal("INVALID_CARDS:" + label) from exc
    if len(set(cards)) != len(cards):
        raise Refusal("CARD_COLLISION:" + label)
    return cards


def _private_or_future(value):
    if isinstance(value, dict):
        return any(k in FORBIDDEN or _private_or_future(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_private_or_future(v) for v in value)
    return False


def extract_facts(payload):
    """Preserve declared facts/candidates; reader/reference formats stay partial."""
    if isinstance(payload.get("facts"), dict):
        return deepcopy(payload["facts"])
    fields = deepcopy(payload.get("fields", {}))
    critical = payload.get("critical_perception_v1", {})
    if isinstance(critical, dict) and isinstance(critical.get("fields"), dict):
        fields.update(deepcopy(critical["fields"]))
    # Visual slots, ribbon digits and balances are separate from canonical
    # seats, contribution pot and committed PlayerState. Only explicit facts
    # above may declare the canonical contract.
    aliases = {"actor": "actor_slot", "board": "board_cards",
               "pot": "displayed_pot", "stacks": "visible_stacks",
               "participation": "participation_slots"}
    facts = {aliases.get(k, k): v for k, v in fields.items()}
    # Top-level exact reader declarations retain producer evidence, not VALID.
    for name in ("hero_seat", "hand_id", "state_version", "street", "table_size",
                 "complete_legal_state", "actions_complete_and_canonical_verified"):
        if name in payload and name not in facts:
            facts[name] = {"status": "CANDIDATE", "value": deepcopy(payload[name]),
                           "evidence_ref": "producer_declaration_unverified"}
    cards = payload.get("cards")
    if isinstance(cards, dict) and "hero" in cards and "hero_cards" not in facts:
        facts["hero_cards"] = {"status": "CANDIDATE", "value": deepcopy(cards["hero"]),
                               "evidence_ref": "reader_card_candidate"}
    # Keep observable reader fields even when critical fields remain UNKNOWN.
    # These additions never satisfy missing canonical seats, pot or players.
    for raw_name, fact_name in (
        ("current_actor", "actor_slot"),
        ("pot", "displayed_pot"),
        ("stacks", "visible_stacks"),
        ("hero_slot", "hero_slot"),
        ("declared_action_window", "declared_action_window"),
        ("displayed_actions", "displayed_actions"),
        ("ledger_pot", "unverified_ledger_pot"),
        ("next_hand_posts", "next_hand_posts"),
    ):
        if raw_name not in payload or fact_name in facts:
            continue
        raw = deepcopy(payload[raw_name])
        value = raw.get("value") if isinstance(raw, dict) and "value" in raw else raw
        facts[fact_name] = {
            "status": "CANDIDATE", "value": value,
            "evidence_ref": "producer_visual_field:" + raw_name,
            "producer_evidence": raw,
            "semantics": "visual_or_declared_candidate_not_canonical_state",
        }
    return facts


def _quality(facts, origin):
    provenance, errors = [], []
    source = InputSource.CONFIG
    # Provenance class does not authenticate the source. Origin remains external.
    if origin != "synthetic_contract":
        source = (
            InputSource.VISION if origin == "saved_recognition" else InputSource.MANUAL
        )
    for name in REQUIRED:
        item = facts.get(name)
        if not isinstance(item, dict):
            errors.append("MISSING_FIELD:" + name)
            continue
        status = item.get("status")
        status = {
            "KNOWN": QualityStatus.VALID, "VALID": QualityStatus.VALID,
            "CONFLICT": QualityStatus.CONFLICT,
            "LOW_CONFIDENCE": QualityStatus.LOW_CONFIDENCE,
        }.get(status, QualityStatus.UNKNOWN)
        confidence = item.get("confidence", 0.0)
        evidence = item.get("evidence_ref")
        if "value" not in item:
            errors.append("MISSING_VALUE:" + name)
        elif item["value"] is None:
            status = QualityStatus.UNKNOWN
        if not isinstance(evidence, str) or not evidence:
            errors.append("MISSING_PROVENANCE:" + name)
            evidence = "missing"
        try:
            provenance.append(
                InputProvenance(name, source, status, confidence, evidence)
            )
        except (ValueError, TypeError):
            errors.append("INVALID_PROVENANCE:" + name)
    quality = aggregate_context_quality(
        tuple(provenance), ContextQualityPolicy(REQUIRED),
        consistency_failures=tuple(errors),
    )
    return quality


def _serialize_menu(actions):
    return [{"action": a.action.value,
             "min_amount": format(a.min_amount.value.normalize(), "f"),
             "max_amount": format(a.max_amount.value.normalize(), "f"),
             "amount_semantics": a.amount_semantics.value} for a in actions]


def _normalize_menu(value, quantum):
    if not isinstance(value, list) or not value:
        raise Refusal("INVALID_LEGAL_MENU")
    rows = []
    seen = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "action", "min_amount", "max_amount", "amount_semantics",
        }:
            raise Refusal("INVALID_LEGAL_MENU_ROW")
        kind = row["action"]
        if kind in seen:
            raise Refusal("DUPLICATE_LEGAL_ACTION")
        seen.add(kind)
        minimum = _money(row["min_amount"], "menu_min", quantum)
        maximum = _money(row["max_amount"], "menu_max", quantum)
        if minimum > maximum:
            raise Refusal("INVALID_LEGAL_MENU_BOUNDS")
        rows.append((kind, minimum.value, maximum.value, row["amount_semantics"]))
    return sorted(rows)


def _check_history(values, players, big_blind, quantum):
    """Independently account for declared payments and short-raise reopening.

    This checks declarations, not visual timing, room authenticity or actor order.
    A missing history is never reconstructed from current stacks or later frames.
    """
    paid = defaultdict(lambda: Decimal(0))
    street_paid = defaultdict(lambda: Decimal(0))
    last_stage, level, full_increment, acted = None, Decimal(0), big_blind, set()
    folded, all_in = set(), set()
    for event in values["history"]:
        stage, actor, action = event["street"], event["actor"], event["action"]
        if actor not in {p.seat for p in players}:
            raise Refusal("HISTORY_SEAT_NOT_OCCUPIED")
        if actor in folded or actor in all_in:
            raise Refusal("HISTORY_ACTION_AFTER_FOLD_OR_ALL_IN")
        if stage != last_stage:
            stage_number = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
            if (
                last_stage is not None
                and stage_number[stage] < stage_number[last_stage]
            ):
                raise Refusal("BACKWARDS_HISTORY_STREET")
            last_stage, level, full_increment, acted = (
                stage, Decimal(0), big_blind, set()
            )
        amount = _money(event["amount"], "history_amount", quantum).value
        prior = street_paid[(stage, actor)]
        semantics = event["amount_semantics"]
        if semantics == "additional":
            target = prior + amount
        elif semantics == "total_street":
            target = amount
            if target < prior:
                raise Refusal("HISTORY_TOTAL_BELOW_COMMITTED")
        else:
            target = prior
        delta = target - prior
        if action in {"post_sb", "post_bb", "post_ante"}:
            if stage != "preflop" or semantics != "additional":
                raise Refusal("INVALID_FORCED_POST_HISTORY")
            specified = values["rules"][{
                "post_sb": "small_blind", "post_bb": "big_blind", "post_ante": "ante",
            }[action]]
            if amount != _money(specified, "forced_post", quantum).value:
                raise Refusal("FORCED_POST_RULE_MISMATCH")
            level = max(level, target) if action != "post_ante" else level
            if action == "post_ante":
                target = prior  # ante contributes to hand but not street wager
        else:
            if action == "check" and prior < level:
                raise Refusal("HISTORY_CHECK_FACING_BET")
            if action == "call" and (
                semantics != "additional" or delta != level - prior
            ):
                raise Refusal("HISTORY_CALL_AMOUNT_MISMATCH")
            if target > level:
                if action not in {"bet", "raise", "all_in"}:
                    raise Refusal("HISTORY_UNDECLARED_AGGRESSION")
                if actor in acted and level > 0:
                    raise Refusal("HISTORY_RAISE_NOT_REOPENED")
                increment = target - level
                if increment >= full_increment:
                    full_increment, acted = increment, set()
                elif action != "all_in":
                    raise Refusal("HISTORY_SHORT_RAISE_NOT_ALL_IN")
                level = target
            acted.add(actor)
        paid[actor] += delta
        street_paid[(stage, actor)] = target
        if action == "fold":
            folded.add(actor)
        if action == "all_in":
            all_in.add(actor)
    for player in players:
        if paid[player.seat] != player.committed_this_hand.value:
            raise Refusal("HISTORY_HAND_COMMITMENT_MISMATCH")
        if (
            street_paid[(values["street"], player.seat)]
            != player.committed_this_street.value
        ):
            raise Refusal("HISTORY_STREET_COMMITMENT_MISMATCH")
        if (player.status is PlayerStatus.FOLDED) != (player.seat in folded):
            raise Refusal("HISTORY_PARTICIPATION_MISMATCH")
        if (player.status is PlayerStatus.ALL_IN) != (player.seat in all_in):
            raise Refusal("HISTORY_ALL_IN_MISMATCH")
    if values["street"] != last_stage:
        level, full_increment, acted = Decimal(0), big_blind, set()
    if (
        _money(
            values["minimum_raise_increment"], "minimum_raise_increment", quantum,
        ).value
        != full_increment
    ):
        raise Refusal("MINIMUM_RAISE_HISTORY_MISMATCH")
    if values["betting_reopened"] != (values["actor_seat"] not in acted):
        raise Refusal("REOPENING_HISTORY_MISMATCH")


def _construct(values):
    rules = values["rules"]
    if not isinstance(rules, dict):
        raise Refusal("RULES_MISSING")
    required_rules = {
        "variant", "game_type", "small_blind", "big_blind", "ante",
        "rake_percent", "rake_cap", "minimum_chip", "straddle", "verified",
    }
    if set(rules) != required_rules:
        raise Refusal("RULE_PROFILE_INCOMPLETE")
    if rules["variant"] != "NLHE" or rules["game_type"] != "cash":
        raise Refusal("MAPPING_SCOPE_VARIANT")
    if rules["verified"] is not True:
        raise Refusal("RULES_NOT_VERIFIED")
    if _money(rules["straddle"], "straddle").value != 0:
        raise Refusal("MAPPING_SCOPE_STRADDLE")
    quantum = _money(rules["minimum_chip"], "minimum_chip").value
    if quantum <= 0:
        raise Refusal("INVALID_CHIP_UNIT")
    table = _integer(values["table_size"], "table_size", 2)
    dealt = _integer(values["dealt_player_count"], "dealt_player_count", 2)
    if not 2 <= dealt <= table <= 9:
        raise Refusal("MAPPING_SCOPE_PLAYER_COUNT")
    hero = _integer(values["hero_seat"], "hero_seat")
    actor = _integer(values["actor_seat"], "actor_seat")
    dealer = _integer(values["dealer_seat"], "dealer_seat")
    if any(s >= table for s in (hero, actor, dealer)):
        raise Refusal("SEAT_OUT_OF_BOUNDS")
    if not isinstance(values["hand_id"], str) or not values["hand_id"]:
        raise Refusal("HAND_ID_MISSING")
    version = _integer(values["state_version"], "state_version")
    try:
        street = Street(values["street"])
    except (TypeError, ValueError) as exc:
        raise Refusal("MAPPING_SCOPE_STREET") from exc
    if street.value not in {"preflop", "flop", "turn", "river"}:
        raise Refusal("MAPPING_SCOPE_STREET")
    hero_cards = _cards(values["hero_cards"], 2, "hero")
    board = _cards(
        values["board_cards"],
        {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[street.value], "board",
    )
    if set(hero_cards) & set(board):
        raise Refusal("CARD_COLLISION:hero_board")
    if (
        values["complete_legal_state"] is not True
        or values["actions_complete_and_canonical_verified"] is not True
    ):
        raise Refusal("CANONICAL_STATE_NOT_COMPLETE")
    if (
        values["history_complete"] is not True
        or not isinstance(values["history"], list)
    ):
        raise Refusal("HISTORY_NOT_COMPLETE")
    for i, event in enumerate(values["history"]):
        if not isinstance(event, dict) or event.get("sequence") != i:
            raise Refusal("HISTORY_SEQUENCE_GAP")
        if event.get("street") not in {"preflop", "flop", "turn", "river"}:
            raise Refusal("INVALID_HISTORY_STREET")
        if (
            {"preflop": 0, "flop": 1, "turn": 2, "river": 3}[event["street"]]
            > {"preflop": 0, "flop": 1, "turn": 2, "river": 3}[street.value]
        ):
            raise Refusal("FUTURE_HISTORY")
        _integer(event.get("actor"), "history_actor")
        if event["actor"] >= table:
            raise Refusal("HISTORY_ACTOR_OUT_OF_BOUNDS")
        try:
            action = ActionType(event.get("action"))
        except (TypeError, ValueError) as exc:
            raise Refusal("INVALID_HISTORY_ACTION") from exc
        amount = _money(event.get("amount"), "history_amount", quantum)
        semantics = event.get("amount_semantics")
        if semantics not in {"none", "additional", "total_street"}:
            raise Refusal("HISTORY_AMOUNT_SEMANTICS_UNKNOWN")
        if action in (ActionType.CHECK, ActionType.FOLD) and (
            amount.value or semantics != "none"
        ):
            raise Refusal("HISTORY_ZERO_ACTION_AMOUNT")
    reopening = _bool(values["betting_reopened"], "betting_reopened")
    if values["legal_menu_kind"] != "complete_nlhe_intervals":
        raise Refusal("LEGAL_MENU_NOT_COMPLETE")
    players_raw = values["players"]
    if not isinstance(players_raw, list) or len(players_raw) != dealt:
        raise Refusal("OCCUPIED_SEAT_LEDGER_INCOMPLETE")
    players, seats = [], []
    for row in players_raw:
        if not isinstance(row, dict):
            raise Refusal("INVALID_PLAYER")
        seat = _integer(row.get("seat"), "player_seat")
        if seat >= table:
            raise Refusal("SEAT_OUT_OF_BOUNDS")
        stack = _money(row.get("stack"), "stack", quantum)
        committed = _money(row.get("street_committed"), "street_committed", quantum)
        hand = _money(row.get("hand_committed"), "hand_committed", quantum)
        try:
            status = PlayerStatus(row.get("status"))
            position = Position(row.get("position"))
        except (ValueError, TypeError) as exc:
            raise Refusal("PARTICIPATION_OR_POSITION_UNKNOWN") from exc
        if status not in {
            PlayerStatus.ACTIVE, PlayerStatus.FOLDED, PlayerStatus.ALL_IN,
        }:
            raise Refusal("PARTICIPATION_UNKNOWN")
        if (status is PlayerStatus.ALL_IN) != (stack.value == 0):
            raise Refusal("ALL_IN_STACK_CONFLICT")
        players.append(PlayerState(
            f"seat-{seat}", seat, position, stack, committed, hand,
            status, status is not PlayerStatus.FOLDED, seat == hero, seat == dealer,
        ))
        seats.append(DecisionSeat(
            seat, f"seat-{seat}", position, stack, committed, hand,
            status, is_hero=seat == hero, is_dealer=seat == dealer,
        ))
    by_id = {p.seat: p for p in players}
    if len(by_id) != len(players):
        raise Refusal("DUPLICATE_PLAYER_SEAT")
    if not {hero, actor, dealer} <= set(by_id):
        raise Refusal("REQUIRED_SEAT_MISSING")
    if sum(p.status in {PlayerStatus.ACTIVE, PlayerStatus.ALL_IN} for p in players) < 2:
        raise Refusal("NO_DECISION_OPPORTUNITY")
    if by_id[actor].status is not PlayerStatus.ACTIVE or by_id[actor].stack.value <= 0:
        raise Refusal("ACTOR_NOT_ACTIONABLE")
    pot = _money(values["pot"], "pot", quantum)
    current = _money(values["current_bet"], "current_bet", quantum)
    to_call = _money(values["to_call"], "to_call", quantum)
    increment = _money(
        values["minimum_raise_increment"], "minimum_raise_increment", quantum,
    )
    if increment.value <= 0:
        raise Refusal("INVALID_MINIMUM_RAISE_INCREMENT")
    if pot.value != sum((p.committed_this_hand.value for p in players), Decimal(0)):
        raise Refusal("POT_COMMITMENT_CONFLICT")
    if current.value != max(p.committed_this_street.value for p in players):
        raise Refusal("CURRENT_BET_CONFLICT")
    if to_call.value != max(
        Decimal(0), current.value - by_id[actor].committed_this_street.value
    ):
        raise Refusal("TO_CALL_CONFLICT")
    game = GameConfig(
        "NLHE", GameType.CASH, table, dealt,
        _money(rules["small_blind"], "small_blind", quantum),
        _money(rules["big_blind"], "big_blind", quantum),
        _money(rules["ante"], "ante", quantum),
        _money(rules["rake_percent"], "rake_percent").value,
        _money(rules["rake_cap"], "rake_cap", quantum), ChipAmount(quantum),
    )
    _check_history(values, players, game.big_blind.value, quantum)
    state = PokerState(version, values["hand_id"], street, hero_cards, board,
                       tuple(players), pot, current, to_call, actor)
    actions = calculate_legal_actions(state, game, minimum_raise_increment=increment)
    # Existing core API lacks this explicit guard. Keep call/short-all-in calls.
    if not reopening and current.value > 0:
        actions = tuple(
            a for a in actions if a.action not in {ActionType.RAISE, ActionType.BET}
            and not (
                a.action is ActionType.ALL_IN and a.max_amount.value > to_call.value
            )
        )
    expected = _serialize_menu(actions)
    supplied = _normalize_menu(values["legal_menu"], quantum)
    if supplied != _normalize_menu(expected, quantum):
        raise Refusal("LEGAL_MENU_MISMATCH")
    pots = calculate_side_pots(tuple(seats), settle_uncalled=False)
    return state, game, expected, pots


def map_opportunity(record):
    if not isinstance(record, dict):
        record = {"payload": record}
    raw_source = record.get("source")
    source = raw_source if isinstance(raw_source, dict) else {}
    result = {"schema": SCHEMA, "mapping_scope": MAPPING_SCOPE,
              "opportunity_id": record.get("opportunity_id"),
              "input_ordinal": record.get("input_ordinal"),
              "source": deepcopy(source),
              "mapping_status": "REFUSED_INPUT", "strategy_status": "ABSTAIN",
              "quality_status": "NOT_SCORED", "scope_status": "NOT_CHECKED",
              "strategy_eligible": False, "advice_emitted": False, "action": None,
              "legal_menu_checked": False, "reasons": [], "candidate_facts": {},
              "range_binding": {"status": "UNKNOWN", "combos": None},
              "strategy_scope_requested": record.get("target_strategy_scope")}
    payload = record.get("payload")
    if not isinstance(payload, dict):
        result["reasons"] = [record.get("parse_error", "INVALID_INPUT_RECORD")]
        return result
    if raw_source is not None and not isinstance(raw_source, dict):
        result["reasons"] = ["INVALID_SOURCE_METADATA"]
        return result
    if "fields" in payload and not isinstance(payload["fields"], dict):
        result["reasons"] = ["INVALID_CANDIDATE_FIELDS"]
        return result
    origin = result["source"].get("kind")
    if not isinstance(origin, str) or origin not in {
        "real_development_reference", "synthetic_contract", "saved_recognition",
    }:
        result["reasons"] = ["UNKNOWN_SOURCE_KIND"]
        return result
    facts = extract_facts(payload)
    result["candidate_facts"] = facts
    if "ranges" in payload:
        result["range_binding"] = deepcopy(payload["ranges"])
    try:
        if origin != "synthetic_contract" and payload.get("simulation_only") is True:
            raise Refusal("REAL_SOURCE_MISLABELLED_SYNTHETIC")
        if _private_or_future(payload):
            raise Refusal("PRIVATE_OR_FUTURE_INPUT")
        quality = _quality(facts, origin)
        if not quality.is_decision_ready:
            result["reasons"] = list(quality.hard_failures)
            return result
        values = {k: facts[k]["value"] for k in REQUIRED}
        expected_hand = result["source"].get("expected_hand_id")
        if expected_hand is not None and values["hand_id"] != expected_hand:
            raise Refusal("HAND_IDENTITY_MISMATCH")
        if payload.get("capture_epoch") != values["hand_id"]:
            raise Refusal("HAND_EPOCH_MISMATCH")
        state, game, menu, pots = _construct(values)
        result.update(
            mapping_status="MAPPED_MENU_CHECKED", legal_menu_checked=True,
            normalized_state={
                "hand_id": state.hand_id, "state_version": state.state_version,
                "street": state.street.value, "actor": state.actor,
                "hero_seat": values["hero_seat"],
                "board": [str(c) for c in state.board_cards],
                "hero_cards": [str(c) for c in state.hero_cards],
                "pot": str(state.pot.value), "to_call": str(state.to_call.value),
            },
            legal_menu=menu,
            pot_eligibility=[
                {"pot_id": p.pot_id, "amount": str(p.amount.value),
                 "eligible_seats": list(p.eligible_seats)} for p in pots.pots
            ],
        )
        actor = next(p for p in state.players if p.seat == state.actor)
        active_stacks = [
            p.stack.value for p in state.players if p.status is PlayerStatus.ACTIVE
        ]
        eff_bb = min(active_stacks) / game.big_blind.value
        history_unopened = all(
            e["street"] == "preflop" and e["action"] in
            {"fold", "post_sb", "post_bb", "post_ante"} for e in values["history"]
        )
        requested = record.get("target_strategy_scope")
        matches = (
            requested == HEURISTIC_SCOPE and state.street is Street.PREFLOP
            and values["table_size"] in {6, 7, 8, 9}
            and values["dealt_player_count"] == values["table_size"]
            and state.actor == values["hero_seat"] and eff_bb == 100
            and game.ante.value == 0 and game.rake_percent == 0 and history_unopened
            and actor.position in {
                Position.UTG, Position.HJ, Position.CO, Position.BTN, Position.SB,
            }
        )
        if matches:
            result.update(
                scope_status="HEURISTIC_ONLY", quality_status="NOT_SCORED_HEURISTIC",
                reasons=["HEURISTIC_IS_NOT_SCORED_STRATEGY"],
                heuristic_derived_from_nine_hand=values["table_size"] in {7, 8},
            )
        else:
            result.update(
                scope_status="OUT_OF_SCOPE", reasons=["STRATEGY_SCOPE_MISMATCH"],
            )
        return result
    except Refusal as exc:
        reason = str(exc)
        result["reasons"] = [reason]
        if reason.startswith("MAPPING_SCOPE_"):
            result["scope_status"] = "OUT_OF_MAPPING_SCOPE"
        if reason == "LEGAL_MENU_MISMATCH":
            result["mapping_status"] = "REFUSED_MENU"
        return result
    except (ValueError, TypeError, KeyError, ArithmeticError, InvalidStateError) as exc:
        result["reasons"] = ["INVALID_CANONICAL_FACTS:" + type(exc).__name__]
        return result


def replay_records(records):
    """One output per input, including bad JSON, duplicate IDs and stale rows."""
    outputs, ids, sequences = [], set(), {}
    for ordinal, original in enumerate(records, 1):
        record = (
            deepcopy(original) if isinstance(original, dict) else {"payload": original}
        )
        record["input_ordinal"] = ordinal
        identity = record.get("opportunity_id")
        raw_source = record.get("source")
        source = raw_source if isinstance(raw_source, dict) else {}
        if not isinstance(raw_source, dict):
            record["source"] = {
                "kind": "UNKNOWN", "raw_source_metadata": deepcopy(raw_source),
            }
        sequence = source.get("sequence")
        source_id, source_hand = source.get("source_id"), source.get("expected_hand_id")
        source_identity_valid = (
            isinstance(source_id, str) and bool(source_id)
            and (source_hand is None or isinstance(source_hand, str))
        )
        stream = (
            (source_id, source_hand) if source_identity_valid
            else ("invalid-source", ordinal)
        )
        extra = []
        if not isinstance(raw_source, dict):
            extra.append("INVALID_SOURCE_METADATA")
        if not source_identity_valid:
            extra.append("SOURCE_IDENTITY_UNKNOWN")
        if not isinstance(identity, str) or not identity:
            extra.append("OPPORTUNITY_ID_MISSING")
        elif identity in ids:
            extra.append("DUPLICATE_OPPORTUNITY_ID")
        else:
            ids.add(identity)
        if type(sequence) is not int or sequence < 0:
            extra.append("SOURCE_SEQUENCE_UNKNOWN")
        elif stream in sequences and sequence <= sequences[stream]:
            extra.append("STALE_OR_BACKWARDS_SOURCE_SEQUENCE")
        else:
            sequences[stream] = sequence
        try:
            result = map_opportunity(record)
        except Exception as exc:
            result = {
                "opportunity_id": identity, "input_ordinal": ordinal,
                "source": deepcopy(source), "mapping_status": "REFUSED_INTERNAL_ERROR",
                "strategy_status": "ABSTAIN", "quality_status": "NOT_SCORED",
                "scope_status": "NOT_CHECKED", "legal_menu_checked": False,
                "strategy_eligible": False, "advice_emitted": False, "action": None,
                "reasons": ["INTERNAL_ERROR:" + type(exc).__name__],
            }
        if extra:
            result.update(
                mapping_status="REFUSED_INPUT", legal_menu_checked=False,
                strategy_status="ABSTAIN", quality_status="NOT_SCORED",
                scope_status="NOT_CHECKED",
            )
            result["reasons"] = extra + result["reasons"]
            for field in ("normalized_state", "legal_menu", "pot_eligibility"):
                result.pop(field, None)
        outputs.append(result)
    groups, statuses, reasons, streets = (
        defaultdict(Counter), Counter(), Counter(), defaultdict(Counter)
    )
    for row in outputs:
        origin = row["source"].get("kind", "UNKNOWN")
        if not isinstance(origin, str):
            origin = "UNKNOWN"
        groups[origin]["inputs"] += 1
        groups[origin]["mapped_menu_checked"] += int(row["legal_menu_checked"])
        groups[origin]["heuristic_only"] += int(
            row.get("scope_status") == "HEURISTIC_ONLY"
        )
        groups[origin]["scored_strategy_eligible"] += int(row["strategy_eligible"])
        statuses[row["mapping_status"]] += 1
        reasons.update(row["reasons"])
        street_field = row.get("candidate_facts", {}).get("street", {})
        street = (
            street_field.get("value") if isinstance(street_field, dict) else "UNKNOWN"
        )
        street = (
            street if isinstance(street, str)
            and street in {"preflop", "flop", "turn", "river"} else "UNKNOWN"
        )
        streets[street]["inputs"] += 1
        streets[street]["mapped_menu_checked"] += int(row["legal_menu_checked"])
    summary = {
        "schema": SCHEMA, "input_record_denominator": len(records),
        "output_records": len(outputs),
        "all_inputs_retained": len(records) == len(outputs),
        "certified_unique_real_decision_denominator": "NOT_VERIFIED",
        "source_groups": {k: dict(v) for k, v in groups.items()},
        "mapping_counts": dict(statuses),
        "street_counts": {k: dict(v) for k, v in streets.items()},
        "reason_counts": dict(reasons),
        "strategy_eligible_records": sum(r["strategy_eligible"] for r in outputs),
        "advice_emitted_records": sum(r["advice_emitted"] for r in outputs),
        "recognizer_executed": False, "training_runs": 0, "quality_recomputations": 0,
    }
    return outputs, summary
