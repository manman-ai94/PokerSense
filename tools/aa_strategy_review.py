"""After a session: every one of your decisions, how its advice went, and
which ones look wrong, worst first.

``tools/aa_session_report.py`` says whether each decision got advice. This
says whether the advice was any good, from the same logs (the window's
``frames.jsonl`` of a recording, or a measurement's):

* the advice as it showed during your turn: each answer in order, with its
  kind (``preflop``, ``multiway`` for the range rule, ``solver``, ``rough``),
  its action, your share of the pot it was worked out from and when it came;
* what you did and whether it was the answer showing last (``followed``);
* flags on what to look at:

  - ``changed``: the action changed during your turn (``followed_first``:
    you acted on the first one);
  - ``rough_final``: after the flop the rough rule's answer was the last one;
  - ``strong_check``: after the flop the last answer checked or called with a
    share of the pot at or above the line the range rule bets or raises at;
  - ``sure_with_one_pair``: a share of 90% or more with one pair or less
    (the opponents' ranges were read too weak: on 10/09 a river bet with top
    pair at "100%" was called by a better hand);
  - ``no_advice``;
  - ``pot_unread``, ``price_unread``, ``cards_unread``: what the screen did
    not give at the decision (most of its frames).

The summary counts the flags by street, the decisions and your chips in bomb
pots apart, and lists the flagged decisions by pot size, the biggest first:
a mistake in a bigger pot costs more.

    PYTHONPATH=src:. .venv/bin/python tools/aa_strategy_review.py \\
        --frames <recording>/frames.jsonl [--frames ...] [--replay-advice] \\
        [--out review.json]

``--ledger <file> --label <name>`` adds this session's summary numbers to a
ledger (one JSON line per session, kept with the recordings, not in the
repository) and prints the sessions so far added up: real win rate needs
thousands of hands, so each session counts toward it. A label already in the
ledger is replaced, not counted twice.

``--replay-advice`` works the advice out again with this checkout's code
(``aa_session_report.replayed_advice``: a heads-up solve counts as done at
once, every other answer as well), to compare a fix against what was played.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.scoreboard.multiway_bot import DEFAULTS as LINES  # noqa: E402
from tools.aa_session_report import (  # noqa: E402
    HERO, load, plain, replayed_advice, session_report)

SURE = 0.9                     # a share of the pot this high with one pair is suspect
ONE_PAIR = 3325                # phevaluator ranks above this: one pair or high card
BOARD = {"flop": 3, "turn": 4, "river": 5}


def mode(values):
    values = [value for value in values if value not in (None, "")]
    return Counter(values).most_common(1)[0][0] if values else None


def answer(report, street):
    """(kind, plain action, share of the pot) of a ready advice report."""
    rows = report.get("advice") or [{}]
    kind = report.get("kind") or ("preflop" if street == "preflop" else "solver")
    share = (report.get("range_equity") or {}).get("value")
    return kind, plain(rows[0].get("action")), share


def one_pair_or_less(hero, board):
    if not hero or len(hero) != 2 or len(board) < 3:
        return False
    from phevaluator import evaluate_cards
    return evaluate_cards(*hero, *board) > ONE_PAIR


def lines_for(opponents):
    """The range rule's (bet, raise) shares against this many opponents."""
    if opponents == 1:
        return LINES["hu_bet"], LINES["hu_raise"]
    return LINES["bet"], LINES["raise"]


def decisions(name, rows, advice):
    """Your turns in one log: consecutive rows with your buttons on screen."""
    hands = {}
    for row, report in zip(rows, advice):
        history = row["fields"].get("actions_v1")
        if history and row["fields"].get("scene_supported"):
            hands.setdefault(history["hand_id"], []).append((row, report))
    result = []
    for hand_id, pairs in hands.items():
        last = pairs[-1][0]["fields"]["actions_v1"]
        keys = ("frame", "street", "slot", "kind", "amount", "source")
        actions = [dict(zip(keys, item)) for item in last["actions"]]
        turns, current = [], None
        for row, report in pairs:
            if not (row["fields"].get("hero_controls") or {}).get("visible"):
                current = None
                continue
            if current is None:
                current = []
                turns.append(current)
            current.append((row, report))
        result += [decision(name, hand_id, turn, actions) for turn in turns]
    return result


def decision(name, hand_id, turn, actions):
    fields = [row["fields"] for row, _ in turn]
    start = turn[0][0]
    street = mode(f.get("street") for f in fields)
    hero = mode(" ".join(f["hero"]) for f in fields
                if f.get("hero") and all(f["hero"]))
    board = mode(" ".join(c for c in f.get("board") or () if c) for f in fields
                 if len([c for c in f.get("board") or () if c]) == BOARD.get(street, 0))
    controls = [f.get("hero_controls") or {} for f in fields]
    button = mode(c.get("button") for c in controls)
    opponents = mode(sum(state in ("active", "all_in") for seat, state in
                         (f.get("participants") or {}).items() if seat != HERO)
                     for f in fields)
    answers, seen = [], None
    for row, report in turn:
        if report.get("status") != "ready":
            continue
        kind, action, share = answer(report, street)
        if (kind, action) != seen:
            seconds = round(row["pts_seconds"] - start["pts_seconds"], 2)
            answers.append({"seconds": seconds, "kind": kind, "action": action,
                            "share": share})
            seen = kind, action
    done = next((item for item in actions if str(item["slot"]) == HERO
                 and item["street"] == street and item["frame"] >= start["processed"]),
                None)
    item = {"log": name, "hand_id": hand_id, "street": street,
            "video_seconds": start.get("video_seconds"),
            "pts": round(start["pts_seconds"], 1), "hero": hero, "board": board,
            "pot": mode(f.get("pot") for f in fields), "button": button,
            "to_call": mode(c.get("call_amount") for c in controls),
            "opponents": opponents, "answers": answers,
            "you_did": None if done is None else plain(done["kind"])}
    item["flags"] = flags(item, fields, controls)
    if answers and item["you_did"]:
        item["followed"] = answers[-1]["action"] == item["you_did"]
    return item


def flags(item, fields, controls):
    answers, street, found = item["answers"], item["street"], []
    if not answers:
        found.append("no_advice")
    if len({answer["action"] for answer in answers}) > 1:
        found.append("changed")
        if item["you_did"] and item["you_did"] == answers[0]["action"]:
            found.append("followed_first")
    if answers and street != "preflop":
        last = answers[-1]
        if last["kind"] == "rough":
            found.append("rough_final")
        share = last["share"]
        if share is not None and item["opponents"]:
            bet, raise_ = lines_for(item["opponents"])
            if (last["action"] == "check" and share >= bet
                    or last["action"] == "call" and share >= raise_):
                found.append("strong_check")
            hero = (item["hero"] or "").split()
            board = (item["board"] or "").split()
            if share >= SURE and one_pair_or_less(hero, board):
                found.append("sure_with_one_pair")
    half = len(fields) / 2
    if sum(f.get("pot") in (None, "") for f in fields) > half:
        found.append("pot_unread")
    if sum(c.get("button") != "check" and c.get("call_amount") in (None, "")
           for c in controls) > half:
        found.append("price_unread")
    if sum(not (f.get("hero") and all(f["hero"])) for f in fields) > half:
        found.append("cards_unread")
    return found


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def review(logs, *, replay_advice=False):
    turns = []
    for name, rows in logs:
        rows = [row for row in rows if row.get("fields")]
        if replay_advice:
            advice = replayed_advice(rows)
        else:
            advice = [row["fields"].get("solver_advice")
                      or row["fields"].get("solver_advice_v1") or {} for row in rows]
        turns += decisions(name, rows, advice)
    hands = session_report(logs)["hands"]
    bombs = {(hand["log"], hand["hand_id"]) for hand in hands if hand.get("bomb_pot")}
    for turn in turns:
        turn["bomb_pot"] = (turn["log"], turn["hand_id"]) in bombs
    chips = Counter()
    for hand in hands:
        if hand["your_chips"] is not None:
            part = "bomb_pot" if hand.get("bomb_pot") else "normal"
            chips[part] += hand["your_chips"]
            chips[part + "_hands"] += 1
    return {"summary": summarize(turns, chips), "decisions": turns}


def summarize(turns, chips):
    by_flag = {}
    for turn in turns:
        for flag in turn["flags"]:
            by_flag.setdefault(flag, Counter())[turn["street"]] += 1
    seen = [turn for turn in turns if turn["answers"] and turn["you_did"]]
    worst = sorted((turn for turn in turns if set(turn["flags"]) & {
        "rough_final", "strong_check", "sure_with_one_pair", "followed_first",
        "no_advice"}), key=lambda turn: -number(turn["pot"]))
    return {"decisions": len(turns),
            "by_street": dict(Counter(turn["street"] for turn in turns)),
            "last_answer_kind": dict(Counter(
                turn["answers"][-1]["kind"] for turn in turns if turn["answers"])),
            "followed": sum(bool(turn.get("followed")) for turn in seen),
            "followed_of": len(seen),
            "flags": {flag: dict(counts) for flag, counts in sorted(by_flag.items())},
            "chips": dict(chips),
            "look_at": [{key: turn[key] for key in (
                "hand_id", "street", "video_seconds", "hero", "board", "pot",
                "opponents", "you_did", "flags")}
                | {"answers": [f"{a['kind']}:{a['action']}"
                               + (f"@{a['share']}" if a["share"] is not None else "")
                               for a in turn["answers"]]} for turn in worst]}


BIG_BLIND = 2                  # chips: the AA table plays 1/2/4 with an ante of 2


def ledger(path, label, summary):
    """Add ``summary`` to the ledger at ``path`` under ``label``; the sessions
    in it added up: hands, decisions, followed, chips and big blinds per 100
    hands, normal hands and bomb pots apart."""
    path = Path(path)
    rows = []
    if path.exists():
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8")
                .splitlines() if line.strip()]
    rows = [row for row in rows if row["label"] != label]
    chips = summary["chips"]
    rows.append({"label": label, "decisions": summary["decisions"],
                 "followed": summary["followed"], "followed_of": summary["followed_of"],
                 **{key: chips.get(key, 0) for key in (
                     "normal", "normal_hands", "bomb_pot", "bomb_pot_hands")}})
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                            for row in rows), encoding="utf-8")
    total = Counter()
    for row in rows:
        total.update({key: value for key, value in row.items() if key != "label"})
    hands = total["normal_hands"] + total["bomb_pot_hands"]
    per_100 = (lambda chips, count: round(chips / BIG_BLIND / count * 100, 1)
               if count else None)
    return {"sessions": len(rows), "hands": hands,
            "followed": total["followed"], "followed_of": total["followed_of"],
            "bb_per_100": per_100(total["normal"] + total["bomb_pot"], hands),
            "normal_bb_per_100": per_100(total["normal"], total["normal_hands"]),
            "bomb_pot_bb_per_100": per_100(total["bomb_pot"], total["bomb_pot_hands"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", required=True)
    parser.add_argument("--replay-advice", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--label")
    args = parser.parse_args(argv)
    if args.ledger and not args.label:
        parser.error("--ledger needs --label")
    logs = [(str(path.parent.name), load(path)) for path in args.frames]
    result = review(logs, replay_advice=args.replay_advice)
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=1))
    if args.ledger:
        print(json.dumps(ledger(args.ledger, args.label, result["summary"]),
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
