"""tools/setup_texassolver.py: the Windows build of the Mac's TexasSolver
commit, without running a compiler (the Windows CI run builds it for real:
tests/desktop/test_second_seat_windows.py)."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "setup_texassolver_tool", ROOT / "tools/setup_texassolver.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def test_it_builds_the_same_commit_as_the_mac():
    script = (ROOT / "tools/setup_texassolver.sh").read_text("utf-8")
    assert f'COMMIT="{tool.COMMIT}"' in script


def test_the_guide_installs_the_same_build_tools():
    """GCC 16 split OpenMP into libgomp; the guide's pacman line must have it."""
    guide = (ROOT / "docs/second-seat-windows.md").read_text("utf-8")
    assert "mingw-w64-ucrt-x86_64-libgomp" in tool.MSYS2_PACKAGES
    assert f'bash.exe -lc "{tool.PACMAN}"' in guide


def test_commands_fetch_the_commit_and_build_only_the_console_solver(tmp_path):
    commands = tool.build_commands(tmp_path / "src", jobs=3,
                                   generator="Ninja", is_windows=True)
    assert commands[0][:2] == ["git", "clone"]
    assert ["git", "-C", str(tmp_path / "src"), "checkout", "--quiet",
            tool.COMMIT] in commands
    configure = next(c for c in commands if c[:2] == ["cmake", "-S"])
    assert "-DCMAKE_BUILD_TYPE=Release" in configure
    assert "-DPYTHONLIBS_FOUND=TRUE" in configure    # no Python needed
    assert configure[configure.index("-G") + 1] == "Ninja"
    assert "-DCMAKE_CXX_COMPILER=g++" in configure
    assert ["cmake", "--build", str(tmp_path / "src/build"), "--target",
            "console_solver", "-j", "3"] in commands
    assert commands[-1] == ["cmake", "--install", str(tmp_path / "src/build")]
    (tmp_path / "src/.git").mkdir(parents=True)
    again = tool.build_commands(tmp_path / "src", is_windows=False)
    assert again[0][:3] == ["git", "-C", str(tmp_path / "src")]
    assert not any("-G" in c or "-DCMAKE_CXX_COMPILER=g++" in c for c in again)


def test_the_usual_mingw_folders_join_the_path_on_windows(tmp_path):
    tools = tmp_path / "msys64/ucrt64/bin"
    tools.mkdir(parents=True)
    environ = tool.build_environment({"PATH": "user"}, extra=(str(tools), "C:/none"),
                                     is_windows=True)
    assert environ["PATH"].split(tool.os.pathsep) == ["user", str(tools)]
    assert tool.build_environment({"PATH": "user"}, extra=(str(tools),),
                                  is_windows=False)["PATH"] == "user"


def test_a_folder_with_a_shell_leaves_the_build_path(tmp_path):
    git, gcc = tmp_path / "git/bin", tmp_path / "gcc"
    git.mkdir(parents=True)
    gcc.mkdir()
    (git / "sh.exe").write_bytes(b"")
    path = tool.os.pathsep.join([str(git), str(gcc)])
    assert tool.without_shell({"PATH": path}, is_windows=True)["PATH"] == str(gcc)
    assert tool.without_shell({"PATH": path}, is_windows=False)["PATH"] == path


def test_ninja_first_then_mingw_make():
    def which(found):
        return lambda name, path=None: name if name in found else None
    assert tool.pick_generator({}, which({"ninja"}), is_windows=True) == "Ninja"
    assert tool.pick_generator({}, which({"mingw32-make"}),
                               is_windows=True) == "MinGW Makefiles"
    assert tool.pick_generator({}, which(set()), is_windows=False) is None


def test_a_failed_step_stops_the_build(tmp_path):
    ran = []

    def run(command, env):
        ran.append(command)
        return SimpleNamespace(returncode=1 if command[1] == "--build" else 0)

    with pytest.raises(RuntimeError, match="cmake --build failed"):
        tool.build(tmp_path / "src", {"PATH": ""}, run=run, out=lambda line: None,
                   which=lambda name, path=None: None)
    assert ran[-1][1] == "--build"


def test_a_build_that_leaves_no_solver_is_an_error(tmp_path):
    with pytest.raises(RuntimeError, match="no console_solver"):
        tool.build(tmp_path / "src", {"PATH": ""},
                   run=lambda command, env: SimpleNamespace(returncode=0),
                   out=lambda line: None, which=lambda name, path=None: None)


def test_missing_tools_are_named_before_anything_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(tool.DATA_ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(tool.sys, "platform", "win32")
    monkeypatch.setattr(tool, "missing_tools", lambda environ: ["cmake", "g++"])
    assert tool.main([], run=lambda *a, **k: pytest.fail("ran")) == 1
    assert "缺编译工具：cmake、g++" in capsys.readouterr().err


def test_the_data_folder_must_be_set(monkeypatch):
    monkeypatch.delenv(tool.DATA_ROOT_ENV, raising=False)
    monkeypatch.setattr(tool.sys, "platform", "win32")
    with pytest.raises(SystemExit) as error:
        tool.main([])
    assert error.value.code == 2


def test_check_reports_the_test_solve(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(tool.DATA_ROOT_ENV, str(tmp_path))
    failed = {"ready": False, "seconds": 0.0, "reason": "not_installed", "binary": None}
    monkeypatch.setattr(tool, "smoke_test", lambda: failed)
    assert tool.main(["--check"]) == 1
    assert "not_installed" in capsys.readouterr().err
    passed = {"ready": True, "seconds": 4.2, "reason": None, "binary": "x"}
    monkeypatch.setattr(tool, "smoke_test", lambda: passed)
    assert tool.main(["--check"]) == 0
    assert "试算通过（4.2 秒）" in capsys.readouterr().out
