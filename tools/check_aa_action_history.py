"""How complete and consistent the live betting history is, from a measurement log.

Reads the ``frames.jsonl`` that ``tools/measure_aa_realtime.py`` writes and
rebuilds the betting history the observer page had (the reader's
``action_history_candidate``), hand by hand. Without labels it reports how
much of it a solver could use: actions with an amount, streets that agree
with the board-card street, hands whose streets run in order. With a
labelled hand (the format of
``tests/fixtures/aa_reference_hands/eight_session_56dd_actions_v1.json``) it
also compares the sequence action by action.

    PYTHONPATH=src:. .venv/bin/python tools/check_aa_action_history.py \\
        --frames <measurement dir>/frames.jsonl [--labels <labelled hand json>]
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from decimal import Decimal
from difflib import SequenceMatcher
import json
from pathlib import Path

STREETS = ("preflop", "flop", "turn", "river")
# The reader's glyph kinds against the labels' canonical kinds.
KIND = {"aggressive": "raise", "raise": "raise", "bet": "raise", "call": "call",
        "check": "check", "fold": "fold", "all_in": "all_in"}
PRICED = ("call", "raise", "all_in")


def load(path):
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def rebuild(rows):
    """Every distinct action the log saw, in the order it first appeared."""
    seen, actions = set(), []
    for row in rows:
        for action in (row.get("fields") or {}).get("actions_tail") or []:
            key = (action.get("epoch"), action.get("frame"), action.get("slot"),
                   action.get("kind"))
            if key in seen:
                continue
            seen.add(key)
            actions.append({**action, "seen_pts": row.get("pts_seconds"),
                            "seen_frame": row.get("source_frame")})
    return actions


def street_lookup(rows):
    """Board-card street (street_v1) at a reader frame number.

    The reader numbers the frames it processes (the log's ``processed``), which
    is what an action's ``frame`` refers to, not the recording's frame.
    """
    points = sorted((row["processed"], (row.get("fields") or {}).get("street"))
                    for row in rows if row.get("processed") is not None)
    frames = [frame for frame, _ in points]

    def street_at(frame):
        index = bisect_right(frames, frame) - 1
        return points[index][1] if index >= 0 else None
    return street_at


def source_frames(rows):
    """Recording frame number of each reader frame number."""
    return {row["processed"]: row["source_frame"] for row in rows
            if row.get("processed") is not None and row.get("source_frame") is not None}


def hands(actions):
    grouped = {}
    for action in actions:
        grouped.setdefault(action.get("epoch"), []).append(action)
    return grouped


def summarize(rows):
    actions = rebuild(rows)
    street_at = street_lookup(rows)
    priced = [a for a in actions if KIND.get(a.get("kind")) in PRICED]
    with_amount = [a for a in priced if a.get("amount") not in (None, "")]
    compared = [(a.get("street"), street_at(a["frame"])) for a in actions
                if a.get("frame") is not None and street_at(a["frame"]) in STREETS]
    disagree = [pair for pair in compared if pair[0] != pair[1]]
    grouped = hands(actions)
    regressions = 0
    for items in grouped.values():
        order = [STREETS.index(a["street"]) for a in items
                 if a.get("street") in STREETS]
        regressions += sum(1 for a, b in zip(order, order[1:]) if b < a)
    return {
        "frames": len(rows),
        "actions": len(actions),
        "hands": len([epoch for epoch in grouped if epoch is not None]),
        "kinds": dict(Counter(KIND.get(a.get("kind"), a.get("kind"))
                              for a in actions)),
        "priced_actions": len(priced),
        "priced_with_amount": len(with_amount),
        "street_checked": len(compared),
        "street_disagrees": len(disagree),
        "street_disagreement_pairs": dict(Counter(f"{a}->{b}" for a, b in disagree)),
        "street_regressions": regressions,
    }


def pot_runs(rows_by_frame, first, last):
    """Pot values held for at least two reader frames, as (value, start, end)."""
    runs, value, start, end, count = [], None, None, None, 0
    for frame in range(first, last + 1):
        row = rows_by_frame.get(frame)
        pot = None if row is None else (row.get("fields") or {}).get("pot")
        if pot in (None, ""):
            continue
        pot = Decimal(pot)
        if pot == value:
            end, count = frame, count + 1
            continue
        if value is not None and count >= 2:
            runs.append((value, start, end))
        value, start, end, count = pot, frame, frame, 1
    if value is not None and count >= 2:
        runs.append((value, start, end))
    return runs


def pot_step(rows_by_frame, frame, before=10, after=15):
    """Chips added at an action: the pot rise nearest to the action's frame.

    The displayed pot includes this street's bets, so a call or a raise shows
    up as a rise from one steady value to the next, often a little before
    the action badge is read.
    """
    runs = pot_runs(rows_by_frame, frame - before, frame + after)
    steps = [(abs(b[1] - frame), b[0] - a[0]) for a, b in zip(runs, runs[1:])
             if b[0] > a[0]]
    return min(steps)[1] if steps else None


def rebuilt(rows):
    """The history again, with amounts from pot rises, streets from the board
    cards, and a new hand whenever the board-card street goes back."""
    by_frame = {row["processed"]: row for row in rows
                if row.get("processed") is not None}
    street_at = street_lookup(rows)
    hands_, current, last = [], [], None
    for action in rebuild(rows):
        street = street_at(action["frame"]) if action.get("frame") is not None else None
        if street not in STREETS:
            continue
        if last is not None and STREETS.index(street) < STREETS.index(last):
            hands_.append(current)
            current = []
        last = street
        amount = action.get("amount")
        if KIND.get(action.get("kind")) in PRICED:
            step = pot_step(by_frame, action["frame"])
            amount = str(step) if step is not None else amount
        current.append({**action, "street": street, "amount": amount})
    if current:
        hands_.append(current)
    priced = [a for hand in hands_ for a in hand if KIND.get(a.get("kind")) in PRICED]
    return {"hands": len(hands_), "actions": sum(len(hand) for hand in hands_),
            "priced_actions": len(priced),
            "priced_with_amount": sum(1 for a in priced
                                      if a.get("amount") not in (None, ""))}


def label_sequence(label):
    """(street, seat, kind, chips, recording-frame window) per labelled action."""
    result = []
    for street in label["streets"]:
        for action in street["actions"]:
            kind = "all_in" if action.get("all_in") else KIND[action["kind"]]
            result.append((street["street"], action["slot"], kind,
                           action.get("debit"), action["window"]))
    return result


def compare(rows, label):
    """Detected actions inside the labelled hand's frames, matched in order."""
    expected = label_sequence(label)
    first, last = expected[0][4][0], expected[-1][4][1]
    source = source_frames(rows)
    actions = [a for a in rebuild(rows)
               if first <= source.get(a.get("frame"), -1) <= last + 30]
    got = [(a.get("street"), a.get("slot"), KIND.get(a.get("kind"), a.get("kind")))
           for a in actions]
    want = [(street, slot, kind) for street, slot, kind, _, _ in expected]
    matcher = SequenceMatcher(a=want, b=got, autojunk=False)
    matched, amounts = 0, Counter()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(i2 - i1):
            matched += 1
            debit = expected[i1 + offset][3]
            amount = actions[j1 + offset].get("amount")
            if expected[i1 + offset][2] in PRICED:
                if amount in (None, ""):
                    amounts["missing"] += 1
                else:
                    amounts["correct" if str(amount) == str(debit) else "wrong"] += 1
    return {"labelled": len(want), "detected": len(got), "matched_in_order": matched,
            "amounts": dict(amounts),
            "differences": [
                {"op": tag, "labelled": want[i1:i2], "detected": got[j1:j2]}
                for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args(argv)
    rows = load(args.frames)
    report = {"summary": summarize(rows), "rebuilt": rebuilt(rows)}
    if args.labels:
        report["labelled_hand"] = compare(
            rows, json.loads(args.labels.read_text(encoding="utf-8")))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
