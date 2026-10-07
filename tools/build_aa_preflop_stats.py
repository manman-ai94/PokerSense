"""Count how real AA players act before the flop, from read action histories.

Reads the per-frame logs of measured recordings (``frames.jsonl`` with the
rebuilt ``actions_v1`` history of each hand), keeps the hands whose history is
complete, and counts every preflop action by the kind of decision it was
(``spots.preflop_spot``: rfi, vs_limp, vs_open ...): raise, call or fold.
Only totals per kind of decision are written, pooled over positions; the
population bot scales its real-player frequencies by them (see
``population.py``).

    PYTHONPATH=src:. .venv/bin/python tools/build_aa_preflop_stats.py \\
        <measurement>/frames.jsonl [...] [--out <file>]
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from poker_engine.scoreboard.spots import preflop_spot
from tools.check_aa_action_history import hands_v1, load

OUT = (Path(__file__).resolve().parents[1]
       / "src/poker_engine/scoreboard/aa_preflop_stats_v1.json")
KINDS = {"fold": "fold", "check": "call", "call": "call", "bet": "raise",
         "raise": "raise", "all_in": "raise"}


def count(rows, spots):
    """Add one log's complete hands to ``spots``; returns the hands counted."""
    counted = 0
    for hand in hands_v1(rows).values():
        actions = [a for a in hand["actions"]
                   if a["street"] == "preflop" and a["slot"] is not None
                   and a["kind"] in KINDS]
        if not hand["complete"] or not actions:
            continue
        counted += 1
        history = []
        for action in actions:
            kind = KINDS[action["kind"]]
            spots[preflop_spot(history, action["slot"])][kind] += 1
            history.append((action["slot"], {"fold": "f", "call": "c",
                                             "raise": "r"}[kind]))
    return counted


def build(paths):
    spots, sources = defaultdict(Counter), []
    for path in paths:
        hands = count(load(path), spots)
        sources.append({"log": path.parent.name, "hands": hands})
    return {
        "schema_version": 1,
        "method": ("complete hands of the rebuilt action history (actions_v1); "
                   "every preflop action counted by its kind of decision, pooled "
                   "over positions; all in counts as a raise"),
        "sources": sources,
        "hands": sum(source["hands"] for source in sources),
        "spots": {spot: {"n": sum(counts.values()),
                         **{kind: counts[kind] for kind in ("raise", "call", "fold")}}
                  for spot, counts in sorted(spots.items())},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("frames", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    report = build(args.frames)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for spot, row in report["spots"].items():
        print(f"{spot:<14} n={row['n']:<4} raise {row['raise'] / row['n']:.2f} "
              f"call {row['call'] / row['n']:.2f} fold {row['fold'] / row['n']:.2f}")
    print(f"{report['hands']} hands -> {args.out}")


if __name__ == "__main__":
    main()
