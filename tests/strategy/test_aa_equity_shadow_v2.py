from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from unittest.mock import Mock

import pytest

from poker_engine.core.enums import Street
from poker_engine.core.value_objects import ChipAmount
from poker_engine.strategy.aa_equity_shadow_v2 import (
    AAEquityShadowStatus,
    evaluate_aa_equity_shadow,
)
from poker_engine.strategy.aa_rules_v2 import (
    AARuleProfileV2,
    build_forced_bet_plan,
    reconcile_opening_debits,
)
from poker_engine.strategy.contracts import PotState, RangeDistribution
from poker_engine.strategy.aa_range_assets_v2 import (
    AAConcreteRangeAssetV2,
    AARangeQueryV2,
    AARangeShadowSnapshotV2,
    AARangeShadowTrackerV2,
    assess_aa_range_readiness,
)

from .helpers import NOW, context


def rules(*, verification="live_verified", distribution="proportional_all_pots",
          application="all_pots", rounding="exact"):
    return AARuleProfileV2.from_dict({
        "schema_version": 2, "table_size": 6,
        "small_blind": "0.5", "big_blind": "1", "ante": "0",
        "ante_mode": "none", "straddle_mode": "mandatory_utg",
        "straddle_amount": "2", "rake_percent": "0.10",
        "rake_cap_bb": "100", "rake_application": application,
        "rake_rounding": rounding, "rake_distribution": distribution,
        "minimum_chip": "0.5", "verification_status": verification,
        "source": "test",
    })


def inputs(*, rule=None):
    """Explicitly unbound math fixture; live positives use trusted_inputs."""
    profile = rule or rules()
    plan = build_forced_bet_plan(profile, tuple(range(6)), dealer_seat=3)
    observed = {str(seat): str(plan.contributions[seat]) for seat in range(8)}
    opening = reconcile_opening_debits(profile, plan, observed)
    base = context(6, street=Street.RIVER, active_count=3)
    source = f"aa-ranges-v2:{profile.fingerprint}:unbound:equity-math-fixture"
    ranges = (
        RangeDistribution(
            3, {"QcQd": Decimal("1")}, "unbound", source, confidence=1.0,
        ),
        RangeDistribution(
            4, {"JcJd": Decimal("1")}, "unbound", source, confidence=1.0,
        ),
    )
    pots = (
        PotState("main", ChipAmount("100"), (3, 4, 5)),
        PotState("side-1", ChipAmount("50"), (4, 5)),
    )
    ctx = replace(
        base, game_config=profile.game_config(), villain_ranges=ranges, pots=pots,
    )
    return profile, plan, opening, ctx


def trusted_inputs(tmp_path, *, rule=None):
    """Produce a snapshot through the loader/tracker using pinned fixture bytes."""
    profile, plan, opening, ctx = inputs(rule=rule)
    payload = {
        "schema_version": 2,
        "asset_id": "equity-math-fixture",
        "asset_version": "fixture-v1",
        "asset_status": "shadow_reviewed",
        "rule_fingerprint": profile.fingerprint,
        "source": {
            "url": "https://example.invalid/synthetic-equity-fixture",
            "revision": "1" * 40,
            "license_spdx": "LicenseRef-Synthetic-Test",
        },
        "limitations": ["synthetic math fixture; no empirical range evidence"],
        "nodes": [{
            "node_id": f"equity-seat-{item.seat_id}",
            "player_count": 6,
            "position": ctx.seats[item.seat_id].position.value,
            "stack_bb": str(ctx.effective_stack_bb),
            "action_line": ctx.action_line,
            "prior": [{
                "combo": combo, "weight": str(weight),
            } for combo, weight in sorted(item.combo_weights.items())],
            "action_likelihoods": {},
            "confidence": 1.0,
            "effective_sample_size": 0,
            "evidence": ["synthetic exact-river math fixture only"],
        } for item in ctx.villain_ranges],
    }
    path = tmp_path / "equity-ranges.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    asset = AAConcreteRangeAssetV2(
        path, expected_sha256=digest,
        expected_rule_fingerprint=profile.fingerprint,
    )
    tracker = AARangeShadowTrackerV2(asset)
    assert tracker.seed(tuple(AARangeQueryV2(
        item.seat_id, 6, ctx.seats[item.seat_id].position,
        ctx.effective_stack_bb, ctx.action_line,
        ctx.hero_cards + ctx.board_cards,
    ) for item in ctx.villain_ranges)) == ()
    snapshot = tracker.snapshot(hero_seat=ctx.hero_seat, pots=ctx.pots)
    assert snapshot.equity_permitted and not snapshot.blockers
    return profile, plan, opening, replace(
        ctx, villain_ranges=snapshot.distributions,
    ), snapshot


def explicit_unbound_snapshot(ctx, profile):
    readiness = assess_aa_range_readiness(
        ctx.villain_ranges, hero_seat=ctx.hero_seat, pots=ctx.pots,
        rule_fingerprint=profile.fingerprint,
    )
    return AARangeShadowSnapshotV2(
        1, ctx.villain_ranges, (), (), readiness, True,
        asset_status="unbound",
    )


def blocked_before_math(monkeypatch, ctx, profile, plan, opening, **kwargs):
    math = Mock(side_effect=AssertionError("refused input reached equity math"))
    monkeypatch.setattr(
        "poker_engine.strategy.aa_equity_shadow_v2.calculate_adaptive_equity", math,
    )
    result = evaluate_aa_equity_shadow(
        ctx, profile, plan, opening, now=kwargs.pop("now", NOW), **kwargs,
    )
    math.assert_not_called()
    assert result.status is AAEquityShadowStatus.BLOCKED
    assert result.equity_report is None
    assert result.gross_expected_chips is None
    assert result.configured_net_expected_chips is None
    assert not result.advice_emitted and not result.strategy_eligible
    return result


def test_live_verified_exact_river_reports_gross_and_proportional_net(tmp_path):
    profile, plan, opening, ctx, snapshot = trusted_inputs(tmp_path)
    assert snapshot.asset_id == "equity-math-fixture"
    assert snapshot.asset_version == "fixture-v1"
    assert snapshot.asset_status == "shadow_reviewed"
    assert snapshot.rule_fingerprint == profile.fingerprint
    assert snapshot.asset_sha256 == hashlib.sha256(
        (tmp_path / "equity-ranges.json").read_bytes()
    ).hexdigest()
    result = evaluate_aa_equity_shadow(
        ctx, profile, plan, opening, now=NOW, range_snapshot=snapshot,
    )
    assert result.status is AAEquityShadowStatus.COMPLETE
    assert result.equity_report.method.value == "exact"
    assert result.rake.amount == Decimal("15.00")
    assert result.rake_allocations == {
        "main": Decimal("10.00"), "side-1": Decimal("5.00"),
    }
    assert result.configured_net_expected_chips == (
        result.gross_expected_chips * Decimal("0.9")
    )
    assert result.reasons == ()
    assert not result.advice_emitted and not result.strategy_eligible


def test_main_pot_first_uses_each_pot_share_instead_of_global_scaling(tmp_path):
    profile, plan, opening, ctx, snapshot = trusted_inputs(
        tmp_path, rule=rules(distribution="main_pot_first"),
    )
    result = evaluate_aa_equity_shadow(
        ctx, profile, plan, opening, now=NOW, range_snapshot=snapshot,
    )
    assert result.status is AAEquityShadowStatus.COMPLETE
    assert result.rake_allocations == {
        "main": Decimal("15.00"), "side-1": Decimal("0"),
    }
    shares = {
        pot.pot_id: pot.expected_share for pot in result.equity_report.result.pots
    }
    expected = Decimal("85") * shares["main"] + Decimal("50") * shares["side-1"]
    assert result.configured_net_expected_chips == expected


def test_simulation_requires_explicit_opt_in_and_stays_simulation(monkeypatch):
    profile, plan, opening, ctx = inputs(rule=rules(verification="simulation"))
    blocked = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening, allow_untracked_ranges=True,
    )
    assert "simulation_rules_not_explicitly_enabled" in blocked.reasons
    monkeypatch.undo()
    result = evaluate_aa_equity_shadow(
        ctx, profile, plan, opening, now=NOW, allow_simulation=True,
        allow_untracked_ranges=True,
    )
    assert result.status is AAEquityShadowStatus.SIMULATION
    assert result.reasons == (
        "simulation_rules_only", "untracked_ranges_explicit_test_only",
    )
    assert not result.rake.strategy_eligible
    assert not result.advice_emitted and not result.strategy_eligible


def test_missing_ranges_and_unreconciled_opening_block_before_math(
    tmp_path, monkeypatch,
):
    profile, plan, opening, ctx, snapshot = trusted_inputs(tmp_path)
    missing = replace(ctx, villain_ranges=())
    result = blocked_before_math(
        monkeypatch, missing, profile, plan, opening, range_snapshot=snapshot,
    )
    assert "villain_ranges_missing" in result.reasons
    observed = {str(seat): str(plan.contributions[seat]) for seat in range(8)}
    observed["0"] = "99"
    bad = reconcile_opening_debits(profile, plan, observed)
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, bad, range_snapshot=snapshot,
    )
    assert "opening_forced_bets_not_exact" in result.reasons


def test_unknown_rake_distribution_blocks_net_equity(monkeypatch):
    profile = rules(
        verification="simulation", distribution="unverified",
        application="unverified", rounding="unverified",
    )
    profile, plan, opening, ctx = inputs(rule=profile)
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening, allow_simulation=True,
        allow_untracked_ranges=True,
    )
    assert result.rake.amount is None


@pytest.mark.parametrize("late_by", (timedelta(0), timedelta(microseconds=1)))
def test_expired_request_becomes_computation_blocker_not_exception(
    tmp_path, monkeypatch, late_by,
):
    profile, plan, opening, ctx, snapshot = trusted_inputs(tmp_path)
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening,
        now=ctx.request.expires_at + late_by, range_snapshot=snapshot,
    )
    assert result.reasons == (
        "equity_input_or_computation_error:equity_deadline_expired",
    )


def test_range_tracker_snapshot_is_required_by_default_and_identity_bound(
    tmp_path, monkeypatch,
):
    profile, plan, opening, ctx, snapshot = trusted_inputs(tmp_path)
    blocked = blocked_before_math(monkeypatch, ctx, profile, plan, opening)
    assert "range_tracker_snapshot_missing" in blocked.reasons
    mismatch = replace(snapshot, distributions=tuple(reversed(
        snapshot.distributions,
    )))
    blocked = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening, range_snapshot=mismatch,
    )
    assert "range_tracker_context_mismatch" in blocked.reasons


@pytest.mark.parametrize("allow_simulation,allow_untracked", (
    (False, False), (False, True), (True, False), (True, True),
))
def test_live_rules_cannot_use_missing_snapshot_flags(
    monkeypatch, allow_simulation, allow_untracked,
):
    profile, plan, opening, ctx = inputs()
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening,
        allow_simulation=allow_simulation,
        allow_untracked_ranges=allow_untracked,
    )
    assert "missing_range_snapshot_with_non_simulation_rules" in result.reasons


def test_simulation_missing_snapshot_needs_untracked_opt_in(monkeypatch):
    profile, plan, opening, ctx = inputs(rule=rules(verification="simulation"))
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening, allow_simulation=True,
    )
    assert "range_tracker_snapshot_missing" in result.reasons


@pytest.mark.parametrize("legacy_positions", (6, 8))
def test_legacy_snapshot_constructor_preserved_but_identity_missing_refuses(
    tmp_path, monkeypatch, legacy_positions,
):
    profile, plan, opening, ctx, trusted = trusted_inputs(tmp_path)
    args = (
        trusted.version, trusted.distributions, trusted.blockers, trusted.events,
        trusted.readiness, trusted.equity_permitted,
    )
    if legacy_positions == 8:
        args += (False, False)
    legacy = AARangeShadowSnapshotV2(*args)
    assert all(getattr(legacy, name) is None for name in (
        "asset_id", "asset_version", "asset_sha256", "asset_status",
        "rule_fingerprint",
    ))
    assert not legacy.advice_emitted and not legacy.strategy_eligible
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening, range_snapshot=legacy,
        allow_simulation=True, allow_untracked_ranges=True,
    )
    assert "range_snapshot_asset_identity_missing" in result.reasons


@pytest.mark.parametrize("field", (
    "asset_id", "asset_version", "asset_sha256", "asset_status",
    "rule_fingerprint",
))
def test_bound_snapshot_requires_each_identity_field(tmp_path, monkeypatch, field):
    profile, plan, opening, ctx, snapshot = trusted_inputs(tmp_path)
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening,
        range_snapshot=replace(snapshot, **{field: None}),
    )
    assert "range_snapshot_asset_identity_missing" in result.reasons


@pytest.mark.parametrize("field,value,reason", (
    ("asset_id", "other-fixture", "range_snapshot_asset_identity_mismatch"),
    ("asset_version", "fixture-v2", "range_snapshot_asset_identity_mismatch"),
    ("asset_sha256", "a" * 64, "range_snapshot_asset_identity_mismatch"),
    ("asset_status", "live_approved", "range_snapshot_asset_identity_mismatch"),
    ("rule_fingerprint", "b" * 64, "range_snapshot_rule_fingerprint_mismatch"),
))
def test_bound_snapshot_identity_cannot_relabel_ranges(
    tmp_path, monkeypatch, field, value, reason,
):
    profile, plan, opening, ctx, snapshot = trusted_inputs(tmp_path)
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening,
        range_snapshot=replace(snapshot, **{field: value}),
    )
    assert reason in result.reasons


@pytest.mark.parametrize("changes", (
    {"equity_permitted": False},
    {"blockers": ("range_action_likelihood_missing:3:call",)},
))
def test_tracker_permission_and_blockers_refuse_before_math(
    tmp_path, monkeypatch, changes,
):
    profile, plan, opening, ctx, snapshot = trusted_inputs(tmp_path)
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening,
        range_snapshot=replace(snapshot, **changes),
    )
    assert "range_tracker_snapshot_not_permitted" in result.reasons


@pytest.mark.parametrize("mismatch", ("context", "plan"))
def test_wrong_rules_refuse_before_math(tmp_path, monkeypatch, mismatch):
    profile, plan, opening, ctx, snapshot = trusted_inputs(tmp_path)
    if mismatch == "context":
        wrong = replace(profile, rake_percent=Decimal("0.05"))
        ctx = replace(ctx, game_config=wrong.game_config())
        reason = "decision_context_rule_profile_mismatch"
    else:
        plan = replace(plan, rules_fingerprint="b" * 64)
        reason = "forced_bet_plan_rule_fingerprint_mismatch"
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening, range_snapshot=snapshot,
    )
    assert reason in result.reasons


def test_invalid_rule_verification_is_rejected_before_math(monkeypatch):
    math = Mock(side_effect=AssertionError("invalid rules reached equity math"))
    monkeypatch.setattr(
        "poker_engine.strategy.aa_equity_shadow_v2.calculate_adaptive_equity", math,
    )
    with pytest.raises(ValueError, match="invalid verification_status"):
        rules(verification="unverified")
    math.assert_not_called()


@pytest.mark.parametrize("snapshot_present", (False, True))
def test_bound_ranges_cannot_use_untracked_simulation_escape(
    tmp_path, monkeypatch, snapshot_present,
):
    profile, plan, opening, ctx, trusted = trusted_inputs(
        tmp_path, rule=rules(verification="simulation"),
    )
    snapshot = None
    if snapshot_present:
        snapshot = AARangeShadowSnapshotV2(
            trusted.version, trusted.distributions, (), (), trusted.readiness,
            True, asset_status="unbound",
        )
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening, range_snapshot=snapshot,
        allow_simulation=True, allow_untracked_ranges=True,
    )
    reason = (
        "unbound_snapshot_cannot_wrap_bound_ranges" if snapshot_present else
        "missing_snapshot_cannot_wrap_bound_ranges"
    )
    assert reason in result.reasons


@pytest.mark.parametrize("allow_simulation,allow_untracked", (
    (False, False), (False, True), (True, False),
))
def test_explicit_unbound_snapshot_needs_both_simulation_opt_ins(
    monkeypatch, allow_simulation, allow_untracked,
):
    profile, plan, opening, ctx = inputs(rule=rules(verification="simulation"))
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening,
        range_snapshot=explicit_unbound_snapshot(ctx, profile),
        allow_simulation=allow_simulation,
        allow_untracked_ranges=allow_untracked,
    )
    if not allow_simulation:
        assert "simulation_rules_not_explicitly_enabled" in result.reasons
    if not allow_untracked:
        assert "unbound_range_snapshot_requires_test_opt_in" in result.reasons


def test_explicit_unbound_snapshot_cannot_use_live_rules(monkeypatch):
    profile, plan, opening, ctx = inputs()
    result = blocked_before_math(
        monkeypatch, ctx, profile, plan, opening,
        range_snapshot=explicit_unbound_snapshot(ctx, profile),
        allow_simulation=True, allow_untracked_ranges=True,
    )
    assert "unbound_range_snapshot_with_non_simulation_rules" in result.reasons


def test_explicit_unbound_snapshot_is_disclosed_simulation_only():
    profile, plan, opening, ctx = inputs(rule=rules(verification="simulation"))
    result = evaluate_aa_equity_shadow(
        ctx, profile, plan, opening, now=NOW,
        range_snapshot=explicit_unbound_snapshot(ctx, profile),
        allow_simulation=True, allow_untracked_ranges=True,
    )
    assert result.status is AAEquityShadowStatus.SIMULATION
    assert "simulation_rules_only" in result.reasons
    assert "untracked_ranges_explicit_test_only" in result.reasons
    assert result.equity_report.method.value == "exact"
    assert not result.rake.strategy_eligible
    assert not result.advice_emitted and not result.strategy_eligible


@pytest.mark.parametrize("suffix", (
    "test", "unbound", "unbound:", "unbound:fixture@" + "a" * 64,
    "equity-math-fixture:fixture-v1@" + "a" * 64,
    "equity-math-fixture:fixture-v1@" + "a" * 64 + ":shadow_reviewed",
))
def test_old_or_malformed_sources_cannot_take_untracked_escape(
    monkeypatch, suffix,
):
    profile, plan, opening, ctx = inputs(rule=rules(verification="simulation"))
    ranges = tuple(replace(
        item, source_version=f"aa-ranges-v2:{profile.fingerprint}:{suffix}",
    ) for item in ctx.villain_ranges)
    result = blocked_before_math(
        monkeypatch, replace(ctx, villain_ranges=ranges), profile, plan, opening,
        allow_simulation=True, allow_untracked_ranges=True,
    )
    assert "untracked_range_source_not_explicitly_unbound" in result.reasons


def test_stripped_source_header_retaining_asset_source_cannot_bypass(
    tmp_path, monkeypatch,
):
    profile, plan, opening, ctx, snapshot = trusted_inputs(
        tmp_path, rule=rules(verification="simulation"),
    )
    stripped = tuple(replace(
        item,
        source_version=f"aa-ranges-v2:{profile.fingerprint}:unbound:stripped",
    ) for item in snapshot.distributions)
    assert all(item.source == "equity-math-fixture" for item in stripped)
    result = blocked_before_math(
        monkeypatch, replace(ctx, villain_ranges=stripped), profile, plan, opening,
        allow_simulation=True, allow_untracked_ranges=True,
    )
    assert "untracked_range_source_not_explicitly_unbound" in result.reasons
