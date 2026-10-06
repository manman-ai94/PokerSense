"""Conversion tests use saved or explicitly MOCK output, never a new solve."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, Inexact, Rounded, localcontext
import json
import subprocess
import tomllib

import pytest

from poker_engine.core.enums import ActionType, PlayerStatus
from poker_engine.core.value_objects import ChipAmount
from poker_engine.strategy.contracts import ActionAmountSemantics, EffectiveStack
from poker_engine.strategy.frozen_postflop import DEFAULT_SOLUTION
from poker_engine.strategy.provider import LookupState
from poker_engine.strategy.router import StrategyRouter
from research.hu_root.adapter import (
    RootAssetProvider, RootError, config_toml, digest, request_config,
)
from research.hu_root.fixtures import CASES, Case, native_root
from research.hu_root.prepare import prepare_files


def mock_solution(context):
    """Invented distributions for schema conversion only, explicitly not solved."""
    config = request_config(context)
    combos = sorted(context.hero_range.combo_weights)
    ip = sorted(context.villain_ranges[0].combo_weights)
    return {
        "format_version": 1, "config": config, "node_count": 1,
        "nodes": [{"node": 0, "player": 0, "combo_count": len(combos),
                   "actions": [{"kind": "Check"}, {"kind": "Bet", "amount":
                               config["starting_pot"] / 2}, {"kind": "Bet", "amount":
                               config["starting_pot"]}, {"kind": "AllIn"}],
                   "strategy": [p for p in (0.1, 0.2, 0.3, 0.4) for _ in combos]}],
        "root_combos": [[{"cards": c, "index": i} for i, c in enumerate(side)]
                        for side in (combos, ip)],
        "meta": {"iterations": 1, "exploitability_pct_of_pot": 0.1,
                 "payoff_unit": "chips", "root_evs": {"zero_sum": [0, 0]},
                 "gain": [0, 0]},
    }


def mock_provider(context, change=None):
    value = mock_solution(context)
    if change:
        change(value)
    data = json.dumps(value).encode()
    return RootAssetProvider(
        context, request_config(context), data, sha256=digest(data),
        origin="MOCK_CONVERSION_ONLY",
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_parameterized_native_ROOT_facts_and_TOML_conversion(case):
    state, context = native_root(case)
    before = deepcopy((state.operations, state.stacks, state.bets, state.hole_cards))
    config = request_config(context)
    assert tomllib.loads(config_toml(config)) == config
    assert config["board"] == case.board
    assert config["starting_pot"] == case.pot
    assert config["effective_stack"] == case.stack
    assert context.game_config.dealt_player_count == len(context.active_seats) == 2
    assert context.game_config.big_blind.value == 2
    assert context.pots[0].amount.value == sum(
        s.hand_committed.value for s in context.seats)
    assert len(context.hero_range.combo_weights) > 20
    assert len(context.villain_ranges[0].combo_weights) > 20
    assert (state.operations, state.stacks, state.bets, state.hole_cards) == before


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_MOCK_ROOT_retains_per_size_frequency_in_existing_Router(case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Conversion must not launch any process")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    _, context = native_root(case)
    result = StrategyRouter((mock_provider(context),)).route(context)
    assert result.state is LookupState.HIT_EXACT
    assert result.selected.action_ev == {} and result.selected.confidence == 0
    assert len(result.selected.action_options) == 4
    assert [o.probability for o in result.selected.action_options] == [
        Decimal("0.1"), Decimal("0.2"), Decimal("0.3"), Decimal("0.4")]
    assert [o.amount.value for o in result.selected.action_options[1:]] == [
        case.pot / 2, case.pot, case.stack]
    assert result.selected.action_probabilities[ActionType.BET] == Decimal("0.9")
    assert "result_origin:MOCK_CONVERSION_ONLY" in result.selected.evidence


@pytest.mark.parametrize("change", [
    "effective_BB", "effective_chips", "ranges", "status", "line",
    "native_semantics", "partial_menu", "selection",
])
def test_contradictory_context_has_no_candidate(change):
    _, context = native_root(CASES[0])
    provider = mock_provider(context)
    if change == "effective_BB":
        bad = replace(context, effective_stack_bb=Decimal(36))
    elif change == "effective_chips":
        bad = replace(context, effective_stacks=(EffectiveStack(1, ChipAmount(999)),))
    elif change == "ranges":
        bad = replace(context, hero_range=context.villain_ranges[0],
                      villain_ranges=(context.hero_range,))
    elif change == "status":
        bad = replace(context, seats=(context.seats[0], replace(
            context.seats[1], status=PlayerStatus.FOLDED)))
    elif change == "line":
        bad = replace(context, action_line="hu-root:CHECK")
    elif change == "native_semantics":
        bad = replace(context, legal_actions=tuple(
            replace(a, amount_semantics=ActionAmountSemantics.ADDITIONAL)
            if a.action is ActionType.BET else a for a in context.legal_actions))
    elif change == "partial_menu":
        bad = replace(context, legal_actions=context.legal_actions[1:])
    else:
        bad = replace(context, assumptions=("execution_mode:simulation",))
    assert provider.query(bad).candidate is None
    assert StrategyRouter((provider,)).route(bad).selected is None


@pytest.mark.parametrize("change", [
    "drop_action", "size", "mass", "combo", "unconverged",
])
def test_MOCK_bad_saved_output_is_rejected(change):
    _, context = native_root(CASES[0])

    def modify(value):
        node = value["nodes"][0]
        if change == "drop_action":
            node["actions"].pop()
        elif change == "size":
            node["actions"][1]["amount"] += 1
        elif change == "mass":
            node["strategy"][0] = 0.9
        elif change == "combo":
            value["root_combos"][0][0]["cards"] = "2c3c"
        else:
            value["meta"]["exploitability_pct_of_pot"] = 10
    assert mock_provider(context, modify).query(context).candidate is None


@pytest.mark.parametrize("hero", ["AsAh", "8c6c"])
def test_reviewed_saved_ROOT_asset_is_read_without_running_solver(hero):
    case = Case("reviewed-river", "2c 3d 7h 9s Jc", 10, 20,
                "AsAh:1,8c6c:1", "AsKd:1,TsTh:1", hero)
    _, context = native_root(case)
    data = DEFAULT_SOLUTION.read_bytes()
    config = json.loads(data)["config"]
    provider = RootAssetProvider(
        context, config, data, sha256=digest(data),
        origin="REVIEWED_SAVED_FIXTURE")
    result = StrategyRouter((provider,)).route(context)
    assert result.state is LookupState.HIT_EXACT and not result.selected.action_ev
    assert len(result.selected.action_options) == 2
    assert "result_origin:REVIEWED_SAVED_FIXTURE" in result.selected.evidence
    assert sum(result.selected.action_probabilities.values()) == 1


def test_decimal_environment_is_preserved():
    with localcontext() as caller:
        caller.prec = 1
        caller.traps[Inexact] = caller.traps[Rounded] = True
        before = dict(caller.flags)
        _, context = native_root(CASES[0])
        assert mock_provider(context).query(context).candidate is not None
        assert caller.prec == 1 and dict(caller.flags) == before


def test_preparation_creates_three_inputs_and_never_overwrites(tmp_path):
    rows = prepare_files(tmp_path)
    assert len(rows) == 3 and all(r["new_solves"] == 0 for r in rows)
    assert all(r["status"] == "PREPARED_NOT_RUN" for r in rows)
    assert len(list(tmp_path.glob("*.toml"))) == 3
    with pytest.raises(FileExistsError):
        prepare_files(tmp_path)


def test_declared_origin_and_solution_digest_are_required():
    _, context = native_root(CASES[0])
    data = json.dumps(mock_solution(context)).encode()
    with pytest.raises(RootError, match="digest"):
        RootAssetProvider(context, request_config(context), data,
                          sha256="0" * 64, origin="MOCK_CONVERSION_ONLY")
    with pytest.raises(RootError, match="origin"):
        RootAssetProvider(context, request_config(context), data,
                          sha256=digest(data), origin="UNKNOWN")
