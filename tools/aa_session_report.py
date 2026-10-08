"""A played session, hand by hand: your decisions, the advice, and what went wrong.

Reads the ``frames.jsonl`` logs that ``tools/measure_aa_realtime.py --advice``
writes for the recordings of one session and reports, for every hand: the
players, whether you were in it and your cards were read, each of your
decisions (your buttons on screen) with the advice it got or why none came,
the betting-history checks of ``tools/check_aa_action_history.py``, whether
the hand replays on the AA table (``aa_solver_input.check_hand``) and the
stalls (more than a second between two shown frames). The summary counts the
causes over the session, most frequent first.

    PYTHONPATH=src:. .venv/bin/python tools/aa_session_report.py \\
        --frames <measurement>/frames.jsonl [--frames ...] [--out report.json]

The window's own log of a recording (``frames.jsonl`` in the recording's
folder, what it read and advised during play) reads the same way; each hand
then says where it starts in the video (``video_seconds``).

A log measured without ``--advice`` has no solver advice for your heads-up
turn and river; ``--replay-advice`` then works the advice out again from the
log with the current code, taking any heads-up solve as done (no TexasSolver).
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import Future
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_solver_input import check_hand, hand_facts  # noqa: E402
from tools.check_aa_action_history import (  # noqa: E402
    skipped_seats, unexplained_rises, unrecorded_folds)

HERO = "4"
IN_HAND = ("active", "all_in")
STALL = 1.0          # seconds between two shown frames that count as a stall
STALE = 2.0          # the live window clears the table after this long
LATE = 3.0           # advice later than this after your buttons showed
MISREAD = 3          # frames a second reading of one card needs to count


def load(path):
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class _Now:
    def submit(self, function, *args):
        done = Future()
        done.set_result(function(*args))
        return done


class _Solved:
    """Stands in for TexasSolver: any heads-up solve comes back at once."""

    def solved_spot(self, observation, salt):
        action = "CALL" if float(observation["to_call"] or 0) else "CHECK"
        return {action: 1.0}, {"AsAh": 1.0}


def replayed_advice(rows):
    """Each row's advice worked out again with the current code."""
    from poker_engine.desktop.aa_solver_advice import AASolverAdvice
    advice = AASolverAdvice(_Solved(), _Now())
    return [advice.observe_fields(row["fields"], row["processed"]) for row in rows]


def cause(report):
    """Why a decision got no advice, in a few words."""
    status, reason = report.get("status"), report.get("reason")
    if status == "computing":
        return "solve_not_finished"
    if reason in ("waiting_for_last_action", "not_your_turn_yet"):
        return "history_says_not_your_turn"
    return f"{status}:{reason}"


def decisions(rows, advice):
    """Your turns: consecutive rows with your buttons on screen."""
    result, current = [], None
    for row, report in zip(rows, advice):
        fields = row["fields"]
        if not (fields.get("hero_controls") or {}).get("visible"):
            current = None
            continue
        if current is None:
            current = {"pts": round(row["pts_seconds"], 1),
                       "street": fields.get("street"), "reports": [],
                       "first_ready": None, "cards_read": False}
            result.append(current)
        current["reports"].append(report)
        current["cards_read"] |= len([c for c in fields.get("hero") or () if c]) == 2
        if report.get("status") == "ready" and current["first_ready"] is None:
            current["first_ready"] = round(row["pts_seconds"] - current["pts"], 2)
            current["kind"] = report.get("kind")
            current["advice"] = [option.get("action") for option in
                                 (report.get("advice") or [])[:1]]
        current["seconds"] = round(row["pts_seconds"] - current["pts"], 1)
    for turn in result:
        reports = turn.pop("reports")
        if turn["first_ready"] is None:
            causes = Counter(cause(r) for r in reports if r.get("status") != "ready")
            turn["cause"] = causes.most_common(1)[0][0] if causes else "none"
        elif turn["first_ready"] > LATE:
            turn["cause"] = "advice_late"
    return result


def stalls(rows):
    """Gaps between two frames shown one after the other, in seconds."""
    gaps = []
    for before, after in zip(rows, rows[1:]):
        one = (before.get("timing") or {}).get("published_at")
        two = (after.get("timing") or {}).get("published_at")
        if one is not None and two is not None and two - one > STALL:
            gaps.append({"pts": round(after["pts_seconds"], 1),
                         "seconds": round(two - one, 2)})
    return gaps


def hand_report(rows, advice, gaps=()):
    fields = [row["fields"] for row in rows]
    facts = hand_facts(rows)
    in_hand = [f for f in fields if (f.get("participants") or {}).get(HERO) in IN_HAND
               or (f.get("hero_controls") or {}).get("visible")]
    cards = Counter(" ".join(f["hero"]) for f in in_hand
                    if f.get("hero") and all(f["hero"]))
    history = hand_from(rows)
    replay = check_hand(rows) if facts["complete"] else None
    boards = [[] for _ in range(5)]
    for f in fields:
        for slot, card in enumerate((f.get("board") or [])[:5]):
            if card:
                boards[slot].append(card)
    return {
        "hand_id": facts["hand_id"], "start_pts": round(rows[0]["pts_seconds"], 1),
        "video_seconds": rows[0].get("video_seconds"),
        "end_pts": round(rows[-1]["pts_seconds"], 1), "players": len(facts["seats"]),
        "complete": facts["complete"], "dealer_read": facts["dealer"] is not None,
        "you_in": len(in_hand) >= 5, "your_cards": cards.most_common(1)[0][0]
        if cards else None,
        "your_cards_read_share": round(sum(cards.values()) / len(in_hand), 2)
        if in_hand else None,
        # Two readings of your cards, each in at least MISREAD frames: one
        # of them is wrong.
        "your_cards_readings": sum(n >= MISREAD for n in cards.values()),
        "board_slots_with_two_readings": sum(map(flickers, boards)),
        "decisions": decisions(rows, advice),
        "skipped_seats": len(skipped_seats(history)),
        "unexplained_pot_rises": len(unexplained_rises(history)),
        "unrecorded_folds": len(unrecorded_folds(history)),
        "replay": None if replay is None else (
            "ok" if replay["status"] == "ok" else replay["reason"]),
        "bomb_pot": None if replay is None else replay.get("bomb_pot"),
        "stalls": [gap for gap in gaps
                   if rows[0]["pts_seconds"] <= gap["pts"] <= rows[-1]["pts_seconds"]]}


def flickers(readings):
    """Whether one board card was read another way for at least MISREAD
    frames in the middle of its usual reading. (The last hand's board still
    showing as a new hand starts comes before it, and does not count.)"""
    counts = Counter(readings)
    if len(counts) < 2:
        return False
    usual = counts.most_common(1)[0][0]
    first = readings.index(usual)
    last = len(readings) - 1 - readings[::-1].index(usual)
    inside = Counter(card for card in readings[first:last] if card != usual)
    return any(n >= MISREAD for n in inside.values())


def hand_from(rows):
    """The hand in the form ``check_aa_action_history`` checks."""
    history = rows[-1]["fields"]["actions_v1"]
    keys = ("frame", "street", "slot", "kind", "amount", "source")
    return {"rows": rows, "complete": history["complete"],
            "actions": [dict(zip(keys, item)) for item in history["actions"]]}


def session_report(logs, *, replay_advice=False):
    hands = []
    for name, rows in logs:
        rows = [row for row in rows if row.get("fields")]
        if replay_advice:
            advice = replayed_advice(rows)
        else:
            advice = [row["fields"].get("solver_advice")
                      or row["fields"].get("solver_advice_v1") or {} for row in rows]
        gaps, grouped = stalls(rows), {}
        for row, report in zip(rows, advice):
            history = row["fields"].get("actions_v1")
            if history and row["fields"].get("scene_supported"):
                grouped.setdefault(history["hand_id"], []).append((row, report))
        for pairs in grouped.values():
            hand = hand_report([p[0] for p in pairs], [p[1] for p in pairs], gaps)
            hands.append({"log": name, **hand})
    return {"summary": summarize(hands), "hands": hands}


def summarize(hands):
    real = [h for h in hands if h["complete"] or h["you_in"]]
    turns = [t for h in real for t in h["decisions"]]
    advised = [t for t in turns if t["first_ready"] is not None]
    yours = [h for h in real if h["you_in"]]
    causes = Counter(t["cause"] for t in turns if t.get("cause"))
    problems = Counter()
    for hand in real:
        unread = sum(not turn["cards_read"] for turn in hand["decisions"])
        if unread:
            problems["decisions_with_your_cards_unread"] += unread
        if hand["your_cards_readings"] > 1:
            problems["your_cards_read_two_ways"] += 1
        if hand["board_slots_with_two_readings"]:
            problems["board_card_read_two_ways"] += 1
        if hand["complete"] and not hand["dealer_read"]:
            problems["dealer_unread"] += 1
        if hand["replay"] not in (None, "ok"):
            problems["replay_stops:" + hand["replay"]] += 1
        for key in ("skipped_seats", "unexplained_pot_rises", "unrecorded_folds"):
            if hand[key]:
                problems["hands_with_" + key] += 1
        if any(stall["seconds"] > STALE for stall in hand["stalls"]):
            problems["hands_with_stall_over_2s"] += 1
    return {"hands": len(real), "players": dict(sorted(Counter(
                h["players"] for h in real).items())),
            "your_hands": len(yours), "your_decisions": len(turns),
            "advised": len(advised),
            "advised_by_street": dict(Counter(t["street"] for t in advised)),
            "decisions_by_street": dict(Counter(t["street"] for t in turns)),
            "seconds_to_advice_median": sorted(t["first_ready"] for t in advised)[
                len(advised) // 2] if advised else None,
            "no_advice_causes": dict(causes.most_common()),
            "hand_problems": dict(problems.most_common()),
            "stalls_over_2s": sum(1 for h in real for s in h["stalls"]
                                  if s["seconds"] > STALE)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", required=True)
    parser.add_argument("--replay-advice", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    logs = [(str(path.parent.name), load(path)) for path in args.frames]
    report = session_report(logs, replay_advice=args.replay_advice)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
