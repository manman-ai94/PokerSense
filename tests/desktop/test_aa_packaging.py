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
    # The record button's encoder works here; the solver answers either way.
    assert report["recorder_ready"] is True, report["recorder"]
    assert isinstance(report["solver_ready"], bool)
    assert report["solver"]["ready"] is report["solver_ready"]


def test_the_self_check_reports_the_solver_and_the_recorder():
    ready = entry.readiness(
        solver_check=lambda: {"ready": True, "seconds": 4.0, "reason": None},
        recorder_check=lambda: {"ready": False, "fourcc": None, "reason": "no encoder"})
    assert ready["solver_ready"] is True and ready["recorder_ready"] is False
    assert ready["recorder"]["reason"] == "no encoder"


def test_small_computers_give_recognition_half_their_threads():
    assert [entry.recognition_threads(cpus) for cpus in (1, 2, 3, 4, 8, 10)] == [
        1, 1, 1, 2, None, None]
    assert entry.recognition_threads(0) is None   # os.cpu_count() unknown
    applied = []
    assert entry.limit_recognition_threads(4, applied.append) == 2
    assert entry.limit_recognition_threads(10, applied.append) is None
    assert applied == [2]
    report = entry.package_report(entry.parser().parse_args([]))
    assert report["recognition_threads"] == entry.recognition_threads()


def test_only_the_self_check_solves_and_records(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(entry, "readiness", lambda: calls.append(1) or {})
    monkeypatch.setattr(entry, "serve", lambda args: 0)
    assert entry.main(["--no-update-check", "--state", str(tmp_path / "s")]) == 0
    assert calls == []
    assert entry.main(["--self-check", "--state", str(tmp_path / "s")]) == 0
    assert calls == [1]


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
    installer = (ROOT / "packaging/pokersense.iss").read_text("utf-8-sig")
    assert '#define MyAppExeName "PokerSense-AA.exe"' in installer
    assert '  #define MyAppVersion "' + __version__ + '"' in installer
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


def test_installed_builds_keep_one_data_folder_across_updates(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert entry.default_state() == tmp_path / "PokerSense-AA" / __version__
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert entry.default_state() == tmp_path / "PokerSense-AA" / "data"


def test_a_recognition_bundle_in_the_data_folder_turns_on_the_capture_card(
        tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"
    digest = "a" * 64
    (state / "recognition" / digest).mkdir(parents=True)
    (state / "recognition" / digest / "profile.json").write_text("{}", "utf-8")
    (state / "recognition" / "current.json").write_text(
        json.dumps({"manifest_sha256": digest}), "utf-8")
    monkeypatch.setattr(entry.app_update, "install_root", lambda: tmp_path / "app")
    # main() 会设这个变量：先 setenv 让 monkeypatch 记下“原来没有”，测试结束时才会清掉，
    # 否则后面的测试会到这个临时目录里找求解器等私有数据。
    monkeypatch.setenv(entry.DATA_ROOT_ENV, "unset")
    monkeypatch.delenv(entry.DATA_ROOT_ENV)
    monkeypatch.delenv(entry.app_update.URL_ENV, raising=False)
    assert entry.main(["--self-check", "--state", str(state)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["capture_enabled"] is True
    assert report["recognition_bundle"] == "INSTALLED"
    assert report["external_model"] == "CONFIGURED_NOT_VALIDATED"
    # Recordings go to the user's data folder, not the old G: drive.
    assert entry.os.environ[entry.DATA_ROOT_ENV] == str(state)
    monkeypatch.delenv(entry.DATA_ROOT_ENV)
    assert entry.main(["--self-check", "--no-recognition", "--state", str(state)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["capture_enabled"] is False
    assert report["recognition_bundle"] == "NOT_INSTALLED"
    monkeypatch.delenv(entry.DATA_ROOT_ENV)


def published_bundle(tmp_path):
    """A release manifest listing an exported, packed (synthetic) bundle."""
    from tests.desktop import test_aa_bundle
    from poker_engine.desktop.aa_bundle import export_bundle
    packer = importlib.util.spec_from_file_location(
        "pack_aa_recognition", ROOT / "tools/pack_aa_recognition.py")
    pack = importlib.util.module_from_spec(packer)
    packer.loader.exec_module(pack)
    (tmp_path / "private").mkdir()
    profile = test_aa_bundle.source.__wrapped__(tmp_path / "private")
    export_bundle(profile, tmp_path / "bundle")
    sidecar = pack.pack(tmp_path / "bundle", tmp_path / "cloud")
    manifest = {"schema": "pokersense-update-v1", "product": "PokerSense-AA",
                "version": __version__, "installer": {
                    "url": str(tmp_path / "setup.exe"), "sha256": "0" * 64,
                    "bytes": 1},
                "recognition": {"url": str(tmp_path / "cloud" / pack.ZIP_NAME),
                                "sha256": sidecar["zip_sha256"],
                                "bytes": sidecar["zip_bytes"],
                                "manifest_sha256": sidecar["manifest_sha256"]}}
    (tmp_path / "latest.json").write_text(json.dumps(manifest), "utf-8")
    return tmp_path / "latest.json", sidecar


def test_first_start_fetches_the_recognition_bundle_the_release_lists(tmp_path):
    url, sidecar = published_bundle(tmp_path)
    lines = []
    args = entry.parser().parse_args(["--state", str(tmp_path / "state"),
                                      "--update-url", str(url)])
    profile, digest = entry.use_recognition(args, out=lines.append)
    assert digest == sidecar["manifest_sha256"] and profile.is_file()
    assert (args.profile, args.bundle_sha256, args.allow_capture) == (
        profile, digest, True)
    assert any("已下载" in line for line in lines)
    lines.clear()
    args = entry.parser().parse_args(["--state", str(tmp_path / "state"),
                                      "--update-url", str(url)])
    assert entry.use_recognition(args, out=lines.append)[1] == digest
    assert lines[-1] == "[识别资源] 已经是最新的。"
    with TestClient(entry.create_app(args)) as client:
        assert client.get("/api/build").json()["recognition_bundle"] == "INSTALLED"
        status = client.get("/api/status").json()
        assert status["capture_available"] is True
        assert status["profile"]["ready"] is True


def test_no_fetch_for_a_self_check_an_explicit_profile_or_no_recognition(tmp_path):
    url, _ = published_bundle(tmp_path)
    for flags in (["--self-check"], ["--no-recognition"], ["--no-update-check"],
                  ["--profile", str(tmp_path / "mine.json")]):
        args = entry.parser().parse_args(["--state", str(tmp_path / "state"),
                                          "--update-url", str(url), *flags])
        assert entry.use_recognition(args, out=pytest.fail) is None
    assert not (tmp_path / "state").exists()


def test_a_failed_fetch_keeps_the_window_working_without_the_capture_card(tmp_path):
    url, _ = published_bundle(tmp_path)
    manifest = json.loads(url.read_text("utf-8"))
    manifest["recognition"]["sha256"] = "0" * 64
    url.write_text(json.dumps(manifest), "utf-8")
    lines = []
    args = entry.parser().parse_args(["--state", str(tmp_path / "state"),
                                      "--update-url", str(url)])
    assert entry.use_recognition(args, out=lines.append) is None
    assert args.allow_capture is False and args.profile is None
    assert any("sha256" in line for line in lines)
    assert "下次打开程序会再试" in lines[-1]


def test_the_window_reports_and_refuses_updates_when_running_from_source(tmp_path):
    import hashlib
    data = b"MZ" * 100
    (tmp_path / "setup.exe").write_bytes(data)
    (tmp_path / "latest.json").write_text(json.dumps({
        "schema": "pokersense-update-v1", "product": "PokerSense-AA",
        "version": "99.0.0", "installer": {
            "url": str(tmp_path / "setup.exe"),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}}), "utf-8")
    args = entry.parser().parse_args(["--state", str(tmp_path / "state"),
                                      "--update-url", str(tmp_path / "latest.json")])
    with TestClient(entry.create_app(args)) as client:
        assert client.get("/api/update").json()["status"] == "NOT_CHECKED"
        assert client.get("/update_banner.js").status_code == 200
        assert client.post("/api/update/check", json={}).status_code == 403
        state = client.post("/api/update/check", json={},
                            headers={"X-AA-Live": "1"}).json()
        assert (state["status"], state["latest"], state["can_install"]) == (
            "AVAILABLE", "99.0.0", False)
        response = client.post("/api/update/install", json={},
                               headers={"X-AA-Live": "1"})
        assert response.status_code == 409
    args = entry.parser().parse_args(["--state", str(tmp_path / "plain")])
    with TestClient(entry.create_app(args)) as client:
        assert client.get("/api/update").json()["status"] == "UNCONFIGURED"


def test_the_check_for_updates_shortcut_without_an_address(tmp_path, capsys):
    args = entry.parser().parse_args(["--update-now", "--state", str(tmp_path)])
    assert entry.console_update(args, keep_open=False) == 3
    assert "没有配置更新地址" in capsys.readouterr().out


def test_the_self_test_runs_the_core_calculations_and_recognition_imports(capsys):
    assert entry.main(["--self-test"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["result"] == "SELF_TEST_PASS" and report["missing_modules"] == []
    assert report["scoreboard_hands"] > 0 and report["rough_advice"] in (
        "check", "call", "fold", "bet", "raise")


def test_chinese_messages_survive_output_to_a_pipe():
    import io
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    with pytest.raises(UnicodeEncodeError):
        print("[更新] 已经是最新版", file=stream, flush=True)
    entry.utf8_output([stream, None])
    print("[更新] 已经是最新版", file=stream, flush=True)
    assert "[更新] 已经是最新版".encode("utf-8") in raw.getvalue()


# -- closing the black window is 停止 -----------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="no SIGHUP on Windows")
def test_closing_the_terminal_or_a_takeover_closes_like_stop(monkeypatch):
    installed, closed, quieted = {}, [], []
    monkeypatch.setattr(entry, "quiet", lambda: quieted.append(1))
    handler = entry.on_close(lambda: closed.append(1), platform="posix",
                             install=lambda signum, h: installed.update({signum: h}))
    import signal
    assert installed == {signal.SIGHUP: handler, signal.SIGTERM: handler}
    handler(signal.SIGTERM, None)              # a new launch takes over
    assert closed == [1] and quieted == []
    handler(signal.SIGHUP, None)               # Terminal closed: no terminal left
    assert closed == [1, 1] and quieted == [1]


def test_closing_the_windows_console_closes_like_stop():
    class Kernel32:
        def SetConsoleCtrlHandler(self, handler, add):
            self.handler, self.add = handler, add
            return 1
    kernel32, closed = Kernel32(), []
    entry.on_close(lambda: closed.append(1), platform="nt", kernel32=kernel32)
    assert kernel32.add is True
    assert kernel32.handler(0) == 0 and closed == []    # Ctrl+C: as before
    for event in (2, 5, 6, 1):          # window closed, log off, shut down, break
        assert kernel32.handler(event) == 1
    assert closed == [1, 1, 1, 1]
    assert kernel32.handler in entry._KEPT


def test_closing_finishes_the_recording_then_hands_over_the_upload(tmp_path):
    """What 停止 does, then the upload: the recording's recording.json and its
    sheet start before anything else, even when stopping fails."""
    from poker_engine.desktop.aa_recorder import AARecorder
    from tests.desktop.test_aa_recorder import AA8, Writer

    order = []
    recorder = AARecorder(tmp_path / "20261016-210927-live", AA8,
                          writer_factory=Writer,
                          on_finished=lambda folder: order.append(("sheet", folder)))

    class Service:
        def stop(self):
            recorder.stop("source_stopped")
    entry.close_window(Service(), after_close=lambda: order.append("upload"))
    summary = json.loads((tmp_path / "20261016-210927-live" / "recording.json")
                         .read_text(encoding="utf-8"))
    assert summary["stopped_reason"] == "source_stopped"
    assert order == [("sheet", tmp_path / "20261016-210927-live"), "upload"]

    class Broken:
        def stop(self):
            raise RuntimeError("driver")
    order.clear()
    with pytest.raises(RuntimeError):
        entry.close_window(Broken(), after_close=lambda: order.append("upload"))
    assert order == ["upload"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
@pytest.mark.parametrize("name", ["SIGHUP", "SIGTERM"])
def test_a_real_close_signal_runs_the_close_and_no_more(tmp_path, name):
    """Without the handler the system ends the program on the spot."""
    import signal
    import subprocess
    done = tmp_path / "closed"
    path = ROOT / "packaging" / "aa_live_entry.py"
    script = (
        "import importlib.util, sys, time\n"
        f"spec = importlib.util.spec_from_file_location('e', {str(path)!r})\n"
        "e = importlib.util.module_from_spec(spec); spec.loader.exec_module(e)\n"
        f"e.on_close(lambda: open({str(done)!r}, 'w').write('ok') and sys.exit(0))\n"
        "print('ready', flush=True)\n"
        "time.sleep(20)\n"
        "sys.exit(3)\n")
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                             text=True, env=dict(__import__("os").environ,
                                                 PYTHONPATH=f"{ROOT / 'src'}:{ROOT}"))
    try:
        assert child.stdout.readline().strip() == "ready"
        child.send_signal(getattr(signal, name))
        assert child.wait(15) == 0
    finally:
        child.kill()
        child.stdout.close()
    assert done.read_text() == "ok"
