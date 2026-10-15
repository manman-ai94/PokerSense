"""Fit the "AA 校准桌" opponents (``scoreboard.calibrated``) on recordings.

    PYTHONPATH=src:. .venv/bin/python tools/fit_aa_cal.py \\
        --frames <recording>/frames.jsonl [...] \\
        --fold A=<log>,<log> --fold B=<log>,... \\
        [--minutes <log>=<minutes> ...] [--workers 4] --out <dir>

1. The logs' hands are counted into AA numbers as ``tools/aa_population_stats.py``
   counts them and kept as ``tools/build_aa_real_stats.py`` keeps them: from
   all logs, and from each fold alone.
2. Every hand that replays (as ``tools/sim_fidelity.py`` replays it) is
   prepared once: at each decision of each seat, the equity of every hand the
   seat could hold, as ``aa_cal`` works it out, and before the flop the band
   its earlier actions leave it.
3. The parameters (``calibrated.FITTED``) are fitted by maximum likelihood:
   the two log losses of ``scoreboard.fidelity`` (the actions and the cards
   shown) summed over every decision and shown hand, by a coordinate search
   over grids.
4. Each fold is scored with the parameters and numbers fitted on the other
   fold (out of sample), for three versions: the numbers only (every
   parameter 0, as ``aa_real`` on the new numbers), with the price (the
   slope only), and everything; and, to compare, ``aa_real`` as the
   scoreboard has it (its own numbers, no departures).

Writes ``<out>/fit.json`` (parameters and losses, aggregates only) and
``<out>/aa_cal_stats.json`` (the numbers of all logs, for the package).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.scoreboard.aa_real import (  # noqa: E402
    aa_stats, postflop_shares, preflop_band, preflop_shares)
from poker_engine.scoreboard.bots import (  # noqa: E402
    MAX_EQUITY_OPPONENTS, POSTFLOP_TRIALS, opponents_in_hand)
from poker_engine.scoreboard.calibrated import (  # noqa: E402
    FITTED, STREETS, checked_probs, facing_probs, preflop_probs)
from poker_engine.scoreboard.bots import _rng  # noqa: E402
from poker_engine.scoreboard.fidelity import FLOOR, SALT, options  # noqa: E402
from poker_engine.scoreboard.population import actions, postflop_situation  # noqa: E402
from poker_engine.scoreboard.replay import public_replay, with_hole  # noqa: E402
from poker_engine.scoreboard.spots import preflop_spot  # noqa: E402
from poker_engine.scoreboard.strength import combo_percentile, equity  # noqa: E402
from poker_engine.solver.texassolver import all_combos, combo_key  # noqa: E402
from tools.aa_population_stats import build as build_counts, reduce_log  # noqa: E402
from tools.build_aa_real_stats import build as keep_stats  # noqa: E402
from tools.sim_fidelity import load, log_name, log_tasks, seated  # noqa: E402

COMBOS = all_combos()
INDEX = {key: index for index, key in enumerate(COMBOS)}
CARDS = [(key[:2], key[2:]) for key in COMBOS]
PERCENTILE = np.array([combo_percentile(cards) for cards in CARDS])
KIND_INDEX = {"f": 0, "c": 1, "r": 2}
GRIDS = {"mix": (0.0, 0.03, 0.06, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8),
         "price_slope": (0.5, 0.0, -0.5, -1.0, -1.5, -2.0, -3.0),
         "slow": (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
         "bluff": (0.0, 0.03, 0.06, 0.1, 0.15, 0.2, 0.3, 0.4),
         "sticky": (0.0, 0.03, 0.06, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5)}
ROUNDS = 3


def zero_params():
    return {"mix": 0.0, "price_slope": 0.0,
            **{street: {"slow": 0.0, "bluff": 0.0, "sticky": 0.0}
               for street in STREETS}}


def blocked(cards):
    cards = set(cards)
    return np.array([a in cards or b in cards for a, b in CARDS])


# ------------------------------------------------------------------ prepare


def prepare(job):
    """One hand's decisions, with what every possible hand would face."""
    (where, observation, skip, shown, dead), versions = job
    prepared = []
    for decision in public_replay(observation):
        seat = decision.seat
        if seat in skip:
            continue
        seen = decision.observation
        can_fold, _, can_raise = (kind in options(seen) for kind in "fcr")
        item = {"seat": seat, "street": decision.street,
                "scored": (seat, decision.street) not in skip,
                "actual": KIND_INDEX[decision.kind], "can_fold": can_fold,
                "can_raise": can_raise, "blocked": blocked(seen["board"])}
        if decision.street == "preflop":
            spot = preflop_spot(actions(seen, "preflop"), seat)
            item["bands"] = {name: (*preflop_band(seen, aa=stats),
                                    *preflop_shares(seen, spot, aa=stats))
                             for name, stats in versions.items()}
        else:
            to_call = float(seen["to_call"] or 0)
            opponents = min(opponents_in_hand(seen), MAX_EQUITY_OPPONENTS)
            win = np.full(len(COMBOS), np.nan)
            for index, cards in enumerate(CARDS):
                if item["blocked"][index] or cards[0] in dead or cards[1] in dead:
                    continue
                # The draws ``fidelity`` gives the bot for this hand.
                hole = with_hole(seen, cards)
                win[index] = equity(hole["own_hole"], seen["board"], opponents,
                                    POSTFLOP_TRIALS, _rng(SALT, hole))
            item.update(spot=postflop_situation(seen), win=win,
                        price=(to_call / (float(seen["pot"]) + to_call)
                               if to_call else 0.0))
        prepared.append(item)
    board = observation["board"]
    return {"where": where, "decisions": prepared,
            "dead": blocked(dead), "final": blocked(board),
            "shown": {seat: INDEX[combo_key(cards)] for seat, cards in shown.items()
                      if not set(cards) & (set(board) | set(dead))}}


# ------------------------------------------------------------------ score


def decision_probs(item, params, version, stats):
    if item["street"] == "preflop":
        low, high, raise_share, call_share = item["bands"][version]
        width = high - low
        place = (PERCENTILE - low) / width if width > 0 else np.ones(len(COMBOS))
        base = np.where(place <= raise_share, 2,
                        np.where(place <= raise_share + call_share, 1, 0))
        return preflop_probs(base, raise_share, call_share, params["mix"],
                             item["can_fold"], item["can_raise"])
    street = params[item["street"]]
    row = postflop_shares(item["spot"], aa=stats)
    win = np.nan_to_num(item["win"], nan=0.0)
    if not item["price"]:
        return checked_probs(win, item["spot"], row.get("bet") or 0.35, street["slow"],
                             street["bluff"], item["can_raise"])
    return facing_probs(win, item["spot"], row.get("raise") or 0.1,
                        row.get("call") or 0.4, item["price"], street["slow"],
                        street["sticky"], params["price_slope"], item["can_raise"])


def score(hands, params, version, stats):
    """(action loss, decisions, cards loss, shown hands) summed over ``hands``."""
    action_loss = card_loss = 0.0
    decisions = cards = 0
    for hand in hands:
        start = (~hand["dead"]).astype(float)
        weights = {}
        for item in hand["decisions"]:
            weight = np.where(item["blocked"], 0.0, weights.get(item["seat"], start))
            if weight.sum() <= 0:            # the board emptied it: start again
                weight = np.where(item["blocked"], 0.0, start)
            probs = decision_probs(item, params, version, stats)
            total = weight.sum()
            if item["scored"]:
                forecast = weight @ probs / total
                kinds = [k for k, open_ in enumerate((item["can_fold"], True,
                                                      item["can_raise"])) if open_]
                mixed = (1 - FLOOR) * forecast[item["actual"]] + FLOOR / len(kinds)
                action_loss -= math.log(mixed)
                decisions += 1
            after = weight * probs[:, item["actual"]]
            weights[item["seat"]] = after if after.sum() > 0 else weight
        for seat, index in hand["shown"].items():
            weight = weights.get(seat)
            if weight is None:
                continue
            weight = np.where(hand["final"], 0.0, weight)
            if weight.sum() <= 0:
                weight = np.where(hand["final"], 0.0, start)
            count = int((~(hand["final"] | hand["dead"])).sum())
            share = weight[index] / weight.sum()
            card_loss -= math.log(((1 - FLOOR) * share + FLOOR / count) * count)
            cards += 1
    return action_loss, decisions, card_loss, cards


def total(hands, params, version, stats):
    found = score(hands, params, version, stats)
    return found[0] + found[2]


_JOB = {}


def _total(params):
    return total(*_JOB["hands"], params, *_JOB["version"])


def fit(hands, version, stats, names, start=None, workers=1):
    """Coordinate search over ``GRIDS`` for the parameters in ``names``; the
    values of one parameter are tried in parallel (forked workers share
    ``hands``)."""
    params = deepcopy(start or zero_params())
    _JOB.update(hands=(hands,), version=(version, stats))
    best = total(hands, params, version, stats)
    if not names:
        return params, best
    with ProcessPoolExecutor(workers) as executor:
        for _ in range(ROUNDS):
            moved = False
            for name in names:
                street, _, key = name.rpartition(".")
                trials = []
                for value in GRIDS[key]:
                    trial = deepcopy(params)
                    (trial[street] if street else trial)[key] = value
                    trials.append(trial)
                for trial, loss in zip(trials, executor.map(_total, trials)):
                    if loss < best - 1e-9:
                        best, params, moved = loss, trial, True
            if not moved:
                break
    return params, best


VARIANTS = {"numbers": (),
            "price": ("price_slope",),
            "all": ("mix", "price_slope",
                    *(f"{street}.{key}" for street in STREETS
                      for key in ("slow", "bluff", "sticky")))}


def losses(hands, params, version, stats):
    action, decisions, cards_loss, cards = score(hands, params, version, stats)
    return {"decisions": decisions, "action_loss": round(action / decisions, 4),
            "shown": cards, "cards_loss": round(cards_loss / max(cards, 1), 4),
            "total": round(action + cards_loss, 2)}


def stats_of(rows_by_log, logs, hero_logs, minutes):
    hands = [hand for name in logs for hand in reduce_log(rows_by_log[name], name)]
    return keep_stats(build_counts(hands, hero_logs & set(logs), minutes))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", nargs="+", type=Path, required=True)
    parser.add_argument("--fold", action="append", required=True,
                        help="NAME=log,log (two folds)")
    parser.add_argument("--minutes", nargs="*", default=[])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    folds = {name: logs.split(",") for name, _, logs in
             (item.partition("=") for item in args.fold)}
    minutes = {name: float(value) for name, _, value in
               (item.partition("=") for item in args.minutes)}
    rows_by_log, tasks, hero_logs = {}, [], set()
    for path in args.frames:
        name = log_name(path)
        rows = load(path)
        rows_by_log[name] = rows
        if seated([row for row in rows if row.get("fields")]):
            hero_logs.add(name)
        tasks += log_tasks(name, rows)[0]
    every = [name for logs in folds.values() for name in logs]
    versions = {"all": stats_of(rows_by_log, every, hero_logs, minutes)}
    for fold, logs in folds.items():
        versions[fold] = stats_of(rows_by_log, logs, hero_logs, minutes)
    versions["aa_real"] = aa_stats()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "aa_cal_stats.json").write_text(
        json.dumps(versions["all"], indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"{len(tasks)} hands; preparing", file=sys.stderr)
    jobs = [(task, versions) for task in tasks]
    with ProcessPoolExecutor(args.workers) as executor:
        hands = list(executor.map(prepare, jobs, chunksize=2))
    by_fold = {fold: [hand for hand in hands if hand["where"]["log"] in logs]
               for fold, logs in folds.items()}
    # The table the scoreboard had: aa_real, its numbers, no departures.
    result = {"hands": len(hands), "variants": {},
              "aa_real": {fold: losses(by_fold[fold], zero_params(), "aa_real",
                                       versions["aa_real"]) for fold in folds}}
    result["aa_real"]["all"] = losses(hands, zero_params(), "aa_real",
                                      versions["aa_real"])
    print(f"aa_real: {result['aa_real']}", file=sys.stderr)
    names = list(folds)
    for variant, keys in VARIANTS.items():
        found = {}
        for train, test in ((names[0], names[1]), (names[1], names[0])):
            params, _ = fit(by_fold[train], train, versions[train], keys,
                            workers=args.workers)
            found[test] = {"fitted_on": train, "params": params,
                           **losses(by_fold[test], params, train, versions[train])}
            print(f"{variant}: fit {train} -> {test}: {found[test]}", file=sys.stderr)
        params, _ = fit(hands, "all", versions["all"], keys, workers=args.workers)
        found["all"] = {"params": params,
                        **losses(hands, params, "all", versions["all"])}
        print(f"{variant}: all: {found['all']}", file=sys.stderr)
        result["variants"][variant] = found
    result["fitted"] = result["variants"]["all"]["all"]["params"]
    result["defaults_before"] = FITTED
    (args.out / "fit.json").write_text(json.dumps(result, indent=1) + "\n",
                                       encoding="utf-8")


if __name__ == "__main__":
    main()
