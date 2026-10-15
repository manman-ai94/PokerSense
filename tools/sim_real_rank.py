"""Does the simulation put strategy variants in the order the shown cards do?

    PYTHONPATH=src:. .venv/bin/python tools/sim_real_rank.py \\
        --sim <scoreboard>.json --frames <log>.jsonl.gz [...] \\
        [--workers 4] [--out <dir>]

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
from poker_engine.scoreboard.bots import make_policy  # noqa: E402
from tools.aa_compare_advice import chips, shown_spot, turns  # noqa: E402
from tools.replay_aa_action_history import replay  # noqa: E402
from tools.sim_fidelity import load, log_name  # noqa: E402

HOLDOUT = re.compile(r"20260909[_-]?031030")   # the acceptance recording
AGREE = 0.5          # tau: three pairs in four in the same order
MIN_VARIANTS = 8     # besides the reference
MIN_TURNS = 30


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sim", type=Path, required=True)
    parser.add_argument("--frames", nargs="+", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    sim = json.loads(args.sim.read_text(encoding="utf-8"))
    paths = [path for path in args.frames if not HOLDOUT.search(log_name(path))]
    with ProcessPoolExecutor(args.workers) as executor:
        found = [spot for part in executor.map(log_spots, paths) for spot in part]
    result = rank(sim, found, workers=args.workers)
    print(summary(result))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "rank.json").write_text(json.dumps(result, indent=1) + "\n",
                                            encoding="utf-8")


if __name__ == "__main__":
    main()
