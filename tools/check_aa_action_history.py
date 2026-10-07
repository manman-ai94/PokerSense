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
FIELDS_V1 = ("frame", "street", "slot", "kind", "amount", "source")


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


def hands_v1(rows):
    """Each hand's last rebuilt history (``actions_v1``) with the frames it covered."""
    result = {}
    for row in rows:
        history = (row.get("fields") or {}).get("actions_v1")
        if not history:
            continue
        hand = result.setdefault(history["hand_id"], {"rows": []})
        hand.update(complete=history["complete"], start=history["start"],
                    dealer=history["dealer"],
                    actions=[dict(zip(FIELDS_V1, item)) for item in history["actions"]])
        hand["rows"].append(row)
    return result


def _between(first, second):
    """Seats strictly between two seats, going round the table (8 seats)."""
    seats, seat = [], (first + 1) % 8
    while seat != second:
        seats.append(seat)
        seat = (seat + 1) % 8
    return seats


def skipped_seats(hand):
    """Seats still in the hand that should have acted between two actions of
    one street but have no action there: likely missed actions."""
    by_frame = {row["processed"]: row for row in hand["rows"]}
    folded, flags = set(), []
    actions = sorted(hand["actions"], key=lambda a: a["frame"])
    for first, second in zip(actions, actions[1:]):
        if first["kind"] == "fold":
            folded.add(first["slot"])
        if (first["street"] != second["street"]
                or None in (first["slot"], second["slot"])):
            continue
        row = by_frame.get(second["frame"]) or {}
        states = (row.get("fields") or {}).get("participants") or {}
        for seat in _between(first["slot"], second["slot"]):
            if seat not in folded and states.get(str(seat)) == "active":
                flags.append({"street": second["street"], "seat": seat,
                              "between": [first["slot"], second["slot"]],
                              "frame": second["frame"]})
    return flags


def street_balance(hand):
    """Per street: chips of its actions against the rise of the steady pot."""
    pots = [(row["processed"], (row.get("fields") or {}).get("pot"))
            for row in hand["rows"]]
    pots = [(frame, Decimal(pot)) for frame, pot in pots if pot not in (None, "")]
    result = []
    for street in STREETS:
        acts = [a for a in hand["actions"] if a["street"] == street]
        if not acts or any(a["kind"] in PRICED and a["amount"] in (None, "")
                           for a in acts if a["kind"] in PRICED):
            continue
        start, end = acts[0]["frame"], acts[-1]["frame"]
        before = [pot for frame, pot in pots if frame < start - 10]
        after = [pot for frame, pot in pots if end + 15 < frame]
        if not before or not after:
            continue
        chips = sum(Decimal(a["amount"]) for a in acts if a["kind"] in PRICED)
        result.append({"street": street, "chips": str(chips),
                       "pot_rise": str(after[0] - before[-1]),
                       "balanced": chips == after[0] - before[-1]})
    return result


def unexplained_rises(hand):
    """Steady pot rises in a hand that no call or raise accounts for.

    A rise spans from the last reading of the old pot to the first of the new
    one (the pot is sometimes unreadable for seconds). Each call or raise
    accounts for the rise nearest to it, within 15 frames of the span. The
    rise from an empty pot is the blinds and antes.
    """
    by_frame = {row["processed"]: row for row in hand["rows"]}
    if not by_frame:
        return []
    runs = pot_runs(by_frame, min(by_frame), max(by_frame))
    rises = [(before, after) for before, after in zip(runs, runs[1:])
             if after[0] > before[0] and before[0] != 0]
    explained = set()
    for action in hand["actions"]:
        if action["kind"] not in PRICED:
            continue
        frame = action["frame"]
        gaps = [(max(before[2] - frame, frame - after[1], 0), after[1])
                for before, after in rises]
        near = [gap for gap in gaps if gap[0] <= 15]
        if near:
            explained.add(min(near)[1])
    return [{"frame": after[1], "chips": str(after[0] - before[0])}
            for before, after in rises if after[1] not in explained]


def unrecorded_folds(hand):
    """Seats the seat states show folding during the hand with no fold action."""
    folds = {a["slot"] for a in hand["actions"] if a["kind"] == "fold"}
    seen_active, result = set(), set()
    for row in hand["rows"]:
        states = (row.get("fields") or {}).get("participants") or {}
        for seat, state in states.items():
            if state == "active":
                seen_active.add(int(seat))
            elif (state == "folded" and int(seat) in seen_active
                    and int(seat) not in folds):
                result.add(int(seat))
    return sorted(result)


def summarize_v1(rows):
    hands_ = hands_v1(rows)
    actions = [a for hand in hands_.values() for a in hand["actions"]]
    priced = [a for a in actions if a["kind"] in PRICED]
    flags = [flag for hand in hands_.values() for flag in skipped_seats(hand)]
    balances = [item for hand in hands_.values() if hand["complete"]
                for item in street_balance(hand)]
    return {"hands": len(hands_),
            "complete_hands": sum(hand["complete"] for hand in hands_.values()),
            "starts": dict(Counter(hand["start"] for hand in hands_.values())),
            "actions": len(actions), "priced_actions": len(priced),
            "priced_with_amount": sum(a["amount"] not in (None, "") for a in priced),
            "amount_sources": dict(Counter(a["source"] for a in priced)),
            "skipped_seat_flags": len(flags),
            "unexplained_pot_rises": sum(len(unexplained_rises(hand))
                                         for hand in hands_.values()),
            "unrecorded_folds": sum(len(unrecorded_folds(hand))
                                    for hand in hands_.values()),
            "streets_checked": len(balances),
            "streets_balanced": sum(item["balanced"] for item in balances)}


def compare_hands(rows, labelled):
    """Rebuilt hands against labelled hands of one recording.

    ``labelled`` is a list of {"from", "to", "actions": [[street, seat, kind,
    chips], ...]} with recording seconds; each is matched to the rebuilt hand
    with the most actions in that span, then compared action by action.
    """
    pts = {row["processed"]: row.get("pts_seconds") for row in rows}
    rebuilt_hands = hands_v1(rows)
    totals = Counter()
    details = []
    for label in labelled:
        def inside(action):
            seconds = pts.get(action["frame"])
            return seconds is not None and label["from"] <= seconds <= label["to"]
        best = max(rebuilt_hands.values(), default=None,
                   key=lambda hand: sum(map(inside, hand["actions"])))
        got = [] if best is None else [a for a in best["actions"] if inside(a)]
        want = [tuple(item[:3]) for item in label["actions"]]
        seen = [(a["street"], a["slot"], a["kind"]) for a in got]
        matcher = SequenceMatcher(a=want, b=seen, autojunk=False)
        matched = missing = extra = 0
        amounts = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                matched += i2 - i1
                for offset in range(i2 - i1):
                    chips = label["actions"][i1 + offset][3]
                    amount = got[j1 + offset]["amount"]
                    if want[i1 + offset][2] in PRICED:
                        result = ("missing" if amount in (None, "") else
                                  "correct" if str(amount) == str(chips) else "wrong")
                        totals["amount_" + result] += 1
                        if result != "correct":
                            amounts.append({"action": want[i1 + offset],
                                            "labelled": chips, "rebuilt": amount})
            else:
                missing += i2 - i1
                extra += j2 - j1
        totals.update(labelled_actions=len(want), matched=matched, missing=missing,
                      extra=extra)
        details.append({"from": label["from"], "matched": matched, "missing": missing,
                        "extra": extra, "differences": [
                            {"labelled": want[i1:i2], "rebuilt": seen[j1:j2]}
                            for tag, i1, i2, j1, j2 in matcher.get_opcodes()
                            if tag != "equal"],
                        "amount_differences": amounts})
    return {"totals": dict(totals), "hands": details}


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
    parser.add_argument("--hand-labels", type=Path,
                        help="labelled hands of several recordings (see compare_hands)")
    parser.add_argument("--recording", help="recording name inside --hand-labels")
    args = parser.parse_args(argv)
    rows = load(args.frames)
    report = {"summary": summarize(rows), "rebuilt": rebuilt(rows)}
    if any((row.get("fields") or {}).get("actions_v1") for row in rows):
        report["v1"] = summarize_v1(rows)
    if args.labels:
        report["labelled_hand"] = compare(
            rows, json.loads(args.labels.read_text(encoding="utf-8")))
    if args.hand_labels:
        labels = json.loads(args.hand_labels.read_text(encoding="utf-8"))
        report["labelled_hands"] = compare_hands(
            rows, labels["recordings"][args.recording])
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
