import json
from pathlib import Path

from tools import tester_review as review
from tools.flywheel_sync import digest_of

BASELINE = (Path(__file__).resolve().parents[2]
            / "configs/acceptance/second_seat_baseline_v1.json")


def row(frame, *, hand="hand_0", turn=False, advice=None, pot=10, actions=(),
        recognition_ms=300.0, seconds=0.4):
    return {"processed": frame, "pts_seconds": frame * seconds,
            "timing": {"published_at": frame * seconds,
                       "recognition_ms": recognition_ms},
            "fields": {"scene_supported": True, "hero": ["As", "Kd"],
                       "board": [None] * 5, "dealer": 5, "actor": 4 if turn else 6,
                       "participants": {**{str(slot): "empty" for slot in range(8)},
                                        "4": "active", "5": "active", "6": "active"},
                       "hero_controls": {"visible": turn, "button": "call",
                                         "call_amount": "4" if turn else None},
                       "street": "preflop", "stacks": {"4": "100", "5": "90",
                                                       "6": "80"},
                       "pot": pot,
                       "actions_v1": {"hand_id": hand, "complete": False,
                                      "start": "boundary", "dealer": 5,
                                      "actions": [list(a) for a in actions]},
                       "solver_advice": advice or {"status": "idle",
                                                   "reason": "not_your_turn"}}}


RAISED = [(3, "preflop", 5, "raise", "8", "bet")]
BLANK = {"status": "abstain", "reason": "dealer_ambiguous"}


def recording(tmp_path, name="20261015-102047-live", *, machine="du", rows=None):
    """One hand on a slow computer: its turn comes and no advice shows."""
    rows = rows or ([row(f) for f in range(3)]
                    + [row(f, actions=RAISED) for f in range(3, 5)]
                    + [row(f, turn=True, advice=BLANK, actions=RAISED)
                       for f in range(5, 8)])
    folder = tmp_path / machine / name
    folder.mkdir(parents=True)
    text = "\n".join(json.dumps(item) for item in rows) + "\n"
    (folder / "frames.jsonl").write_text(text, encoding="utf-8")
    info = {"started": "2026-10-15T10:20:47+0800", "recorded_seconds": 1090.3,
            "megabytes": 379.1, "offered_frames": 31019, "skipped_frames": 341,
            "code": {"commit": "f2ef4cbda7a3"}, "backend": "FFMPEG", "error": None}
    (folder / "recording.json").write_text(json.dumps(info), encoding="utf-8")
    files = [["frames.jsonl", len(text.encode("utf-8"))], ["recording.json", 1]]
    (folder / "upload.json").write_text(json.dumps(
        {"machine": machine, "folder": name, "files": files}), encoding="utf-8")
    return folder


def args(tmp_path, folders):
    return review.argparse.Namespace(
        recording=list(folders), state=tmp_path / "state", out=tmp_path / "out",
        baseline=BASELINE, machine=None, day="2026-10-15", again=False)


def test_machine_and_name_come_from_the_upload_marker(tmp_path):
    folder = recording(tmp_path)
    files = json.loads((folder / "upload.json").read_text(encoding="utf-8"))["files"]
    assert review.identify(folder) == ("du", "20261015-102047-live", digest_of(files))
    pulled = tmp_path / "du-x"
    pulled.mkdir()
    (pulled / "pulled.json").write_text(json.dumps(
        {"machine": "du", "folder": "x", "digest": "abc"}), encoding="utf-8")
    assert review.identify(pulled) == ("du", "x", "abc")
    bare = tmp_path / "bare"
    bare.mkdir()
    assert review.identify(bare, "mac") == ("mac", "bare", "frames.jsonl:0")


def test_a_run_reviews_new_recordings_once(tmp_path, capsys):
    folder = recording(tmp_path)
    assert review.run(args(tmp_path, [folder])) == 0
    state, out = tmp_path / "state", tmp_path / "out"
    [entry] = review.read_lines(state / review.REVIEWED)
    assert (entry["machine"], entry["log"]) == ("du", "du-20261015-102047-live")
    assert entry["numbers"]["blank"] == 1 and entry["numbers"]["turns"] == 1
    assert entry["minutes"] == 18.17
    result = json.loads((out / "du-20261015-102047-live.json").read_text(
        encoding="utf-8"))
    assert result["speed"]["frames_per_second"] == 2.5
    assert result["speed"]["recognition_ms"] == 300
    sheet = (out / review.SHEET).read_text(encoding="utf-8")
    assert "10/14 晚上 7:20（洛杉矶）" in sheet and "代码 f2ef4cb" in sheet
    assert "- 电脑太慢：每秒只读 2.5 帧" in sheet
    assert "轮到他 1 次，1 次窗口没给建议（庄位没认清 1）" in sheet
    lines = (out / review.LINES).read_text(encoding="utf-8").splitlines()
    assert lines[0] == ("复盘了 du 的 1 场录像（18 分钟，1 手）；"
                        "20261015-102047 读帧 2.5/秒、识别 300 毫秒/帧")
    assert lines[1].startswith("问题：电脑太慢：每秒只读 2.5 帧；轮到他 1 次")
    assert "（" not in lines[1]
    capsys.readouterr()
    review.run(args(tmp_path, [folder]))            # nothing new: skipped
    assert "已经复盘过" in capsys.readouterr().out
    assert (out / review.LINES).read_text(encoding="utf-8").startswith("没有新录像")
    again = args(tmp_path, [folder])
    again.again = True
    review.run(again)
    assert len(review.read_lines(state / review.REVIEWED)) == 1
    logs = {line["log"] for line in review.read_lines(state / review.HANDS)}
    assert logs == {"du-20261015-102047-live"}


def test_the_next_recording_says_what_moved(tmp_path):
    first = recording(tmp_path)
    review.run(args(tmp_path, [first]))
    second = recording(tmp_path, "20261016-190000-live")
    rows = [json.loads(line) for line in (second / "frames.jsonl").read_text(
        encoding="utf-8").splitlines()]
    for item in rows:
        item["pts_seconds"] = item["processed"] * 0.125
        if item["fields"]["hero_controls"]["visible"]:
            item["fields"]["solver_advice"] = {
                "status": "ready", "kind": "preflop", "advice": [{"action": "call"}]}
    (second / "frames.jsonl").write_text(
        "\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")
    review.run(args(tmp_path, [second]))
    sheet = (tmp_path / "out" / review.SHEET).read_text(encoding="utf-8")
    assert "和上次（20261015-102047-live）比：读帧 2.5/秒 → 8/秒；没建议的轮次 100% → 0%" in sheet
    assert "电脑太慢" not in sheet


CALL = {"status": "ready", "kind": "preflop", "advice": [{"action": "call"}]}


def four_handed(frame, hand, stack, *, cards=("As", "Kd"), **more):
    """A frame at four players with him on the button (dealer)."""
    item = row(frame, hand=hand, **more)
    fields = item["fields"]
    fields["hero"] = list(cards)
    fields["participants"]["7"] = "active"
    fields["stacks"] = {"4": stack}
    fields["dealer"] = fields["actions_v1"]["dealer"] = 4
    return item


def played_rows():
    """He calls 4 on the button with ace-king and loses it, then folds 7-2."""
    called = [(6, "preflop", 4, "call", "4", "bet")]
    return ([four_handed(f, "hand_0", "100") for f in range(5)]
            + [four_handed(5, "hand_0", "100", turn=True, advice=CALL),
               four_handed(6, "hand_0", "96", actions=called)]
            + [four_handed(f, "hand_7", "96", cards=("7c", "2d")) for f in range(7, 12)]
            + [four_handed(f, "hand_12", "96") for f in range(12, 15)])


def test_results_with_the_luck_out_go_on_the_sheet_and_stay_private(tmp_path, capsys):
    folder = recording(tmp_path, "20261016-190000-live", rows=played_rows())
    review.run(args(tmp_path, [folder]))
    state, out = tmp_path / "state", tmp_path / "out"
    hands = review.read_lines(state / review.RESULTS)
    assert [(line["machine"], line["log"], line["bb"]) for line in hands] == [
        ("du", "du-20261016-190000-live", -2.0), ("du", "du-20261016-190000-live", 0.0)]
    assert hands[0]["seat"] == "BTN" and hands[0]["card_luck"] is not None
    assert hands[0]["code"] == "f2ef4cbda7a3"
    [decision] = review.read_lines(state / review.DECISIONS)
    assert (decision["advice"], decision["you_did"], decision["followed"]) == (
        "call", "call", True)
    result = json.loads((out / "du-20261016-190000-live.json").read_text(
        encoding="utf-8"))
    assert result["results"]["hands"] == 2 and "hand_id" not in str(result["results"])
    sheet = (out / review.SHEET).read_text(encoding="utf-8")
    assert "成绩（积分）：\n- 2 手：打出来 -100 bb/100；扣掉运气 " in sheet
    assert "## du 到今天为止的成绩" in sheet
    lines = (out / review.LINES).read_text(encoding="utf-8").splitlines()
    assert "；du 累计 2 手扣掉运气 " in lines[2] and lines[2].endswith("（说不准）")
    again = args(tmp_path, [folder])
    again.again = True
    review.run(again)                                 # replaced, not added
    assert len(review.read_lines(state / review.RESULTS)) == 2
    assert len(review.read_lines(state / review.DECISIONS)) == 1
    capsys.readouterr()
    total = tmp_path / "成绩.json"
    assert review.main(["results", "--state", str(state), "--out", str(total)]) == 0
    report = json.loads(total.read_text(encoding="utf-8"))
    assert report["machines"]["du"]["hands"] == 2 and report["all"]["hands"] == 2
    assert capsys.readouterr().out.startswith("du：2 手：打出来 -100 bb/100")


def result(**more):
    base = {"frames": 100, "recording": {"error": None, "skipped": 0.01,
                                         "mb_per_hour": 800, "backend": "FFMPEG",
                                         "fourcc": "mp4v"},
            "speed": {"frames_per_second": 7.5, "recognition_ms": 90},
            "advice": {"hands": 20, "turns": 30, "blank": 0, "causes": {},
                       "past_preflop_advised": [5, 5], "stalls_over_2s": 0,
                       "hand_problems": {}},
            "recognition": {"rows": []}, "stakes_read": [20, 20],
            "opponents_usable": [17, 20]}
    for key, value in more.items():
        base[key] = {**base[key], **value} if isinstance(value, dict) else value
    return base


def test_a_good_recording_has_no_problems():
    assert review.problems(result()) == []
    assert review.problems(result(frames=0)) == ["窗口日志是空的：这场没有可复盘的帧"]


def test_problems_are_measured_against_the_mac():
    found = review.problems(result(
        speed={"frames_per_second": 2.3, "recognition_ms": 360},
        advice={"blank": 2, "causes": {"abstain:street_mismatch": 2},
                "past_preflop_advised": [0, 5], "stalls_over_2s": 1,
                "hand_problems": {"replay_stops:raise_without_amount": 7,
                                  "hands_with_skipped_seats": 3,
                                  "board_card_read_two_ways": 2,
                                  "hand_split_in_two": 2}},
        recognition={"rows": [
            {"label": "你的手牌", "value": 0.5, "baseline": 0.64, "line": 0.58,
             "verdict": "不通过"},
            {"label": "底池", "value": 0.97, "baseline": 0.96, "line": 0.87,
             "verdict": "通过"}]},
        stakes_read=[2, 20], opponents_usable=[9, 20],
        recording={"skipped": 0.05, "mb_per_hour": 26000, "backend": None,
                   "fourcc": "avc1"}))
    assert found == [
        "电脑太慢：每秒只读 2.3 帧（Mac 约 7.8），识别一帧 360 毫秒（Mac 约 83），"
        "动作和牌容易漏读",
        "轮到他 30 次，2 次窗口没给建议（街道对不上 2）",
        "他的手牌只读出 50%（三星 64%，线 58%）",
        "20 手里 7 手在模拟牌桌上按 AA 规则重放不下去（加注没读到金额 7）",
        # 3 skipped-seat hands of 20 is the Mac's rate; 2 board cards is not
        "读错：公共牌读成两样 2、一手被拆成两手 2",
        "打到翻后的 5 手里，每一步都有建议的只有 0 手",
        "18/20 手没从牌桌读出级别（盲注）",
        "能用来统计对手的只有 9/20 手（Mac 录像约 85%）：有人的动作漏读了",
        "卡顿超过 2 秒 1 次",
        "录像丢了 5% 的帧",
        "录像每小时 26000 MB（编码 avc1），上传会很慢"]


def test_times_are_shown_in_los_angeles():
    assert review.when("2026-10-15T10:20:47+0800") == "10/14 晚上 7:20（洛杉矶）"
    assert review.when("2026-10-15T09:05:00-0700") == "10/15 上午 9:05（洛杉矶）"
    assert review.when(None) is None and review.when("yesterday") is None


def test_population_leaves_every_testers_own_seat_out(tmp_path, monkeypatch, capsys):
    state = tmp_path / "state"
    state.mkdir()
    review.write_lines(state / "base.jsonl", [{"log": "mac-1", "hand_id": "h1"}])
    (state / review.BASE).write_text(json.dumps(
        {"hands": "base.jsonl", "hero_logs": ["mac-1"], "minutes": {"mac-1": 30}}),
        encoding="utf-8")
    review.write_lines(state / review.REVIEWED, [
        {"log": "du-a", "minutes": 18.2}, {"log": "du-b", "minutes": None}])
    review.write_lines(state / review.HANDS, [
        {"log": "du-a", "hand_id": "h2"}, {"log": "du-gone", "hand_id": "h3"}])
    seen = {}

    def build(hands, hero_logs, minutes):
        seen.update(hands=[hand["hand_id"] for hand in hands], hero=hero_logs,
                    minutes=minutes)
        return {"hands_counted": 2, "video_minutes": 48.2, "groups": {},
                "sources": [{"log": "mac-1", "counted": 1},
                            {"log": "du-a", "counted": 1}]}

    monkeypatch.setattr(review.pop, "build", build)
    monkeypatch.setattr(review.pop, "phh_reference", lambda report: {})
    out = tmp_path / "stats.json"
    review.population(review.argparse.Namespace(state=state, out=out))
    assert seen["hands"] == ["h1", "h2"]
    assert seen["hero"] == {"mac-1", "du-a", "du-b"}
    assert seen["minutes"] == {"mac-1": 30, "du-a": 18.2}
    assert json.loads(out.read_text(encoding="utf-8"))["hands_counted"] == 2
    assert "共 2 手能用（0.8 小时录像），其中同事录像 1 手" in capsys.readouterr().out
