"""证据单: session packages read back as one page (made-up packages only)."""

import json

from poker_engine.scoreboard import plain_policy
from tools import session_evidence as evidence
from tools import session_package as package

from tests.tools.test_session_package import PAGE, rows


def decision(hand, rule, *, followed=True, bb=-10.0, adjusted=-4.0, iron5=False,
             missing=None, seconds=0.5, reason=None):
    return {"log": "s", "hand_id": hand, "street": "flop", "position": "late",
            "advice": {"kind": "plain", "action": "call", "rule": rule,
                       "rule_label": rule},
            "followed": followed, "you_did": "call" if followed else "fold",
            "hand_bb": bb, "hand_bb_luck_adjusted": adjusted, "iron5": iron5,
            "missing": missing, "unspecified": None, "seconds_to_advice": seconds,
            "advice_before_action": True, "deviation_reason": reason}


def shown(hand, cls, *, how="showdown", inside=True, corrected=False):
    calibrates = how in ("showdown", "allin_showdown") and not corrected
    return {"log": "s", "hand_id": hand, "seat": 3, "preflop_class": cls,
            "how": how, "corrected": corrected, "calibrates": calibrates,
            "range": {"class": cls, "preflop_in": True, "in": inside,
                      "percentile": 0.3}}


def made(root, machine, label, *, hands=10, misread_hands=0, decisions=(),
         shows=(), rule_hash="aaaa", version="v3.1"):
    """A package as session_package writes it, with only what the page reads."""
    folder = root / machine / label / "flywheel"
    folder.mkdir(parents=True)
    items = [{"type": "skipped_seats", "log": "s", "hand_id": f"h{index}"}
             for index in range(misread_hands)]
    data = {
        "schema": "pokersense.session_package", "format": 1,
        "session": {"label": label, "machine": machine, "hands": hands,
                    "decisions": len(decisions), "fully_advised": [hands, hands],
                    "results": {"all": {"hands": hands, "bb": -10.0}},
                    "luck_adjusted": {"hands": hands, "adjusted_bb_per_100": 5.0}},
        "identity": {"player": machine},
        "decisions": list(decisions), "shown": list(shows),
        "shown_denominators": {"raise": {"seats": 4, "showdown": len(shows),
                                         "folded": 4 - len(shows)}},
        "misreads": {"counts": {"hands": hands, "decisions": len(decisions),
                                "actions": 50, "skipped_seats": misread_hands,
                                "actions_inferred_from_chips": 2,
                                "actions_filled_in_by_replay": 0},
                     "items": items},
        "timing": {"changes_of_mind": 0, "decisions_changed": 0},
        "versions": {"page": {"version": version, "rules": {
            "F.C": {"text": "面对下注·C 档", "sha256": rule_hash}}}},
        "nulls": {}}
    (folder / "package.json").write_text(json.dumps(data, ensure_ascii=False),
                                         encoding="utf-8")
    return folder / "package.json"


def test_one_package_reads_as_one_page(tmp_path, capsys):
    folder = tmp_path / "20261016-200000-live"
    folder.mkdir()
    (folder / "frames.jsonl").write_text(
        "\n".join(json.dumps(item) for item in rows()) + "\n", encoding="utf-8")
    path = package.make(folder, settings={"machine": "peng", "player": "peng"})
    assert evidence.main(["--package", str(path)]) == 0
    page = capsys.readouterr().out.splitlines()
    assert page[0].startswith("证据单 20261016-200000-live · 机器 peng · 打牌人 peng")
    assert f"一页纸 {PAGE}" in page[0] and "1/2/4(2) 1 手" in page[0]
    text = "\n".join(page)
    assert "铁律 5：1/4（25%）" in text and "缺 pot 1" in text
    assert f"  T2.call 表 2·跟注（不限筹码） [{PAGE} " in text
    assert "加注：校准用 1 个，翻前范围里 1/1（100%），缩窄后范围里 1/1（100%）" in text
    assert "落在翻前范围外 0/1（0%），真牌位置均值" in text and "100 个才稳：不够" in text
    assert "分母 1 个座位（普通摊牌 1）" in text
    assert "改口 0 次" in text and "动作靠筹码推断：1/12" in text
    assert "遵从率（动作和建议一样、加注尺寸 ±25%，除以不是 UNKNOWN 的建议）：全部 3/3（100%）" in text
    assert "identity.opponents" in text


def test_rules_are_ranked_and_each_wording_kept_apart(tmp_path):
    first = made(tmp_path, "peng", "20261016-200000-live", decisions=[
        decision("h1", "F.C"), decision("h2", "F.C", followed=False, bb=20.0,
                                        adjusted=8.0, reason="读到他偷鸡")])
    second = made(tmp_path, "peng", "20261017-200000-live", rule_hash="bbbb",
                  decisions=[decision("h1", "F.C")])
    page = evidence.one(evidence.load(first))
    line = next(line for line in page if line.startswith("  F.C"))
    assert "命中 2，照做 1/2，这些手 2 手 实际 +10.0 大盲，扣运气 +4.0" in line
    assert any("理由：读到他偷鸡" in line for line in page)
    lines = evidence.rule_lines([evidence.load(first), evidence.load(second)])
    assert len(lines) == 2                     # same number, another wording
    assert "[v3.1 aaaa]" in lines[0] and "[v3.1 bbbb]" in lines[1]


def test_iron_rule_5_counts_its_causes():
    decisions = [decision("h1", "I5", iron5=True, missing=["pot"]),
                 decision("h2", "I5", iron5=True, missing=["pot"]),
                 decision("h3", "F.C"), {"iron5": None}]
    assert evidence.iron5_lines(decisions) == ["铁律 5：2/3（67%） 个一页纸决策",
                                               "  主因：缺 pot 2"]


def test_only_whole_showdowns_calibrate_the_ranges(tmp_path):
    path = made(tmp_path, "du", "20261016-100000-live", shows=[
        shown("h1", "raise"), shown("h2", "raise", inside=False),
        shown("h3", "raise", corrected=True), shown("h4", "raise", how="voluntary")])
    page = evidence.range_lines([evidence.load(path)])
    line = next(line for line in page if line.startswith("  加注"))
    assert "校准用 2 个，翻前范围里 2/2（100%），缩窄后范围里 1/2（50%）" in line
    assert "落在翻前范围外 0/2（0%），真牌位置均值 30%（中位数 30%）" in line
    assert "分母 4 个座位（普通摊牌 4）" in line


def test_all_takes_each_machine_then_only_the_ones_that_read_alike(tmp_path, capsys):
    made(tmp_path, "peng", "20261016-200000-live", misread_hands=1,
         decisions=[decision("h1", "F.C")])
    made(tmp_path, "du", "20261016-100000-live", misread_hands=1,
         decisions=[decision("h1", "F.C")])
    made(tmp_path, "du", "20261016-110000-live", misread_hands=5,  # 50%: out
         decisions=[decision("h1", "F.C")])
    made(tmp_path, "mini", "20261016-120000-live", misread_hands=2,  # 20% vs 10%
         decisions=[decision("h1", "F.C")])
    (tmp_path / "du" / "notes").mkdir()                              # not a package
    copy = tmp_path / "pulled" / "du" / "20261016-100000-live" / "flywheel"
    copy.mkdir(parents=True)                                         # found twice
    (copy / "package.json").write_bytes(
        (tmp_path / "du" / "20261016-100000-live" / "flywheel" / "package.json")
        .read_bytes())
    assert evidence.main(["--all", str(tmp_path)]) == 0
    page = capsys.readouterr().out.splitlines()
    assert page[0].startswith("证据单（全部）：4 场，3 台机器")
    assert any(line.startswith("[du] 2 场、20 手") and "达标 1 场" in line
               for line in page)
    merged = next(line for line in page if line.startswith("合并："))
    assert merged.startswith("合并：2 场（不合并 2 场）")
    assert "mini（识别错率 20.0%，比最好的 10.0% 高出 10.0%）" in merged
    rule = next(line for line in page if line.startswith("  F.C"))
    assert "命中 2" in rule


def test_all_says_so_when_there_is_nothing(tmp_path, capsys):
    assert evidence.main(["--all", str(tmp_path)]) == 2
    assert "没有场次包" in capsys.readouterr().out


def ledger(group, entered, bb, *, luck_out=None, loosened=None, first=True):
    return {"first_divergence": first, "group": group if first else None,
            "entered": entered, "in_minus_fold_bb": bb if entered else None,
            "in_minus_fold_luck_out_bb": luck_out if entered else None,
            "loosened": loosened, "plain": {"action": "call" if loosened else "fold"}}


def test_the_ledger_adds_up_its_groups_and_tests_the_loosenings(tmp_path):
    path = made(tmp_path, "peng", "20261016-200000-live", hands=1000)
    data = json.loads(path.read_text(encoding="utf-8"))
    limps = [ledger("other", True, value, luck_out=value, loosened="late_limp")
             for value in (-1.0, 1.0, 2.0, -2.0)]
    items = [ledger("a_preflop_old_in", True, -4.0, luck_out=-3.0),
             ledger("a_preflop_old_in", False, None),
             ledger("c_old_allin", True, 50.0, luck_out=10.0), *limps]
    data["shadow"] = {"summary": {
        "page_version": "v3.3", "shown_by": {"plain": 7},
        "replay_matches_shown": {"n": 7, "same": 6}, "decisions": 7, "compared": 7,
        "diverged": 7, "first_divergences": 7,
        "groups": {}, "booked": {"n": 3, "plain_minus_old_bb": 1.0},
        "by_shown": {"n": 0, "plain_minus_old_bb": 0.0},
        "plain_fold_shown": {"n": 5, "weak": 2, "diverged": 1, "diverged_weak": 1},
        "fold_check": {"n": 1, "off": 0}}, "decisions": items}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    text = "\n".join(evidence.shadow_lines([evidence.load(path)]))
    assert "按一页纸 v3.3 重放：1 场 1000 手" in text and "一样 6/7" in text
    assert "a 翻前旧进、本页弃：2 手，你没弃 1" in text
    assert "记上账 1 手 -4.0 bb" in text and "扣全下后发牌运气 1 手 -3.0 bb" in text
    assert "c 旧策略建议全下（有效筹码 ≥ 50 个大盲）：1 手，你加注了 1" in text
    assert "晚位平跟：碰到 4 次，本页说进 4，你进了 4" in text
    assert "区间含 0 且上限 < +4：是" in text
    assert "大盲补齐：碰到 0 次" in text and "还算不出区间" in text
    assert ("P3：翻后本页说弃、还在的对手后来都亮了牌 5 次，其中对手亮的是一对或更差"
            "（一对、诈唬） 2 次；是分歧的 1 次（一对或更差 1）") in text


def test_a_page_without_loosenings_has_nothing_to_review(tmp_path):
    path = made(tmp_path, "peng", "20261017-200000-live", hands=300)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["shadow"] = {"summary": {
        "page_version": "v3.3a", "shown_by": {"plain": 2},
        "replay_matches_shown": {"n": 2, "same": 2}, "decisions": 2, "compared": 2,
        "diverged": 1, "first_divergences": 1, "groups": {}, "loosened": {},
        "booked": {"n": 0, "plain_minus_old_bb": 0.0},
        "by_shown": {"n": 0, "plain_minus_old_bb": 0.0},
        "fold_check": {"n": 0, "off": 0}},
        "decisions": [ledger("a_preflop_old_in", True, -4.0, luck_out=-4.0)]}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    text = "\n".join(evidence.shadow_lines([evidence.load(path)]))
    assert "按一页纸 v3.3a 重放：1 场 300 手" in text
    assert "放宽复核：这一版晚位平跟、小盲大盲补齐用的是 v3.2 的表，没有放宽要复核" in text
    assert "晚位平跟：碰到" not in text and "收回" not in text


def test_the_withdrawal_test_wants_0_inside_and_the_top_under_4():
    assert evidence.withdraw_line([-1.0, 1.0, 2.0, -2.0]).endswith(
        "是（到复核时还是这样就收回）")
    assert evidence.withdraw_line([9.0, 10.0, 11.0, 12.0]).endswith("否")   # all above 0
    assert evidence.withdraw_line([-30.0, 40.0, -20.0, 30.0]).endswith("否")  # top>4
    assert evidence.withdraw_line([3.0]) == "还算不出区间"


def test_compliance_adds_up_and_names_the_sessions_under_80(tmp_path):
    def tally(counted, complied, looser=0, tighter=0):
        rate = complied / counted
        return {"counted": counted, "complied": complied, "rate": rate,
                "looser": looser, "tighter": tighter, "no_advice": 1, "unknown": 2,
                "you_unread": 0, "results_count": rate >= 0.8}
    packages = []
    for label, numbers in (("20261016-200000-live", (100, 90, 6, 4)),
                           ("20261017-200000-live", (100, 70, 25, 5))):
        path = made(tmp_path, "peng", label)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["compliance"] = {"all": tally(*numbers), "plain": tally(*numbers)}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        packages.append(evidence.load(path))
    packages.append(evidence.load(made(tmp_path, "du", "20261016-100000-live")))
    text = evidence.compliance_lines(packages)
    assert text[0].endswith("全部 160/200（80%），偏松 31、偏紧 9；"
                            "一页纸 160/200（80%），偏松 31、偏紧 9")
    assert "没有建议 2、UNKNOWN 4" in text[1] and "（400 次才稳：不够）" in text[1]
    assert text[2] == "  低于 80% 的场次（本页规定不计成绩）：peng 20261017-200000-live（70%）"
    assert text[3] == "  没有遵从率的场次 1 场（场次包格式 1–2）"
    assert evidence.compliance_lines(packages[2:]) == [
        "遵从率：没有（1 场的场次包是格式 1–2）"]


def test_old_packages_say_they_have_no_ledger(tmp_path):
    path = made(tmp_path, "du", "20261016-100000-live")
    text = evidence.shadow_lines([evidence.load(path)])
    assert text[-2:] == ["  没有可比的决策",
                         "  没有分量账本的场次 1 场（场次包格式 1，或这一块没做成）"]


def ledger_package(version, hands, loosened=None):
    return {"session": {"hands": hands}, "shadow": {"summary": {
        "page_version": version, "shown_by": {"plain": 1},
        "replay_matches_shown": {"n": 1, "same": 1}, "decisions": 1, "compared": 1,
        "diverged": 0, "first_divergences": 0, "groups": {}, "loosened": loosened or {},
        "booked": {"n": 0, "plain_minus_old_bb": 0.0},
        "by_shown": {"n": 0, "plain_minus_old_bb": 0.0},
        "fold_check": {"n": 0, "off": 0}}, "decisions": []}}


def test_a_v33_ledger_and_a_v33c_ledger_are_not_added_up():
    """A package the v3.3 page wrote (its loosenings still in) and one this
    page writes now stay on two lines."""
    old = ledger_package("v3.3", 300, loosened={"late_limp": {"n": 0}})
    now = ledger_package(package.versions(plain_policy, None)["page"]["version"], 500)
    lines = [line for line in evidence.shadow_lines([old, now]) if "重放：" in line]
    assert len(lines) == 2, lines
