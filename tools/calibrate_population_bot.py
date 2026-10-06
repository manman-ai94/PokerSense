"""Calibrate the population bot's postflop thresholds by simulation.

Eight population bots play the AA table; the equity each had at every kind
of postflop decision is recorded and turned into 101 quantiles per spot, so
that "bet 71% of the time" can be read as "bet with the top 71%". The first
pass starts from a flat guess, each further pass from the previous result.
A final pass only measures how often the calibrated bot bets, calls, raises
and folds, next to the real players' frequencies. ``--preflop-check`` only
measures the same for its preflop decisions, which need no calibration.

    PYTHONPATH=src:. .venv/bin/python tools/calibrate_population_bot.py \\
        [--hands 80000] [--passes 5] [--workers 8] [--preflop-check]
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import re

PACKAGE = Path(__file__).resolve().parents[1] / "src/poker_engine/scoreboard"
OUT = PACKAGE / "population_bot_v1.json"
RULES = (Path(__file__).resolve().parents[1]
         / "configs/game/aa-scoreboard-rules-v1.json")
MIN_SAMPLES = 100


def play(seeds, preflop=False):
    """(spot, equity, action) for every postflop decision in these deals.

    With ``preflop``, (spot, None, action) for every preflop decision instead,
    the spot being the real-player row the bot took its shares from.
    """
    from poker_engine.scoreboard.population import (PopulationBot, actions,
                                                    population_stats, stats_position)
    from poker_engine.scoreboard.spots import preflop_spot
    from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
    from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules)
    records = []
    bot = PopulationBot(recorder=None if preflop else records)
    for seed in seeds:
        arena.reset(seed)
        deciders = {seat: bot.for_game(f"calibration:{seed}:{seat}")
                    for seat in arena.occupied_seats}
        while not arena.terminal:
            seat = arena.actor
            observation = arena.observe(seat)
            action = deciders[seat](observation)
            if preflop and observation["street"] == "preflop":
                situation = preflop_spot(actions(observation, "preflop"), seat)
                spot = f"{stats_position(observation)}|{situation}"
                if spot not in population_stats():
                    spot = f"ALL|{situation}"
                kind = ("raise" if action.startswith("raise_to") else
                        "fold" if action == "fold" else "call")
                records.append((spot, None, kind))
            arena.step(action)
    return records


def simulate(hands, workers, first_seed, preflop=False):
    seeds = list(range(first_seed, first_seed + hands))
    parts = [seeds[i::workers * 4] for i in range(workers * 4)]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return [row for part in executor.map(play, parts, [preflop] * len(parts))
                for row in part]


def quantiles(records):
    """101 equity quantiles per spot, plus the pooled spots ``fallbacks`` names."""
    from poker_engine.scoreboard.population import fallbacks
    by_spot = defaultdict(list)
    for spot, win, _ in records:
        for key in (spot, *fallbacks(spot)):
            by_spot[key].append(win)
    result = {}
    for spot, values in sorted(by_spot.items()):
        if len(values) < MIN_SAMPLES:
            continue
        values.sort()
        result[spot] = [round(values[int(i / 100 * (len(values) - 1))], 4)
                        for i in range(101)]
    return result, {spot: len(values) for spot, values in by_spot.items()}


def dump(data):
    """JSON with every list of numbers on one line, so the file stays readable."""
    text = json.dumps(data, indent=1)

    def one_line(match):
        return "[" + " ".join(match.group(1).split()) + "]"
    return re.sub(r"\[\s+([-0-9.e,\s]+?)\s+\]", one_line, text) + "\n"


def write(table, samples, hands, passes, check=()):
    OUT.write_text(dump({
        "schema_version": 1,
        "method": ("postflop equity quantiles of the population bot at each kind of "
                   "decision, from self-play on the AA scoreboard table"),
        "hands_per_pass": hands, "passes": passes, "min_samples": MIN_SAMPLES,
        "samples": samples, "quantiles": table,
        "check": list(check)}), encoding="utf-8")


def measured(records):
    """How often the bot took each decision per spot, next to the real players."""
    from poker_engine.scoreboard.population import population_stats
    stats = population_stats()
    counts = defaultdict(Counter)
    for spot, _, action in records:
        counts[spot][action] += 1
    rows = []
    for spot, actions in sorted(counts.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(actions.values())
        target = stats.get(spot, {})
        choices = ("bet", "check", "fold", "call", "raise")
        rows.append({"spot": spot, "n": n,
                     "bot": {a: round(c / n, 3) for a, c in sorted(actions.items())},
                     "players": {a: round(target[a], 3) for a in choices
                                 if a in target}})
    return rows


def largest_gap(row):
    """Largest difference between the bot's and the players' share of a decision."""
    choices = set(row["bot"]) | set(row["players"])
    return max(abs(row["bot"].get(a, 0) - row["players"].get(a, 0)) for a in choices)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hands", type=int, default=80000)
    parser.add_argument("--passes", type=int, default=5)
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 1) - 2))
    parser.add_argument("--preflop-check", action="store_true",
                        help="only measure the preflop shares against the players'")
    args = parser.parse_args(argv)
    if args.preflop_check:
        rows = measured(simulate(args.hands, args.workers, 98_000_000, preflop=True))
        for row in rows:
            print(f"{row['spot']:<22} {row['n']:>7}  gap {largest_gap(row):.3f}  "
                  f"bot {row['bot']}  players {row['players']}")
        return
    flat = {"flop|hu": [i / 100 for i in range(101)],
            "flop|multi": [i / 100 for i in range(101)]}
    for street in ("turn", "river"):
        for width in ("hu", "multi"):
            flat[f"{street}|{width}"] = [i / 100 for i in range(101)]
    write(flat, {}, 0, 0)
    for number in range(1, args.passes + 1):
        records = simulate(args.hands, args.workers, number * 10_000_000)
        gaps = [(row["n"], largest_gap(row)) for row in measured(records)]
        common = [gap for n, gap in gaps if n >= 1000]
        table, samples = quantiles(records)
        write(table, samples, args.hands, number)
        print(f"pass {number}: {len(records)} decisions, {len(table)} quantile tables; "
              f"largest gap where n >= 1000: {max(common):.3f}")
    check = measured(simulate(args.hands, args.workers, 99_000_000))
    write(table, samples, args.hands, args.passes, check)
    for row in check:
        print(f"{row['spot']:<32} {row['n']:>7}  gap {largest_gap(row):.3f}  "
              f"bot {row['bot']}  players {row['players']}")


if __name__ == "__main__":
    main()
