"""A second seat runs from source (docs/second-seat-windows.md): the received
recognition pack is installed into the data folder, and START-AA.cmd finds it
there, opens the window with the capture card, records and gives advice."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import venv
import zipfile

import pytest

from tests.desktop.test_aa_packaging import entry, published_bundle


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "pack_aa_recognition_tool", ROOT / "tools/pack_aa_recognition.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Requires Windows cmd.exe")
# A cold CI runner can take over 30 s to import the desktop dependencies.
TIMEOUT = 180


def received_pack(tmp_path, *, bank=True):
    """The folder the owner sends: zip, sidecar and (usually) the mushroom bank."""
    _, sidecar = published_bundle(tmp_path)
    folder = tmp_path / "cloud"
    if bank:
        (folder / tool.MUSHROOM_NAME).write_bytes(b"mushroom bank")
    return folder / tool.ZIP_NAME, sidecar


def test_a_received_pack_is_installed_where_the_window_finds_it(
        tmp_path, monkeypatch):
    archive, sidecar = received_pack(tmp_path)
    data = tmp_path / "PokerSense_data"
    monkeypatch.setenv(entry.DATA_ROOT_ENV, str(data))
    assert tool.main(["--install", str(archive)]) == 0
    state = data / "aa-live-state"
    profile, digest = entry.app_update.installed_recognition(state)
    assert digest == sidecar["manifest_sha256"]
    bank = data / "PokerSense_private" / tool.MUSHROOM_BANK
    assert bank.read_bytes() == b"mushroom bank"
    # A source checkout with the data folder set uses it by default.
    args = entry.parser().parse_args(["--no-update-check"])
    assert args.state == state
    assert entry.use_recognition(args) == (profile, digest)
    assert args.allow_capture is True
    # Installing the same pack again leaves exactly one bundle.
    assert tool.main(["--install", str(archive)]) == 0
    assert {p.name for p in (state / "recognition").iterdir()} == {
        "current.json", digest}


def test_a_damaged_zip_is_refused_and_nothing_changes(tmp_path):
    archive, _ = received_pack(tmp_path, bank=False)
    archive.write_bytes(archive.read_bytes()[:-1] + b"x")
    state = tmp_path / "state"
    with pytest.raises(ValueError, match="does not match"):
        tool.install(archive, state, tmp_path / "private")
    assert entry.app_update.installed_recognition(state) is None


def test_a_tampered_file_inside_the_pack_is_refused(tmp_path):
    archive, sidecar = received_pack(tmp_path, bank=False)
    with zipfile.ZipFile(archive) as source:
        files = {info.filename: source.read(info) for info in source.infolist()}
    name = next(n for n in files if n.endswith(".png"))
    files[name] += b"tampered"
    with zipfile.ZipFile(archive, "w") as target:
        for key, value in files.items():
            target.writestr(key, value)
    data = archive.read_bytes()
    sidecar.update(zip_bytes=len(data),
                   zip_sha256=tool.hashlib.sha256(data).hexdigest())
    (archive.parent / tool.JSON_NAME).write_text(json.dumps(sidecar), "utf-8")
    state = tmp_path / "state"
    with pytest.raises(ValueError):
        tool.install(archive, state, tmp_path / "private")
    assert entry.app_update.installed_recognition(state) is None
    assert list((state / "recognition").iterdir()) == []


def test_install_needs_the_data_folder_set(tmp_path, monkeypatch):
    monkeypatch.delenv(entry.DATA_ROOT_ENV, raising=False)
    with pytest.raises(SystemExit) as error:
        tool.main(["--install", str(tmp_path / tool.ZIP_NAME)])
    assert error.value.code == 2


def test_installed_builds_ignore_the_source_data_folder(tmp_path, monkeypatch):
    monkeypatch.setenv(entry.DATA_ROOT_ENV, str(tmp_path / "data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert entry.default_state() == tmp_path / "data" / "aa-live-state"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert entry.default_state() == tmp_path / "PokerSense-AA" / "data"


# ---- On Windows: the real checkout, the way the guide sets it up ----------


@pytest.fixture(scope="module")
def checkout_venv():
    """The guide makes the checkout's .venv; on CI the test makes one that sees
    the runner's installed packages, and removes it afterwards."""
    made = not (ROOT / ".venv").exists()
    if made:
        venv.EnvBuilder(system_site_packages=True, with_pip=False).create(
            ROOT / ".venv")
    try:
        yield ROOT / ".venv/Scripts/python.exe"
    finally:
        if made:
            shutil.rmtree(ROOT / ".venv", ignore_errors=True)


def start_aa(arguments, env, **options):
    invocation = subprocess.list2cmdline(
        [str(ROOT / "launch/aa/START-AA.cmd"), *arguments])
    command = f'"{os.environ["COMSPEC"]}" /d /s /c "{invocation}"'
    return command, {"env": env, "cwd": ROOT, "text": True, "encoding": "utf-8",
                     "errors": "replace", **options}


def seat(tmp_path, python):
    """杜's machine: the data folder set, the received pack installed."""
    archive, sidecar = received_pack(tmp_path)
    env = {**os.environ, entry.DATA_ROOT_ENV: str(tmp_path / "PokerSense_data")}
    env.pop("PYTHONUTF8", None)    # an assistant's plain shell: no UTF-8 mode
    result = subprocess.run(
        [str(python), str(ROOT / "tools/pack_aa_recognition.py"),
         "--install", str(archive)], env={**env, "PYTHONPATH": f"src{os.pathsep}."},
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        timeout=TIMEOUT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "装好了" in result.stdout
    return env, sidecar


@WINDOWS
def test_start_aa_finds_the_installed_pack(tmp_path, checkout_venv):
    env, sidecar = seat(tmp_path, checkout_venv)
    command, options = start_aa(["--self-check"], env)
    result = subprocess.run(command, capture_output=True, timeout=TIMEOUT, **options)
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(checkout_venv) in result.stdout
    report = json.loads(result.stdout[result.stdout.index("{"):])
    assert report["capture_enabled"] is True
    assert report["recognition_bundle"] == "INSTALLED"
    assert report["recorder_ready"] is True, report["recorder"]
    assert report["recorder"]["fourcc"] in ("avc1", "mp4v")


MSYS2 = Path(r"C:\msys64\usr\bin\bash.exe")
# The guide's build tools (docs/second-seat-windows.md, 装求解器).
PACMAN = ("pacman -S --noconfirm --needed mingw-w64-ucrt-x86_64-gcc "
          "mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja")


@WINDOWS
@pytest.mark.skipif(not MSYS2.is_file(), reason="Needs MSYS2 (on every CI runner)")
# Building takes about ten minutes: CI runs it as a job of its own
# (.github/workflows/ci.yml, "solver build").
@pytest.mark.skipif(not os.environ.get("POKERSENSE_SOLVER_BUILD_TEST"),
                    reason="Set POKERSENSE_SOLVER_BUILD_TEST=1 to build the solver")
def test_the_solver_builds_and_the_self_check_solves_with_it(tmp_path, checkout_venv):
    """The guide's solver step: MSYS2's compiler builds the Mac's TexasSolver
    commit, and START-AA.cmd --self-check solves with it."""
    env, _ = seat(tmp_path, checkout_venv)
    tools = subprocess.run([str(MSYS2), "-lc", PACMAN], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=900)
    assert tools.returncode == 0, tools.stdout[-3000:] + tools.stderr[-3000:]
    result = subprocess.run(
        [str(checkout_venv), str(ROOT / "tools/setup_texassolver.py")],
        env={**env, "PYTHONPATH": f"src{os.pathsep}."}, cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=2400)
    assert result.returncode == 0, result.stdout[-5000:] + result.stderr[-5000:]
    assert "试算通过" in result.stdout
    command, options = start_aa(["--self-check"], env)
    result = subprocess.run(command, capture_output=True, timeout=TIMEOUT, **options)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout[result.stdout.index("{"):])
    assert report["solver_ready"] is True, report["solver"]
    assert report["recorder_ready"] is True, report["recorder"]


@WINDOWS
def test_start_aa_core_advice_runs(tmp_path, checkout_venv):
    env, _ = seat(tmp_path, checkout_venv)
    command, options = start_aa(["--self-test"], env)
    result = subprocess.run(command, capture_output=True, timeout=TIMEOUT, **options)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout[result.stdout.index("{"):])
    assert report["result"] == "SELF_TEST_PASS"
    assert report["rough_advice"]


@WINDOWS
def test_start_aa_opens_the_window_with_the_capture_card(tmp_path, checkout_venv):
    env, _ = seat(tmp_path, checkout_venv)
    ready = tmp_path / "ready.json"
    command, options = start_aa(
        ["--no-browser", "--port", "0", "--no-update-check",
         "--ready-file", str(ready)], env)
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, **options)
    try:
        deadline = time.monotonic() + TIMEOUT
        while not ready.is_file() and process.poll() is None:
            assert time.monotonic() < deadline, "the window did not open"
            time.sleep(0.5)
        assert ready.is_file(), process.stdout.read()
        base = json.loads(ready.read_text("utf-8"))["base"]
        assert json.loads(ready.read_text("utf-8"))["state"] == str(
            tmp_path / "PokerSense_data" / "aa-live-state")
        with urllib.request.urlopen(base, timeout=30) as page:
            assert page.status == 200
        with urllib.request.urlopen(base + "api/status", timeout=30) as reply:
            status = json.load(reply)
        assert status["capture_available"] is True
        assert status["profile"]["ready"] is True
    finally:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True)
        process.wait(timeout=30)


@WINDOWS
def test_the_record_button_can_write_video_on_windows(tmp_path):
    """The window records with OpenCV's H.264 (avc1) writer."""
    import cv2
    import numpy as np
    from poker_engine.desktop import aa_recorder

    path = tmp_path / "segment.mp4"
    writer = aa_recorder.avc1_writer(path, aa_recorder.FPS, aa_recorder.SIZE)
    assert writer.isOpened()
    frame = np.zeros((aa_recorder.SIZE[1], aa_recorder.SIZE[0], 3), np.uint8)
    frame[:, 711:1209] = 200
    for _ in range(30):
        writer.write(frame)
    writer.release()
    capture = cv2.VideoCapture(str(path))
    count = 0
    while capture.read()[0]:
        count += 1
    capture.release()
    assert count == 30
