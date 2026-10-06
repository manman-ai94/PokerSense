"""Score strategies on simulated AA eight-seat tables (bb/100 with 95% intervals).

    PYTHONPATH=src:. .venv/bin/python tools/run_scoreboard.py --deals 2000 \\
        [--strategies rfi_table,tag,always_call] [--pool tag,lag,rock,station] \\
        [--workers 10] [--out result.json]

Each deal is played by every strategy from all eight seats against the same
shuffled lineup of pool styles; ``hands`` = deals x 8 per strategy.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from poker_engine.scoreboard.bots import POLICY_NAMES
from poker_engine.scoreboard.runner import DEFAULT_POOL, run_scoreboard
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

DEFAULT_RULES = (Path(__file__).resolve().parents[1]
                 / "configs/game/aa-scoreboard-rules-v1.json")


def table(report):
    rows = sorted(report["strategies"].items(), key=lambda kv: -kv[1]["bb_per_100"])
    header = "vs " + report["reference"]
    lines = [f"{'strategy':<12} {'bb/100':>8}  {'95% interval':<20} {header:>14}"]
    for name, row in rows:
        ci = row["ci95"]
        versus = report["versus_reference"].get(name)
        delta = "" if versus is None else f"{versus['delta_bb_per_100']:+.1f}"
        lines.append(f"{name:<12} {row['bb_per_100']:>8.1f}  "
                     f"[{ci[0]:.1f}, {ci[1]:.1f}]".ljust(42) + f"{delta:>8}")
    lines.append(f"{report['hands_per_strategy']} hands per strategy, "
                 f"{report['seconds']} s on {report['workers']} workers")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deals", type=int, default=2000)
    parser.add_argument("--strategies", default=",".join(POLICY_NAMES))
    parser.add_argument("--pool", default=",".join(DEFAULT_POOL))
    parser.add_argument("--reference", default="always_call")
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 1) - 2),
                        help="processes; default leaves two cores free")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--no-all-in-ev", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    rules = AARuleProfileV2.from_dict(
        json.loads(args.rules.read_text(encoding="utf-8")))
    report = run_scoreboard(rules, args.strategies.split(","), deals=args.deals,
                            pool=tuple(args.pool.split(",")), workers=args.workers,
                            base_seed=args.seed, reference=args.reference,
                            all_in_ev=not args.no_all_in_ev)
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(table(report))


if __name__ == "__main__":
    main()
