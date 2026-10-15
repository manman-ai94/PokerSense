"""How the long-run winners of the 2009 online games played (aggregate profiles).

Reads the PHH dataset's ``data/handhq`` logs (7-9 players, no antes, the
games ``phh_showdown_check.py`` and ``phh_population_stats.py`` use), works
out every named player's result in big blinds at each stake (big blind
size), and sorts the players with at least ``--min-hands`` hands at a stake
by their win rate and its 95% interval:

- ``winner``: the interval is above 0; ``big_winner``: a winner at
  ``--big`` bb/100 or more;
- ``loser``: the interval is below 0; ``even``: neither.

Each group's play is then pooled over its players: how often they put chips
in and raise before the flop (VPIP, PFR), open by raising or limping, raise
limpers, re-raise, fold to a re-raise, bet the flop as the preflop raiser
(heads-up and multiway), fold to that bet, bet or raise by street (and the
aggression factor), reach and win showdowns, fold to river bets, and what
they showed behind river bets of three quarters of the pot or more
(``phh_showdown_check.category``). Stakes up to ``--low-max`` are also
pooled as ``low``. A group with fewer than ``MIN_GROUP`` players is left
out, and no player, hand or name is written: only the groups' totals.

A hand's result is ``finishing_stacks`` minus ``starting_stacks`` when the
log has them, else ``winnings`` minus what the player put in (less an
uncalled bet), else the pot is settled from the shown cards without rake
(``net_source`` counts which); a showdown no shown cards decide is left out
of the results.

Dataset: Juho Kim (University of Toronto), "A Dataset of Poker Hand
Histories", Zenodo record 13997158, https://doi.org/10.5281/zenodo.13997158,
CC BY 4.0.

    PYTHONPATH=src:. .venv/bin/python tools/phh_winner_profiles.py \\
        --zip ~/Projects/PokerSense_data/datasets/phh/poker-hand-histories.zip \\
        --out <dir>/phh_winner_profiles_v1.json [--workers 8] [--limit 50]
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path
import statistics

from phevaluator import evaluate_cards

from tools.phh_showdown_check import _cards, _files, _hands, category, in_scope, wilson

MIN_HANDS = 5000
MIN_GROUP = 5             # groups with fewer players are not written
BIG = 5.0                 # bb/100 for a big winner
LOW_MAX = 0.5             # big blinds up to this (NL25, NL50) are pooled as "low"
BIG_BET = 0.75            # a river bet this share of the pot or more is "big"
STREETS = ("preflop", "flop", "turn", "river")
FIELDS = (
    "hands", "net_hands", "vpip", "pfr",
    "rfi_opp", "rfi_raise", "rfi_limp", "iso_opp", "iso_raise", "overlimp",
    "vs_raise_opp", "threebet", "vs_raise_call", "vs_3bet_opp", "fold_to_3bet",
    "cbet_hu_opp", "cbet_hu", "cbet_multi_opp", "cbet_multi",
    "vs_cbet_opp", "fold_to_cbet", "raise_cbet",
    *(f"{street}_{kind}" for street in STREETS[1:]
      for kind in ("decisions", "aggressive", "calls")),
    "saw_flop", "won_after_flop", "showdowns", "showdown_known", "won_showdown",
    "vs_river_bet_opp", "fold_to_river_bet", "vs_river_big_opp", "fold_to_river_big",
    "river_big_bets", "river_big_shown", "river_big_strong", "river_big_pair",
    "river_big_nothing",
)
INDEX = {name: i for i, name in enumerate(FIELDS)}
# (name in the output, hits, opportunities)
SHARES = (
    ("vpip", "vpip", "hands"), ("pfr", "pfr", "hands"),
    ("open_raise", "rfi_raise", "rfi_opp"), ("open_limp", "rfi_limp", "rfi_opp"),
    ("iso_raise_vs_limpers", "iso_raise", "iso_opp"),
    ("overlimp", "overlimp", "iso_opp"),
    ("threebet_vs_raise", "threebet", "vs_raise_opp"),
    ("call_vs_raise", "vs_raise_call", "vs_raise_opp"),
    ("fold_to_3bet", "fold_to_3bet", "vs_3bet_opp"),
    ("cbet_flop_hu", "cbet_hu", "cbet_hu_opp"),
    ("cbet_flop_multiway", "cbet_multi", "cbet_multi_opp"),
    ("fold_to_flop_cbet", "fold_to_cbet", "vs_cbet_opp"),
    ("raise_flop_cbet", "raise_cbet", "vs_cbet_opp"),
    *((f"{street}_bet_or_raise", f"{street}_aggressive", f"{street}_decisions")
      for street in STREETS[1:]),
    ("went_to_showdown", "showdowns", "saw_flop"),
    ("won_at_showdown", "won_showdown", "showdown_known"),
    ("won_after_flop", "won_after_flop", "saw_flop"),
    ("fold_to_river_bet", "fold_to_river_bet", "vs_river_bet_opp"),
    ("fold_to_river_big_bet", "fold_to_river_big", "vs_river_big_opp"),
    ("river_big_bet_strong", "river_big_strong", "river_big_shown"),
    ("river_big_bet_pair", "river_big_pair", "river_big_shown"),
    ("river_big_bet_nothing", "river_big_nothing", "river_big_shown"),
)


class Row(list):
    """One player's counts at one stake, plus the result in big blinds."""

    def __init__(self):
        super().__init__([0] * len(FIELDS))
        self.net = 0.0
        self.net_sq = 0.0

    def add(self, name, value=1):
        self[INDEX[name]] += value

    def merge(self, other):
        for i, value in enumerate(other):
            self[i] += value
        self.net += other.net
        self.net_sq += other.net_sq

    def get(self, name):
        return self[INDEX[name]]


def _uncalled(put):
    """Chips handed back to the biggest contributor: the part nobody matched."""
    order = sorted(range(len(put)), key=lambda i: put[i], reverse=True)
    if len(order) < 2:
        return list(put)
    back = list(put)
    back[order[0]] -= put[order[0]] - put[order[1]]
    return back


def settle(put, folded, shown, board):
    """Each player's net chips from the pots, without rake; None if a pot's
    winner is not shown."""
    put = _uncalled(put)
    live = [i for i in range(len(put)) if i not in folded]
    strength = {}
    if len(live) > 1:
        if len(board) != 5:
            return None
        strength = {i: evaluate_cards(*shown[i], *board) for i in live if i in shown}
    net = [-amount for amount in put]
    low, eligible = 0.0, []
    for level in sorted({put[i] for i in live}):
        pot = sum(min(max(amount - low, 0.0), level - low) for amount in put)
        eligible = [i for i in live if put[i] >= level]
        if len(eligible) > 1:
            eligible = [i for i in eligible if i in strength]
            if not eligible:
                return None
            best = min(strength[i] for i in eligible)
            eligible = [i for i in eligible if strength[i] == best]
        for i in eligible:
            net[i] += pot / len(eligible)
        low = level
    # A folded player's chips above every live player's (matched before the
    # fold by another player who folded later) go to the last pot's winners.
    rest = sum(max(amount - low, 0.0) for amount in put)
    for i in eligible:
        net[i] += rest / len(eligible)
    return net


def replay(hand):
    """(stats, net, folded, shown, board) of one hand.

    stats: {player: Counter of FIELDS}; net: [chips] or None.
    """
    players = len(hand["starting_stacks"])
    blinds = hand["blinds_or_straddles"]
    stacks = list(hand["starting_stacks"])
    committed = [blinds[i] if i < len(blinds) else 0 for i in range(players)]
    put = list(committed)
    stats = {i: Counter(hands=1) for i in range(players)}
    folded, shown, board = set(), {}, []
    street, aggressor = 0, None
    raises, limpers, opener = 0, 0, None
    acted = set()                               # acted voluntarily before the flop
    street_bets, first_bettor, first_size = 0, None, 0.0
    pot = 0.0
    for text in hand["actions"]:
        parts = text.split()
        if parts[0] == "d":
            if parts[1] == "db":
                pot += sum(committed)
                stacks = [s - c for s, c in zip(stacks, committed)]
                committed = [0] * players
                street += 1
                street_bets, first_bettor, first_size = 0, None, 0.0
                board += _cards(parts[2])
                if street == 1:
                    for i in range(players):
                        if i not in folded:
                            stats[i]["saw_flop"] += 1
            continue
        player, kind = int(parts[0][1:]) - 1, parts[1]
        if kind == "sm":
            if len(parts) > 2 and "?" not in parts[2]:
                shown[player] = _cards(parts[2])
            continue
        if kind not in ("f", "cc", "cbr"):
            continue
        row = stats[player]
        current = max(committed)
        if street == 0:
            _preflop(row, player, kind, current, committed[player], raises, limpers,
                     opener, acted)
            if kind == "cbr":
                raises += 1
                aggressor = player
                opener = player if raises == 1 else opener
            elif kind == "cc" and raises == 0 and player not in acted and player != 1:
                limpers += 1
            if kind != "f":
                acted.add(player)
        else:
            name = STREETS[min(street, 3)]
            opponents = players - len(folded) - 1
            row[f"{name}_decisions"] += 1
            if kind == "cbr":
                row[f"{name}_aggressive"] += 1
            elif kind == "cc" and street_bets:
                row[f"{name}_calls"] += 1
            if street == 1:
                _flop(row, player, kind, opponents, aggressor, street_bets,
                      first_bettor)
            if street == 3 and street_bets == 1:
                big = first_size >= BIG_BET
                row["vs_river_bet_opp"] += 1
                row["fold_to_river_bet"] += kind == "f"
                if big:
                    row["vs_river_big_opp"] += 1
                    row["fold_to_river_big"] += kind == "f"
            if kind == "cbr":
                size = ((float(parts[2]) - committed[player])
                        / max(pot + sum(committed), 1e-9))
                if street == 3 and size >= BIG_BET:
                    row["river_big_bets"] += 1
                    row["_river_big"] += 1
                if street_bets == 0:
                    first_bettor, first_size = player, size
                street_bets += 1
        if kind == "cbr":
            amount = float(parts[2])
            put[player] += amount - committed[player]
            committed[player] = amount
        elif kind == "cc":
            call = min(current, stacks[player]) - committed[player]
            put[player] += call
            committed[player] += call
        else:
            folded.add(player)
    return stats, put, folded, shown, board


def _preflop(row, player, kind, current, own, raises, limpers, opener, acted):
    if kind == "cbr":
        row["pfr"] = 1
    if kind == "cbr" or (kind == "cc" and current > own):
        row["vpip"] = 1
    if player in acted:
        if raises == 2 and player == opener:
            row["vs_3bet_opp"] += 1
            row["fold_to_3bet"] += kind == "f"
        return
    if raises == 0 and player != 1:
        key = "rfi" if limpers == 0 else "iso"
        row[f"{key}_opp"] += 1
        if kind == "cbr":
            row[f"{key}_raise"] += 1
        elif kind == "cc":
            row["rfi_limp" if key == "rfi" else "overlimp"] += 1
    elif raises == 1:
        row["vs_raise_opp"] += 1
        row["threebet"] += kind == "cbr"
        row["vs_raise_call"] += kind == "cc"


def _flop(row, player, kind, opponents, aggressor, street_bets, first_bettor):
    if player == aggressor and street_bets == 0:
        width = "hu" if opponents == 1 else "multi"
        row[f"cbet_{width}_opp"] += 1
        row[f"cbet_{width}"] += kind == "cbr"
    elif street_bets == 1 and first_bettor == aggressor and player != aggressor:
        row["vs_cbet_opp"] += 1
        row["fold_to_cbet"] += kind == "f"
        row["raise_cbet"] += kind == "cbr"


def hand_net(hand, put, folded, shown, board):
    """(net chips per player, source) or (None, reason)."""
    start = hand["starting_stacks"]
    if hand.get("finishing_stacks"):
        net = [f - s for f, s in zip(hand["finishing_stacks"], start)]
        return net, "finishing_stacks"
    if hand.get("winnings"):
        back = _uncalled(put)
        return [w - p for w, p in zip(hand["winnings"], back)], "winnings"
    net = settle(put, folded, shown, board)
    return (net, "settled_no_rake") if net is not None else (None, "unknown_showdown")


def count_hand(hand, rows, counts):
    """Add one hand to ``rows`` ({(name, big blind): Row}); False if out of scope."""
    names = hand.get("players")
    if not names or not in_scope(hand):
        return False
    stats, put, folded, shown, board = replay(hand)
    net, source = hand_net(hand, put, folded, shown, board)
    counts[f"net_source|{source}"] += 1
    big_blind = float(hand["blinds_or_straddles"][1])
    live = [i for i in range(len(put)) if i not in folded]
    showdown = len(live) > 1 and len(board) == 5
    for player, stat in stats.items():
        if not names[player]:
            continue
        row = rows.setdefault((names[player], big_blind), Row())
        river_big = stat.pop("_river_big", 0)
        for key, value in stat.items():
            row.add(key, value)
        mine = None if net is None else net[player] / big_blind
        if mine is not None:
            row.add("net_hands")
            row.net += mine
            row.net_sq += mine * mine
        if stat["saw_flop"] and mine is not None and mine > 0:
            row.add("won_after_flop")
        if showdown and player in live:
            row.add("showdowns")
            if mine is not None:
                row.add("showdown_known")
                row.add("won_showdown", int(mine > 0))
            if river_big and player in shown:
                row.add("river_big_shown", river_big)
                row.add(f"river_big_{category(shown[player], board)}", river_big)
    counts["hands"] += 1
    return True


def count_file(args):
    rows, counts = {}, Counter()
    for hand in _hands(*args):
        try:
            count_hand(hand, rows, counts)
        except (KeyError, ValueError, IndexError, TypeError):
            counts["skipped_malformed"] += 1
    return rows, counts


def win_rate(row):
    """(bb/100, low, high) of the 95% interval; None without hands."""
    n = row.get("net_hands")
    if n < 2:
        return None
    mean = row.net / n
    var = max(row.net_sq / n - mean * mean, 0.0) * n / (n - 1)
    half = 1.96 * math.sqrt(var / n)
    return 100 * mean, 100 * (mean - half), 100 * (mean + half)


def groups_of(rate, big=BIG):
    _, low, high = rate
    out = ["all"]
    if low > 0:
        out.append("winner")
        if rate[0] >= big:
            out.append("big_winner")
    elif high < 0:
        out.append("loser")
    else:
        out.append("even")
    return out


def profile(members):
    """Pooled shares and per-player medians of a group's players."""
    total = Row()
    for row, _ in members:
        total.merge(row)
    out = {"players": len(members), "hands": total.get("hands"),
           "bb_per_100_pooled": round(100 * total.net / max(total.get("net_hands"), 1),
                                      2),
           "bb_per_100_median": round(statistics.median(r[0] for _, r in members), 2)}
    for name, hits, chances in SHARES:
        n = total.get(chances)
        share = total.get(hits) / n if n else None
        out[name] = {"share": None if share is None else round(share, 3),
                     "ci95": wilson(total.get(hits), n), "n": n}
    for name in ("vpip", "pfr"):
        out[f"{name}_median"] = round(statistics.median(
            row.get(name) / row.get("hands") for row, _ in members), 3)
    for street in STREETS[1:]:
        calls = total.get(f"{street}_calls")
        out[f"{street}_aggression_factor"] = (
            round(total.get(f"{street}_aggressive") / calls, 2) if calls else None)
    return out


def summarize(rows, min_hands=MIN_HANDS, big=BIG, low_max=LOW_MAX):
    """{stake: {group: profile}} for groups of at least ``MIN_GROUP`` players."""
    members = {}
    for (_, big_blind), row in rows.items():
        if row.get("net_hands") < min_hands:
            continue
        rate = win_rate(row)
        if rate is None:
            continue
        stakes = [f"bb={big_blind:g}"] + (["low"] if big_blind <= low_max else [])
        for stake in stakes:
            for group in groups_of(rate, big):
                members.setdefault(stake, {}).setdefault(group, []).append((row, rate))
    return {stake: {group: profile(players) for group, players in sorted(groups.items())
                    if len(players) >= MIN_GROUP}
            for stake, groups in sorted(members.items())}


def collect(zip_path, workers, limit=None):
    rows, counts = {}, Counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for part, part_counts in executor.map(count_file, _files(zip_path, limit),
                                              chunksize=8):
            counts.update(part_counts)
            for key, row in part.items():
                rows.setdefault(key, Row()).merge(row)
    return rows, counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int,
                        help="read only this many files (a quick look)")
    parser.add_argument("--min-hands", type=int, default=MIN_HANDS)
    parser.add_argument("--big", type=float, default=BIG)
    parser.add_argument("--low-max", type=float, default=LOW_MAX)
    args = parser.parse_args(argv)
    rows, counts = collect(args.zip, args.workers, args.limit)
    hands_by_stake = Counter()
    for (_, big_blind), row in rows.items():
        hands_by_stake[f"bb={big_blind:g}"] += row.get("hands")
    result = {
        "source": {"dataset": "https://doi.org/10.5281/zenodo.13997158",
                   "license": "CC BY 4.0",
                   "part": "data/handhq (online no-limit hold'em, July 2009), "
                           "7-9 players"},
        "hands": counts["hands"], "skipped_malformed": counts["skipped_malformed"],
        "net_source": {key.split("|", 1)[1]: value for key, value in counts.items()
                       if key.startswith("net_source|")},
        "player_hands_by_stake": dict(sorted(hands_by_stake.items())),
        "groups": {"winner": "95% interval of bb/100 above 0",
                   "big_winner": f"winner at {args.big} bb/100 or more",
                   "loser": "95% interval below 0", "even": "neither",
                   "min_hands": args.min_hands, "low": f"big blind <= {args.low_max}",
                   "min_players": MIN_GROUP},
        "profiles": summarize(rows, args.min_hands, args.big, args.low_max),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    print(f"{counts['hands']} hands, {len(rows)} player-stakes -> {args.out}")


if __name__ == "__main__":
    main()
