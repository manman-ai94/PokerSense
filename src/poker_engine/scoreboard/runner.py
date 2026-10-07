"""Run the scoreboard: every strategy plays the same deals from every seat.

For each deal (one shuffled deck) the opponents' styles are spread over the
eight seats; each strategy then takes each seat in turn against that lineup,
with the same cards. A deal's score for a strategy is its average over the
eight seats, so card luck and seat luck largely cancel, and comparisons
between strategies use exactly the same cards and opponents. All-in hands are
scored by their expected result (see ``allin_ev``).

Results are reported in big blinds per 100 hands with a 95% interval computed
over deals, which are independent of each other.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import math
import random
from statistics import fmean, stdev
import time

from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

from .allin_ev import runout_ev
from .bots import make_policy

# Opponent pools by name. "population" plays like real players (see
# population.py) and is the default; "aa" like them but as loose before the
# flop as AA players; "styles" is the first version's mix.
POOLS = {"population": ("population",), "aa": ("aa_population",),
         "styles": ("tag", "lag", "rock", "station")}
DEFAULT_POOL = POOLS["population"]
MAX_ACTIONS = 400


def lineup(seed, pool, seats):
    """Opponent style per seat for one deal: the pool repeated, then shuffled."""
    styles = [pool[i % len(pool)] for i in range(len(seats))]
    random.Random(seed * 1_000_003 + 17).shuffle(styles)
    return dict(zip(seats, styles))


def _salt(base_seed, seed, seat):
    return hashlib.sha256(f"{base_seed}:{seed}:{seat}".encode()).hexdigest()


def play_hand(arena, seed, deciders, hero, *, all_in_ev=True):
    """Hero's result in chips and whether the all-in EV replaced the runout."""
    arena.reset(seed)
    actions = 0
    while not arena.terminal:
        actions += 1
        if actions > MAX_ACTIONS:
            raise RuntimeError("hand did not finish")
        seat = arena.actor
        arena.step(deciders[seat](arena.observe(seat)))
    if all_in_ev:
        expected = runout_ev(arena, seed=seed)
        if expected is not None:
            return expected[hero], True
    return float(arena.terminal_returns()[hero]), False


def score_deals(rules_dict, strategies, pool, seeds, base_seed, all_in_ev=True):
    """Per deal and strategy: (average result in big blinds, all-in hands).

    Also returns, per strategy that keeps them, the counts of how it decided
    (for example how often a solver strategy fell back to its base policy).
    """
    rules = AARuleProfileV2.from_dict(rules_dict)
    arena = AAFullHandArena(rules)
    seats = arena.occupied_seats
    big_blind = float(rules.big_blind)
    bots = {name: make_policy(name) for name in {*strategies, *pool}}
    rows = []
    for seed in seeds:
        styles = lineup(seed, pool, seats)
        bound = {seat: bots[styles[seat]].for_game(_salt(base_seed, seed, seat))
                 for seat in seats}
        row = {}
        for name in strategies:
            total, adjusted = 0.0, 0
            for hero in seats:
                deciders = dict(bound)
                deciders[hero] = bots[name].for_game(_salt(base_seed, seed, hero))
                value, was_adjusted = play_hand(arena, seed, deciders, hero,
                                                all_in_ev=all_in_ev)
                total += value
                adjusted += was_adjusted
            row[name] = (total / len(seats) / big_blind, adjusted)
        rows.append((seed, row))
    counts = {name: dict(bots[name].counts) for name in strategies
              if getattr(bots[name], "counts", None)}
    return rows, counts


def _interval(values):
    mean = fmean(values)
    half = 1.96 * stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
    return mean, half


def summarize(rows, strategies, reference, seats):
    """bb/100 with 95% intervals, and each strategy minus the reference."""
    per = {name: [row[name][0] for _, row in rows] for name in strategies}
    summary = {}
    for name in strategies:
        mean, half = _interval(per[name])
        adjusted = sum(row[name][1] for _, row in rows)
        summary[name] = {
            "bb_per_100": round(mean * 100, 2),
            "ci95": None if half is None else [round((mean - half) * 100, 2),
                                               round((mean + half) * 100, 2)],
            "hands": len(rows) * seats,
            "all_in_ev_share": round(adjusted / (len(rows) * seats), 4)}
    versus = {}
    if reference in per:
        for name in strategies:
            if name == reference:
                continue
            diff = [a - b for a, b in zip(per[name], per[reference])]
            mean, half = _interval(diff)
            versus[name] = {
                "delta_bb_per_100": round(mean * 100, 2),
                "ci95": None if half is None else [round((mean - half) * 100, 2),
                                                   round((mean + half) * 100, 2)]}
    return summary, versus


def pairwise(rows, strategies):
    """Every pair of strategies compared on the same deals: first minus second."""
    per = {name: [row[name][0] for _, row in rows] for name in strategies}
    result = {}
    for index, first in enumerate(strategies):
        for second in strategies[index + 1:]:
            mean, half = _interval([a - b for a, b in zip(per[first], per[second])])
            result[f"{first} - {second}"] = {
                "delta_bb_per_100": round(mean * 100, 2),
                "ci95": None if half is None else [round((mean - half) * 100, 2),
                                                   round((mean + half) * 100, 2)]}
    return result


def run_scoreboard(rules, strategies, *, deals, pool=DEFAULT_POOL, workers=1,
                   base_seed=1, reference=None, all_in_ev=True, chunk=None,
                   progress=None):
    """Score ``strategies`` over ``deals`` deals; same arguments, same result.

    ``progress(done, total, seconds)`` is called after each batch of deals.
    """
    if not strategies or deals < 2:
        raise ValueError("need at least one strategy and two deals")
    rules_dict = rules.to_dict()
    seeds = [base_seed * 1_000_000 + i for i in range(deals)]
    # Small batches keep every worker busy to the end (slow strategies vary a lot).
    chunk = chunk or max(2, deals // (max(1, workers) * 32))
    chunks = [seeds[i:i + chunk] for i in range(0, len(seeds), chunk)]
    started = time.perf_counter()
    args = [(rules_dict, tuple(strategies), tuple(pool), part, base_seed, all_in_ev)
            for part in chunks]
    results = []

    def finished(result):
        results.append(result)
        if progress:
            progress(len(results), len(args), time.perf_counter() - started)

    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            for future in as_completed([executor.submit(score_deals, *arg)
                                        for arg in args]):
                finished(future.result())
    else:
        for arg in args:
            finished(score_deals(*arg))
    rows = sorted((row for part, _ in results for row in part), key=lambda r: r[0])
    counts = {}
    for _, part in results:
        for name, values in part.items():
            merged = counts.setdefault(name, {})
            for key, value in values.items():
                merged[key] = merged.get(key, 0) + value
    seats = rules.table_size
    reference = reference or strategies[0]
    summary, versus = summarize(rows, strategies, reference, seats)
    return {
        "schema_version": 1,
        "rules": rules_dict,
        "pool": list(pool),
        "deals": deals,
        "hands_per_strategy": deals * seats,
        "all_in_ev": all_in_ev,
        "base_seed": base_seed,
        "strategies": summary,
        "reference": reference,
        "versus_reference": versus,
        "pairwise": pairwise(rows, strategies),
        "decision_counts": counts,
        # Average big blinds per hand of each strategy on each deal, so any
        # later comparison can be made from the saved file.
        "per_deal": [[seed, {name: round(row[name][0], 6) for name in strategies}]
                     for seed, row in rows],
        "seconds": round(time.perf_counter() - started, 1),
        "workers": workers,
        "method": ("same deal from every seat against a shuffled lineup of the pool; "
                   "95% interval over deals (normal approximation)"),
    }


__all__ = ["DEFAULT_POOL", "POOLS", "lineup", "pairwise", "play_hand", "run_scoreboard",
           "score_deals", "summarize"]
