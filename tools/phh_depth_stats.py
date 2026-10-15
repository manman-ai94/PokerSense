"""How players' folds, calls and bets depend on the price and the stack depth (PHH).

The scoreboard's opponents (``population``, ``aa_real``, ``aa_cal``) fold,
call and raise as often in a spot whatever the bet and however deep the
stacks: they call a pot-sized bet as readily as a third of the pot, and a
short stack facing an all-in folds as often as a deep one. With stacks of
25-250 big blinds (``--stacks``) that makes the scoreboard optimistic. This
counts, in the PHH dataset's 2009 online no-limit hold'em logs (the 7-9
player games ``phh_population_stats.py`` counts), every betting decision by:

* the situation, as the population bot sees it (``scoreboard.spots``):
  before the flop ``rfi``, ``vs_open`` ...; after it
  ``street|hu or multi|pfa or other|checked_to, facing_bet or facing_raise``;
* facing a bet: the price (the call as a share of the pot after calling,
  ``PRICES``) and whether calling puts the player all in;
* the depth: before the flop the effective stack in big blinds
  (``PREFLOP_DEPTHS``), after it the effective stack over the pot (SPR,
  ``POSTFLOP_DEPTHS``). The effective stack is the most the player can still
  lose: his chips behind, or less when no player still in can match them;
* the choice: fold, call or raise facing a bet; with nothing to call check,
  or bet with its size as a share of the pot (``SIZES``) or all in.

Keys are ``situation|price|depth|all_in|choice`` (price ``-`` with nothing
to call; all_in ``1`` when calling puts the player all in). Only aggregate
counts are written; no hand or player is stored.

Dataset: Juho Kim (University of Toronto), "A Dataset of Poker Hand
Histories", Zenodo record 13997158, https://doi.org/10.5281/zenodo.13997158,
CC BY 4.0.

    PYTHONPATH=src:. .venv/bin/python tools/phh_depth_stats.py \\
        --zip ~/Projects/PokerSense_data/datasets/phh/poker-hand-histories.zip \\
        --out <dir>/phh_depth_stats_v1.json [--workers 8] [--limit-files 50]
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import tomllib
import zipfile

from poker_engine.scoreboard.spots import postflop_spot, preflop_spot

STREETS = ("preflop", "flop", "turn", "river")
PLAYERS = range(7, 10)              # the 7-9 player games, as the population stats
# (upper edge, name); the last name takes everything above.
PRICES = ((0.10, "p00"), (0.15, "p10"), (0.20, "p15"), (0.25, "p20"),
          (0.30, "p25"), (0.35, "p30"), (0.40, "p35"), (0.45, "p40"),
          (None, "p45"))
PREFLOP_DEPTHS = ((15, "bb00"), (25, "bb15"), (40, "bb25"), (60, "bb40"),
                  (100, "bb60"), (150, "bb100"), (None, "bb150"))
POSTFLOP_DEPTHS = ((0.5, "spr0"), (1, "spr0.5"), (2, "spr1"), (4, "spr2"),
                   (8, "spr4"), (16, "spr8"), (None, "spr16"))
SIZES = ((0.4, "s00"), (0.75, "s40"), (1.1, "s75"), (None, "s110"))


def bucket(value, edges):
    return next(name for top, name in edges if top is None or value < top)


def in_scope(hand):
    blinds = hand["blinds_or_straddles"]
    return (len(hand["starting_stacks"]) in PLAYERS and not any(hand["antes"])
            and not any(blinds[2:]) and 0 < blinds[0] <= blinds[1])


def effective(player, stacks, committed, folded):
    """The most ``player`` can still lose this hand: his chips behind, or
    what the deepest other player still in can put in beyond his own bet."""
    mine = stacks[player] - committed[player]
    others = [stacks[i] - committed[player] for i in range(len(stacks))
              if i != player and i not in folded]
    return max(0.0, min(mine, max(others, default=0.0)))


def count_hand(hand, counts):
    """Count every betting decision of one hand; False if it is out of scope."""
    if not in_scope(hand):
        return False
    players = len(hand["starting_stacks"])
    big = float(hand["blinds_or_straddles"][1])
    stacks = [float(s) for s in hand["starting_stacks"]]        # at street start
    committed = [float(b) for b in hand["blinds_or_straddles"]]  # on this street
    committed[0] = min(committed[0], stacks[0])
    committed[1] = min(committed[1], stacks[1])
    pot, street, aggressor = 0.0, 0, None
    folded, done = set(), []
    for text in hand["actions"]:
        parts = text.split()
        if parts[0] == "d":
            if parts[1] == "db":
                pot += sum(committed)
                stacks = [s - c for s, c in zip(stacks, committed)]
                committed = [0.0] * players
                street, done = street + 1, []
            continue
        kind = parts[1]
        if kind not in ("f", "cc", "cbr"):
            continue                                  # show / muck
        player = int(parts[0][1:]) - 1
        name = STREETS[min(street, 3)]
        current = max(committed)
        behind = stacks[player] - committed[player]
        to_call = min(current - committed[player], behind)
        middle = pot + sum(committed)
        depth = effective(player, stacks, committed, folded)
        letter = {"f": "f", "cc": "c", "cbr": "r"}[kind]
        if street == 0:
            situation = preflop_spot(done, player)
            depth_name = bucket(depth / big, PREFLOP_DEPTHS)
        else:
            situation = postflop_spot(name, done, player,
                                      players - len(folded) - 1, aggressor)
            depth_name = bucket(depth / middle if middle else 99.0, POSTFLOP_DEPTHS)
        if to_call > 0:
            price = bucket(to_call / (middle + to_call), PRICES)
            all_in = "1" if to_call >= behind else "0"
            choice = {"f": "fold", "c": "call", "r": "raise"}[letter]
        else:
            price, all_in = "-", "0"
            if letter == "r":
                amount = float(parts[2]) - committed[player]
                choice = ("bet:allin" if amount >= behind else
                          "bet:" + bucket(amount / max(middle, 1e-9), SIZES))
            else:
                choice = "check"
        counts[f"{situation}|{price}|{depth_name}|{all_in}|{choice}"] += 1
        if letter == "r":
            committed[player] = min(float(parts[2]), stacks[player])
            if street == 0:
                aggressor = player
        elif letter == "c":
            committed[player] += to_call
        else:
            folded.add(player)
        done.append((player, letter))
    counts["hands"] += 1
    return True


def count_file(args):
    zip_path, name = args
    counts = Counter()
    with zipfile.ZipFile(zip_path) as archive:
        text = archive.read(name).decode("utf-8")
    for hand in tomllib.loads(text).values():
        try:
            count_hand(hand, counts)
        except (KeyError, ValueError, IndexError):
            counts["skipped_malformed"] += 1
    return counts


def collect(zip_path, workers, limit=None):
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(name for name in archive.namelist()
                       if name.startswith("data/handhq/") and name.endswith(".phhs"))
    if limit:
        names = names[::max(1, len(names) // limit)][:limit]
    total = Counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for counts in executor.map(count_file, [(zip_path, n) for n in names],
                                   chunksize=8):
            total.update(counts)
    return total, len(names)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int,
                        default=max(1, (os.cpu_count() or 1) - 2))
    parser.add_argument("--limit-files", type=int)
    args = parser.parse_args(argv)
    counts, files = collect(args.zip.expanduser(), args.workers, args.limit_files)
    report = {
        "schema_version": 1,
        "source": {"title": "A Dataset of Poker Hand Histories", "version": "v2",
                   "creator": "Juho Kim (University of Toronto)",
                   "doi": "10.5281/zenodo.13997158",
                   "zenodo_record": 13997158, "license": "CC-BY-4.0",
                   "part": "data/handhq (online no-limit hold'em, July 2009)"},
        "files_read": files,
        "hands": counts.pop("hands", 0),
        "skipped_malformed": counts.pop("skipped_malformed", 0),
        "scope": ("7 to 9 players, both blinds posted, no antes or straddles; "
                  "every betting decision"),
        "buckets": {"price": [name for _, name in PRICES],
                    "preflop_depth_bb": [[top, name] for top, name in PREFLOP_DEPTHS],
                    "postflop_spr": [[top, name] for top, name in POSTFLOP_DEPTHS],
                    "bet_size": [[top, name] for top, name in SIZES]},
        "counts": dict(sorted(counts.items())),
    }
    args.out.write_text(json.dumps(report, indent=0) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("files_read", "hands", "skipped_malformed")}
                     | {"keys": len(report["counts"])}))


if __name__ == "__main__":
    main()
