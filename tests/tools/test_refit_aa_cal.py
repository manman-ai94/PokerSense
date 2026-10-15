"""The weekly refit keeps the AA 校准桌 unless new recordings are predicted better."""

from pathlib import Path
import re

import pytest

from poker_engine.scoreboard.calibrated import FITTED, cal_stats
from tools import refit_aa_cal

OLD = {"stats": "old"}
PARAMS = {"mix": 0.6, "flop": {"slow": 0.4}}


class Serial:
    """``ProcessPoolExecutor`` in this process, so the fakes below are used."""

    def __init__(self, workers=1):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, function, items, chunksize=1):
        return map(function, items)


def fake(monkeypatch, hands, losses, read=None):
    """Logs with ``hands[name]`` replayable hands; ``losses[(params mix, first
    log of the half)]`` is the held-out total of a half."""
    read = [] if read is None else read

    def read_log(path):
        name = refit_aa_cal.log_name(path)
        read.append(name)
        return {"name": name, "tasks": [{"log": name}] * hands[name],
                "hands": [name], "minutes": 10.0, "seated": False}

    def fit(train, version, stats, keys, start=None, workers=1):
        assert start is OLD["fitted"] and keys == refit_aa_cal.KEYS
        return {**start, "mix": version}, 0.0

    def score(test, params, version, stats):
        return {"total": losses[(params["mix"], test[0]["where"]["log"])]}

    monkeypatch.setattr(refit_aa_cal, "ProcessPoolExecutor", Serial)
    monkeypatch.setattr(refit_aa_cal, "read_log", read_log)
    monkeypatch.setattr(refit_aa_cal, "prepare",
                        lambda job: {"where": {"log": job[0]["log"]}})
    monkeypatch.setattr(refit_aa_cal, "fit", fit)
    monkeypatch.setattr(refit_aa_cal, "losses", score)
    monkeypatch.setattr(refit_aa_cal, "numbers",
                        lambda logs, names: {"from": sorted(names)})
    return read


@pytest.fixture
def incumbent():
    OLD.update(fitted=PARAMS, logs={"o1": 20.0, "o2": 30.0}, preflop={"x": 1})
    return OLD


def paths(*names):
    return [Path(f"/logs/{name}.jsonl.gz") for name in names]


def test_the_halves_hold_about_as_many_hands():
    groups, counts = refit_aa_cal.halves({"a": 60, "b": 50, "c": 40, "d": 10})
    assert groups == [["a", "d"], ["b", "c"]] and counts == [70, 90]
    # Ties go by name, so the split never depends on the order logs were given.
    assert refit_aa_cal.halves({"y": 5, "x": 5}) == ([["x"], ["y"]], [5, 5])


def test_better_means_lower_on_both_halves():
    def halves(first, second):
        return {"half_1": {"total": first}, "half_2": {"total": second}}

    assert refit_aa_cal.better(halves(9.0, 9.9), halves(10.0, 10.0))
    assert not refit_aa_cal.better(halves(5.0, 10.0), halves(10.0, 10.0))


def test_a_candidate_better_on_both_halves_replaces_numbers_and_parameters(
        monkeypatch, incumbent):
    losses = {("without_1", "n1"): 90.0, (0.6, "n1"): 100.0,
              ("without_2", "n2"): 190.0, (0.6, "n2"): 200.0}
    fake(monkeypatch, {"o1": 5, "o2": 5, "n1": 60, "n2": 40, "n3": 10}, losses)
    result, package = refit_aa_cal.refit(paths("o1", "o2", "n1", "n2", "n3"), incumbent)
    assert result["verdict"] == "accepted" and result["new"] == ["n1", "n2", "n3"]
    assert [half["logs"] for half in result["halves"]] == [["n1"], ["n2", "n3"]]
    assert package["fitted"] == {**PARAMS, "mix": "all"}
    assert package["from"] == ["n1", "n2", "n3", "o1", "o2"]
    # The package's own minutes are kept; new logs bring theirs.
    assert package["logs"] == {"n1": 10.0, "n2": 10.0, "n3": 10.0, "o1": 20.0,
                               "o2": 30.0}
    assert "accepted" in refit_aa_cal.summary(result)


def test_better_on_one_half_only_keeps_the_package(monkeypatch, incumbent):
    losses = {("without_1", "n2"): 90.0, (0.6, "n2"): 100.0,
              ("without_2", "n1"): 201.0, (0.6, "n1"): 200.0}
    fake(monkeypatch, {"o1": 5, "o2": 5, "n1": 60, "n2": 70}, losses)
    result, package = refit_aa_cal.refit(paths("o1", "o2", "n1", "n2"), incumbent)
    assert package is None and result["verdict"] == "kept"
    assert "201.0" in refit_aa_cal.summary(result)


def test_too_few_new_hands_keep_the_package_without_fitting(monkeypatch, incumbent):
    fake(monkeypatch, {"o1": 5, "o2": 5, "n1": 300, "n2": 20}, {})
    result, package = refit_aa_cal.refit(paths("o1", "o2", "n1", "n2"), incumbent)
    assert package is None and result["verdict"] == "kept" and "scores" not in result


def test_the_acceptance_recording_is_never_read(monkeypatch, incumbent):
    read = fake(monkeypatch, {"o1": 5, "o2": 5}, {})
    holdout = "aa_phone_record_20260909_031030_54322c62"
    result, _ = refit_aa_cal.refit(paths("o1", "o2", holdout), incumbent)
    assert holdout not in read and result["refused"] == [holdout]


def test_every_log_of_the_package_must_be_given(monkeypatch, incumbent):
    fake(monkeypatch, {"o1": 5, "n1": 80, "n2": 80}, {})
    with pytest.raises(SystemExit, match="o2"):
        refit_aa_cal.refit(paths("o1", "n1", "n2"), incumbent)


def test_the_package_carries_its_parameters_and_recordings():
    stats = cal_stats()
    assert FITTED is stats["fitted"] and set(FITTED) >= {"mix", "flop", "turn", "river"}
    # Written by the tool (or its first fit): the minutes add up to the source's.
    minutes = float(re.search(r"([\d.]+) minutes", stats["source"]).group(1))
    assert sum(stats["logs"].values()) == pytest.approx(minutes, abs=0.06)
