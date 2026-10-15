"""Refit the "AA 校准桌" (``aa_cal``) on new recordings, keeping it only if better.

    PYTHONPATH=src:. .venv/bin/python tools/refit_aa_cal.py \\
        --frames <log>.jsonl.gz [...] [--workers 4] --out <dir> [--apply]

The package (``aa_cal_stats_v1.json``) holds the AA numbers, the parameters
fitted on them (``fitted``) and the recordings both came from (``logs``, with
their minutes). Every log given that is not among them is new; the logs it
was made on must all be given too.

1. The new logs are split into two halves of about as many replayable hands
   (``tools/sim_fidelity.py`` replays them; the action history is rebuilt by
   the current reader first, as ``tools/replay_aa_action_history.py`` does).
2. For each half, a candidate is made without it: the numbers of every other
   log, and the parameters of ``tools/fit_aa_cal.py`` (variant ``all``)
   fitted on their hands from the package's. The candidate and the package
   are then scored on that half, which neither has seen (log loss of the
   actions and the cards shown, ``scoreboard.fidelity``).
3. Only if the candidate is lower on both halves is the package replaced:
   numbers and parameters made on every log. Otherwise it stays as it is and
   the new logs stay new, to be tried again with more of them.

Too few new hands (``MIN_HALF_HANDS`` in each half) also keeps the package.
The 9 September recording kept for acceptance is never read.

Writes ``<out>/refit.json`` (losses and parameters, aggregates only) and, when
accepted, ``<out>/aa_cal_stats_v1.json``; ``--apply`` also writes that into the
package. Prints one line with the verdict.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.scoreboard.calibrated import STATS_FILE, cal_stats  # noqa: E402
from tools.aa_population_stats import build as build_counts, reduce_log  # noqa: E402
from tools.build_aa_real_stats import build as keep_stats  # noqa: E402
from tools.fit_aa_cal import VARIANTS, fit, losses, prepare  # noqa: E402
from tools.replay_aa_action_history import replay  # noqa: E402
from tools.sim_fidelity import load, log_name, log_tasks, seated  # noqa: E402

PACKAGE = (Path(__file__).resolve().parents[1] / "src" / "poker_engine"
           / "scoreboard" / STATS_FILE)
HOLDOUT = re.compile(r"20260909[_-]?031030")   # the acceptance recording
MIN_HALF_HANDS = 50
KEYS = VARIANTS["all"]


def read_log(path):
    """What the fit needs of one log, its action history rebuilt: the hands
    that replay, the hands counted into numbers, minutes, and whether you sat."""
    name = log_name(path)
    rows = replay(load(path))
    pts = [row["pts_seconds"] for row in rows if row.get("pts_seconds") is not None]
    return {"name": name, "tasks": log_tasks(name, rows)[0],
            "hands": reduce_log(rows, name),
            "minutes": round((max(pts) - min(pts)) / 60, 2) if pts else 0.0,
            "seated": seated([row for row in rows if row.get("fields")])}


def halves(hands_by_log):
    """The logs in two groups of about as many hands: the biggest first, each
    to the group with fewer so far (ties by name, then the first group)."""
    groups, counts = ([], []), [0, 0]
    for name in sorted(hands_by_log, key=lambda name: (-hands_by_log[name], name)):
        side = 0 if counts[0] <= counts[1] else 1
        groups[side].append(name)
        counts[side] += hands_by_log[name]
    return [sorted(group) for group in groups], counts


def numbers(logs, names):
    """The AA numbers of ``names``, as ``tools/fit_aa_cal.py`` makes them."""
    hands = [hand for name in names for hand in logs[name]["hands"]]
    heroes = {name for name in names if logs[name]["seated"]}
    return keep_stats(build_counts(hands, heroes,
                                   {name: logs[name]["minutes"] for name in names}))


def package(stats, params, logs, names):
    return {**stats, "fitted": params,
            "logs": {name: logs[name]["minutes"] for name in sorted(names)}}


def better(candidate, incumbent):
    """Accept only when the candidate is lower on every held-out half."""
    return all(candidate[half]["total"] < incumbent[half]["total"]
               for half in incumbent)


def refit(paths, incumbent, workers=1):
    """The verdict and, when accepted, the new package."""
    refused = sorted(log_name(path) for path in paths if HOLDOUT.search(log_name(path)))
    paths = [path for path in paths if not HOLDOUT.search(log_name(path))]
    with ProcessPoolExecutor(workers) as executor:
        logs = {log["name"]: log for log in executor.map(read_log, paths)}
    old = dict(incumbent["logs"])
    missing = sorted(set(old) - set(logs))
    if missing:
        raise SystemExit("missing logs the package was made on: " + ", ".join(missing))
    for name, minutes in old.items():
        logs[name]["minutes"] = minutes
    tasks = {name: logs[name]["tasks"] for name in sorted(logs)}
    new = sorted(set(logs) - set(old))
    groups, counts = halves({name: len(tasks[name]) for name in new})
    result = {"logs": len(old), "new": new, "refused": refused,
              "halves": [{"logs": group, "hands": count}
                         for group, count in zip(groups, counts)]}
    if min(counts) < MIN_HALF_HANDS:
        result.update(verdict="kept", why=f"fewer than {MIN_HALF_HANDS} new hands "
                                          "in a half")
        return result, None
    current = {key: value for key, value in incumbent.items()
               if key not in ("fitted", "logs")}
    versions = {"incumbent": current}
    for index, group in enumerate(groups, 1):
        versions[f"without_{index}"] = numbers(logs, sorted(set(logs) - set(group)))
    versions["all"] = numbers(logs, sorted(logs))
    jobs = [(task, versions) for name in sorted(tasks) for task in tasks[name]]
    print(f"{len(jobs)} hands; preparing", file=sys.stderr)
    with ProcessPoolExecutor(workers) as executor:
        hands = list(executor.map(prepare, jobs, chunksize=2))
    scores = {"incumbent": {}, "candidate": {}}
    for index, group in enumerate(groups, 1):
        version = f"without_{index}"
        train = [hand for hand in hands if hand["where"]["log"] not in group]
        test = [hand for hand in hands if hand["where"]["log"] in group]
        params, _ = fit(train, version, versions[version], KEYS,
                        start=incumbent["fitted"], workers=workers)
        half = f"half_{index}"
        scores["incumbent"][half] = losses(test, incumbent["fitted"], "incumbent",
                                           current)
        scores["candidate"][half] = {"params": params,
                                     **losses(test, params, version, versions[version])}
        print(f"{half}: {scores['incumbent'][half]['total']} -> "
              f"{scores['candidate'][half]['total']}", file=sys.stderr)
    result["scores"] = scores
    if not better(scores["candidate"], scores["incumbent"]):
        result.update(verdict="kept", why="not better on both halves")
        return result, None
    params, _ = fit(hands, "all", versions["all"], KEYS, start=incumbent["fitted"],
                    workers=workers)
    result.update(verdict="accepted", fitted=params, hands=len(hands))
    return result, package(versions["all"], params, logs, sorted(logs))


def summary(result):
    """The one line for the report."""
    halves_text = "; ".join(
        f"{half} {result['scores']['incumbent'][half]['total']} -> "
        f"{result['scores']['candidate'][half]['total']}"
        for half in result.get("scores", {}).get("incumbent", {}))
    new = sum(item["hands"] for item in result["halves"])
    why = result.get("why", "better on both halves")
    head = (f"aa_cal refit: {result['verdict']} ({why}); {result['logs']} logs + "
            f"{len(result['new'])} new ({new} hands)")
    return head + (f"; held-out loss old -> new: {halves_text}" if halves_text else "")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", nargs="+", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true",
                        help="write an accepted package into src/")
    args = parser.parse_args(argv)
    result, new = refit(args.frames, cal_stats(), workers=args.workers)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "refit.json").write_text(json.dumps(result, indent=1) + "\n",
                                         encoding="utf-8")
    if new is not None:
        text = json.dumps(new, indent=1, ensure_ascii=False) + "\n"
        (args.out / STATS_FILE).write_text(text, encoding="utf-8")
        if args.apply:
            PACKAGE.write_text(text, encoding="utf-8")
    print(summary(result))


if __name__ == "__main__":
    main()
