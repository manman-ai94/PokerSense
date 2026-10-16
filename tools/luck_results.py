"""Real results with the luck taken out, and a ledger of every decision.

From the window's own log of a session (``frames.jsonl``), for every hand
you were in with a result (the hands ``tools/flywheel_session.py`` counts,
in big blinds at the hand's own level):

* card luck (``luck.hole_luck``): what your two cards are worth above the
  average hand at your seat, on the simulated AA table; taken out of every
  normal hand whose seat is known (dealer read, or the blinds placing him)
  and whose cards were read. Bomb pots keep theirs (the table is of normal
  hands);
* runout luck (``luck.runout_luck``): after an all-in with cards still to
  come, what the board that came won or lost against the average board,
  when every live hand was face up and the whole board read. The hand is
  replayed on the AA table (``aa_solver_input``, from the stacks read, else
  deep) for what each player put in, and only counts when that replay pays
  you what the table did (within ``SETTLE_MATCH`` of the pot). A hand that
  does not replay, or whose replay pays out otherwise, is worked out from
  the screen instead when two were left with their cards face up
  (``screen_runout``): the street one of them went all in, and the pot they
  played for from the pot read, their stacks and your result, which it
  must agree with;
* the result less both: on average the same as the result, whatever was
  decided (only chance is taken out), with less spread.

Both are only taken out where they can be worked out, and whether they can
does not depend on what the luck was, so nothing is biased by it; the
summary says in how many hands each one was (``cards``, ``allin``). The card
luck's average is a check too: over many hands it must come near zero, and
far from zero says hands were left out by their cards (quick folds whose
cards were not read).

Each decision on your turn becomes a ledger line: the advice that showed
last and its kind, what you did, whether that followed it, its flags
(``tools/aa_strategy_review.py``), and the hand's result with and without
the luck. Hand and decision lines hold your cards' worth, not the cards;
they stay in the private data folder all the same (a decision line is one
seat's play). Only the summary goes anywhere else.

The summary gives big blinds per 100 hands as played and with the luck
out, with the always-valid 95% interval (``luck.always_valid``: it stays
right however often it is looked at, so the daily look cannot call a
result too early), the verdict it gives (赢 / 输 / 说不准), how many hands an
interval of ±100 and ±20 bb/100 needs at this spread, and the same split into normal
hands and bomb pots, by whether you followed the advice (decided by you, not
chance: only a hint) and by code version.

    PYTHONPATH=src:. .venv/bin/python tools/luck_results.py \\
        --frames <录像>/frames.jsonl [...] [--out 汇总.json] [--lines <私有目录>]
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_solver_input import (  # noqa: E402
    PLAYERS, _rules, hand_facts, replay_hand, starting_stacks)
from poker_engine.desktop.aa_stakes import stakes_label  # noqa: E402
from poker_engine.scoreboard import luck  # noqa: E402
from poker_engine.scoreboard.allin_ev import SHOWN, _rake_share  # noqa: E402
from poker_engine.scoreboard.strength import DECK  # noqa: E402
from poker_engine.strategy.aa_rules_v2 import estimate_rake  # noqa: E402
from tools import flywheel_session as fly  # noqa: E402
from tools.aa_session_report import (  # noqa: E402
    HERO, IN_HAND, followed, number, session_report, stack)
from tools.aa_strategy_review import decisions as review_decisions  # noqa: E402

SEAT = int(HERO)
WIDTHS = (100, 20)          # bb/100 an interval of ± this many needs how many hands
SETTLE_MATCH = 0.05         # share of the pot the replayed result may be off
ALL_IN_FRAMES = 3           # frames a seat must read all in (or folded) to count
CALLED = 1.5                # pot growth after an all-in (his last chips) from a call


def stable_seed(*parts):
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def position(facts):
    """(your seat 0-7 on the simulated table, None), or (None, why not)."""
    seats = facts["seats"]
    if SEAT not in seats:
        return None, "not_dealt_in"
    dealer = facts["dealer"] if facts["dealer"] in seats else facts.get("blind_dealer")
    if dealer not in seats:
        return None, "dealer_unread"
    index = luck.seat_order(seats, dealer).index(SEAT)
    seat = luck.table_position(index, len(seats))
    return (None, f"players_{len(seats)}") if seat is None else (seat, None)


def card_luck(hand, facts, bomb):
    """(big blinds, None) or (None, why it was not taken out)."""
    if bomb:
        return None, "bomb_pot"
    cards = (hand.get("your_cards") or "").split()
    if len(cards) != 2 or not all(card in DECK for card in cards) or \
            cards[0] == cards[1]:
        return None, "cards_unread"
    seat, why = position(facts)
    if seat is None:
        return None, why
    return luck.hole_luck(cards, seat), None


def _replayed(facts):
    """The hand replayed from the stacks read (else deep): (arena, how). A
    seat all in without a stack reading had nothing behind: what it put in
    was its stack (else the table waits for it to act on the next street)."""
    replay = replay_hand(facts)
    if replay["status"] != "ok":
        return None, replay["reason"]
    stacks = starting_stacks(facts, replay)
    put = replay["arena"].observe(facts["seats"][0])["contributions"]
    for action in facts["actions"]:
        if action["kind"] == "all_in" and action["slot"] not in stacks:
            stacks[action["slot"]] = Decimal(put[str(action["slot"])])
    if stacks:
        stacked = replay_hand(facts, stacks)
        if stacked["status"] == "ok" and stacked["arena"].terminal:
            return stacked["arena"], "stacks"
    return replay["arena"], "deep"


def runout(hand, facts, big_blind, rows=()):
    """{"allin", "luck" (big blinds), "why"} for one hand: ``allin`` False
    (luck 0) when nothing was left to come for you, True with ``luck`` None
    and why when an all-in could not be worked out, None when the hand did
    not replay (whether it was an all-in is not known). A hand that does not
    replay, or whose replay pays out otherwise or misses the board, is
    worked out from its frames (``rows``, ``screen_runout``) when they show
    it."""
    arena, how = _replayed(facts)
    if arena is None or not arena.terminal:
        why = how if arena is None else "not_finished"
        return (screen_runout(hand, rows, facts, big_blind)
                or {"allin": None, "luck": None, "why": f"replay:{why}"})
    found = _replay_runout(hand, facts, big_blind, arena, how)
    if found["why"] in ("board_unread", "settle_mismatch"):
        screen = screen_runout(hand, rows, facts, big_blind)
        if screen and screen["luck"] is not None:
            return screen
    return found


def _replay_runout(hand, facts, big_blind, arena, how):
    alive = [i for i, seat in enumerate(arena._seats) if seat not in arena._folded]
    street = arena._history[-1]["street"] if arena._history else "preflop"
    if (len(alive) < 2 or SHOWN[street] >= 5 or SEAT not in arena._seats
            or arena._seats.index(SEAT) not in alive):
        return {"allin": False, "luck": 0.0, "why": None}
    found = {"allin": True, "luck": None, "replay": how}
    shown = {item["seat"]: list(item["cards"]) for item in hand["shown_cards"]}
    shown[SEAT] = (hand.get("your_cards") or "").split()
    holes = {}
    for i in alive:
        cards = shown.get(arena._seats[i]) or []
        if len(cards) != 2 or not all(card in DECK for card in cards):
            return {**found, "why": "cards_not_shown"}
        holes[i] = cards
    board = list(facts["board"])
    if len(board) != 5:
        return {**found, "why": "board_unread"}
    seen = board + [card for cards in holes.values() for card in cards]
    if len(set(seen)) != len(seen) or not all(card in DECK for card in board):
        return {**found, "why": "cards_conflict"}
    contributions = [float(value) for value in arena._contributions]
    actual, expected = luck.runout_luck(
        contributions, holes, board, street,
        _rake_share(arena.rules, arena._contributions),
        seed=stable_seed(hand["log"], hand["hand_id"]))
    at = arena._seats.index(SEAT)
    unit = float(arena.rules.minimum_chip)
    pot = sum(contributions) * unit
    if abs(actual[at] * unit - hand["your_chips"]) > SETTLE_MATCH * pot:
        # The replay put in or paid out other chips than the table did (a
        # stack misread): its luck is not this hand's (10/08, a 130 bb bust
        # replayed deep came out 570 bb unlucky).
        return {**found, "why": "settle_mismatch", "settle_matches": False}
    return {**found, "why": None,
            "luck": (actual[at] - expected[at]) * unit / big_blind,
            "settle_matches": True}


def screen_runout(hand, rows, facts, big_blind):
    """``runout`` from the hand's frames alone, for two players still in, or
    None when they do not show it (your seat never read dealt in).

    A seat is still in when it did not read folded once dealt in: you, and
    the others that showed their cards. The betting closed in the frame
    where all of you but one were all in (stack 0, or the seat read all in),
    on that frame's street. Its luck is your share of the pot the two of you
    played for, after rake (all, half or none: the board's, else your
    result's sign), less your chance of winning it then (``_played``)."""
    rows = [row for row in rows if row.get("fields")]
    dealt = next((at for at, row in enumerate(rows) if _state(row, SEAT) in IN_HAND),
                 None)
    if dealt is None:
        return None
    rows = rows[dealt:]
    nothing = {"allin": False, "luck": 0.0, "why": None, "replay": "screen"}
    found = {"allin": True, "luck": None, "replay": "screen"}
    folded = {seat for seat in range(8) if _folded(rows, seat)}
    if SEAT in folded:
        return nothing
    shown = {item["seat"]: list(item["cards"]) for item in hand["shown_cards"]
             if item["seat"] != SEAT and item["seat"] not in folded}
    live = [SEAT, *sorted(shown)]
    if len(live) < 2:
        # Nobody else showed: an all-in of yours, or one you called, cannot
        # be worked out.
        others = [_first([at for at, row in enumerate(rows)
                          if _state(row, seat) == "all_in"])
                  for seat in range(8) if seat != SEAT]
        anyone = [at for at in [_first(_all_in_frames(rows, SEAT)), *others]
                  if at is not None]
        if anyone and SHOWN[_street(rows, min(anyone))] < 5:
            return {**found, "why": "cards_not_shown"}
        return nothing
    closed = _closed(rows, live)
    if closed is None or SHOWN[_street(rows, closed)] >= 5:
        return nothing
    if len(live) > 2:
        return {**found, "why": "multiway"}
    street = _street(rows, closed)
    holes = {0: (hand.get("your_cards") or "").split(), 1: shown[live[1]]}
    if not all(len(cards) == 2 and all(card in DECK for card in cards)
               for cards in holes.values()):
        return {**found, "why": "cards_not_shown"}
    board = list(facts["board"])
    known = board[:SHOWN[street]]
    seen = board + [card for cards in holes.values() for card in cards]
    if len(set(seen)) != len(seen) or not all(card in DECK for card in board):
        return {**found, "why": "cards_conflict"}
    if len(known) < SHOWN[street]:
        return {**found, "why": "board_unread"}
    if len(board) == 5:
        share = (luck.runout_result([1.0, 1.0], holes, board)[0] + 1) / 2
    elif hand["your_chips"]:
        share = 1.0 if hand["your_chips"] > 0 else 0.0
    else:
        return {**found, "why": "board_unread"}
    # The rake does not change with the table's size (the rules cover 4-8).
    players = min(max(len(facts["seats"]), min(PLAYERS)), max(PLAYERS))
    played = _played(rows, closed, live[1], share, hand["your_chips"],
                     _rules(players, facts.get("stakes")))
    if played is None:
        return {**found, "why": "settle_mismatch", "settle_matches": False}
    outcomes = luck.runout_outcomes([1.0, 1.0], holes, known,
                                    seed=stable_seed(hand["log"], hand["hand_id"]))
    chance = (sum(result[0] for _, result in outcomes) / len(outcomes) + 1) / 2
    return {**found, "why": None, "luck": (share - chance) * played / big_blind,
            "settle_matches": True}


def _played(rows, closed, other, share, yours, rules):
    """The pot you and ``other`` played for after rake, read off the screen
    from the frame the betting ``closed``, or None when no reading of it
    agrees with your result (``yours``, your ``share`` of it).

    The screen's pot holds a bet the all-in could not call until the hand is
    paid. With both of you all in, that part is the bigger stack's excess
    over the smaller. With one all in and the pot then growing by more than
    his last chips again (the other called him), there is none. Either of
    those counts when your share of it less your stake is your result,
    within ``SETTLE_MATCH`` of the pot. Else it is what the winner won plus
    what the loser lost: you by the table's result, the other by his stack
    before the hand and the last one read in it."""
    pot = _steady_max(number(row["fields"].get("pot")) for row in rows[closed:])
    before = _steady_max(number(row["fields"].get("pot")) for row in rows[:closed])
    stakes = {seat: stack(rows, str(seat)) for seat in (SEAT, other)}
    all_in = {seat: _first(_all_in_frames(rows, seat)) for seat in (SEAT, other)}
    whole = None
    if pot and None not in stakes.values():
        if None not in all_in.values():
            whole = pot - abs(stakes[SEAT] - stakes[other])
        else:
            short = SEAT if all_in[SEAT] is not None else other
            last = [number((row["fields"].get("stacks") or {}).get(str(short)))
                    for row in rows[:all_in[short]]]
            last = next((value for value in reversed(last) if value), None)
            if before is not None and last and pot - before >= CALLED * last:
                whole = pot
    if whole:
        net = whole - float(estimate_rake(rules, str(whole), saw_flop=True).amount)
        if abs(share * net - min(stakes.values()) - yours) <= SETTLE_MATCH * whole:
            return net
    after = _last_stack(rows, other)
    if share == 0.5 or stakes[other] is None or after is None:
        return None
    theirs = after - stakes[other]
    won, lost = (yours, -theirs) if share else (theirs, -yours)
    played = won + lost
    cap = float(rules.rake_cap_bb * rules.big_blind)
    if (won <= 0 or lost <= 0 or (pot and played > pot * (1 + SETTLE_MATCH))
            or 2 * lost > played + cap + SETTLE_MATCH * played):
        return None
    return played


def _steady_max(values):
    """The largest value read in two frames or more, or None."""
    counts = Counter(value for value in values if value)
    return max((value for value, count in counts.items() if count >= 2), default=None)


def _state(row, seat):
    return (row["fields"].get("participants") or {}).get(str(seat))


def _folded(rows, seat):
    """Whether the seat read folded once it was in the hand (the last hand's
    folds can still show as this one is dealt)."""
    states = [_state(row, seat) for row in rows]
    dealt = next((at for at, state in enumerate(states) if state in IN_HAND), None)
    return dealt is not None and states[dealt:].count("folded") >= ALL_IN_FRAMES


def _first(frames, count=ALL_IN_FRAMES):
    """The first of these frame numbers, when there are at least ``count``."""
    return frames[0] if len(frames) >= count else None


def _all_in_frames(rows, seat):
    """The frames (numbers into ``rows``) where the seat read all in: no
    chips left, or its seat read all in."""
    return [at for at, row in enumerate(rows) if _state(row, seat) == "all_in"
            or number((row["fields"].get("stacks") or {}).get(str(seat))) == 0]


def _closed(rows, live):
    """The frame where all of live but one were all in, or None."""
    firsts = sorted(at for at in (_first(_all_in_frames(rows, seat)) for seat in live)
                    if at is not None)
    return firsts[len(live) - 2] if len(firsts) >= len(live) - 1 else None


def _last_stack(rows, seat):
    """The seat's last stack read in two frames running (after the pot was
    paid, when the frames go on that long)."""
    values = [number((row["fields"].get("stacks") or {}).get(str(seat)))
              for row in rows]
    values = [value for value in values if value is not None]
    return next((one for one, two in zip(values[::-1], values[-2::-1]) if one == two),
                None)


def _street(rows, at):
    """The street read at frame ``at`` (else the last one read before it)."""
    for row in reversed(rows[:at + 1]):
        if row["fields"].get("street") in SHOWN:
            return row["fields"]["street"]
    return "preflop"


def hand_lines(name, rows, code=None, report=None):
    """(hand lines, decision lines) of one log; ``report``: its
    ``session_report`` when already made (``tools/session_package.py``)."""
    rows = [row for row in rows if row.get("fields")]
    report = report or session_report([(name, rows)])
    grouped = fly.by_hand(rows)
    stakes = fly.hand_stakes(grouped)
    turns = {}
    for turn in review_decisions(name, rows, [fly._advice(row) for row in rows]):
        turns.setdefault(turn["hand_id"], []).append(turn)
    hands, ledger = [], []
    for hand in report["hands"]:
        if hand["your_chips"] is None:
            continue
        level = stakes[hand["hand_id"]]
        big_blind = float(Decimal(level["big_blind"]))
        facts = hand_facts(grouped[hand["hand_id"]], level)
        bomb = bool(hand.get("bomb_pot"))
        bb = hand["your_chips"] / big_blind
        cards, cards_why = card_luck(hand, facts, bomb)
        ran = runout(hand, facts, big_blind, grouped[hand["hand_id"]])
        adjusted = bb - (cards or 0.0) - (ran["luck"] or 0.0)
        seat, _ = position(facts)
        line = {"log": name, "hand_id": hand["hand_id"], "code": code,
                "video_seconds": hand["video_seconds"], "players": hand["players"],
                "seat": None if seat is None else luck.POSITIONS[seat],
                "stakes": stakes_label(level),
                "stakes_sure": level["source"] != "unsure",
                "bomb_pot": bomb, "bb": round(bb, 3),
                "card_luck": None if cards is None else round(cards, 3),
                "card_luck_missing": cards_why,
                "runout_luck": None if ran["luck"] is None else round(ran["luck"], 3),
                "runout_missing": ran["why"],
                "allin": ran["allin"],
                "settle_matches": ran.get("settle_matches"),
                "runout_from": ran.get("replay"),
                "adjusted": round(adjusted, 3), "followed": followed(hand),
                "decisions": len(hand["decisions"])}
        hands.append(line)
        for turn in turns.get(hand["hand_id"]) or ():
            last = turn["answers"][-1] if turn["answers"] else {}
            ledger.append({
                "log": name, "hand_id": hand["hand_id"], "code": code,
                "street": turn["street"], "video_seconds": turn["video_seconds"],
                "opponents": turn["opponents"], "button": turn["button"],
                "to_call": turn["to_call"], "pot": turn["pot"],
                "advice": last.get("action"), "kind": last.get("kind"),
                "share": last.get("share"),
                "first_advice_seconds": (turn["answers"][0]["seconds"]
                                         if turn["answers"] else None),
                "advice_changed": len(turn["answers"]) > 1,
                "you_did": turn["you_did"], "followed": turn.get("followed"),
                "flags": turn["flags"], "seat": line["seat"],
                "bomb_pot": bomb, "stakes": line["stakes"],
                "hand_bb": line["bb"], "hand_adjusted": line["adjusted"]})
    return hands, ledger


def _per_100(value):
    return None if value is None else round(100 * value, 1)


def part(lines):
    """One group's numbers, per 100 hands."""
    raw = [line["bb"] for line in lines]
    adjusted = [line["adjusted"] for line in lines]
    if not lines:
        return {"hands": 0}
    mean, half = luck.always_valid(adjusted)
    raw_mean, raw_half = luck.always_valid(raw)
    plain_mean, plain_half = luck.interval(adjusted)
    item = {"hands": len(lines), "bb": round(sum(raw), 2),
            "bb_per_100": _per_100(raw_mean),
            "bb_per_100_ci95": None if raw_half is None else [
                _per_100(raw_mean - raw_half), _per_100(raw_mean + raw_half)],
            "adjusted_bb_per_100": _per_100(mean),
            "adjusted_ci95": None if half is None else [
                _per_100(mean - half), _per_100(mean + half)],
            "adjusted_ci95_one_look": None if plain_half is None else [
                _per_100(plain_mean - plain_half), _per_100(plain_mean + plain_half)],
            "verdict": verdict(mean, half)}
    if len(lines) > 1:
        before, after = spread(raw), spread(adjusted)
        item["spread_per_hand_bb"] = {"as_played": round(before, 2),
                                      "luck_out": round(after, 2)}
        item["fewer_hands"] = round((before / after) ** 2, 2) if after else None
        item["hands_needed"] = {str(width): luck.hands_for(after, width / 100)
                                for width in WIDTHS}
    return item


def verdict(mean, half):
    if half is None:
        return "说不准"
    if mean - half > 0:
        return "赢"
    if mean + half < 0:
        return "输"
    return "说不准"


def spread(values):
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def summarize(lines):
    """The summary of hand lines (``hand_lines``): totals only."""
    normal = [line for line in lines if not line["bomb_pot"]]
    carded = [line["card_luck"] for line in normal if line["card_luck"] is not None]
    allin = [line for line in lines if line["allin"]]
    unknown = sum(line["allin"] is None for line in lines)
    applied = [line for line in allin if line["runout_missing"] is None]
    card_mean, card_half = luck.interval(carded)
    missing = Counter(line["runout_missing"] for line in allin
                      if line["runout_missing"] is not None)
    summary = {**part(lines),
               "card_luck_bb_per_100": _per_100(card_mean),
               "card_luck_ci95": None if card_half is None else [
                   _per_100(card_mean - card_half), _per_100(card_mean + card_half)],
               "runout_luck_bb": round(sum(line["runout_luck"] for line in applied), 2),
               "cards": {"taken_out": len(carded), "normal_hands": len(normal),
                         "missing": dict(Counter(line["card_luck_missing"]
                                                 for line in normal
                                                 if line["card_luck"] is None))},
               "allin": {"hands": len(allin), "taken_out": len(applied),
                         "not_replayed": unknown,
                         "missing": dict(missing),
                         "settle_matches": sum(bool(line["settle_matches"])
                                               for line in applied),
                         "from_screen": sum(line.get("runout_from") == "screen"
                                            for line in applied),
                         "screen_checked": sum(line.get("runout_from") == "screen"
                                               for line in lines)},
               "by_kind": {"normal": part(normal), "bomb_pot": part(
                   [line for line in lines if line["bomb_pot"]])},
               "by_followed": {key: part([line for line in lines
                                          if line["followed"] == key])
                               for key in ("yes", "no", "no_advice", "no_decision")},
               "by_code": {}}
    for code in sorted({line.get("code") for line in lines}, key=str):
        summary["by_code"][str(code)[:7] if code else "unknown"] = part(
            [line for line in lines if line.get("code") == code])
    return summary


def plain_lines(summary, who="他"):
    """The summary in a few plain lines (Chinese), for a review sheet."""
    if not summary.get("hands"):
        return ["没有算得出成绩的手"]
    card = summary["cards"]
    allin = summary["allin"]

    def ci(pair):
        return "—" if pair is None else f"{pair[0]:+g} 到 {pair[1]:+g}"

    lines = [f"{summary['hands']} 手：打出来 {summary['bb_per_100']:+g} bb/100；"
             f"扣掉运气 {summary['adjusted_bb_per_100']:+g} bb/100"
             f"（95% 区间 {ci(summary['adjusted_ci95'])}，结论：{summary['verdict']}）"]
    luck_parts = []
    if summary.get("card_luck_bb_per_100") is not None:
        luck_parts.append(f"起手牌运气 {summary['card_luck_bb_per_100']:+g} bb/100"
                          f"（{card['taken_out']}/{card['normal_hands']} 手算得出）")
    if allin["hands"]:
        luck_parts.append(f"全下后发牌运气 {summary['runout_luck_bb']:+g} bb"
                          f"（全下 {allin['hands']} 手，算得出 {allin['taken_out']} 手）")
    if luck_parts:
        lines.append("运气：" + "；".join(luck_parts))
    if summary.get("hands_needed"):
        lines.append("按现在的波动，区间缩到 " + "、".join(
            f"±{width} bb/100 共约需 {count:,} 手"
            for width, count in summary["hands_needed"].items()))
    follow = summary["by_followed"]
    if follow["yes"]["hands"] and follow["no"]["hands"]:
        yes, no = follow["yes"], follow["no"]
        lines.append(f"照建议打的 {yes['hands']} 手扣运气后 "
                     f"{yes['adjusted_bb_per_100']:+g}，没照的 {no['hands']} 手 "
                     f"{no['adjusted_bb_per_100']:+g}（是{who}自己选的，只作参考）")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, help="the summary (totals only)")
    parser.add_argument("--lines", type=Path,
                        help="a private folder for hands.jsonl and decisions.jsonl")
    args = parser.parse_args(argv)
    hands, ledger = [], []
    for path in args.frames:
        rows = fly.load(path)
        code = fly.code_of(path.parent, rows)
        code = code.get("commit") if isinstance(code, dict) else code
        found, turns = hand_lines(path.parent.name, rows, code)
        hands += found
        ledger += turns
    summary = summarize(hands)
    if args.out:
        args.out.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    if args.lines:
        args.lines.mkdir(parents=True, exist_ok=True)
        for name, items in (("hands.jsonl", hands), ("decisions.jsonl", ledger)):
            (args.lines / name).write_text("".join(
                json.dumps(item, ensure_ascii=False) + "\n" for item in items),
                encoding="utf-8")
    print("\n".join(plain_lines(summary, "你")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
