"""Run the scoreboard: every strategy plays the same deals from every seat.

For each deal (one shuffled deck) the opponents' styles are spread over the
eight seats; each strategy then takes each seat in turn against that lineup,
with the same cards. A deal's score for a strategy is its average over the
eight seats, so card luck and seat luck largely cancel, and comparisons
between strategies use exactly the same cards and opponents. All-in hands are
scored by their expected result (see ``allin_ev``).

Results are reported in big blinds per 100 hands with a 95% interval computed
over deals, which are independent of each other. Each strategy's result is
also split by how its hand reached the flop (``by_flop``): over before it
(folded, won, or all in before the flop), heads-up, or with two or more
opponents. The parts add up to the whole, and the split of the difference to
the reference shows where a strategy wins or loses. A second split
(``by_end``) is by where the hand ended for the strategy: the street it
folded on or won without a showdown, or the showdown (all-in hands included).
Losing without showdowns points at folding too much or bluffing into callers;
losing at showdowns at calling or betting too thin.

With ``mushroom`` the AA mushroom pool is played too (see ``mushroom``), and
each strategy's report says how often the small blind took the pool on its
tables (``mushroom_take``). The pool carried in from earlier hands is drawn
as if the small blind takes it ``mushroom.take`` of the time; where the
measured share differs much, the draws add or remove chips that no earlier
hand paid in (a table where the small blind wins half the pots carries far
less than the default assumes), so the run should be repeated with the
measured share (``run_gauntlet.py`` does this itself).
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import math
import random
from statistics import fmean, stdev
import time
from typing import NamedTuple

from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

from .allin_ev import runout_ev
from .bots import make_policy
from .mushroom import Mushroom, main_pot_shares, pool_result, small_blind

# Opponent pools by name. "population" plays like real players (see
# population.py) and is the default; "aa" like them but as loose before the
# flop as AA players; "styles" is the first version's mix. The tougher ones
# (opponents.py): "reg", "maniac" and "nit" alone, "tough" all three next to
# AA players; "mirror" is the AI itself; "solver" regulars that play heads-up
# turns and rivers with TexasSolver (installed solver only, slow).
POOLS = {"population": ("population",), "aa": ("aa_population",),
         "styles": ("tag", "lag", "rock", "station"),
         "reg": ("reg",), "maniac": ("maniac",), "nit": ("nit",),
         "tough": ("reg", "maniac", "nit", "aa_population"),
         "mirror": ("range_multiway+aa_preflop",),
         "solver": ("solver_turn+reg",)}
DEFAULT_POOL = POOLS["population"]
MAX_ACTIONS = 400
FLOP = ("preflop", "heads_up", "multiway")      # how a hand reached the flop
END = ("preflop", "flop", "turn", "river", "showdown")   # where it ended


def lineup(seed, pool, seats):
    """Opponent style per seat for one deal: the pool repeated, then shuffled."""
    styles = [pool[i % len(pool)] for i in range(len(seats))]
    random.Random(seed * 1_000_003 + 17).shuffle(styles)
    return dict(zip(seats, styles))


def _salt(base_seed, seed, seat):
    return hashlib.sha256(f"{base_seed}:{seed}:{seat}".encode()).hexdigest()


def ended(observation, hero):
    """Where a finished hand ended for ``hero`` (one of ``END``)."""
    history = observation["public_history"]
    if hero in observation["folded"]:
        return next(row["street"] for row in reversed(history)
                    if row["actor"] == hero and row["kind"] == "fold")
    if len(observation["occupied_seats"]) - len(observation["folded"]) > 1:
        return "showdown"
    return history[-1]["street"]


class Hand(NamedTuple):
    value: float            # hero's result in chips
    adjusted: bool          # the all-in EV replaced the runout
    flop: str               # how the hand reached the flop for hero (``FLOP``)
    end: str                # where it ended for hero (``END``)
    small_blind: float      # the small blind's share of the main pot (0 without
    #                         a mushroom pool): how often it takes the pool


def play_hand(arena, seed, deciders, hero, *, all_in_ev=True, mushroom=None):
    """One hand from ``hero``'s seat, as a ``Hand``."""
    arena.reset(seed)
    if mushroom is not None:
        post, carried = mushroom.pool(seed, float(arena.rules.big_blind))
        pool = f"{carried + post:g}"
    actions = 0
    flop, reached = "preflop", False
    while not arena.terminal:
        actions += 1
        if actions > MAX_ACTIONS:
            raise RuntimeError("hand did not finish")
        seat = arena.actor
        observation = arena.observe(seat)
        if mushroom is not None:
            observation["mushroom_pool"] = pool
        if not reached and observation["street"] != "preflop":
            reached = True                  # the first decision after the flop
            if hero not in observation["folded"]:
                live = len(observation["occupied_seats"]) - len(observation["folded"])
                flop = "heads_up" if live == 2 else "multiway"
        arena.step(deciders[seat](observation))
    expected = runout_ev(arena, seed=seed, main_pot=True) if all_in_ev else None
    if expected is not None:
        (returns, shares), adjusted = expected, True
    else:
        returns, adjusted = arena.terminal_returns(), False
        shares = main_pot_shares(arena) if mushroom is not None else {}
    value, taken = float(returns[hero]), 0.0
    if mushroom is not None:
        value += pool_result(arena, mushroom, carried, post, hero, shares)
        taken = shares.get(small_blind(arena), 0.0)
    return Hand(value, adjusted, flop, ended(arena.observe(hero), hero), taken)


def score_deals(rules_dict, strategies, pool, seeds, base_seed, all_in_ev=True,
                mushroom=None):
    """Per deal and strategy: (average result in big blinds, all-in hands).

    Also returns, per strategy that keeps them, the counts of how it decided
    (for example how often a solver strategy fell back to its base policy).
    """
    rules = AARuleProfileV2.from_dict(rules_dict)
    arena = AAFullHandArena(rules)
    seats = arena.occupied_seats
    big_blind = float(rules.big_blind)
    mushroom = None if mushroom is None else Mushroom(**mushroom)
    bots = {name: make_policy(name) for name in {*strategies, *pool}}
    rows = []
    for seed in seeds:
        styles = lineup(seed, pool, seats)
        bound = {seat: bots[styles[seat]].for_game(_salt(base_seed, seed, seat))
                 for seat in seats}
        row = {}
        for name in strategies:
            total, adjusted, taken = 0.0, 0, 0.0
            split = {part: [0.0, 0] for part in FLOP}
            end = {part: [0.0, 0] for part in END}
            for hero in seats:
                deciders = dict(bound)
                deciders[hero] = bots[name].for_game(_salt(base_seed, seed, hero))
                hand = play_hand(arena, seed, deciders, hero, all_in_ev=all_in_ev,
                                 mushroom=mushroom)
                total += hand.value
                adjusted += hand.adjusted
                taken += hand.small_blind
                for parts, part in ((split, hand.flop), (end, hand.end)):
                    parts[part][0] += hand.value
                    parts[part][1] += 1
            scale = len(seats) * big_blind
            row[name] = (total / scale, adjusted,
                         {part: (chips / scale, hands)
                          for part, (chips, hands) in split.items()},
                         {part: (chips / scale, hands)
                          for part, (chips, hands) in end.items()},
                         taken)
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


def flop_split(rows, strategies, reference, seats, index=2, parts=FLOP):
    """Each strategy's bb/100 from hands that ended before the flop, went to
    it heads-up or multiway (adding up to its whole result), with the share
    of its hands in each; and each part of its difference to the reference.

    ``index=3, parts=END`` splits by where the hand ended instead."""
    def part(name, flop):
        return [row[name][index][flop][0] for _, row in rows]

    split, versus = {}, {}
    for name in strategies:
        split[name] = {}
        for flop in parts:
            mean, half = _interval(part(name, flop))
            hands = sum(row[name][index][flop][1] for _, row in rows)
            split[name][flop] = {
                "bb_per_100": round(mean * 100, 2),
                "ci95": None if half is None else [round((mean - half) * 100, 2),
                                                   round((mean + half) * 100, 2)],
                "share": round(hands / (len(rows) * seats), 4)}
        if reference in strategies and name != reference:
            versus[name] = {}
            for flop in parts:
                mean, half = _interval([a - b for a, b in zip(
                    part(name, flop), part(reference, flop))])
                versus[name][flop] = {
                    "delta_bb_per_100": round(mean * 100, 2),
                    "ci95": None if half is None else [round((mean - half) * 100, 2),
                                                       round((mean + half) * 100, 2)]}
    return split, versus


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
                   progress=None, mushroom=None):
    """Score ``strategies`` over ``deals`` deals; same arguments, same result.

    ``mushroom``: None, or a ``Mushroom`` to play the AA mushroom pool.

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
    pool_rule = None if mushroom is None else {"post": mushroom.post,
                                               "take": mushroom.take}
    args = [(rules_dict, tuple(strategies), tuple(pool), part, base_seed, all_in_ev,
             pool_rule) for part in chunks]
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
    if mushroom is not None:
        for name in strategies:
            taken = sum(row[name][4] for _, row in rows)
            summary[name]["mushroom_take"] = round(taken / (len(rows) * seats), 4)
    for key, index, names in (("by_flop", 2, FLOP), ("by_end", 3, END)):
        split, split_versus = flop_split(rows, strategies, reference, seats,
                                         index, names)
        for name, parts in split.items():
            summary[name][key] = parts
        for name, parts in split_versus.items():
            versus[name][key] = parts
    return {
        "schema_version": 1,
        "rules": rules_dict,
        "pool": list(pool),
        "deals": deals,
        "hands_per_strategy": deals * seats,
        "all_in_ev": all_in_ev,
        "mushroom": None if mushroom is None else mushroom.to_dict(),
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


__all__ = ["DEFAULT_POOL", "END", "FLOP", "POOLS", "Hand", "ended", "flop_split",
           "lineup", "pairwise", "play_hand", "run_scoreboard", "score_deals",
           "summarize"]
