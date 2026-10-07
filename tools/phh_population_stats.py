"""Population tendencies of real players from the PHH dataset (aggregate counts).

Reads the 2009 online no-limit hold'em logs (``data/handhq``) straight from
the dataset zip and counts, for every betting decision, what players chose:
before the flop by position and situation (open, facing limpers, facing a
raise, facing a re-raise after opening ...), after it by street, heads-up or
multiway, preflop aggressor or not, and whether a bet or a raise is faced.
The situations are the ones the population bot uses
(``poker_engine.scoreboard.spots``). Only aggregate counts are written; no
hand or player is stored.

Dataset: Juho Kim (University of Toronto), "A Dataset of Poker Hand
Histories", Zenodo record 13997158, https://doi.org/10.5281/zenodo.13997158,
CC BY 4.0.

    PYTHONPATH=src:. .venv/bin/python tools/phh_population_stats.py \\
        --zip ~/Projects/PokerSense_data/datasets/phh/poker-hand-histories.zip \\
        --out src/poker_engine/scoreboard/phh_population_stats_v1.json [--workers 8]
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

TABLE_GROUPS = {6: "6", 7: "7-9", 8: "7-9", 9: "7-9"}
STREETS = ("preflop", "flop", "turn", "river")
POSITIONS = ("SB", "BB", "BTN", "CO", "HJ", "LJ", "EP")
PHH_KINDS = {"f": "f", "cc": "c", "cbr": "r"}


def position(index, players):
    """PHH order is SB, BB, then first to act ... button."""
    if index == 0:
        return "SB"
    if index == 1:
        return "BB"
    behind = players - 1 - index          # seats between this seat and the button
    return ("BTN", "CO", "HJ", "LJ", "EP")[min(behind, 4)]


def parse_actions(actions):
    """[(street, player index, kind)] for the player actions, kind f/c/r."""
    street, rows = 0, []
    for text in actions:
        parts = text.split()
        if parts[0] == "d":
            if parts[1] == "db":
                street += 1
            continue
        if parts[1] not in PHH_KINDS:
            continue                       # show/muck
        player = int(parts[0][1:]) - 1
        rows.append((STREETS[min(street, 3)], player, PHH_KINDS[parts[1]]))
    return rows


def count_hand(hand, counts):
    """Count every betting decision of one hand; False if the hand is out of scope."""
    players = len(hand["starting_stacks"])
    group = TABLE_GROUPS.get(players)
    blinds = hand["blinds_or_straddles"]
    if group is None or any(hand["antes"]) or any(blinds[2:]):
        return False
    if not 0 < blinds[0] <= blinds[1]:
        # A missing blind shifts who is who (the first player is then the big blind).
        counts["skipped_missing_blind"] += 1
        return False
    done = {street: [] for street in STREETS}
    folded, aggressor = set(), None
    for street, player, kind in parse_actions(hand["actions"]):
        actions = done[street]
        if street == "preflop":
            spot = f"{position(player, players)}|{preflop_spot(actions, player)}"
            choice = {"f": "fold", "c": "call", "r": "raise"}[kind]
            if kind == "r":
                aggressor = player
        else:
            spot = postflop_spot(street, actions, player,
                                 players - len(folded) - 1, aggressor)
            facing = any(other == "r" for _, other in actions)
            choice = {"f": "fold", "c": "call" if facing else "check",
                      "r": "raise" if facing else "bet"}[kind]
        counts[f"{group}|{spot}|{choice}"] += 1
        actions.append((player, kind))
        if kind == "f":
            folded.add(player)
    counts[f"{group}|hands"] += 1
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


def frequencies(counts):
    """Nested {group: {spot: {decision: share, 'n': count}}}.

    Preflop spots are also pooled over positions as ``ALL|<situation>``.
    """
    grouped = {}
    for key, value in counts.items():
        parts = key.split("|")
        if len(parts) < 3:
            continue
        group, spot, choice = parts[0], "|".join(parts[1:-1]), parts[-1]
        spots = grouped.setdefault(group, {})
        spots.setdefault(spot, Counter())[choice] += value
        if parts[1] in POSITIONS:
            spots.setdefault(f"ALL|{parts[2]}", Counter())[choice] += value
    result = {}
    for group, spots in grouped.items():
        result[group] = {}
        for spot, choices in sorted(spots.items()):
            n = sum(choices.values())
            result[group][spot] = {"n": n, **{c: round(v / n, 4)
                                              for c, v in sorted(choices.items())}}
    return result


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
                   "part": "data/handhq (online no-limit hold'em, July 2009)",
                   "md5_of_zip": "0918a30f97bda0129897b7e0f1ec895a"},
        "files_read": files,
        "hands": {group: counts.get(f"{group}|hands", 0) for group in ("6", "7-9")},
        "skipped_malformed": counts.get("skipped_malformed", 0),
        "skipped_missing_blind": counts.get("skipped_missing_blind", 0),
        "scope": ("6 to 9 players, both blinds posted, no antes or straddles; every "
                  "betting decision; positions counted back from the button"),
        "frequencies": frequencies(counts),
    }
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    summary = ("files_read", "hands", "skipped_malformed", "skipped_missing_blind")
    print(json.dumps({key: report[key] for key in summary}))


if __name__ == "__main__":
    main()
