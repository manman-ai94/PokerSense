"""Replaying every rebuilt hand of a measurement log on the AA table."""

import json

from tests.desktop.test_aa_solver_input import rows
from tools.check_aa_solver_input import hands, main, summarize


def test_hands_are_grouped_and_summarized(tmp_path, capsys):
    log = rows()
    assert list(hands(log)) == ["hand_1"]
    frames = tmp_path / "frames.jsonl"
    frames.write_text("".join(json.dumps(row) + "\n" for row in log))
    main(["--frames", str(frames)])
    report = json.loads(capsys.readouterr().out)
    assert report["summary"] == summarize(report["hands"])
    assert report["summary"]["replayed_fully"] == 1
    assert report["summary"]["dealer_from"] == {"reader": 1}
    assert report["summary"]["opening_pot_matches"] == 1
