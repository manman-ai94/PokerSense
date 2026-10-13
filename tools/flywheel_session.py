"""After a recorded session (飞轮第一期): its check-up sheet, the results
ledger, and the losses ranked across sessions.

    # One session (run on its own when a recording in the window stops):
    PYTHONPATH=src:. .venv/bin/python tools/flywheel_session.py report \\
        --recording <录像文件夹> [--recording ...] [--ledger <账本.jsonl>]
    # The spots that lost the most over the sessions so far:
    PYTHONPATH=src:. .venv/bin/python tools/flywheel_session.py rank \\
        [--root <录像目录>] [--since 20261013] [--commit <提交号前几位>] [--top 15]
    # The ledger added up (all sessions, and each code version apart):
    PYTHONPATH=src:. .venv/bin/python tools/flywheel_session.py ledger [--ledger ...]

``report`` reads the window's log of a recording (``frames.jsonl``, the
advice as it showed) with ``tools/aa_session_report.py`` and the decision
review of ``tools/aa_strategy_review.py`` and writes into
``<录像文件夹>/flywheel/``:

* ``hands.json``: every hand you were in with your result in big blinds of
  that hand's own level (``aa_stakes``: 1/2/4, 2/4/8 ... read from the
  table; a hand whose level was not read counts at the last level read, or
  1/2/4 when none was, and is counted as unsure), whether it was a bomb pot,
  and the spot where it was decided (your last turn: street, what you faced,
  how many opponents, the advice and its kind, what you did);
* ``summary.json`` and ``体检单.txt``: the code that played (``code`` on the
  log's first line), the levels, hands and decisions, how many got advice,
  stalls, results in big blinds per 100 hands with a 95% interval, normal
  hands and bomb pots apart, and the spots that lost the most;
* a line in the ledger (default ``PokerSense_private/flywheel/ledger.jsonl``;
  the recording's folder name is the label, a session reported again replaces
  its line).

``rank`` adds up ``hands.json`` of every recording under ``--root`` (default
``PokerSense_private/aa-mac-recordings``) by spot and lists the spots that
lost the most big blinds, with the hands to look at (recording and second in
the video). All of it is table points (积分), never money; the files stay in
the private data folder (other players' hands).
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.data_paths import private_root  # noqa: E402
from poker_engine.desktop.aa_solver_input import hand_facts  # noqa: E402
from poker_engine.desktop.aa_stakes import stakes_label  # noqa: E402
from tools.aa_session_report import AGGRESSIVE, HERO, session_report  # noqa: E402
from tools.aa_strategy_review import decisions as review_decisions  # noqa: E402

Z95 = 1.96
FOLDER = "flywheel"
TOP = 5                       # spots on the check-up sheet


def default_ledger():
    return private_root() / FOLDER / "ledger.jsonl"


def default_root():
    return private_root() / "aa-mac-recordings"


def load(path):
    """The log's rows; a last line cut short (still being written) is left out."""
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _advice(row):
    fields = row["fields"]
    return fields.get("solver_advice") or fields.get("solver_advice_v1") or {}


def by_hand(rows):
    """{hand id: rows}, in the order the hands were played (as the reports
    group them)."""
    hands = {}
    for row in rows:
        history = (row.get("fields") or {}).get("actions_v1")
        if history and row["fields"].get("scene_supported"):
            hands.setdefault(history["hand_id"], []).append(row)
    return hands


def hand_stakes(hands):
    """{hand id: stakes} as the window settles them hand after hand."""
    found, earlier = {}, None
    for hand_id, rows in hands.items():
        stakes = hand_facts(rows, earlier)["stakes"]
        found[hand_id] = stakes
        if stakes["source"] == "table":
            earlier = stakes
    return found


def facing(rows, turn, big_blind=None):
    """What your last turn faced, from the button and the price on it then
    (an opponent's bet is often logged in the same frame your turn shows up,
    so the frame number cannot tell before from after): with 让牌 on the
    button nothing; otherwise the bets and raises on that street before your
    answer, at least one when the price is more than the big blind (or after
    the flop at all), and whether one of them was all in."""
    start = next((row["processed"] for row in rows
                  if round(row["pts_seconds"], 1) == turn["pts"]), None)
    actions = rows[-1]["fields"]["actions_v1"]["actions"]
    mine = next((index for index, (frame, street, slot, *_) in enumerate(actions)
                 if str(slot) == HERO and street == turn["street"]
                 and start is not None and frame >= start), len(actions))
    raises = all_in = 0
    if turn.get("button") != "check":
        for frame, street, slot, kind, *_ in actions[:mine]:
            if street == turn["street"] and kind in AGGRESSIVE:
                raises += 1
                all_in += kind in ("all_in", "allin") and str(slot) != HERO
        price = number(turn.get("to_call"))
        if turn.get("button") == "all_in" or (
                turn["street"] != "preflop" and price) or (
                big_blind is not None and price is not None and price > big_blind):
            raises = max(raises, 1)
    if turn["street"] == "preflop":
        text = ("没人加注", "面对加注", "面对再加注")[min(raises, 2)]
    else:
        text = ("没人下注", "面对下注", "面对加注")[min(raises, 2)]
    return text + ("（有人全下）" if all_in else "")


def number(value):
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except ArithmeticError:
        return None


def spot(rows, turn, big_blind=None):
    """The spot a hand was decided in: your last turn."""
    last = turn["answers"][-1] if turn["answers"] else None
    opponents = turn["opponents"]
    return {"street": turn["street"], "facing": facing(rows, turn, big_blind),
            "opponents": opponents,
            "table": None if opponents is None else "单挑" if opponents == 1 else "多人",
            "advice": None if last is None else last["action"],
            "kind": None if last is None else last["kind"],
            "you_did": turn["you_did"], "followed": turn.get("followed"),
            "flags": turn["flags"]}


def spot_key(item):
    """Spots that count as the same in the ranking."""
    where = item["spot"]
    if where is None:
        return "没轮到你"
    return " · ".join(str(part) for part in (
        {"preflop": "翻前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}.get(
            where["street"], where["street"]),
        where["table"] or "人数未读", where["facing"], f"你{plain(where['you_did'])}"))


def plain(action):
    return {"fold": "弃牌", "check": "让牌", "call": "跟注", "bet": "下注",
            "raise": "加注", "all_in": "全下", None: "动作未读"}.get(action, action)


def session_hands(name, rows):
    """Every hand you were in with a result: big blinds at its own level and
    the spot it was decided in."""
    rows = [row for row in rows if row.get("fields")]
    report = session_report([(name, rows)])
    grouped = by_hand(rows)
    stakes = hand_stakes(grouped)
    turns = {}
    for turn in review_decisions(name, rows, [_advice(row) for row in rows]):
        turns.setdefault(turn["hand_id"], []).append(turn)
    hands = []
    for hand in report["hands"]:
        if hand["your_chips"] is None:
            continue
        level = stakes[hand["hand_id"]]
        mine = turns.get(hand["hand_id"]) or []
        hands.append({
            "log": name, "hand_id": hand["hand_id"],
            "video_seconds": hand["video_seconds"], "your_cards": hand["your_cards"],
            "players": hand["players"], "stakes": stakes_label(level),
            "stakes_sure": level["source"] != "unsure",
            "chips": hand["your_chips"],
            "bb": round(float(Decimal(str(hand["your_chips"]))
                              / Decimal(level["big_blind"])), 2),
            "bomb_pot": bool(hand.get("bomb_pot")),
            "spot": spot(grouped[hand["hand_id"]], mine[-1],
                         number(level["big_blind"])) if mine else None,
            "misreads": misreads(hand),
            "turn_seconds": [turn["video_seconds"] for turn in mine
                             if turn["video_seconds"] is not None],
            "end_seconds": None if hand["video_seconds"] is None else round(
                hand["video_seconds"] + hand["end_pts"] - hand["start_pts"], 2)})
    return report["summary"], hands


MISREADS = (("your_cards_readings", lambda n: n > 1, "你的牌认成两种"),
            ("board_slots_with_two_readings", bool, "公共牌认成两种"),
            ("unexplained_pot_rises", bool, "底池涨了没看到谁下注"),
            ("unrecorded_folds", bool, "有人弃牌没记上"),
            ("skipped_seats", bool, "行动顺序跳过了座位"))


def misreads(hand):
    """What the screen reading got wrong in this hand (``aa_session_report``)."""
    return [label for key, wrong, label in MISREADS if wrong(hand.get(key) or 0)]


def result(values):
    """Big blinds per 100 hands with a 95% interval (normal approximation)."""
    count = len(values)
    if not count:
        return {"hands": 0, "bb": 0, "bb_per_100": None, "ci95": None}
    mean = sum(values) / count
    if count < 2:
        return {"hands": 1, "bb": round(sum(values), 2),
                "bb_per_100": round(100 * mean, 1), "ci95": None}
    spread = math.sqrt(sum((v - mean) ** 2 for v in values) / (count - 1))
    half = Z95 * spread / math.sqrt(count)
    return {"hands": count, "bb": round(sum(values), 2),
            "bb_per_100": round(100 * mean, 1),
            "ci95": [round(100 * (mean - half), 1), round(100 * (mean + half), 1)]}


def ranking(hands, top=None):
    """Spots by the big blinds they lost, the most first."""
    groups = {}
    for hand in hands:
        groups.setdefault(spot_key(hand), []).append(hand)
    ranked = []
    for key, items in groups.items():
        lost = [hand for hand in items if hand["bb"] < 0]
        kinds = Counter(hand["spot"]["kind"] for hand in items if hand["spot"])
        followed = [hand["spot"]["followed"] for hand in items
                    if hand["spot"] and hand["spot"]["followed"] is not None]
        ranked.append({
            "spot": key, "hands": len(items), "net_bb": round(sum(
                hand["bb"] for hand in items), 2),
            "lost_bb": round(sum(hand["bb"] for hand in lost), 2),
            "losing_hands": len(lost),
            "followed": sum(followed), "followed_of": len(followed),
            "advice_kinds": dict(kinds.most_common()),
            "worst": [{key: hand[key] for key in (
                "log", "hand_id", "video_seconds", "your_cards", "stakes", "bb")}
                | {"advice": hand["spot"] and hand["spot"]["advice"]}
                for hand in sorted(lost, key=lambda hand: hand["bb"])[:3]]})
    ranked.sort(key=lambda group: (group["lost_bb"], group["net_bb"]))
    return ranked[:top] if top else ranked


def session_summary(name, code, summary, hands):
    normal = [hand["bb"] for hand in hands if not hand["bomb_pot"]]
    bombs = [hand["bb"] for hand in hands if hand["bomb_pot"]]
    fully = summary["fully_advised"]
    return {"schema_version": 1, "label": name, "code": code,
            "stakes": dict(Counter(hand["stakes"] for hand in hands).most_common()),
            "stakes_unsure_hands": sum(not hand["stakes_sure"] for hand in hands),
            "hands": summary["hands"], "your_hands": len(hands),
            "decisions": summary["your_decisions"], "advised": summary["advised"],
            "fully_advised": [fully["advised"], fully["hands"]],
            "followed": [summary["followed_advice"],
                         summary["advised_and_action_seen"]],
            "stalls_over_2s": summary["stalls_over_2s"],
            "no_advice_causes": summary["no_advice_causes"],
            "all": result(normal + bombs), "normal": result(normal),
            "bomb_pot": result(bombs),
            "lost_most": ranking(hands, TOP)}


def sheet(item):
    """The check-up sheet in plain lines."""
    code = item["code"] or {}
    commit = (code.get("commit") or "未知")[:7]
    levels = "、".join(f"{label} {count} 手" for label, count in item["stakes"].items())
    text = [f"{item['label']} 体检单（代码 {code.get('version', '?')} · {commit}"
            + ("，有未提交的改动" if code.get("dirty") else "") + "）",
            "级别：" + (levels or "没读到")
            + (f"（其中 {item['stakes_unsure_hands']} 手没读到级别）"
               if item["stakes_unsure_hands"] else ""),
            f"牌局 {item['hands']} 手，你在局里 {item['your_hands']} 手；"
            f"你的决策 {item['decisions']} 次，有建议 {item['advised']} 次；"
            f"每一步都有建议的手 {item['fully_advised'][0]}/{item['fully_advised'][1]}；"
            f"照建议做 {item['followed'][0]}/{item['followed'][1]}；"
            f"卡顿超过 2 秒 {item['stalls_over_2s']} 次"]
    for key, label in (("all", "全部"), ("normal", "普通局"), ("bomb_pot", "暴击局")):
        part = item[key]
        if not part["hands"] or key != "all" and not item["bomb_pot"]["hands"]:
            continue                # no bomb pots: "all" says it already
        line = (f"{label}：{part['hands']} 手，{part['bb']:+} 个大盲的积分"
                f"（每百手 {part['bb_per_100']:+}")
        if part["ci95"]:
            line += f"，95% 区间 {part['ci95'][0]:+} 到 {part['ci95'][1]:+}"
        text.append(line + "）")
    if item["lost_most"]:
        text.append("输得最多的局面：")
        for rank, group in enumerate(item["lost_most"], 1):
            if group["lost_bb"] >= 0:
                break
            worst = "；".join(f"{hand['video_seconds'] or '?'} 秒 {hand['your_cards']} "
                             f"{hand['bb']:+}" for hand in group["worst"])
            text.append(f"  {rank}. {group['spot']}：输的 {group['losing_hands']} 手共 "
                        f"{group['lost_bb']} 个大盲（这类共 {group['hands']} 手，净 "
                        f"{group['net_bb']:+}；照建议 {group['followed']}/"
                        f"{group['followed_of']}）看录像：{worst}")
    look = item.get("to_look_at")
    if look and look["hands"]:
        text.append(f"要看的手 {look['hands']} 手（输 {LOOK_LOSS} 个大盲以上或认错），"
                    f"截图 {look['pictures']} 张在 flywheel/frames/，"
                    "文件名里 turn 是你决策时、end 是这手结束时的画面")
    if look and look["misreads"]:
        counts = look["misreads"].items()
        text.append("认错：" + "、".join(f"{label} {count} 手" for label, count in counts))
    return text


def code_of(folder, rows):
    first = next((row["code"] for row in rows[:1] if "code" in row), None)
    if first is None and (folder / "recording.json").exists():
        meta = json.loads((folder / "recording.json").read_text(encoding="utf-8"))
        first = meta.get("code")
    return first


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


# -- the pictures of the hands to look at ------------------------------------------

LOOK_LOSS = 20                # big blinds lost: a hand worth a look
LOOK_HANDS = 30               # at most this many hands get pictures
PICTURE_WIDTH = 360           # pixels: the phone strip, made small


def to_look_at(hands):
    """The hands that lost the most or were misread, the worst first."""
    flagged = [hand for hand in hands if hand["bb"] <= -LOOK_LOSS or hand["misreads"]]
    return sorted(flagged, key=lambda hand: hand["bb"])[:LOOK_HANDS]


def segments_of(folder):
    """[(start seconds, file)] of a recording, oldest first."""
    index = folder / "segments.csv"
    if not index.exists():
        return []
    found = []
    for line in index.read_text(encoding="utf-8").splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and (folder / parts[0]).exists():
            found.append((float(parts[1]), folder / parts[0]))
    return sorted(found)


def pictures(folder, hands, out, *, opener=None):
    """Cut the moments of each hand to look at (your turns and the end of the
    hand, where shown cards are) from the recording as small pictures in
    ``out``; each hand gets ``pictures`` (paths relative to ``out``'s parent).
    Nothing leaves the computer; without the video or OpenCV, none are cut."""
    segments = segments_of(folder)
    if not segments:
        return 0
    try:
        import cv2
    except ImportError:
        return 0
    opener = opener or cv2.VideoCapture
    meta = folder / "recording.json"
    strip = (json.loads(meta.read_text(encoding="utf-8")).get("strip")
             if meta.exists() else None)
    wanted = []
    for hand in hands:
        moments = [("turn", seconds) for seconds in hand["turn_seconds"]]
        if hand["end_seconds"] is not None:
            moments.append(("end", hand["end_seconds"]))
        for label, seconds in moments:
            wanted.append((seconds, hand, label))
    out.mkdir(parents=True, exist_ok=True)
    made, current, capture = 0, None, None
    for seconds, hand, label in sorted(wanted, key=lambda item: item[0]):
        start, path = max(((s, p) for s, p in segments if s <= seconds),
                          default=segments[0])
        if path != current:
            if capture is not None:
                capture.release()
            capture, current = opener(str(path)), path
        capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds - start) * 1000)
        ok, image = capture.read()
        if not ok or image is None:
            continue
        if strip:
            x0, y0, x1, y1 = strip
            image = image[y0:y1, x0:x1]
        height, width = image.shape[:2]
        image = cv2.resize(image, (PICTURE_WIDTH,
                                   max(1, round(height * PICTURE_WIDTH / width))))
        name = f"{hand['hand_id']}-{label}-{seconds:.1f}s.jpg"
        # Encoded here and written by Python: OpenCV's own writer cannot
        # take every path on Windows (a user folder with Chinese in it).
        ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            (out / name).write_bytes(data.tobytes())
            hand.setdefault("pictures", []).append(f"{out.name}/{name}")
            made += 1
    if capture is not None:
        capture.release()
    return made


def report(folder, ledger_path, *, opener=None):
    folder = Path(folder)
    rows = load(folder / "frames.jsonl")
    summary, hands = session_hands(folder.name, rows)
    item = session_summary(folder.name, code_of(folder, rows), summary, hands)
    out = folder / FOLDER
    out.mkdir(exist_ok=True)
    look = to_look_at(hands)
    made = pictures(folder, look, out / "frames", opener=opener)
    item["to_look_at"] = {
        "hands": len(look), "pictures": made,
        "misread_hands": sum(bool(hand["misreads"]) for hand in hands),
        "misreads": dict(Counter(label for hand in hands
                                 for label in hand["misreads"]).most_common())}
    write_json(out / "hands.json", hands)
    write_json(out / "summary.json", item)
    text = sheet(item)
    (out / "体检单.txt").write_text("\n".join(text) + "\n", encoding="utf-8")
    if ledger_path is not None:
        add_to_ledger(ledger_path, item, hands)
    return text


# -- the ledger -----------------------------------------------------------------

def ledger_row(item, hands):
    """One session in the ledger: the sums its totals are added up from."""
    row = {"label": item["label"], "code": item["code"], "stakes": item["stakes"],
           "decisions": item["decisions"], "advised": item["advised"],
           "fully_advised": item["fully_advised"], "followed": item["followed"],
           "stalls_over_2s": item["stalls_over_2s"]}
    for key, bomb in (("normal", False), ("bomb_pot", True)):
        values = [hand["bb"] for hand in hands if hand["bomb_pot"] is bomb]
        row[key] = {"hands": len(values), "bb": round(sum(values), 2),
                    "bb_squared": round(sum(v * v for v in values), 2)}
    return row


def read_ledger(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def add_to_ledger(path, item, hands):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [row for row in read_ledger(path) if row["label"] != item["label"]]
    rows.append(ledger_row(item, hands))
    rows.sort(key=lambda row: row["label"])
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                            for row in rows), encoding="utf-8")


def from_sums(hands, total, squares):
    """``result`` from the sums the ledger keeps."""
    if not hands:
        return {"hands": 0, "bb": 0, "bb_per_100": None, "ci95": None}
    mean = total / hands
    out = {"hands": hands, "bb": round(total, 2), "bb_per_100": round(100 * mean, 1),
           "ci95": None}
    if hands > 1:
        spread = math.sqrt(max(0.0, (squares - hands * mean * mean) / (hands - 1)))
        half = Z95 * spread / math.sqrt(hands)
        out["ci95"] = [round(100 * (mean - half), 1), round(100 * (mean + half), 1)]
    return out


def totals(rows):
    """The sessions added up: all, and each code version apart."""
    def add(group):
        sums = Counter()
        for row in group:
            for key in ("normal", "bomb_pot"):
                for part in ("hands", "bb", "bb_squared"):
                    sums[f"{key}.{part}"] += row[key][part]
        return {key: from_sums(sums[f"{key}.hands"], sums[f"{key}.bb"],
                               sums[f"{key}.bb_squared"])
                for key in ("normal", "bomb_pot")} | {
            "all": from_sums(sums["normal.hands"] + sums["bomb_pot.hands"],
                             sums["normal.bb"] + sums["bomb_pot.bb"],
                             sums["normal.bb_squared"] + sums["bomb_pot.bb_squared"]),
            "sessions": len(group)}
    versions = {}
    for row in rows:
        commit = ((row.get("code") or {}).get("commit") or "未知")[:7]
        versions.setdefault(commit, []).append(row)
    return {"all": add(rows),
            "by_code": {commit: add(group) for commit, group in versions.items()}}


# -- the ranking over sessions ----------------------------------------------------

def collect(root, since=None, commit=None):
    """``hands.json`` of the recordings under ``root``."""
    hands, sessions = [], []
    for path in sorted(Path(root).glob(f"*/{FOLDER}/hands.json")):
        folder = path.parent.parent
        if since and folder.name[:len(since)] < since:
            continue
        summary = path.parent / "summary.json"
        code = (json.loads(summary.read_text(encoding="utf-8")).get("code")
                if summary.exists() else None) or {}
        if commit and not (code.get("commit") or "").startswith(commit):
            continue
        sessions.append(folder.name)
        hands += json.loads(path.read_text(encoding="utf-8"))
    return sessions, hands


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("report")
    one.add_argument("--recording", type=Path, action="append", required=True)
    one.add_argument("--ledger", type=Path)
    one.add_argument("--no-ledger", action="store_true")
    many = commands.add_parser("rank")
    many.add_argument("--root", type=Path)
    many.add_argument("--since")
    many.add_argument("--commit")
    many.add_argument("--top", type=int, default=15)
    many.add_argument("--out", type=Path)
    book = commands.add_parser("ledger")
    book.add_argument("--ledger", type=Path)
    args = parser.parse_args(argv)
    if args.command == "report":
        if hasattr(os, "nice"):
            os.nice(10)             # runs beside the window: stay out of its way
        ledger_path = None if args.no_ledger else (args.ledger or default_ledger())
        for folder in args.recording:
            print("\n".join(report(folder, ledger_path)))
        return 0
    if args.command == "rank":
        sessions, hands = collect(args.root or default_root(), args.since, args.commit)
        ranked = ranking(hands, args.top)
        if args.out:
            write_json(args.out, {"sessions": sessions, "hands": len(hands),
                                  "ranking": ranked})
        print(f"{len(sessions)} 场、{len(hands)} 手（大盲的积分，按各手自己的级别换算）")
        for rank, group in enumerate(ranked, 1):
            print(f"{rank}. {group['spot']}：输的 {group['losing_hands']} 手共 "
                  f"{group['lost_bb']}，这类 {group['hands']} 手净 {group['net_bb']:+}")
        return 0
    print(json.dumps(totals(read_ledger(args.ledger or default_ledger())),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
