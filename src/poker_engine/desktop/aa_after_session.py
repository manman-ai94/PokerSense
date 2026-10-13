"""When a recording in the window stops: its check-up sheet, made on its own.

``start_report`` starts ``tools/flywheel_session.py report`` for the
recording's folder in a separate process at low priority (the window keeps
running), with its output in ``<folder>/flywheel/report.log``. It does
nothing in a packaged build (no ``tools/`` next to the code) or when the
folder has no window log (``frames.jsonl``)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from ..data_paths import REPO_ROOT

TOOL = REPO_ROOT / "tools" / "flywheel_session.py"


def start_report(folder, *, tool=TOOL, popen=subprocess.Popen):
    """The started process, or None when there is nothing to do."""
    folder = Path(folder)
    if getattr(sys, "frozen", False) or not Path(tool).exists():
        return None
    if not (folder / "frames.jsonl").exists():
        return None
    out = folder / "flywheel"
    out.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT)]))
    extra = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
              | subprocess.BELOW_NORMAL_PRIORITY_CLASS}
             if os.name == "nt" else {"start_new_session": True})
    with open(out / "report.log", "w", encoding="utf-8") as log:
        return popen([sys.executable, str(tool), "report", "--recording", str(folder)],
                     cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                     stderr=subprocess.STDOUT, **extra)


__all__ = ["start_report"]
