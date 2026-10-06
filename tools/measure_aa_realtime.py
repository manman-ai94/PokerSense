"""Measure the AA real-time pipeline on a recording played at recorded pace.

Runs the observation page's session, reader and table math with a recording
standing in for the capture card, logs every processed frame, then summarizes
timing, dropped frames, field coverage and agreement with reviewed checkpoint
labels. Agreement on development checkpoints is not independent acceptance.

    PYTHONPATH=src:. .venv/bin/python tools/measure_aa_realtime.py \\
        --video <recording file or segment folder> --out <dir> \\
        [--exclude 300-820] [--gold <checkpoint json>] [--max-seconds 1800]
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time

from poker_engine.desktop.aa_math import KNOWN_STATES, AATableMath
from poker_engine.desktop.aa_reader import AA8Reader
from poker_engine.desktop.aa_session import AARecognitionSession
from poker_engine.desktop.aa_sources import source_factory
from poker_engine.desktop.aa_video_source import parse_windows

DEFAULT_PROFILE = "configs/reproduction/aa8_candidate_v2/factory.json"
SLOTS = tuple(str(slot) for slot in range(8))


def run(profile, video, frame_log, *, start=0.0, exclude=(), speed=1.0,
        max_seconds=None, poll=1.0):
    """Play the recording through a real session until it ends or times out."""
    session = AARecognitionSession(
        source_factory(profile, replay_video=video, replay_video_start=start,
                       replay_video_exclude=parse_windows(exclude),
                       replay_video_speed=speed),
        lambda: AA8Reader(profile), interval_seconds=0.03,
        table_math=AATableMath().compute, frame_log=frame_log)
    began = time.monotonic()
    session.start({"mode": "video-replay"})
    try:
        while True:
            time.sleep(poll)
            status = session.snapshot()
            if status["status"] in ("ENDED", "ERROR"):
                return {"status": status["status"], "error": status.get("error"),
                        "wall_seconds": time.monotonic() - began}
            if max_seconds is not None and time.monotonic() - began >= max_seconds:
                return {"status": "TIME_LIMIT", "error": None,
                        "wall_seconds": time.monotonic() - began}
    finally:
        session.stop()


def percentiles(values):
    if not values:
        return None
    ordered = sorted(values)

    def at(q):
        return round(ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)], 1)

    return {"n": len(ordered), "p50": at(0.50), "p95": at(0.95),
            "max": round(ordered[-1], 1)}


def _known_cards(cards):
    return [card for card in cards or () if card]


def _fraction(count, total):
    return None if not total else round(count / total, 4)


def summarize(rows):
    """Timing, drops and coverage over every processed frame."""
    timing = [row["timing"] for row in rows]
    age = [(t["published_at"] - t["host_source_received_at"]) * 1000
           for t in timing if t.get("host_source_received_at") is not None]
    arrived = max(row["source_frame"] for row in rows) + 1 if rows else 0
    video = [row["source_video_pts"] for row in rows
             if row.get("source_video_pts") is not None]
    span = (timing[-1]["published_at"] - timing[0]["published_at"]) if rows else 0
    fields = [row["fields"] for row in rows]
    total = len(fields)
    hero_turn = [f for f in fields if (f["hero_controls"] or {}).get("visible")]
    coverage = {
        "hero_cards": sum(len(_known_cards(f["hero"])) == 2 for f in fields),
        "pot": sum(f["pot"] is not None for f in fields),
        "street": sum(f["street"] is not None for f in fields),
        "actor": sum(isinstance(f["actor"], int) for f in fields),
        "all_participants": sum(
            all(f["participants"].get(slot) in KNOWN_STATES for slot in SLOTS)
            for f in fields),
    }
    hero_frames = [f for f in fields if len(_known_cards(f["hero"])) == 2]
    with_actor = [f for f in hero_frames if isinstance(f["actor"], int)]
    hero_in_hand = [f for f in hero_frames
                    if f["participants"].get("4") in ("active", "all_in")]

    def all_known(frames):
        return _fraction(sum(all(f["participants"].get(slot) in KNOWN_STATES
                                 for slot in SLOTS) for f in frames), len(frames))

    math_rows = [f["table_math"] or {} for f in fields]
    table_math = {}
    for key in ("equity", "pot_odds", "spr"):
        items = [m.get(key) or {} for m in math_rows]
        table_math[key] = {
            "available": _fraction(sum(i.get("available") is True for i in items),
                                   total),
            "reasons": dict(Counter(i.get("reason") for i in items
                                    if i.get("available") is not True)),
        }
    return {
        "frames_processed": total,
        "frames_arrived": arrived,
        "frames_dropped_fraction": _fraction(arrived - total, arrived),
        "processed_per_second": round(total / span, 2) if span > 0 else None,
        "video_seconds_covered": (round(max(video) - min(video), 1)
                                  if video else None),
        "latency_ms": {
            "arrival_to_published": percentiles(age),
            "recognition": percentiles([t["recognition_ms"] for t in timing]),
            "table_math": percentiles([t.get("math_ms", 0) for t in timing]),
        },
        "coverage": {key: _fraction(value, total) for key, value in coverage.items()},
        "all_participants_known": {
            "hero_card_frames": all_known(hero_frames),
            "hero_card_frames_with_actor": all_known(with_actor),
            "hero_turn_frames": all_known(hero_turn),
        },
        "equity_available_hero_in_hand": _fraction(
            sum(((f["table_math"] or {}).get("equity") or {}).get("available") is True
                for f in hero_in_hand), len(hero_in_hand)),
        "hero_turn_frames": len(hero_turn),
        "call_amount_read_on_hero_turn": _fraction(
            sum(f["hero_controls"].get("call_amount") is not None
                for f in hero_turn), len(hero_turn)),
        "table_math": table_math,
    }


def _nearest(rows, pts, tolerance):
    best = min((row for row in rows if row.get("source_video_pts") is not None),
               key=lambda row: abs(row["source_video_pts"] - pts), default=None)
    if best is None or abs(best["source_video_pts"] - pts) > tolerance:
        return None
    return best


def _verdict(expected, actual):
    if actual is None or actual == "unknown":
        return "unknown"
    return "correct" if actual == expected else "wrong"


def compare_gold(rows, gold, tolerance=0.2):
    """Per-field agreement with reviewed checkpoints at the nearest processed frame."""
    results = {name: Counter() for name in (
        "hero_cards", "board_cards", "street", "pot", "actor", "stacks",
        "participation")}
    details = []
    for point in gold["checkpoints"]:
        pts = float(point["pts_seconds"])
        row = _nearest(rows, pts, tolerance)
        if row is None:
            results["hero_cards"]["no_frame"] += 1
            details.append({"pts": pts, "matched": None})
            continue
        got, fields = row["fields"], point["fields"]
        checks = {}

        def check(name, expected, actual, key=None):
            verdict = _verdict(expected, actual)
            results[name][verdict] += 1
            if verdict != "correct":
                checks[key or name] = {"expected": expected, "actual": actual}

        if fields["hero_cards"]["status"] == "KNOWN":
            hero = got["hero"] if len(_known_cards(got["hero"])) == 2 else None
            check("hero_cards", fields["hero_cards"]["value"], hero)
        if fields["board_cards"]["status"] == "KNOWN":
            # No visible board is a reading of zero cards, right preflop.
            board = None if got["board"] is None else _known_cards(got["board"])
            check("board_cards", fields["board_cards"]["value"], board)
        if fields["street"]["status"] == "KNOWN":
            check("street", fields["street"]["value"], got["street"])
        if fields["pot"]["status"] == "KNOWN":
            check("pot", fields["pot"]["value"], got["pot"])
        if fields["actor"]["status"] == "KNOWN":
            check("actor", fields["actor"]["value"], got["actor"])
        for slot, value in (fields["stacks"].get("value") or {}).items():
            if isinstance(value, str):
                check("stacks", value, got["stacks"].get(slot), f"stacks:{slot}")
        for slot, value in (fields["participation"].get("value") or {}).items():
            if value is not None:
                check("participation", value, got["participants"].get(slot),
                      f"participation:{slot}")
        details.append({"pts": pts, "matched_video_pts": row["source_video_pts"],
                        "mismatches": checks})
    return {"fields": {name: dict(counts) for name, counts in results.items()},
            "checkpoints": details}


def read_log(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", type=Path, default=Path(DEFAULT_PROFILE))
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="START-END")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--gold", type=Path)
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=False)
    frame_log = args.out / "frames.jsonl"
    outcome = run(args.profile, args.video, frame_log, start=args.start,
                  exclude=args.exclude, speed=args.speed,
                  max_seconds=args.max_seconds)
    rows = read_log(frame_log) if frame_log.exists() else []
    report = {"video": str(args.video), "start": args.start,
              "exclude": args.exclude, "speed": args.speed, "run": outcome,
              "summary": summarize(rows)}
    if args.gold is not None:
        report["gold"] = {"file": str(args.gold), **compare_gold(
            rows, json.loads(args.gold.read_text(encoding="utf-8")))}
    (args.out / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("run", "summary")},
                     ensure_ascii=False, indent=1))
    return 0 if outcome["status"] != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
