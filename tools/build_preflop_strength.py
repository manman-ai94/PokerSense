"""Rank the 169 starting hands by equity against one random hand.

Writes ``src/poker_engine/scoreboard/preflop_strength_v1.json``; the file is
reproducible from the fixed seed and trial count below.

    PYTHONPATH=src:. .venv/bin/python tools/build_preflop_strength.py
"""

from __future__ import annotations

import json
from pathlib import Path
import random

from poker_engine.scoreboard.strength import all_classes, class_combos, equity

TRIALS = 40000
SEED = 20261006
OUT = (Path(__file__).resolve().parents[1]
       / "src/poker_engine/scoreboard/preflop_strength_v1.json")


def example(name):
    if len(name) == 2:
        return [name[0] + "c", name[1] + "d"]
    return [name[0] + "c", name[1] + ("c" if name.endswith("s") else "d")]


def build():
    rng = random.Random(SEED)
    rows = [(name, equity(example(name), [], 1, TRIALS, rng)) for name in all_classes()]
    rows.sort(key=lambda row: (-row[1], row[0]))
    total = sum(class_combos(name) for name, _ in rows)
    classes, seen = {}, 0
    for rank, (name, value) in enumerate(rows, 1):
        seen += class_combos(name)
        classes[name] = {"rank": rank, "equity_vs_one_random": round(value, 4),
                         "percentile": round(seen / total, 4)}
    return {"schema_version": 1, "method": "monte_carlo_equity_vs_one_random_hand",
            "trials_per_class": TRIALS, "seed": SEED, "combos": total,
            "percentile": "share of starting-hand combinations at least this strong",
            "classes": classes}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT)
