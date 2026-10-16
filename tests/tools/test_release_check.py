"""The release check on synthetic logs and runs (no recording, no solver)."""

import json
from pathlib import Path

from tools import release_check as check
from tools.flywheel_gates import git

# A 2/4/8(4) table, eight players, you (seat 4) on the button. Seat 0 limps,
# you raise to 40, seat 0 re-raises to 170; your buttons are up on frames
# 20-27 (as in test_aa_compare_advice).
ACTIONS = [
    (10, "preflop", 0, "call", "8"), (11, "preflop", 1, "fold", "0"),
    (12, "preflop", 2, "fold", "0"), (13, "preflop", 3, "fold", "0"),
    (14, "preflop", 4, "raise", "40"), (15, "preflop", 5, "fold", "0"),
    (16, "preflop", 6, "fold", "0"), (17, "preflop", 7, "fold", "0"),
    (18, "preflop", 0, "raise", "162"), (28, "preflop", 4, "call", "130"),
]
STACKS = {"0": "226", "1": "396", "2": "396", "3": "396", "4": "356",
          "5": "394", "6": "392", "7": "388"}


def rows(hand_id="hand_1", seconds=0.0):
    history = {"hand_id": hand_id, "complete": True, "start": "pot_went_down",
               "dealer": 4}
    result = []
    for frame in range(30):
        wagers = ({str(seat): "4" for seat in range(8)} if frame == 3 else
                  {"5": "2", "6": "4", "7": "8"} if 4 <= frame < 10 else {})
        turn = 20 <= frame < 28
        fields = {
            "pot": "0" if frame < 3 else "46" if frame < 19 else "256",
            "street": "preflop",
            "participants": {str(seat): "active" for seat in range(8)},
            "street_wagers": wagers, "board": [None] * 5, "hero": ["Ad", "Qd"],
            "stacks": STACKS if frame >= 19 else {}, "scene_supported": True,
            "hero_controls": {"visible": turn, "button": "call",
                              "call_amount": "130" if turn else None},
            "actions_v1": {**history, "actions": [
                list(a) + ["no_chips"] for a in ACTIONS if a[0] <= frame]}}
        result.append({"processed": frame, "pts_seconds": frame * 0.1,
                       "video_seconds": seconds + frame * 0.1, "fields": fields})
    return result


def write_log(folder, items):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "frames.jsonl", "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"code": "test"}) + "\n")
        for item in items:
            handle.write(json.dumps(item) + "\n")
    return folder / "frames.jsonl"


def test_the_held_out_part_is_always_skipped(tmp_path):
    held = tmp_path / "aa_phone_record_20260909_031030_54322c62"
    assert check.windows_for(held) == ((300.0, 820.0),)
    assert check.windows_for(tmp_path / "20261008-153114-live") == ()
    assert check.windows_for(held, ((10.0, 20.0),)) == ((10.0, 20.0), (300.0, 820.0))
    log = write_log(held, rows(seconds=290.0) + rows("hand_2", seconds=400.0))
    kept = check.kept_log("held", log, check.windows_for(held), tmp_path)
    lines = [json.loads(line) for line in kept.read_text().splitlines()]
    assert lines[0] == {"code": "test"}
    assert all(row["video_seconds"] < 300 for row in lines[1:])
    assert len(lines) == 1 + 30
    assert check.kept_log("other", log, (), tmp_path) == log
    untimed = write_log(tmp_path / "untimed", [{"fields": {}}])
    assert check.kept_log("untimed", untimed, ((300.0, 820.0),), tmp_path) is None


def test_recordings_are_found_by_folder_log_or_parent(tmp_path):
    one = write_log(tmp_path / "all" / "one", [])
    two = write_log(tmp_path / "all" / "two", [])
    assert check.recording_logs([tmp_path / "all" / "one"]) == [("one", one)]
    assert check.recording_logs([two]) == [("two", two)]
    assert check.recording_logs([tmp_path / "all"]) == [("one", one), ("two", two)]


def _replayed(action, fully, *, kind="preflop", to=None):
    advice = {"action": action, **({"to": to} if to else {})}
    report = {"status": "ready", "kind": kind, "advice": [advice]}
    return {"summary": {"fully_advised": {"hands": 1, "advised": fully,
                                          "past_preflop": 0, "past_preflop_advised": 0},
                        "advised": fully, "your_decisions": 1,
                        "advised_by_kind": {kind: fully}},
            "logs": [{"name": "log", "rows": 30, "reports": {
                str(i): report for i in range(20, 28)}}]}


def test_changed_advice_is_listed_with_the_rule_that_gave_it():
    logs = [("log", rows())]
    same = check.compare_replays(logs, _replayed("raise", 1, to="170"),
                                 _replayed("raise", 1, to="170"))
    assert same["passed"] and same["changed"] == same["size_only"] == 0
    result = check.compare_replays(logs, _replayed("raise", 1, to="170"),
                                   _replayed("call", 1))
    assert result["passed"] and result["changed"] == 1
    assert result["why"] == [("翻前 · 翻前 → 翻前：加注→跟注 1", 1)]
    [item] = result["changes"]
    assert (item["hand_id"], item["you_did"]) == ("hand_1", "call")
    sized = check.compare_replays(logs, _replayed("raise", 1, to="170"),
                                  _replayed("raise", 1, to="356"))
    assert (sized["changed"], sized["size_only"], sized["why"]) == (0, 1, [])


def test_answers_of_the_solver_stand_in_are_listed_apart():
    # Without --solver a heads-up solve comes back at once as check or call
    # (10/16: a rough fold that became "solver call, equity 0%" was nearly
    # taken for a bug).
    logs = [("log", rows())]
    result = check.compare_replays(logs, _replayed("fold", 1, kind="rough"),
                                   _replayed("call", 1, kind="solver"))
    assert result["passed"]
    assert (result["changed"], result["stand_in"]) == (0, 1)
    assert result["why"] == [] and result["priced"] is None
    assert result["stand_in_why"] == [("翻前 · 粗略 → 求解器替身：弃牌→替身 1", 1)]
    [item] = result["changes"]
    assert item["stand_in"] and item["note"] == check.STAND_IN
    text = check.page({"old": A, "new": B, "finished": "", "minutes": 1.0,
                       "not_run": {}, "steps": {"replay": result}})
    assert "建议变了 0 处（另 1 处是求解器替身，不算）" in text
    assert "另有 1 处一边是求解器替身（不是真实建议）" in text
    assert "粗略弃牌 → 求解器替身（不是真实建议），你跟注" in text
    # With --solver its answers are the solver's own.
    real = check.compare_replays(logs, _replayed("fold", 1, kind="rough"),
                                 _replayed("call", 1, kind="solver"), solver=True)
    assert (real["changed"], real["stand_in"]) == (1, 0)
    assert real["why"] == [("翻前 · 粗略 → 求解器：弃牌→跟注 1", 1)]


def _gone():
    gone = _replayed("call", 0)
    gone["logs"][0]["reports"] = {
        str(i): {"status": "abstain", "reason": "unknown_seats"} for i in range(20, 28)}
    return gone


def test_less_advice_on_the_recordings_fails():
    result = check.compare_replays([("log", rows())], _replayed("call", 1), _gone())
    assert not result["passed"]
    assert result["reasons"] == ["每一步都有建议的手从 1 变成 0", "有建议的决策从 1 变成 0"]
    assert result["why"] == [("翻前 · 翻前 → 没有建议：跟注→无（unknown_seats） 1", 1)]


def _run(**changes):
    numbers = {"run": "ENDED",
               "coverage": {"pot": {"value": 0.99, "n": 5000},
                            "postflop_advice": {"value": 0.75, "n": 20}},
               "stalls_over_2s": 2, "dropped": 0.05, "latency_p95_ms": 200.0,
               "fully_advised": {"value": 0.9, "n": 100},
               "advised": {"value": 0.95, "n": 300},
               "seconds_to_advice_median": 0.4}
    for key, value in changes.items():
        if key in numbers["coverage"]:
            numbers["coverage"][key] = {**numbers["coverage"][key], "value": value}
        else:
            numbers[key] = value
    return numbers


def test_a_run_at_recorded_pace_fails_only_past_the_noise():
    labels = {"pot": "底池", "postflop_advice": "翻后轮到你：给出建议"}
    rows_, reasons = check.compare_runs(_run(), _run(pot=0.985, stalls_over_2s=3,
                                                     postflop_advice=0.66), labels)
    assert reasons == []
    assert [row["what"] for row in rows_][:2] == ["底池", "翻后轮到你：给出建议"]
    _, reasons = check.compare_runs(_run(), _run(pot=0.97), labels)
    assert reasons == ["底池：99.0% → 97.0%"]
    # Few decisions: two of twenty is within the noise, three is not.
    _, reasons = check.compare_runs(_run(), _run(postflop_advice=0.6), labels)
    assert reasons == ["翻后轮到你：给出建议：75.0% → 60.0%"]
    _, reasons = check.compare_runs(
        _run(), _run(stalls_over_2s=4, dropped=0.08, latency_p95_ms=400.0), labels)
    assert reasons == ["卡顿超过 2 秒：2 → 4", "丢帧：5.0% → 8.0%",
                       "画面延迟 p95（毫秒）：200.0 → 400.0"]
    _, reasons = check.compare_runs(_run(run="ERROR"), _run(), labels)
    assert reasons == ["旧版没放完（ERROR）"]


def _measured_run(folder, items, status="ENDED", dropped=0.01):
    write_log(folder, items)
    (folder / "summary.json").write_text(json.dumps({
        "run": {"status": status}, "summary": {
            "frames_dropped_fraction": dropped,
            "latency_ms": {"arrival_to_published": {"p95": 120.0}}}}))


def _recording(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "recording.json").write_text(json.dumps({"recorded_seconds": 600}))
    return folder


def _played(monkeypatch):
    """Play no recording: each run at recorded pace writes a short finished
    log. The (version, recording) of each run, in the order played."""
    played = []

    def run_tool(tree, args, log):
        _measured_run(Path(args[args.index("--out") + 1]), rows())
        played.append((tree, Path(args[args.index("--video") + 1]).name))
        return 0

    monkeypatch.setattr("tools.flywheel_gates.run_tool", run_tool)
    return played


A, B, C = "a" * 40, "b" * 40, "c" * 40


def test_both_versions_are_played_in_the_same_check(tmp_path, monkeypatch):
    played = _played(monkeypatch)
    folder = _recording(tmp_path, "20261008-153114-live")
    cache = tmp_path / "cache"
    check.measure_step({"old": "a", "new": "b"}, {"old": A, "new": B}, [folder], (),
                       cache, tmp_path)
    # b was the new version last time and is the old one now: that run met
    # another day's machine, so b is played again next to c.
    played.clear()
    result = check.measure_step({"old": "b", "new": "c"}, {"old": B, "new": C},
                                [folder], (), cache, tmp_path)
    assert played == [("b", folder.name), ("c", folder.name)]
    [item] = result["recordings"]
    assert item["reused"] == {"old": False, "new": False}
    assert set(item["finished_at"]) == {"old", "new"}


def test_a_check_cut_short_picks_up_its_own_runs(tmp_path, monkeypatch):
    played = _played(monkeypatch)
    folder = _recording(tmp_path, "20261008-153114-live")
    args = ({"old": "a", "new": "b"}, {"old": A, "new": B}, [folder], (),
            tmp_path / "cache", tmp_path)
    check.measure_step(*args)
    played.clear()
    result = check.measure_step(*args)
    assert result["passed"], result["reasons"]
    assert played == []
    [item] = result["recordings"]
    assert item["reused"] == {"old": True, "new": True} and item["minutes"] == 10.0
    pot = next(row for row in item["rows"] if row["what"] == "底池")
    assert pot["old"] == pot["new"] == 1.0
    assert any(row["what"] == "卡顿超过 2 秒" for row in item["rows"])
    text = check.page({"old": A, "new": B, "finished": "", "minutes": 1.0,
                       "not_run": {}, "steps": {"measure": result}})
    assert "两版都在这次复查里放：旧版 " in text
    # The same two versions checked again into a new folder: played again.
    (tmp_path / "again").mkdir()
    check.measure_step(*args[:5], tmp_path / "again")
    assert played == [("a", folder.name), ("b", folder.name)]


def test_the_order_alternates_and_a_version_against_itself_plays_twice(
        tmp_path, monkeypatch):
    played = _played(monkeypatch)
    first, second = _recording(tmp_path, "rec-1"), _recording(tmp_path, "rec-2")
    cache = tmp_path / "cache"
    check.measure_step({"old": "a", "new": "b"}, {"old": A, "new": B},
                       [first, second], (), cache, tmp_path)
    assert played == [("a", "rec-1"), ("b", "rec-1"), ("b", "rec-2"), ("a", "rec-2")]
    played.clear()
    result = check.measure_step({"old": "a", "new": "a"}, {"old": A, "new": A},
                                [first], (), cache, tmp_path)
    assert played == [("a", "rec-1"), ("a", "rec-1")]
    [item] = result["recordings"]
    assert item["runs"]["old"] != item["runs"]["new"]


def test_the_plan_says_how_long_the_slow_part_takes(tmp_path, capsys):
    held = tmp_path / "aa_phone_record_20260909_031030_54322c62"
    held.mkdir()
    (held / "recording.json").write_text(json.dumps({"recorded_seconds": 1000}))
    status = check.main(["HEAD", "HEAD", "--measure", str(held), "--plan",
                         "--cache", str(tmp_path / "cache"),
                         "--out", str(tmp_path / "o")])
    assert status == 0
    out = capsys.readouterr().out
    assert "8.0 分钟 × 2 版" in out           # 1000 s less 300-820
    assert "合计约 16 分钟" in out
    assert not (tmp_path / "o").exists()


def test_the_second_seat_verdict_comes_from_its_own_table(tmp_path, monkeypatch):
    def fake(tree, args, log):
        target = tmp_path / "p30"
        target.mkdir()
        rows_ = [{"label": "底池", "value": 0.935, "line": 0.867, "verdict": "通过"},
                 {"label": "翻后轮到你：给出建议", "value": None, "line": 0.67,
                  "verdict": "量不了", "note": "只有 8 个翻后决策"}]
        (target / "acceptance.json").write_text(json.dumps({"acceptance": {
            "rows": rows_, "overall": "没量全", "counts": {"通过": 1, "量不了": 1}}}))
        assert args[:2] == ["tools/p30_acceptance.py", "run"]
        assert "--frames" in args
        return 1

    monkeypatch.setattr("tools.flywheel_gates.run_tool", fake)
    result = check.p30_step(None, tmp_path / "du", tmp_path / "frames.jsonl", (),
                            tmp_path)
    assert not result["passed"] and result["overall"] == "没量全"
    assert result["reasons"] == ["翻后轮到你：给出建议 —（线 67.0%）：只有 8 个翻后决策"]


def test_tests_run_flake8_and_the_tests_of_what_changed(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("tools.flywheel_gates.run_tool",
                        lambda tree, args, log: calls.append(args) or 0)
    monkeypatch.setattr(check, "changed_between", lambda old, new: [
        "tools/p30_acceptance.py", "ui/aa-live/signal_view.js", "docs/WORKLOG.md"])
    result = check.tests_step(check.ROOT, "a", "b", None, tmp_path)
    assert result["passed"]
    assert calls[0][:2] == ["-m", "flake8"] and "src" in calls[0]
    assert calls[1] == ["-m", "pytest", "-q", "tests/desktop",
                        "tests/tools/test_p30_acceptance.py"]


def test_page_says_what_ran_and_what_did_not():
    result = {"old": "a" * 40, "new": "b" * 40, "finished": "2026-10-15 09:00",
              "minutes": 3.0, "not_run": {"measure": "前面没过，没跑（要跑加 --keep-going）"},
              "steps": {"tests": {"passed": True, "reasons": [],
                                  "test_paths": ["tests/desktop"],
                                  "pytest_tail": "12 passed in 3.0s"},
                        "replay": check.compare_replays([("log", rows())],
                                                        _replayed("call", 1), _gone()),
                        "measure": None, "p30": None}}
    text = check.page(result)
    assert text.startswith("# 装新版前复查：没过（没跑：按原速重放、杜的 P30 验收）")
    assert "旧版 aaaaaaa → 新版 bbbbbbb" in text
    assert "| 测试和代码检查 | 通过 | flake8 和相关测试（tests/desktop）：12 passed in 3.0s |" in text
    assert "每一步都有建议的手从 1 变成 0" in text
    assert ("- log hand_1，录像第 2 秒：翻前 Ad Qd，翻前跟注 → 没有建议，你跟注"
            in text)
    assert "| 按原速重放 | 没跑 | 前面没过，没跑（要跑加 --keep-going） |" in text
    assert "求解器当作立刻算完" in text


def test_main_replays_both_versions_in_worktrees_and_cleans_up(
        tmp_path, capsys, monkeypatch):
    write_log(tmp_path / "rec" / "20261010-120000-live", rows())
    # Only this run's worktrees: tests in other workers add their own meanwhile.
    made = []
    real = check.checkout

    def checkout(ref):
        commit, folder = real(ref)
        made.append(folder)
        return commit, folder

    monkeypatch.setattr(check, "checkout", checkout)
    out = tmp_path / "out"
    status = check.main(["HEAD", "HEAD", "--recording", str(tmp_path / "rec"),
                         "--no-tests", "--window-open-ok", "--out", str(out)])
    result = json.loads((out / "release_check.json").read_text(encoding="utf-8"))
    assert status == 0, (out / "replay-old.log").read_text()
    replay = result["steps"]["replay"]
    assert replay["passed"] and replay["changed"] == 0 and replay["logs"] == 1
    assert replay["numbers"][0] == {"what": "每一步都有建议的手", "old": 1, "new": 1}
    assert result["old"] == result["new"] == git("rev-parse", "HEAD")
    assert (out / "复查单.md").read_text(encoding="utf-8").startswith(
        "# 装新版前复查：通过（没跑：测试和代码检查、按原速重放、杜的 P30 验收）")
    assert "录像日志重放" in capsys.readouterr().out
    listed = git("worktree", "list", "--porcelain")
    assert len(made) == 1  # the same commit is checked out once
    assert not any(folder.exists() for folder in made)
    assert not any(str(path) in listed for folder in made
                   for path in (folder, folder.resolve()))
