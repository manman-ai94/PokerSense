"""证据单: session packages as one page of plain text, for an AI to read.

    PYTHONPATH=src:. .venv/bin/python tools/session_evidence.py \\
        --package <录像文件夹>/flywheel/package.json
    PYTHONPATH=src:. .venv/bin/python tools/session_evidence.py \\
        --all <云盘里的“PokerSense 同事数据”文件夹> [--max-misread 0.2] [--agree 0.05]

It reads only what ``tools/session_package.py`` wrote and works nothing new
out about the play: coverage, how often iron rule 5 answered and why, the
rules ranked by hits (big blinds as played and with the luck taken out),
the decisions you did not follow (with your reason when the window kept
one), shown hands against the range the page read for them by preflop class
(with the seats that never showed as the denominator), misreads by kind,
changes of mind and time to advice. The layout is for reading by a program
or an AI, not for a person.

``--all`` takes every ``*/flywheel/package.json`` under the folder:

* first each machine on its own (sessions, hands, decisions, coverage, iron
  rule 5, misread rate, results);
* then together only the sessions whose misread rate (hands with a misread
  of their own: cards or board read two ways, an unexplained pot rise, an
  unrecorded fold, a skipped seat) is at most ``--max-misread``, and only
  from the machines whose rate over those sessions is within ``--agree`` of
  the best machine's: a machine that reads the table worse would bend the
  numbers. What was left out and why is printed.
* A session found twice (same machine and recording) counts once.
* Rules are counted per one-page version and rule hash: the same rule
  number with other wording or numbers is another line, never added up.
* Shown hands corrected by a later frame, shown by choice, or from a hand
  not seen whole never count for the ranges (``calibrates`` in the package).
* The 分量账本 (block 11) is added up per one-page version of the replay:
  for each of the page's three groups, what you got from the first
  divergence on less the fold line, with the plain 95% interval and the one
  that stays right however often it is looked at (``luck.always_valid``),
  raw and with the luck of the cards after an all-in taken out; and for
  each of v3.3's two loosenings the test to withdraw it (plain 95% interval
  of the luck-out numbers holds 0, top under +4 big blinds a hand; it is
  meant to be read once, after 1000-1500 hands). Packages from before
  block 11 are counted as having none.

The packages hold other players' hands: this reads them where they are and
prints counts; nothing is written.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poker_engine.scoreboard.luck import always_valid, interval  # noqa: E402

CLASSES = ("limp", "raise", "call_raise", "three_bet", "call_three_bet")
CLASS_WORD = {"limp": "平跟", "raise": "加注", "call_raise": "跟加注",
              "three_bet": "再加注", "call_three_bet": "跟再加注",
              "all_in": "全下", "bomb": "暴击局", "none": "翻前没投入"}
HAND_MISREADS = ("your_cards_two_ways", "board_two_ways", "unexplained_pot_rises",
                 "unrecorded_folds", "skipped_seats")
DECISION_MISREADS = ("price_missing", "pot_missing", "opponent_stack_missing")
MISREAD_WORD = {"your_cards_two_ways": "你的牌认成两种",
                "board_two_ways": "公共牌认成两种",
                "unexplained_pot_rises": "底池涨了没看到谁下注",
                "unrecorded_folds": "有人弃牌没记上",
                "skipped_seats": "行动顺序跳过了座位",
                "price_missing": "轮到你时缺跟注额",
                "pot_missing": "轮到你时缺底池",
                "opponent_stack_missing": "轮到你时缺对手筹码",
                "shown_cards_corrected": "亮牌被后帧纠正"}
OUTCOMES = ("showdown", "allin_showdown", "voluntary", "corrected", "mucked",
            "folded", "won_uncontested", "late", "unfinished")
OUTCOME_WORD = {"showdown": "普通摊牌", "allin_showdown": "全下摊牌",
                "voluntary": "主动亮", "corrected": "被纠正", "mucked": "盖牌",
                "folded": "弃", "won_uncontested": "没摊牌赢", "late": "没从头看到",
                "unfinished": "录像停在半手"}
STRATEGY_WORD = {"plain": "一页纸", "old": "旧策略"}
GROUP_WORD = {"a_preflop_old_in": "a 翻前旧进、本页弃",
              "b_postflop_plain_fold": "b 翻后本页弃、旧继续",
              "c_old_allin": "c 旧策略建议全下（有效筹码 ≥ 50 个大盲）"}
ENTER_WORD = {"a_preflop_old_in": "没弃", "b_postflop_plain_fold": "没弃",
              "c_old_allin": "加注了"}
GROUPS = (*GROUP_WORD, "other")       # as session_shadow.GROUPS
LOOSE_WORD = {"late_limp": "晚位平跟", "bb_complete": "大盲补齐", "sb_complete": "小盲补齐"}
WITHDRAW_TOP = 4.0
DEVIATIONS_SHOWN = 30
MAX_MISREAD = 0.2
AGREE = 0.05


def load(path):
    with open(path, encoding="utf-8") as handle:
        package = json.load(handle)
    if package.get("schema") != "pokersense.session_package":
        raise ValueError(f"{path} 不是场次包")
    package["_path"] = str(path)
    return package


def find(root):
    """Every session package under a folder, oldest recording first."""
    return sorted((path for path in Path(root).rglob("package.json")
                   if path.parent.name == "flywheel"),
                  key=lambda path: (path.parent.parent.name, str(path)))


def all_decisions(packages):
    return [item for package in packages for item in package.get("decisions") or ()]


def share(part, whole):
    return f"{part}/{whole}" + (f"（{part / whole:.0%}）" if whole else "")


def signed(value):
    return "无" if value is None else f"{value:+.1f}"


# -- what one or more packages add up to ---------------------------------------------

def misread_rate(package):
    """(hands with a misread of their own, hands) of one session."""
    hands = (package.get("misreads") or {}).get("counts", {}).get("hands") or 0
    bad = {(item["log"], item["hand_id"])
           for item in (package.get("misreads") or {}).get("items") or ()
           if item["type"] in HAND_MISREADS}
    return len(bad), hands


def page_of(package):
    page = (package.get("versions") or {}).get("page") or {}
    return page.get("version"), page.get("rules") or {}


def rule_lines(packages):
    """Rules by hits, one line per (page version, rule, hash)."""
    table = {}
    for package in packages:
        version, rules = page_of(package)
        for item in package.get("decisions") or ():
            rule = (item.get("advice") or {}).get("rule")
            if not rule:
                continue
            known = rules.get(rule) or {}
            key = (version, rule, known.get("sha256"))
            line = table.setdefault(key, {"label": known.get("text") or (
                item["advice"].get("rule_label")), "hits": 0, "followed": 0,
                "followed_of": 0, "hands": {}})
            line["hits"] += 1
            if item.get("followed") is not None:
                line["followed_of"] += 1
                line["followed"] += bool(item["followed"])
            line["hands"][(package["_path"], item["log"], item["hand_id"])] = (
                item.get("hand_bb"), item.get("hand_bb_luck_adjusted"))
    text = []
    for (version, rule, digest), line in sorted(
            table.items(), key=lambda pair: (-pair[1]["hits"], pair[0][1])):
        played = [bb for bb, _ in line["hands"].values() if bb is not None]
        adjusted = [bb for _, bb in line["hands"].values() if bb is not None]
        text.append(
            f"  {rule} {line['label'] or ''} [{version or '?'} {(digest or '?')[:8]}]："
            f"命中 {line['hits']}，照做 {line['followed']}/{line['followed_of']}，"
            f"这些手 {len(line['hands'])} 手 实际 {sum(played):+.1f} 大盲，"
            f"扣运气 {sum(adjusted):+.1f}（{len(adjusted)} 手算得出）")
    return text or ["  （没有一页纸打法的建议）"]


def iron5_lines(decisions):
    judged = [item for item in decisions if item.get("iron5") is not None]
    fired = [item for item in judged if item["iron5"]]
    causes = Counter()
    for item in fired:
        if item.get("missing"):
            causes[f"缺 {item['missing'][0]}"] += 1
        elif item.get("unspecified"):
            causes[f"v3.1 没写：{item['unspecified']}"] += 1
        else:
            causes[(item.get("advice") or {}).get("rule") or "?"] += 1
    text = [f"铁律 5：{share(len(fired), len(judged))} 个一页纸决策"]
    if causes:
        listed = [f"{cause} {count}" for cause, count in causes.most_common()]
        text.append("  主因：" + "、".join(listed))
    return text


def deviation_lines(decisions, limit=DEVIATIONS_SHOWN):
    off = [item for item in decisions if item.get("followed") is False]
    read = sum(item.get("followed") is not None for item in decisions)
    text = [f"偏离建议：{share(len(off), read)} 个读到你动作的决策"]
    for item in off[:limit]:
        advice = item.get("advice") or {}
        text.append(
            f"  {item['log']} {item['hand_id']} {item['street']} "
            f"{item.get('position') or '?'}："
            f"建议 {advice.get('action')}（{advice.get('rule') or advice.get('kind')}），"
            f"你 {item.get('you_did')}；这手 {signed(item.get('hand_bb'))} 大盲；"
            f"理由：{item.get('deviation_reason') or '没记'}")
    if len(off) > limit:
        text.append(f"  ……另有 {len(off) - limit} 个")
    return text


def range_lines(packages):
    """Shown hands against the page's range, by preflop class, with the
    seats that never showed as the denominator."""
    shown = [item for package in packages for item in package.get("shown") or ()]
    seats = {}
    for package in packages:
        for cls, counts in (package.get("shown_denominators") or {}).items():
            group = seats.setdefault(cls, Counter())
            group.update(counts)
    text = ["亮牌对范围（只算从头看到的手里全下摊牌和普通摊牌、没被纠正的）："]
    extra = [cls for cls in seats if cls not in CLASSES]
    for cls in (*CLASSES, *[cls for cls in ("all_in", "bomb", "none") if cls in extra]):
        mine = [item for item in shown if item.get("preflop_class") == cls]
        used = [item for item in mine if item.get("calibrates")]
        before = sum(bool((item["range"] or {}).get("preflop_in")) for item in used)
        after = sum(bool((item["range"] or {}).get("in")) for item in used)
        places = sorted((item["range"] or {}).get("percentile") for item in used
                        if (item["range"] or {}).get("percentile") is not None)
        counts = seats.get(cls, Counter())
        where = f"，真牌位置中位数 {statistics.median(places):.0%}" if places else ""
        text.append(
            f"  {CLASS_WORD.get(cls, cls)}：校准用 {len(used)} 个，翻前范围里 "
            f"{share(before, len(used))}，缩窄后范围里 {share(after, len(used))}{where}；"
            f"分母 {counts.get('seats', 0)} 个座位" + "".join(
                f"（{'、'.join(ends)}）" for ends in [[
                    f"{OUTCOME_WORD[key]} {counts[key]}" for key in OUTCOMES
                    if counts.get(key)]] if ends))
    return text


def misread_lines(packages):
    counts = Counter()
    for package in packages:
        counts.update((package.get("misreads") or {}).get("counts") or {})
    hands, decisions = counts["hands"], counts["decisions"]
    text = [f"识别错（{hands} 手、{decisions} 个决策、{counts['actions']} 个动作）："]
    for key in (*HAND_MISREADS, *DECISION_MISREADS, "shown_cards_corrected"):
        if counts.get(key):
            whole = hands if key in HAND_MISREADS else (
                decisions if key in DECISION_MISREADS else None)
            text.append(f"  {MISREAD_WORD[key]}：{counts[key]}"
                        + (f"（{counts[key] / whole:.1%}）" if whole else ""))
    inferred = share(counts["actions_inferred_from_chips"], counts["actions"])
    text.append(f"  动作靠筹码推断：{inferred}；"
                f"重放补上的动作：{counts['actions_filled_in_by_replay']}")
    return text


def timing_lines(packages):
    decisions = all_decisions(packages)
    seconds = sorted(item["seconds_to_advice"] for item in decisions
                     if item.get("seconds_to_advice") is not None)
    changes = sum((package.get("timing") or {}).get("changes_of_mind") or 0
                  for package in packages)
    changed = sum((package.get("timing") or {}).get("decisions_changed") or 0
                  for package in packages)
    before = [item.get("advice_before_action") for item in decisions
              if item.get("advice_before_action") is not None]
    text = [f"时序：没建议的决策 {sum(item.get('advice') is None for item in decisions)}/"
            f"{len(decisions)}；改口 {changes} 次（{changed} 个决策，应为 0）；"
            f"建议赶在你动作之前 {share(sum(before), len(before))}"]
    if seconds:
        p90 = seconds[min(len(seconds) - 1, int(0.9 * len(seconds)))]
        text.append(f"  出建议用时：中位 {statistics.median(seconds):.2f}s，"
                    f"90% {p90:.2f}s，最长 {seconds[-1]:.2f}s")
    return text


def _booked(values):
    """'+x bb，每手 +m（95% 区间 [lo, hi]；随时看都算数 ±h）' over these values."""
    if not values:
        return "没有"
    mean, half = interval(values)
    text = f"{sum(values):+.1f} bb，每手 {mean:+.2f}"
    if half is not None:
        steady = always_valid(values)[1]
        text += (f"（95% 区间 [{mean - half:+.2f}, {mean + half:+.2f}]；"
                 f"随时看都算数 ±{steady:.2f}）")
    return text


def withdraw_line(values):
    """v3.3's test for its two loosenings: the interval holds 0 and its top is
    under +4 big blinds a hand."""
    mean, half = interval(values)
    if half is None:
        return "还算不出区间"
    low, high = mean - half, mean + half
    meets = low <= 0 <= high and high < WITHDRAW_TOP
    return ("区间含 0 且上限 < +4：是（到复核时还是这样就收回）" if meets
            else "区间含 0 且上限 < +4：否")


def shadow_lines(packages):
    """分量账本 (block 11), per one-page version of the replay."""
    groups, without = {}, 0
    for package in packages:
        shadow = package.get("shadow")
        if not shadow or "groups" not in shadow.get("summary", {}):
            without += 1
            continue
        version = shadow["summary"].get("page_version") or "无"
        groups.setdefault(version, []).append((package, shadow))
    text = ["分量账本（一页纸第七节：本页和旧策略都按录像离线重放，每手只记第一个分歧，"
            "弃 = 0；数字是你投进去的实得减弃牌线，正数是比弃好；只记账，不给打牌的人看）："]
    for version, found in sorted(groups.items()):
        tops = [shadow["summary"] for _, shadow in found]
        items = [item for _, shadow in found for item in shadow["decisions"]]
        hands = sum((package.get("session") or {}).get("hands") or 0
                    for package, _ in found)
        shown_by = Counter()
        for top in tops:
            shown_by.update(top.get("shown_by") or {})
        showed = "、".join(f"{STRATEGY_WORD.get(name, name)} {count}"
                          for name, count in shown_by.most_common()) or "无"
        same = sum(top["replay_matches_shown"]["same"] for top in tops)
        checked = sum(top["replay_matches_shown"]["n"] for top in tops)
        text.append(
            f"  按一页纸 {version} 重放：{len(found)} 场 {hands} 手，决策 "
            f"{sum(top['decisions'] for top in tops)}，两边都有建议 "
            f"{sum(top['compared'] for top in tops)}，分歧 "
            f"{sum(top['diverged'] for top in tops)}（每手第一个 "
            f"{sum(top['first_divergences'] for top in tops)}）；窗口当时显示 "
            f"{showed}，重放和窗口说的一样 {same}/{checked}")
        for name in GROUPS:
            mine = [item for item in items
                    if item.get("first_divergence") and item["group"] == name]
            if name == "other":
                text.append(f"    其他分歧 {len(mine)} 手（不在三组里，只数不记）")
                continue
            went = [item for item in mine if item["entered"]]
            raw = [item["in_minus_fold_bb"] for item in went
                   if item["in_minus_fold_bb"] is not None]
            lucky = [item["in_minus_fold_luck_out_bb"] for item in went
                     if item["in_minus_fold_luck_out_bb"] is not None]
            text.append(f"    {GROUP_WORD[name]}：{len(mine)} 手，你{ENTER_WORD[name]} "
                        f"{len(went)}（另 {len(mine) - len(went)} 手你没走这条线，只数不记）；"
                        f"记上账 {len(raw)} 手 {_booked(raw)}；扣全下后发牌运气 "
                        f"{len(lucky)} 手 {_booked(lucky)}")
        text.append("    放宽复核（v3.3 新加的牌；1000–1500 手后区间含 0 且上限 < +4 bb/手"
                    f" → 收回；现在 {hands} 手）：")
        for name, word in LOOSE_WORD.items():
            mine = [item for item in items if item.get("loosened") == name]
            went = [item for item in mine if item["entered"]]
            lucky = [item["in_minus_fold_luck_out_bb"] for item in went
                     if item["in_minus_fold_luck_out_bb"] is not None]
            raw = [item["in_minus_fold_bb"] for item in went
                   if item["in_minus_fold_bb"] is not None]
            enters = sum((item.get("plain") or {}).get("action") not in (None, "fold")
                         for item in mine)
            text.append(f"      {word}：碰到 {len(mine)} 次，本页说进 {enters}，你进了 "
                        f"{len(went)}；扣运气 {len(lucky)} 手 {_booked(lucky)}，"
                        f"{withdraw_line(lucky)}；不扣运气 {_booked(raw)}")
        shown = sum(top["by_shown"]["n"] for top in tops)
        shown_bb = sum(top["by_shown"]["plain_minus_old_bb"] for top in tops)
        booked = sum(top["booked"]["n"] for top in tops)
        booked_bb = sum(top["booked"]["plain_minus_old_bb"] for top in tops)
        folds = sum(top["fold_check"]["n"] for top in tops)
        off = sum(top["fold_check"]["off"] for top in tops)
        text.append(f"    另两种算法（不和上面相加）：两条线都算得出的分歧 {booked} 次，本页减旧 "
                    f"{booked_bb:+.1f} bb；按亮牌算 {shown} 次，本页减旧 {shown_bb:+.1f} bb")
        text.append(f"    你弃牌时“从这一步起”不是 0 的 {off}/{folds}（筹码读错的迹象）；"
                    "旧策略重放时单挑转牌河牌用范围规则代替求解器")
    if not groups:
        text.append("  没有可比的决策")
    if without:
        text.append(f"  没有分量账本的场次 {without} 场（场次包格式 1，或这一块没做成）")
    return text


def coverage_lines(packages):
    decisions = all_decisions(packages)
    advised = sum(item.get("advice") is not None for item in decisions)
    full = [package["session"].get("fully_advised") for package in packages]
    full = [pair for pair in full if isinstance(pair, (list, tuple)) and len(pair) == 2]
    text = [f"覆盖：有建议的决策 {share(advised, len(decisions))}"]
    if full:
        whole = share(sum(pair[0] for pair in full), sum(pair[1] for pair in full))
        text[0] += f"；每手全覆盖 {whole}"
    return text


def results_line(packages):
    hands = sum(((package["session"].get("results") or {}).get("all") or {}).get(
        "hands") or 0 for package in packages)
    played = sum(((package["session"].get("results") or {}).get("all") or {}).get(
        "bb") or 0 for package in packages)
    lucky = [package["session"].get("luck_adjusted") for package in packages]
    known = [item for item in lucky if item and item.get("adjusted_bb_per_100")
             is not None]
    line = f"成绩：{hands} 手 {played:+.1f} 大盲"
    if hands:
        line += f"（每百手 {played / hands * 100:+.1f}）"
    if len(known) == 1 and len(packages) == 1:
        item = known[0]
        line += (f"；扣运气每百手 {item['adjusted_bb_per_100']:+.1f}，区间 "
                 f"{item.get('adjusted_ci95')}，结论 {item.get('verdict')}")
    elif known:
        weight = sum(item["hands"] for item in known)
        mean = sum(item["adjusted_bb_per_100"] * item["hands"] for item in known)
        line += f"；扣运气每百手（{weight} 手按手数加权）{mean / weight:+.1f}"
    return line


def body(packages):
    """The sections every page has, over these packages."""
    decisions = all_decisions(packages)
    text = [results_line(packages)]
    text += coverage_lines(packages)
    text += iron5_lines(decisions)
    text.append("规则命中排行（按一页纸版本和规则哈希分开）：")
    text += rule_lines(packages)
    text += deviation_lines(decisions)
    text += range_lines(packages)
    text += misread_lines(packages)
    text += timing_lines(packages)
    text += shadow_lines(packages)
    return text


# -- the two pages ---------------------------------------------------------------------

def one(package):
    session, identity = package["session"], package.get("identity") or {}
    version, rules = page_of(package)
    code = session.get("code") or {}
    text = [f"证据单 {session['label']} · 机器 {session.get('machine')} · "
            f"打牌人 {identity.get('player')} · "
            f"{'观战' if session.get('spectate') else '坐着打'} · 代码 "
            f"{(code.get('commit') or '?')[:7]} · 一页纸 {version or '无'}"
            f"（{len(rules)} 条规则）· 级别 " + ("、".join(
                f"{level} {count} 手" for level, count in
                (session.get("stakes") or {}).items()) or "没读到"),
            f"手数 {session.get('hands')}，你的决策 {session.get('decisions')}，"
            f"亮牌 {len(package.get('shown') or ())}，场次包格式 {package.get('format')}"]
    text += body([package])
    nulls = package.get("nulls") or {}
    if nulls:
        text.append("缺的字段：" + "；".join(f"{key}：{why}" for key, why in nulls.items()))
    return text


def everything(packages, *, max_misread=MAX_MISREAD, agree=AGREE):
    seen, unique = set(), []
    for package in packages:            # a session found twice counts once
        key = (package["session"].get("machine"), package["session"].get("label"))
        if key not in seen:
            seen.add(key)
            unique.append(package)
    packages = unique
    by_machine = {}
    for package in packages:
        machine = package["session"].get("machine") or "?"
        by_machine.setdefault(machine, []).append(package)
    text = [f"证据单（全部）：{len(packages)} 场，{len(by_machine)} 台机器；"
            f"识别错率上限 {max_misread:.0%}，各机相差不超过 {agree:.0%}"]
    rates, kept = {}, {}
    for machine, mine in sorted(by_machine.items()):
        good = []
        for package in mine:
            bad, hands = misread_rate(package)
            if hands and bad / hands <= max_misread:
                good.append(package)
        bad = sum(misread_rate(package)[0] for package in good)
        hands = sum(misread_rate(package)[1] for package in good)
        all_bad = sum(misread_rate(package)[0] for package in mine)
        all_hands = sum(misread_rate(package)[1] for package in mine)
        if hands:
            rates[machine] = bad / hands
        kept[machine] = good
        decisions = all_decisions(mine)
        text.append(f"[{machine}] {len(mine)} 场、{all_hands} 手、{len(decisions)} 个决策；"
                    f"识别错的手 {share(all_bad, all_hands)}；达标 {len(good)} 场")
        text += ["  " + line for line in (
            [results_line(mine)] + coverage_lines(mine) + iron5_lines(decisions))]
    best = min(rates.values()) if rates else None
    merged, left = [], []
    for machine in sorted(by_machine):
        if machine not in rates:
            left.append(f"{machine}（没有达标的场次）")
        elif rates[machine] - best > agree:
            left.append(f"{machine}（识别错率 {rates[machine]:.1%}，比最好的 "
                        f"{best:.1%} 高出 {rates[machine] - best:.1%}）")
        else:
            merged += kept[machine]
    dropped = sum(len(mine) for mine in by_machine.values()) - len(merged)
    text.append(f"合并：{len(merged)} 场（不合并 {dropped} 场）"
                + (f"；整台不合并：{'、'.join(left)}" if left else ""))
    versions = Counter(page_of(package)[0] or "无" for package in merged)
    listed = [f"{version} {count} 场" for version, count in versions.most_common()]
    text.append("一页纸版本：" + ("、".join(listed) or "无"))
    if merged:
        text += body(merged)
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--package", type=Path)
    which.add_argument("--all", type=Path)
    parser.add_argument("--max-misread", type=float, default=MAX_MISREAD)
    parser.add_argument("--agree", type=float, default=AGREE)
    args = parser.parse_args(argv)
    if args.package:
        print("\n".join(one(load(args.package))))
        return 0
    paths = find(args.all)
    if not paths:
        print(f"{args.all} 下面没有场次包（*/flywheel/package.json）")
        return 2
    packages = []
    for path in paths:
        try:
            packages.append(load(path))
        except (OSError, ValueError) as exc:
            print(f"跳过 {path}：{exc}")
    print("\n".join(everything(packages, max_misread=args.max_misread,
                               agree=args.agree)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
