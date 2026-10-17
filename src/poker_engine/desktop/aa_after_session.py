"""When a recording in the window stops: its check-up sheet and session
package, made on their own.

``start_report`` starts ``tools/session_package.py --with-sheet`` for the
recording's folder in a separate process at low priority (the window keeps
running): the sheet as ``tools/flywheel_session.py report`` makes it, then
``flywheel/package.json``, with the output in ``<folder>/flywheel/report.log``. It does
nothing in a packaged build (no ``tools/`` next to the code) or when the
folder has no window log (``frames.jsonl``). The process goes on when the
window is closed (on Windows it has no console of its own to be closed with
the window's), and ``flywheel/building`` is there until it ends: an upload,
from this window or one started later, waits for it (``aa_upload.building``).

``after_recording`` is what the capture source calls: the sheet, then the
folder handed to the uploader the window started (``aa_upload``), which
waits for both before it sends the folder.

``after_close`` is what closing the window adds to 停止 (``aa_live_entry``):
the window's uploader stops, and what it had left to send goes on in a
process of its own (``python -m poker_engine.desktop.aa_upload``)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from ..data_paths import REPO_ROOT
from . import aa_upload

TOOL = REPO_ROOT / "tools" / "session_package.py"
MODULE = "poker_engine.desktop.aa_after_session"


def detached():
    """Options for a process that outlives the window: its own session on a
    Mac (closing Terminal does not end it), its own hidden console on Windows
    (closing the window's console does not end it), at low priority."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.BELOW_NORMAL_PRIORITY_CLASS
                | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def environment():
    return dict(os.environ, PYTHONPATH=os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT)]))


def start_report(folder, *, tool=TOOL, popen=subprocess.Popen):
    """The started process, or None when there is nothing to do."""
    folder = Path(folder)
    if getattr(sys, "frozen", False) or not Path(tool).exists():
        return None
    if not (folder / "frames.jsonl").exists():
        return None
    out = folder / "flywheel"
    out.mkdir(exist_ok=True)
    # Made before the process starts: nothing uploads the folder in between.
    (folder / aa_upload.BUILDING).write_text("", encoding="utf-8")
    try:
        with open(out / "report.log", "w", encoding="utf-8") as log:
            return popen([sys.executable, "-m", MODULE, "--recording",
                          str(folder), "--tool", str(tool)],
                         cwd=REPO_ROOT, env=environment(), stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT, **detached())
    except BaseException:
        done(folder)
        raise


def done(folder):
    try:
        (Path(folder) / aa_upload.BUILDING).unlink()
    except OSError:
        pass


def build(folder, *, tool=TOOL, call=subprocess.call):
    """The sheet and the package (in the process ``start_report`` started),
    then ``flywheel/building`` gone, whatever the tool did."""
    try:
        return call([sys.executable, str(tool), "--recording", str(folder),
                     "--with-sheet"], cwd=REPO_ROOT, stdin=subprocess.DEVNULL)
    finally:
        done(folder)


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


def after_close(uploader=None, *, popen=subprocess.Popen):
    """The window is closing (its recording already finished): its uploader
    stops, the rclone it runs is ended, and one upload pass goes on in a
    process of its own once the window lets go of the upload lock. The
    started process, or None (no uploader, uploads switched off, a packaged
    build)."""
    uploader = uploader or aa_upload.current()
    if uploader is None:
        return None
    uploader.stop()
    aa_upload.end_processes()
    if getattr(sys, "frozen", False):
        return None
    try:
        if not uploader.settings()["enabled"]:
            return None
        base = uploader.settings_path.parent
        base.mkdir(parents=True, exist_ok=True)
        with open(base / "after-close.log", "a", encoding="utf-8") as log:
            return popen([sys.executable, "-m", aa_upload.__name__,
                          "--root", str(uploader.root), "--base", str(base)],
                         cwd=REPO_ROOT, env=environment(), stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT, **detached())
    except OSError:
        return None                  # the next window uploads it


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="录像停下后：体检单和场次包")
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--tool", type=Path, default=TOOL)
    args = parser.parse_args(argv)
    return build(args.recording, tool=args.tool)


__all__ = ["after_close", "after_recording", "build", "detached", "start_report"]


if __name__ == "__main__":
    raise SystemExit(main())
