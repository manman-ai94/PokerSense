"""Apply the one-reading-per-card check offline to a frame log.

Logs made before the check (``aa_card_check``) keep the cards as the reader
read them. This runs each row's ``hero`` and ``board`` through
``AACardCheck`` with the row's hand (``actions_v1``), writes the log again
with the checked cards and ``cards_held_back``, and prints how many frames
and hands had a card held back. The new log can then be measured like any
other, for example by ``tools/plain_live_report.py``:

    PYTHONPATH=src:. .venv/bin/python tools/replay_card_check.py \\
        --frames <录像>/frames.jsonl --out <新目录>/frames.jsonl

A log made with the check already has it: running this again changes
nothing. A reader reset in the log (a gap) is not replayed; the hand id
changes there anyway.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poker_engine.desktop.aa_card_check import AACardCheck  # noqa: E402


def _open(path, mode):
    return gzip.open(path, mode + "t") if path.suffix == ".gz" else path.open(mode)


def replay(rows):
    """(each row with the checked cards, totals)."""
    check = AACardCheck()
    frames, hands = 0, set()
    out = []
    for row in rows:
        fields = row.get("fields")
        if not isinstance(fields, dict):
            out.append(row)
            continue
        hand = (fields.get("actions_v1") or {}).get("hand_id")
        folded = (fields.get("participants") or {}).get("4") == "folded"
        hero, board, report = check.observe(fields.get("hero"), fields.get("board"),
                                            hand, row.get("pts_seconds"), folded=folded)
        if report["held_back"]:
            frames += 1
            hands.add(hand)
        out.append({**row, "fields": {**fields, "hero": hero, "board": board,
                                      "cards_held_back": report["held_back"]}})
    return out, {"frames_held_back": frames, "hands_held_back": len(hands)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    with _open(args.frames, "r") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    rows, totals = replay(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with _open(args.out, "w") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(totals, ensure_ascii=False))


if __name__ == "__main__":
    main()
