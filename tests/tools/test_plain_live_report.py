"""一页纸打法在实录上重放的统计（``tools/plain_live_report.py``），用合成的画面：
你的轮次怎么切、你做了什么、覆盖和改口、规则命中、遵从率怎么算。"""

import gzip
import itertools
import json
from types import SimpleNamespace

from poker_engine.desktop import aa_plain_advice
from tests.desktop.test_aa_plain_live import Clock, Screen
from tools import plain_live_report as report


class Recorder:
    """站在建议的位置上，把每一帧的画面字段记成日志的一行。"""

    def __init__(self, clock):
        self.clock, self.rows = clock, []

    def observe_fields(self, fields, frame):
        self.rows.append({"processed": frame, "pts_seconds": round(self.clock(), 3),
                          "fields": fields})
        return {}


def screen():
    clock = Clock()
    recorder = Recorder(clock)
    return Screen(recorder, clock=clock, hero=("Qs", "Qh")), recorder


def facing_an_open(you="raise", to=36):
    """你拿 QQ 面对 3 号位开到 12：一页纸说再加注到 36（表 2）。"""
    table, recorder = screen()
    table.deal()
    table.put(3, 12, badge="raise")
    table.turn(call=12, frames=8)
    table.acted()
    if you == "fold":
        table.fold(4)
    else:
        table.put(4, to if you == "raise" else 12, badge=you)
    return table, recorder


def test_a_turn_is_counted_once_with_what_you_did_and_the_page(monkeypatch):
    # How long the page takes is its own wall clock (perf_counter), which a
    # busy runner stretches; here each reading moves 0.05 s, the same anywhere.
    ticks = itertools.count()
    monkeypatch.setattr(aa_plain_advice, "time", SimpleNamespace(
        perf_counter=lambda: next(ticks) * 0.05))
    _, recorder = facing_an_open()
    found = report.log_report("synthetic", recorder.rows, luck=False)
    (turn,) = found["turns"]
    assert turn["real"] and turn["street"] == "preflop"
    assert (turn["you"], turn["you_read"]) == ("raise", "history")
    assert turn["plain"]["advice"] == "raise" and turn["plain"]["rule"] == "T2.3bet"
    summary = report.summarize([found])
    plain = summary["coverage"]["plain"]
    assert summary["coverage"]["turns"] == 1 and plain["with_advice"] == 1
    assert plain["changed_within_decision"] == 0 and plain["rough"] == 0
    assert plain["iron5_unread"] == 0 and plain["ready_to_advice_median"] == 0.05
    assert summary["rules"]["hits"]["T2.3bet"] == {"hits": 1, "you_did_it": 1}
    assert summary["abilities"]["compliance"]["rate"] == 1.0
    assert summary["abilities"]["compliance"]["sample"] == "不够"
    assert summary["preflop"]["plain"]["raises_by_cards"] == {"前 5%": 1}


def test_a_raise_far_from_the_page_size_is_not_following_it():
    _, recorder = facing_an_open(to=60)
    summary = report.summarize([report.log_report("x", recorder.rows, luck=False)])
    compliance = summary["abilities"]["compliance"]
    assert (compliance["rate"], compliance["looser"]) == (0.0, 1)


def test_compliance_sides_and_sizes():
    item = {"advice": "raise", "to": "36"}
    assert report.compliance("raise", "40", item) == (True, None)
    assert report.compliance("raise", "50", item) == (False, "looser")
    assert report.compliance("raise", "20", item) == (False, "tighter")
    assert report.compliance("call", None, item) == (False, "tighter")
    assert report.compliance("fold", None, {"advice": "check"}) == (True, None)
    assert report.compliance("call", None, {"advice": "fold"}) == (False, "looser")
    assert report.compliance(None, None, item) == (None, None)


def test_buttons_left_on_while_the_flop_comes_are_not_a_turn():
    table, recorder = facing_an_open(you="call")
    for seat in (5, 6, 7, 0, 1, 2):
        table.fold(seat, frames=1)
    table.turn(call=None, frames=2)                 # 按钮还在，翻牌已经发下来
    table.show(2, board=["2c", "7d", "9h", None, None])
    table.acted()
    table.street("flop")
    found = report.log_report("x", recorder.rows, luck=False)
    summary = report.summarize([found])
    assert summary["coverage"]["turns"] == 1
    assert summary["coverage"]["buttons_after_you_acted"] == 1


def test_a_check_without_a_badge_is_read_from_the_next_street():
    table, recorder = screen()
    table.badges = False
    table.deal()
    for seat in (3, 5, 6, 7, 0, 1):
        table.fold(seat, frames=1)
    table.put(2, 4, frames=1)
    table.put(4, 4, frames=3)
    table.street("flop", "2c", "7d", "9h")
    table.turn(call=None, frames=8)
    table.acted()
    table.street("turn", "Kc")
    found = report.log_report("x", recorder.rows, luck=False)
    flop = [turn for turn in found["turns"] if turn["street"] == "flop"]
    assert [(turn["you"], turn["you_read"]) for turn in flop] == [("check", "screen")]


def test_logs_load_plain_or_gzipped(tmp_path):
    _, recorder = facing_an_open()
    lines = "".join(json.dumps(row) + "\n" for row in recorder.rows)
    (tmp_path / "rec").mkdir()
    (tmp_path / "rec" / "frames.jsonl").write_text(lines, encoding="utf-8")
    with gzip.open(tmp_path / "du-1.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.write(lines)
    assert report.load(tmp_path / "rec" / "frames.jsonl") == recorder.rows
    assert report.load(tmp_path / "du-1.jsonl.gz") == recorder.rows
    assert report.log_name(tmp_path / "rec" / "frames.jsonl") == "rec"
    assert report.log_name(tmp_path / "du-1.jsonl.gz") == "du-1"


def test_the_summary_holds_totals_only(tmp_path, capsys):
    _, recorder = facing_an_open()
    path = tmp_path / "du-2.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in recorder.rows),
                    encoding="utf-8")
    out = tmp_path / "summary.json"
    report.main(["--frames", str(path), "--no-luck", "--out", str(out)])
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert set(summary["by_who"]) == {"杜"}
    text = out.read_text(encoding="utf-8")
    assert "hand_1" not in text and "Qs" not in text
    assert summary["all"]["results"] == {"hands": 0}


def test_shown_card_difference_is_split_by_page_rule():
    priced = [{"plain": {"rule": "N.C"}, "chips": [0.0, 12.5]},
              {"plain": {"rule": "N.C"}, "chips": [3.0, 1.0]},
              {"plain": {"rule": "T1.out"}, "chips": [0.0, -2.0]}]
    assert report._by_rule(priced) == {
        "N.C": {"decisions": 2, "plain_worse": 1, "difference_bb": -10.5},
        "T1.out": {"decisions": 1, "plain_worse": 0, "difference_bb": 2.0}}


def test_the_board_counts_only_after_the_flop():
    table, recorder = screen()
    table.badges = False
    table.deal()
    for seat in (3, 5, 6, 7, 0, 1):
        table.fold(seat, frames=1)
    table.put(2, 4, frames=1)
    table.put(4, 4, frames=3)
    table.street("flop", "2c", "7d", "9h")
    table.turn(call=None, frames=8)
    table.acted()
    table.street("turn", "Kc")
    summary = report.summarize([report.log_report("x", recorder.rows, luck=False)])
    board = summary["reading"]["board"]
    assert (board["turns"], board["within_2s"]) == (1, 1.0)
    assert summary["reading"]["hero_cards"]["turns"] == summary["reading"]["turns"]
