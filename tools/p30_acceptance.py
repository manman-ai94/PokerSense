"""Acceptance of a second seat's phone picture (first: 杜's Huawei P30).

Before a new phone goes to a table, a short capture-card recording of it is
compared with the Samsung S25 Ultra + UGREEN baseline in one command:

1. Phone strip: where the lit phone picture sits in the 1920x1080 frame,
   against the Samsung strip (columns 711-1208) that recognition is
   calibrated on, and how often the window's picture check sees a phone.
2. Real-time fields: the recording is played at recorded pace through the
   live session (``tools/measure_aa_realtime.py``) and each field's coverage
   is set beside the baseline's.
3. Seat states: every third frame read offline (``tools/check_aa_seat_states.py``);
   when the strip is elsewhere, read a second time on the strip found.

Pass lines: every coverage at least 90% of the baseline's; on your turn the
button and the amount to call at least 95% of the baseline's; the strip
within 3 columns of the Samsung one. A spectating recording shows no hero
cards or buttons, so those lines stay unmeasured and the verdict cannot be
a pass. Coverage is not accuracy: a pass means "read as often as on the
Samsung", not "read right".

    PYTHONPATH=src:. .venv/bin/python tools/p30_acceptance.py run \\
        --video <recording folder> --out <new folder> [--frames <frames.jsonl>]

    # refresh the baseline from measured logs (and seat-state check output)
    PYTHONPATH=src:. .venv/bin/python tools/p30_acceptance.py baseline \\
        --frames <frames.jsonl[.gz]> [...] [--seat-states <check output.json> ...] \\
        --label <where the numbers come from> --out <baseline.json>
"""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import statistics

DEFAULT_BASELINE = Path("configs/acceptance/second_seat_baseline_v1.json")
SAMSUNG_STRIP = (711, 1209)        # half-open columns of the S25 Ultra picture
STRIP_TOLERANCE = 3                # columns
RELATIVE_LINE = 0.90               # of the baseline's coverage
TURN_LINE = 0.95                   # of the baseline's, on your turn
MIN_TURN_FRAMES = 50               # fewer frames on your turn: not measured
BAR_DARK = 16                      # as aa_recorder: a black bar's brightest pixel
HERO = "4"
SLOTS = tuple(str(slot) for slot in range(8))
SEATED = ("active", "folded", "waiting")
KNOWN = (*SEATED, "all_in", "empty")

# key, label, measured over
FIELDS = (
    ("table", "画面认作牌桌", "全部帧"),
    ("pot", "底池", "牌桌帧"),
    ("street", "街道", "牌桌帧"),
    ("board", "公共牌（张数合理）", "有公共牌的牌桌帧"),
    ("stacks", "座位筹码", "牌桌帧里有人的座位"),
    ("dealer", "庄位按钮", "牌桌帧"),
    ("actor", "当前行动者", "牌桌帧"),
    ("seats", "8 座状态全确定", "牌桌帧"),
    ("hero_cards", "你的手牌", "你在局的牌桌帧"),
)
TURN_FIELDS = (
    ("hero_button", "轮到你：按钮读出", "你在行动且有手牌的帧"),
    ("call_amount", "轮到你：跟注额读出", "按钮可见的帧"),
)
SEAT_FIELDS = (
    ("all_known_supported", "离线：8 座全确定（牌桌帧）"),
    ("all_known_while_acting", "离线：8 座全确定（有人在行动）"),
)


def read_frames(path):
    """Rows of a session frame log (``frames.jsonl``, or ``.gz``)."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _share(hits, total):
    return {"value": round(hits / total, 4) if total else None, "n": total}


def field_coverage(rows):
    """Coverage of each field over the frames it applies to."""
    fields = [row["fields"] for row in rows]
    table = [f for f in fields if f.get("scene_supported") is True]
    boards = ([c for c in f.get("board") or () if c] for f in table)
    with_board = [cards for cards in boards if cards]
    seats = [(f, slot) for f in table for slot in SLOTS
             if (f.get("participants") or {}).get(slot) in SEATED]
    in_hand = [f for f in table
               if (f.get("participants") or {}).get(HERO) in ("active", "all_in")]
    with_cards = [f for f in table if len([c for c in f.get("hero") or () if c]) == 2]
    acting = [f for f in with_cards if f.get("actor") == int(HERO)]
    turn = [f for f in fields if (f.get("hero_controls") or {}).get("visible")]
    return {
        "table": _share(len(table), len(fields)),
        "pot": _share(sum(f.get("pot") is not None for f in table), len(table)),
        "street": _share(sum(f.get("street") is not None for f in table), len(table)),
        "board": _share(sum(len(cards) >= 3 for cards in with_board), len(with_board)),
        "stacks": _share(sum((f.get("stacks") or {}).get(slot) is not None
                             for f, slot in seats), len(seats)),
        "dealer": _share(sum(isinstance(f.get("dealer"), int) for f in table),
                         len(table)),
        "actor": _share(sum(isinstance(f.get("actor"), int) for f in table),
                        len(table)),
        "seats": _share(sum(all((f.get("participants") or {}).get(slot) in KNOWN
                                for slot in SLOTS) for f in table), len(table)),
        "hero_cards": _share(sum(len([c for c in f.get("hero") or () if c]) == 2
                                 for f in in_hand), len(in_hand)),
        "hero_button": _share(sum((f.get("hero_controls") or {}).get("button")
                                  is not None for f in acting), len(acting)),
        "call_amount": _share(sum(f["hero_controls"].get("call_amount") is not None
                                  for f in turn), len(turn)),
        "spectating": not with_cards,
    }


def find_strip(frame):
    """Half-open columns ``(left, right)`` of the widest lit run in a
    1920x1080 frame (the phone picture between black bars), or None."""
    import numpy as np

    gray = frame.mean(axis=2) if frame.ndim == 3 else frame
    lit = np.percentile(gray[::4], 99, axis=0) > BAR_DARK
    best, start = None, None
    for column, on in enumerate([*lit, False]):
        if on and start is None:
            start = column
        elif not on and start is not None:
            if best is None or column - start > best[1] - best[0]:
                best = (start, column)
            start = None
    return best


def strip_check(frames):
    """Where the phone strip sits over sampled full frames, against Samsung."""
    from poker_engine.desktop.aa_recorder import picture

    kinds, strips = Counter(), []
    for frame in frames:
        kinds[picture(frame)] += 1
        strip = find_strip(frame) if frame.shape[:2] == (1080, 1920) else None
        if strip is not None and strip[1] - strip[0] >= 200:
            strips.append(strip)
    if not strips:
        return {"frames": sum(kinds.values()), "picture": dict(kinds),
                "strip": None, "matches_samsung": False}
    left = int(statistics.median(s[0] for s in strips))
    right = int(statistics.median(s[1] for s in strips))
    steady = sum(abs(s[0] - left) <= STRIP_TOLERANCE
                 and abs(s[1] - right) <= STRIP_TOLERANCE for s in strips)
    return {"frames": sum(kinds.values()), "picture": dict(kinds),
            "lit_frames": len(strips), "strip": [left, right],
            "width": right - left, "steady": round(steady / len(strips), 4),
            "matches_samsung": (abs(left - SAMSUNG_STRIP[0]) <= STRIP_TOLERANCE
                                and abs(right - SAMSUNG_STRIP[1]) <= STRIP_TOLERANCE)}


def sample_frames(video, every=2.0, exclude=()):
    """Full frames every ``every`` seconds of a recording (file or folder)."""
    import cv2

    from poker_engine.desktop.aa_video_source import video_segments

    due = 0.0
    for segment in video_segments(video):
        capture = cv2.VideoCapture(str(segment.path))
        while capture.grab():
            pts = segment.start + capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if pts < due or any(a <= pts < b for a, b in exclude):
                continue
            ok, frame = capture.retrieve()
            if ok:
                yield frame
            due = pts + every
        capture.release()


def _verdict(value, line):
    if value is None:
        return "量不了"
    return "通过" if value >= line else "不通过"


def compare(measured, baseline, seat_states=None, strip=None):
    """Rows of the acceptance table and the overall verdict."""
    rows = []
    base = baseline["realtime"]["metrics"]
    for key, label, over in FIELDS:
        got = measured[key]["value"]
        if key == "hero_cards" and measured["spectating"]:
            rows.append({"key": key, "label": label, "over": over, "value": None,
                         "baseline": base.get(key), "line": None,
                         "verdict": "量不了", "note": "观战录像看不到你的手牌"})
            continue
        line = None if base.get(key) is None else round(RELATIVE_LINE * base[key], 4)
        rows.append({"key": key, "label": label, "over": over, "value": got,
                     "n": measured[key]["n"], "baseline": base.get(key),
                     "line": line, "verdict": (_verdict(got, line) if line is not None
                                               else "没有基准")})
    for key, label, over in TURN_FIELDS:
        got, n = measured[key]["value"], measured[key]["n"]
        note = None
        line = None if base.get(key) is None else round(TURN_LINE * base[key], 4)
        if n < MIN_TURN_FRAMES:
            got, note = None, (f"只有 {n} 帧轮到你" if n else
                               "录像里没有轮到你的时候（观战看不到你的按钮）")
        rows.append({"key": key, "label": label, "over": over, "value": got, "n": n,
                     "baseline": base.get(key), "line": line,
                     "verdict": (_verdict(got, line) if line is not None
                                 else "没有基准"), "note": note})
    seat_base = (baseline.get("seat_states") or {}).get("metrics") or {}
    for key, label in SEAT_FIELDS if seat_states else ():
        got, ref = seat_states.get(key), seat_base.get(key)
        line = None if ref is None else round(RELATIVE_LINE * ref, 4)
        rows.append({"key": key, "label": label, "over": "每 3 帧", "value": got,
                     "baseline": ref, "line": line,
                     "verdict": _verdict(got, line) if line is not None else "没有基准"})
    if strip is not None:
        found = strip.get("strip")
        rows.append({"key": "strip", "label": "手机画面位置（列）",
                     "over": f"{strip['frames']} 张抽样",
                     "value": None if found is None else f"{found[0]}–{found[1] - 1}",
                     "baseline": f"{SAMSUNG_STRIP[0]}–{SAMSUNG_STRIP[1] - 1}",
                     "line": f"差 ≤ {STRIP_TOLERANCE} 列",
                     "verdict": ("量不了" if found is None else
                                 "通过" if strip["matches_samsung"] else "不通过")})
    verdicts = Counter(row["verdict"] for row in rows)
    overall = ("不通过" if verdicts["不通过"] else
               "通过" if set(verdicts) <= {"通过"} else "没量全")
    return {"rows": rows, "overall": overall, "counts": dict(verdicts)}


def _pct(value):
    return "—" if value is None else (f"{value:.1%}" if isinstance(value, float)
                                      else str(value))


def markdown(result, baseline):
    lines = [f"# 第二台机器画面验收：{result['overall']}", "",
             f"基准：{baseline['realtime'].get('label', '')}", "",
             "| 项目 | 分母 | 这次 | 基准 | 过线 | 结论 | 备注 |",
             "|---|---|---|---|---|---|---|"]
    for row in result["rows"]:
        cells = (row["label"], row["over"], _pct(row["value"]), _pct(row["baseline"]),
                 _pct(row["line"]), row["verdict"], row.get("note") or "")
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "覆盖率只说明读出来的频率和三星一样，不说明读得对；"
              "上桌前仍要抽几手看过。"]
    return "\n".join(lines) + "\n"


def build_baseline(frame_logs, seat_outputs=(), label=""):
    rows = [row for path in frame_logs for row in read_frames(path)]
    coverage = field_coverage(rows)
    metrics = {key: coverage[key]["value"] for key, _, _ in FIELDS + TURN_FIELDS}
    baseline = {"schema": "second-seat-baseline-v1",
                "realtime": {"label": label, "frames": len(rows),
                             "sources": [Path(p).name for p in frame_logs],
                             "metrics": metrics,
                             "n": {key: coverage[key]["n"] for key in metrics}}}
    if seat_outputs:
        reports = [json.loads(Path(p).read_text(encoding="utf-8"))["coverage"]
                   for p in seat_outputs]
        baseline["seat_states"] = {
            "sources": [Path(p).name for p in seat_outputs],
            "metrics": {key: round(statistics.mean(r[key] for r in reports), 4)
                        for key, _ in SEAT_FIELDS}}
    return baseline


def run(args):
    from tools import check_aa_seat_states, measure_aa_realtime
    from poker_engine.desktop.aa_video_source import parse_windows

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    exclude = parse_windows(args.exclude)
    args.out.mkdir(parents=True, exist_ok=False)
    report = {"video": str(args.video)}

    strip = strip_check(sample_frames(args.video, exclude=exclude))
    report["strip"] = strip
    print("手机画面位置：", json.dumps(strip, ensure_ascii=False), flush=True)

    frame_log = args.frames
    if frame_log is None:
        frame_log = args.out / "frames.jsonl"
        report["measure_run"] = measure_aa_realtime.run(
            args.profile, args.video, frame_log, exclude=args.exclude)
    report["frames"] = str(frame_log)
    measured = field_coverage(read_frames(frame_log))
    report["realtime"] = measured

    seat_states = None
    if not args.skip_seat_check:
        rows = check_aa_seat_states.read_states(args.video, exclude=exclude,
                                                profile=str(args.profile))
        seat_states = check_aa_seat_states.coverage(rows)
        report["seat_states"] = seat_states
        found = strip.get("strip")
        if found and not strip["matches_samsung"]:
            # what recognition would read once cropped at the strip found
            report["seat_states_on_found_strip"] = check_aa_seat_states.coverage(
                check_aa_seat_states.read_states(args.video, exclude=exclude,
                                                 profile=str(args.profile),
                                                 crop=tuple(found)))

    result = compare(measured, baseline, seat_states, strip)
    report["acceptance"] = result
    (args.out / "acceptance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    text = markdown(result, baseline)
    if "seat_states_on_found_strip" in report:
        again = report["seat_states_on_found_strip"]
        text += ("\n按找到的位置裁切后（只是试算，没改识别）：8 座全确定 "
                 f"{_pct(again['all_known_supported'])}（牌桌帧）、"
                 f"{_pct(again['all_known_while_acting'])}（有人在行动）。\n")
    (args.out / "验收表.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["overall"] == "通过" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    go = commands.add_parser("run", help="check one recording against the baseline")
    go.add_argument("--video", type=Path, required=True)
    go.add_argument("--out", type=Path, required=True)
    go.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    go.add_argument("--frames", type=Path,
                    help="use this measured frame log instead of measuring again")
    go.add_argument("--profile", type=Path,
                    default=Path("configs/reproduction/aa8_candidate_v2/factory.json"))
    go.add_argument("--exclude", action="append", default=[], metavar="START-END")
    go.add_argument("--skip-seat-check", action="store_true")
    base = commands.add_parser("baseline", help="baseline numbers from measured logs")
    base.add_argument("--frames", type=Path, nargs="+", required=True)
    base.add_argument("--seat-states", type=Path, nargs="*", default=[])
    base.add_argument("--label", default="")
    base.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "baseline":
        baseline = build_baseline(args.frames, args.seat_states, args.label)
        args.out.write_text(json.dumps(baseline, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
        print(json.dumps(baseline, ensure_ascii=False, indent=1))
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
