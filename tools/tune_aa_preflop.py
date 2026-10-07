"""Tune the AA preflop policy's parameters on the scoreboard.

Every combination of the given parameter values plays the same deals, next to
a reference strategy; the combinations are ranked by their paired difference
to the reference (bb/100 with a 95% interval). Choose on one set of deals and
check the choice on another (``--seed``): the best of many settings on the
same deals looks better than it is.

    PYTHONPATH=src:. .venv/bin/python tools/tune_aa_preflop.py \\
        --grid realize_ip=0.9,1.0,1.1 --grid realize_oop=0.7,0.8 \\
        [--pool aa] [--deals 2000] [--seed 1] [--reference rfi_table/population] \\
        [--base aa_preflop] [--out result.json]
"""

from __future__ import annotations

import argparse
from itertools import product
import json
import os
from pathlib import Path
import sys

from poker_engine.scoreboard.preflop_policy import PreflopParams
from poker_engine.scoreboard.runner import POOLS, run_scoreboard
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

DEFAULT_RULES = (Path(__file__).resolve().parents[1]
                 / "configs/game/aa-scoreboard-rules-v2.json")


def parse_grid(items):
    """``["realize_ip=0.9,1.0", ...]`` -> [(name, [values]), ...]."""
    known = PreflopParams.__dataclass_fields__
    grid = []
    for item in items:
        name, _, values = item.partition("=")
        if name not in known:
            raise SystemExit(f"unknown parameter: {name}")
        grid.append((name, [float(value) for value in values.split(",")]))
    return grid


def strategy_names(base, grid):
    names = []
    for values in product(*(values for _, values in grid)):
        settings = ":".join(f"{name}={value:g}"
                            for (name, _), value in zip(grid, values))
        names.append(f"{base}@{settings}" if settings else base)
    return names


def ranking(report):
    rows = [(name, row["delta_bb_per_100"], row["ci95"])
            for name, row in report["versus_reference"].items()]
    return sorted(rows, key=lambda row: -row[1])


def show_progress(done, total, seconds):
    left = seconds / done * (total - done)
    sys.stderr.write(f"\r{done}/{total} batches, {seconds / 60:.1f} min, "
                     f"about {left / 60:.1f} min left ")
    if done == total:
        sys.stderr.write("\n")
    sys.stderr.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--grid", action="append", default=[],
                        help="parameter=value,value,... (repeat for more)")
    parser.add_argument("--base", default="aa_preflop")
    parser.add_argument("--reference", default="rfi_table/population")
    parser.add_argument("--pool", default="aa")
    parser.add_argument("--deals", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 1) - 2))
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    names = strategy_names(args.base, parse_grid(args.grid))
    rules = AARuleProfileV2.from_dict(
        json.loads(args.rules.read_text(encoding="utf-8")))
    report = run_scoreboard(rules, [args.reference, *names], deals=args.deals,
                            pool=POOLS.get(args.pool) or tuple(args.pool.split(",")),
                            workers=args.workers, base_seed=args.seed,
                            reference=args.reference, progress=show_progress)
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"pool {args.pool}, {args.deals} deals, seed {args.seed}; "
          f"difference to {args.reference} (bb/100, 95% interval):")
    for name, delta, ci in ranking(report):
        print(f"{delta:+8.1f}  [{ci[0]:+.1f}, {ci[1]:+.1f}]  {name}")


if __name__ == "__main__":
    main()
