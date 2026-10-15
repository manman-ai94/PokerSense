"""What players held when they bet or raised after the flop and showed down.

Checks a claim such as "a passive player's river raise is almost never a
bluff" against the PHH dataset's 2009 online no-limit hold'em logs
(``data/handhq``, the same 7-9 player games ``phh_population_stats.py``
counts). For every bet and raise after the flop it records the spot
(street, heads-up or multiway, preflop aggressor or not, bet / raise /
check-raise, size as a share of the pot) and, when that player's cards are
shown at a river showdown, what they held on the final board:

- ``strong``: two pair of their own or better (``multiway_bot.weak_hand``);
- ``pair``: a pair using a hole card that plays (top pair included; QQ on
  K K 7 7 2 too, as KKQQ7);
- ``nothing``: no pair of their own (a missed draw, or the board plays).

Bets that won without a showdown are never seen, so the shares describe the
hands that were called down: the hands a caller meets, which is what a
"should I call" rule needs.

With ``players`` names in the logs, each player's share of postflop
decisions that bet or raised over the whole dataset sorts them into
``passive`` (below ``PASSIVE``), ``aggressive`` (above ``AGGRESSIVE``) or
``normal``; fewer than ``MIN_DECISIONS`` decisions is ``few``. Every spot is
also counted over everyone (``all``). Only aggregate counts are written; no
hand or player is stored.

Dataset: Juho Kim (University of Toronto), "A Dataset of Poker Hand
Histories", Zenodo record 13997158, https://doi.org/10.5281/zenodo.13997158,
CC BY 4.0.

    PYTHONPATH=src:. .venv/bin/python tools/phh_showdown_check.py \\
        --zip ~/Projects/PokerSense_data/datasets/phh/poker-hand-histories.zip \\
        --out <dir>/phh_showdown_v1.json [--workers 8] [--limit 50]
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
import json
import math
from pathlib import Path
import tomllib
import zipfile

from phevaluator import evaluate_cards

from poker_engine.scoreboard.multiway_bot import weak_hand

STREETS = ("preflop", "flop", "turn", "river")
PLAYERS = range(7, 10)               # the 7-9 player games, as the population stats
PASSIVE, AGGRESSIVE = 0.20, 0.40     # postflop bet-or-raise share that sorts players
MIN_DECISIONS = 50
SIZES = ((0.40, "<40%"), (0.75, "40-75%"), (1.10, "75-110%"))
CATEGORIES = ("strong", "pair", "nothing")
_NAMES = {}                           # player name -> bucket, set in each worker


def size_bucket(share):
    return next((name for top, name in SIZES if share < top), ">110%")


def player_bucket(decisions, aggressive):
    if decisions < MIN_DECISIONS:
        return "few"
    share = aggressive / decisions
    if share < PASSIVE:
        return "passive"
    return "aggressive" if share > AGGRESSIVE else "normal"


def own_pair_plays(hole, board):
    """Whether the best five cards hold a pair (or more) made with one of
    ``hole``: QQ on K K 7 7 2 plays as KKQQ7, A2 there only as a kicker."""
    cards = list(hole) + list(board)
    scored = [(evaluate_cards(*five), five) for five in combinations(cards, 5)]
    best = min(score for score, _ in scored)
    for score, five in scored:
        if score == best:
            ranks = Counter(card[0] for card in five)
            if any(card in five and ranks[card[0]] >= 2 for card in hole):
                return True
    return False


def category(hole, board):
    """``strong``, ``pair`` or ``nothing`` for ``hole`` on a five-card ``board``."""
    if not weak_hand(hole, board):
        return "strong"
    if evaluate_cards(*board) == evaluate_cards(*hole, *board):
        return "nothing"                    # the board plays
    return "pair" if own_pair_plays(hole, board) else "nothing"


def _cards(text):
    return [text[i:i + 2] for i in range(0, len(text), 2)]


def in_scope(hand):
    blinds = hand["blinds_or_straddles"]
    return (len(hand["starting_stacks"]) in PLAYERS and not any(hand["antes"])
            and not any(blinds[2:]) and 0 < blinds[0] <= blinds[1])


def walk(hand):
    """(events, shown, decisions, board) of one hand.

    events: [(player, key)] for each postflop bet or raise, key
    ``street|hu or multi|pfa or other|bet, raise or check_raise|size``;
    shown: {player: [hole cards]} at a river showdown with five board cards;
    decisions: [(player, aggressive)] for every postflop decision.
    """
    players = len(hand["starting_stacks"])
    stacks = list(hand["starting_stacks"])
    blinds = hand["blinds_or_straddles"]
    committed = [blinds[i] if i < len(blinds) else 0 for i in range(players)]
    pot, street, board, folded, aggressor = 0, 0, [], set(), None
    acted, checked = [], set()
    events, shown, decisions = [], {}, []
    for text in hand["actions"]:
        parts = text.split()
        if parts[0] == "d":
            if parts[1] == "db":
                pot += sum(committed)
                stacks = [s - c for s, c in zip(stacks, committed)]
                committed = [0] * players
                street, acted, checked = street + 1, [], set()
                board += _cards(parts[2])
            continue
        player, kind = int(parts[0][1:]) - 1, parts[1]
        if kind == "sm":
            if len(parts) > 2 and "?" not in parts[2] and len(board) == 5:
                shown[player] = _cards(parts[2])
            continue
        current = max(committed)
        if street == 0:
            if kind == "cbr":
                aggressor = player
        elif kind in ("f", "cc", "cbr"):
            facing = any(k == "cbr" for _, k in acted)
            decisions.append((player, kind == "cbr"))
            if kind == "cbr":
                put = float(parts[2]) - committed[player]
                share = put / max(pot + sum(committed), 1e-9)
                move = "bet"
                if facing:
                    move = "check_raise" if player in checked else "raise"
                width = "hu" if players - len(folded) - 1 == 1 else "multi"
                role = "pfa" if player == aggressor else "other"
                name = STREETS[min(street, 3)]
                size = size_bucket(share)
                events.append((player, f"{name}|{width}|{role}|{move}|{size}"))
            elif kind == "cc" and not facing:
                checked.add(player)
        if kind == "cbr":
            committed[player] = float(parts[2])
        elif kind == "cc":
            committed[player] = min(current, stacks[player])
        elif kind == "f":
            folded.add(player)
        acted.append((player, kind))
    return events, shown, decisions, board


def _hands(zip_path, name):
    with zipfile.ZipFile(zip_path) as archive:
        text = archive.read(name).decode("utf-8")
    return tomllib.loads(text).values()


def count_players(args):
    """Pass one: {name: Counter(decisions, aggressive)} over one file."""
    totals = {}
    for hand in _hands(*args):
        names = hand.get("players")
        if not names:
            continue
        try:
            if not in_scope(hand):
                continue
            _, _, decisions, _ = walk(hand)
        except (KeyError, ValueError, IndexError):
            continue
        for player, aggressive in decisions:
            row = totals.setdefault(names[player], [0, 0])
            row[0] += 1
            row[1] += int(aggressive)
    return totals


def _set_names(names):
    _NAMES.clear()
    _NAMES.update(names)


def count_hand(hand, counts, names=None):
    """Count one hand's postflop bets and raises; False if out of scope."""
    if not in_scope(hand):
        return False
    names = _NAMES if names is None else names
    events, shown, _, board = walk(hand)
    labels = hand.get("players") or []
    for player, key in events:
        buckets = ["all"]
        if player < len(labels) and labels[player] in names:
            buckets.append(names[labels[player]])
        for bucket in buckets:
            counts[f"{key}|{bucket}|events"] += 1
            if player in shown:
                counts[f"{key}|{bucket}|shown"] += 1
                counts[f"{key}|{bucket}|{category(shown[player], board)}"] += 1
    counts["hands"] += 1
    return True


def count_file(args):
    counts = Counter()
    for hand in _hands(*args):
        try:
            count_hand(hand, counts)
        except (KeyError, ValueError, IndexError):
            counts["skipped_malformed"] += 1
    return counts


def wilson(hits, n, z=1.96):
    if not n:
        return [0.0, 0.0]
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def shares(counts):
    """{spot|bucket: {"events", "shown", category: {"count", "share", "ci95"}}}."""
    spots = {}
    for key, value in counts.items():
        if key.count("|") != 6:
            continue
        spot, field = key.rsplit("|", 1)
        spots.setdefault(spot, Counter())[field] += value
    out = {}
    for spot, row in sorted(spots.items()):
        shown = row["shown"]
        out[spot] = {"events": row["events"], "shown": shown}
        for name in CATEGORIES:
            out[spot][name] = {"count": row[name],
                               "share": round(row[name] / shown, 3) if shown else None,
                               "ci95": wilson(row[name], shown)}
    return out


def _files(zip_path, limit=None):
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(name for name in archive.namelist()
                       if name.startswith("data/handhq/") and name.endswith(".phhs"))
    if limit:
        names = names[::max(1, len(names) // limit)][:limit]
    return [(zip_path, name) for name in names]


def collect(zip_path, workers, limit=None):
    files = _files(zip_path, limit)
    totals = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for part in executor.map(count_players, files, chunksize=8):
            for name, (decisions, aggressive) in part.items():
                row = totals.setdefault(name, [0, 0])
                row[0] += decisions
                row[1] += aggressive
    names = {name: player_bucket(*row) for name, row in totals.items()}
    counts = Counter()
    with ProcessPoolExecutor(max_workers=workers, initializer=_set_names,
                             initargs=(names,)) as executor:
        for part in executor.map(count_file, files, chunksize=8):
            counts.update(part)
    return counts, Counter(names.values()), len(files)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int,
                        help="read only this many files (a quick look)")
    args = parser.parse_args(argv)
    counts, players, files = collect(args.zip, args.workers, args.limit)
    result = {
        "source": {"dataset": "https://doi.org/10.5281/zenodo.13997158",
                   "license": "CC BY 4.0",
                   "part": "data/handhq (online no-limit hold'em, July 2009), "
                           "7-9 players",
                   "files": files},
        "hands": counts["hands"], "skipped_malformed": counts["skipped_malformed"],
        "players_by_bucket": dict(players),
        "buckets": {"passive": f"postflop bet-or-raise share < {PASSIVE}",
                    "aggressive": f"> {AGGRESSIVE}",
                    "few": f"< {MIN_DECISIONS} decisions"},
        "categories": {"strong": "two pair of their own or better",
                       "pair": "one pair using a hole card",
                       "nothing": "no pair of their own"},
        "spots": shares(counts),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    print(f"{counts['hands']} hands, {len(result['spots'])} spots -> {args.out}")


if __name__ == "__main__":
    main()
