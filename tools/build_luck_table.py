"""Build the card-luck table (``luck_table_v1.json``) on the simulated AA table.

A strategy (``aa_preflop`` by default: fast, and the window's preflop) plays
every seat of each deal against a pool (the AA calibrated players by
default), all-in hands scored by their expected result. Each hand gives its
seat, its two cards' class and its result in big blinds. A class's value is
its average result less the average at its seat, pooled over the seats and
shifted to average zero over the 1326 hands; each seat then gets its own
slope (how far results at that seat follow the class values, least
squares). A seat's card luck is slope times class value (``luck.hole_luck``).

The check plays other deals (other seeds) and says how much the luck takes
out there: the spread per hand before and after, how many times fewer hands
the same interval then needs, and the card luck's average, which must be
zero within its interval (the table cannot change a result on average). The
runout part is the same for all-in hands scored by their expected result
instead of the board that came. ``--check-strategy`` also checks it with
another strategy (the window's) on fewer deals: the table helps a player
whose results follow it less too, only by less. ``--hands`` keeps every
simulated hand (deal, seat, class, result, result with the board that came;
a line each, ``"fit"`` or ``"check"``) for looking at other fits.

    PYTHONPATH=src:. .venv/bin/python tools/build_luck_table.py --deals 16000 \\
        --check-deals 4000 --workers 4 \\
        --check-strategy range_multiway@hu=1+aa_preflop --check-strategy-deals 300 \\
        --out src/poker_engine/scoreboard/luck_table_v1.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poker_engine.code_version import code_version  # noqa: E402
from poker_engine.scoreboard import luck  # noqa: E402
from poker_engine.scoreboard import runner  # noqa: E402
from poker_engine.scoreboard.bots import make_policy  # noqa: E402
from poker_engine.scoreboard.strength import all_classes, hand_class  # noqa: E402
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena  # noqa: E402
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2  # noqa: E402

DEFAULT_RULES = (Path(__file__).resolve().parents[1]
                 / "configs/game/aa-scoreboard-rules-v2.json")
SEED = 70_000_000
CHECK_OFFSET = 10_000_000   # check deals: other seeds than the fit's
CHUNKS_PER_WORKER = 4


def play(rules_dict, strategy, pool, seeds, base_seed):
    """[(deal, seat 0-7 from the small blind, class, result, result with the
    board that came)] in big blinds, for every seat of every deal."""
    rules = AARuleProfileV2.from_dict(rules_dict)
    arena = AAFullHandArena(rules)
    seats = arena.occupied_seats
    big_blind = float(rules.big_blind)
    bots = {name: make_policy(name) for name in pool}
    hero_policy = make_policy(strategy)
    hands = []
    for seed in seeds:
        styles = runner.lineup(seed, pool, seats)
        bound = {seat: bots[styles[seat]].for_game(runner._salt(base_seed, seed, seat))
                 for seat in seats}
        for hero in seats:
            deciders = dict(bound)
            deciders[hero] = hero_policy.for_game(runner._salt(base_seed, seed, hero))
            hand = runner.play_hand(arena, seed, deciders, hero)
            index = arena._seats.index(hero)
            cards = [repr(card) for card in arena._holes[index]]
            came = float(arena.terminal_returns()[hero])
            hands.append((seed, index, hand_class(cards), hand.value / big_blind,
                          came / big_blind))
    return hands


def played(rules_dict, strategy, pool, seeds, base_seed, workers):
    seeds = list(seeds)
    if workers <= 1:
        return play(rules_dict, strategy, pool, seeds, base_seed)
    size = max(1, math.ceil(len(seeds) / (workers * CHUNKS_PER_WORKER)))
    chunks = [seeds[i:i + size] for i in range(0, len(seeds), size)]
    with ProcessPoolExecutor(workers) as executor:
        jobs = [(rules_dict, strategy, pool, chunk, base_seed) for chunk in chunks]
        parts = executor.map(play, *zip(*jobs))
        return [hand for part in parts for hand in part]


def fit(hands):
    """(class values, slope per seat) from (deal, seat, class, result, _)."""
    by_seat = defaultdict(list)
    for _, seat, name, value, _ in hands:
        by_seat[seat].append((name, value))
    means = {seat: sum(v for _, v in items) / len(items)
             for seat, items in by_seat.items()}
    sums, counts = defaultdict(float), defaultdict(int)
    for _, seat, name, value, _ in hands:
        sums[name] += value - means[seat]
        counts[name] += 1
    missing = [name for name in all_classes() if not counts[name]]
    if missing:
        raise ValueError(f"no hands of {', '.join(missing[:5])}: play more deals")
    classes = luck.centered({name: sums[name] / counts[name] for name in all_classes()})
    slopes = []
    for seat in range(luck.SEATS):
        items = by_seat[seat]
        top = sum((value - means[seat]) * classes[name] for name, value in items)
        bottom = sum(classes[name] ** 2 for name, _ in items)
        slopes.append(top / bottom if bottom else 0.0)
    return classes, slopes


def spread(values):
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def by_deal(hands, values):
    """Per-deal sums of ``values`` (the seats of a deal share a deck)."""
    sums = defaultdict(float)
    for hand, value in zip(hands, values):
        sums[hand[0]] += value
    return list(sums.values())


def check(hands, table):
    """How much the table takes out of ``hands`` it was not fitted on."""
    came = [hand[4] for hand in hands]
    expected = [hand[3] for hand in hands]
    cards = [luck.class_luck(hand[2], hand[1], table) for hand in hands]
    both = [value - lucky for value, lucky in zip(expected, cards)]
    deals = by_deal(hands, cards)
    seats = len(hands) / len(deals)
    mean, half = luck.interval(deals)
    raw, runout, adjusted = spread(came), spread(expected), spread(both)
    return {"deals": len(deals), "hands": len(hands),
            "spread_per_hand_bb": {"as_dealt": round(raw, 3),
                                   "runout_taken_out": round(runout, 3),
                                   "both_taken_out": round(adjusted, 3)},
            "fewer_hands": {"runout": round((raw / runout) ** 2, 3),
                            "cards": round((runout / adjusted) ** 2, 3),
                            "both": round((raw / adjusted) ** 2, 3)},
            "card_luck_bb_per_100": round(100 * mean / seats, 2),
            "card_luck_ci95": [round(100 * (mean - half) / seats, 2),
                               round(100 * (mean + half) / seats, 2)]}


def build(args):
    rules_dict = json.loads(Path(args.rules).read_text(encoding="utf-8"))
    pool = runner.POOLS[args.pool]
    fitted = played(rules_dict, args.strategy, pool,
                    range(args.seed, args.seed + args.deals), args.seed, args.workers)
    classes, slopes = fit(fitted)
    table = {"classes": classes, "slopes": slopes}
    start = args.seed + CHECK_OFFSET
    checked = played(rules_dict, args.strategy, pool,
                     range(start, start + args.check_deals), start, args.workers)
    report = {"schema_version": 1, "unit": "big blinds",
              "seats": list(luck.POSITIONS),
              "built": {"tool": "tools/build_luck_table.py", "strategy": args.strategy,
                        "pool": args.pool, "deals": args.deals, "seed": args.seed,
                        "rules": Path(args.rules).name,
                        "code": (code_version()["commit"] or "")[:7] or None},
              "slopes": [round(value, 4) for value in slopes],
              "classes": {name: round(value, 4) for name, value in classes.items()},
              "check": {args.strategy: check(checked, table)}}
    if args.check_strategy:
        start += args.check_deals
        other = played(rules_dict, args.check_strategy, pool,
                       range(start, start + args.check_strategy_deals), start,
                       args.workers)
        report["check"][args.check_strategy] = check(other, table)
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    if args.hands:
        with Path(args.hands).open("w", encoding="utf-8") as handle:
            for part, hands in (("fit", fitted), ("check", checked)):
                for hand in hands:
                    handle.write(json.dumps([part, *hand]) + "\n")
    for name, item in report["check"].items():
        print(f"{name}: {item['hands']} hands, spread {item['spread_per_hand_bb']}, "
              f"fewer hands {item['fewer_hands']}, card luck "
              f"{item['card_luck_bb_per_100']} {item['card_luck_ci95']} bb/100")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deals", type=int, default=16000)
    parser.add_argument("--check-deals", type=int, default=4000)
    parser.add_argument("--strategy", default="aa_preflop")
    parser.add_argument("--pool", default="aa_cal", choices=sorted(runner.POOLS))
    parser.add_argument("--check-strategy")
    parser.add_argument("--check-strategy-deals", type=int, default=300)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--hands", type=Path, help="keep every simulated hand here")
    return build(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
