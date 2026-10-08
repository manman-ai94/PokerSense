"""The gauntlet: every strategy against every kind of opponent table."""

import json

import pytest

from tools import run_gauntlet
from tools.run_gauntlet import main, needs_solver, verdict, weakest


def test_verdict_reads_the_interval():
    assert verdict({"ci95": [1.0, 9.0]}) == "wins"
    assert verdict({"ci95": [-9.0, -1.0]}) == "loses"
    assert verdict({"ci95": [-1.0, 9.0]}) == "unclear"
    assert verdict({"ci95": None}) == "unclear"


def part(value, share=0.2):
    return {"bb_per_100": value, "share": share}


def test_weakest_parts_compare_with_the_baseline_table():
    base = {"by_flop": {"preflop": part(-50), "heads_up": part(10)},
            "by_end": {"preflop": part(-60), "showdown": part(30)}}
    here = {"by_flop": {"preflop": part(-140), "heads_up": part(12)},
            "by_end": {"preflop": part(-70), "showdown": part(-20, 0.1)}}
    assert weakest(here, base) == [("to the flop: preflop", -90, 0.2),
                                   ("ended: showdown", -50, 0.1)]


def test_solver_pools_are_refused_without_the_solver(monkeypatch):
    assert needs_solver(("solver_turn+reg",)) and not needs_solver(("reg", "nit"))
    monkeypatch.setattr(run_gauntlet, "solver_binary", lambda: None)
    with pytest.raises(SystemExit):
        main(["--deals", "2", "--pools", "reg,solver"])


def test_small_gauntlet_writes_every_pool(tmp_path, capsys):
    main(["--deals", "2", "--workers", "1", "--strategies", "tag",
          "--reference", "always_call", "--pools", "aa,maniac", "--out", str(tmp_path)])
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert set(summary["strategies"]) == {"tag", "always_call"}
    assert set(summary["strategies"]["tag"]) == {"aa", "maniac"}
    assert summary["strategies"]["tag"]["aa"]["weakest"] == []
    assert "vs_reference" in summary["strategies"]["tag"]["maniac"]
    assert (tmp_path / "maniac.json").is_file()
    assert "maniac" in capsys.readouterr().out


def test_mushroom_take_is_measured_per_table(tmp_path):
    main(["--deals", "3", "--calibration-deals", "2", "--workers", "1",
          "--strategies", "aa_preflop", "--pools", "nit", "--mushroom", "3",
          "--out", str(tmp_path)])
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    take = summary["mushroom"]["take"]["nit"]
    report = json.loads((tmp_path / "nit.json").read_text(encoding="utf-8"))
    assert report["mushroom"]["take"] == take
    assert 0 < take <= 1


def test_resume_reuses_saved_pools(tmp_path, monkeypatch):
    args = ["--deals", "2", "--workers", "1", "--strategies", "tag", "--pools",
            "aa,nit", "--out", str(tmp_path)]
    main(args)
    saved = (tmp_path / "aa.json").read_text(encoding="utf-8")
    played = []
    real = run_gauntlet.run_scoreboard
    monkeypatch.setattr(run_gauntlet, "run_scoreboard",
                        lambda *a, **k: played.append(k["pool"]) or real(*a, **k))
    main(args + ["--resume"])
    assert played == []
    main(["--deals", "3", *args[2:], "--resume"])          # other settings: rerun
    assert len(played) == 2
    assert (tmp_path / "aa.json").read_text(encoding="utf-8") != saved


def test_reads_are_given_and_count_for_resume(tmp_path, monkeypatch):
    args = ["--deals", "2", "--workers", "1", "--strategies",
            "aa_preflop,noreads+aa_preflop", "--pools", "nit", "--out", str(tmp_path)]
    main(args + ["--reads", "40"])
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["reads"] == 40
    report = json.loads((tmp_path / "nit.json").read_text(encoding="utf-8"))
    assert report["reads"]["hands"] == 40
    played = []
    real = run_gauntlet.run_scoreboard
    monkeypatch.setattr(run_gauntlet, "run_scoreboard",
                        lambda *a, **k: played.append(k["reads"]) or real(*a, **k))
    main(args + ["--reads", "40", "--resume"])
    assert played == []
    main(args + ["--resume"])                               # without reads: rerun
    assert played == [None]


def test_bomb_pots_are_scored_and_count_for_resume(tmp_path, monkeypatch):
    args = ["--deals", "3", "--workers", "1", "--strategies", "population",
            "--pools", "nit", "--out", str(tmp_path), "--bomb", "7"]
    main(args + ["--bomb-share", "1"])
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["bomb"] == {"post_big_blinds": 7.0, "share": 1.0}
    assert summary["strategies"]["population"]["nit"]["bomb"]["share"] == 1.0
    played = []
    real = run_gauntlet.run_scoreboard
    monkeypatch.setattr(run_gauntlet, "run_scoreboard",
                        lambda *a, **k: played.append(k["bomb"]) or real(*a, **k))
    main(args + ["--bomb-share", "1", "--resume"])
    assert played == []
    main(args + ["--resume"])                         # another share: rerun
    assert played == [run_gauntlet.Bomb(7, 0.07)]
