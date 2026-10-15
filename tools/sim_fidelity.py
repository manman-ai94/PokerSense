"""How much the scoreboard's opponents play like the AA players on recordings.

Every hand of the frame logs that replays on the AA table (as the range
reading and ``tools/aa_range_exclusion.py`` replay it) is put to each pool's
opponent model, seat by seat (``scoreboard.fidelity``): the model's forecast
of every real decision, and how well its play explains the cards shown at
the end. Your own seat is never scored: a log in which your cards were read
is one you sat in, and seat 4 there is you (``--spectated`` names logs to
score seat 4 in anyway). Decisions on a street where the replay had to fill
in a seat's missed action are not scored for that seat.

    PYTHONPATH=src:. .venv/bin/python tools/sim_fidelity.py \\
        --frames <recording>/frames.jsonl [...] --pools aa_real,noisy,aa \\
        [--group early=<log>,<log>] [--workers 4] --out <dir>

Writes ``<out>/summary.json``: per pool (and per ``--group`` of logs) the log
losses and tables of ``fidelity.summarize``, aggregates only. The per-decision
lines (``<out>/decisions-<pool>.jsonl``, with hand ids) stay private, like the
logs. A log's name is its folder's name (``<name>/frames.jsonl``) or the file's.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_solver_input import (  # noqa: E402
    HERO, hand_facts, replay_hand, starting_stacks)
from poker_engine.scoreboard.bots import make_policy  # noqa: E402
from poker_engine.scoreboard.fidelity import score_hand, summarize  # noqa: E402
from tools.aa_range_exclusion import hands_in_order, shown_seats  # noqa: E402

POOLS = {"aa_real": "aa_real", "noisy": "noisy+aa_real", "aa": "aa_population",
         "population": "population", "aa_cal": "aa_cal"}


def load(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def log_name(path):
    path = Path(path)
    if path.name.startswith("frames.jsonl"):
        return path.parent.name
    return path.name.split(".")[0]


def seated(rows):
    """Whether your cards were read in the log: you sat at the table."""
    return any(all((row.get("fields") or {}).get("hero") or [None]) for row in rows)


def replayed(facts):
    """The hand's table after every action read and the actions the replay
    filled in, or None (as ``aa_range_exclusion.replayed``)."""
    if facts.get("complete") is not True:
        return None
    first = replay_hand(facts)
    if first["status"] != "ok":
        return None
    stacks = starting_stacks(facts, first)
    again = replay_hand({**facts, "dealer": first["dealer"]}, stacks)
    return again if again["status"] == "ok" else None


def hand_table(rows, stakes=None):
    """(replay, whole) with all the hand's rows, else the most of them that
    replay (cut where an action or a board card was read); (None, False)."""
    cuts, seen = [], None
    for index, row in enumerate(rows):
        fields = row["fields"]
        mark = (len((fields.get("actions_v1") or {}).get("actions") or ()),
                sum(1 for card in fields.get("board") or () if card))
        if mark != seen:
            seen = mark
            cuts.append(index + 1)
    for end in [len(rows)] + list(reversed(cuts)):
        try:
            found = replayed(hand_facts(rows[:end], stakes))
        except Exception:              # a log the replay cannot take: try less
            found = None
        if found is not None:
            return found, end == len(rows)
    return None, False


def hero_cards(rows):
    cards = [row["fields"].get("hero") for row in rows
             if all(row["fields"].get("hero") or [None])]
    return tuple(cards[-1]) if cards else ()


def log_tasks(name, rows, *, spectated=False):
    """The scoring jobs of one log: (where, observation, skip, shown, dead)."""
    rows = [row for row in rows if row.get("fields")]
    sat = seated(rows) and not spectated
    tasks, stakes, skipped = [], None, {}
    for hand_id, hand in hands_in_order(rows):
        found, whole = hand_table(hand, stakes)
        if found is None:
            skipped["no_replay"] = skipped.get("no_replay", 0) + 1
        else:
            arena = found["arena"]
            observation = arena.observe(arena.occupied_seats[0])
            skip = {HERO} if sat else set()
            skip |= {(action["slot"], action["street"]) for action in found["inferred"]}
            shown = shown_seats(hand) if whole else {}
            shown = {seat: cards for seat, cards in shown.items()
                     if seat in observation["occupied_seats"]
                     and seat not in observation["folded"] and seat not in skip}
            dead = hero_cards(hand) if sat else ()
            tasks.append(({"log": name, "hand_id": hand_id}, observation, skip,
                          shown, dead))
        try:
            facts = hand_facts(hand, stakes)
        except Exception:
            continue
        if facts["stakes"].get("source") == "table":
            stakes = facts["stakes"]
    return tasks, skipped


_MODELS = {}


def _score(job):
    pool, (where, observation, skip, shown, dead) = job
    model = _MODELS.get(pool)
    if model is None:
        model = _MODELS[pool] = make_policy(POOLS.get(pool, pool))
    decisions, cards = score_hand(observation, model, skip=skip, shown=shown,
                                  dead=dead)
    return ([{**where, **record} for record in decisions],
            [{**where, **record} for record in cards])


def score_pool(pool, tasks, workers=1):
    jobs = [(pool, task) for task in tasks]
    if workers > 1:
        with ProcessPoolExecutor(workers) as executor:
            results = list(executor.map(_score, jobs, chunksize=4))
    else:
        results = [_score(job) for job in jobs]
    decisions = [record for found, _ in results for record in found]
    cards = [record for _, found in results for record in found]
    return decisions, cards


def report(decisions, cards, groups):
    result = {"all": summarize(decisions, cards)}
    for name, logs in groups.items():
        result[name] = summarize([d for d in decisions if d["log"] in logs],
                                 [c for c in cards if c["log"] in logs])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", nargs="+", type=Path, required=True)
    parser.add_argument("--pools", default="aa_real,noisy,aa,population")
    parser.add_argument("--group", action="append", default=[],
                        help="NAME=log,log: also report these logs alone")
    parser.add_argument("--spectated", default="",
                        help="logs to score seat 4 in although your cards show")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    groups = {name: set(logs.split(",")) for name, _, logs in
              (item.partition("=") for item in args.group)}
    spectated = set(filter(None, args.spectated.split(",")))
    tasks, sources = [], []
    for path in args.frames:
        name = log_name(path)
        found, skipped = log_tasks(name, load(path), spectated=name in spectated)
        tasks += found
        sources.append({"log": name, "hands": len(found), "skipped": skipped})
        print(f"{name}: {len(found)} hands", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {"sources": sources, "hands": len(tasks), "pools": {}}
    for pool in filter(None, args.pools.split(",")):
        decisions, cards = score_pool(pool, tasks, args.workers)
        with (args.out / f"decisions-{pool}.jsonl").open("w", encoding="utf-8") as out:
            for record in decisions:
                out.write(json.dumps(record) + "\n")
        with (args.out / f"cards-{pool}.jsonl").open("w", encoding="utf-8") as out:
            for record in cards:
                out.write(json.dumps(record) + "\n")
        summary["pools"][pool] = report(decisions, cards, groups)
        overall = summary["pools"][pool]["all"]
        print(f"{pool}: {overall['decisions']['all']['n']} decisions, action loss "
              f"{overall['decisions']['all']['loss']:.3f}; cards "
              f"{overall.get('cards')}", file=sys.stderr)
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
