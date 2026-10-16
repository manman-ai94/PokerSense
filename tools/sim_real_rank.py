"""Does the simulation put strategy variants in the order the shown cards do,
and does it say what the window's strategy really makes?

    PYTHONPATH=src:. .venv/bin/python tools/sim_real_rank.py \\
        --sim <scoreboard>.json [--frames <log>.jsonl.gz ...] \\
        [--real-hands <hands.jsonl> ... --real-decisions <decisions.jsonl> ...] \\
        [--live <strategy>] [--workers 4] [--out <dir>]

``--sim`` is what ``tools/run_scoreboard.py --out`` writes for the variants and
their reference (``--strategies a,b,c,ref --reference ref``): a variant's
simulated gain is its ``versus_reference`` in bb/100.

In the recordings (the action history rebuilt by the current reader, as
``tools/replay_aa_action_history.py`` does), at each of your turns in a hand
where every opponent still in showed his cards at the end, every variant and
the reference decide as they would at the table (the hand replayed on the
simulated table, ``aa_solver_input.table_observation``), and each answer is
valued in big blinds against those cards as ``tools/aa_compare_advice.py``
values one. A variant's evidence is its total minus the reference's.

The check is Kendall's tau of the two orders (the reference at 0 in both):
"agree" from ``AGREE`` up, else "disagree"; "not enough data" with fewer than
``MIN_VARIANTS`` variants or ``MIN_TURNS`` priced turns where a variant
answers otherwise than the reference.

Limits: a hand reaches the showdown more often when the opponents hold more,
so the cards shown favour folding; each turn is priced alone, the rest of the
hand as it was played; the opponents' reads and chips on screen beyond the
replayed pot are not given (score the simulation without ``--reads``);
variants that need the solver cannot be priced. The 9 September recording
kept for acceptance is never read. Writes aggregates only.

The level (``--real-hands``): the simulation's bb/100 for the window's
strategy (``--live``, as ``run_scoreboard`` plays it; run it on ``aa_cal``)
against what that strategy really made at the table: the luck-adjusted
result of the hands played as advised, every decision of the hand following
the advice and none of them on a rough one (the hand and decision lines that
``tools/luck_results.py --lines`` and ``tools/tester_review.py`` write,
private; only totals come out here). Above the real 95% interval the
simulation is "too optimistic", below it "too pessimistic": its opponents
are easier, or harder, than the real ones, and its results say more than
they should. "inside" otherwise; "not enough data" with fewer than
``MIN_LEVEL_HANDS`` hands. The plain interval decides; whether the
simulation is outside even the always-valid one (``luck.always_valid``,
right however often it is looked at) is said too. Hands played otherwise
than advised, or on a rough advice, are another strategy and are left out
(whether the advice was followed is the player's choice, which can lean the
rest a little either way).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_solver_input import HERO as HERO_SEAT  # noqa: E402
from poker_engine.scoreboard import luck  # noqa: E402
from poker_engine.scoreboard.bots import make_policy  # noqa: E402
from tools.aa_compare_advice import chips, shown_spot, turns  # noqa: E402
from tools.replay_aa_action_history import replay  # noqa: E402
from tools.sim_fidelity import load, log_name  # noqa: E402

HOLDOUT = re.compile(r"20260909[_-]?031030")   # the acceptance recording
AGREE = 0.5          # tau: three pairs in four in the same order
MIN_VARIANTS = 8     # besides the reference
MIN_TURNS = 30
LIVE = "range_multiway@hu=1+aa_preflop"   # the window's advice, as simulated
MIN_LEVEL_HANDS = 200


def log_spots(path):
    """``spots`` of one log, its action history rebuilt by the current reader."""
    return spots(log_name(path), replay(load(path)))


def spots(name, rows):
    """Your turns in a log's rows that the shown cards price:
    [(where, the table as you saw it, your share against the cards shown)]."""
    rows = [row for row in rows if row.get("fields")]
    found = []
    for indexes in turns(rows):
        fields = rows[indexes[0]]["fields"]
        hand = (rows[indexes[-1]]["fields"].get("actions_v1") or {}).get("hand_id")
        try:
            spot = shown_spot(rows, indexes, hand)
        except Exception:                 # a hand that does not replay
            spot = None
        if spot is None:
            continue
        observation, share, _ = spot
        if observation.get("actor") != HERO_SEAT or not observation["legal_actions"]:
            continue
        if Decimal(fields.get("mushroom_pool") or 0) > 0:
            observation = {**observation, "mushroom_pool": fields["mushroom_pool"]}
        found.append(({"log": name, "hand_id": hand, "row": indexes[0]},
                      observation, share))
    return found


def answer(observation, action_id):
    """A table action as ``aa_compare_advice.chips`` reads an answer."""
    action = next(item for item in observation["legal_actions"]
                  if item["id"] == action_id)
    if action["kind"] == "raise_to":
        return {"action": "raise", "to": action["raise_to"]}
    if action["kind"] == "fold":
        return {"action": "fold"}
    return {"action": "call" if Decimal(observation["to_call"] or 0) else "check"}


def decide(job):
    """One strategy's answers at every spot, each with its worth in big blinds."""
    name, found = job
    policy = make_policy(name)
    result = []
    for where, observation, share in found:
        salt = hashlib.sha256(f"{where['log']}:{where['hand_id']}:{where['row']}"
                              .encode()).hexdigest()
        picked = answer(observation, policy.for_game(salt)(observation))
        worth = chips(picked, observation, share) / float(observation["big_blind"])
        result.append((picked, worth))
    return result


def kendall(pairs):
    """Kendall's tau (a) of [(x, y)] and the pairs in the same and the other order."""
    same = other = total = 0
    for index, (x1, y1) in enumerate(pairs):
        for x2, y2 in pairs[index + 1:]:
            total += 1
            sign = (x1 - x2) * (y1 - y2)
            same, other = same + (sign > 0), other + (sign < 0)
    return ((same - other) / total if total else None), same, other


def rank(sim, found, workers=1):
    reference = sim["reference"]
    variants = [name for name in sim["strategies"] if name != reference]
    names = [reference, *variants]
    with ProcessPoolExecutor(workers) as executor:
        decided = dict(zip(names, executor.map(decide, [(name, found)
                                                        for name in names])))
    base = decided[reference]
    differ = sum(any(decided[name][index][0] != base[index][0] for name in variants)
                 for index in range(len(found)))
    rows = {reference: {"sim": 0.0, "shown": 0.0, "differ": 0}}
    for name in variants:
        rows[name] = {
            "sim": sim["versus_reference"][name]["delta_bb_per_100"],
            "shown": round(sum(mine[1] - theirs[1] for mine, theirs
                               in zip(decided[name], base)), 2),
            "differ": sum(mine[0] != theirs[0] for mine, theirs
                          in zip(decided[name], base))}
    tau, same, other = kendall([(row["sim"], row["shown"]) for row in rows.values()])
    if len(variants) < MIN_VARIANTS or differ < MIN_TURNS:
        verdict = "not enough data"
    else:
        verdict = "agree" if tau >= AGREE else "disagree"
    return {"reference": reference, "pool": sim.get("pool"), "turns": len(found),
            "turns_differ": differ, "variants": rows,
            "tau": None if tau is None else round(tau, 3), "same_order": same,
            "other_order": other, "verdict": verdict}


def summary(result):
    lines = [f"{'variant':<48} {'sim bb/100':>10} {'shown bb':>9} {'differ':>6}"]
    for name, row in sorted(result["variants"].items(), key=lambda kv: -kv[1]["sim"]):
        lines.append(f"{name:<48} {row['sim']:>10.2f} {row['shown']:>9.2f} "
                     f"{row['differ']:>6}")
    tau = "n/a" if result["tau"] is None else f"{result['tau']:+.2f}"
    lines.append(f"sim vs shown cards: {result['verdict']} (tau {tau}; pairs in the "
                 f"same order {result['same_order']}, other {result['other_order']}; "
                 f"{result['turns_differ']} of {result['turns']} priced turns differ; "
                 f"needs {MIN_VARIANTS} variants and {MIN_TURNS} turns)")
    return "\n".join(lines)


def _hand(line):
    return line.get("machine"), line["log"], line["hand_id"]


def advised(hands, decisions):
    """The luck-adjusted results (big blinds) of the hands played as advised:
    every decision followed the advice and none was on a rough one."""
    rough = {_hand(line) for line in decisions if line.get("kind") == "rough"}
    return [float(line["adjusted"]) for line in hands
            if line.get("followed") == "yes" and _hand(line) not in rough]


def _per_100(low, high):
    return [round(100 * low, 1), round(100 * high, 1)]


def level(sim, values, live=LIVE):
    """The simulation's bb/100 for ``live`` against the real interval of
    ``values`` (``advised``)."""
    row = sim["strategies"].get(live)
    if row is None:
        raise SystemExit(f"{live} is not among the simulation's strategies")
    simulated = row["bb_per_100"]
    result = {"live": live, "pool": sim.get("pool"), "sim": simulated,
              "sim_ci95": row.get("ci95"), "hands": len(values),
              "real": None, "real_ci95": None, "always_valid_ci95": None,
              "outside_always_valid": None}
    mean, half = luck.interval(values)
    if half is None or len(values) < MIN_LEVEL_HANDS:
        result["verdict"] = "not enough data"
        if mean is not None:
            result["real"] = round(100 * mean, 1)
        return result
    _, lasting = luck.always_valid(values)
    low, high = _per_100(mean - half, mean + half)
    wide = _per_100(mean - lasting, mean + lasting)
    result.update(real=round(100 * mean, 1), real_ci95=[low, high],
                  always_valid_ci95=wide,
                  outside_always_valid=not wide[0] <= simulated <= wide[1],
                  verdict=("sim too optimistic" if simulated > high else
                           "sim too pessimistic" if simulated < low else "inside"))
    return result


def level_summary(result):
    real = ("—" if result["real_ci95"] is None else
            f"{result['real']:+g} [{result['real_ci95'][0]:+g}, "
            f"{result['real_ci95'][1]:+g}]")
    line = (f"sim vs real level: {result['verdict']} (sim {result['sim']:+g} bb/100 "
            f"for {result['live']} on {','.join(result['pool'] or ['?'])}; real "
            f"{real} on {result['hands']} hands played as advised, luck out; "
            f"needs {MIN_LEVEL_HANDS} hands")
    if result["always_valid_ci95"] is not None:
        wide = result["always_valid_ci95"]
        line += (f"; always-valid [{wide[0]:+g}, {wide[1]:+g}], sim "
                 f"{'outside' if result['outside_always_valid'] else 'inside'} it")
    return line + ")"


def read_lines(paths):
    return [line for path in paths or () for line in load(path)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sim", type=Path, required=True)
    parser.add_argument("--frames", nargs="+", type=Path,
                        help="logs for the order of the variants")
    parser.add_argument("--real-hands", nargs="+", type=Path,
                        help="hand lines (luck_results --lines, tester_review) "
                             "for the level of --live")
    parser.add_argument("--real-decisions", nargs="+", type=Path,
                        help="their decision lines (which advice was rough)")
    parser.add_argument("--live", default=LIVE)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if not args.frames and not args.real_hands:
        parser.error("give --frames, --real-hands or both")
    sim = json.loads(args.sim.read_text(encoding="utf-8"))
    results = {}
    if args.frames:
        paths = [path for path in args.frames if not HOLDOUT.search(log_name(path))]
        with ProcessPoolExecutor(args.workers) as executor:
            found = [spot for part in executor.map(log_spots, paths) for spot in part]
        results["rank"] = rank(sim, found, workers=args.workers)
        print(summary(results["rank"]))
    if args.real_hands:
        values = advised(read_lines(args.real_hands), read_lines(args.real_decisions))
        results["level"] = level(sim, values, args.live)
        print(level_summary(results["level"]))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        for name, result in results.items():
            (args.out / f"{name}.json").write_text(json.dumps(result, indent=1) + "\n",
                                                   encoding="utf-8")


if __name__ == "__main__":
    main()
