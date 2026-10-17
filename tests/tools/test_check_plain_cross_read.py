"""``tools/check_plain_cross_read.py``：两处读数对上的读法在日志上和真读到的比。"""

from copy import deepcopy
import json

from tests.desktop.test_aa_plain_cross_read import HERO, first_hand, next_hand
from tools import check_plain_cross_read as check


class _Log:
    """Stands in for the window: keeps every frame's fields as a log row."""

    def __init__(self):
        self.rows = []

    def observe_fields(self, fields, frame):
        at = len(self.rows)
        self.rows.append({"processed": at, "pts_seconds": at / 10,
                          "fields": deepcopy(fields)})
        return {}


def write(tmp_path, rows):
    path = tmp_path / "rec" / "frames.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_carried_stacks_that_match_later_reads_pass_the_gate(tmp_path):
    log = _Log()
    first = first_hand(log)
    second = next_hand(log, first, dealer=1)
    second.put(5, 12)
    second.turn(call=8, frames=30)                  # 你的筹码一直没读到：往前带的救下
    second.hidden.discard(HERO)
    second.turn(call=8, frames=5)                   # 后来读到了：和往前带的一样
    out = tmp_path / "out.json"
    path = write(tmp_path, log.rows)
    assert check.main(["--frames", str(path), "--out", str(out), "--tails", "0,3"]) == 0
    total = json.loads(out.read_text(encoding="utf-8"))["total"]
    assert total["gate"]["pass"] and total["counts"]["stack_check_frames"] > 0
    assert total["counts"]["stack_carried_hands"] == 1
    assert total["iron5_off"] == {"stack": 1} and not total["iron5_on"]
    assert total["iron5_detail_off"] == {"preflop/stack": 1}
    assert "rec" in json.loads(out.read_text(encoding="utf-8"))["logs"]
    assert total["tails"]["0"]["stack_carried_hands"] == 1
    assert total["tails"]["3"]["stack_disagree_frames"] == 0


def test_a_carried_stack_that_disagrees_with_a_read_fails_the_gate(tmp_path):
    log = _Log()
    first = first_hand(log)
    second = next_hand(log, first, dealer=1)
    second.stacks[HERO] += 50                       # 两手之间多了 50（往前带的会错）
    second.hidden.discard(HERO)
    second.put(5, 12)
    second.turn(call=8, frames=5)
    assert check.main(["--frames", str(write(tmp_path, log.rows))]) == 1
