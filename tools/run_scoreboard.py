"""Score strategies on simulated AA eight-seat tables (bb/100 with 95% intervals).

    PYTHONPATH=src:. .venv/bin/python tools/run_scoreboard.py --deals 2000 \\
        [--strategies rfi_table,tag,always_call] \\
        [--pool population|aa|aa_real|styles|reg|maniac|nit|tough|mirror|solver] \\
        [--mushroom 3 [--mushroom-take 0.135]] [--bomb 7 [--bomb-share 0.07]] \\
        [--reads 100] [--workers 10] [--out result.json]

Each deal is played by every strategy from all eight seats against the same
shuffled lineup of pool opponents; ``hands`` = deals x 8 per strategy. The
pool is a name from ``runner.POOLS`` or a comma-separated list of policies;
the default, "population", plays like real players; "aa_real" like the AA
players measured on recordings (``scoreboard/aa_real.py``); "reg", "maniac",
"nit" and "tough" are the tougher opponents of ``scoreboard/opponents.py``.
``--mushroom 3`` plays the AA mushroom pool with the dealer putting in 3 big
blinds (see ``scoreboard/mushroom.py``). ``--bomb 7`` makes 7% of the deals
bomb pots where every player puts in 7 big blinds and the hand starts on the
flop (``--bomb-share 1`` for bomb pots only; see ``scoreboard/bomb.py``).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from poker_engine.scoreboard.bots import POLICY_NAMES
from poker_engine.scoreboard.bomb import SHARE, Bomb
from poker_engine.scoreboard.mushroom import TAKE, Mushroom
from poker_engine.scoreboard.runner import POOLS, run_scoreboard
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

DEFAULT_RULES = (Path(__file__).resolve().parents[1]
                 / "configs/game/aa-scoreboard-rules-v2.json")


def table(report):
    rows = sorted(report["strategies"].items(), key=lambda kv: -kv[1]["bb_per_100"])
    width = max(12, *(len(name) for name, _ in rows))
    header = "vs " + report["reference"]
    lines = [f"{'strategy':<{width}} {'bb/100':>8}  {'95% interval':<20} {header:>14}"]
    for name, row in rows:
        ci = row["ci95"]
        versus = report["versus_reference"].get(name)
        delta = "" if versus is None else f"{versus['delta_bb_per_100']:+.1f}"
        interval = f"[{ci[0]:.1f}, {ci[1]:.1f}]"
        lines.append(f"{name:<{width}} {row['bb_per_100']:>8.1f}  {interval:<20} "
                     f"{delta:>14}")
    others = {pair: row for pair, row in report.get("pairwise", {}).items()
              if report["reference"] not in pair.split(" - ")}
    for pair, row in others.items():
        ci = row["ci95"]
        lines.append(f"{pair}: {row['delta_bb_per_100']:+.1f} "
                     f"[{ci[0]:.1f}, {ci[1]:.1f}]" if ci else f"{pair}: "
                     f"{row['delta_bb_per_100']:+.1f}")
    lines += split_lines(report, rows, "by_flop",
                         "by flop (bb/100 from hands over before it / heads-up / "
                         "multiway; share of hands):")
    lines += split_lines(report, rows, "by_end",
                         "by where the hand ended (folded or won on a street, or "
                         "showdown; share of hands):")
    lines += split_lines(report, rows, "by_kind",
                         "normal hands and bomb pots (share of hands):")
    if report.get("bomb"):
        lines.append(f"bomb pots: {report['bomb']['share']:.0%} of deals, every "
                     f"player puts in {report['bomb']['post_big_blinds']:g} big blinds")
    if report.get("mushroom"):
        lines.append("mushroom pool: the dealer puts in "
                     f"{report['mushroom']['post_big_blinds']:g} big blinds, the small "
                     f"blind takes it {report['mushroom']['take']:.1%} of hands")
    lines.append(f"{report['hands_per_strategy']} hands per strategy, "
                 f"{report['seconds']} s on {report['workers']} workers")
    return "\n".join(lines)


def split_lines(report, rows, key, title):
    lines = [title]
    for name, row in rows:
        parts = row.get(key)
        if not parts:
            continue
        versus = (report["versus_reference"].get(name) or {}).get(key) or {}
        cells = []
        for flop, part in parts.items():
            delta = versus.get(flop)
            cells.append(f"{flop} {part['bb_per_100']:+.1f} ({part['share']:.0%})"
                         + ("" if delta is None else
                            f" vs ref {delta['delta_bb_per_100']:+.1f}"))
        lines.append(f"  {name}: " + " | ".join(cells))
    return lines if len(lines) > 1 else []


def show_progress(done, total, seconds):
    left = seconds / done * (total - done)
    sys.stderr.write(f"\r{done}/{total} batches, {seconds / 60:.1f} min, "
                     f"about {left / 60:.1f} min left ")
    if done == total:
        sys.stderr.write("\n")
    sys.stderr.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deals", type=int, default=2000)
    parser.add_argument("--strategies", default=",".join(POLICY_NAMES))
    parser.add_argument("--pool", default="population",
                        help="pool name (" + ", ".join(POOLS) + ") or policies a,b,c")
    parser.add_argument("--reference", default="always_call")
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 1) - 2),
                        help="processes; default leaves two cores free")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--no-all-in-ev", action="store_true")
    parser.add_argument("--mushroom", type=float, metavar="BIG_BLINDS",
                        help="play the AA mushroom pool: the dealer's post")
    parser.add_argument("--mushroom-take", type=float, default=TAKE,
                        help="chance a hand's small blind takes the pool")
    parser.add_argument("--bomb", type=float, metavar="BIG_BLINDS",
                        help="make some deals bomb pots: what every player puts in")
    parser.add_argument("--bomb-share", type=float, default=SHARE,
                        help="share of deals that are bomb pots (1: only bomb pots)")
    parser.add_argument("--reads", type=int, metavar="HANDS",
                        help="give every decision reads on the opponents from this "
                        "many hands (aa_preflop uses them; noreads+name ignores them)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    rules = AARuleProfileV2.from_dict(
        json.loads(args.rules.read_text(encoding="utf-8")))
    report = run_scoreboard(rules, args.strategies.split(","), deals=args.deals,
                            pool=POOLS.get(args.pool) or tuple(args.pool.split(",")),
                            workers=args.workers,
                            base_seed=args.seed, reference=args.reference,
                            all_in_ev=not args.no_all_in_ev, progress=show_progress,
                            mushroom=None if args.mushroom is None else Mushroom(
                                args.mushroom, args.mushroom_take),
                            reads=args.reads,
                            bomb=None if args.bomb is None else Bomb(
                                args.bomb, args.bomb_share))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(table(report))


if __name__ == "__main__":
    main()
