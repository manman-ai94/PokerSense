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
  deep) for what each player put in;
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
interval of ±20 bb/100 needs at this spread, and the same split into normal
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
    hand_facts, replay_hand, starting_stacks)
from poker_engine.desktop.aa_stakes import stakes_label  # noqa: E402
from poker_engine.scoreboard import luck  # noqa: E402
from poker_engine.scoreboard.allin_ev import SHOWN, _rake_share  # noqa: E402
from poker_engine.scoreboard.strength import DECK  # noqa: E402
from tools import flywheel_session as fly  # noqa: E402
from tools.aa_session_report import HERO, followed, session_report  # noqa: E402
from tools.aa_strategy_review import decisions as review_decisions  # noqa: E402

SEAT = int(HERO)
HALF_WIDTH = 0.20           # big blinds per hand: ±20 bb/100
SETTLE_MATCH = 0.05         # share of the pot the replayed result may be off


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


def runout(hand, facts, big_blind):
    """{"allin", "luck" (big blinds), "why"} for one hand: ``allin`` False
    (luck 0) when nothing was left to come for you, True with ``luck`` None
    and why when an all-in could not be worked out, None when the hand did
    not replay (whether it was an all-in is not known)."""
    arena, how = _replayed(facts)
    if arena is None or not arena.terminal:
        why = how if arena is None else "not_finished"
        return {"allin": None, "luck": None, "why": f"replay:{why}"}
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
    return {**found, "why": None,
            "luck": (actual[at] - expected[at]) * unit / big_blind,
            "settle_matches": abs(actual[at] * unit - hand["your_chips"])
            <= SETTLE_MATCH * pot}


def hand_lines(name, rows, code=None):
    """(hand lines, decision lines) of one log."""
    rows = [row for row in rows if row.get("fields")]
    report = session_report([(name, rows)])
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
        ran = runout(hand, facts, big_blind)
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
        item["hands_for_20"] = luck.hands_for(after, HALF_WIDTH)
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
                                               for line in applied)},
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
    if summary.get("hands_for_20"):
        lines.append(f"按现在的波动，要把区间缩到 ±20 bb/100 共约需 "
                     f"{summary['hands_for_20']:,} 手")
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
