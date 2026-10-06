"""Source interpreter selection and actual Windows command dispatch."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import pytest


ROOT = Path(__file__).resolve().parents[2]
LAUNCH = ROOT / "launch/aa"
SPEC = importlib.util.spec_from_file_location(
    "aa_source_launcher", LAUNCH / "source_launcher.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@pytest.mark.parametrize("version,expected", [
    ((3, 10, 9), False), ((3, 11, 0), True), ((3, 12, 14), True),
    ((3, 13, 9), True), ((3, 14, 0), False), ((4, 0, 0), False),
])
def test_supported_python_contract(version, expected):
    assert launcher.supported(version) is expected


def no_subprocess(*args, **kwargs):
    pytest.fail("A supported selected interpreter must not probe alternatives")


def test_only_python_312_needs_no_python_311(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 12, 14))
    monkeypatch.setattr(sys, "executable", "python312-only")
    monkeypatch.setattr(subprocess, "run", no_subprocess)
    assert launcher.select_python(tmp_path) == "python312-only"


def test_project_venv_wins_over_system_python(tmp_path, monkeypatch):
    python = tmp_path / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(sys, "version_info", (3, 12, 14))
    monkeypatch.setattr(sys, "executable", "different-system-python")
    monkeypatch.setattr(subprocess, "run", no_subprocess)
    assert launcher.select_python(tmp_path) == str(python)


def test_incomplete_project_venv_never_falls_back(tmp_path, monkeypatch):
    (tmp_path / ".venv").mkdir()
    monkeypatch.setattr(subprocess, "run", no_subprocess)
    with pytest.raises(RuntimeError, match="virtual environment is incomplete"):
        launcher.select_python(tmp_path)


@pytest.mark.parametrize("available", ["3.12", "3.13", "3.11"])
def test_newer_default_does_not_hide_supported_python(
        tmp_path, monkeypatch, available):
    monkeypatch.setattr(sys, "version_info", (3, 14, 0))
    queried = []

    def probe(command, **kwargs):
        queried.append(command[1])
        success = command[1] == "-" + available
        actual = [int(value) for value in available.split(".")]
        return subprocess.CompletedProcess(command, 0 if success else 103,
                                           json.dumps(["chosen-python", actual]))

    monkeypatch.setattr(subprocess, "run", probe)
    assert launcher.select_python(tmp_path) == "chosen-python"
    assert queried[-1] == "-" + available


@pytest.mark.parametrize("failure", ["missing", "timeout", "bad-json", "3.14"])
def test_no_supported_interpreter_is_a_clear_error(
        tmp_path, monkeypatch, failure):
    monkeypatch.setattr(sys, "version_info", (3, 14, 0))

    def probe(command, **kwargs):
        if failure == "missing":
            raise FileNotFoundError("py")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        output = "broken" if failure == "bad-json" else json.dumps(
            ["unsupported-python", [3, 14]])
        return subprocess.CompletedProcess(command, 0, output)

    monkeypatch.setattr(subprocess, "run", probe)
    with pytest.raises(RuntimeError, match="Python 3.11-3.13 was not found"):
        launcher.select_python(tmp_path)


@pytest.mark.parametrize("missing", launcher.DEPENDENCIES)
def test_missing_dependency_refuses_before_state_or_entry(
        tmp_path, monkeypatch, capsys, missing):
    state = tmp_path / "state"
    monkeypatch.setattr(launcher, "select_python", lambda root: sys.executable)

    def import_module(name):
        if name == missing:
            raise ModuleNotFoundError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", import_module)
    monkeypatch.setattr(launcher.runpy, "run_path", no_subprocess)
    assert launcher.main(["--state", str(state), "--no-browser"]) == 4
    error = capsys.readouterr().err
    assert missing in error and sys.executable in error
    assert '-m pip install -e ".[desktop]"' in error
    assert not state.exists()


def test_broken_native_dependency_is_actionable(monkeypatch, capsys):
    def import_module(name):
        raise OSError("native library load failed")

    monkeypatch.setattr(importlib, "import_module", import_module)
    assert launcher.check_dependencies() is False
    assert "native library load failed" in capsys.readouterr().err


def test_unsupported_venv_never_runs_entry(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "select_python", lambda root: sys.executable)
    monkeypatch.setattr(sys, "version_info", (3, 14, 0))
    monkeypatch.setattr(launcher, "check_dependencies", no_subprocess)
    monkeypatch.setattr(launcher.runpy, "run_path", no_subprocess)
    assert launcher.main(["--self-check"]) == 3
    assert "virtual environment requires Python 3.11-3.13" in (
        capsys.readouterr().err)


def test_real_source_self_check_from_other_directory(tmp_path):
    state = tmp_path / "must not be created"
    result = subprocess.run(
        [sys.executable, str(LAUNCH / "source_launcher.py"), "--self-check",
         "--state", str(state)], cwd=tmp_path, capture_output=True, text=True,
        timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(ROOT / "packaging/aa_live_entry.py") in result.stdout
    report = json.loads(result.stdout[result.stdout.index("{"):])
    assert report["resource_root"] == str(ROOT)
    assert report["missing_resources"] == []
    assert report["capture_enabled"] is False
    assert report["strategy_eligible"] is False
    assert not state.exists()


def make_checkout(tmp_path):
    root = tmp_path / "checkout with spaces"
    launch = root / "launch/aa"
    launch.mkdir(parents=True)
    for name in ("START-AA.cmd", "source_launcher.py"):
        shutil.copyfile(LAUNCH / name, launch / name)
    (root / "src/poker_engine").mkdir(parents=True)
    (root / "src/poker_engine/__init__.py").touch()
    (root / "packaging").mkdir()
    (root / "packaging/aa_live_entry.py").write_text(
        "import json,sys\n"
        "print(json.dumps({'python':sys.executable, 'args':sys.argv[1:]}))\n"
        "raise SystemExit(17)\n", encoding="utf-8")
    return root


def test_actual_source_argument_and_exit_code_preservation(tmp_path):
    root = make_checkout(tmp_path)
    args = ["--version", "--state", str(tmp_path / "状态 with spaces")]
    result = subprocess.run(
        [sys.executable, str(root / "launch/aa/source_launcher.py"), *args],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONUTF8": "1"})
    assert result.returncode == 17, result.stdout + result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["args"] == args


WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Requires Windows cmd.exe")


def run_cmd(path, arguments, cwd, env=None):
    invocation = subprocess.list2cmdline([str(path), *arguments])
    command = f'"{os.environ["COMSPEC"]}" /d /s /c "{invocation}"'
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=30)


@WINDOWS
def test_windows_cmd_source_venv_beats_both_stale_exes(tmp_path):
    root = make_checkout(tmp_path)
    venv.EnvBuilder(with_pip=False).create(root / ".venv")
    for path in (root / "launch/aa/PokerSense-AA.exe",
                 root / "dist/PokerSense-AA/PokerSense-AA.exe"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stale executable must not run")
    args = ["--version", "--state", str(tmp_path / "状态 with spaces")]
    result = run_cmd(root / "launch/aa/START-AA.cmd", args, tmp_path,
                     {**os.environ, "PYTHONUTF8": "1"})
    assert result.returncode == 17, result.stdout + result.stderr
    report = json.loads(next(line for line in result.stdout.splitlines()
                             if line.startswith("{")))
    assert Path(report["python"]) == root / ".venv/Scripts/python.exe"
    assert report["args"] == args
    assert "Packaged entry:" not in result.stdout


@WINDOWS
def test_windows_cmd_system_python_without_project_venv(tmp_path):
    root = make_checkout(tmp_path)
    result = run_cmd(root / "launch/aa/START-AA.cmd", ["--version"], tmp_path,
                     {**os.environ, "PYTHONUTF8": "1"})
    assert result.returncode == 17, result.stdout + result.stderr
    assert "Source entry:" in result.stdout


@WINDOWS
@pytest.mark.parametrize("location", ["launch/aa", "dist/PokerSense-AA"])
def test_windows_cmd_standalone_packaged_route(tmp_path, location):
    root = make_checkout(tmp_path)
    (root / "packaging/aa_live_entry.py").unlink()
    target = root / location
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(sys.base_prefix) / "python.exe",
                    target / "PokerSense-AA.exe")
    for dll in Path(sys.base_prefix).glob("python*.dll"):
        shutil.copyfile(dll, target / dll.name)
    result = run_cmd(
        root / "launch/aa/START-AA.cmd", ["-c", "print('PACKAGED_ROUTE')"],
        tmp_path, {**os.environ, "PYTHONHOME": sys.base_prefix,
                   "PYTHONUTF8": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PACKAGED_ROUTE" in result.stdout
    assert str(target / "PokerSense-AA.exe") in result.stdout
    assert "Source checkout:" not in result.stdout
