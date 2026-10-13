"""How often the range the AI read for an opponent had thrown out the hand
he then showed, from the window's frame logs of a session.

For every hand in which an opponent still in at the end turned his cards
face up (``fields["shown_cards"]``), the hand is replayed on the AA table
from the log (``aa_solver_input``), as far as it goes, and the opponent's
range is read action by action with the code the advice uses
(``ranges.opponent_ranges`` with the window's model, and the reads on each
seat from the hands of the log before this one, as ``aa_reads`` counts them
during play). ``scoreboard.exclusion`` then says whether the real hand was
still in after each action and sums up:

* ``all``: every shown hand that replayed;
* ``narrowed``: those whose range the reading had cut at all;
* ``river``: those whose betting reached the river;
* ``you_in``: those in which you were still in at the end;
* ``by_street``: of the hands that reached a street, the share out by its
  end; ``first``: the street and action that first threw the hand out.

``whole_hand`` reads every action, the last call at the showdown too;
``before_end`` leaves out the action that ended the hand: the reading as it
stood when the window could last be asked for advice (the rates 59%, 69%
and 84% of 2026-10 were counted that way, without reads: ``--no-reads``).
Hands that do not replay, and seats that showed after folding, are counted
by reason in ``skipped``.

    PYTHONPATH=src:. .venv/bin/python tools/aa_range_exclusion.py \\
        --frames <recording>/frames.jsonl [--frames ...] [--no-reads] \\
        [--out exclusion.json]

``--compare before.json after.json`` puts two runs over the same logs side
by side (for example this tool on ``main`` and on a branch that changes the
reading): the rates of each, and the hands one kept that the other threw
out. ``tools/aa_session_report.py`` and ``tools/aa_strategy_review.py`` add
the same numbers to their reports.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_reads import AAReads  # noqa: E402
from poker_engine.desktop.aa_solver_input import (  # noqa: E402
    HERO, hand_facts, replay_hand, starting_stacks)
from poker_engine.scoreboard.exclusion import (  # noqa: E402
    brief, compare, exclusion_trace, summarize)
from poker_engine.scoreboard.preflop_policy import AAPreflopPolicy  # noqa: E402
from poker_engine.scoreboard.preflop_reading import (  # noqa: E402
    reading_model, reading_of)


def load(path):
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def window_model():
    """The model the window reads ranges with (``AASolverAdvice._range_model``)."""
    policy = AAPreflopPolicy()
    return reading_model(policy.adjusted, reading_of(policy))


def hands_in_order(rows):
    """[(hand id, rows)] as the window follows them: a new hand id starts a hand."""
    hands = []
    for row in rows:
        history = (row.get("fields") or {}).get("actions_v1")
        if not history:
            continue
        if not hands or hands[-1][0] != history["hand_id"]:
            hands.append((history["hand_id"], []))
        hands[-1][1].append(row)
    return hands


def replayed(facts):
    """The hand's table after every action read (finished or not), or None."""
    if facts.get("complete") is not True:
        return None
    first = replay_hand(facts)
    if first["status"] != "ok":
        return None
    stacks = starting_stacks(facts, first)
    again = replay_hand({**facts, "dealer": first["dealer"]}, stacks)
    if again["status"] != "ok":
        return None
    return again["arena"]


def hand_table(rows, stakes=None):
    """(arena, whole): the hand replayed with all its rows, else with the
    most of them that replay (cut where an action or a board card was read);
    ``whole`` says which. (None, False) when nothing replays."""
    cuts, seen = [], None
    for index, row in enumerate(rows):
        fields = row["fields"]
        mark = (len((fields.get("actions_v1") or {}).get("actions") or ()),
                sum(1 for card in fields.get("board") or () if card))
        if mark != seen:
            seen = mark
            cuts.append(index + 1)
    for end in [len(rows)] + list(reversed(cuts)):
        try:
            arena = replayed(hand_facts(rows[:end], stakes))
        except Exception:              # a log the replay cannot take: try less
            arena = None
        if arena is not None:
            return arena, end == len(rows)
    return None, False


def shown_seats(rows):
    """{seat: two cards} the hand's last reading of the cards shown."""
    shown = next((row["fields"]["shown_cards"] for row in reversed(rows)
                  if row["fields"].get("shown_cards")), None) or {}
    return {int(seat): value["cards"]
            for seat, value in (shown.get("seats") or {}).items()
            if len(value.get("cards") or ()) == 2 and all(value["cards"])}


def hand_traces(rows, model, reads=None, stakes=None):
    """[(seat, cards, trace or None, reason)] for the seats that showed."""
    shown = shown_seats(rows)
    if not shown:
        return []
    arena, whole = hand_table(rows, stakes)
    if arena is None:
        return [(seat, cards, None, "no_replay") for seat, cards in shown.items()]
    base = arena.observe(arena.occupied_seats[0])
    if reads:
        base["reads"] = reads
    result = []
    for seat, cards in sorted(shown.items()):
        if seat not in base["occupied_seats"]:
            result.append((seat, cards, None, "seat_not_dealt_in"))
            continue
        if seat in base["folded"]:
            result.append((seat, cards, None, "shown_after_folding"))
            continue
        others = [other for other in base["occupied_seats"] if other != seat]
        observer = HERO if HERO in others else others[0]
        try:
            trace = exclusion_trace({**base, "observing_seat": observer}, seat, cards,
                                    model)
        except ValueError:
            result.append((seat, cards, None, "cards_do_not_fit"))
            continue
        trace["you_in"] = observer == HERO and HERO not in base["folded"]
        trace["replayed"] = "whole" if whole else "part"
        result.append((seat, cards, trace, None))
    return result


def log_exclusion(name, rows, *, model=None, reads=True):
    """Every shown seat of one log: {"traces": [...], "skipped": [...]}.

    The reads on each seat are those of the hands before, counted the way
    the window counts them (``aa_reads``); ``reads=False`` reads without."""
    model = model or window_model()
    counted, stakes = AAReads(), None
    traces, skipped = [], []
    for hand_id, hand in hands_in_order([row for row in rows if row.get("fields")]):
        snapshot = counted.snapshot() if reads else None
        for seat, cards, trace, reason in hand_traces(hand, model, snapshot, stakes):
            where = {"log": name, "hand_id": hand_id,
                     "video_seconds": hand[0].get("video_seconds"), "seat": seat}
            if trace is None:
                skipped.append({**where, "cards": cards, "reason": reason})
            else:
                traces.append({**where, **trace})
        try:
            counted.add_hand(hand, stakes)
            found = hand_facts(hand, stakes)["stakes"]
        except Exception:                  # the window goes on without this hand
            continue
        if found.get("source") == "table":
            stakes = found
    return {"traces": traces, "skipped": skipped}


def session_exclusion(logs, *, reads=True):
    """The exclusion rates of every shown seat over ``logs`` ([(name, rows)])."""
    model = window_model()
    traces, skipped = [], []
    for name, rows in logs:
        found = log_exclusion(name, rows, model=model, reads=reads)
        traces += found["traces"]
        skipped += found["skipped"]
    return {"reads": reads,
            "whole_hand": summarize(traces),
            "before_end": summarize(traces, before_end=True),
            "skipped": dict(Counter(item["reason"] for item in skipped).most_common()),
            "hands": [brief(trace, log=trace["log"], hand_id=trace["hand_id"],
                            video_seconds=trace["video_seconds"])
                      for trace in traces],
            "traces": traces, "skipped_hands": skipped}


def compare_runs(before, after):
    """Two runs of this tool over the same logs, paired by log, hand and seat."""
    key = ("log", "hand_id", "seat")
    second = {tuple(trace[k] for k in key): trace for trace in after["traces"]}
    pairs = [(trace, second[tuple(trace[k] for k in key)]) for trace in before["traces"]
             if tuple(trace[k] for k in key) in second]
    result = {}
    for before_end in (False, True):
        found = compare([one for one, _ in pairs], [two for _, two in pairs],
                        before_end=before_end)
        result["before_end" if before_end else "whole_hand"] = found
    result["paired_hands"] = len(pairs)
    return result


def rate_line(part):
    if part["rate"] is None:
        return "-"
    low, high = part["ci95"]
    return (f"{part['excluded']}/{part['hands']} = {part['rate']:.0%} "
            f"[{low:.0%}, {high:.0%}]")


def lines(report):
    out = []
    for view in ("whole_hand", "before_end"):
        summary = report[view]
        out.append(f"{view}: all {rate_line(summary['all'])} | range cut "
                   f"{rate_line(summary['narrowed'])} | to the river "
                   f"{rate_line(summary['river'])} | you in "
                   f"{rate_line(summary['you_in'])}")
        out.append("  by street: " + " | ".join(
            f"{street} {rate_line(part)}"
            for street, part in summary["by_street"].items()))
        out.append("  first out at: " + ", ".join(
            f"{label} {count}" for label, count in summary["first"].items()))
    if report["skipped"]:
        out.append("skipped: " + ", ".join(
            f"{reason} {count}" for reason, count in report["skipped"].items()))
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append")
    parser.add_argument("--no-reads", action="store_true",
                        help="read every seat as the average AA player")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args(argv)
    if args.compare:
        before, after = (json.loads(path.read_text(encoding="utf-8"))
                         for path in args.compare)
        result = compare_runs(before, after)
        shown = {view: {key: result[view][key]
                        for key in ("change", "kept_now", "excluded_now")}
                 for view in ("whole_hand", "before_end")}
        print(json.dumps({**shown, "paired_hands": result["paired_hands"]}, indent=1))
        if args.out:
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        return
    if not args.frames:
        parser.error("--frames or --compare is needed")
    logs = [(str(path.parent.name), load(path)) for path in args.frames]
    report = session_exclusion(logs, reads=not args.no_reads)
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(lines(report))


if __name__ == "__main__":
    main()
