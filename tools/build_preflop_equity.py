"""Build the heads-up preflop equity table between all 169 hand classes.

For every pair of classes the equity of the first against the second is
estimated by Monte Carlo: each trial draws one pair of combinations that
share no card (uniformly among all such pairs) and five board cards, and
counts a win as 1 and a tie as 1/2. The table also keeps, for each pair, how
many combinations of the second class a hand of the first leaves possible
(card removal), averaged over the first class's combinations.

    PYTHONPATH=src:. .venv/bin/python tools/build_preflop_equity.py \\
        [--trials 6000] [--workers 8]
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
import json
import os
from pathlib import Path
import random

from poker_engine.scoreboard.strength import (_EVALUATE_7, CARD_ID, DECK, hand_class,
                                              preflop_table)

OUT = (Path(__file__).resolve().parents[1]
       / "src/poker_engine/scoreboard/preflop_equity_v1.json")
SEED = 20261007


def class_order():
    table = preflop_table()["classes"]
    return sorted(table, key=lambda name: table[name]["rank"])


def combos_by_class():
    groups = {}
    for first, second in combinations(DECK, 2):
        groups.setdefault(hand_class((first, second)), []).append(
            (CARD_ID[first], CARD_ID[second]))
    return groups


def row(task):
    """Equities and compatible-combination counts of one class against all."""
    index, names, trials = task
    groups = combos_by_class()
    mine = groups[names[index]]
    rng = random.Random(SEED * 1000 + index)
    equities, counts = [], []
    for other in names:
        pairs = [(a, b) for a in mine for b in groups[other]
                 if not set(a) & set(b)]
        counts.append(round(len(pairs) / len(mine), 4))
        won = 0.0
        for _ in range(trials):
            (h1, h2), (v1, v2) = rng.choice(pairs)
            dead = {h1, h2, v1, v2}
            board = rng.sample([card for card in range(52) if card not in dead], 5)
            hero, villain = _EVALUATE_7(h1, h2, *board), _EVALUATE_7(v1, v2, *board)
            won += 1.0 if hero < villain else 0.5 if hero == villain else 0.0
        equities.append(won / trials)
    return index, equities, counts


def build(trials, workers):
    names = class_order()
    tasks = [(index, names, trials) for index in range(len(names))]
    rows = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for index, equities, counts in executor.map(row, tasks):
            rows[index] = (equities, counts)
    size = len(names)
    # Each pair was estimated twice (once from each side): average the two.
    equity = [[round((rows[i][0][j] + 1 - rows[j][0][i]) / 2, 4) for j in range(size)]
              for i in range(size)]
    return {
        "schema_version": 1,
        "method": ("monte_carlo: uniform non-overlapping combination pairs and "
                   "five-card boards; each pair estimated from both sides and "
                   "averaged; ties count half"),
        "trials_per_side": trials,
        "seed": SEED,
        "classes": names,
        "equity": equity,
        "compatible_combos": [rows[i][1] for i in range(size)],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=6000)
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 1) - 2))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    report = build(args.trials, args.workers)
    args.out.write_text(json.dumps(report, separators=(",", ":")) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out} ({len(report['classes'])} classes)")


if __name__ == "__main__":
    main()
