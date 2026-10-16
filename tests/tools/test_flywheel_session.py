import json

import pytest

from tools import flywheel_session as fly


def row(frame, *, hand="hand_0", turn=False, cards=("As", "Kd"), advice=None,
        stack="100", pot=10, street="preflop", actions=(), code=None):
    item = {"processed": frame, "pts_seconds": frame * 0.1,
            "timing": {"published_at": frame * 0.1},
            "fields": {"scene_supported": True, "hero": list(cards),
                       "participants": {"4": "active", "5": "active", "6": "active"},
                       "hero_controls": {"visible": turn, "button": "call"},
                       "street": street, "stacks": {"4": stack}, "pot": pot,
                       "actions_v1": {"hand_id": hand, "complete": False,
                                      "start": "boundary", "dealer": 5,
                                      "actions": [list(a) for a in actions]},
                       "solver_advice": advice or {"status": "idle",
                                                   "reason": "not_your_turn"}}}
    if code is not None:
        item["code"] = code
    return item


CALL = {"status": "ready", "kind": "preflop", "advice": [{"action": "call"}]}
CODE = {"version": "0.1.0", "commit": "abcdef1234", "dirty": False}


def session(tmp_path, name="20261013-200000-live"):
    """Two hands: you call a raise and a re-raise all in and lose 40 chips
    (20 big blinds at 1/2/4), then lose 4 more in the second."""
    raised = [(3, "preflop", 5, "raise", "8", "bet"),
              (4, "preflop", 6, "all_in", "40", "pot_rise")]
    called = raised + [(6, "preflop", 4, "call", "40", "bet")]
    rows = ([row(0, code=CODE)] + [row(f) for f in range(1, 5)]
            + [row(5, turn=True, advice=CALL, actions=raised),
               row(6, actions=called, stack="60", pot=90)]
            + [row(f, hand="hand_7", cards=("7c", "2d"), stack="60")
               for f in range(7, 12)]
            + [row(f, hand="hand_12", cards=("9c", "9d"), stack="56")
               for f in range(12, 15)])
    folder = tmp_path / name
    folder.mkdir()
    lines = [json.dumps(item) for item in rows]
    (folder / "frames.jsonl").write_text("\n".join(lines) + '\n{"cut sh',
                                         encoding="utf-8")
    return folder


def test_report_writes_the_sheet_and_the_ledger(tmp_path):
    folder = session(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    text = fly.report(folder, ledger)
    hands = json.loads((folder / "flywheel" / "hands.json").read_text(encoding="utf-8"))
    first, second = hands
    assert (first["chips"], first["bb"], first["stakes"]) == (-40, -20.0, "1/2/4(2)")
    assert first["stakes_sure"] is False
    assert first["spot"]["facing"] == "面对再加注（有人全下）"
    assert (first["spot"]["table"], first["spot"]["you_did"]) == ("多人", "call")
    assert first["spot"]["followed"] is True
    assert second["bb"] == -2.0 and second["spot"] is None
    summary = json.loads((folder / "flywheel" / "summary.json").read_text(
        encoding="utf-8"))
    assert summary["code"] == CODE
    assert summary["all"]["bb"] == -22.0 and summary["all"]["hands"] == 2
    assert summary["lost_most"][0]["spot"] == "翻前 · 多人 · 面对再加注（有人全下） · 你跟注"
    assert text[0] == "20261013-200000-live 体检单（代码 0.1.0 · abcdef1）"
    assert "（其中 2 手没读到级别）" in text[1]
    assert any("-22.0 个大盲的积分" in line for line in text)
    assert (folder / "flywheel" / "体检单.txt").read_text(encoding="utf-8") == (
        "\n".join(text) + "\n")
    [line] = fly.read_ledger(ledger)
    assert line["normal"] == {"hands": 2, "bb": -22.0, "bb_squared": 404.0}
    fly.report(folder, ledger)                    # reported again: replaced
    assert len(fly.read_ledger(ledger)) == 1


def test_the_sheet_counts_the_rules_of_the_one_page_advice(tmp_path):
    # The same session, advised by 《一页纸打法》: the call was table 2's row,
    # and the second hand's turn was a blind the page says nothing about.
    plain = {"status": "ready", "kind": "plain", "advice": [{"action": "call"}],
             "plain": {"rule": "T2.call", "hits": ["T2.call"],
                       "rule_key": "T2.call#0123456789abcdef"}}
    folder = session(tmp_path)
    rows = [json.loads(line) for line in (folder / "frames.jsonl").read_text(
        encoding="utf-8").splitlines()[:-1]]
    for item in rows:
        if item["fields"]["solver_advice"].get("kind") == "preflop":
            item["fields"]["solver_advice"] = plain
        if item["processed"] == 9:
            item["fields"]["hero_controls"]["visible"] = True
            item["fields"]["solver_advice"] = {
                "status": "ready", "kind": "plain", "advice": [{"action": "fold"}],
                "plain": {"rule": "I5", "unspecified": "blind_unopened"}}
    (folder / "frames.jsonl").write_text("\n".join(json.dumps(item) for item in rows)
                                         + "\n", encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    text = fly.report(folder, ledger)
    summary = json.loads((folder / "flywheel" / "summary.json").read_text(
        encoding="utf-8"))
    assert summary["rules"]["T2.call"] == {"hits": 1, "followed": 1, "followed_of": 1,
                                           "hands": 1, "bb": -20.0}
    assert summary["rules"]["I5"]["hits"] == 1
    assert summary["unspecified"] == {"blind_unopened": 1}
    at = text.index("规则命中统计（一页纸打法）：")
    assert ("  T2.call 表 2·跟注（不限筹码）：命中 1 次，照做 1/1，"
            "这些手 1 手共 -20.0 个大盲") in text[at + 1:at + 3]
    assert any(line.startswith("本页没写的情形（按铁律 5）：盲位前面全弃")
               for line in text)
    # The ledger keeps the hits by rule key (编号#条文哈希); I5 was logged
    # without one (older code), so it is left out rather than added up.
    [line] = fly.read_ledger(ledger)
    assert line["rules"] == {"T2.call#0123456789abcdef":
                             {"hits": 1, "hands": 1, "bb": -20.0}}
    assert "规则命中统计（一页纸打法）：" not in fly.sheet(
        {**summary, "rules": {}, "unspecified": {}})


def test_levels_follow_the_table_hand_by_hand(monkeypatch):
    seen = iter([{"big_blind": "4", "source": "table"},
                 {"big_blind": "4", "source": "carried"},
                 {"big_blind": "2", "source": "unsure"}])
    calls = []

    def facts(rows, earlier):
        calls.append(earlier)
        return {"stakes": next(seen)}

    monkeypatch.setattr(fly, "hand_facts", facts)
    found = fly.hand_stakes({"a": [], "b": [], "c": []})
    assert [found[key]["big_blind"] for key in "abc"] == ["4", "4", "2"]
    table = {"big_blind": "4", "source": "table"}
    assert calls[0] is None and calls[1] == calls[2] == table


def hand(spot, bb, *, followed=True, kind="multiway", log="s1"):
    return {"log": log, "hand_id": f"h{bb}", "video_seconds": 10.0,
            "your_cards": "As Kd", "stakes": "2/4/8(4)", "bb": bb, "bomb_pot": False,
            "spot": None if spot is None else {
                "street": spot[0], "table": "多人", "facing": spot[1],
                "you_did": spot[2], "advice": spot[2], "kind": kind,
                "followed": followed, "flags": []}}


def test_ranking_puts_the_spot_that_lost_most_first():
    hands = [hand(("river", "面对下注", "call"), -30),
             hand(("river", "面对下注", "call"), 12),
             hand(("flop", "没人下注", "bet"), -10),
             hand(("flop", "没人下注", "bet"), -8, followed=False),
             hand(None, -1)]
    first, second, third = fly.ranking(hands)
    assert (first["spot"], first["lost_bb"], first["net_bb"]) == (
        "河牌 · 多人 · 面对下注 · 你跟注", -30, -18)
    assert [h["bb"] for h in first["worst"]] == [-30]
    assert (second["spot"], second["losing_hands"]) == ("翻牌 · 多人 · 没人下注 · 你下注", 2)
    assert (second["followed"], second["followed_of"]) == (1, 2)
    assert third["spot"] == "没轮到你"
    assert len(fly.ranking(hands, 1)) == 1


def test_ledger_totals_match_the_hands_and_split_by_code(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    values = {"one": [-3.0, 1.0, 5.0], "two": [2.0, -4.0]}
    for label, bbs in values.items():
        item = {"label": label, "code": {"commit": label * 3}, "stakes": {},
                "decisions": 0, "advised": 0, "fully_advised": [0, 0],
                "followed": [0, 0], "stalls_over_2s": 0}
        fly.add_to_ledger(ledger, item, [{"bb": v, "bomb_pot": False} for v in bbs])
    found = fly.totals(fly.read_ledger(ledger))
    every = values["one"] + values["two"]
    assert found["all"]["all"] == fly.result(every)
    assert found["all"]["sessions"] == 2
    assert found["by_code"]["oneoneo"]["normal"] == fly.result(values["one"])
    assert found["all"]["bomb_pot"]["hands"] == 0


def test_result_interval():
    assert fly.result([]) == {"hands": 0, "bb": 0, "bb_per_100": None, "ci95": None}
    assert fly.result([1.0])["ci95"] is None
    found = fly.result([1.0, -1.0, 1.0, -1.0])
    assert found["bb_per_100"] == 0.0
    assert found["ci95"] == pytest.approx([-113.2, 113.2], abs=0.1)


def test_rank_reads_the_sessions_under_the_root(tmp_path, capsys):
    for name, commit, bb in (("20261012-1-live", "aaa", -5),
                             ("20261013-1-live", "bbb", -7)):
        out = tmp_path / name / "flywheel"
        out.mkdir(parents=True)
        (out / "hands.json").write_text(json.dumps(
            [hand(("turn", "面对下注", "call"), bb, log=name)]), encoding="utf-8")
        (out / "summary.json").write_text(json.dumps({"code": {"commit": commit}}),
                                          encoding="utf-8")
    assert fly.collect(tmp_path)[0] == ["20261012-1-live", "20261013-1-live"]
    assert fly.collect(tmp_path, since="20261013")[0] == ["20261013-1-live"]
    assert fly.collect(tmp_path, commit="aa")[0] == ["20261012-1-live"]
    assert fly.main(["rank", "--root", str(tmp_path), "--out",
                     str(tmp_path / "rank.json")]) == 0
    assert "1. 转牌 · 多人 · 面对下注 · 你跟注：输的 2 手共 -12" in capsys.readouterr().out


class FakeVideo:
    """Stands in for cv2.VideoCapture: the frame's colour is the second asked."""

    opened = []

    def __init__(self, path):
        self.path, self.ms = path, 0
        FakeVideo.opened.append(path)

    def set(self, prop, value):
        self.ms = value

    def read(self):
        import numpy as np
        return True, np.full((1080, 1920, 3), int(self.ms / 1000) % 255, np.uint8)

    def release(self):
        pass


def test_the_hands_to_look_at_get_pictures_cut_from_the_recording(tmp_path):
    pytest.importorskip("cv2")
    folder = session(tmp_path)
    (folder / "segment_0000.mp4").write_bytes(b"")
    (folder / "segments.csv").write_text("segment_0000.mp4,0.000000,600.000000\n")
    (folder / "recording.json").write_text(json.dumps(
        {"strip": [711, 0, 1209, 1080]}))
    lines = (folder / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.startswith("{\"processed")]
    for item in rows:
        item["video_seconds"] = round(100 + item["pts_seconds"], 2)
    (folder / "frames.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8")
    FakeVideo.opened = []
    text = fly.report(folder, None, opener=FakeVideo)
    hands = json.loads((folder / "flywheel" / "hands.json").read_text(encoding="utf-8"))
    first, second = hands
    # Lost 20 big blinds: your turn and the hand's end; the small loss: none.
    assert first["pictures"] == ["frames/hand_0-turn-100.5s.jpg",
                                 "frames/hand_0-end-100.6s.jpg"]
    assert "pictures" not in second
    for name in first["pictures"]:
        assert (folder / "flywheel" / name).stat().st_size > 0
    assert FakeVideo.opened == [str(folder / "segment_0000.mp4")]
    summary = json.loads((folder / "flywheel" / "summary.json").read_text(
        encoding="utf-8"))
    look = summary["to_look_at"]
    assert (look["hands"], look["pictures"]) == (1, 2)
    assert any(line.startswith("要看的手 1 手") for line in text)


def test_no_video_no_pictures(tmp_path):
    hands = [{"hand_id": "h", "bb": -30, "misreads": [], "turn_seconds": [1.0],
              "end_seconds": 2.0}]
    assert fly.pictures(tmp_path, hands, tmp_path / "frames") == 0
    assert fly.to_look_at(hands + [{"bb": -1, "misreads": ["你的牌认成两种"]},
                                   {"bb": -5, "misreads": []}])[1]["bb"] == -1


def _turn(street, button, to_call, frame=5):
    return {"pts": round(frame * 0.1, 1), "street": street, "button": button,
            "to_call": to_call}


@pytest.mark.parametrize("street, actions, button, to_call, big_blind, expected", [
    # The bet is logged in the very frame your turn shows up.
    ("flop", [(5, "flop", 6, "all_in", "250", "bet")], "call", "250", 8,
     "面对下注（有人全下）"),
    ("turn", [(5, "turn", 6, "bet", "40", "bet")], "call", "40", 8, "面对下注"),
    ("preflop", [(5, "preflop", 6, "raise", "80", "bet")], "call", "80", 8, "面对加注"),
    # The bet was not read at all: the price on the button tells.
    ("preflop", [], "call", "80", 8, "面对加注"),
    ("river", [], "call", "40", 8, "面对下注"),
    ("preflop", [], "call", "4", 8, "没人加注"),
    # 让牌 on the button: nothing faced, whatever the log says.
    ("flop", [(5, "flop", 6, "bet", "40", "bet")], "check", "0", 8, "没人下注"),
    # You bet, were raised, and answer again: a raise; actions after you don't count.
    ("flop", [(2, "flop", 4, "bet", "20", "bet"),
              (5, "flop", 6, "raise", "80", "bet"),
              (7, "flop", 4, "call", "60", "bet"),
              (8, "flop", 5, "raise", "300", "bet")],
     "call", "60", 8, "面对加注"),
])
def test_facing_reads_the_button_and_the_price(street, actions, button, to_call,
                                               big_blind, expected):
    rows = [row(f, street=street, actions=actions) for f in range(9)]
    assert fly.facing(rows, _turn(street, button, to_call), big_blind) == expected
