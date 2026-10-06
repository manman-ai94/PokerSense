"""Dependency-free bootstrap for the AA source checkout, never a frozen EXE."""

import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


DEPENDENCIES = ("numpy", "cv2", "fastapi", "uvicorn")
READ_ONLY_OPTIONS = {"--help", "-h", "--version", "--self-check"}


def supported(version):
    return (3, 11) <= tuple(version[:2]) < (3, 14)


def select_python(root):
    """Keep the project's venv, otherwise use a supported system interpreter."""
    venv = root / ".venv"
    if venv.exists():
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            raise RuntimeError(f"Project virtual environment is incomplete: {python}")
        return str(python)
    if supported(sys.version_info):
        return sys.executable
    # A launcher default such as Python 3.14 must not hide an installed 3.12.
    probe = ("import json,sys; print(json.dumps("
             "[sys.executable, list(sys.version_info[:2])]))")
    for version in ("3.12", "3.13", "3.11"):
        try:
            result = subprocess.run(["py", "-" + version, "-c", probe],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                python, actual = json.loads(result.stdout)
                if isinstance(python, str) and python and supported(actual):
                    return python
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            continue
    raise RuntimeError("Python 3.11-3.13 was not found. Create this checkout's "
                       ".venv with a supported Python.")


def check_dependencies():
    """Check imports before the entry can create state or start a server."""
    for name in DEPENDENCIES:
        try:
            importlib.import_module(name)
        except (ImportError, OSError) as error:
            print(f"[AA] ERROR: Dependency {name!r} is unavailable in "
                  f"{sys.executable}: {error}", file=sys.stderr)
            print("[AA] In the source checkout, install its desktop dependencies "
                  "with the selected interpreter:", file=sys.stderr)
            print(f'  "{sys.executable}" -m pip install -e ".[desktop]"',
                  file=sys.stderr)
            return False
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[2]
    entry = root / "packaging" / "aa_live_entry.py"
    if not entry.is_file() or not (root / "src/poker_engine/__init__.py").is_file():
        print(f"[AA] ERROR: Incomplete AA source checkout: {root}", file=sys.stderr)
        return 2
    try:
        python = select_python(root)
        if os.path.normcase(os.path.abspath(python)) != os.path.normcase(
                os.path.abspath(sys.executable)):
            return subprocess.run([python, str(Path(__file__).resolve()),
                                   *argv]).returncode
    except (RuntimeError, OSError) as error:
        print(f"[AA] ERROR: {error}", file=sys.stderr)
        return 3
    print(f"[AA] Python {sys.version.split()[0]}: {sys.executable}", flush=True)
    print(f"[AA] Source entry: {entry}", flush=True)
    if not supported(sys.version_info):
        print("[AA] ERROR: The project virtual environment requires Python "
              "3.11-3.13. Re-create it with a supported Python.", file=sys.stderr)
        return 3
    if not READ_ONLY_OPTIONS.intersection(argv) and not check_dependencies():
        return 4
    previous = sys.argv
    try:
        sys.argv = [str(entry), *argv]
        runpy.run_path(str(entry), run_name="__main__")
    finally:
        sys.argv = previous
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
