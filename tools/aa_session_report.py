"""A played session, hand by hand: your decisions, the advice, and what went wrong.

Reads the ``frames.jsonl`` logs that ``tools/measure_aa_realtime.py --advice``
writes for the recordings of one session and reports, for every hand: the
players, whether you were in it and your cards were read, each of your
decisions (your buttons on screen) with the advice it got or why none came,
what you then did and whether it was the advised action, the cards each
opponent showed with that seat's actions street by street, the betting-history
checks of ``tools/check_aa_action_history.py``, whether the hand replays on
the AA table (``aa_solver_input.check_hand``), the stalls (more than a second
between two shown frames) and your chips from this hand's start to the next
one's (with this hand's blinds, antes and mushroom post, not the next one's).
The summary leads with the hands in which every one of your decisions got
advice, from the first before the flop to the last (``fully_advised``;
also for the hands you played past the flop), then counts the decisions
advised, by kind of advice (``rough`` is the rough rule's), and the causes
over the session, most frequent first, splits hands and decisions by table
size and adds up your chips by whether you followed the advice.

    PYTHONPATH=src:. .venv/bin/python tools/aa_session_report.py \\
        --frames <measurement>/frames.jsonl [--frames ...] [--out report.json]

The window's own log of a recording (``frames.jsonl`` in the recording's
folder, what it read and advised during play) reads the same way; each hand
then says where it starts in the video (``video_seconds``).

A log measured without ``--advice`` has no solver advice for your heads-up
turn and river; ``--replay-advice`` then works the advice out again from the
log with the current code, taking any heads-up solve as done (no TexasSolver).

Every opponent who showed his cards while still in also gets the range the
advice read for him checked (``tools/aa_range_exclusion.py``): each entry
of a hand's ``shown_cards`` has ``range_read`` (the action that first threw
his real hand out of the range, or None), and the summary's
``range_exclusion`` has the rates (all shown hands, those whose range was
cut, those that reached the river, by street).
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

from poker_engine.desktop.aa_solver_input import (  # noqa: E402
    _rules, bomb_post, check_hand, hand_facts)
from poker_engine.strategy.aa_rules_v2 import build_forced_bet_plan  # noqa: E402
from tools.aa_range_exclusion import session_exclusion  # noqa: E402
from tools.check_aa_action_history import (  # noqa: E402
    skipped_seats, unexplained_rises, unrecorded_folds)

HERO = "4"
FLASH = 0.5             # seconds: your buttons this briefly while sitting out
IN_HAND = ("active", "all_in")
STALL = 1.0          # seconds between two shown frames that count as a stall
STALE = 2.0          # the live window clears the table after this long
LATE = 3.0           # advice later than this after your buttons showed
MUSHROOM_POST = 3    # big blinds the dealer puts in the mushroom pool (蘑菇:3BB)
MISREAD = 3          # frames a second reading of one card needs to count
FIRST = 5            # frames at a hand's start that read its stacks
AGGRESSIVE = {"bet": "raise", "raise": "raise", "all_in": "raise", "allin": "raise"}


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
    """Each row's advice worked out again with the current code, on the
    recording's clock (a stall the frames skip still counts)."""
    from poker_engine.desktop.aa_solver_advice import AASolverAdvice
    now = [0.0]
    advice = AASolverAdvice(_Solved(), _Now(), clock=lambda: now[0])
    result = []
    for row in rows:
        now[0] = row.get("pts_seconds") or now[0]
        result.append(advice.observe_fields(row["fields"], row["processed"]))
    return result


def cause(report):
    """Why a decision got no advice, in a few words."""
    status, reason = report.get("status"), report.get("reason")
    if status == "computing":
        return "solve_not_finished"
    if reason in ("waiting_for_last_action", "not_your_turn_yet"):
        return "history_says_not_your_turn"
    return f"{status}:{reason}"


def decisions(rows, advice):
    """Your turns: consecutive rows with your buttons on screen. Buttons that
    show up while your seat still sits out (waiting) and are gone within
    ``FLASH`` seconds are not a turn: you were not dealt in yet (10/07: two
    or three frames at a hand's start, twice; your real turn came later)."""
    result, current = [], None
    for row, report in zip(rows, advice):
        fields = row["fields"]
        if not (fields.get("hero_controls") or {}).get("visible"):
            current = None
            continue
        if current is None:
            current = {"pts": row["pts_seconds"],
                       "street": fields.get("street"), "reports": [],
                       "first_ready": None, "cards_read": False,
                       "frame": row["processed"],
                       "seated": (fields.get("participants") or {}).get(HERO)
                       != "waiting"}
            result.append(current)
        current["reports"].append(report)
        current["cards_read"] |= len([c for c in fields.get("hero") or () if c]) == 2
        if report.get("status") == "ready" and current["first_ready"] is None:
            current["first_ready"] = round(row["pts_seconds"] - current["pts"], 2)
            current["kind"] = report.get("kind") or (
                "preflop" if current["street"] == "preflop" else "solver")
            current["advice"] = [option.get("action") for option in
                                 (report.get("advice") or [])[:1]]
        current["seconds"] = round(row["pts_seconds"] - current["pts"], 1)
    result = [turn for turn in result
              if turn.pop("seated") or turn.get("seconds", 0) >= FLASH]
    for turn in result:
        turn["pts"] = round(turn["pts"], 1)
        reports = turn.pop("reports")
        if turn["first_ready"] is None:
            causes = Counter(cause(r) for r in reports if r.get("status") != "ready")
            turn["cause"] = causes.most_common(1)[0][0] if causes else "none"
        elif turn["first_ready"] > LATE:
            turn["cause"] = "advice_late"
    return result


def plain(action):
    """fold, check, call or raise (a bet or an all-in counts as a raise)."""
    action = str(action or "").lower()
    return AGGRESSIVE.get(action, action) or None


def your_actions(turns, actions):
    """What you did at each decision: your first action on its street from
    its first frame on, and whether that was the advised action."""
    for turn in turns:
        frame = turn.pop("frame")
        done = next((item for item in actions if str(item["slot"]) == HERO
                     and item["street"] == turn["street"]
                     and item["frame"] >= frame), None)
        turn["you_did"] = None if done is None else plain(done["kind"])
        if turn.get("advice") and turn["you_did"]:
            turn["followed"] = plain(turn["advice"][0]) == turn["you_did"]
    return turns


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def stack(rows, seat=HERO):
    """The seat's stack at the start of these rows: the usual reading of
    their first frames that read it once the pot holds this hand's blinds
    and antes (until then the last pot may still be on its way to you)."""
    readings = [(row["fields"].get("stacks") or {}).get(seat) for row in rows
                if (number(row["fields"].get("pot")) or 0) > 0]
    readings = [value for value in readings if value not in (None, "")][:FIRST]
    return number(Counter(readings).most_common(1)[0][0]) if readings else None


def readings(rows, seat=HERO):
    """The seat's stack in each frame of these rows that read one."""
    values = [number((row["fields"].get("stacks") or {}).get(seat)) for row in rows]
    return [value for value in values if value is not None]


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


def posted(facts):
    """Your chips the table took before the hand's start reading
    (``stack``): your ante and blind or straddle, the mushroom post when you
    are the dealer, or a bomb pot's post. 0 when you were not dealt in; None
    when the dealer is not read or the table size has no AA rules (4 to 8
    players), so the hand counts as before 10/17.

    10/17: each hand counted from that reading to the next hand's, so it
    paid the next hand's posts instead of its own (on 1/2/4(2) a small
    blind folding cost 4 big blinds, the dealer's mushroom post and ante)."""
    seats, hero = facts["seats"], int(HERO)
    if hero not in seats:
        return 0.0
    bomb = bomb_post(facts)
    if bomb is not None:
        return float(bomb)
    dealer = facts["dealer"] if facts["dealer"] in seats else facts.get("blind_dealer")
    if dealer not in seats or not 4 <= len(seats) <= 8:
        return None
    rules = _rules(len(seats), facts["stakes"])
    chips = build_forced_bet_plan(rules, tuple(seats), dealer).contributions[hero]
    if dealer == hero:
        chips += rules.big_blind * MUSHROOM_POST
    return float(chips)


def hand_report(rows, advice, gaps=(), stakes=None):
    """One hand; ``stakes``: what earlier hands settled on (``hand_facts``)."""
    fields = [row["fields"] for row in rows]
    facts = hand_facts(rows, stakes)
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
        "decisions": your_actions(decisions(rows, advice), history["actions"]),
        **shown_cards(fields, history["actions"]),
        "skipped_seats": len(skipped_seats(history)),
        "unexplained_pot_rises": len(unexplained_rises(history)),
        "unrecorded_folds": len(unrecorded_folds(history)),
        "replay": None if replay is None else (
            "ok" if replay["status"] == "ok" else replay["reason"]),
        "bomb_pot": None if replay is None else replay.get("bomb_pot"),
        "stalls": [gap for gap in gaps
                   if rows[0]["pts_seconds"] <= gap["pts"] <= rows[-1]["pts_seconds"]],
        "start_stack": stack(rows), "posted": posted(facts),
        "stakes": facts["stakes"],
        "first_stack": next(iter(readings(rows)), None),
        "end_stack": (readings(rows) or [None])[-1],
        "most_pot": max(filter(None, map(number, (f.get("pot") for f in fields))),
                        default=None)}


def shown_cards(fields, actions):
    """The cards opponents turned face up in the hand, each with that seat's
    actions street by street, and the seats read as two different pairs."""
    shown = next((f["shown_cards"] for f in reversed(fields) if f.get("shown_cards")),
                 None) or {"seats": {}, "unknown": []}
    seats = []
    for seat, value in sorted(shown["seats"].items(), key=lambda item: int(item[0])):
        streets = {}
        for item in actions:
            if str(item["slot"]) == seat:
                streets.setdefault(item["street"], []).append(
                    item["kind"] if item["amount"] in (None, "0") else
                    f"{item['kind']} {item['amount']}")
        seats.append({"seat": int(seat), "cards": value["cards"], "actions": streets})
    return {"shown_cards": seats, "shown_unknown": [int(s) for s in shown["unknown"]]}


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
        ours, settled = [], None
        for pairs in grouped.values():
            hand = hand_report([p[0] for p in pairs], [p[1] for p in pairs], gaps,
                               settled)
            stakes = hand.pop("stakes")
            if stakes["source"] == "table":
                settled = stakes
            ours.append({"log": name, **hand})
        chips(ours)
        hands += ours
    summary = summarize(hands)
    summary["range_exclusion"] = range_reads(logs, hands)
    return {"summary": summary, "hands": hands}


def range_reads(logs, hands):
    """Each shown seat's ``range_read`` and the session's exclusion rates."""
    found = session_exclusion(logs)
    reads = {}
    for item in found["hands"]:
        reads.setdefault((item["log"], item["hand_id"], item["seat"]), {
            key: item[key] for key in ("street", "narrowed", "out", "out_before_end")})
    for item in found["skipped_hands"]:
        reads.setdefault((item["log"], item["hand_id"], item["seat"]),
                         {"skipped": item["reason"]})
    for hand in hands:
        for seat in hand["shown_cards"]:
            seat["range_read"] = reads.get((hand["log"], hand["hand_id"], seat["seat"]))
    keep = ("all", "narrowed", "river", "you_in", "by_street", "first")
    return {"reads": found["reads"], "skipped": found["skipped"],
            **{view: {key: found[view][key] for key in keep}
               for view in ("whole_hand", "before_end")}}


def chips(hands):
    """Your chips from each hand's start to the next hand's start in the same
    recording, before either hand's posts (``posted``). A hand that goes on
    with your same two cards was split in two (a new hand was started in the
    middle of it): both parts count as one, on the first. A rise larger than
    the hand's biggest pot is a rebuy or a misread and is left out.

    A hand you finished all in with nothing left (``busted``) costs your
    whole start. Until 10/16 those were left out (no stack read after it)
    or counted against the rebuy (10 busts on 10/07-10/16, about 1,060 big
    blinds). A rebuy before the next hand cannot be told from a win."""
    parts = []
    for hand in hands:
        last = parts[-1][-1] if parts else None
        if last is not None and hand["your_cards"] and \
                hand["your_cards"] == last["your_cards"]:
            hand["split_from"] = last["hand_id"]
            parts[-1].append(hand)
        else:
            parts.append([hand])
    for whole, after in zip(parts, parts[1:] + [None]):
        first = whole[0]
        one = first["start_stack"]
        two = after[0]["start_stack"] if after else None
        if one is not None:
            one += first["posted"] or 0
        if two is not None:
            two += after[0]["posted"] or 0
        most = max((h["most_pot"] for h in whole if h["most_pot"] is not None),
                   default=None)
        for hand in whole:
            hand["your_chips"] = None
        if not any(h["you_in"] for h in whole) or one is None:
            continue
        if busted(whole, after):
            first["your_chips"] = round(-one, 2)
            continue
        if two is None:
            continue
        change = two - one
        if change > 0 and (most is None or change > most):
            continue
        first["your_chips"] = round(change, 2)
    for hand in hands:
        for key in ("start_stack", "posted", "most_pot", "first_stack", "end_stack"):
            del hand[key]


def busted(whole, after):
    """Whether you lost all your chips in this hand (``whole``, its parts):
    your last stack read 0, and either the recording ended after the hand
    ended or the whole next hand (``after``, its parts) went by without you
    dealt in, your stack first read 0 or not read (a rebuy comes later)."""
    last = whole[-1]
    if last["end_stack"] != 0:
        return False
    if after is None:
        return last["complete"]
    following = after[0]
    return (following["complete"] and not following["you_in"]
            and not following["first_stack"])


def followed(hand):
    """Whether you followed the advice in this hand: "yes" when every advised
    decision was followed, "no" when one was not, "no_advice" when a decision
    had none, "no_decision" when you only folded out of turn or watched."""
    turns = hand["decisions"]
    if not turns:
        return "no_decision"
    if any(turn.get("followed") is False for turn in turns):
        return "no"
    if any(turn["first_ready"] is None for turn in turns):
        return "no_advice"
    return "yes"


def advised_throughout(hand):
    """Every one of your decisions in ``hand`` got advice."""
    return all(turn["first_ready"] is not None for turn in hand["decisions"])


def summarize(hands):
    real = [h for h in hands if h["complete"] or h["you_in"]]
    turns = [t for h in real for t in h["decisions"]]
    advised = [t for t in turns if t["first_ready"] is not None]
    played = [h for h in real if h["decisions"]]
    deep = [h for h in played if any(t["street"] != "preflop" for t in h["decisions"])]
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
    split = sum(bool(hand.get("split_from")) for hand in hands)
    if split:
        problems["hand_split_in_two"] = split
    sizes = {}
    for hand in real:
        size = sizes.setdefault(hand["players"], Counter())
        size["hands"] += 1
        size["your_decisions"] += len(hand["decisions"])
        size["advised"] += sum(t["first_ready"] is not None for t in hand["decisions"])
        if hand["your_chips"] is not None:
            size["your_chips"] += hand["your_chips"]
    known = [t for t in advised if t.get("you_did")]
    results = {}
    for hand in real:
        if hand["your_chips"] is not None:
            group = results.setdefault(followed(hand), Counter())
            group["hands"] += 1
            group["chips"] += hand["your_chips"]
    return {"fully_advised": {
                "hands": len(played), "advised": sum(map(advised_throughout, played)),
                "past_preflop": len(deep),
                "past_preflop_advised": sum(map(advised_throughout, deep))},
            "hands": len(real), "players": dict(sorted(Counter(
                h["players"] for h in real).items())),
            "by_players": {size: dict(counts)
                           for size, counts in sorted(sizes.items())},
            "advised_and_action_seen": len(known),
            "followed_advice": sum(bool(t.get("followed")) for t in known),
            "your_chips": round(sum(h["your_chips"] for h in real
                                    if h["your_chips"] is not None), 2),
            "your_chips_by_advice": {key: {"hands": value["hands"],
                                           "chips": round(value["chips"], 2)}
                                     for key, value in sorted(results.items())},
            "your_hands": len(yours), "your_decisions": len(turns),
            "advised": len(advised),
            "advised_by_street": dict(Counter(t["street"] for t in advised)),
            "advised_by_kind": dict(Counter(t["kind"] for t in advised)),
            "decisions_by_street": dict(Counter(t["street"] for t in turns)),
            "seconds_to_advice_median": sorted(t["first_ready"] for t in advised)[
                len(advised) // 2] if advised else None,
            "no_advice_causes": dict(causes.most_common()),
            "hand_problems": dict(problems.most_common()),
            "stalls_over_2s": sum(1 for h in real for s in h["stalls"]
                                  if s["seconds"] > STALE),
            "shown_cards": {
                "hands": sum(bool(h["shown_cards"]) for h in real),
                "seats": sum(len(h["shown_cards"]) for h in real),
                "seats_unknown": sum(len(h["shown_unknown"]) for h in real)}}


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
