"""Postflop reading weights from the hands opponents showed.

The range reading (``ranges.opponent_ranges``) keeps, at each postflop
action, only the hands the population model plays that way: a hand the model
would have bet drops out when the player checks, a hand the model would
have checked drops out when he bets. This tool measures, on the window's
frame logs, how real players' shown hands fit that rule, street by street,
and which weights a softer reading should give the hands the model plays
otherwise:

* ``slow``: at a check or call, the hands the model would bet or raise;
* ``loose``: at a call, the hands the model would fold;
* ``bluff``: at a bet or raise, the hands the model would check or fold.

For every seat that showed its cards while still in, the hand is replayed
as ``tools/aa_range_exclusion.py`` does; its preflop range is read with the
window's model (with and without the reads of the hands before), and at each
of its postflop actions the model's action is worked out for every hand the
board leaves. A set of weights then gives each hand a weight: its preflop
weight times, at each postflop action, 1 if the model plays it that way and
the weight of its kind otherwise. Weights are chosen per street to make the
shown hands most likely (the mean log of the shown hand's share of its
range), by coordinate ascent over ``GRID``; ``--bootstrap`` resamples the
seats for an interval. The exclusion rates of the current reading and of the
fitted weights are counted as ``scoreboard.exclusion`` counts them.

Shown hands are those that reached a showdown: strong hands are more likely
to get there than the hands a player checked and later folded, so the slow
play weight is, if anything, measured high.

    PYTHONPATH=src:. .venv/bin/python tools/aa_postflop_reading_weights.py \\
        --frames <recording>/frames.jsonl [--frames ...] --out weights.json
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
import math
from pathlib import Path
import random
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_reads import AAReads  # noqa: E402
from poker_engine.desktop.aa_solver_input import HERO, hand_facts  # noqa: E402
from poker_engine.scoreboard.bots import _rng  # noqa: E402
from poker_engine.scoreboard.exclusion import (  # noqa: E402
    EXCLUDED, action_word, compare, summarize)
from poker_engine.scoreboard.ranges import (  # noqa: E402
    FLOOR_FROM, _shares, floor)
from poker_engine.scoreboard.reads import aggression_factor, factors  # noqa: E402
from poker_engine.scoreboard.replay import (  # noqa: E402
    kind_of, public_replay, with_hole)
from poker_engine.scoreboard.solver_bot import MODEL_SALT, kept  # noqa: E402
from poker_engine.solver.texassolver import all_combos, combo_key  # noqa: E402
from tools.aa_range_exclusion import (  # noqa: E402
    hand_table, hands_in_order, load, shown_seats, window_model)

POSTFLOP = ("flop", "turn", "river")
KINDS = ("slow", "loose", "bluff")
MATCH, SLOW, LOOSE, BLUFF = 0, 1, 2, 3
PRE_FLOOR = 0.01
GRID = (0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5,
        0.7, 1.0)


def mismatch(taken, model_kind):
    """MATCH, or which kind of hand the model plays otherwise than ``taken``."""
    if model_kind == taken:
        return MATCH
    if taken == "c":
        return SLOW if model_kind == "r" else LOOSE
    return BLUFF


def model_kinds(decision, keys, model):
    """{combo key: "f"/"c"/"r"} the model's action with each hand at ``decision``."""
    result = {}
    for key in keys:
        observation = with_hole(decision.observation, (key[:2], key[2:]))
        choice = model.decide(observation, _rng(MODEL_SALT, observation))
        result[key] = (max(choice, key=choice.get) if isinstance(choice, dict)
                       else kind_of(choice))
    return result


def preflop_weights(observation, seat, model, decisions):
    """(weights after the seat's preflop actions, preflop steps) as
    ``opponent_ranges`` reads them."""
    reads = observation.get("reads") or {}
    read = factors(reads.get(str(seat)), _shares(model))
    weights = {key: 1.0 for key in all_combos()}
    steps = []
    for decision in decisions:
        if decision.seat != seat or decision.street != "preflop":
            continue
        if read != (1.0, 1.0):
            decision = replace(decision, observation={
                **decision.observation, "read_factors": read})
        weights = kept(weights, decision, lambda obs: model.decide(
            obs, _rng(MODEL_SALT, obs))) or weights
        steps.append((decision, dict(weights)))
    return weights, steps


def seat_record(observation, seat, cards, model, decisions, kinds_cache):
    """What the reading needs of one shown seat, with and without reads."""
    key = combo_key(cards)
    board = tuple(observation["board"])
    keys = [combo for combo in all_combos(board)]
    if key not in keys:
        raise ValueError("cards do not fit")
    history = observation["public_history"]
    last = len(history) - 1 if observation.get("terminal") else None
    actions = []
    for decision in decisions:
        if decision.seat != seat or decision.street == "preflop":
            continue
        cache_key = (id(observation), decision.action.get("index"))
        if cache_key not in kinds_cache:
            kinds_cache[cache_key] = model_kinds(decision, keys, model)
        kinds = kinds_cache[cache_key]
        actions.append({
            "street": decision.street, "kind": decision.kind,
            "word": action_word(decision), "index": decision.action.get("index"),
            "ends_hand": decision.action.get("index") == last,
            "types": np.array([mismatch(decision.kind, kinds[combo]) for combo in keys],
                              dtype=np.int8)})
    record = {"seat": seat, "cards": list(cards), "true": keys.index(key),
              "combos": len(keys),
              "street": (history[-1]["street"]
                         if observation.get("terminal") and history
                         else observation["street"]),
              "actions": actions, "modes": {}}
    for mode in ("reads", "no_reads"):
        seen = observation if mode == "reads" else {
            k: v for k, v in observation.items() if k != "reads"}
        pre, steps = preflop_weights(seen, seat, model, decisions)
        reads = seen.get("reads") or {}
        aggression = aggression_factor(reads.get(str(seat)), _shares(model))
        record["modes"][mode] = {
            "pre": np.array([pre.get(combo, 0.0) for combo in keys]),
            "pre_steps": [_step(decision, _relative(weights, key), weights, last)
                          for decision, weights in steps],
            "aggression": aggression, "floor": floor(aggression)}
    return record


def _relative(weights, key):
    top = max(weights.values(), default=0.0)
    return weights.get(key, 0.0) / top if top > 0 else 0.0


def _step(decision, weight, weights, last):
    top = max(weights.values(), default=0.0)
    index = decision.action.get("index")
    return {"index": index, "street": decision.street, "action": action_word(decision),
            "weight": round(weight, 6),
            "hands": sum(value > EXCLUDED * top for value in weights.values()),
            "excluded": weight <= EXCLUDED, "ends_hand": index == last}


def collect(logs, model=None):
    """[(where, record)] for every shown seat still in, and skipped reasons."""
    model = model or window_model()
    records, skipped = [], Counter()
    for name, rows in logs:
        counted, stakes = AAReads(), None
        for hand_id, hand in hands_in_order([row for row in rows if row.get("fields")]):
            snapshot = counted.snapshot()
            shown = shown_seats(hand)
            if shown:
                arena, _ = hand_table(hand, stakes)
                if arena is None:
                    skipped["no_replay"] += len(shown)
                else:
                    base = arena.observe(arena.occupied_seats[0])
                    base["reads"] = snapshot
                    kinds_cache = {}
                    for seat, cards in sorted(shown.items()):
                        if seat not in base["occupied_seats"]:
                            skipped["seat_not_dealt_in"] += 1
                            continue
                        if seat in base["folded"]:
                            skipped["shown_after_folding"] += 1
                            continue
                        others = [s for s in base["occupied_seats"] if s != seat]
                        observer = HERO if HERO in others else others[0]
                        observation = {**base, "observing_seat": observer}
                        try:
                            record = seat_record(
                                observation, seat, cards, model,
                                public_replay(observation), kinds_cache)
                        except ValueError:
                            skipped["cards_do_not_fit"] += 1
                            continue
                        record["you_in"] = (observer == HERO
                                            and HERO not in base["folded"])
                        records.append(({"log": name, "hand_id": hand_id}, record))
            try:
                counted.add_hand(hand, stakes)
                found = hand_facts(hand, stakes)["stakes"]
            except Exception:
                continue
            if found.get("source") == "table":
                stakes = found
    return records, dict(skipped)


# -- applying weights ----------------------------------------------------------

def factor_table(params, seat_floor=0.0):
    """{street: [factor per type]} for ``params`` {kind: {street: weight}}."""
    return {street: np.array([1.0] + [max(params[kind][street], seat_floor)
                                      for kind in KINDS])
            for street in POSTFLOP}


def read_record(record, mode, params, *, hard=False, pre_floor=0.0):
    """[(action, weights after it)] of one seat under ``params`` (``hard``:
    the current reading, with its floor and the range kept when an action
    would empty it; ``pre_floor``: every hand keeps at least that share of
    the largest preflop weight)."""
    part = record["modes"][mode]
    weights = part["pre"]
    if pre_floor:
        weights = np.maximum(weights, pre_floor * weights.max())
    table = factor_table(params, part["floor"])
    result = []
    for action in record["actions"]:
        after = weights * table[action["street"]][action["types"]]
        if hard:
            if not after.any():
                after = weights
            elif part["floor"]:
                after = np.maximum(after, part["floor"] * weights)
        weights = after
        result.append((action, weights))
    return result


def log_share(record, mode, params):
    """Log of the shown hand's share of its range. Preflop the hand keeps at
    least ``PRE_FLOOR`` of the largest weight: a hand the preflop reading
    threw out (task 3's business) would make every postflop weight equally
    bad and say nothing about them."""
    if not record["actions"]:
        return 0.0
    weights = read_record(record, mode, params, pre_floor=PRE_FLOOR)[-1][1]
    total = weights.sum()
    mine = weights[record["true"]]
    return math.log(mine / total) if mine > 0 and total > 0 else -math.inf


def trace_of(record, mode, params, hard=False):
    """An ``exclusion_trace``-like dict, for ``exclusion.summarize``."""
    steps = list(record["modes"][mode]["pre_steps"])
    for action, weights in read_record(record, mode, params, hard=hard):
        top = weights.max()
        weight = weights[record["true"]] / top if top > 0 else 0.0
        steps.append({"index": action["index"], "street": action["street"],
                      "action": action["word"], "weight": round(float(weight), 6),
                      "hands": int((weights > EXCLUDED * top).sum()),
                      "excluded": bool(weight <= EXCLUDED),
                      "ends_hand": action["ends_hand"]})
    return {"seat": record["seat"], "street": record["street"],
            "combos": record["combos"], "you_in": record["you_in"], "steps": steps}


HARD = {kind: dict.fromkeys(POSTFLOP, 0.0) for kind in KINDS}


def objective(records, mode, params):
    shares = [log_share(record, mode, params) for record in records]
    return sum(shares) / len(shares) if shares else 0.0


def fit(records, mode, start=None, grid=GRID, sweeps=3, kinds=KINDS, pooled=False):
    """Coordinate ascent of ``objective`` over ``grid``, kind by kind and
    street by street (``pooled``: one weight per kind for every street)."""
    params = {kind: dict((start or {}).get(kind) or dict.fromkeys(POSTFLOP, 0.1))
              for kind in KINDS}
    best = objective(records, mode, params)
    for _ in range(sweeps):
        moved = False
        for kind in kinds:
            for street in ((POSTFLOP,) if pooled else POSTFLOP):
                for value in grid:
                    trial = {k: dict(v) for k, v in params.items()}
                    for one in (street if pooled else (street,)):
                        trial[kind][one] = value
                    score = objective(records, mode, trial)
                    if score > best + 1e-12:
                        best, params, moved = score, trial, True
        if not moved:
            break
    return params, best


def shares_table(records, mode, groups=None):
    """Counts of the shown seats' postflop actions by street and action, and
    how many of them the model plays otherwise, by kind."""
    rows = {}
    for record in records:
        group = groups(record) if groups else "all"
        for action in record["actions"]:
            kind = mismatch_kind(action["types"][record["true"]])
            row = rows.setdefault(f"{group}|{action['street']}|{action['word']}",
                                  Counter())
            row["n"] += 1
            row[kind] += 1
    return {key: dict(value) for key, value in sorted(rows.items())}


def mismatch_kind(code):
    return ("match", "slow", "loose", "bluff")[int(code)]


def aggression_group(mode):
    def group(record):
        value = record["modes"][mode]["aggression"]
        if value is None:
            return "no_read"
        return "bet_happy" if value > FLOOR_FROM else "normal"
    return group


def bootstrap(records, mode, params, count, seed=0):
    """{kind: {street: [2.5%, 50%, 97.5%]}} of weights fitted to resampled seats."""
    rng = random.Random(seed)
    fits = []
    for _ in range(count):
        sample = [rng.choice(records) for _ in records]
        fits.append(fit(sample, mode, start=params, sweeps=2)[0])
    return {kind: {street: [float(np.percentile([f[kind][street] for f in fits], q))
                            for q in (2.5, 50, 97.5)]
                   for street in POSTFLOP} for kind in KINDS}


def summary_rates(traces):
    """The rates of ``summarize``, and ``postflop_only``: of the hands still
    in after the preflop reading, how many the postflop reading threw out."""
    result = {}
    for view in ("whole_hand", "before_end"):
        part = summarize(traces, before_end=view == "before_end")
        kept_preflop = out = 0
        for trace in traces:
            steps = [step for step in trace["steps"]
                     if not (view == "before_end" and step["ends_hand"])]
            if any(step["excluded"] for step in steps if step["street"] == "preflop"):
                continue
            if not any(step["street"] != "preflop" for step in steps):
                continue
            kept_preflop += 1
            out += any(step["excluded"] for step in steps)
        result[view] = {"all": part["all"], "river": part["river"],
                        "by_street": part["by_street"],
                        "postflop_only": {"hands": kept_preflop, "excluded": out}}
    return result


def evaluate(records, mode, sets):
    """Exclusion rates and mean log share of each named weight set, against
    the current reading."""
    current = [trace_of(record, mode, HARD, hard=True) for record in records]
    result = {"current": {"rates": summary_rates(current),
                          "log_share": objective(records, mode, HARD)}}
    for name, params in sets.items():
        traces = [trace_of(record, mode, params) for record in records]
        changed = {}
        for view in ("whole_hand", "before_end"):
            found = compare(current, traces, before_end=view == "before_end")
            changed[view] = {key: found[key] for key in ("kept_now", "excluded_now")}
        result[name] = {"params": params, "rates": summary_rates(traces),
                        "log_share": objective(records, mode, params),
                        "vs_current": changed}
    return result


def seat_lines(records, mode, params):
    """One short line per seat: where, cards, the kinds of its mismatches and
    the shown hand's final relative weight now and with ``params``."""
    lines = []
    for where, record in records:
        kinds = [f"{a['street'][0]}{a['word'][:2]}:"
                 f"{mismatch_kind(a['types'][record['true']])}"
                 for a in record["actions"]]
        now = trace_of(record, mode, HARD, hard=True)["steps"]
        soft = trace_of(record, mode, params)["steps"]
        lines.append(f"{where['log']} {where['hand_id']} s{record['seat']} "
                     f"{''.join(record['cards'])} {record['street']} "
                     f"{' '.join(kinds)} | {now[-1]['weight'] if now else 1:.3g} -> "
                     f"{soft[-1]['weight'] if soft else 1:.3g}")
    return lines


def report(records, skipped, bootstrap_count=0):
    plain = [record for _, record in records]
    result = {"seats": len(plain), "skipped": skipped,
              "seats_with_postflop_actions": sum(bool(r["actions"]) for r in plain),
              "preflop_out": {mode: sum(r["modes"][mode]["pre"][r["true"]] <= EXCLUDED
                                        * r["modes"][mode]["pre"].max() for r in plain)
                              for mode in ("reads", "no_reads")},
              "postflop_actions": sum(len(r["actions"]) for r in plain), "modes": {}}
    for mode in ("reads", "no_reads"):
        fitted, score = fit(plain, mode)
        sets = {"fitted": fitted, "pooled": fit(plain, mode, pooled=True)[0]}
        part = {"shares": shares_table(plain, mode),
                "shares_by_aggression": shares_table(plain, mode,
                                                     aggression_group(mode)),
                "aggression_groups": dict(Counter(aggression_group(mode)(r)
                                                  for r in plain)),
                "evaluation": evaluate(plain, mode, sets)}
        bet_happy = [r for r in plain if aggression_group(mode)(r) == "bet_happy"]
        if mode == "reads" and len(bet_happy) >= 5:
            part["bet_happy_bluff"] = fit(bet_happy, mode, start=fitted,
                                          kinds=("bluff",))[0]["bluff"]
            part["bet_happy_seats"] = len(bet_happy)
        if bootstrap_count:
            part["bootstrap"] = bootstrap(plain, mode, fitted, bootstrap_count)
        result["modes"][mode] = part
    result["seat_lines"] = seat_lines(records, "reads",
                                      result["modes"]["reads"]["evaluation"]["fitted"]
                                      ["params"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", required=True)
    parser.add_argument("--bootstrap", type=int, default=0)
    parser.add_argument("--try", dest="tries", action="append", default=[],
                        metavar="NAME=slow:f,t,r;loose:f,t,r;bluff:f,t,r",
                        help="also evaluate a named weight set")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    logs = [(path.parent.name, load(path)) for path in args.frames]
    records, skipped = collect(logs)
    result = report(records, skipped, args.bootstrap)
    for text in args.tries:
        name, spec = text.split("=", 1)
        params = {}
        for part in spec.split(";"):
            kind, values = part.split(":")
            params[kind] = dict(zip(POSTFLOP, map(float, values.split(","))))
        plain = [record for _, record in records]
        for mode in ("reads", "no_reads"):
            result["modes"][mode]["evaluation"].update(
                {name: evaluate(plain, mode, {name: params})[name]})
    text = json.dumps(result, ensure_ascii=False, indent=1, default=float)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()


__all__ = ["collect", "fit", "mismatch", "report"]
