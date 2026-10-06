"""Private data root and old Windows path mapping."""

import json
import os
from pathlib import Path

import pytest

from poker_engine import data_paths
from poker_engine.data_paths import (
    DATA_ROOT_ENV, REPO_ROOT, archive_root, data_root, private_root,
    resolve_legacy_path)
from poker_engine.desktop.aa_reader import preflight_profile

posix_only = pytest.mark.skipif(
    os.name == "nt", reason="drive paths are real absolute paths on Windows")


def test_environment_variable_sets_the_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    assert data_root() == tmp_path
    assert private_root() == tmp_path / "PokerSense_private"
    assert archive_root() == tmp_path / "PokerSense_archive"


def test_default_data_root_keeps_windows_on_the_old_drive(monkeypatch):
    monkeypatch.delenv(DATA_ROOT_ENV, raising=False)
    expected = (Path("G:/") if os.name == "nt"
                else Path.home() / "Projects" / "PokerSense_data")
    assert data_root() == expected


def test_blank_environment_variable_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(DATA_ROOT_ENV, "  ")
    assert data_root() == data_paths._default_data_root().expanduser()


@posix_only
@pytest.mark.parametrize("value", [
    "G:/PokerSense_private/aa8_first_hand_full_v1",
    "g:\\PokerSense_private\\aa8_first_hand_full_v1",
])
def test_old_g_drive_paths_move_under_the_data_root(tmp_path, monkeypatch, value):
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path))
    assert resolve_legacy_path(value) == (
        tmp_path / "PokerSense_private" / "aa8_first_hand_full_v1")


@posix_only
def test_old_checkout_paths_move_into_this_checkout():
    value = ("C:/Users/Administrator/WorkBuddy/扑克/PokerSense/configs/vision/"
             "aa_android_capture_card/layout.json")
    assert resolve_legacy_path(value) == (
        REPO_ROOT / "configs/vision/aa_android_capture_card/layout.json")


@pytest.mark.parametrize("value", [
    "C:/Users/someone-else/file.json",   # unknown old location: not guessed
    "configs/vision/layout.json",        # ordinary relative path
    "/Users/man/data/file.json",         # POSIX absolute path
    "",
])
def test_other_paths_are_not_legacy(value):
    assert resolve_legacy_path(value) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows-only behaviour")
def test_drive_paths_are_left_alone_on_windows():
    assert resolve_legacy_path("G:/PokerSense_private/x") is None


@posix_only
def test_reader_profile_with_old_windows_paths_resolves_on_this_machine(
        tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv(DATA_ROOT_ENV, str(data))
    spec = {"audit": "a" * 64}
    for key in ("source", "context_source", "late_source", "bomb_pool"):
        folder = data / "PokerSense_private" / key
        folder.mkdir(parents=True)
        (folder / "samples.json").write_text("{}", encoding="utf-8")
        spec[key] = f"G:/PokerSense_private/{key}"
    for key in ("bank_path", "heads_path", "reservations"):
        target = data / "PokerSense_private" / key
        target.write_text("{}", encoding="utf-8")
        spec[key] = f"G:/PokerSense_private/{key}"
    layout = data / "PokerSense_private" / "layout.json"
    layout.write_text(json.dumps({
        "canvas": [498, 1080], "hero_slot": 4,
        "slots": [{"slot": i} for i in range(8)]}), encoding="utf-8")
    spec["profile_path"] = "G:\\PokerSense_private\\layout.json"
    path = tmp_path / "reader.json"
    path.write_text(json.dumps(spec), encoding="utf-8")

    result = preflight_profile(path)

    private = (data / "PokerSense_private").resolve()
    assert result["paths"]["source"] == str(private / "source")
    assert result["paths"]["profile_path"] == str(private / "layout.json")
    assert not [e for e in result["errors"] if e.startswith("missing_")]
