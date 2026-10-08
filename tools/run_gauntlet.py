"""Score strategies against every kind of opponent, one table type at a time.

    PYTHONPATH=src:. .venv/bin/python tools/run_gauntlet.py --deals 2000 \\
        --strategies range_multiway+aa_preflop [--reference aa_preflop] \\
        [--pools aa,population,reg,maniac,nit,tough] [--mushroom 3] \\
        [--seed 1] [--workers 8] [--out <directory>]

Each pool is a full scoreboard run (``run_scoreboard.py --pool <name>``) on
the same deals, so a strategy's rows can be compared across pools. The table
shows bb/100 with its 95% interval per pool and a verdict: "wins" when the
whole interval is above zero, "loses" when it is below, "unclear" otherwise.
For a pool a strategy does not win, the parts of the result that fall
furthest below the same part against the first pool (the baseline table,
"aa" by default) are listed: how the hand reached the flop (before it,
heads-up, multiway) and where it ended (folded or won on a street, or at the
showdown). For example "ended: preflop -90" against maniacs: hands that end
before the flop cost 90 bb/100 more than on the AA table (folding to raises).

The "mirror" pool is the AI itself: a table of equals loses about the rake,
so there it is judged against the reference instead. Pools with a solver
("solver") need TexasSolver installed (``tools/setup_texassolver.sh``) and
take hours; they are refused without it rather than quietly playing without.

With ``--mushroom`` the pool carried in from earlier hands is drawn as if the
small blind takes it as often as it does on that table: short runs of
``--calibration-deals`` deals measure it, each starting from the share the
last one measured, since a bigger pool makes the small blind play more hands
(``--mushroom-take`` sets one share for every pool instead). On a table of
tight players, where the small blind wins half the pots, the default share
(13.5%, from the AA players) would carry in far more chips than such a table
ever leaves in the pool.

With ``--out`` every pool's full report is saved as <pool>.json next to
summary.json; ``--resume`` reuses the pools a stopped run already saved there
with the same settings.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from poker_engine.scoreboard.bomb import SHARE, Bomb
from poker_engine.scoreboard.mushroom import TAKE, Mushroom
from poker_engine.scoreboard.runner import POOLS, run_scoreboard
from poker_engine.solver.texassolver import solver_binary
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

DEFAULT_RULES = (Path(__file__).resolve().parents[1]
                 / "configs/game/aa-scoreboard-rules-v2.json")
DEFAULT_POOLS = "aa,population,reg,maniac,nit,tough"
LOSING_PARTS = 2          # parts listed where a strategy does not win
CALIBRATION_DEALS = 200   # deals that measure how often the small blind takes
CALIBRATION_PASSES = 2    # each from the share the last one measured
MIN_TAKE = 0.01


def needs_solver(pool):
    return any(name.startswith("solver_") or "+solver_" in name for name in pool)


def verdict(row):
    low, high = row["ci95"] or (None, None)
    if low is not None and low > 0:
        return "wins"
    if high is not None and high < 0:
        return "loses"
    return "unclear"


def weakest(row, base):
    """The parts of a strategy's result that fall furthest below the same part
    against the first pool (the baseline table), worst first: (part, bb/100
    here minus there, share of hands here)."""
    parts = []
    for key, label in (("by_flop", "to the flop:"), ("by_end", "ended:"),
                       ("by_kind", "hands:")):
        for part, value in row.get(key, {}).items():
            if part not in base.get(key, {}):
                continue
            gap = value["bb_per_100"] - base[key][part]["bb_per_100"]
            if value["share"] > 0 and gap < 0:
                parts.append((f"{label} {part}", round(gap, 2), value["share"]))
    return sorted(parts, key=lambda item: item[1])[:LOSING_PARTS]


def summarize(reports, strategies, reference):
    """{strategy: {pool: bb/100, interval, verdict, weakest parts, vs reference}}."""
    summary = {}
    base = next(iter(reports))
    for name in strategies:
        summary[name] = {}
        for pool, report in reports.items():
            row = report["strategies"][name]
            weak = [] if pool == base else weakest(
                row, reports[base]["strategies"][name])
            versus = report["versus_reference"].get(name)
            cell = {"bb_per_100": row["bb_per_100"], "ci95": row["ci95"],
                    "verdict": verdict(row), "weakest": weak}
            bomb = row.get("by_kind", {}).get("bomb")
            if bomb and bomb["share"]:
                cell["bomb"] = bomb
            if versus is not None:
                cell["vs_reference"] = {"delta_bb_per_100": versus["delta_bb_per_100"],
                                        "ci95": versus["ci95"],
                                        "verdict": verdict({"ci95": versus["ci95"]})}
            if pool == "mirror":
                cell["verdict"] = cell.get("vs_reference", {}).get("verdict", "unclear")
            summary[name][pool] = cell
    return summary


def measured_take(report):
    """How often the small blind took the pool, over every strategy's hands."""
    shares = [row["mushroom_take"] for row in report["strategies"].values()]
    return max(MIN_TAKE, sum(shares) / len(shares))


def bomb_settings(args):
    if args.bomb is None:
        return None
    return Bomb(args.bomb, args.bomb_share).to_dict()


def finished(args, pool, strategies):
    """With ``--resume``, the pool's report already saved by the same run
    settings (an interrupted run picks up where it stopped), else None."""
    path = args.out / f"{pool}.json" if args.out else None
    if not args.resume or path is None or not path.is_file():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    post = (report.get("mushroom") or {}).get("post_big_blinds")
    same = (report["deals"] == args.deals and report["base_seed"] == args.seed
            and list(report["pool"]) == list(POOLS[pool])
            and set(strategies) <= set(report["strategies"])
            and post == args.mushroom
            and (report.get("reads") or {}).get("hands") == (args.reads or None)
            and report.get("bomb") == bomb_settings(args)
            and (args.mushroom_take is None or post is None
                 or report["mushroom"]["take"] == args.mushroom_take))
    return report if same else None


def table(summary, pools, reference, takes=None):
    lines = []
    for name, cells in summary.items():
        lines.append(name)
        for pool in pools:
            cell = cells[pool]
            low, high = cell["ci95"] or (float("nan"), float("nan"))
            text = (f"  {pool:<11} {cell['bb_per_100']:>+8.1f}  "
                    f"[{low:+.1f}, {high:+.1f}]  {cell['verdict']}")
            if "vs_reference" in cell:
                delta = cell["vs_reference"]["delta_bb_per_100"]
                text += f"  (vs {reference} {delta:+.1f})"
            if takes:
                text += f"  [mushroom take {takes[pool]:.0%}]"
            if "bomb" in cell and cell["bomb"]["share"] < 1:
                text += (f"  [bomb pots {cell['bomb']['bb_per_100']:+.1f} of it, "
                         f"{cell['bomb']['share']:.0%} of hands]")
            lines.append(text)
            if cell["verdict"] != "wins" and cell["weakest"]:
                lines.append(f"              below {pools[0]} most: " + ", ".join(
                    f"{part} {value:+.1f} ({share:.0%} of hands)"
                    for part, value, share in cell["weakest"]))
    return "\n".join(lines)


def progress(pool, done, total, seconds):
    left = seconds / done * (total - done)
    sys.stderr.write(f"\r{pool}: {done}/{total} batches, {seconds / 60:.1f} min, "
                     f"about {left / 60:.1f} min left ")
    if done == total:
        sys.stderr.write("\n")
    sys.stderr.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deals", type=int, default=2000)
    parser.add_argument("--strategies", default="range_multiway+aa_preflop")
    parser.add_argument("--reference", help="a strategy to compare with (added "
                        "to the run when missing)")
    parser.add_argument("--pools", default=DEFAULT_POOLS,
                        help="pool names from: " + ", ".join(POOLS))
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 1) - 2))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--mushroom", type=float, metavar="BIG_BLINDS")
    parser.add_argument("--mushroom-take", type=float,
                        help=f"one share for every pool (default: measured; "
                        f"the AA players' is {TAKE})")
    parser.add_argument("--bomb", type=float, metavar="BIG_BLINDS",
                        help="make some deals bomb pots: what every player puts in")
    parser.add_argument("--bomb-share", type=float, default=SHARE,
                        help="share of deals that are bomb pots (1: only bomb pots)")
    parser.add_argument("--reads", type=int, metavar="HANDS",
                        help="give every decision reads on the opponents from "
                        "this many hands (noreads+name ignores them)")
    parser.add_argument("--calibration-deals", type=int, default=CALIBRATION_DEALS)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--resume", action="store_true",
                        help="reuse pools already saved in --out by the same settings")
    args = parser.parse_args(argv)
    strategies = args.strategies.split(",")
    if args.reference and args.reference not in strategies:
        strategies.append(args.reference)
    pools = args.pools.split(",")
    unknown = [pool for pool in pools if pool not in POOLS]
    if unknown:
        parser.error(f"unknown pools {unknown}; known: {', '.join(POOLS)}")
    if solver_binary() is None and any(needs_solver(POOLS[pool]) for pool in pools):
        parser.error("a pool plays with TexasSolver, which is not installed here "
                     "(tools/setup_texassolver.sh)")
    rules = AARuleProfileV2.from_dict(
        json.loads(args.rules.read_text(encoding="utf-8")))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
    reports, takes = {}, {}
    bomb = None if args.bomb is None else Bomb(args.bomb, args.bomb_share)
    for pool in pools:
        saved = finished(args, pool, strategies)
        if saved is not None:
            reports[pool] = saved
            if saved.get("mushroom"):
                takes[pool] = saved["mushroom"]["take"]
            continue
        mushroom = None
        if args.mushroom is not None:
            take = args.mushroom_take
            if take is None:
                take = TAKE
                for _ in range(CALIBRATION_PASSES):
                    take = measured_take(run_scoreboard(
                        rules, strategies,
                        deals=min(args.deals, args.calibration_deals),
                        pool=POOLS[pool], workers=args.workers,
                        base_seed=args.seed, mushroom=Mushroom(args.mushroom, take),
                        reads=args.reads, bomb=bomb,
                        progress=lambda done, total, seconds, pool=pool: progress(
                            f"{pool} (mushroom take)", done, total, seconds)))
            takes[pool] = take
            mushroom = Mushroom(args.mushroom, take)
        reports[pool] = run_scoreboard(
            rules, strategies, deals=args.deals, pool=POOLS[pool],
            workers=args.workers, base_seed=args.seed,
            reference=args.reference or strategies[0], mushroom=mushroom,
            reads=args.reads, bomb=bomb,
            progress=lambda done, total, seconds, pool=pool: progress(
                pool, done, total, seconds))
        if args.out:
            (args.out / f"{pool}.json").write_text(json.dumps(reports[pool], indent=1),
                                                   encoding="utf-8")
    summary = summarize(reports, strategies, args.reference)
    if args.out:
        (args.out / "summary.json").write_text(json.dumps({
            "deals": args.deals, "seed": args.seed, "pools": pools,
            "reference": args.reference, "reads": args.reads,
            "bomb": bomb_settings(args),
            "mushroom": None if args.mushroom is None else {
                "post_big_blinds": args.mushroom, "take": takes},
            "strategies": summary}, indent=1), encoding="utf-8")
    print(table(summary, pools, args.reference, takes))
    hands = args.deals * rules.table_size
    print(f"{hands} hands per strategy and pool, seed {args.seed}"
          + ("" if args.mushroom is None else
             f", mushroom {args.mushroom:g} big blinds")
          + ("" if not args.reads else f", reads from {args.reads} hands")
          + ("" if args.bomb is None else
             f", bomb pots {args.bomb_share:.0%} of deals ({args.bomb:g} big blinds)"))


if __name__ == "__main__":
    main()
