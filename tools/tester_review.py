"""A tester's uploaded recordings, reviewed once each is finished (同事录像复盘);
the owner's own Mac recordings the same way (``--machine peng``).

Exception-based: nobody watches the video. For each recording another
computer uploaded (``poker_engine.desktop.aa_upload``: ``frames.jsonl``, the
window's own log of what it read and advised during play, ``recording.json``
and ``upload.json``) it says what went wrong, against the Samsung baseline of
``tools/p30_acceptance.py`` and the owner's Mac:

* the computer: frames read per second and the time recognition takes per
  frame (a slow computer reads fewer frames, so actions and cards get
  missed), frames the recorder skipped, the video writer, errors;
* recognition: every field's coverage (``p30_acceptance.field_coverage``)
  against 90% of the Samsung baseline, and the hands whose level (blinds)
  was read from the table;
* advice (``tools/aa_session_report.py``): the tester's turns with no advice
  on screen (there should be none), and why; hands advised at every step;
  stalls over two seconds; the turns where the advice and his answer were
  far apart (``far_apart``: a big bet, raise or all in advised and he
  folded, or a fold advised and he put a lot in), the advice to look at
  first;
* opponents: the hands whose other seats' actions are clean enough for the
  AA population statistics (``tools/aa_population_stats.py``; the tester's
  own seat is left out, as peng's is);
* results (``tools/luck_results.py``): what the advice won at his seat, in
  big blinds per 100 hands as played and with the luck of the cards dealt
  and of all-in runouts taken out, with the interval that stays right
  however often it is looked at; and the same for every recording of that
  machine so far. His play is not judged: a decision's line says what the
  advice was and whether it was followed, nothing more.

    PYTHONPATH=src:. .venv/bin/python tools/tester_review.py run \\
        --recording <录像文件夹> [...] --state <复盘目录> --out <这次的输出目录>
    PYTHONPATH=src:. .venv/bin/python tools/tester_review.py population \\
        --state <复盘目录> --out <aa_population_stats.json>
    PYTHONPATH=src:. .venv/bin/python tools/tester_review.py results \\
        --state <复盘目录> --out <成绩.json>

A recording folder is the cloud copy (with ``upload.json``) or one pulled to
this computer (``pulled.json``); its machine and own name come from there.
``run`` skips recordings already in ``<复盘目录>/reviewed.jsonl`` with the
same files (``--again`` reviews them again), writes ``<机器>-<录像>.json``
for each, ``复盘单.md`` (totals only, with the change since that machine's
last review), ``三行.txt`` and, when the owner's own recordings (``--machine``)
were among them, ``给主人.txt`` (two lines to him: hands and result, what to
look at) into ``--out``, and adds to the state:
``reviewed.jsonl`` (a line per recording) and ``hands.jsonl`` (its hand lines
for the population statistics), ``results.jsonl`` (a line per hand with
its result and luck) and ``decisions.jsonl`` (a line per decision: the
advice, what he did, the hand's result). The sheet's results are totals,
for the recording and for the machine so far; a last line counts every
machine's hands with a result toward the table condition (``TABLE_HANDS``
hands, luck-adjusted not clearly losing). ``results`` writes the
totals so far per machine (and all machines together) as JSON and prints
them in plain lines. ``population`` builds the statistics from the
base sample of ``<复盘目录>/population-base.json`` (``{"hands": <hand lines>,
"hero_logs": [...], "minutes": {...}}``, the path relative to that file)
plus every reviewed recording, the testers' own seats left out. All of it
stays in the private data folder: logs and hand lines hold other players'
hands.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import statistics
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop import aa_upload  # noqa: E402
from tools import aa_population_stats as pop  # noqa: E402
from tools import flywheel_session as fly  # noqa: E402
from tools import luck_results  # noqa: E402
from tools import p30_acceptance as p30  # noqa: E402
from tools.aa_session_report import session_report  # noqa: E402
from tools.flywheel_sync import digest_of  # noqa: E402

REVIEWED = "reviewed.jsonl"
HANDS = "hands.jsonl"
RESULTS = "results.jsonl"
DECISIONS = "decisions.jsonl"
BASE = "population-base.json"
SHEET = "复盘单.md"
LINES = "三行.txt"
OWNER = "给主人.txt"
# The owner's Mac, window log of 20261010-012911-live: 7.8 frames read per
# second, recognition 83 ms a frame (median).
MAC_FPS, MAC_RECOGNITION_MS = 7.8, 83
SLOW_FPS = 4.0              # fewer frames read per second: a slow computer
SKIPPED_LINE = 0.02         # frames the recorder dropped
MB_PER_HOUR_LINE = 2000     # an FFmpeg recording is 0.5-1 GB an hour
STAKES_LINE = 0.9           # hands whose level was read from the table
USABLE_LINE = 0.7           # hands usable for the opponents (Mac: about 85%)
SHORT_MINUTES = 3           # shorter: numbers are only a hint
TOP_CAUSES = 3
TOP_PROBLEMS = 3            # in the three lines
# Advice and answer far apart: this many big blinds or more advised and
# folded, or put in against a fold (10/16: an all in to 143 advised with 3-8
# after a misread level; peng caught it by eye).
FAR_BB = 20
FAR_SHOWN = 3               # of them in the problem line
ALL_IN_SHARE = Decimal("0.95")  # of his chips: an all in
HERO = "4"
STREETS = {"preflop": "翻前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}
LA_FALLBACK = timezone(timedelta(hours=-7), "UTC-7")
# Shares of hands on the owner's Mac (9 recordings of 10/08-10/10, 394
# hands, measured at 8f4f2c3): a tester's share is a problem past twice that
# (and at least two hands).
MAC_REPLAY_STOPS = 0.155    # hands that stop replaying on the AA table
MAC_MISREADS = {"board_card_read_two_ways": 0.038, "your_cards_read_two_ways": 0.005,
                "hands_with_skipped_seats": 0.132,
                "hands_with_unexplained_pot_rises": 0.053,
                "hands_with_unrecorded_folds": 0.003, "hand_split_in_two": 0.0,
                "dealer_unread": 0.043}
TIMES_MAC = 2
# The condition for playing on (peng, Oct 15): this many hands with a
# result, all machines together, luck-adjusted not clearly losing.
TABLE_HANDS = 2000
# How a machine is named to people (the rest by their machine name).
SHOWN = {"du": "杜"}
# Why a turn got no advice, or a hand stopped replaying, in plain words.
CAUSES = {
    "dealer_ambiguous": "庄位没认清", "no_dealer_fits": "庄位对不上",
    "street_mismatch": "街道对不上", "starts_after_preflop": "翻后才看到这手",
    "raise_without_amount": "加注没读到金额", "not_this_seats_turn": "动作顺序对不上",
    "illegal_at_the_table": "动作不合规则", "stacks_do_not_fit": "筹码对不上",
    "stacks_unknown": "筹码没读到", "price_does_not_match": "跟注额对不上",
    "board_not_read": "公共牌没读出", "hand_incomplete": "这手没读全",
    "history_says_not_your_turn": "动作记录说还没轮到他",
    "solve_not_finished": "求解没算完"}
# Hands read wrong (``aa_session_report`` hand problems).
MISREADS = {
    "board_card_read_two_ways": "公共牌读成两样",
    "your_cards_read_two_ways": "他的手牌读成两样",
    "hands_with_skipped_seats": "漏了座位的动作",
    "hands_with_unexplained_pot_rises": "底池涨了没读到下注",
    "hands_with_unrecorded_folds": "弃牌没记上",
    "hand_split_in_two": "一手被拆成两手", "dealer_unread": "庄位没读出"}


def los_angeles():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:           # no time zone data (Windows without tzdata)
        return LA_FALLBACK


def identify(folder, machine=None):
    """(machine, its own folder name, digest of its files) of a recording."""
    folder = Path(folder)
    for marker in (aa_upload.MARKER, aa_upload.PULLED):
        try:
            data = json.loads((folder / marker).read_text(encoding="utf-8"))
            digest = data.get("digest") or digest_of(
                [[str(rel), int(size)] for rel, size in data["files"]])
            return str(data["machine"]), str(data["folder"]), digest
        except (OSError, ValueError, KeyError, TypeError):
            continue
    frames = folder / "frames.jsonl"
    size = frames.stat().st_size if frames.exists() else 0
    return machine or fly.LOCAL, folder.name, f"frames.jsonl:{size}"


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_lines(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def write_lines(path, items):
    Path(path).write_text("".join(json.dumps(item, ensure_ascii=False) + "\n"
                                  for item in items), encoding="utf-8")


def speed(rows):
    """Frames read per second of play and recognition time per frame."""
    pts = [row["pts_seconds"] for row in rows
           if isinstance(row.get("pts_seconds"), (int, float))]
    span = pts[-1] - pts[0] if len(pts) > 1 else 0
    times = sorted(row["timing"]["recognition_ms"] for row in rows
                   if isinstance((row.get("timing") or {}).get("recognition_ms"),
                                 (int, float)))
    return {"frames_per_second": round((len(pts) - 1) / span, 2) if span > 0 else None,
            "recognition_ms": round(statistics.median(times)) if times else None,
            "recognition_ms_p90": (round(times[int(0.9 * (len(times) - 1))])
                                   if times else None)}


def stakes_read(rows):
    """(hands whose level was read from the table, hands)."""
    found = fly.hand_stakes(fly.by_hand(rows))
    return [sum(item["source"] == "table" for item in found.values()), len(found)]


def advice(name, rows):
    """The window's advice on the tester's turns (``aa_session_report``)."""
    summary = session_report([(name, rows)])["summary"]
    full = summary["fully_advised"]
    return {"hands": summary["hands"], "turns": summary["your_decisions"],
            "advised": summary["advised"],
            "blank": summary["your_decisions"] - summary["advised"],
            "causes": summary["no_advice_causes"],
            "advised_by_kind": summary["advised_by_kind"],
            "fully_advised": [full["advised"], full["hands"]],
            "past_preflop_advised": [full["past_preflop_advised"],
                                     full["past_preflop"]],
            "seconds_to_advice": summary["seconds_to_advice_median"],
            "stalls_over_2s": summary["stalls_over_2s"],
            "hand_problems": summary["hand_problems"]}


def _decimal(value):
    try:
        return None if value in (None, "") else Decimal(str(value))
    except InvalidOperation:
        return None


def far_apart(rows, started=None):
    """His turns where the advice and his answer were far apart: a bet,
    raise or all in of ``FAR_BB`` big blinds or more advised and he folded,
    or a fold advised and he put that much in (called, raised or went all
    in). His play is not judged: it is the advice there to look at again,
    worst read first (a misread level, a hand run on into the next)."""
    hands = fly.by_hand(rows)
    stakes = fly.hand_stakes(hands)
    found = []
    for hand_id, part in hands.items():
        big_blind = _decimal(stakes[hand_id]["big_blind"])
        actions = part[-1]["fields"]["actions_v1"].get("actions") or []
        turn = []
        for row in part + [None]:
            if row is not None and (row["fields"].get("hero_controls")
                                    or {}).get("visible"):
                turn.append(row)
                continue
            item = _far(hand_id, turn, actions, big_blind, started) if turn else None
            if item:
                found.append(item)
            turn = []
    return found


def _far(hand_id, turn, actions, big_blind, started):
    """One turn's far-apart line, or None."""
    ready = [report for report in map(fly._advice, turn)
             if report.get("status") == "ready" and report.get("advice")]
    if not ready or not big_blind:
        return None
    advised, street = ready[-1]["advice"][0], ready[-1].get("street")
    first = turn[0]
    answer = next((item for item in actions if str(item[2]) == HERO
                   and item[1] == street and item[0] >= first["processed"]), None)
    if answer is None:
        return None
    advice, did = advised.get("action"), answer[3]
    fields = first["fields"]
    chips = ((_decimal((fields.get("stacks") or {}).get(HERO)) or 0)
             + (_decimal((fields.get("street_wagers") or {}).get(HERO)) or 0))
    to = _decimal(advised.get("to"))
    paid = _decimal(answer[4]) if len(answer) > 4 else None
    if did == "call" and not paid:
        paid = _decimal((fields.get("hero_controls") or {}).get("call_amount"))

    def blinds(value):
        return f"{float(value / big_blind):.0f}"

    if (advice in ("bet", "raise", "all_in") and did == "fold" and to
            and to >= FAR_BB * big_blind):
        shove = advice == "all_in" or (chips and to >= ALL_IN_SHARE * chips)
        text = (f"建议全下 {blinds(to)} 个大盲" if shove else
                f"建议{'下注' if advice == 'bet' else '加注到'} {blinds(to)} 个大盲"
                ) + "、他弃牌"
    elif (advice == "fold" and did in ("call", "bet", "raise", "all_in") and paid
          and paid >= FAR_BB * big_blind):
        text = "建议弃牌、他" + {"call": "跟了", "all_in": "全下"}.get(
            did, "加注到") + f" {blinds(paid)} 个大盲"
    else:
        return None
    seconds = first.get("video_seconds")
    return {"hand_id": hand_id, "video_seconds": seconds, "street": street,
            "advice": advice, "advice_to": None if to is None else str(to),
            "you_did": did, "you_put": None if paid is None else str(paid),
            "big_blind": str(big_blind),
            "text": f"{clock(started, seconds)} {STREETS.get(street, '')}{text}"}


def clock(started, seconds):
    """When in the recording, as peng reads it: 19:29 (Los Angeles), or the
    minute of the recording when its start is not known."""
    try:
        moment = datetime.strptime(started, "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        moment = None
    if moment is None or not isinstance(seconds, (int, float)):
        return f"第 {int(seconds or 0) // 60} 分钟"
    local = (moment + timedelta(seconds=seconds)).astimezone(los_angeles())
    return f"{local.hour}:{local.minute:02d}"


def opponents(log, rows):
    """The hand lines for the population statistics and how many are usable."""
    lines = pop.reduce_log(rows, log)
    [source] = pop.build(lines, {log})["sources"] or [{}]
    return lines, [source.get("counted", 0), len(lines)]


def recording_facts(folder):
    info = read_json(Path(folder) / "recording.json")
    seconds = info.get("recorded_seconds")
    offered = info.get("offered_frames") or 0
    megabytes = info.get("megabytes")
    return {"started": info.get("started"),
            "minutes": round(seconds / 60, 2) if seconds else None,
            "code": (info.get("code") or {}).get("commit"),
            "api": info.get("api"), "backend": info.get("backend"),
            "fourcc": info.get("fourcc"), "error": info.get("error"),
            "skipped": (round((info.get("skipped_frames") or 0) / offered, 4)
                        if offered else None),
            "mb_per_hour": (round(megabytes / seconds * 3600)
                            if megabytes and seconds else None)}


def played(machine, log, rows, code):
    """(hand result lines, decision lines) of the tester's seat
    (``luck_results``), each marked with the machine."""
    if not rows:
        return [], []
    hands, ledger = luck_results.hand_lines(log, rows, code)
    return ([{"machine": machine, **line} for line in hands],
            [{"machine": machine, **line} for line in ledger])


def review(folder, baseline, machine=None):
    """Everything this tool says about one recording, its population lines,
    and its result and decision lines (private)."""
    folder = Path(folder)
    machine, name, digest = identify(folder, machine)
    rows = [row for row in fly.load(folder / "frames.jsonl") if row.get("fields")]
    log = f"{machine}-{name}"
    measured = p30.field_coverage(rows) if rows else None
    lines, usable = opponents(log, rows)
    facts = recording_facts(folder)
    hands, ledger = played(machine, log, rows, facts["code"])
    result = {"machine": machine, "folder": name, "log": log, "digest": digest,
              "recording": facts, "frames": len(rows),
              "speed": speed(rows),
              "recognition": p30.compare(measured, baseline) if rows else None,
              "stakes_read": stakes_read(rows),
              "advice": advice(log, rows) if rows else None,
              "far_apart": far_apart(rows, facts["started"]),
              "opponents_usable": usable,
              "results": luck_results.summarize(hands)}
    result["problems"] = problems(result)
    return result, lines, hands, ledger


def show(machine):
    return SHOWN.get(machine, machine)


def _pct(value):
    return "—" if value is None else f"{value:.0%}"


def plain_cause(code):
    """``abstain:dealer_ambiguous`` -> 庄位没认清 (unknown codes as they are)."""
    reason = str(code).split(":")[-1]
    return CAUSES.get(reason, reason)


def counted(items):
    return "、".join(f"{name} {count}" for name, count in items)


def worse_than_mac(count, hands, mac):
    return bool(hands) and count >= 2 and count > TIMES_MAC * mac * hands


def tester(label):
    """The acceptance labels speak to the seat's player; here that is him."""
    return label.replace("你", "他")


def problems(result):
    """What went wrong, worst first, in plain words (empty: nothing)."""
    found = []
    facts = result["recording"]
    if not result["frames"]:
        return ["窗口日志是空的：这场没有可复盘的帧"]
    if facts["error"]:
        found.append(f"录像出错：{facts['error']}")
    far = result.get("far_apart") or []
    if far:
        found.append(f"建议和他的选择差很远 {len(far)} 次，先看这几处建议对不对："
                     + "，".join(item["text"] for item in far[:FAR_SHOWN])
                     + ("等" if len(far) > FAR_SHOWN else ""))
    rate = result["speed"]["frames_per_second"]
    if rate is not None and rate < SLOW_FPS:
        found.append(
            f"电脑太慢：每秒只读 {rate:g} 帧（Mac 约 {MAC_FPS:g}），识别一帧"
            f" {result['speed']['recognition_ms']} 毫秒（Mac 约 {MAC_RECOGNITION_MS}），"
            "动作和牌容易漏读")
    turns = result["advice"]
    if turns["blank"]:
        causes = counted((plain_cause(cause), count) for cause, count in list(
            turns["causes"].items())[:TOP_CAUSES])
        found.append(f"轮到他 {turns['turns']} 次，{turns['blank']} 次窗口没给建议"
                     + (f"（{causes}）" if causes else ""))
    for row in (result["recognition"] or {}).get("rows", ()):
        if row["verdict"] == "不通过":
            found.append(f"{tester(row['label'])}只读出 {_pct(row['value'])}"
                         f"（三星 {_pct(row['baseline'])}，线 {_pct(row['line'])}）")
    hand_problems = turns["hand_problems"]
    stops = Counter({key.split(":", 1)[1]: count for key, count in
                     hand_problems.items() if key.startswith("replay_stops:")})
    if worse_than_mac(sum(stops.values()), turns["hands"], MAC_REPLAY_STOPS):
        found.append(f"{turns['hands']} 手里 {sum(stops.values())} 手在模拟牌桌上"
                     "按 AA 规则重放不下去（" + counted(
                         (plain_cause(code), count)
                         for code, count in stops.most_common(TOP_CAUSES)) + "）")
    misread = [(MISREADS[key], hand_problems[key]) for key in MISREADS
               if worse_than_mac(hand_problems.get(key, 0), turns["hands"],
                                 MAC_MISREADS[key])]
    if misread:
        found.append("读错：" + counted(misread))
    done, deep = turns["past_preflop_advised"]
    if deep and done < deep:
        found.append(f"打到翻后的 {deep} 手里，每一步都有建议的只有 {done} 手")
    read, hands = result["stakes_read"]
    if hands and read < STAKES_LINE * hands:
        found.append(f"{hands - read}/{hands} 手没从牌桌读出级别（盲注）")
    usable, total = result["opponents_usable"]
    if total and usable < USABLE_LINE * total:
        found.append(f"能用来统计对手的只有 {usable}/{total} 手"
                     "（Mac 录像约 85%）：有人的动作漏读了")
    if turns["stalls_over_2s"]:
        found.append(f"卡顿超过 2 秒 {turns['stalls_over_2s']} 次")
    if facts["skipped"] is not None and facts["skipped"] > SKIPPED_LINE:
        found.append(f"录像丢了 {_pct(facts['skipped'])} 的帧")
    if facts["mb_per_hour"] is not None and facts["mb_per_hour"] > MB_PER_HOUR_LINE:
        found.append(f"录像每小时 {facts['mb_per_hour']} MB（编码 "
                     f"{facts['backend'] or facts['fourcc']}），上传会很慢")
    return found


def numbers(result):
    """What the ledger keeps of a review, for the next day's comparison."""
    rows = {row["key"]: row["value"]
            for row in (result["recognition"] or {}).get("rows", ())}
    turns = result["advice"] or {}
    return {"frames_per_second": result["speed"]["frames_per_second"],
            "recognition_ms": result["speed"]["recognition_ms"],
            "coverage": rows, "turns": turns.get("turns"),
            "blank": turns.get("blank"), "fully_advised": turns.get("fully_advised"),
            "stakes_read": result["stakes_read"],
            "opponents_usable": result["opponents_usable"],
            "stalls_over_2s": turns.get("stalls_over_2s")}


def when(started):
    """``recording.json``'s start in Los Angeles time, as peng reads it."""
    try:
        moment = datetime.strptime(started, "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None
    local = moment.astimezone(los_angeles())
    hour = local.hour % 12 or 12
    part = "上午" if local.hour < 12 else "下午" if local.hour < 18 else "晚上"
    return f"{local.month}/{local.day} {part} {hour}:{local.minute:02d}（洛杉矶）"


def short(minutes):
    return minutes is not None and minutes < SHORT_MINUTES


def change(before, after):
    """The numbers that moved since the machine's last review."""
    moved = []

    def add(label, old, new, text):
        if old is not None and new is not None and old != new:
            moved.append(f"{label} {text(old)} → {text(new)}")

    add("读帧", before.get("frames_per_second"), after.get("frames_per_second"),
        lambda v: f"{v:g}/秒")
    old, new = before.get("coverage") or {}, after.get("coverage") or {}
    for key, label in (("pot", "底池"), ("hero_cards", "手牌"), ("board", "公共牌"),
                       ("actor", "行动者"), ("dealer", "庄位")):
        if old.get(key) is not None and new.get(key) is not None and abs(
                old[key] - new[key]) >= 0.05:
            add(label, old[key], new[key], _pct)

    def share(pair):
        return None if not pair or not pair[1] else pair[0] / pair[1]

    blank = [None if not item.get("turns") else item["blank"] / item["turns"]
             for item in (before, after)]
    add("没建议的轮次", *blank, _pct)
    add("每步有建议的手", share(before.get("fully_advised")),
        share(after.get("fully_advised")), _pct)
    add("能统计对手的手", share(before.get("opponents_usable")),
        share(after.get("opponents_usable")), _pct)
    return moved


def table_condition(lines, machines=()):
    """One line: the hands with a result so far toward ``TABLE_HANDS``, by
    machine, and the luck-adjusted verdict of all of them together."""
    counts = Counter(line.get("machine") for line in lines)
    for machine in machines:
        counts.setdefault(machine, 0)
    verdict = luck_results.summarize(lines).get("verdict") if lines else None
    order = sorted(counts.items(), key=lambda item: str(item[0]))
    by = "，".join(f"{show(machine)} {count}" for machine, count in order)
    return (f"上桌条件：{len(lines)}/{TABLE_HANDS} 手" + (f"（{by}）" if by else "")
            + f"，扣掉运气 {verdict or '说不准'}")


def owner_lines(own, summary):
    """Two plain lines to the owner about his own recordings of this run
    (none when there are none): how long, the hands and the result with
    luck taken out (``summary``: ``luck_results.summarize`` of their hands),
    then what is worth his attention. His decisions are not judged."""
    if not own:
        return []
    minutes = sum(item["recording"]["minutes"] or 0 for item in own)
    first = when(own[0]["recording"]["started"]) if len(own) == 1 else None
    what = (f"你 {first}开始，打了 {minutes:.0f} 分钟" if first
            else f"你这 {len(own)} 场共打了 {minutes:.0f} 分钟" if len(own) > 1
            else f"你这场打了 {minutes:.0f} 分钟")
    if summary.get("hands"):
        result = (f"算出成绩 {summary['hands']} 手，打出来 {summary['bb']:+g} 个大盲；"
                  f"扣掉运气 {summary['adjusted_bb_per_100']:+g} bb/100，"
                  f"结论：{summary['verdict']}")
    else:
        result = "没有算得出成绩的手"
    if all(short(item["recording"]["minutes"]) for item in own):
        result += "（太短，只作参考）"
    found = [line.split("（")[0].replace("他", "你")
             for item in own for line in item["problems"]][:TOP_PROBLEMS]
    return [f"{what}：{result}",
            ("要注意：" + "；".join(found)) if found else "没发现要你注意的问题"]


def sheet(results, day, totals=None, condition=None):
    """The day's review sheet (totals only) and its lines: three, and the
    table ``condition`` (``table_condition``) when given. ``totals``:
    {machine: ``luck_results.summarize`` of all its recordings so far}."""
    totals = totals or {}
    results = sorted(results, key=lambda item: (item["machine"], item["folder"]))
    text = [f"# 录像复盘 · {day}", ""]
    if condition:
        text += [condition, ""]
    if not results:
        text.append("没有新录像。")
    for item in results:
        facts = item["recording"]
        head = " · ".join(filter(None, (
            show(item["machine"]), item["folder"], when(facts["started"]),
            f"{facts['minutes']:g} 分钟" if facts["minutes"] else None,
            f"代码 {facts['code'][:7]}" if facts["code"] else None)))
        text += [f"## {head}", ""]
        if short(facts["minutes"]):
            text += ["太短，数字只作参考。", ""]
        text.append("要看的问题：" if item["problems"] else "没有要看的问题。")
        text += [f"- {line}" for line in item["problems"]]
        turns = item["advice"] or {}
        rate = item["speed"]["frames_per_second"]
        text += ["", "数字：" + " · ".join(filter(None, (
            f"读帧 {rate:g}/秒" if rate is not None else None,
            f"识别 {item['speed']['recognition_ms']} 毫秒/帧"
            if item["speed"]["recognition_ms"] is not None else None,
            f"牌局 {turns.get('hands', 0)} 手",
            f"轮到他 {turns.get('turns', 0)} 次、有建议 {turns.get('advised', 0)} 次",
            "每步都有建议的手 {}/{}".format(*turns["fully_advised"])
            if turns.get("fully_advised") else None,
            "能统计对手的手 {}/{}".format(*item["opponents_usable"]),
            f"卡顿超过 2 秒 {turns.get('stalls_over_2s', 0)} 次")))]
        passed = [tester(row["label"])
                  for row in (item["recognition"] or {}).get("rows", ())
                  if row["verdict"] == "通过"]
        if passed:
            text.append("识别达标：" + "、".join(passed))
        since = item.get("since_last")
        if since:
            text.append(f"和上次（{since['folder']}）比："
                        + ("；".join(since["moved"]) or "没有明显变化"))
        if item.get("results"):
            text += ["", "成绩（积分）："]
            text += [f"- {line}" for line in luck_results.plain_lines(
                item["results"], show(item["machine"]))]
        text.append("")
    for machine, summary in sorted(totals.items()):
        text += [f"## {show(machine)} 到今天为止的成绩", ""]
        text += [f"- {line}"
                 for line in luck_results.plain_lines(summary, show(machine))]
        text.append("")
    tail = [condition] if condition else []
    if not results:
        return "\n".join(text).rstrip() + "\n", ["没有新录像", "—", "—"] + tail
    worth = [item for item in results
             if not short(item["recording"]["minutes"])] or results
    machines = sorted({item["machine"] for item in results})
    # Each machine's problems on their own, so one's never reads as the other's.
    found = []
    for machine in machines:
        own = [line.split("（")[0] for item in worth if item["machine"] == machine
               for line in item["problems"]][:TOP_PROBLEMS]
        if own:
            found.append((f"{show(machine)}：" if len(machines) > 1 else "")
                         + "；".join(own))
    minutes = sum(item["recording"]["minutes"] or 0 for item in results)
    hands = sum((item["advice"] or {}).get("hands", 0) for item in results)
    usable = sum(item["opponents_usable"][0] for item in results)
    # Every recording's speed, even a fast one: the slow-computer work
    # follows it from day to day.
    speeds = "；".join(
        f"{show(item['machine']) + ' ' if len(machines) > 1 else ''}"
        f"{item['folder'].removesuffix('-live')} 读帧 "
        f"{item['speed']['frames_per_second']:g}/秒、识别 "
        f"{item['speed']['recognition_ms']} 毫秒/帧"
        for item in results if item["speed"]["frames_per_second"] is not None)
    lines = [f"复盘了 {'、'.join(map(show, machines))} 的 {len(results)} 场录像"
             f"（{minutes:.0f} 分钟，{hands} 手）" + (f"；{speeds}" if speeds else ""),
             ("问题：" + "。".join(found)) if found else "没有要看的问题",
             f"对手统计新加 {usable} 手能用的牌局" + "".join(
                 f"；{show(machine)} 累计 {summary['hands']} 手扣掉运气 "
                 f"{summary['adjusted_bb_per_100']:+g} bb/100（{summary['verdict']}）"
                 for machine, summary in sorted(totals.items())
                 if summary.get("hands"))]
    return "\n".join(text).rstrip() + "\n", lines + tail


def run(args):
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    ledger = read_lines(state / REVIEWED)
    done = {(item["log"], item["digest"]) for item in ledger}
    earlier = {}
    for item in sorted(ledger, key=lambda entry: entry.get("started") or ""):
        if not short(item.get("minutes")):
            earlier[item["machine"]] = item
    stored = read_lines(state / HANDS)
    kept = read_lines(state / RESULTS)
    ledger_lines = read_lines(state / DECISIONS)
    results = []
    for folder in sorted(args.recording, key=lambda path: Path(path).name):
        machine, name, digest = identify(folder, args.machine)
        if (f"{machine}-{name}", digest) in done and not args.again:
            print(f"{machine}/{name}：已经复盘过")
            continue
        result, lines, hands, decisions = review(folder, baseline, args.machine)
        entry = {"machine": machine, "folder": name, "log": result["log"],
                 "digest": digest, "started": result["recording"]["started"],
                 "minutes": result["recording"]["minutes"],
                 "code": result["recording"]["code"],
                 "reviewed_at": datetime.now(timezone.utc).strftime(
                     "%Y-%m-%dT%H:%M:%SZ"),
                 "numbers": numbers(result), "problems": result["problems"]}
        previous = earlier.get(machine)
        if previous and previous["log"] != result["log"] and not short(
                entry["minutes"]):
            result["since_last"] = {"folder": previous["folder"],
                                    "moved": change(previous["numbers"],
                                                    entry["numbers"])}
        if not short(entry["minutes"]):
            earlier[machine] = entry
        results.append(result)
        (out / f"{result['log']}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        ledger = [item for item in ledger if item["log"] != result["log"]] + [entry]
        stored = [line for line in stored if line["log"] != result["log"]] + lines
        kept = [line for line in kept if line["log"] != result["log"]] + hands
        ledger_lines = [line for line in ledger_lines
                        if line["log"] != result["log"]] + decisions
        print(f"{machine}/{name}：{len(result['problems'])} 个问题")
    write_lines(state / REVIEWED, ledger)
    write_lines(state / HANDS, stored)
    write_lines(state / RESULTS, kept)
    write_lines(state / DECISIONS, ledger_lines)
    day = args.day or datetime.now(los_angeles()).strftime("%Y-%m-%d")
    totals = machine_totals(kept, {item["machine"] for item in results})
    condition = table_condition(kept, {item["machine"] for item in ledger})
    text, lines = sheet(results, day, totals, condition)
    (out / SHEET).write_text(text, encoding="utf-8")
    (out / LINES).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    # The owner's own recordings (``--machine``): two lines for him at once.
    own = [item for item in sorted(results, key=lambda item: item["folder"])
           if args.machine and item["machine"] == args.machine]
    logs = {item["log"] for item in own}
    told = owner_lines(own, luck_results.summarize(
        [line for line in kept if line["log"] in logs]) if own else {})
    (out / OWNER).unlink(missing_ok=True)
    if told:
        (out / OWNER).write_text("\n".join(told) + "\n", encoding="utf-8")
        print("\n".join(told))
    return 0


def machine_totals(lines, machines):
    """{machine: summary of its result lines so far}."""
    return {machine: luck_results.summarize(
        [line for line in lines if line.get("machine") == machine])
        for machine in sorted(machines)}


def results_so_far(args):
    """Every machine's results so far, and all machines together: totals
    only, as JSON, and in plain lines."""
    lines = read_lines(Path(args.state) / RESULTS)
    machines = {line.get("machine") for line in lines}
    report = {"machines": machine_totals(lines, machines),
              "all": luck_results.summarize(lines)}
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    for machine, summary in report["machines"].items():
        print(f"{show(machine)}：" + "；".join(
            luck_results.plain_lines(summary, show(machine))))
    if not machines:
        print("还没有成绩")
    print(table_condition(lines))
    return 0


def population(args):
    """The AA population statistics: the base sample plus every reviewed
    recording, the testers' own seats left out."""
    state = Path(args.state)
    base = read_json(state / BASE)
    base_hands = read_lines((state / BASE).parent / base["hands"]) if base else []
    reviewed = read_lines(state / REVIEWED)
    logs = {item["log"] for item in reviewed}
    hands = base_hands + [line for line in read_lines(state / HANDS)
                          if line["log"] in logs]
    minutes = dict(base.get("minutes") or {})
    minutes.update({item["log"]: item["minutes"] for item in reviewed
                    if item.get("minutes")})
    report = pop.build(hands, set(base.get("hero_logs") or ()) | logs, minutes)
    report["reference_2009_7to9"] = pop.phh_reference(report)
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    ours = sum(source.get("counted", 0) for source in report["sources"]
               if source["log"] in logs)
    hours = (report["video_minutes"] or 0) / 60
    print(f"对手统计：共 {report['hands_counted']} 手能用（{hours:.1f} 小时录像），"
          f"其中同事录像 {ours} 手")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    go = commands.add_parser("run")
    go.add_argument("--recording", type=Path, action="append", default=[])
    go.add_argument("--state", type=Path, required=True)
    go.add_argument("--out", type=Path, required=True)
    go.add_argument("--baseline", type=Path, default=p30.DEFAULT_BASELINE)
    go.add_argument("--machine", help="when the folder has no upload.json "
                    "(the owner's own Mac recordings: peng)")
    go.add_argument("--day", help="the sheet's date (default: today in Los Angeles)")
    go.add_argument("--again", action="store_true")
    build = commands.add_parser("population")
    build.add_argument("--state", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    total = commands.add_parser("results")
    total.add_argument("--state", type=Path, required=True)
    total.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    return {"run": run, "population": population,
            "results": results_so_far}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
