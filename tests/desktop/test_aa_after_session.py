"""The check-up sheet starts on its own when a recording stops."""

import sys

from poker_engine.desktop import aa_after_session
from poker_engine.desktop.aa_after_session import start_report


def test_the_report_starts_for_a_recording_with_a_window_log(tmp_path):
    tool = tmp_path / "flywheel_session.py"
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
    assert args == [sys.executable, str(tool), "report", "--recording", str(folder)]
    assert options["cwd"] == aa_after_session.REPO_ROOT
    assert (folder / "flywheel" / "report.log").exists()


def test_a_packaged_build_makes_no_report(tmp_path, monkeypatch):
    tool = tmp_path / "flywheel_session.py"
    tool.write_text("")
    (tmp_path / "frames.jsonl").write_text("{}\n")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert start_report(tmp_path, tool=tool, popen=lambda *a, **k: 1 / 0) is None


def test_the_tool_it_starts_is_there():
    assert aa_after_session.TOOL.exists()
