"""How real AA players play, before and after the flop, from measured recordings.

Two steps. ``reduce`` turns one measurement log (``frames.jsonl`` of
``tools/measure_aa_realtime.py``) into one line per hand: the rebuilt action
history (``actions_v1``), the dealer, the occupied seats and, for every
action, the steady pot before it. ``build`` counts the decisions of those
hands into aggregate statistics for an "AA real players" opponent model:
preflop by position and table size (VPIP, PFR, 3-bet, limp, fold to a 3-bet,
raise/call/fold per kind of decision), postflop by the population bot's
situations (``spots.postflop_spot``), bet sizes as a share of the pot, how
many players see the flop and how often they reach a showdown. Every share
carries its count and a 95% Wilson interval. Only totals are written; no
hand, seat or player.

A hand is used street by street: as long as its actions follow the seat
order (first preflop action from the seat after the straddle, every later
one from the next seat still in, each postflop street from the first seat
still in after the button), the street counts; from the first street that
breaks the order (a missed or misread action) the rest of the hand does not.
Seats that never act in a hand are taken as sitting out. The decisions of
peng's own seat (``aa_solver_advice.HERO``, bottom centre) in logs where
peng plays (``--hero-logs``)
shape the history but are not counted.

    PYTHONPATH=src:. .venv/bin/python tools/aa_population_stats.py reduce \\
        <measurement>/frames.jsonl --name <log name> >> hands.jsonl
    PYTHONPATH=src:. .venv/bin/python tools/aa_population_stats.py build \\
        hands.jsonl --hero-logs <name,...> [--minutes <name>=<minutes> ...] \\
        [--out stats.json]
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import sys

from poker_engine.desktop.aa_solver_advice import HERO as HERO_SEAT
from poker_engine.scoreboard.spots import postflop_spot, preflop_spot
from tools.check_aa_action_history import (
    FIELDS_V1, labelled_kinds, load, pot_runs)

STREETS = ("preflop", "flop", "turn", "river")
NOT_SEATED = ("empty", "waiting")
LETTER = {"fold": "f", "check": "c", "call": "c", "raise": "r"}
SIZE_GROUPS = {4: "4-6", 5: "4-6", 6: "4-6", 7: "7-8", 8: "7-8"}
# Bet sizes as a share of the pot before the bet; the last bucket is open.
SIZE_EDGES = (0.25, 0.4, 0.6, 0.8, 1.05, 1.6)
SIZE_NAMES = ("<25%", "25-40%", "40-60%", "60-80%", "80-105%", "105-160%", ">160%")
USABLE, ROUGH = 30, 10
FIELDS = {
    "groups": "ALL, players_4-6, players_7-8: the same counts for every table, "
              "4-6 player tables and 7-8 player tables (players dealt in)",
    "player": "<position or ALL>|<stat>: share of player-hands; n = chances, hits",
    "player stats": {
        "vpip": "put chips in voluntarily before the flop (a straddle's or "
                "blind's check is not)",
        "pfr": "raised before the flop",
        "rfi_raise / rfi_limp": "first in (nobody in yet): raised / just called",
        "three_bet": "re-raised when facing one raise (also after limping)",
        "fold_to_3bet": "opened, then folded to a re-raise",
        "saw_flop": "still in when the flop came",
        "wtsd": "of players who saw the flop: reached a showdown (hands whose end "
                "was read; biased low, see hands|flop_to_river_card)",
        "postflop_aggressive_share": "after the flop: bets and raises among "
                                     "bets, raises and calls",
    },
    "hands": "hands|...: per hand: reach_flop (two or more see it), flop_headsup / "
             "flop_3way / flop_4plus, flop_to_river_card (the fifth card dealt), "
             "showdown_after_flop, dealer_as_read (dealer from the screen, else "
             "implied by the first action)",
    "preflop": "<position or ALL>|<kind of decision> (spots.preflop_spot): "
               "raise / call / fold with count, share, ci95",
    "postflop": "<street>|<hu or multi>|<pfa or other>|<checked_to, facing_bet, "
                "facing_raise> (spots.postflop_spot, as the population bot); "
                "<street>|ALL; flop|vs_cbet = facing the preflop raiser's flop bet",
    "sizes": "bets and raises as a share of the pot just before them: median, "
             "quartiles, buckets; preflop_open / preflop_iso_raise (over limpers) "
             "/ preflop_reraise; <street>_bet / _raise; postflop_<bet or "
             "raise>_<hu or multi>",
    "grade": (f"usable n >= {USABLE}, rough {ROUGH} <= n < {USABLE}, "
              f"too_few n < {ROUGH}"),
    "ci95": "95% Wilson interval of the share",
    "more_video_hours": "extra hours of recordings like these for n to reach 30 "
                        "(about +-15 points) and 100 (about +-9 points)",
    "reference_2009_7to9": "2009 online shares (7-9 players) for the same keys; "
                           "AA's STR is compared with 2009's BB, BB with SB, UTG1 "
                           "with EP",
}


# ----------------------------------------------------------------- reduce


def _pot(value):
    try:
        return Decimal(value) if value not in (None, "") else None
    except InvalidOperation:
        return None


def pot_before(by_frame, frame, before=10, after=15):
    """Steady pot just before an action: the run before the nearest pot rise,
    else the last steady run up to the action (checks and folds)."""
    runs = pot_runs(by_frame, frame - before, frame + after)
    steps = [(abs(b[1] - frame), a[0]) for a, b in zip(runs, runs[1:]) if b[0] > a[0]]
    if steps:
        return str(min(steps)[1])
    prior = [run for run in runs if run[1] <= frame]
    return str(prior[-1][0]) if prior else None


def reduce_log(rows, name):
    """One record per hand of a measurement log (see the module notes)."""
    by_frame, hands = {}, {}
    for row in rows:
        fields = row.get("fields") or {}
        if row.get("processed") is not None:
            by_frame[row["processed"]] = {"fields": {"pot": fields.get("pot")}}
        history = fields.get("actions_v1")
        if not history:
            continue
        hand = hands.setdefault(history["hand_id"], {
            "log": name, "hand_id": history["hand_id"],
            "seats_first": fields.get("participants") or {}, "board_max": 0})
        board = sum(1 for card in fields.get("board") or [] if card)
        hand.update(complete=history["complete"], dealer=history["dealer"],
                    actions=[dict(zip(FIELDS_V1, item))
                             for item in history["actions"]],
                    board_max=max(hand["board_max"], board))
    for hand in hands.values():
        for action in hand["actions"]:
            if action["frame"] is not None:
                action["pot_before"] = pot_before(by_frame, action["frame"])
    return list(hands.values())


# ----------------------------------------------------------------- replay


def position_names(players):
    """Position names in seat order from the small blind to the button.

    AA tables post a straddle, so the third seat after the button acts last
    before the flop and the seat after it first.
    """
    middle = ("UTG1", "LJ", "HJ", "CO")[4 - min(players - 4, 4):]
    return ("SB", "BB", "STR", *middle, "BTN")


def seats_in_order(dealer, seats):
    """``seats`` in acting order from the seat after ``dealer``."""
    return [(dealer + step) % 8 for step in range(1, 9) if (dealer + step) % 8 in seats]


def dealt_seats(hand):
    """Seats in the hand: those that act, plus the blind a walk leaves silent."""
    acted = {action["slot"] for action in hand["actions"]}
    seated = {int(seat) for seat, state in (hand.get("seats_first") or {}).items()
              if state not in NOT_SEATED}
    preflop = [a for a in hand["actions"] if a["street"] == "preflop"]
    silent = (seated | acted) - acted
    walk = (preflop and len(silent) == 1 and all(a["kind"] == "fold" for a in preflop)
            and {a["slot"] for a in preflop} == acted)
    return acted | silent if walk else acted


def dealer_candidates(hand, seats):
    """The dealer read on screen, then the one the first preflop action implies.

    The first seat to act before the flop sits right after the straddle, so
    the button is four seats before it. The reader's dealer is sometimes the
    previous hand's.
    """
    result = [] if hand.get("dealer") is None else [hand["dealer"]]
    preflop = [a for a in hand["actions"] if a["street"] == "preflop"]
    if preflop and preflop[0]["slot"] in seats:
        cycle = seats_in_order(preflop[0]["slot"], seats)   # first actor is last
        implied = cycle[(len(cycle) - 1 - 4) % len(cycle)]
        if implied not in result:
            result.append(implied)
    return result


def replay(hand):
    """The countable decisions of a hand, street by street (module notes).

    Returns a dict: ``players`` (seat -> position), ``decisions``, ``streets``
    (the streets whose actions follow the seat order), ``closed`` (those whose
    betting round also finished), ``remaining`` (seats not folded) and
    ``dealer`` ("read" or "implied"). None when the preflop actions do not
    follow the seat order from any dealer, or fewer than four players.
    """
    seats = dealt_seats(hand)
    if len(seats) < 4:
        return None
    for dealer in dealer_candidates(hand, seats):
        result = _play(hand, seats_in_order(dealer, seats))
        if "preflop" in result["streets"]:
            result["dealer"] = "read" if dealer == hand.get("dealer") else "implied"
            return result
    return None


def _play(hand, order):
    names = dict(zip(order, position_names(len(order))))
    kinds = labelled_kinds(hand["actions"])
    folded, all_in, decisions = set(), set(), []
    streets, closed, aggressor = [], [], None
    current, done, pending, expected = 0, [], set(order), order[3 % len(order)]
    for action, kind in zip(hand["actions"], kinds):
        label = STREETS.index(action["street"]) if action["street"] in STREETS else -1
        if not pending and current < 3 and len(order) - len(folded) >= 2:
            closed.append(STREETS[current])
            streets.append(STREETS[current])
            current, done = current + 1, []
            pending = {seat for seat in order if seat not in folded | all_in}
            expected = _next_live(order, order[-1], folded, all_in)
        elif label > current and pending:
            break                      # the round never finished: missed actions
        seat, letter = action["slot"], LETTER.get(kind)
        if seat != expected or letter is None or not pending:
            break
        street = STREETS[current]
        facing = any(other == "r" for _, other in done)
        if street == "preflop":
            spot = preflop_spot(done, seat)
            choice = {"f": "fold", "c": "call", "r": "raise"}[letter]
        else:
            spot = postflop_spot(street, done, seat, len(order) - len(folded) - 1,
                                 aggressor)
            choice = {"f": "fold", "c": "call" if facing else "check",
                      "r": "raise" if facing else "bet"}[letter]
        decisions.append({
            "street": street, "seat": seat, "position": names[seat], "spot": spot,
            "choice": choice, "action": action["kind"],
            "facing_from": _last_raiser(done), "share": _share(action, letter)})
        done.append((seat, letter))
        if letter == "r":
            pending = {s for s in order if s not in folded | all_in} - {seat}
            if street == "preflop":
                aggressor = seat
        pending.discard(seat)
        if letter == "f":
            folded.add(seat)
        if action["kind"] == "all_in":
            all_in.add(seat)
        expected = _next_live(order, seat, folded, all_in)
    else:
        streets.append(STREETS[current])
        if not pending or len(order) - len(folded) < 2:
            closed.append(STREETS[current])
    valid = set(streets)
    decisions = [d for d in decisions if d["street"] in valid]
    return {"players": names, "decisions": decisions, "streets": streets,
            "closed": closed, "remaining": [s for s in order if s not in folded],
            "live": [s for s in order if s not in folded | all_in]}


def _next_live(order, seat, folded, all_in):
    """The next seat after ``seat`` that can still act."""
    index = order.index(seat)
    for step in range(1, len(order) + 1):
        candidate = order[(index + step) % len(order)]
        if candidate not in folded and candidate not in all_in:
            return candidate
    return None


def _last_raiser(actions):
    raisers = [seat for seat, kind in actions if kind == "r"]
    return raisers[-1] if raisers else None


def _share(action, letter):
    """Chips put in as a share of the steady pot before the action."""
    if letter != "r":
        return None
    amount, pot = _pot(action.get("amount")), _pot(action.get("pot_before"))
    if amount is None or not pot:
        return None
    return float(amount / pot)


# ----------------------------------------------------------------- counting


def wilson(hits, n, z=1.96):
    if not n:
        return None
    share = hits / n
    centre = (share + z * z / (2 * n)) / (1 + z * z / n)
    spread = math.sqrt(share * (1 - share) / n + z * z / (4 * n * n))
    half = z * spread / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def grade(n):
    return "usable" if n >= USABLE else "rough" if n >= ROUGH else "too_few"


def rate(hits, n):
    return {"n": n, "hits": hits, "share": round(hits / n, 3) if n else None,
            "ci95": wilson(hits, n), "grade": grade(n)}


def choices(counter):
    n = sum(counter.values())
    return {"n": n, "grade": grade(n),
            **{choice: {"count": count, "share": round(count / n, 3),
                        "ci95": wilson(count, n)}
               for choice, count in sorted(counter.items())}}


def size_bucket(share):
    for edge, name in zip(SIZE_EDGES, SIZE_NAMES):
        if share < edge:
            return name
    return SIZE_NAMES[-1]


def sizes(shares):
    if not shares:
        return {"n": 0, "grade": grade(0)}
    ordered = sorted(shares)
    buckets = Counter(size_bucket(share) for share in ordered)
    return {"n": len(ordered), "grade": grade(len(ordered)),
            "median": round(ordered[len(ordered) // 2], 2),
            "quartiles": [round(ordered[len(ordered) // 4], 2),
                          round(ordered[(3 * len(ordered)) // 4], 2)],
            "buckets": {name: buckets.get(name, 0) for name in SIZE_NAMES}}


class Tally:
    """Counts of one population of player-hands and decisions."""

    def __init__(self):
        self.player = defaultdict(lambda: [0, 0])    # stat -> [hits, chances]
        self.preflop = defaultdict(Counter)          # "<pos>|<spot>" -> choices
        self.postflop = defaultdict(Counter)         # postflop spot -> choices
        self.sizes = defaultdict(list)               # what -> pot shares

    def chance(self, stat, hit):
        self.player[stat][1] += 1
        self.player[stat][0] += int(bool(hit))

    def report(self):
        def table(items, make):
            return {key: make(value) for key, value in sorted(items.items())}
        return {"player": table(self.player, lambda value: rate(*value)),
                "preflop": table(self.preflop, choices),
                "postflop": table(self.postflop, choices),
                "sizes": table(self.sizes, sizes)}


def count_hand(hand, tallies, hero):
    """Add one hand to ``tallies`` (keyed by group name); True if it counted."""
    placed = replay(hand)
    if placed is None or "preflop" not in placed["closed"]:
        return False
    players, decisions = placed["players"], placed["decisions"]
    remaining = placed["remaining"]
    targets = [tallies["ALL"], tallies[f"players_{SIZE_GROUPS.get(len(players))}"]]
    out_preflop = {d["seat"] for d in decisions
                   if d["street"] == "preflop" and d["choice"] == "fold"}
    saw_flop = [seat for seat in players if seat not in out_preflop]
    if len(saw_flop) < 2:
        saw_flop = []
    # The whole hand is known when its last read street finished and nothing
    # could follow: one player left, the river done, or all in and run out.
    whole = placed["closed"][-1:] == placed["streets"][-1:] and (
        len(remaining) < 2 or "river" in placed["closed"]
        or (len(placed["live"]) <= 1 and hand.get("board_max", 0) == 5))
    showdown = whole and len(remaining) >= 2
    for target in targets:
        target.chance("hands|dealer_as_read", placed["dealer"] == "read")
        target.chance("hands|reach_flop", saw_flop)
        if saw_flop:
            target.chance("hands|flop_headsup", len(saw_flop) == 2)
            target.chance("hands|flop_3way", len(saw_flop) == 3)
            target.chance("hands|flop_4plus", len(saw_flop) >= 4)
            target.chance("hands|flop_to_river_card", hand.get("board_max", 0) == 5)
        if saw_flop and whole:
            target.chance("hands|showdown_after_flop", showdown)
    for seat, name in players.items():
        if hero and seat == HERO_SEAT:
            continue
        mine = [d for d in decisions if d["seat"] == seat]
        pre = [d for d in mine if d["street"] == "preflop"]
        if not pre:
            continue                  # a walk: the blind never decided
        for target in targets:
            for key in ("ALL", name):
                _player_stats(target, key, pre, mine)
                target.chance(f"{key}|saw_flop", seat in saw_flop)
                if seat in saw_flop:
                    if whole:
                        target.chance(f"{key}|wtsd", showdown and seat in remaining)
    for decision in decisions:
        if hero and decision["seat"] == HERO_SEAT:
            continue
        for target in targets:
            _decision_stats(target, decision, decisions)
    return True


def _player_stats(target, key, pre, mine):
    target.chance(f"{key}|vpip",
                  any(d["action"] in ("call", "raise", "all_in") for d in pre))
    target.chance(f"{key}|pfr", any(d["choice"] == "raise" for d in pre))
    first = pre[0]
    if first["spot"] == "rfi":
        target.chance(f"{key}|rfi_raise", first["choice"] == "raise")
        target.chance(f"{key}|rfi_limp", first["choice"] == "call")
    for decision in pre:
        if decision["spot"] in ("vs_open", "limp_vs_raise"):
            target.chance(f"{key}|three_bet", decision["choice"] == "raise")
        if decision["spot"] == "open_vs_3bet":
            target.chance(f"{key}|fold_to_3bet", decision["choice"] == "fold")
    post = [d for d in mine if d["street"] != "preflop"]
    for decision in post:
        if decision["choice"] in ("bet", "raise", "call"):
            target.chance(f"{key}|postflop_aggressive_share",
                          decision["choice"] != "call")


def _decision_stats(target, decision, decisions):
    street, spot, choice = decision["street"], decision["spot"], decision["choice"]
    if street == "preflop":
        target.preflop[f"{decision['position']}|{spot}"][choice] += 1
        target.preflop[f"ALL|{spot}"][choice] += 1
        if choice == "raise" and decision["share"] is not None:
            what = {"rfi": "preflop_open", "vs_limp": "preflop_iso_raise"}.get(
                spot, "preflop_reraise")
            target.sizes[what].append(decision["share"])
        return
    target.postflop[spot][choice] += 1
    target.postflop[f"{street}|ALL"][choice] += 1
    _, width, role, facing = spot.split("|")
    if street == "flop" and facing == "facing_bet":
        bettor = decision["facing_from"]
        pfa = _preflop_aggressor(decisions)
        if bettor is not None and bettor == pfa:
            target.postflop["flop|vs_cbet"][choice] += 1
    if choice in ("bet", "raise") and decision["share"] is not None:
        target.sizes[f"{street}_{choice}"].append(decision["share"])
        target.sizes[f"postflop_{choice}_{width}"].append(decision["share"])


def _preflop_aggressor(decisions):
    raisers = [d["seat"] for d in decisions
               if d["street"] == "preflop" and d["choice"] == "raise"]
    return raisers[-1] if raisers else None


def build(hands, hero_logs=(), minutes=None, reference=None):
    tallies = defaultdict(Tally)
    sources = defaultdict(Counter)
    for hand in hands:
        source = sources[hand["log"]]
        source["hands"] += 1
        if not hand.get("complete"):
            continue
        source["complete"] += 1
        if count_hand(hand, tallies, hand["log"] in hero_logs):
            source["counted"] += 1
    counted = sum(source["counted"] for source in sources.values())
    total_minutes = sum((minutes or {}).values())
    report = {
        "schema_version": 1,
        "method": __doc__.split("\n\n")[1].replace("\n", " ") + " "
        + __doc__.split("\n\n")[2].replace("\n", " "),
        "positions": ("SB, BB, STR (the straddle, acts last before the flop), "
                      "UTG1 (first after the straddle), LJ, HJ, CO, BTN; short tables "
                      "drop UTG1 first, then LJ, then HJ"),
        "fields": FIELDS,
        "size_buckets": ("chips put in by a bet or raise as a share of the steady "
                         "pot just before it (preflop: blinds, straddle, antes and "
                         "earlier bets)"),
        "sources": [{"log": name, **dict(counts),
                     **({"video_minutes": minutes[name]} if minutes and name in minutes
                        else {})} for name, counts in sorted(sources.items())],
        "hands_counted": counted,
        "video_minutes": round(total_minutes, 1) if total_minutes else None,
        "counted_hands_per_hour": (round(counted / total_minutes * 60, 1)
                                   if total_minutes else None),
        "groups": {name: tally.report() for name, tally in sorted(tallies.items())},
    }
    if total_minutes:
        hours = total_minutes / 60
        for group in report["groups"].values():
            for table in group.values():
                for entry in table.values():
                    entry["more_video_hours"] = more_hours(entry["n"], hours)
    if reference:
        report["reference_2009_7to9"] = reference
    return report


def more_hours(n, hours):
    """Extra hours of recordings (at this table's pace) to reach each count.

    30 decisions pin a share to about +-15 points, 100 to about +-9.
    """
    if not n:
        return None
    return {str(target): round(max(0.0, (target - n) / (n / hours)), 1)
            for target in (USABLE, 100)}


def phh_reference(report):
    """2009 online shares (7-9 players) for the spots the AA report has."""
    path = (Path(__file__).resolve().parents[1]
            / "src/poker_engine/scoreboard/phh_population_stats_v1.json")
    frequencies = json.loads(path.read_text(encoding="utf-8"))["frequencies"]["7-9"]
    spots = set()
    for group in report["groups"].values():
        spots |= set(group["preflop"]) | set(group["postflop"])
    aliases = {"STR": "BB", "BB": "SB", "UTG1": "EP"}
    result = {}
    for spot in sorted(spots):
        head, _, rest = spot.partition("|")
        key = f"{aliases.get(head, head)}|{rest}" if head in aliases else spot
        if key in frequencies:
            result[spot] = frequencies[key]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("reduce", help="measurement log -> hand lines on stdout")
    one.add_argument("frames", type=Path)
    one.add_argument("--name", required=True)
    two = sub.add_parser("build", help="hand lines -> statistics JSON")
    two.add_argument("hands", nargs="+", type=Path)
    two.add_argument("--hero-logs", default="")
    two.add_argument("--minutes", nargs="*", default=[])
    two.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "reduce":
        for hand in reduce_log(load(args.frames), args.name):
            sys.stdout.write(json.dumps(hand) + "\n")
        return
    hands = [json.loads(line) for path in args.hands
             for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    minutes = {name: float(value) for name, value in
               (item.split("=") for item in args.minutes)}
    report = build(hands, set(filter(None, args.hero_logs.split(","))), minutes)
    report["reference_2009_7to9"] = phh_reference(report)
    text = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(f"{report['hands_counted']} hands counted", file=sys.stderr)


if __name__ == "__main__":
    main()
