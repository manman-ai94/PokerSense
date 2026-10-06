"""Check the Hero call-button reading against labelled Hero turns of a recording.

For every labelled turn the green button is read every ``--step`` seconds
and compared with the label: an amount to call, "check" (让牌), "all_in" or
"none". Wrong amounts are listed; an unread button counts as unknown.

    PYTHONPATH=src:. .venv/bin/python tools/check_aa_call_button.py \\
        --video <recording> \\
        --labels tests/fixtures/aa_reference_hands/hero_call_button_labels_v1.json
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path

DEFAULT_PROFILE = "configs/reproduction/aa8_candidate_v2/factory.json"


def load_bank(profile=DEFAULT_PROFILE):
    import numpy as np

    from poker_engine.data_paths import resolve_legacy_path
    from poker_engine.perceptual.vision.gray_amount_recognizer import (
        GrayAmountRecognizer)

    spec = json.loads(Path(profile).read_text(encoding="utf-8"))
    path = resolve_legacy_path(spec["bank_path"]) or Path(spec["bank_path"])
    with np.load(path, allow_pickle=False) as bank:
        return GrayAmountRecognizer(bank["features"], bank["labels"], augment=True)


def read_button(image, bank):
    """What the green button says in one canvas frame, as a label string."""
    from poker_engine.desktop.aa_hero_controls import button_text

    text = button_text(image)
    if text["kind"] == "call":
        return asdict(bank.diagnose(text["digits"]))["value"]
    if text["kind"] in ("check", "all_in"):
        return text["kind"]
    return "none" if text["reason"] == "no_button_text" else None


def sample_frames(video, turns, step=0.5):
    """[(turn index, seconds, canvas)] every ``step`` seconds inside each turn."""
    import cv2

    from poker_engine.desktop.aa_video_source import video_segments
    from poker_engine.perceptual.capture.normalization import (
        NormalizationConfig, normalize)

    config = NormalizationConfig(
        rotate_degrees=0, source_size=(1920, 1080),
        crop_after_rotation=(711, 0, 1209, 1080), output_size=(498, 1080),
        version="aa8-capture-canvas-v1")
    wanted = sorted((turn["from"] + k * step, index)
                    for index, turn in enumerate(turns)
                    for k in range(int((turn["to"] - turn["from"]) / step + 1e-9) + 1))
    frames, position = [], 0
    for segment in video_segments(video):
        capture = cv2.VideoCapture(str(segment.path))
        while position < len(wanted):
            ok, frame = capture.read()
            if not ok:
                break
            pts = segment.start + capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            while position < len(wanted) and pts >= wanted[position][0] - 0.02:
                frames.append((wanted[position][1], pts, normalize(frame, config)))
                position += 1
        capture.release()
    return frames


def compare(results, turns):
    """Counts and mismatches for [(turn index, seconds, read label)]."""
    counts, mismatches = Counter(), []
    for index, seconds, got in results:
        expected = turns[index]["button"]
        kind = expected if expected in ("check", "all_in", "none") else "amount"
        if got == expected:
            counts[kind + ":correct"] += 1
        elif got is None:
            counts[kind + ":unknown"] += 1
        else:
            counts[kind + ":wrong"] += 1
            mismatches.append({"seconds": round(seconds, 3), "expected": expected,
                               "got": got})
    return {"counts": dict(sorted(counts.items())), "wrong": mismatches}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--step", type=float, default=0.5)
    args = parser.parse_args(argv)
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    turns = labels["recordings"][args.video.name]["turns"]
    bank = load_bank()
    results = [(index, seconds, read_button(image, bank))
               for index, seconds, image in sample_frames(args.video, turns, args.step)]
    print(json.dumps({"video": str(args.video), "turns": len(turns),
                      "frames": len(results), **compare(results, turns)},
                     indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
