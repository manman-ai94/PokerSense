"""How much of a log's missed actions and rough advice comes from its frame rate.

A slow computer reads fewer frames a second (10/15: 杜's 2.5 against the
Mac's 7.8), and the same code then misses more of the table: replayed on the
same code, 38% of 杜's hands did not replay against 18% of the Mac's, 44% of
his decisions after the flop got only rough or no advice against 13%, and 19%
of his hands had a pot rise nobody's bet explained against 4%. His screen (a
Huawei P30, not the Samsung) and its unread check badges differ too. This
tool separates the two, on the logs the window writes (``frames.jsonl``):

- **as recorded**: frames per second of play and the gaps between frames;
  every complete hand replayed on the AA table, and for each pair of
  actions one after the other the longest gap between two frames in the
  stretch from the first to the second (``pairs_by_gap``: pairs, and pairs
  where the replay stopped at the second action); likewise every steady pot
  rise and the longest gap between the old pot's last reading and the new
  one's first (``rises_by_gap``: rises, and rises no call or raise
  explains). If the stops and the unexplained rises gather at the long
  gaps, frame rate is the cause; if their rate is flat, it is not;
- **slowed down** (``--slow 2.5,4.5``): a fast log thinned to that many frames
  per second of play, numbered as a slow reader numbers its own frames, then
  its betting history, street and advice worked out again with the current
  code. Variants take away one more difference at a time: ``no_checks``
  drops the reader's check badges (杜's window reads none), ``du_like`` also
  drops the bets in front of the ``--blind-wagers`` seats (unread on his
  screen). With ``--full-variants`` the variants run at the log's own rate
  too, which leaves out the frame rate.

Every configuration reports what the loss audit counted (hands that do not
replay and why, decisions after the flop with only rough or no advice, hands
with an unexplained pot rise, decisions with your cards unread) and how long
your cards took to read after your buttons came up before the flop.

What thinning cannot copy: the fast reader's own frame-to-frame checks
(cards, badges, amounts) are already in each logged frame. A slow reader
would need more time for each, so the slowed-down numbers lean optimistic.
Your cards are the exception: a slow reader reads them ``HERO_WAIT`` of its
own frames after a fast one first had them, and that is applied. Badges
are kept from the first kept frame at or after the fast reader confirmed
them; how long a badge stays up is not in the log.

    PYTHONPATH=src:. .venv/bin/python tools/frame_rate_audit.py \\
        --frames <recording>/frames.jsonl [--frames ...] \\
        [--slow 2.5,4.5] [--blind-wagers 1,7] [--full-variants] \\
        [--variants plain,no_checks,du_like] [--no-advice] [--out audit.json]

Working the advice out again takes most of the time (each configuration
replays the whole log); ``--no-advice`` leaves out the rough-advice count.

Only counts and rates are written (split by seat position at most); no hand or
card of a real game.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_solver_input import hand_facts, replay_hand  # noqa: E402
from tools.aa_session_report import session_report  # noqa: E402
from tools.check_aa_action_history import PRICED, pot_runs  # noqa: E402
from tools.replay_aa_action_history import replay  # noqa: E402

HERO = "4"
POSTFLOP = ("flop", "turn", "river")
HERO_WAIT = 3           # frames a slow reader needs once a fast one read your cards
GAPS = (0.25, 0.5, 1.0)     # seconds: the edges of the gap buckets
VARIANTS = ("plain", "no_checks", "du_like")


def load(path):
    with Path(path).open(encoding="utf-8") as handle:
        rows = map(json.loads, filter(str.strip, handle))
        return [row for row in rows if row.get("fields")
                and isinstance(row.get("pts_seconds"), (int, float))]


# -- thinning a fast log ---------------------------------------------------------

def thin(rows, fps=None, *, checks=True, blind_wagers=(), hero_wait=HERO_WAIT):
    """The log as a reader reading at most ``fps`` frames a second would
    have written it (``fps`` None keeps every frame): frames numbered on, a
    break in the original numbering kept as a break, badges placed at the
    first kept frame at or after the fast reader confirmed them, your cards
    held back ``hero_wait`` kept frames (all only when thinning). ``checks``
    False drops check badges; ``blind_wagers`` seats lose their bets on the
    table."""
    step = 1.0 / fps if fps else 0.0
    blind = {str(seat) for seat in blind_wagers}
    out, placed = [], {}
    number, last_pts, last_processed, broken = -1, None, None, False
    held, holding = 0, None
    for row in rows:
        processed, pts = row["processed"], row["pts_seconds"]
        if last_processed is not None and processed != last_processed + 1:
            broken = True
        last_processed = processed
        if (fps and last_pts is not None and not broken
                and pts - last_pts < step * 0.95):
            placed.setdefault(processed, number + 1)
            continue
        number = (processed if not fps else
                  number + (2 if broken and out else 1))
        broken, last_pts = False, pts
        placed[processed] = number
        fields = deepcopy(row["fields"])
        tail = []
        for action in fields.get("actions_tail") or ():
            if not checks and action.get("kind") == "check":
                continue
            if not fps:
                tail.append(action)
                continue
            at = action.get("confirmed_at", action.get("frame"))
            new = placed.get(at, number) if isinstance(at, int) else number
            tail.append({**action, "frame": new, "confirmed_at": new})
        fields["actions_tail"] = tail
        for key in ("street_wagers", "causal_wagers"):
            if isinstance(fields.get(key), dict) and blind:
                fields[key] = {seat: value for seat, value in fields[key].items()
                               if str(seat) not in blind}
        cards = tuple(fields.get("hero") or ())
        if fps and len([card for card in cards if card]) == 2:
            held = held + 1 if cards == holding else 1
            holding = cards
            if held <= hero_wait:
                fields["hero"] = None
        else:
            held, holding = 0, None
        out.append({**row, "processed": number, "fields": fields})
    return out


# -- what the loss audit counts ------------------------------------------------

def frame_rate(rows):
    pts = [row["pts_seconds"] for row in rows]
    span = pts[-1] - pts[0] if len(pts) > 1 else 0
    gaps = sorted(b - a for a, b in zip(pts, pts[1:]) if b > a)
    return {"frames": len(rows),
            "frames_per_second": round((len(pts) - 1) / span, 2) if span > 0 else None,
            "gap_p50": round(gaps[len(gaps) // 2], 3) if gaps else None,
            "gap_p90": round(gaps[int(0.9 * (len(gaps) - 1))], 3) if gaps else None,
            "gaps_over_0.5s": sum(gap > 0.5 for gap in gaps),
            "gaps_over_1s": sum(gap > 1.0 for gap in gaps)}


def counts(rows, name="log", *, advice=True):
    """The loss audit's numbers for a log, with the betting history and the
    street rebuilt by the current code (and the advice too, with ``advice``)."""
    rows = replay(rows, streets=True)
    report = session_report([(name, rows)], replay_advice=advice)
    hands = report["hands"]
    complete = [hand for hand in hands
                if hand["complete"] and hand["replay"] is not None]
    stops = Counter(hand["replay"] for hand in complete if hand["replay"] != "ok")
    turns = [turn for hand in hands if hand["complete"] or hand["you_in"]
             for turn in hand["decisions"]]
    late = [turn for turn in turns if turn["street"] in POSTFLOP]
    rough = [turn for turn in late
             if turn["first_ready"] is None or turn.get("kind") == "rough"]
    real = [hand for hand in hands if hand["complete"] or hand["you_in"]]
    rising = sum(bool(hand["unexplained_pot_rises"]) for hand in real)
    result = {
        "hands": len(real), "complete_hands": len(complete),
        "not_replayed": sum(stops.values()),
        "not_replayed_share": share(sum(stops.values()), len(complete)),
        "stops": dict(stops.most_common()),
        "hands_with_unexplained_rises": rising,
        "hands_with_unexplained_rises_share": share(rising, len(real)),
        "decisions": len(turns),
        "decisions_with_your_cards_unread": sum(not t["cards_read"] for t in turns),
        "your_cards_wait": cards_wait(rows)}
    if advice:
        advised = Counter(turn.get("kind") for turn in turns
                          if turn["first_ready"] is not None)
        result.update({"postflop_decisions": len(late),
                       "postflop_rough_or_none": len(rough),
                       "postflop_rough_or_none_share": share(len(rough), len(late)),
                       "advised_by_kind": dict(advised)})
    return result


def share(part, whole):
    return round(part / whole, 3) if whole else None


def cards_wait(rows):
    """Seconds from your buttons coming up before the flop until both your
    cards were read (0 when they already were), per decision."""
    waits, start = [], None
    for row in rows:
        fields = row["fields"]
        shown = bool((fields.get("hero_controls") or {}).get("visible"))
        if not shown or fields.get("street") != "preflop":
            start = None
            continue
        if start is None:
            start = [row["pts_seconds"], False]
        if not start[1] and len([c for c in fields.get("hero") or () if c]) == 2:
            waits.append(row["pts_seconds"] - start[0])
            start[1] = True
    waits.sort()
    return {"decisions": len(waits),
            "median": round(statistics.median(waits), 2) if waits else None,
            "p90": round(waits[int(0.9 * (len(waits) - 1))], 2) if waits else None}


# -- where the misses happen, as recorded -----------------------------------------

def bucket(gap):
    for edge in GAPS:
        if gap <= edge:
            return f"<={edge}s"
    return f">{GAPS[-1]}s"


def longest_gap(pts, first, last):
    """The longest gap between two frames one after the other from frame
    ``first`` to frame ``last`` (by the log's numbering)."""
    frames = [frame for frame in sorted(pts) if first <= frame <= last]
    return max((pts[b] - pts[a] for a, b in zip(frames, frames[1:])), default=0.0)


def by_hand(rows):
    grouped = {}
    for row in rows:
        history = row["fields"].get("actions_v1")
        if history and row["fields"].get("scene_supported"):
            grouped.setdefault(history["hand_id"], []).append(row)
    return list(grouped.values())


def where(rows, *, rebuild=True):
    """Stops and unexplained rises by the longest frame gap near them (on
    the betting history the current code rebuilds, unless ``rebuild`` is
    False)."""
    if rebuild:
        rows = replay(rows, streets=True)
    pairs, rises = Counter(), Counter()
    stopped, unexplained = Counter(), Counter()
    stopped_seats, wagers = Counter(), {}
    for hand in by_hand(rows):
        pts = {row["processed"]: row["pts_seconds"] for row in hand}
        facts = hand_facts(hand)
        actions = facts["actions"]
        if facts["complete"] and actions:
            result = replay_hand(facts)
            failed = None
            if result["status"] != "ok":
                failed = result["replayed"] - len(result["inferred"])
                if 1 <= failed < len(actions):
                    stopped_seats[str(actions[failed]["slot"])] += 1
            last = len(actions) - 1 if failed is None else min(failed, len(actions) - 1)
            for at in range(1, last + 1):
                gap = bucket(longest_gap(pts, actions[at - 1]["frame"],
                                         actions[at]["frame"]))
                pairs[gap] += 1
                if at == failed:
                    stopped[gap] += 1
        priced = [a["frame"] for a in actions if a["kind"] in PRICED]
        runs = pot_runs({row["processed"]: row for row in hand}, min(pts), max(pts))
        for before, after in zip(runs, runs[1:]):
            if not (after[0] > before[0] and before[0] != 0):
                continue
            gap = bucket(longest_gap(pts, before[2], after[1]))
            rises[gap] += 1
            if not any(max(before[2] - f, f - after[1], 0) <= 15 for f in priced):
                unexplained[gap] += 1
        for action in actions:
            if action["kind"] in PRICED:
                seat = str(action["slot"])
                seen = any((row["fields"].get("street_wagers") or {}).get(seat)
                           not in (None, "", "0") for row in hand)
                read = wagers.setdefault(seat, [0, 0])
                read[0] += seen
                read[1] += 1
    order = [bucket(edge) for edge in GAPS] + [bucket(GAPS[-1] + 1)]
    return {"pairs_by_gap": {key: [pairs[key], stopped[key]] for key in order},
            "rises_by_gap": {key: [rises[key], unexplained[key]] for key in order},
            "stopped_at_seat": dict(sorted(stopped_seats.items())),
            "bets_with_a_wager_read_by_seat": {
                seat: value for seat, value in sorted(wagers.items())},
            "badges_read": dict(Counter(
                action.get("kind") for action in unique_badges(rows)))}


def unique_badges(rows):
    seen = {}
    for row in rows:
        for action in row["fields"].get("actions_tail") or ():
            key = (action.get("frame"), action.get("slot"), action.get("kind"),
                   action.get("confirmed_at"))
            seen.setdefault(key, action)
    return list(seen.values())


# -- the whole audit ----------------------------------------------------------------

def audit(rows, name, *, slow=(), blind_wagers=(), full_variants=False, advice=True,
          variants=VARIANTS):
    own = frame_rate(rows)
    result = {"as_recorded": {**own, **counts(rows, name, advice=advice)},
              "where": where(rows), "configurations": {}}
    options = {"plain": {}, "no_checks": {"checks": False},
               "du_like": {"checks": False, "blind_wagers": blind_wagers}}
    targets = ([None] if full_variants else []) + [
        fps for fps in slow
        if own["frames_per_second"] and fps < own["frames_per_second"]]
    for fps in targets:
        for variant in variants:
            if fps is None and variant == "plain":
                continue
            if variant == "du_like" and not blind_wagers:
                continue
            thinned = thin(rows, fps, **options[variant])
            label = f"{'full' if fps is None else fps}/{variant}"
            result["configurations"][label] = {
                **frame_rate(thinned), **counts(thinned, name, advice=advice)}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", required=True)
    parser.add_argument("--slow", default="",
                        help="frames per second to thin fast logs to, e.g. 2.5,4.5")
    parser.add_argument("--blind-wagers", default="",
                        help="seats whose bets on the table go unread in du_like")
    parser.add_argument("--full-variants", action="store_true",
                        help="the variants at each log's own frame rate too")
    parser.add_argument("--variants", default=",".join(VARIANTS),
                        help="which of plain, no_checks, du_like to run")
    parser.add_argument("--no-advice", action="store_true",
                        help="skip working the advice out again (much faster)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    slow = [float(value) for value in args.slow.split(",") if value.strip()]
    blind = [int(value) for value in args.blind_wagers.split(",") if value.strip()]
    variants = [value.strip() for value in args.variants.split(",") if value.strip()]
    unknown = set(variants) - set(VARIANTS)
    if unknown:
        parser.error(f"unknown variants: {', '.join(sorted(unknown))}")
    report = {}
    for path in args.frames:
        name = path.parent.name or path.stem
        report[name] = audit(load(path), name, slow=slow, blind_wagers=blind,
                             full_variants=args.full_variants,
                             advice=not args.no_advice, variants=variants)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
