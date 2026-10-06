"""Synthetic declared histories only, on two existing saved river assets."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, Rounded, localcontext
import subprocess

import pytest

from poker_engine.core.enums import PlayerStatus, Position, Rank, Suit
from poker_engine.core.events import EventType, StateEvent
from poker_engine.core.request_context import RequestContext
from poker_engine.core.value_objects import Card, ChipAmount
from poker_engine.strategy.advice import AdviceStatus, build_advice
from poker_engine.strategy.contracts import (
    EffectiveStack, InputProvenance, InputSource, PotState, QualityStatus,
)
from poker_engine.strategy.provider import LookupState, MatchKind
from poker_engine.strategy.router import StrategyRouter
from poker_engine.strategy.state import calculate_side_pots
from research.hu_root.adapter import RootError
from research.hu_root.catalog import line
from research.hu_root.river_projection import FIELDS, LIMITS, SOURCE, context_digest
from tests.strategy.test_hu_saved_paths import asset, hero_for

EVIDENCE = {"positive_queries": [], "refusals": [], "qualification": []}
PAIR = (4, 1)


@pytest.fixture(autouse=True)
def no_backend(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Projection cannot start a backend process")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def declared_start(provider, n, hero_role, hero, origin="DECLARED_SYNTHETIC"):
    model = provider.context_for_path((), hero_for(provider, ()))
    roles = provider.path_ranges(())
    source = origin + "/river-start-range"
    ranges = tuple(replace(r, seat_id=seat, source=source,
                           source_version=f"declared/{n}/{seat}/river-start")
                   for seat, r in zip(PAIR, roles))
    # Blinds 2/2 are folded money. Remaining players matched preflop 2 and
    # flop (pot-8)/2, then checked through turn. This is an explicit ledger.
    flop_bet = (model.pots[0].amount.value - 8) / 2
    committed = 2 + flop_bet
    stack = model.seats[0].stack.value
    initial = stack + committed
    seats = tuple(replace(
        model.seats[0], seat_id=i, player_id=f"declared-{i}",
        position=Position.BTN if i == 1 else Position.UTG,
        stack=ChipAmount(stack if i in PAIR else initial - (2 if i in (2, 3) else 0)),
        hand_committed=ChipAmount(committed if i in PAIR else 2 if i in (2, 3) else 0),
        status=PlayerStatus.ACTIVE if i in PAIR else PlayerStatus.FOLDED,
        is_hero=i == PAIR[hero_role], is_dealer=i == 1,
    ) for i in range(n))
    events = []
    now = datetime.now(timezone.utc) - timedelta(seconds=1)

    def add(kind, street, seat=None, amount=0, semantics="none", **extra):
        payload = {"street": street, **extra}
        if seat is not None:
            payload.update(seat=seat, amount_total_street=str(amount),
                           amount_semantics=semantics)
        version = len(events)
        events.append(StateEvent(kind, f"projection-{n}", version, payload,
                                 now + timedelta(milliseconds=version), SOURCE))

    add(EventType.HAND_START, "preflop", dealt_seats=list(range(n)),
        initial_stacks={str(i): str(initial) for i in range(n)},
        postflop_action_order=list(range(2, n)) + [0, 1])
    add(EventType.DEAL, "preflop", 2, 1, "additional", action="post_sb")
    add(EventType.DEAL, "preflop", 3, 2, "additional", action="post_bb")
    add(EventType.CALL, "preflop", 4, 2, "additional")
    for i in list(range(5, n)) + [0]:
        add(EventType.FOLD, "preflop", i)
    add(EventType.CALL, "preflop", 1, 2, "additional")
    add(EventType.CALL, "preflop", 2, 1, "additional")
    add(EventType.CHECK, "preflop", 3)
    add(EventType.STREET_CHANGE, "flop")
    add(EventType.CHECK, "flop", 2)
    add(EventType.CHECK, "flop", 3)
    add(EventType.BET, "flop", 4, flop_bet, "total_street")
    add(EventType.CALL, "flop", 1, flop_bet, "additional")
    add(EventType.FOLD, "flop", 2)
    add(EventType.FOLD, "flop", 3)
    add(EventType.STREET_CHANGE, "turn")
    add(EventType.CHECK, "turn", 4)
    add(EventType.CHECK, "turn", 1)
    add(EventType.STREET_CHANGE, "river", board=[str(c) for c in model.board_cards])
    req = RequestContext(f"projection-{n}", events[-1].state_version,
                         f"projection-{n}-start", events[-1].timestamp)
    pots = calculate_side_pots(seats).pots
    start = replace(
        model, request=req,
        game_config=replace(model.game_config, max_seats=n, dealt_player_count=n),
        seats=seats, hero_seat=PAIR[hero_role], actor_seat=PAIR[0], active_seats=PAIR,
        hero_cards=tuple(model.hero_cards), pots=pots, action_history=tuple(events),
        effective_stacks=(EffectiveStack(PAIR[1 - hero_role], ChipAmount(stack)),),
        hero_range=ranges[hero_role], villain_ranges=(ranges[1 - hero_role],),
        input_provenance=tuple(InputProvenance(
            name, (InputSource.CONFIG if origin == "DECLARED_SYNTHETIC"
                   else InputSource.MANUAL),
            QualityStatus.VALID, 1.0, "declared fixture only",
        ) for name in sorted(FIELDS)),
        assumptions=model.assumptions + ("public_history_complete:declared",
                                         "folded_card_information:unknown"),
    )
    return replace(start, hero_cards=(Card(Rank(hero[0]), Suit(hero[1])),
                                      Card(Rank(hero[2]), Suit(hero[3]))))


def declared_current(bridge, path):
    start, pair = bridge._river_start, bridge._river_order
    hero = "".join(str(c) for c in start.hero_cards)
    req = replace(start.request, state_version=start.state_version + len(path),
                  request_id=start.request_id + "/" + line(path),
                  requested_at=(start.request.requested_at
                                + timedelta(milliseconds=len(path))))
    model = bridge._river_asset.context_for_path(path, hero, request=req)
    seats = []
    for old in start.seats:
        if old.seat_id in pair:
            current = model.seats[pair.index(old.seat_id)]
            old = replace(old, stack=current.stack,
                          street_committed=current.street_committed,
                          hand_committed=ChipAmount(old.hand_committed.value
                                                    + current.street_committed.value),
                          status=current.status)
        seats.append(old)
    suffix = []
    for i, event in enumerate(model.action_history):
        payload = dict(event.payload)
        payload["seat"] = pair[payload["seat"]]
        suffix.append(replace(event, payload=payload, source=SOURCE,
                              state_version=start.state_version + i + 1,
                              timestamp=(start.request.requested_at
                                         + timedelta(milliseconds=i + 1))))
    ranges = {r.seat_id: r for r in bridge.river_ranges(path)}
    return replace(
        start, request=req, actor_seat=pair[model.actor_seat], seats=tuple(seats),
        pots=calculate_side_pots(tuple(seats), settle_uncalled=False).pots,
        legal_actions=model.legal_actions,
        action_history=start.action_history + tuple(suffix),
        effective_stacks=(EffectiveStack(pair[1 - model.hero_seat],
                                         model.effective_stacks[0].amount),),
        effective_stack_bb=model.effective_stack_bb, action_line=line(path),
        hero_range=ranges[start.hero_seat],
        villain_ranges=(ranges[pair[1 - model.hero_seat]],),
    )


@pytest.mark.parametrize("name,n", [("river-a", 6), ("river-b", 8)])
def test_all_catalogued_river_paths_in_full_original_roster(name, n):
    provider, _, _ = asset(name)
    for path, (_, actor, _) in provider.paths.items():
        hero = hero_for(provider, path)
        start = declared_start(provider, n, actor, hero)
        bridge = provider.for_multiway_river(
            start, action_order=PAIR, origin="DECLARED_SYNTHETIC")
        context = declared_current(bridge, path)
        before = context_digest(context), context_digest(start)
        with localcontext() as caller:
            caller.prec = 40
            route = StrategyRouter((bridge,)).route(context)
            assert route.state is LookupState.HIT_APPROXIMATE, route.reasons
            expected = provider.query(provider.context_for_path(
                path, hero, request=context.request))
            assert route.selected.action_options == expected.candidate.action_options
            assert route.selected.match_kind is MatchKind.HEURISTIC
            assert route.selected.confidence == 0 and not route.selected.action_ev
        assert (context_digest(context), context_digest(start)) == before
        assert context.game_config.dealt_player_count == len(context.seats) == n
        assert context.pots[0].amount.value == (
            Decimal(provider.config["starting_pot"])
            + sum(s.street_committed.value for s in context.seats))
        assert set(LIMITS) <= set(route.selected.assumptions)
        assert provider.query(context).candidate is None  # Old gate unchanged.
        EVIDENCE["positive_queries"].append({
            "asset": name, "path": list(path), "dealt": n, "OOP_IP": list(PAIR),
            "original_context_sha256": before[0], "dead_folded_chips": "4",
            "pot": str(context.pots[0].amount.value), "frequency_equal_to_saved": True,
            "lookup": route.state.value, "action_EV": {}, "confidence": 0,
        })


@pytest.mark.parametrize("origin", ["DECLARED_SYNTHETIC", "DECLARED_MANUAL"])
def test_explicit_origin_and_advice_execution_gate(origin):
    provider, _, _ = asset("river-a")
    hero = hero_for(provider, ("CHECK",))
    start = declared_start(provider, 8, 1, hero, origin)
    bridge = provider.for_multiway_river(start, action_order=PAIR, origin=origin)
    context = declared_current(bridge, ("CHECK",))
    assert bridge.query(context).candidate is not None
    # Fresh declared replay request isolates the execution gate. The older
    # original request must still respect the existing freshness refusal.
    stale = bridge.projected_advice(context)
    assert stale.status is AdviceStatus.STALE
    assert not stale.action_options and not stale.action_probabilities
    fresh = replace(context, request=replace(
        context.request, requested_at=datetime.now(timezone.utc)))
    advice = bridge.projected_advice(fresh)
    assert advice.status is AdviceStatus.ABSTAIN
    assert not advice.action_options and not advice.action_probabilities
    gate = next(g for g in advice.gate_results
                if g.name == "research_river_projection_execution")
    assert gate.status.value == "FAIL"
    EVIDENCE["qualification"].append({
        "origin": origin, "frequency_found": True,
        "advice_status": advice.status.value, "gate": gate.name,
        "older_request_status": stale.status.value,
        "action_executable": False, "strategy_eligible": False,
    })


START_GUARDS = (
    "order", "missing_order", "range_missing", "range_weights", "real_range_label",
    "provenance", "missing_history", "late_fold", "fold_money", "unknown_origin",
    "marker_missing", "marker_board", "future_event", "known_folded_cards",
    "3contenders", "masked_3contenders", "multiple_pots", "board", "unequal_stack",
    "missing_declaration", "partial_menu", "live_mode", "history_version_gap",
    "backwards_marker", "history_call_semantics", "history_fold_amount",
    "history_chip_unit", "missing_full_order", "known_opponent_cards",
    "hero_missing", "hero_outside_range", "effective_stack", "range_role_swap",
)


@pytest.mark.parametrize("guard", START_GUARDS)
def test_start_refusals_never_create_projected_provider(guard):
    provider, _, _ = asset("river-a")
    start = declared_start(provider, 6, 0, hero_for(provider, ()))
    bad, order, origin = start, PAIR, "DECLARED_SYNTHETIC"
    if guard == "order":
        order = tuple(reversed(PAIR))
    elif guard == "missing_order":
        order = None
    elif guard in ("range_missing", "range_weights", "real_range_label"):
        if guard == "range_missing":
            bad = replace(start, hero_range=None)
        else:
            values = dict(start.hero_range.combo_weights)
            values[next(iter(values))] += Decimal("0.1")
            bad = replace(start, hero_range=replace(
                start.hero_range,
                combo_weights=(values if guard == "range_weights"
                               else start.hero_range.combo_weights),
                source=("inferred-real-range" if guard == "real_range_label"
                        else start.hero_range.source)))
    elif guard == "provenance":
        bad = replace(start, input_provenance=())
    elif guard == "hero_missing":
        bad = replace(start, hero_cards=())
    elif guard == "hero_outside_range":
        bad = replace(start, hero_cards=(Card(Rank.TWO, Suit.CLUBS),
                                         Card(Rank.THREE, Suit.CLUBS)))
    elif guard == "effective_stack":
        bad = replace(start, effective_stacks=(EffectiveStack(1, ChipAmount(79)),))
    elif guard == "range_role_swap":
        bad = replace(start, hero_range=start.villain_ranges[0],
                      villain_ranges=(start.hero_range,))
    elif guard in ("missing_history", "marker_missing"):
        bad = replace(start, action_history=(
            () if guard == "missing_history" else start.action_history[:-1]))
    elif guard in ("late_fold", "marker_board", "future_event", "known_folded_cards",
                   "history_version_gap", "backwards_marker", "history_call_semantics",
                   "history_fold_amount", "history_chip_unit", "missing_full_order",
                   "known_opponent_cards"):
        events = list(start.action_history)
        index = next(i for i, e in enumerate(events) if e.event_type is EventType.FOLD)
        if guard == "marker_board":
            index = len(events) - 1
        elif guard == "backwards_marker":
            index = next(i for i, e in enumerate(events)
                         if e.payload.get("street") == "turn")
        elif guard in ("history_call_semantics", "history_chip_unit"):
            index = next(i for i, e in enumerate(events)
                         if e.event_type is EventType.CALL)
        elif guard == "missing_full_order":
            index = 0
        event = events[index]
        payload = dict(event.payload)
        if guard == "late_fold":
            payload["street"] = "river"
        elif guard == "marker_board":
            payload["board"] = []
        elif guard == "known_folded_cards":
            payload["known_dead_cards"] = ["2c"]
        elif guard == "known_opponent_cards":
            payload["opponent_cards"] = ["2c", "3c"]
        elif guard == "backwards_marker":
            payload["street"] = "flop"
        elif guard == "history_call_semantics":
            payload["amount_semantics"] = "total_street"
        elif guard == "history_fold_amount":
            payload["amount_total_street"] = "1"
        elif guard == "history_chip_unit":
            payload["amount_total_street"] = "1.5"
        elif guard == "missing_full_order":
            del payload["postflop_action_order"]
        events[index] = replace(
            event, payload=payload,
            state_version=(event.state_version
                           + (1 if guard == "history_version_gap" else 0)),
            timestamp=(start.request.requested_at + timedelta(seconds=1)
                       if guard == "future_event" else event.timestamp))
        bad = replace(start, action_history=tuple(events))
    elif guard in ("fold_money", "unequal_stack", "3contenders", "masked_3contenders"):
        seats = list(start.seats)
        if guard == "fold_money":
            seats[2] = replace(seats[2], hand_committed=ChipAmount(0))
        elif guard == "unequal_stack":
            seats[4] = replace(seats[4], stack=ChipAmount(79))
        else:
            seats[2] = replace(seats[2], stack=ChipAmount(0),
                               status=PlayerStatus.ALL_IN)
        bad = replace(start, seats=tuple(seats), active_seats=(
            PAIR + (2,) if guard == "3contenders" else PAIR))
    elif guard == "multiple_pots":
        bad = replace(start, pots=(start.pots[0],
                                   PotState("side", ChipAmount(1), PAIR)))
    elif guard == "unknown_origin":
        origin = "UNKNOWN"
    elif guard == "board":
        bad = replace(start, board_cards=tuple(reversed(start.board_cards)))
    elif guard == "partial_menu":
        bad = replace(start, legal_actions=start.legal_actions[:-1])
    else:
        bad = replace(start, assumptions=(
            ("execution_mode:live",) if guard == "live_mode" else ()))
    before = context_digest(bad)
    with pytest.raises((RootError, KeyError, ValueError)) as exc:
        provider.for_multiway_river(bad, action_order=order, origin=origin)
    assert context_digest(bad) == before
    EVIDENCE["refusals"].append({
        "stage": "start", "guard": guard, "reason": str(exc.value)})


CURRENT_GUARDS = (
    "pseudo_ROOT", "history_prefix", "history_amount", "history_source",
    "third_allin", "masked_third_allin", "pot_eligibility", "unconditioned_range",
    "folded_money_removed", "actor", "menu", "outside_path", "chance_path",
    "missing_namespace",
)


@pytest.mark.parametrize("guard", CURRENT_GUARDS)
def test_current_refusals_never_return_frequencies(guard):
    provider, _, _ = asset("river-a")
    path = ("BET:10",)
    start = declared_start(provider, 8, 1, hero_for(provider, path))
    bridge = provider.for_multiway_river(
        start, action_order=PAIR, origin="DECLARED_SYNTHETIC")
    context = declared_current(bridge, path)
    bad = context
    if guard == "pseudo_ROOT":
        bad = replace(context, action_line=line(()),
                      action_history=start.action_history)
    elif guard == "history_prefix":
        bad = replace(context, action_history=context.action_history[1:])
    elif guard in ("history_amount", "history_source"):
        last = context.action_history[-1]
        payload = dict(last.payload)
        if guard == "history_amount":
            payload["amount_total_street"] = "11"
        bad = replace(context, action_history=context.action_history[:-1] + (replace(
            last, payload=payload,
            source="unknown" if guard == "history_source" else last.source),))
    elif guard in ("third_allin", "masked_third_allin", "folded_money_removed"):
        seats = list(context.seats)
        seats[2] = (replace(seats[2], hand_committed=ChipAmount(0))
                    if guard == "folded_money_removed" else replace(
                        seats[2], stack=ChipAmount(0), status=PlayerStatus.ALL_IN))
        bad = replace(context, seats=tuple(seats), active_seats=(
            PAIR + (2,) if guard == "third_allin" else PAIR))
    elif guard == "pot_eligibility":
        bad = replace(context, pots=(replace(context.pots[0],
                                             eligible_seats=(1, 2, 4)),))
    elif guard == "unconditioned_range":
        bad = replace(context, villain_ranges=start.villain_ranges)
    elif guard == "actor":
        bad = replace(context, actor_seat=4)
    elif guard == "menu":
        bad = replace(context, legal_actions=context.legal_actions[:-1])
    else:
        bad = replace(context, action_line={
            "outside_path": "hu-root:BET:6", "chance_path": "hu-root:CHECK,CHECK",
            "missing_namespace": "BET:10",
        }[guard])
    result = bridge.query(bad)
    assert result.candidate is None
    assert StrategyRouter((bridge,)).route(bad).selected is None
    EVIDENCE["refusals"].append({
        "stage": "current", "guard": guard, "reasons": result.reasons})


@pytest.mark.parametrize("precision", [1, 28, 40])
def test_public_range_and_query_helpers_preserve_decimal_context(precision):
    provider, _, _ = asset("river-a")
    path = ("CHECK", "BET:10")
    start = declared_start(provider, 6, 0, hero_for(provider, path))
    bridge = provider.for_multiway_river(
        start, action_order=PAIR, origin="DECLARED_SYNTHETIC")
    context = declared_current(bridge, path)
    with localcontext() as ambient:
        ambient.prec = precision
        ambient.traps[Inexact] = ambient.traps[Rounded] = True
        flags = dict(ambient.flags)
        assert bridge.river_ranges(path) == (context.hero_range,
                                             context.villain_ranges[0])
        assert bridge.query(context).candidate is not None
        assert ambient.prec == precision and dict(ambient.flags) == flags
    with localcontext() as ordinary:
        ordinary.prec = 28
        assert StrategyRouter((bridge,)).route(context).selected is not None


def test_declared_range_metadata_and_namespace_are_preserved():
    provider, _, _ = asset("river-a")
    path = ("BET:10",)
    start = declared_start(provider, 6, 1, hero_for(provider, path))
    start = replace(
        start, hero_range=replace(start.hero_range, confidence=0.8),
        villain_ranges=(replace(start.villain_ranges[0], confidence=0.6),),
    )
    bridge = provider.for_multiway_river(
        start, action_order=PAIR, origin="DECLARED_SYNTHETIC")
    assert bridge.river_ranges(()) == (start.villain_ranges[0], start.hero_range)
    current = declared_current(bridge, path)
    assert current.hero_range.confidence == 0.8
    assert current.villain_ranges[0].confidence == 0.6
    assert current.hero_range.source == start.hero_range.source
    assert current.hero_range.source_version.startswith(start.hero_range.source_version)
    assert bridge.query(current).candidate.confidence == 0


@pytest.mark.parametrize("name,n,origin", [
    ("river-a", 6, "DECLARED_SYNTHETIC"),
    ("river-b", 8, "DECLARED_MANUAL"),
])
def test_projection_generic_advice_cannot_promote_frequencies(name, n, origin):
    provider, _, _ = asset(name)
    path = next(p for p in provider.paths if len(p) == 1 and p[0].startswith("BET:"))
    start = declared_start(provider, n, 1, hero_for(provider, path), origin)
    bridge = provider.for_multiway_river(start, action_order=PAIR, origin=origin)
    current = declared_current(bridge, path)
    route = StrategyRouter((bridge,)).route(current)
    assert route.state is LookupState.HIT_APPROXIMATE
    assert route.selected.action_options and route.selected.confidence == 0
    advice = build_advice(current, route, now=current.request.requested_at)
    assert advice.status is AdviceStatus.ABSTAIN
    assert "declared_model_frequency_only" in advice.rejection_reasons
    assert not advice.action_options and not advice.action_probabilities
    assert advice.preferred_action is None and not advice.action_ev
    assert any(g.name == "strategy_source" and g.status.value == "FAIL"
               for g in advice.gate_results)


@pytest.mark.parametrize("stage", ["bind", "query"])
@pytest.mark.parametrize("origin", ["DECLARED_SYNTHETIC", "DECLARED_MANUAL"])
@pytest.mark.parametrize("offset", [None, -60, 0, 60])
def test_declared_range_times_respect_request_without_inventing_time(
    stage, origin, offset,
):
    provider, _, _ = asset("river-a")
    path = ("CHECK",)
    start = declared_start(provider, 6, 1, hero_for(provider, path), origin)
    bridge = provider.for_multiway_river(start, action_order=PAIR, origin=origin)
    context = start if stage == "bind" else declared_current(bridge, path)
    observed = (None if offset is None else
                context.request.requested_at + timedelta(seconds=offset))
    changed = replace(context, input_provenance=tuple(
        replace(p, observed_at=observed) if p.field_name == "ranges" else p
        for p in context.input_provenance
    ))
    if stage == "bind":
        if offset == 60:
            with pytest.raises(RootError, match="projection_provenance_from_future"):
                provider.for_multiway_river(changed, action_order=PAIR, origin=origin)
        else:
            rebound = provider.for_multiway_river(
                changed, action_order=PAIR, origin=origin,
            )
            assert rebound.query(declared_current(rebound, path)).candidate is not None
            assert next(p.observed_at for p in rebound._river_start.input_provenance
                        if p.field_name == "ranges") == observed
    else:
        result = bridge.query(changed)
        if offset == 60:
            assert result.state is LookupState.REJECTED and result.candidate is None
            assert result.reasons == ("projection_provenance_from_future",)
        else:
            assert result.state is LookupState.HIT_APPROXIMATE
            assert result.candidate is not None


@pytest.mark.parametrize("stage", ["bind", "query"])
def test_all_supplied_projection_provenance_fields_refuse_future_times(stage):
    provider, _, _ = asset("river-a")
    path = ("CHECK",)
    start = declared_start(provider, 6, 1, hero_for(provider, path))
    bridge = provider.for_multiway_river(
        start, action_order=PAIR, origin="DECLARED_SYNTHETIC",
    )
    context = start if stage == "bind" else declared_current(bridge, path)
    for field in sorted(FIELDS):
        changed = replace(context, input_provenance=tuple(
            replace(p, observed_at=(context.request.requested_at
                                    + timedelta(seconds=60)))
            if p.field_name == field else p for p in context.input_provenance
        ))
        if stage == "bind":
            with pytest.raises(RootError, match="projection_provenance_from_future"):
                provider.for_multiway_river(
                    changed, action_order=PAIR, origin="DECLARED_SYNTHETIC",
                )
        else:
            assert bridge.query(changed).reasons == (
                "projection_provenance_from_future",
            )
