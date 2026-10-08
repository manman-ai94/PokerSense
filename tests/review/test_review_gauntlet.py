"""Review: run_gauntlet --resume and reference labelling.

Each test fails on the current code because a saved pool report is reused
(or a comparison is labelled) under settings it was not computed with.
"""

import json
from pathlib import Path
from statistics import fmean

import pytest

from tools.run_gauntlet import main

ROOT = Path(__file__).resolve().parents[2]
UNRAKED = ROOT / "configs/game/aa-scoreboard-rules-v1.json"
RAKED = ROOT / "configs/game/aa-scoreboard-rules-v2.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_resume_does_not_reuse_a_pool_scored_against_another_reference(tmp_path):
    base = ["--deals", "2", "--workers", "1", "--strategies", "tag,always_call",
            "--pools", "nit", "--out", str(tmp_path)]
    main(base + ["--reference", "rock"])
    main(base + ["--reference", "always_call", "--resume"])
    summary = read(tmp_path / "summary.json")
    assert summary["reference"] == "always_call"
    per_deal = read(tmp_path / "nit.json")["per_deal"]
    expected = round(fmean(row["tag"] - row["always_call"]
                           for _, row in per_deal) * 100, 2)
    cell = summary["strategies"]["tag"]["nit"]["vs_reference"]
    # On the current code the reused nit.json still holds tag - rock.
    assert cell["delta_bb_per_100"] == pytest.approx(expected, abs=0.02)


def test_resume_does_not_reuse_a_pool_played_under_other_rules(tmp_path):
    base = ["--deals", "2", "--workers", "1", "--strategies", "tag",
            "--pools", "nit", "--out", str(tmp_path)]
    main(base + ["--rules", str(UNRAKED)])
    main(base + ["--rules", str(RAKED), "--resume"])
    # The unraked report is reused for a raked run on the current code.
    assert read(tmp_path / "nit.json")["rules"] == read(RAKED)


def test_without_reference_the_comparison_names_the_strategy_it_used(
        tmp_path, capsys):
    main(["--deals", "2", "--workers", "1", "--strategies", "tag,rock",
          "--pools", "nit", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    report = read(tmp_path / "nit.json")
    assert report["reference"] == "tag"          # what the deltas are against
    assert "vs None" not in out
    assert read(tmp_path / "summary.json")["reference"] == report["reference"]
