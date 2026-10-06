"""Check the eight seat states on a recording: coverage and agreement with labels.

Runs the AA reader over a recording (every ``--stride``-th frame, in order)
and reports how often all eight seats are known, both overall and on frames
where someone is acting. With ``--labels`` it also compares the seat states
with seats read by eye at given times.

Labels file (JSON): ``{"labels": {"<seconds>": "<8 letters>"}}``, or
``{"recordings": {"<recording folder name>": {"labels": ...}}}``; one letter
per seat 0-7: A active, F folded, E empty, W waiting or away, I all-in,
? not scored. Labels for the 2026-10-06 spectating recordings are in
``tests/fixtures/aa_reference_hands/mac_spectate_seat_labels_20261006.json``.

    PYTHONPATH=src:. .venv/bin/python tools/check_aa_seat_states.py \\
        --video <recording> [--labels labels.json] [--exclude 300-820]
"""

from __future__ import annotations

import argparse
import bisect
from collections import Counter
import json
from pathlib import Path

LETTERS = {"A": "active", "F": "folded", "E": "empty", "W": "waiting",
           "I": "all_in"}
KNOWN = frozenset(LETTERS.values())
SLOTS = tuple(str(slot) for slot in range(8))
DEFAULT_PROFILE = "configs/reproduction/aa8_candidate_v2/factory.json"


def read_states(video, *, stride=3, exclude=(), profile=DEFAULT_PROFILE):
    """[(pts, row summary)] for every ``stride``-th frame outside ``exclude``."""
    import cv2

    from poker_engine.desktop.aa_reader import AA8Reader
    from poker_engine.desktop.aa_video_source import video_segments
    from poker_engine.perceptual.capture.normalization import (
        NormalizationConfig, normalize)

    config = NormalizationConfig(
        rotate_degrees=0, source_size=(1920, 1080),
        crop_after_rotation=(711, 0, 1209, 1080), output_size=(498, 1080),
        version="aa8-capture-canvas-v1")
    reader = AA8Reader(profile)
    rows, sequence, index = [], 0, 0
    for segment in video_segments(video):
        capture = cv2.VideoCapture(str(segment.path))
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            pts = segment.start + capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            index += 1
            if index % stride or any(start <= pts < end for start, end in exclude):
                continue
            payload = reader.read(normalize(frame, config), sequence, {
                "source_frame": index, "pts_seconds": pts,
                "source_kind": "video"})
            sequence += 1
            hero = [card for card in payload["cards"].get("hero") or () if card]
            rows.append((pts, {
                "supported": payload.get("scene_supported") is True,
                "hero_cards": len(hero) == 2,
                "actor": payload.get("current_actor"),
                "states": {slot: seat["state"] for slot, seat in
                           payload["seat_states_v1"]["seats"].items()}}))
        capture.release()
    return rows


def _fraction(count, total):
    return round(count / total, 4) if total else None


def coverage(rows):
    def all_known(selected):
        return _fraction(sum(all(row["states"].get(slot) in KNOWN for slot in SLOTS)
                             for row in selected), len(selected))

    supported = [row for _, row in rows if row["supported"]]
    acting = [row for row in supported if isinstance(row["actor"], int)]
    hero = [row for row in supported if row["hero_cards"]]
    return {"frames": len(rows), "supported_frames": len(supported),
            "all_known_supported": all_known(supported),
            "all_known_while_acting": all_known(acting),
            "hero_card_frames": len(hero),
            "all_known_hero_cards": all_known(hero),
            "all_known_hero_cards_while_acting": all_known(
                [row for row in hero if isinstance(row["actor"], int)])}


def agreement(rows, labels, tolerance=0.2):
    times = [pts for pts, _ in rows]
    counts, wrong = Counter(), []
    for text, truth in sorted(labels.items(), key=lambda item: float(item[0])):
        target = float(text)
        position = bisect.bisect_left(times, target)
        near = [i for i in (position - 1, position) if 0 <= i < len(rows)]
        best = min(near, key=lambda i: abs(times[i] - target), default=None)
        if best is None or abs(times[best] - target) > tolerance:
            counts["no_frame"] += 1
            continue
        for slot, letter in enumerate(truth):
            if letter == "?":
                continue
            got = rows[best][1]["states"].get(str(slot))
            if got not in KNOWN:
                counts["unknown"] += 1
            elif got == LETTERS[letter]:
                counts["correct"] += 1
            else:
                counts["wrong"] += 1
                wrong.append({"seconds": target, "seat": slot,
                              "expected": LETTERS[letter], "got": got})
    return {"counts": dict(counts), "wrong": wrong}


def main(argv=None):
    from poker_engine.desktop.aa_video_source import parse_windows

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--exclude", action="append", default=[],
                        help="seconds window to skip, e.g. 300-820 (repeatable)")
    args = parser.parse_args(argv)
    rows = read_states(args.video, stride=args.stride,
                       exclude=parse_windows(args.exclude))
    report = {"video": str(args.video), "stride": args.stride,
              "exclude": args.exclude, "coverage": coverage(rows)}
    if args.labels:
        data = json.loads(args.labels.read_text(encoding="utf-8"))
        labels = (data["labels"] if "labels" in data
                  else data["recordings"][args.video.name]["labels"])
        report["labels"] = agreement(rows, labels)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
