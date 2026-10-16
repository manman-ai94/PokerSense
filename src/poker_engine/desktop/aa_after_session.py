"""When a recording in the window stops: its check-up sheet and session
package, made on their own.

``start_report`` starts ``tools/session_package.py --with-sheet`` for the
recording's folder in a separate process at low priority (the window keeps
running): the sheet as ``tools/flywheel_session.py report`` makes it, then
``flywheel/package.json``, with the output in ``<folder>/flywheel/report.log``. It does
nothing in a packaged build (no ``tools/`` next to the code) or when the
folder has no window log (``frames.jsonl``).

``after_recording`` is what the capture source calls: the sheet, then the
folder handed to the uploader the window started (``aa_upload``), which
waits for both before it sends the folder."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from ..data_paths import REPO_ROOT
from . import aa_upload

TOOL = REPO_ROOT / "tools" / "session_package.py"


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
        return popen([sys.executable, str(tool), "--recording", str(folder),
                      "--with-sheet"],
                     cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log,
                     stderr=subprocess.STDOUT, **extra)


def after_recording(folder, *, report=None, uploader=None):
    """The sheet, then the upload; neither may fail the recording."""
    process = None
    try:
        process = (report or start_report)(folder)
    finally:
        uploader = uploader or aa_upload.current()
        if uploader is not None:
            uploader.submit(folder, wait_for=process)
    return process


__all__ = ["after_recording", "start_report"]
