"""Offline package acceptance: identity, resources and no implicit capture."""

import importlib.util
import json
from pathlib import Path
import shutil
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


def test_the_desktop_entry_stops_an_unwatched_source_after_three_minutes(tmp_path):
    # A closed browser window releases the capture card (aa_server.IdleStop).
    assert entry.parser().parse_args(["--state", str(tmp_path)]).idle_stop == 180
    assert entry.parser().parse_args(["--idle-stop", "0"]).idle_stop == 0
    app = entry.create_app(entry.parser().parse_args(["--state", str(tmp_path)]))
    assert app.state.idle_stop.seconds == 180


def test_a_mac_with_chrome_opens_the_page_in_chrome(tmp_path):
    """The small always-on-top window needs Chrome; Safari has no such window."""
    chrome = tmp_path / "Google Chrome.app"
    calls, fallback = [], []

    def run(command, **kwargs):
        calls.append(command)

    url = "http://127.0.0.1:5000/"
    entry.open_page(url, platform="darwin", chrome=tmp_path / "none.app", run=run,
                    fallback=fallback.append)
    assert (calls, fallback) == ([], [url])            # no Chrome: the default
    chrome.mkdir()
    entry.open_page(url, platform="darwin", chrome=chrome, run=run,
                    fallback=fallback.append)
    assert calls == [["open", "-a", str(chrome), url]] and fallback == [url]
    entry.open_page(url, platform="win32", chrome=chrome, run=run,
                    fallback=fallback.append)
    assert len(calls) == 1 and fallback == [url, url]  # Windows: the default

    def broken(command, **kwargs):
        raise entry.subprocess.CalledProcessError(1, command)
    entry.open_page(url, platform="darwin", chrome=chrome, run=broken,
                    fallback=fallback.append)
    assert fallback == [url, url, url]


def test_a_new_launch_closes_the_older_window_on_its_port():
    # lsof lists this process, an older window and another program.
    commands = {"201": ".venv/bin/python packaging/aa_live_entry.py --allow-capture",
                "305": "/usr/sbin/someserver"}
    calls, kills, stops, alive = [], [], [], {201: 2, 305: 99}

    def run(command, **kwargs):
        calls.append(command[0])
        out = "100\n201\n305\n" if command[0] == "lsof" else commands[command[-1]]
        return entry.subprocess.CompletedProcess(command, 0, stdout=out)

    def kill(pid, sig):
        kills.append((pid, sig))
        if sig == 0:
            alive[pid] -= 1
            if alive[pid] < 0:
                raise ProcessLookupError(pid)

    closed = entry.take_over(8771, run=run, kill=kill, stop=stops.append, me=100,
                             sleep=lambda seconds: None)
    assert closed == [201] and stops == [8771]
    assert kills[0] == (201, entry.signal.SIGTERM)       # a normal kill, then waits
    assert {pid for pid, _ in kills} == {201}             # the other program is left
    assert calls == ["lsof", "ps", "ps"]


def test_without_lsof_nothing_is_closed():
    def run(command, **kwargs):
        raise FileNotFoundError(command[0])
    assert entry.take_over(8771, run=run, kill=None, stop=None) == []


@pytest.mark.skipif(entry.os.name == "nt" or shutil.which("lsof") is None,
                    reason="needs lsof (macOS, Linux)")
def test_a_second_launch_takes_the_port_of_the_first(tmp_path):
    import subprocess
    import time
    import urllib.request

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    processes = []

    def launch(name):
        ready = tmp_path / f"{name}.json"
        processes.append(subprocess.Popen(
            [sys.executable, str(ROOT / "packaging" / "aa_live_entry.py"),
             "--no-browser", "--state", str(tmp_path / "state"), "--port", str(port),
             "--ready-file", str(ready)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace"))
        deadline = time.monotonic() + 90
        while not ready.is_file() or not ready.read_text(encoding="utf-8"):
            assert processes[-1].poll() is None, processes[-1].stdout.read()[-1500:]
            assert time.monotonic() < deadline, f"{name} never got ready"
            time.sleep(0.1)
        return json.loads(ready.read_text(encoding="utf-8"))["base"]

    try:
        first = launch("first")
        # A page polls the first window, as Chrome does.
        status = urllib.request.Request(first + "api/status",
                                        headers={"X-AA-Live": "1"})
        urllib.request.urlopen(status, timeout=10).read()
        second = launch("second")
        assert first == f"http://127.0.0.1:{port}/"
        assert second == first
        assert processes[0].wait(timeout=20) is not None
        assert "关掉了之前开着的窗口" in processes[1].stdout.readline()
    finally:
        for process in processes:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
