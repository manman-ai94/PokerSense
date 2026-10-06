"""Saved-row differentials, scope refusal and the real offline CLI entry."""

import copy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import runpy
import subprocess

import pytest

from poker_engine.core.enums import ActionType
from poker_engine.strategy.frozen_postflop import (
    DEFAULT_SOLUTION,
    ENGINE_PIN,
    FrozenLookupError,
    FrozenPostflopProvider,
    MAX_REQUEST_BYTES,
    SOLUTION_SHA256,
    decode_request,
)
from poker_engine.strategy.provider import LookupState, ProviderResult


ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "docs" / "examples" / "frozen-postflop"


def request(scene="root-oop-aa", combo=None):
    value = json.loads((EXAMPLES / f"{scene}.json").read_text("utf-8"))
    if combo is not None:
        value["decision"]["hero_combo"] = combo
    return value


@pytest.mark.parametrize("scene,combo,node,slot,raw", [
    ("root-oop-aa", "AsAh", 0, 1, ("1.0807657e-7", "0.99999994")),
    ("root-oop-aa", "8c6c", 0, 0, ("0.66672975", "0.3332702")),
    ("ip-after-check-ak", "AsKd", 1, 1, ("0.81048936", "0.18951064")),
    ("ip-after-check-ak", "TsTh", 1, 0, ("0.99999595", "0.0000040539303")),
    ("oop-facing-bet-aa", "AsAh", 3, 1, ("0.0052066506", "0.9947933")),
    ("oop-facing-bet-aa", "8c6c", 3, 0, ("1.0", "8.439969e-10")),
    ("ip-facing-bet-tt", "AsKd", 6, 1, ("1.1254346e-9", "1.0")),
    ("ip-facing-bet-tt", "TsTh", 6, 0, ("0.6668206", "0.3331794")),
])
def test_eight_saved_rows_match_original_action_major_index(
    scene, combo, node, slot, raw,
):
    provider = FrozenPostflopProvider()
    value = request(scene, combo)
    output = provider.query_json(value)
    result = provider.query(value)
    assert isinstance(result, ProviderResult)
    assert result.state is LookupState.HIT_EXACT
    assert output["saved_node"] == node
    assert output["saved_combo_slot"] == slot
    assert [Decimal(a["saved_probability"]) for a in output["actions"]] == list(
        map(Decimal, raw))
    assert abs(Decimal(output["raw_probability_mass"]) - 1) <= Decimal("5e-8")
    with localcontext() as context:
        context.prec = 40
        assert sum(result.candidate.action_probabilities.values()) == 1
        for a, probability in zip(
            output["actions"], result.candidate.action_probabilities.values(),
        ):
            assert Decimal(a["probability"]) == probability
            assert abs(probability - Decimal(a["saved_probability"])) <= Decimal("5e-8")
    assert result.candidate.action_ev == {}
    assert output["candidate"]["action_ev"] == {}
    assert output["action_ev_status"] == "NOT_SUPPORTED"
    assert output["engine_pin"] == ENGINE_PIN
    assert output["solution_sha256"] == SOLUTION_SHA256
    assert output["source_engine"] == "ucsandman/postflop"
    assert output["exploitability_bb100"] is None
    assert output["live_eligible"] is False
    assert output["advice_emitted"] is False
    assert output["strategy_eligible"] is False
    assert output["candidate"]["confidence"] == 0.0
    amounts = ["0", "5.0"] if node in (0, 1) else ["0", "5"]
    assert [a["amount_chips"] for a in output["actions"]] == amounts
    if node in (0, 1):
        assert result.candidate.recommended_sizes[ActionType.BET][0].value == 5
        assert output["actions"][1]["amount_semantics"] == "total_street"
    else:
        assert output["actions"][1]["amount_semantics"] == "additional"
        assert result.candidate.recommended_sizes == {}


def mutate(value, path, replacement):
    out = copy.deepcopy(value)
    target = out
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    return out


@pytest.mark.parametrize("path,value", [
    (("schema_version",), True),
    (("execution_mode",), "live"),
    (("execution_mode",), "online"),
    (("source_engine",), "unknown"),
    (("engine_pin",), "0" * 40),
    (("solution_sha256",), "0" * 64),
    (("identity", "state_version"), False),
    (("model", "active_player_count"), 3),
    (("model", "dealt_player_count"), 6),
    (("model", "oop_seat"), False),
    (("model", "street"), "turn"),
    (("model", "board", 4), "Jd"),
    (("model", "board"), None),
    (("model", "unit"), "bb"),
    (("model", "big_blind_chips"), "1"),
    (("model", "starting_pot_chips"), "11"),
    (("model", "initial_stacks_chips", 0), "21"),
    (("model", "ranges", "oop", 0, "weight"), "2"),
    (("model", "ranges", "ip", 0, "weight"), 1.0),
    (("model", "ranges", "ip", 0, "combo"), "2cAs"),
    (("model", "ranges", "oop", 0, "combo"), "6c8c"),
    (("model", "rules"), None),
    (("model", "rules", "variant"), "UNKNOWN"),
    (("model", "rules", "rake_percent"), "0.01"),
    (("model", "rules", "icm"), 0),
    (("model", "rules", "straddle"), 1),
    (("model", "rules", "allow_all_in"), "false"),
    (("model", "rules", "raise_cap"), False),
    (("model", "rules", "locks"), None),
    (("decision", "path"), ["CHECK", "CHECK"]),
    (("decision", "path"), [{}]),
    (("decision", "hero_seat"), False),
    (("decision", "hero_combo"), "AsAs"),
    (("decision", "hero_combo"), "KsKh"),
    (("decision", "pot_chips"), "15"),
    (("decision", "stacks_chips", 0), "19"),
    (("decision", "street_committed_chips", 0), "1"),
    (("decision", "legal_actions", 1, "action"), "RAISE"),
    (("decision", "legal_actions", 1, "amount_chips"), "6"),
    (("decision", "legal_actions", 1, "amount_semantics"), "additional"),
    (("decision", "legal_actions"), []),
    (("decision", "pot_chips"), True),
    (("decision", "pot_chips"), 10.0),
    (("decision", "pot_chips"), "NaN"),
    (("decision", "pot_chips"), "foo"),
    (("decision", "pot_chips"), "-1"),
])
def test_unmatched_or_unknown_inputs_have_no_candidate(path, value):
    output = FrozenPostflopProvider().query_json(mutate(request(), path, value))
    assert output["status"] == "REJECTED"
    assert output["candidate"] is None
    assert output["reasons"]
    assert "actions" not in output and "model_metrics" not in output
    assert output["live_eligible"] is False


def test_no_implicit_missing_rules_or_extra_schema_fields():
    provider = FrozenPostflopProvider()
    value = request()
    del value["model"]["rules"]
    assert provider.query(value).state is LookupState.REJECTED
    value = request()
    value["model"]["rules"]["room"] = "UNKNOWN"
    assert provider.query(value).state is LookupState.REJECTED


def test_combo_and_range_order_are_canonical_but_weights_are_exact():
    value = request(combo="AhAs")
    baseline = FrozenPostflopProvider().query_json(value)["candidate"]
    value["model"]["ranges"]["oop"].reverse()
    value["model"]["ranges"]["ip"].reverse()
    value["model"]["ranges"]["oop"][1]["combo"] = "AhAs"
    assert FrozenPostflopProvider().query_json(value)["candidate"] == baseline


def test_simulation_mode_and_decimal_context_do_not_change_saved_row():
    value = request()
    baseline = FrozenPostflopProvider().query_json(value)
    value["execution_mode"] = "simulation"
    with localcontext() as context:
        context.prec = 6
        assert FrozenPostflopProvider().query_json(value) == baseline


def test_meta_gain_keeps_raw_br_semantics_and_root_ev_stays_aggregate():
    metrics = FrozenPostflopProvider().query_json(request())["model_metrics"]
    assert metrics["raw_br_chips"] == ["-1.110598", "1.111216"]
    assert metrics["profile_root_ev_chips"] == ["-1.1111107", "1.1111108"]
    assert metrics["total_deviation_chips"] == "0.00061798096"
    assert metrics["scope"] == "range_aggregate_saved_profile_not_action_ev"
    assert metrics["bb_chips"] is None and metrics["exploitability_bb100"] is None


def test_tampered_asset_is_rejected_before_use_and_original_stays_unchanged(tmp_path):
    raw = DEFAULT_SOLUTION.read_bytes()
    tampered = tmp_path / "solution.json"
    tampered.write_bytes(raw.replace(b"1100", b"1101"))
    with pytest.raises(FrozenLookupError, match="solution_digest_mismatch"):
        FrozenPostflopProvider(tampered)
    assert DEFAULT_SOLUTION.read_bytes() == raw


@pytest.mark.parametrize("raw", [
    b'{"schema_version":1,"schema_version":1}', b'{"pot":NaN}',
    b'{}' * (MAX_REQUEST_BYTES // 2 + 1), b'\xff', b'{',
    b'{"x":' + b'1' * 5000 + b'}',
    b'[' * 1000 + b'0' + b']' * 1000,
], ids=["duplicate-key", "nonfinite", "oversize", "invalid-utf8", "bad-json",
        "oversize-integer", "nested-array"])
def test_request_decoder_refuses_duplicate_nonfinite_oversized_or_bad_json(raw):
    with pytest.raises(FrozenLookupError):
        decode_request(raw)


def test_lookup_launches_no_external_process(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("frozen lookup must not start any process")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert FrozenPostflopProvider().query(request()).state is LookupState.HIT_EXACT


@pytest.mark.parametrize("scene", [
    "root-oop-aa", "ip-after-check-ak", "oop-facing-bet-aa", "ip-facing-bet-tt",
])
def test_real_cli_main_queries_examples(scene, capsys):
    main = runpy.run_path(str(ROOT / "tools" / "query_frozen_postflop.py"))["main"]
    assert main(["--request", str(EXAMPLES / f"{scene}.json")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "HIT_EXACT"
    assert output["candidate"]["request_id"] == scene
    assert output["live_eligible"] is False


def test_cli_combo_override_and_refusal(tmp_path, capsys):
    main = runpy.run_path(str(ROOT / "tools" / "query_frozen_postflop.py"))["main"]
    assert main(["--request", str(EXAMPLES / "root-oop-aa.json"),
                 "--hero-combo", "8c6c"]) == 0
    assert json.loads(capsys.readouterr().out)["saved_combo_slot"] == 0
    bad = tmp_path / "bad-request.json"
    bad.write_text(json.dumps(mutate(request(), ("execution_mode",), "live")), "utf-8")
    assert main(["--request", str(bad)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["candidate"] is None
    assert output["reasons"] == ["offline_or_simulation_only"]
