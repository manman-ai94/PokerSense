import json
from pathlib import Path

import pytest

from poker_engine.desktop.aa_table_config import (
    AATableConfigStore, STACK_RANGE, empty_config, validate_config,
)
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2


def complete():
    return {**empty_config(), "dealt_players": 8, "small_blind": "2",
            "big_blind": "4", "ante": "1", "straddle_amount": "8",
            "straddle_mode": "mandatory_utg", "rake_percent": "3",
            "rake_cap_bb": "2", "minimum_chip": "1",
            "rake_application": "all_pots", "rake_rounding": "exact",
            "rake_distribution": "proportional_all_pots",
            "insurance": "off", "bomb": "off", "mushroom": "off"}


def test_no_default_rules_and_never_promotes_user_declaration():
    result = validate_config(empty_config())
    assert result["pending_fields"] and result["simulation_rules"] is None
    result = validate_config(complete())
    assert result["conditional_analysis_ready"]
    assert result["simulation_rules"]["rake_percent"] == "0.03"
    assert result["simulation_rules"]["verification_status"] == "simulation"
    assert result["source"] == "MANUAL_DECLARATION"
    assert not result["live_strategy_eligible"] and not result["visual_verified"]


@pytest.mark.parametrize("field,value", [
    ("small_blind", "4"), ("rake_percent", "101"), ("big_blind", "NaN"),
    ("ante", -1), ("minimum_chip", "0"), ("straddle_amount", "2"),
    ("dealt_players", True), ("ante", "0.01"),
])
def test_contradictory_or_inexact_rules_reject(field, value):
    with pytest.raises(ValueError):
        validate_config({**complete(), field: value})


def test_special_modes_retained_and_block_conditional_analysis():
    result = validate_config({**complete(), "bomb": "on"})
    assert result["unsupported_effects"] == ["bomb"]
    assert result["simulation_rules"] is None


def test_atomic_persistence_revision_conflict_and_reset(tmp_path):
    path = tmp_path / "aa-rules.json"
    store = AATableConfigStore(path)
    first = store.get()
    saved = store.save(complete(), first["revision"])
    assert AATableConfigStore(path).get() == saved
    with pytest.raises(ValueError, match="其他页面"):
        store.save(empty_config(), first["revision"])
    reset = store.save(empty_config(), saved["revision"])
    assert not reset["conditional_analysis_ready"]
    assert AATableConfigStore(path).get() == reset


def with_range(document=None):
    return {**(complete() if document is None else document),
            STACK_RANGE[0]: "50.00", STACK_RANGE[1]: "200"}


def legacy(document):
    return {key: value for key, value in document.items() if key not in STACK_RANGE}


def test_range_is_optional_metadata_and_preserves_exact_legacy_rule_identity():
    old = legacy(complete())
    without = validate_config(old)
    ranged = validate_config(with_range())
    assert all(without["document"][key] is None for key in STACK_RANGE)
    assert not any(key in without["pending_fields"] for key in STACK_RANGE)
    assert without["conditional_analysis_ready"]
    assert ranged["document"][STACK_RANGE[0]] == "50.00"
    assert ranged["revision"] != without["revision"]
    assert ranged["simulation_rules"] == without["simulation_rules"]
    # This is the source digest of the old complete() payload before metadata.
    expected_source = ("manual-table-settings:"
                       "97dfe6ef1931542e7fe2dbb3c890cfbe15f"
                       "c0d604f31894d5916e00c51a45d7c")
    assert ranged["simulation_rules"]["source"] == expected_source
    assert not any(key in ranged["simulation_rules"] for key in STACK_RANGE)
    assert (AARuleProfileV2.from_dict(ranged["simulation_rules"]).fingerprint
            == AARuleProfileV2.from_dict(without["simulation_rules"]).fingerprint)
    # Existing source fields stay bound; labels were part of the old identity.
    renamed = validate_config({**with_range(), "table_label": "another table"})
    assert renamed["simulation_rules"]["source"] != expected_source
    assert not ranged["live_strategy_eligible"] and not ranged["visual_verified"]


@pytest.mark.parametrize("low,high", [
    (None, "200"), ("50", None), ("201", "200"), ("0", "200"),
    ("-1", "200"), (50, "200"), (True, "200"), ("", "200"),
    ("NaN", "200"), ("50", "Infinity"), ("50", "1e13"),
    ("0.000000001", "200"), ("0" * 33, "200"),
])
def test_invalid_range_rejects(low, high):
    with pytest.raises(ValueError):
        validate_config({**complete(), STACK_RANGE[0]: low, STACK_RANGE[1]: high})


@pytest.mark.parametrize("amount", ["100", "0.00000001", "1e12"])
def test_equal_positive_range_boundaries_are_valid(amount):
    result = validate_config({**complete(),
                              STACK_RANGE[0]: amount, STACK_RANGE[1]: amount})
    assert result["document"][STACK_RANGE[0]] == amount


def test_legacy_file_load_defaults_without_rewriting_then_persists_metadata(tmp_path):
    path = tmp_path / "rules.json"
    original = json.dumps(legacy(complete()), ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)
    store = AATableConfigStore(path)
    first = store.get()
    assert path.read_bytes() == original
    assert all(first["document"][key] is None for key in STACK_RANGE)
    saved = store.save(with_range(first["document"]), first["revision"])
    assert AATableConfigStore(path).get() == saved
    assert json.loads(path.read_text(encoding="utf-8"))[STACK_RANGE[0]] == "50.00"


def test_legacy_posts_preserve_metadata_explicit_nulls_clear_and_pair_is_merged():
    store = AATableConfigStore()
    first = store.save(with_range(), store.get()["revision"])
    preserved = store.save({**legacy(complete()), "table_label": "renamed"},
                           first["revision"])
    assert all(preserved["document"][key] == first["document"][key]
               for key in STACK_RANGE)
    partial = {**legacy(complete()), STACK_RANGE[0]: "75"}
    changed = store.save(partial, preserved["revision"])
    assert changed["document"][STACK_RANGE[0]] == "75"
    assert changed["document"][STACK_RANGE[1]] == "200"
    # An explicit null on one side cannot silently discard the other side.
    with pytest.raises(ValueError, match="同时填写"):
        store.save({**legacy(complete()), STACK_RANGE[0]: None}, changed["revision"])
    assert store.get() == changed
    cleared = store.save({**legacy(complete()), **dict.fromkeys(STACK_RANGE)},
                         changed["revision"])
    assert all(cleared["document"][key] is None for key in STACK_RANGE)


@pytest.mark.parametrize("mutate", [
    lambda doc: {key: value for key, value in doc.items() if key != "ante"},
    lambda doc: {**doc, "unrecognized_field": None},
    lambda doc: {**doc, STACK_RANGE[0]: "300"},
])
def test_bad_document_leaves_disk_and_memory_unchanged(tmp_path, mutate):
    path = tmp_path / "rules.json"
    store = AATableConfigStore(path)
    saved = store.save(with_range(), store.get()["revision"])
    disk = path.read_bytes()
    with pytest.raises(ValueError):
        store.save(mutate(saved["document"]), saved["revision"])
    assert store.get() == saved and path.read_bytes() == disk


def test_stale_legacy_request_cannot_clear_metadata_or_stop_current_save(tmp_path):
    path = tmp_path / "rules.json"
    store = AATableConfigStore(path)
    prior = store.get()
    saved = store.save(with_range(), prior["revision"])
    disk = path.read_bytes()
    with pytest.raises(ValueError, match="其他页面"):
        store.save(legacy(complete()), prior["revision"])
    assert store.get() == saved and path.read_bytes() == disk


def test_disk_replace_failure_preserves_memory_and_file_and_removes_temporary(
        tmp_path, monkeypatch):
    path = tmp_path / "rules.json"
    store = AATableConfigStore(path)
    saved = store.save(with_range(), store.get()["revision"])
    disk = path.read_bytes()

    def fail_replace(source, target):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic disk failure"):
        store.save(empty_config(), saved["revision"])
    assert store.get() == saved and path.read_bytes() == disk
    assert list(tmp_path.iterdir()) == [path]


def test_zero_is_known_not_unknown_and_percent_is_scaled_only_in_rules():
    known = {**complete(), "ante": "0", "rake_percent": "0", "rake_cap_bb": "0",
             "straddle_mode": "none", "straddle_amount": None}
    result = validate_config(known)
    assert result["pending_fields"] == []
    assert result["simulation_rules"]["rake_cap_bb"] == "0"
    assert result["simulation_rules"]["rake_percent"] == "0"
    unknown = validate_config({**known, "ante": None, "rake_percent": None})
    assert {"ante", "rake_percent"} <= set(unknown["pending_fields"])
    assert unknown["simulation_rules"] is None
