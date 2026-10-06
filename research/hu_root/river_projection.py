"""Opt-in declared multiway-origin river projection onto existing saved HU rows.

Original contexts remain immutable. Only the internal owned model fixture has
two role seats. Folded money remains in the pot; unknown folded cards never
become blockers. This approximation does not model card bunching or a full game.
"""
from copy import copy
from dataclasses import replace
from decimal import Decimal, localcontext
import json

from poker_engine.core.enums import PlayerStatus, Street
from poker_engine.core.errors import InvalidStateError
from poker_engine.core.events import EventType
from poker_engine.core.opponents import PlayerState
from poker_engine.core.value_objects import ChipAmount
from poker_engine.strategy.contracts import (
    DecisionContext, EffectiveStack, InputSource, QualityStatus,
)
from poker_engine.strategy.frozen_postflop import _combo, _fixed_decimal_context
from poker_engine.strategy.provider import LookupState, MatchKind, ProviderResult
from poker_engine.strategy.safety import GateResult, GateStatus
from poker_engine.strategy.serialization import strategy_serialize
from poker_engine.strategy.state import calculate_side_pots
from research.coverage_bridge.admission import FORBIDDEN, _check_history

from .adapter import MODEL, RootError, digest, require, weighted_range
from .catalog import ASSETS, line

VERSION = "declared-multiway-river-HU-projection-v1"
ORIGINS = {"DECLARED_SYNTHETIC": InputSource.CONFIG,
           "DECLARED_MANUAL": InputSource.MANUAL}
SOURCE = "declared-river-projection-v1"
FIELDS = {"seats", "board", "hero", "pots", "legal_actions", "ranges",
          "action_history", "river_start", "action_order"}
LIMITS = ("folded_card_bunching_not_modelled", "HU_independent_range_abstraction",
          "restricted_saved_bet_abstraction", "not_full_multiway_GTO",
          "declared_sources_not_authenticated", "frequency_only_not_execution",
          "strategy_eligible:false", "live_eligible:false",
          "action_executable:false", "advice_ready:false")


def context_digest(context):
    return digest(json.dumps(strategy_serialize(context), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False).encode())


def _declared(context, origin):
    require(isinstance(context, DecisionContext) and not context.missing_fields
            and context.input_quality.is_decision_ready,
            "projection_context_incomplete")
    require(context.street is Street.RIVER and context.game_config.max_seats in (6, 8)
            and context.game_config.dealt_player_count in (6, 8)
            and len(context.seats) == context.game_config.dealt_player_count
            and all(s.occupied for s in context.seats),
            "complete_6_or_8_dealt_roster_required")
    require([a for a in context.assumptions if a.startswith("execution_mode:")]
            == ["execution_mode:simulation"]
            and {"query_model:" + MODEL, "public_history_complete:declared",
                 "folded_card_information:unknown"} <= set(context.assumptions),
            "explicit_projection_declarations_required")
    provenance = {p.field_name: p for p in context.input_provenance}
    require(FIELDS <= provenance.keys()
            and all(provenance[f].status is QualityStatus.VALID
                    and provenance[f].confidence > 0
                    and provenance[f].source is ORIGINS[origin] for f in FIELDS),
            "projection_provenance_incomplete_or_wrong_origin")
    require(all(p.observed_at is None
                or p.observed_at <= context.request.requested_at
                for p in context.input_provenance),
            "projection_provenance_from_future")


def _single_pot(context, pair, *, settled):
    try:
        calculated = calculate_side_pots(context.seats, settle_uncalled=settled)
    except InvalidStateError as exc:
        raise RootError("invalid_original_pot:" + str(exc)) from exc
    require(not calculated.uncalled_returns and len(calculated.pots) == 1
            and context.pots == calculated.pots
            and context.pots[0].amount.value > 0
            and set(context.pots[0].eligible_seats) == set(pair),
            "single_two_contender_pot_required")
    nonfolded = {s.seat_id for s in context.seats
                 if s.status in (PlayerStatus.ACTIVE, PlayerStatus.ALL_IN)}
    require(nonfolded == set(pair) == set(context.active_seats),
            "two_contenders_including_allin_required")


def _public_history(context, *, check_ledger=True):
    history, prior_time, current_stage = [], None, "preflop"
    stages = ("preflop", "flop", "turn", "river")
    require(2 <= len(context.action_history) <= 256, "complete_public_history_required")
    first = context.action_history[0]
    require(first.event_type is EventType.HAND_START
            and first.state_version == 0
            and len(first.payload.get("dealt_seats", ())) == len(context.seats)
            and set(first.payload.get("dealt_seats", ()))
            == {s.seat_id for s in context.seats}, "history_dealt_roster_mismatch")
    for index, event in enumerate(context.action_history):
        require(event.hand_id == context.hand_id and event.source == SOURCE
                and event.state_version == index
                and event.state_version <= context.state_version
                and (prior_time is None or prior_time < event.timestamp)
                and event.timestamp <= context.request.requested_at,
                "public_history_identity_or_time_mismatch")
        prior_time = event.timestamp
        require(not event.payload.get("known_dead_cards")
                and not event.payload.get("revealed_cards")
                and not FORBIDDEN.intersection(event.payload),
                "known_folded_cards_outside_saved_model")
        stage = event.payload.get("street")
        require(stage in ("preflop", "flop", "turn", "river"), "history_street_missing")
        if event.event_type is EventType.HAND_START:
            require(index == 0 and stage == "preflop", "history_start_mismatch")
            continue
        if event.event_type is EventType.STREET_CHANGE:
            require(stages.index(stage) == stages.index(current_stage) + 1,
                    "history_street_marker_order_mismatch")
            current_stage = stage
            continue
        require(stage == current_stage, "history_action_street_mismatch")
        action = (event.payload.get("action") if event.event_type is EventType.DEAL
                  else event.event_type.value)
        require(action in ("post_sb", "post_bb", "post_ante", "fold", "check",
                           "call", "bet", "raise", "all_in"),
                "unsupported_history_event")
        require(type(event.payload.get("seat")) is int
                and event.payload["seat"] in {s.seat_id for s in context.seats},
                "history_actor_required")
        amount = Decimal(event.payload["amount_total_street"])
        semantics = event.payload["amount_semantics"]
        require(amount.is_finite() and amount >= 0 and amount % 1 == 0,
                "history_chip_unit_mismatch")
        require((action in ("check", "fold") and amount == 0 and semantics == "none")
                or (action in ("call", "post_sb", "post_bb", "post_ante")
                    and semantics == "additional")
                or (action in ("bet", "raise", "all_in")
                    and semantics == "total_street"),
                "history_amount_semantics_mismatch")
        history.append({"street": stage, "actor": event.payload["seat"],
                        "action": action, "amount": str(amount),
                        "amount_semantics": semantics})
    by_id = {s.seat_id: s for s in context.seats}
    players = tuple(PlayerState(
        s.player_id, s.seat_id, s.position, s.stack, s.street_committed,
        s.hand_committed, s.status, s.status is not PlayerStatus.FOLDED,
        s.is_hero, s.is_dealer,
    ) for s in context.seats)
    initial = first.payload.get("initial_stacks")
    require(isinstance(initial, dict) or hasattr(initial, "items"),
            "initial_stacks_required")
    require(set(initial) == {str(s) for s in by_id}
            and all(Decimal(initial[str(i)]) == s.stack.value + s.hand_committed.value
                    for i, s in by_id.items()), "initial_stack_accounting_mismatch")
    if check_ledger:
        _check_history({"history": history, "street": context.street.value,
                        "rules": {"small_blind": "1", "big_blind": "2", "ante": "0"},
                        "minimum_raise_increment": "2",
                        "actor_seat": context.actor_seat,
                        "betting_reopened": True}, players, Decimal(2), Decimal(1))


def _source_ranges(context):
    ranges = (context.hero_range,) + context.villain_ranges
    require(all(r is not None and r.combo_weights for r in ranges)
            and len(ranges) == 2 and len({r.seat_id for r in ranges}) == 2
            and context.hero_range.seat_id == context.hero_seat,
            "two_explicit_declared_ranges_required")
    return {r.seat_id: r for r in ranges}


def bind_projection(asset, start, action_order, origin):
    require(not hasattr(asset, "_river_start") and origin in ORIGINS,
            "explicit_non_nested_projection_origin_required")
    require(asset.sha256 in ASSETS and ASSETS[asset.sha256][0].startswith("river"),
            "existing_catalogued_river_asset_required")
    with localcontext(_fixed_decimal_context()):
        _declared(start, origin)
        require(type(action_order) is tuple and len(action_order) == 2
                and all(type(s) is int for s in action_order)
                and len(set(action_order)) == 2, "explicit_OOP_IP_order_required")
        pair = action_order
        _single_pot(start, pair, settled=True)
        require(start.actor_seat == pair[0] and start.hero_seat in pair
                and start.action_line == line(())
                and all(s.street_committed.value == 0 for s in start.seats)
                and all(s.status is PlayerStatus.ACTIVE and s.stack.value > 0
                        for s in start.seats if s.seat_id in pair),
                "two_live_players_at_original_river_start_required")
        _public_history(start)
        marker = start.action_history[-1]
        require(marker.event_type is EventType.STREET_CHANGE
                and marker.payload.get("street") == "river"
                and tuple(marker.payload.get("board", ()))
                == tuple(str(c) for c in start.board_cards)
                and marker.state_version == start.state_version
                and marker.timestamp == start.request.requested_at,
                "explicit_original_river_start_marker_required")
        require(all(e.payload.get("street") != "river"
                    for e in start.action_history[:-1]),
                "river_already_started_multiway")
        order = start.action_history[0].payload.get("postflop_action_order", ())
        dealers = [s.seat_id for s in start.seats if s.is_dealer]
        require(len(order) == len(start.seats) and len(set(order)) == len(order)
                and set(order) == {s.seat_id for s in start.seats}
                and dealers == [order[-1]]
                and tuple(s for s in order if s in pair) == pair,
                "declared_postflop_order_mismatch")
        ranges = _source_ranges(start)
        require(set(ranges) == set(pair), "range_seat_roles_mismatch")
        for seat, role in zip(pair, ("oop", "ip")):
            r = ranges[seat]
            require(r.source == origin + "/river-start-range"
                    and dict(r.combo_weights)
                    == weighted_range(asset.config[role + "_range"]),
                    "declared_river_start_range_not_saved_asset")
        hero = _combo("".join(str(c) for c in start.hero_cards))
        require(hero in ranges[start.hero_seat].combo_weights,
                "declared_Hero_not_in_river_start_range")
        model = asset.context_for_path((), asset.solution["root_combos"][0][0]["cards"])
        require(replace(start.game_config, max_seats=2, dealt_player_count=2)
                == model.game_config and start.board_cards == model.board_cards
                and start.pots[0].amount == model.pots[0].amount
                and all(s.stack == model.seats[0].stack
                        for s in start.seats if s.seat_id in pair)
                and start.effective_stacks == (EffectiveStack(
                    pair[1 - pair.index(start.hero_seat)], model.seats[0].stack),)
                and start.effective_stack_bb == model.effective_stack_bb
                and start.legal_actions == model.legal_actions,
                "river_start_rules_board_pot_stack_or_menu_not_saved_asset")
        bound = copy(asset)
        bound._river_start, bound._river_order = start, pair
        bound._river_origin = origin
        bound._river_asset = asset
        bound.provider_id = asset.provider_id + "/" + VERSION
        bound.source_version = (asset.source_version + "/" + VERSION + "/"
                                + context_digest(start))
        bound.capability = replace(
            asset.capability, base_match_kind=MatchKind.HEURISTIC,
            hero_positions=frozenset(s.position for s in start.seats
                                     if s.seat_id == start.hero_seat),
        )
        return bound


def projected_ranges(provider, path):
    require(hasattr(provider, "_river_start"), "opt_in_river_projection_required")
    with localcontext(_fixed_decimal_context()):
        provider._river_asset._decision(path)
        roots = _source_ranges(provider._river_start)
        if not path:
            return tuple(roots[seat] for seat in provider._river_order)
        return tuple(replace(
            roots[seat], combo_weights=r.combo_weights, entropy=r.entropy,
            effective_sample_size=r.effective_sample_size,
            source_version=(roots[seat].source_version + "/saved-policy/"
                            + provider.sha256 + "/" + line(path)),
        ) for seat, r in zip(
            provider._river_order, provider._river_asset.path_ranges(path)))


def query_projection(provider, context):
    try:
        with localcontext(_fixed_decimal_context()):
            start, pair = provider._river_start, provider._river_order
            _declared(context, provider._river_origin)
            require(context.is_decision_ready and context.hand_id == start.hand_id
                    and context.hero_seat == start.hero_seat
                    and context.hero_cards == start.hero_cards
                    and context.board_cards == start.board_cards
                    and context.game_config == start.game_config,
                    "projection_original_context_mismatch")
            require(isinstance(context.action_line, str)
                    and context.action_line.startswith("hu-root:"),
                    "explicit_saved_path_namespace_required")
            path = (() if context.action_line == line(()) else
                    tuple(context.action_line.removeprefix("hu-root:").split(",")))
            model = provider._river_asset.context_for_path(
                path, _combo("".join(str(c) for c in context.hero_cards)),
                request=context.request)
            require(context.actor_seat == pair[model.actor_seat],
                    "projection_actor_mismatch")
            _single_pot(context, pair, settled=False)
            expected = []
            for seat in start.seats:
                if seat.seat_id in pair:
                    current = model.seats[pair.index(seat.seat_id)]
                    seat = replace(
                        seat, stack=current.stack, status=current.status,
                        street_committed=current.street_committed,
                        hand_committed=ChipAmount(seat.hand_committed.value
                                                  + current.street_committed.value),
                    )
                expected.append(seat)
            require(context.seats == tuple(expected)
                    and context.pots[0].amount == model.pots[0].amount
                    and context.legal_actions == model.legal_actions
                    and context.effective_stacks == (EffectiveStack(
                        pair[1 - model.hero_seat], model.effective_stacks[0].amount),)
                    and context.effective_stack_bb == model.effective_stack_bb,
                    "projection_native_ledger_or_menu_mismatch")
            require(context.action_history[:len(start.action_history)]
                    == start.action_history
                    and len(context.action_history)
                    == len(start.action_history) + len(path)
                    and context.state_version == start.state_version + len(path),
                    "original_history_prefix_or_path_missing")
            for index, (actual, reference) in enumerate(zip(
                    context.action_history[len(start.action_history):],
                    model.action_history)):
                payload = dict(reference.payload)
                payload["seat"] = pair[payload["seat"]]
                require(actual.event_type is reference.event_type
                        and dict(actual.payload) == payload
                        and actual.state_version == start.state_version + index + 1,
                        "original_path_event_mismatch")
            # The unchanged prefix was fully accounted at binding. The suffix
            # is compared with PokerKit's exact saved-path replay above.
            _public_history(context, check_ledger=False)
            supplied = _source_ranges(context)
            require(supplied
                    == {r.seat_id: r for r in projected_ranges(provider, path)},
                    "declared_conditioned_range_mismatch")
            result = provider._river_asset.query(model)
            require(result.candidate is not None, "saved_model_query_refused")
            candidate = replace(
                result.candidate, provider_id=provider.provider_id,
                provider_version=provider.source_version,
                match_kind=MatchKind.HEURISTIC,
                state_match_score=0.0, confidence=0, action_ev={},
                evidence=result.candidate.evidence + (
                    "projection_origin:" + provider._river_origin,
                    "original_dealt:" + str(start.game_config.dealt_player_count),
                    "original_context_sha256:" + context_digest(context),
                    "original_river_start_sha256:" + context_digest(start),
                    "OOP_IP_original_seats:" + ",".join(map(str, pair))),
                assumptions=tuple(dict.fromkeys(
                    context.assumptions + result.candidate.assumptions + LIMITS)),
            )
            return ProviderResult(LookupState.HIT_APPROXIMATE,
                                  provider.provider_id, candidate)
    except (RootError, KeyError, TypeError, ValueError, AttributeError,
            InvalidStateError, ArithmeticError) as exc:
        return ProviderResult(LookupState.REJECTED, provider.provider_id,
                              reasons=(str(exc),))


def projection_gate(provider):
    require(hasattr(provider, "_river_start"), "opt_in_river_projection_required")
    return GateResult("research_river_projection_execution", GateStatus.FAIL,
                      ("declared_model_frequency_only",
                       "folded_card_bunching_not_modelled"))
