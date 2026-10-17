"""The check-up sheet and the session package start on their own when a
recording stops."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest

from poker_engine.desktop import aa_after_session, aa_upload
from poker_engine.desktop.aa_after_session import start_report


def test_the_report_starts_for_a_recording_with_a_window_log(tmp_path):
    tool = tmp_path / "session_package.py"
    tool.write_text("")
    folder = tmp_path / "20261013-200000-live"
    folder.mkdir()
    started = []

    def popen(args, **options):
        started.append((args, options))
        return "process"

    assert start_report(folder, tool=tool, popen=popen) is None   # no frames.jsonl
    (folder / "frames.jsonl").write_text("{}\n")
    assert start_report(tmp_path / "missing", tool=tool, popen=popen) is None
    assert start_report(folder, tool=tmp_path / "gone.py", popen=popen) is None
    assert started == []
    assert start_report(folder, tool=tool, popen=popen) == "process"
    [(args, options)] = started
    assert args == [sys.executable, "-m", "poker_engine.desktop.aa_after_session",
                    "--recording", str(folder), "--tool", str(tool)]
    assert options["cwd"] == aa_after_session.REPO_ROOT
    assert (folder / "flywheel" / "report.log").exists()
    # Uploads wait while it runs; it outlives a closed window.
    assert aa_upload.building(folder)
    if os.name == "nt":
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    else:
        assert options["start_new_session"] is True


def test_a_packaged_build_makes_no_report(tmp_path, monkeypatch):
    tool = tmp_path / "flywheel_session.py"
    tool.write_text("")
    (tmp_path / "frames.jsonl").write_text("{}\n")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert start_report(tmp_path, tool=tool, popen=lambda *a, **k: 1 / 0) is None


def test_the_tool_it_starts_is_there():
    assert aa_after_session.TOOL.exists()


def test_the_package_process_runs_the_tool_then_lets_uploads_go(tmp_path):
    folder = tmp_path / "20261016-210927-live"
    (folder / "flywheel").mkdir(parents=True)
    (folder / aa_upload.BUILDING).write_text("")
    calls = []

    def call(args, **options):
        calls.append(args)
        assert aa_upload.building(folder)        # still being made
        return 0
    assert aa_after_session.build(folder, tool=Path("t.py"), call=call) == 0
    assert calls == [[sys.executable, "t.py", "--recording", str(folder),
                      "--with-sheet"]]
    assert not aa_upload.building(folder)

    (folder / aa_upload.BUILDING).write_text("")

    def broken(args, **options):
        raise OSError("python gone")
    with pytest.raises(OSError):
        aa_after_session.build(folder, call=broken)
    assert not aa_upload.building(folder)       # never left waiting on it


def test_a_package_left_unfinished_is_waited_for_only_so_long(tmp_path):
    (tmp_path / "flywheel").mkdir()
    (tmp_path / aa_upload.BUILDING).write_text("")
    made = (tmp_path / aa_upload.BUILDING).stat().st_mtime
    assert aa_upload.building(tmp_path, now=made + 60)
    assert not aa_upload.building(tmp_path, now=made + aa_upload.REPORT_WAIT + 1)
    assert not aa_upload.building(tmp_path / "other")


FAKE_TOOL = textwrap.dedent("""
    import json, pathlib, sys, time
    folder = pathlib.Path(sys.argv[sys.argv.index("--recording") + 1])
    time.sleep(1.5)
    (folder / "flywheel" / "package.json").write_text(json.dumps({"made": True}))
    print("场次包写好了")
""")


def test_the_package_is_made_after_the_window_is_gone(tmp_path):
    """The window's process ends right after the recording stops (its black
    window closed): the package is still made, and only then may it go up."""
    tool = tmp_path / "tool.py"
    tool.write_text(FAKE_TOOL, encoding="utf-8")
    folder = tmp_path / "20261016-210927-live"
    folder.mkdir()
    (folder / "frames.jsonl").write_text("{}\n")
    window = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import sys, time
            from poker_engine.desktop.aa_after_session import start_report
            start_report({str(folder)!r}, tool={str(tool)!r})
            print("started", flush=True)
            time.sleep(60)
        """)], stdout=subprocess.PIPE, text=True,
        env=aa_after_session.environment())
    try:
        assert window.stdout.readline().strip() == "started"
        assert aa_upload.building(folder)
    finally:
        window.kill()                    # the system ends the window
        window.wait(10)
        window.stdout.close()
    package = folder / "flywheel" / "package.json"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and aa_upload.building(folder):
        time.sleep(0.1)
    assert json.loads(package.read_text()) == {"made": True}
    assert not aa_upload.building(folder)
    assert "场次包写好了" in (folder / "flywheel" / "report.log").read_text(
        encoding="utf-8")


class Uploader:
    def __init__(self, root, base, enabled=True):
        self.root = root
        self.settings_path = base / "settings.json"
        self.enabled = enabled
        self.stopped = False

    def settings(self):
        return {"enabled": self.enabled}

    def stop(self):
        self.stopped = True


def test_closing_the_window_hands_the_upload_to_its_own_process(tmp_path, monkeypatch):
    ended = []
    monkeypatch.setattr(aa_upload, "end_processes", lambda: ended.append(1))
    started = []

    def popen(args, **options):
        started.append((args, options))
        return "process"
    up = Uploader(tmp_path / "recordings", tmp_path / "upload")
    assert aa_after_session.after_close(up, popen=popen) == "process"
    assert up.stopped and ended == [1]
    [(args, options)] = started
    assert args == [sys.executable, "-m", "poker_engine.desktop.aa_upload",
                    "--root", str(tmp_path / "recordings"),
                    "--base", str(tmp_path / "upload")]
    assert options["stdin"] == subprocess.DEVNULL
    if os.name == "nt":
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    else:
        assert options["start_new_session"] is True
    assert (tmp_path / "upload" / "after-close.log").exists()

    started.clear()
    off = Uploader(tmp_path / "recordings", tmp_path / "upload", enabled=False)
    assert aa_after_session.after_close(off, popen=popen) is None
    assert off.stopped and started == []
    monkeypatch.setattr(aa_upload, "_CURRENT", None)
    assert aa_after_session.after_close(popen=popen) is None   # nothing records
