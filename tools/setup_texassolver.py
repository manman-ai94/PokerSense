"""Build TexasSolver's command-line solver on Windows (also Linux).

    .venv\\Scripts\\python.exe tools\\setup_texassolver.py

Builds the same TexasSolver commit as the Mac (``tools/setup_texassolver.sh``)
into ``$POKERSENSE_DATA_ROOT\\third_party\\TexasSolver-console\\install\\``
(``console_solver.exe`` and its ``resources`` folder, where the window looks
for them), then solves one tiny river spot to prove it works; ``--check``
only runs that test solve.

The official v0.2.0 Windows release cannot be used: it does not read ranges
written combination by combination ("6s5s"), which PokerSense sends whenever
card removal or reads weight one combination differently from its class.

Needs git, CMake and a MinGW-w64 GCC with OpenMP (``MSYS2_PACKAGES``: since
GCC 16 MSYS2 ships OpenMP as its own package, libgomp, and without it CMake
stops at "Could NOT find OpenMP_C"). On Windows the MSYS2 tools are found
at their usual place (``C:\\msys64\\ucrt64\\bin``) without changing PATH;
docs/second-seat-windows.md says how to install them. The solver is linked
statically, so it runs without the build tools' DLLs.

TexasSolver (https://github.com/bupticybee/TexasSolver) is AGPL-3.0 and its
author asks that only the link be shared, never the program: every machine
builds it itself. Never commit or send the source or the built folder.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from poker_engine.data_paths import DATA_ROOT_ENV, data_root
from poker_engine.solver.texassolver import smoke_test

REPO_URL = "https://github.com/bupticybee/TexasSolver.git"
COMMIT = "6dfb65b4d7ed081da509e8d8c3d82138c4708267"   # as setup_texassolver.sh
# Where MSYS2 and the GitHub Windows runners keep MinGW-w64 GCC and CMake.
WINDOWS_TOOLS = (r"C:\msys64\ucrt64\bin", r"C:\msys64\mingw64\bin", r"C:\mingw64\bin",
                 r"C:\Program Files\CMake\bin")
NEEDED = ("git", "cmake", "g++")
# What docs/second-seat-windows.md installs with MSYS2's pacman.
MSYS2_PACKAGES = ("mingw-w64-ucrt-x86_64-gcc", "mingw-w64-ucrt-x86_64-libgomp",
                  "mingw-w64-ucrt-x86_64-cmake", "mingw-w64-ucrt-x86_64-ninja")
PACMAN = "pacman -S --noconfirm --needed " + " ".join(MSYS2_PACKAGES)


def source_dir(root=None):
    return Path(root or data_root()) / "third_party/TexasSolver-console"


def build_environment(environ=None, extra=WINDOWS_TOOLS, is_windows=os.name == "nt"):
    """The environment the build runs in: PATH with the usual MinGW and CMake
    folders after the user's own (Windows only)."""
    environ = dict(os.environ if environ is None else environ)
    if is_windows:
        folders = [folder for folder in extra if Path(folder).is_dir()]
        environ["PATH"] = os.pathsep.join([environ.get("PATH", ""), *folders])
    return environ


def missing_tools(environ, which=shutil.which):
    return [tool for tool in NEEDED if which(tool, path=environ.get("PATH")) is None]


def without_shell(environ, is_windows=os.name == "nt"):
    """``environ`` without PATH folders holding a ``sh.exe`` (Git for Windows
    has one): CMake refuses MinGW makefiles when a shell is on PATH."""
    if not is_windows:
        return environ
    folders = [folder for folder in environ.get("PATH", "").split(os.pathsep)
               if folder and not (Path(folder) / "sh.exe").is_file()]
    return {**environ, "PATH": os.pathsep.join(folders)}


def build_commands(source, *, jobs=None, generator=None,
                   is_windows=os.name == "nt"):
    """The commands that fetch, build and install the solver in ``source``."""
    source = Path(source)
    build = source / "build"
    commands = []
    if not (source / ".git").is_dir():
        commands.append(["git", "clone", "--filter=blob:none", "--no-checkout",
                         REPO_URL, str(source)])
    commands += [["git", "-C", str(source), "fetch", "--depth", "1", "origin", COMMIT],
                 ["git", "-C", str(source), "checkout", "--quiet", COMMIT]]
    # The bundled pybind11 (the solver's Python module, not built here) looks
    # for Python with distutils, which Python 3.12 no longer has: say it was
    # found so it does not look.
    configure = ["cmake", "-S", str(source), "-B", str(build),
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                 "-DPYTHONLIBS_FOUND=TRUE", "-DPYTHON_MODULE_EXTENSION=.pyd"]
    if generator:
        configure += ["-G", generator]
    if is_windows:
        # The solver's own CMakeLists links Windows builds statically.
        configure += ["-DCMAKE_C_COMPILER=gcc", "-DCMAKE_CXX_COMPILER=g++"]
    commands += [configure,
                 ["cmake", "--build", str(build), "--target", "console_solver",
                  "-j", str(jobs or os.cpu_count() or 2)],
                 ["cmake", "--install", str(build)]]
    return commands


def pick_generator(environ, which=shutil.which, is_windows=os.name == "nt"):
    """Ninja when there is one, else MinGW's make on Windows (CMake's default
    there is Visual Studio, which this build does not use)."""
    path = environ.get("PATH")
    if which("ninja", path=path):
        return "Ninja"
    if is_windows and which("mingw32-make", path=path):
        return "MinGW Makefiles"
    return None


def build(source, environ, run=subprocess.run, out=print, which=shutil.which):
    # Programs are looked up on the build's PATH here: Windows itself would
    # only search the PATH this program started with.
    path = environ.get("PATH")
    programs = {tool: which(tool, path=path) for tool in ("git", "cmake")}
    environ = without_shell(environ)
    generator = pick_generator(environ, which=which)
    for command in build_commands(source, generator=generator):
        out("[求解器] " + " ".join(command[:4]) + (" ..." if len(command) > 4 else ""))
        program = programs.get(command[0]) or command[0]
        result = run([program, *command[1:]], env=environ)
        if result.returncode:
            raise RuntimeError(f"{command[0]} {command[1]} failed "
                               f"(exit code {result.returncode})")
    binary = source / "install" / ("console_solver.exe" if os.name == "nt"
                                   else "console_solver")
    if not binary.is_file() or not (binary.parent / "resources").is_dir():
        raise RuntimeError(f"the build left no {binary.name} with resources")
    return binary


def main(argv=None, run=subprocess.run):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="only solve the test spot with the installed solver")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # Chinese lines must survive a pipe on Windows (an AI assistant runs this).
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "darwin" and not args.check:
        print("[求解器] Mac 用 tools/setup_texassolver.sh 编译。", file=sys.stderr)
        return 2
    if not os.environ.get(DATA_ROOT_ENV, "").strip():
        parser.error(f"set {DATA_ROOT_ENV} first (the data folder)")
    if not args.check:
        environ = build_environment()
        missing = missing_tools(environ)
        if missing:
            print("[求解器] 缺编译工具：" + "、".join(missing)
                  + "。按 docs/second-seat-windows.md 的“装求解器”先装 MSYS2 工具。",
                  file=sys.stderr)
            return 1
        try:
            binary = build(source_dir(), environ, run=run)
        except (OSError, RuntimeError) as error:
            print(f"[求解器] 没编译成：{error}", file=sys.stderr)
            if os.name == "nt":
                print("[求解器] 报 OpenMP 找不到时，先补装编译工具再重跑：\n"
                      f'C:\\msys64\\usr\\bin\\bash.exe -lc "{PACMAN}"', file=sys.stderr)
            return 1
        print(f"[求解器] 编译好了：{binary}")
    result = smoke_test()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ready"]:
        print(f"[求解器] 试算没通过：{result['reason']}", file=sys.stderr)
        return 1
    print(f"[求解器] 试算通过（{result['seconds']} 秒）。重开 START-AA.cmd 后，"
          "单挑转牌、河牌就用求解器给建议。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
