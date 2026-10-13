"""Which code is running: the package version and, in a git checkout, the
commit and whether files were changed on top of it.

Recordings and frame logs carry this, so a session's numbers can always be
tied to the code that produced them (the results ledger and the replay
comparisons need it). Outside a checkout (a packaged build) the commit is
``None``, never a guess."""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path

from poker_engine import __version__

ROOT = Path(__file__).resolve().parents[2]


def _git(*args):
    try:
        done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


@functools.lru_cache(maxsize=1)
def code_version() -> dict:
    """``{"version", "commit", "dirty"}``; read once per process."""
    commit = _git("rev-parse", "HEAD") if (ROOT / ".git").exists() else None
    dirty = None
    if commit is not None:
        status = _git("status", "--porcelain", "--untracked-files=no")
        dirty = None if status is None else bool(status)
    return {"version": __version__, "commit": commit, "dirty": dirty}


__all__ = ["code_version"]
