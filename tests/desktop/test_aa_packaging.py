"""Offline package acceptance: identity, resources and no implicit capture."""

import importlib.util
import json
from pathlib import Path
import socket
import sys
import tomllib

from fastapi.testclient import TestClient
import pytest

from poker_engine import __version__


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "aa_package_entry", ROOT / "packaging" / "aa_live_entry.py")
entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entry)


def test_public_package_offline_preflight_does_not_write(tmp_path, capsys):
    state = tmp_path / "state"
    assert entry.main(["--self-check", "--state", str(state)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["version"] == __version__ == "0.2.0.dev1"
    assert report["missing_resources"] == []
    assert report["external_model"] == "NOT_CONFIGURED_OFFLINE_AVAILABLE"
    assert report["capture_enabled"] is False
    assert report["strategy_eligible"] is False
    assert not state.exists()


def test_missing_public_files_fail_before_state_or_server(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(entry, "resource_root", lambda: tmp_path)
    state = tmp_path / "state"
    assert entry.main(["--state", str(state), "--no-browser"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert "ui/aa-live/index.html" in report["missing_resources"]
    assert not state.exists()


def test_offline_http_identity_and_capture_refusal(tmp_path):
    args = entry.parser().parse_args(["--state", str(tmp_path), "--no-browser"])
    with TestClient(entry.create_app(args)) as client:
        identity = client.get("/api/build").json()
        assert identity["product"] == "PokerSense-AA"
        assert identity["version"] == __version__
        assert identity["entrypoint"] == "poker_engine.desktop.aa_server"
        assert client.get("/").status_code == 200
        for resource in ("app.js", "style.css", "hand_input.js",
                         "analysis_records.js"):
            assert client.get("/" + resource).status_code == 200
        status = client.get("/api/status").json()
        assert status["capture_available"] is False
        assert status["replay_available"] is False
        assert status["profile"]["ready"] is False
        assert status["strategy_scope"] == "AA8_OBSERVATION_ONLY_NO_ADVICE"
        response = client.post("/api/start", json={"mode": "capture-card"},
                               headers={"X-AA-Live": "1"})
        assert response.status_code == 403


def test_explicit_capture_requires_external_profile():
    with pytest.raises(SystemExit) as error:
        entry.main(["--allow-capture", "--self-check"])
    assert error.value.code == 2


def test_listener_preserves_busy_service():
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", 0))
        existing.listen(1)
        occupied = existing.getsockname()[1]
        with entry.open_listener(occupied) as listener:
            assert listener.getsockname()[0] == "127.0.0.1"
            assert listener.getsockname()[1] != occupied
            assert existing.getsockname()[1] == occupied


def test_frozen_resources_use_bundle_root(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert entry.resource_root() == tmp_path


def test_versions_and_canonical_windows_installer_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert project["project"]["version"] == __version__
    dispatch = (ROOT / "packaging/pokersense.spec").read_text("utf-8")
    assert "'aa_live.spec' if sys.platform == 'win32'" in dispatch
    installer = (ROOT / "packaging/pokersense.iss").read_text("utf-8")
    assert '#define MyAppExeName "PokerSense-AA.exe"' in installer
    assert '#define MyAppVersion "0.2.0-dev1"' in installer
    assert "AllowNoIcons=yes" in installer
    assert 'Source: "..\\dist\\PokerSense-AA\\*"' in installer
    windows = (ROOT / "packaging/windows-version.txt").read_text("utf-8")
    assert "'ProductVersion', '" + __version__ + "'" in windows
