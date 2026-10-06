from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from poker_engine.strategy.aa_equity_shadow_v2 import AAEquityShadowStatus
from tools import run_aa_equity_shadow_synthetic as runner
from tools.run_aa_equity_shadow_synthetic import build_case, run


@pytest.mark.parametrize("count", (6, 7, 8))
def test_synthetic_cases_exercise_exact_equity_without_advice(count):
    result = build_case(count)
    assert runner.rules(count).verification_status == "simulation"
    assert result.status is AAEquityShadowStatus.SIMULATION
    assert result.reasons == (
        "simulation_rules_only", "untracked_ranges_explicit_test_only",
    )
    assert result.equity_report.method.value == "exact"
    assert result.rake.amount == 4
    assert result.gross_expected_chips == 150
    assert result.configured_net_expected_chips == 146
    assert not result.rake.strategy_eligible
    assert not result.advice_emitted and not result.strategy_eligible


def test_synthetic_runner_explicitly_labels_unbound_input_and_both_opt_ins(
    monkeypatch,
):
    evaluate = Mock(wraps=runner.evaluate_aa_equity_shadow)
    monkeypatch.setattr(runner, "evaluate_aa_equity_shadow", evaluate)
    result = build_case(6)
    assert result.status is AAEquityShadowStatus.SIMULATION
    evaluate.assert_called_once()
    ctx, profile, plan, opening = evaluate.call_args.args
    kwargs = evaluate.call_args.kwargs
    assert profile.verification_status == "simulation"
    assert plan.rules_fingerprint == profile.fingerprint
    assert opening.status == "EXACT_FORCED_BETS"
    assert kwargs["allow_simulation"] is True
    assert kwargs["allow_untracked_ranges"] is True
    assert kwargs.get("range_snapshot") is None
    prefix = f"aa-ranges-v2:{profile.fingerprint}:unbound:"
    assert all(
        item.source == "unbound" and item.source_version.startswith(prefix)
        and item.source_version[len(prefix):] and "@" not in item.source_version
        for item in ctx.villain_ranges
    )


def test_synthetic_flags_cannot_promote_live_rules_and_refuse_before_math(
    monkeypatch,
):
    original_rules = runner.rules
    monkeypatch.setattr(runner, "rules", lambda count: replace(
        original_rules(count), verification_status="live_verified",
    ))
    math = Mock(side_effect=AssertionError("live untracked input reached math"))
    monkeypatch.setattr(
        "poker_engine.strategy.aa_equity_shadow_v2.calculate_adaptive_equity", math,
    )
    result = build_case(6)
    math.assert_not_called()
    assert result.status is AAEquityShadowStatus.BLOCKED
    assert "missing_range_snapshot_with_non_simulation_rules" in result.reasons
    assert result.equity_report is None
    assert not result.advice_emitted and not result.strategy_eligible


def test_report_is_explicitly_synthetic_and_immutable(tmp_path):
    report = run(tmp_path / "first")
    assert len(report["results"]) == 3
    assert report["real_visual_input"] is False
    assert report["provider_executed"] is False
    assert report["advice_emitted"] is False
    assert report["strategy_eligible"] is False
    assert all(row["status"] == "SIMULATION" for row in report["results"])
    assert all(row["reasons"] == [
        "simulation_rules_only", "untracked_ranges_explicit_test_only",
    ] for row in report["results"])
    assert json.loads((tmp_path / "first" / "report.json").read_text(
        encoding="utf-8",
    )) == report
    with pytest.raises(FileExistsError):
        run(tmp_path / "first")
