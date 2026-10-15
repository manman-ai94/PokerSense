"""How the heads-up solver's turn and river advice treats passive players.

The solver plays the street as an equilibrium: it bluffs at a balanced rate
and, facing a bet, expects the bettor to bluff at one too. Against the AA
players, who call a lot and whose big river bets are rarely bluffs, that may
cost. This reads the window's logs (``frames.jsonl``) and counts, over every
heads-up turn and river decision the solver answered (the first ready answer
of each decision), by the opponent's read:

- ``open``: nothing to call. ``bluff_weight`` is the solver's bet frequency
  summed over the decisions where your hand is no pair of your own (the
  board plays, or a draw): how often it advised betting with nothing.
- ``facing_big``: a bet of three quarters of the pot or more to call.
  ``weak_continue`` sums the call and raise frequencies where you hold one
  pair or less of your own (``multiway_bot.weak_hand``): how often it
  advised paying off with a bluff-catcher.

- ``style|<rule>``: on the river, the decisions a style rule
  (``scoreboard.style_rules``, off in the window for now) would change, and
  the bet, call and raise frequency it would take away (``moved``). Worked
  out from the logged answer (after the big-pot guard) with the price
  ``to_call / (pot + to_call)``: the log has no seats' chips, so no rake and
  no side pots, and a raise of your bet counts only when its price is big.
  ``--list`` also prints each change (hand, rule, the advice before) for
  review; keep that output in the data folder.

The opponent is ``passive`` when the window's reads on that seat show at
least ``MIN_POSTFLOP`` decisions after the flop and a bet-or-raise share
below ``PASSIVE``, ``aggressive`` above ``AGGRESSIVE``, else ``unknown``
(the thresholds the PHH showdown check uses). Without ``--list`` only
counts are written.

    PYTHONPATH=src:. .venv/bin/python tools/aa_solver_style_check.py \\
        --frames <recording>/frames.jsonl [...] [--out result.json] [--list]
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from poker_engine.scoreboard.multiway_bot import (  # noqa: E402
    _board_kind, hand_kind, weak_hand)
from poker_engine.scoreboard.style_rules import RULES, adjust  # noqa: E402

HERO = "4"
IN_HAND = ("active", "all_in")
MIN_POSTFLOP = 10
PASSIVE, AGGRESSIVE = 0.20, 0.40
BIG = 0.75


def villain_type(read):
    if not read or (read.get("postflop") or 0) < MIN_POSTFLOP:
        return "unknown"
    share = read.get("aggression") or 0.0
    if share < PASSIVE:
        return "passive"
    return "aggressive" if share > AGGRESSIVE else "normal"


def nothing(hole, board):
    """No pair or better of your own: the board's kind is all you have."""
    return hand_kind(list(hole) + list(board)) == _board_kind(board)


def frequency(advice, actions):
    return sum(float(row.get("frequency") or 0) for row in advice
               if row.get("action") in actions)


def decisions(rows):
    """The first ready solver answer of each heads-up turn or river decision,
    with the frame's fields."""
    seen = set()
    for row in rows:
        fields = row.get("fields") or {}
        report = fields.get("solver_advice") or fields.get("solver_advice_v1") or {}
        if (report.get("status") != "ready" or report.get("kind")
                or report.get("provisional")
                or report.get("street") not in ("turn", "river")):
            continue
        key = (report.get("hand_id"), report.get("street"), report.get("decision"))
        if key in seen:
            continue
        seen.add(key)
        yield fields, report


def strategy_of(advice):
    """The logged advice rows as {action: frequency}, as ``adjust`` takes it."""
    strategy = {}
    for row in advice:
        label = " ".join(filter(None, (str(row.get("action") or "").upper(),
                                       row.get("chips"))))
        strategy[label] = strategy.get(label, 0.0) + float(row.get("frequency") or 0)
    return strategy


def style_changes(hole, board, villain, report):
    """[(rule, frequency moved)] for each rule that changes this river answer."""
    to_call = float(report.get("to_call") or 0)
    pot = float(report.get("pot") or 0) + max(0.0, float(report.get("pot_offset") or 0))
    observation = {"street": "river", "observing_seat": int(HERO),
                   "occupied_seats": [int(HERO), int(villain)], "folded": [],
                   "own_hole": list(hole), "board": list(board),
                   "pot": pot, "to_call": to_call, "bets": {HERO: 0},
                   "reads": report.get("seat_reads") or {}}
    strategy = strategy_of(report.get("advice") or [])
    changes = []
    for rule in RULES:
        changed, applied = adjust(strategy, observation, {rule})
        if applied:
            changes.append((rule, round(sum(
                share for action, share in strategy.items()
                if action.startswith(("BET", "RAISE", "CALL"))) - sum(
                share for action, share in changed.items()
                if action.startswith(("BET", "RAISE", "CALL"))), 3)))
    return changes


def count(rows, counts, listed=None):
    for fields, report in decisions(rows):
        hole = [card for card in fields.get("hero") or () if card]
        board = [card for card in fields.get("board") or () if card]
        others = [seat for seat, state in (fields.get("participants") or {}).items()
                  if seat != HERO and state in IN_HAND]
        if len(hole) != 2 or len(board) < 4 or len(others) != 1:
            counts["skipped"] += 1
            continue
        kind = villain_type((report.get("seat_reads") or {}).get(others[0]))
        street, advice = report["street"], report.get("advice") or []
        to_call, pot = float(report.get("to_call") or 0), float(report.get("pot") or 0)
        if street == "river" and len(board) == 5:
            for rule, moved in style_changes(hole, board, others[0], report):
                for who in (kind, "all"):
                    counts[f"river|{who}|style_{rule}|decisions"] += 1
                    counts[f"river|{who}|style_{rule}|moved"] += moved
                if listed is not None:
                    listed.append({"hand_id": report.get("hand_id"),
                                   "decision": report.get("decision"), "rule": rule,
                                   "villain": kind, "to_call": to_call, "pot": pot,
                                   "was": advice})
        for who in (kind, "all"):
            prefix = f"{street}|{who}"
            if to_call == 0:
                counts[f"{prefix}|open|decisions"] += 1
                if nothing(hole, board):
                    counts[f"{prefix}|open|nothing"] += 1
                    counts[f"{prefix}|open|bluff_weight"] += frequency(advice, ("bet",))
            elif pot > to_call and to_call / (pot - to_call) >= BIG:
                counts[f"{prefix}|facing_big|decisions"] += 1
                if weak_hand(hole, board):
                    counts[f"{prefix}|facing_big|weak"] += 1
                    counts[f"{prefix}|facing_big|weak_continue"] += frequency(
                        advice, ("call", "raise"))
    return counts


def summary(counts):
    out = {"skipped": counts.get("skipped", 0)}
    for key in sorted(counts):
        if key.count("|") != 3:
            continue
        street, who, spot, field = key.split("|")
        out.setdefault(f"{street}|{who}|{spot}", {})[field] = round(counts[key], 2)
    for row in out.values():
        if not isinstance(row, dict):
            continue
        for weight, base in (("bluff_weight", "nothing"), ("weak_continue", "weak")):
            if row.get(base):
                row[f"{weight}_share"] = round(row.get(weight, 0) / row[base], 3)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--frames", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--list", action="store_true",
                        help="also list each decision a style rule would change")
    args = parser.parse_args(argv)
    counts, listed = Counter(), [] if args.list else None
    for path in args.frames:
        with path.open(encoding="utf-8") as handle:
            count((json.loads(line) for line in handle if line.strip()), counts, listed)
    result = summary(counts)
    if listed is not None:
        result["changes"] = listed
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
