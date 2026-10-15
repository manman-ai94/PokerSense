import json

import pytest

from tools import flywheel_gates as gates


def _hand(hand_id, *advice, start=10.0):
    return {"hand_id": hand_id, "start_pts": start, "video_seconds": start,
            "decisions": [{"street": "flop", "kind": "rule", "advice": [a] if a else [],
                           "you_did": "call"} for a in advice]}


def _report(advised, fully, stalls, hands):
    return {"summary": {"advised": advised, "stalls_over_2s": stalls,
                        "fully_advised": {"hands": len(hands), "advised": fully}},
            "hands": hands}


def test_replay_passes_when_nothing_gets_worse_and_lists_changed_advice():
    base = _report(10, 4, 1, [_hand("a", "call", "fold"), _hand("b", "check")])
    head = _report(11, 4, 0, [_hand("a", "call", "raise"), _hand("b", "check")])
    verdict = gates.replay_verdict(base, head)
    assert verdict["passed"]
    assert verdict["hands"] == 2
    [change] = verdict["changed_decisions"]
    assert (change["hand_id"], change["decision"]) == ("a", 1)
    assert (change["before"], change["after"]) == ("fold", "raise")


@pytest.mark.parametrize("head, reason", [
    (_report(9, 4, 1, []), "有建议的决策从 10 变成 9"),
    (_report(10, 3, 1, []), "每一步都有建议的手从 4 变成 3"),
    (_report(10, 4, 2, []), "卡顿超过 2 秒从 1 变成 2"),
])
def test_replay_fails_on_fewer_advised_or_more_stalls(head, reason):
    verdict = gates.replay_verdict(_report(10, 4, 1, []), head)
    assert not verdict["passed"]
    assert verdict["reasons"] == [reason]


def test_decision_changes_skip_hands_that_do_not_line_up():
    base = {"hands": [_hand("a", "call", start=1.0)]}
    head = {"hands": [_hand("a", "fold", start=2.0)]}
    assert gates.decision_changes(base, head) == []
    [change] = gates.decision_changes(base, {"hands": [_hand("a", None, start=1.0)]})
    assert change["after"] is None


def test_paired_difference_over_common_deals():
    base = {"per_deal": [[1, {"x": 0.0}], [2, {"x": 0.1}], [3, {"x": -0.1}],
                         [9, {"x": 5}]]}
    head = {"per_deal": [[1, {"y": 0.1}], [2, {"y": 0.2}], [3, {"y": 0.0}]]}
    result = gates.paired(base, head, "x", "y")
    assert result["deals"] == 3
    assert result["difference_bb100"] == 10.0
    assert result["ci95"] == [10.0, 10.0]
    assert (result["base_bb100"], result["head_bb100"]) == (0.0, 10.0)
    with pytest.raises(ValueError):
        gates.paired(base, {"per_deal": [[1, {"y": 0}]]}, "x", "y")


def test_sim_fails_only_when_the_whole_interval_is_below_zero():
    runs = [{"pool": "aa", "seed": 1, "difference_bb100": -3, "ci95": [-8, 2]},
            {"pool": "noisy", "seed": 2, "difference_bb100": -6, "ci95": [-9, -1]}]
    verdict = gates.sim_verdict(runs)
    assert not verdict["passed"]
    assert verdict["reasons"] == ["noisy 第 2 批牌：差 -6（区间 -9 到 -1）"]
    assert gates.sim_verdict(runs[:1])["passed"]


def test_default_tests_follow_the_changed_files():
    changed = ["src/poker_engine/desktop/aa_session.py",
               "tests/desktop/test_aa_session.py", "tests/test_code_version.py",
               "tools/flywheel_gates.py", "docs/WORKLOG.md"]
    assert gates.default_tests(changed) == [
        "tests/desktop", "tests/test_code_version.py",
        "tests/tools/test_flywheel_gates.py"]


def test_default_tests_look_in_the_checkout_given(tmp_path):
    (tmp_path / "tests" / "desktop").mkdir(parents=True)
    changed = ["ui/aa-live/signal_view.js", "tests/ui/test_signal_view.js",
               "src/poker_engine/desktop/aa_reader.py", "tests/tools/test_gone.py",
               "src/poker_engine/solver/texassolver.py"]
    # The page's JavaScript tests run from tests/desktop; a test file the
    # checkout no longer has and a package without tests are left out.
    assert gates.default_tests(changed, root=tmp_path) == ["tests/desktop"]


def test_lines_say_each_gate_in_plain_words():
    result = {"base": "a" * 40, "head": "b" * 40, "head_dirty": True, "gates": {
        "replay": None,
        "sim": gates.sim_verdict([{"pool": "aa", "seed": 1, "difference_bb100": 1.5,
                                   "ci95": [-2, 5], "deals": 600, "base_bb100": 3,
                                   "head_bb100": 4.5}]),
        "tests": {"passed": False, "reasons": ["测试没全过（见 pytest.log）"]}}}
    text = gates.lines(result)
    assert text[0] == "和 aaaaaaa 比（现在的代码 bbbbbbb，含未提交的改动）"
    assert "录像重放：没跑" in text
    assert "模拟：过" in text
    assert any("模拟牌桌的积分" in line for line in text)
    assert "测试：不过：测试没全过（见 pytest.log）" in text
    assert text[-1] == "三道关：没过"


def test_main_checks_out_the_base_and_cleans_it_up(tmp_path, capsys, monkeypatch):
    # Only this run's worktree: tests in other workers add their own meanwhile.
    made = []
    real = gates.base_tree
    monkeypatch.setattr(gates, "base_tree",
                        lambda ref, folder: made.append(folder) or real(ref, folder))
    status = gates.main(["--base", "HEAD", "--no-tests", "--out", str(tmp_path)])
    assert status == 1  # nothing ran, so nothing passed
    result = json.loads((tmp_path / "gates.json").read_text(encoding="utf-8"))
    assert result["base"] == gates.git("rev-parse", "HEAD")
    assert result["gates"] == {"replay": None, "sim": None, "tests": None}
    assert "三道关：一道都没跑" in capsys.readouterr().out
    listed = gates.git("worktree", "list", "--porcelain")
    assert len(made) == 1 and not made[0].exists()
    assert str(made[0]) not in listed and str(made[0].resolve()) not in listed
