"""One finite saved-asset batch; no native binary, new solve or fabricated rows."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, Inexact, Rounded, localcontext
from functools import cache
import json
import os
from pathlib import Path
import subprocess

import pytest

from poker_engine.core.enums import ActionType, PlayerStatus, Position, Rank, Suit
from poker_engine.core.value_objects import Card, ChipAmount
from poker_engine.core.request_context import RequestContext
from poker_engine.strategy.contracts import ActionAmountSemantics, PotState
from poker_engine.strategy.frozen_postflop import _combo, _fixed_decimal_context
from poker_engine.strategy.provider import LookupState
from poker_engine.strategy.router import StrategyRouter
from research.hu_root.adapter import (
    RootAssetProvider, RootError, request_config, digest,
)
from research.hu_root.catalog import ASSETS, line
from research.hu_root.fixtures import CASES, native_path, native_root

EVIDENCE = {"positive_queries": [], "refusals": [], "accounting": [],
            "catalogue_paths": []}


@pytest.fixture(autouse=True)
def forbid_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Saved path lookup must never launch any process")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@cache
def asset(name):
    default = Path(__file__).parents[1] / "fixtures" / "hu_saved"
    directory = Path(os.environ.get("HU_SAVED_ASSET_ROOT", default)) / name
    case = next(c for c in CASES if c.name == name)
    _, root = native_root(case)
    data = (directory / "solution.json").read_bytes()
    sha = next(sha for sha, spec in ASSETS.items() if spec[0] == name)
    assert digest(data) == sha
    provider = RootAssetProvider(root, request_config(root), data,
                                 sha256=sha, origin="NATIVE_SAVED_RUN")
    saved = json.loads(data, parse_float=Decimal)
    golden = json.loads((directory / "saved-query.json").read_text("utf-8"))
    assert golden["solution_sha256"] == sha
    return provider, saved, golden


def hero_for(provider, path):
    actor = provider.paths[path][1]
    ranges = provider.path_ranges(path)
    return next(c for c in ranges[actor].combo_weights
                if any(not {c[:2], c[2:]} & {o[:2], o[2:]}
                       for o in ranges[1 - actor].combo_weights))


def menu_json(menu):
    return [{"action": a.action.value, "min_chips": str(a.min_amount.value),
             "max_chips": str(a.max_amount.value),
             "amount_semantics": a.amount_semantics.value} for a in menu]


def model_json(provider, path):
    return [{"action": a["action"].value, "amount_chips": str(a["amount"]),
             "amount_semantics": a["semantics"].value,
             "source_label": a["source_label"]}
            for a in provider.model_menu(path)]


def counts(context):
    return {"table_capacity": context.game_config.max_seats,
            "dealt": context.game_config.dealt_player_count,
            "pot_contenders": len(set(s for p in context.pots
                                      for s in p.eligible_seats)),
            "actionable": sum(s.occupied and s.status is PlayerStatus.ACTIVE
                              and s.stack.value > 0 for s in context.seats),
            "declared_nonfolded_seats": list(context.active_seats)}


def assert_saved_query(name, provider, saved, context, path):
    with localcontext(_fixed_decimal_context()):
        routed = StrategyRouter((provider,)).route(context)
        assert routed.state is LookupState.HIT_EXACT, {
            "path": path, "reasons": routed.reasons,
            "providers": [r.reasons for r in routed.provider_results],
        }
        candidate = routed.selected
        assert candidate is not None and not candidate.action_ev
        assert candidate.confidence == 0
        node_id, actor, _ = provider.paths[path]
        node = next(n for n in saved["nodes"] if n["node"] == node_id)
        assert node["player"] == actor == context.hero_seat == context.actor_seat
        hero = _combo("".join(str(c) for c in context.hero_cards))
        axis = [_combo(c["cards"]) for c in saved["root_combos"][actor]]
        column = axis.index(hero)
        raw = [node["strategy"][a * node["combo_count"] + column]
               for a in range(len(node["actions"]))]
        assert len(candidate.action_options) == len(raw)
        assert sum(o.probability for o in candidate.action_options) == 1
        assert all(abs(o.probability - p) <= Decimal("0.000001")
                   for o, p in zip(candidate.action_options, raw))
        selected = provider.model_menu(path)
        for option, model in zip(candidate.action_options, selected):
            assert option.action is model["action"]
            assert option.source_label == model["source_label"]
            if option.action in (ActionType.BET, ActionType.RAISE):
                assert option.amount.value == model["amount"]
            else:
                # Existing ActionOption cannot carry a CALL amount; context's
                # legal menu and the separate model menu retain ADDITIONAL.
                assert option.amount is None
        EVIDENCE["positive_queries"].append({
            "case": name, "path": list(path), "saved_node": node_id,
            "actor": actor, "hero": hero, "counts": counts(context),
            "board": [str(c) for c in context.board_cards],
            "current_pot_chips": str(context.pots[0].amount.value),
            "current_stacks_chips": [str(s.stack.value) for s in context.seats],
            "street_bets_chips": [str(s.street_committed.value)
                                  for s in context.seats],
            "native_legal_menu": menu_json(context.legal_actions),
            "model_abstraction_menu": model_json(provider, path),
            "raw_saved_probabilities": [str(x) for x in raw],
            "candidate_probabilities": [str(o.probability)
                                        for o in candidate.action_options],
            "range_versions": [context.hero_range.source_version,
                               context.villain_ranges[0].source_version],
            "action_EV": {}, "strategy_eligible": False, "live_eligible": False,
            "action_executable": False, "advice_ready": False,
        })
        return candidate


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_catalogued_paths_and_all_IP_after_check_combos_against_saved(case):
    provider, saved, golden = asset(case.name)
    for path, (_, actor, _) in provider.paths.items():
        try:
            provider.path_ranges(path)
        except RootError as exc:
            assert str(exc) in ("zero_saved_policy_reach",
                                "zero_compatible_joint_policy_reach")
            hero = _combo(saved["root_combos"][actor][0]["cards"])
            request = RequestContext(case.name, 1, case.name + "-zero-reach",
                                     datetime.now(timezone.utc))
            # A declared prior is insufficient for this path; explicitly reject
            # it instead of replacing the missing posterior with uniform mass.
            context = native_path(replace(case, hero=hero), path, actor,
                                  provider.path_ranges(()), request)
            result = provider.query(context)
            assert result.candidate is None and str(exc) in result.reasons
            EVIDENCE["catalogue_paths"].append({
                "case": case.name, "path": list(path),
                "status": "REJECTED_ZERO_REACH", "reason": str(exc),
            })
            continue
        if not path:
            heroes = [_combo(case.hero)]
        elif path == ("CHECK",):
            heroes = [_combo(c["cards"]) for c in saved["root_combos"][1]]
        else:
            heroes = [hero_for(provider, path)]
        for hero in heroes:
            context = provider.context_for_path(path, hero)
            candidate = assert_saved_query(case.name, provider, saved, context, path)
            if not path:
                original = next(r for r in golden["rows"] if r["hero"] == hero)
                assert [str(o.probability) for o in candidate.action_options] == [
                    a["probability"] for a in original["actions"]]
            assert actor == context.actor_seat
        EVIDENCE["catalogue_paths"].append({
            "case": case.name, "path": list(path),
            "status": "SAVED_FREQUENCY_QUERY_PASS", "combos_queried": len(heroes),
        })


@pytest.mark.parametrize("capacity", [6, 8])
def test_table_capacity_is_distinct_from_two_dealt(capacity):
    provider, saved, _ = asset("river-a")
    path = ("CHECK",)
    context = provider.context_for_path(
        path, hero_for(provider, path), max_seats=capacity,
    )
    assert counts(context) == {"table_capacity": capacity, "dealt": 2,
                               "pot_contenders": 2, "actionable": 2,
                               "declared_nonfolded_seats": [0, 1]}
    assert_saved_query("river-a", provider, saved, context, path)


def test_facing_bet_and_raise_replay_use_original_street_start():
    provider, saved, _ = asset("river-a")
    path = ("BET:10",)
    context = provider.context_for_path(path, hero_for(provider, path))
    assert provider.paths[path][0] == 21 and context.actor_seat == 1
    assert context.pots[0].amount.value == 30
    assert [s.street_committed.value for s in context.seats] == [10, 0]
    assert [s.stack.value for s in context.seats] == [70, 80]
    call = next(a for a in context.legal_actions if a.action is ActionType.CALL)
    assert call.min_amount.value == call.max_amount.value == 10
    assert call.amount_semantics is ActionAmountSemantics.ADDITIONAL
    model = provider.model_menu(path)
    assert model[2]["action"] is ActionType.RAISE and model[2]["amount"] == 50
    assert model[2]["semantics"] is ActionAmountSemantics.TOTAL_STREET
    EVIDENCE["accounting"].append({"path": list(path), "node": 21,
                                   "root_pot": 20, "current_pot": 30,
                                   "call_additional": 10, "raise_to": 50})
    raised = ("CHECK", "BET:10", "RAISE:50")
    context = provider.context_for_path(raised, hero_for(provider, raised))
    assert provider.paths[raised][0] == 6 and context.actor_seat == 1
    assert context.pots[0].amount.value == 80
    assert [s.street_committed.value for s in context.seats] == [50, 10]
    assert [s.stack.value for s in context.seats] == [30, 70]
    assert [a["source_label"] for a in provider.model_menu(raised)] == ["Fold", "Call"]
    assert any(a.action is ActionType.RAISE for a in context.legal_actions)
    EVIDENCE["accounting"].append({"path": list(raised), "node": 6,
                                   "current_pot": 80, "call_additional": 40,
                                   "model_raise_cap": 1,
                                   "native_menu_includes_raise": True})
    assert saved["config"]["starting_pot"] == 20


GUARDS = (
    "actor", "board", "current_pot_as_ROOT", "stack", "range_role",
    "unconditioned_prior", "dropped_history", "history_actor", "history_amount",
    "history_additional", "menu_additional", "menu_truncated", "allin_status",
    "allin_eligibility", "outside_bet", "chance_path", "missing_line",
    "six_dealt_two_contenders", "third_allin_main_pot", "masked_third_contender",
)


@pytest.mark.parametrize("guard", GUARDS)
def test_inconsistent_or_uncatalogued_history_never_returns_candidate(guard):
    provider, _, _ = asset("river-a")
    path = ("ALLIN",) if guard.startswith("allin_") else ("BET:10",)
    context = provider.context_for_path(path, hero_for(provider, path))
    bad = context
    if guard == "actor":
        bad = replace(context, actor_seat=0)
    elif guard == "board":
        bad = replace(context, board_cards=context.board_cards[:-1]
                      + (Card(Rank.FOUR, Suit.SPADES),))
    elif guard == "current_pot_as_ROOT":
        bad = replace(context, action_line=line(()), action_history=())
    elif guard == "stack":
        bad = replace(context, seats=(replace(context.seats[0],
                                              stack=ChipAmount(69)), context.seats[1]))
    elif guard == "range_role":
        bad = replace(context, hero_range=context.villain_ranges[0],
                      villain_ranges=(context.hero_range,))
    elif guard == "unconditioned_prior":
        bad = replace(context, villain_ranges=(provider.path_ranges(())[0],))
    elif guard == "dropped_history":
        bad = replace(context, action_history=())
    elif guard.startswith("history_"):
        event = context.action_history[0]
        payload = dict(event.payload)
        key, value = {"history_actor": ("seat", 1),
                      "history_amount": ("amount_total_street", "11"),
                      "history_additional": ("amount_semantics", "additional")}[guard]
        payload[key] = value
        bad = replace(context, action_history=(replace(event, payload=payload),))
    elif guard == "menu_additional":
        bad = replace(context, legal_actions=tuple(
            replace(a, amount_semantics=ActionAmountSemantics.ADDITIONAL)
            if a.action is ActionType.RAISE else a for a in context.legal_actions))
    elif guard == "menu_truncated":
        bad = replace(context, legal_actions=context.legal_actions[:-1])
    elif guard == "allin_status":
        assert counts(context)["pot_contenders"] == 2
        assert counts(context)["actionable"] == 1
        bad = replace(context, seats=(
            replace(context.seats[0], status=PlayerStatus.ACTIVE), context.seats[1],
        ))
    elif guard == "allin_eligibility":
        bad = replace(context, pots=(replace(context.pots[0], eligible_seats=(1,)),))
    elif guard in ("outside_bet", "chance_path", "missing_line"):
        bad = replace(context, action_line={"outside_bet": "hu-root:BET:6",
                                            "chance_path": "hu-root:CHECK,CHECK",
                                            "missing_line": None}[guard])
    elif guard == "six_dealt_two_contenders":
        bad = replace(context, game_config=replace(context.game_config,
                                                   max_seats=6, dealt_player_count=6))
    else:
        extra = replace(context.seats[0], seat_id=2, player_id="synthetic-2",
                        position=Position.BTN, stack=ChipAmount(0),
                        street_committed=ChipAmount(0), hand_committed=ChipAmount(10),
                        status=PlayerStatus.ALL_IN, is_hero=False, is_dealer=False)
        bad = replace(context, seats=context.seats + (extra,),
                      game_config=replace(context.game_config, max_seats=3,
                                          dealt_player_count=3),
                      active_seats=((0, 1, 2) if guard == "third_allin_main_pot"
                                    else (0, 1)),
                      pots=(PotState("main", ChipAmount(40), (0, 1, 2)),))
        assert counts(bad)["pot_contenders"] == 3 and counts(bad)["actionable"] == 2
    direct = provider.query(bad)
    routed = StrategyRouter((provider,)).route(bad)
    assert direct.candidate is None and routed.selected is None
    EVIDENCE["refusals"].append({
        "guard": guard, "state": direct.state.value,
        "reasons": list(direct.reasons), "router_state": routed.state.value,
        "counts": counts(bad), "candidate_absent": True,
    })


def test_path_query_preserves_hostile_decimal_context():
    provider, saved, _ = asset("turn-c")
    path, hero = ("CHECK",), hero_for(provider, ("CHECK",))
    with localcontext() as ambient:
        ambient.prec = 1
        ambient.traps[Inexact] = ambient.traps[Rounded] = True
        before = dict(ambient.flags)
        context = provider.context_for_path(path, hero)
        assert provider.query(context).candidate is not None
        assert ambient.prec == 1 and dict(ambient.flags) == before
    assert_saved_query("turn-c", provider, saved, context, path)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_path_candidates_route_in_standard_decimal_context(case):
    """The Router copies candidates under the caller's usual 28-digit context."""
    provider, saved, _ = asset(case.name)
    path = ("CHECK",)
    for row in saved["root_combos"][1]:
        hero = _combo(row["cards"])
        with localcontext() as caller:
            caller.prec = 28
            context = provider.context_for_path(path, hero)
            routed = StrategyRouter((provider,)).route(context)
        assert routed.state is LookupState.HIT_EXACT
        assert routed.selected is not None and not routed.selected.action_ev
        with localcontext(_fixed_decimal_context()):
            assert sum(o.probability for o in routed.selected.action_options) == 1
