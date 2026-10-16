"""场次包: one played session as evidence an AI can read, without the video.

    PYTHONPATH=src:. .venv/bin/python tools/session_package.py \\
        --recording <录像文件夹> [--recording ...] [--with-sheet [--no-ledger]]

Writes ``<录像文件夹>/flywheel/package.json`` (a few hundred KB, no pictures).
When a recording stops, the window starts this with ``--with-sheet``
(``aa_after_session``): the check-up sheet first, as ``flywheel_session.py
report`` makes it, then the package, so every recording gets one and the
uploader (``aa_upload``) sends it first; ``flywheel_sync.py pull`` makes one
for a pulled recording that came without it. Everything in it comes from the
logs that are already there (the window's ``frames.jsonl``,
``recording.json``, the sheet's ``flywheel/summary.json`` and
``hands.json``) and the tools that read them (``aa_session_report``,
``aa_strategy_review``, ``luck_results``, the replay of ``aa_solver_input``);
nothing new is worked out about the play. What a field needs and the log
does not have is ``null``, with the reason in ``nulls``.

Blocks (``FORMAT`` 2, which added block 11; ``tools/session_evidence.py``
reads them):

1. ``session``: machine, played code, level, hands, length, spectating or
   not, results in big blinds (per 100 hands with a 95% interval; with the
   luck taken out, ``luck_results``), advice coverage.
2. ``decisions``: one line a turn of yours: hand, street, position, players,
   what you faced, price, pot, effective stack, SPR; the advice that showed
   last (action, size, reason, rule, the three numbers, flip condition: the
   one-page rules ``plain`` log those, the older advice does not); how long
   it took to be ready and what was missing, iron rule 5, ``unspecified``;
   what you did, whether you followed, the hand's result.
3. ``shown``: every seat that turned its cards face up: the cards, each
   reading of them, how they came up (``allin_showdown`` / ``showdown`` /
   ``voluntary``), the seat's actions street by street, the range the
   one-page rules give it (section 4: preflop class, then cut once a street)
   and where the real hand sits in it.
4. ``misreads``: hands whose cards or board were read two ways, decisions
   without a price, a pot or an opponent's stack, actions put in from the
   chips rather than read, readings corrected by later frames.
5. ``rule_hits``: the sheet's rule column (``flywheel_session``'s 规则命中统计
   for ``plain`` advice), as it is.
6. ``timing``: seconds to the first advice, changes of mind, decisions
   without advice, whether the advice came before you acted.
7. ``versions``: package format, one-page version and a hash of each rule's
   wording with every number and hand table of the page (a rule number used
   again with other wording or numbers is another rule), the opponent
   models' files.
8. ``hands``: every hand as one replayable record: your cards, the board,
   every action (``inferred`` when it came from the chips, not a badge;
   the replay's own fill-ins apart), each seat's starting stack, level,
   bomb pot, mushroom pool.
9. ``identity``: who played (``player`` in the upload settings, apart from
   the machine), table and hand numbers, opponents' names hashed.
10. ``shown_denominators``: for each preflop class (section 4), how many
    opponent seats were in it and how each ended (shown at an all-in or a
    plain showdown, shown by choice, mucked, folded, won without a
    showdown; ``late`` for a hand not seen from its start, ``unfinished``
    for the hand the log ends in); only all-in and plain showdowns of hands
    seen whole calibrate a range.
11. ``shadow``: 离线影子重放 and the 分量账本 of the page's section 7
    (``tools/session_shadow.py``): at each of your decisions the page and the
    older advice both worked out again from the frame log; the first
    divergence of each hand booked with a fold worth 0 in the page's three
    groups, and every spot of v3.3's two loosenings kept apart. Calculated
    and kept, never shown to the player.

The package holds other players' hands: it stays in the private data folder
and the owner's cloud folder, never in the repository. All of it is table
points (积分), never money.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.code_version import code_version  # noqa: E402
from poker_engine.data_paths import private_root  # noqa: E402
from poker_engine.desktop import aa_upload  # noqa: E402
from poker_engine.desktop.aa_solver_input import (  # noqa: E402
    bomb_post, hand_facts, replay_hand, starting_stacks)
from poker_engine.desktop.aa_stakes import stakes_label  # noqa: E402
from tools import flywheel_session as fly  # noqa: E402
from tools.aa_session_report import session_report, stack  # noqa: E402
from tools.aa_strategy_review import decision as review_decision  # noqa: E402
from tools import session_shadow  # noqa: E402

FORMAT = 2
FILE = "package.json"
HERO = 4
STREETS = ("preflop", "flop", "turn", "river")
BOARD_CARDS = {"flop": 3, "turn": 4, "river": 5}
LIVE = ("active", "all_in")
AGGRESSIVE = ("raise", "bet", "all_in")
BADGES = ("fold", "check", "call", "aggressive", "raise", "bet", "all_in")
MODELS = ("aa_cal_stats_v1.json", "aa_real_stats_v1.json")
SCOREBOARD = Path(__file__).resolve().parents[1] / "src" / "poker_engine" / "scoreboard"
PLAIN_MISSING = "一页纸打法（plain）不在这版代码里"
BUCKETS = (0.2, 0.5, 1.0, 2.0, 5.0)     # seconds: the first-advice histogram
# Preflop classes of section 4, in the order the evidence sheet lists them.
CLASSES = ("limp", "raise", "call_raise", "three_bet", "call_three_bet")
CALIBRATING = ("allin_showdown", "showdown")


def plain_policy():
    """The one-page rules (``scoreboard.plain_policy``), or None in a version
    of the code without them."""
    try:
        from poker_engine.scoreboard import plain_policy as module
    except ImportError:
        return None
    return module


def digest(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:16]


def number(value):
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except ArithmeticError:
        return None


def money(value):
    if value is None:
        return None
    value = Decimal(value)
    return format(value.normalize(), "f") if value else "0"


def in_bb(value, big_blind):
    if value is None or not big_blind:
        return None
    return round(float(Decimal(value) / Decimal(big_blind)), 2)


def mode(values):
    values = [value for value in values if value not in (None, "")]
    return Counter(values).most_common(1)[0][0] if values else None


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _advice(row):
    fields = row["fields"]
    return fields.get("solver_advice") or fields.get("solver_advice_v1") or {}


# -- 1, 9. the session and who played it ---------------------------------------------

def upload_settings():
    return aa_upload.load_settings(private_root() / "upload" / "settings.json")


def who(folder, settings=None):
    """(machine, player, where the player came from) of a recording: one
    pulled from another computer names its machine in ``pulled.json``; one
    made here takes this computer's upload settings."""
    pulled = read_json(Path(folder) / fly.PULLED)
    if isinstance(pulled, dict) and pulled.get("machine"):
        machine = str(pulled["machine"])
        return machine, machine, "machine"
    settings = settings or upload_settings()
    player = settings.get("player") or ""
    return settings["machine"], player or settings["machine"], (
        "settings" if player else "machine")


def wall_clock(meta):
    """The recording's start as a datetime, or None."""
    started = (meta or {}).get("started")
    try:
        return datetime.strptime(started, "%Y-%m-%dT%H:%M:%S%z")
    except (TypeError, ValueError):
        return None


def at(start, seconds):
    if start is None or seconds is None:
        return None
    return (start + timedelta(seconds=float(seconds))).isoformat(timespec="seconds")


def session_block(folder, meta, item, luck, machine, spectate):
    keep = ("hands", "your_hands", "decisions", "advised", "fully_advised",
            "followed", "stalls_over_2s", "no_advice_causes", "stakes",
            "stakes_unsure_hands")
    return {"label": Path(folder).name, "machine": machine,
            "code": item.get("code"), "started": (meta or {}).get("started"),
            "seconds": (meta or {}).get("recorded_seconds"),
            "spectate": spectate,
            **{key: item.get(key) for key in keep},
            "results": {key: item.get(key) for key in ("all", "normal", "bomb_pot")},
            "luck_adjusted": luck}


def luck_summary(name, rows, code, report):
    """``luck_results`` over this log: (summary, {hand id: luck-adjusted bb},
    {hand id: {"runout": the luck of the cards dealt after an all-in in big
    blinds, "allin": whether there was one}})."""
    from tools import luck_results
    commit = code.get("commit") if isinstance(code, dict) else code
    lines, _ = luck_results.hand_lines(name, rows, commit, report=report)
    keep = ("hands", "bb", "bb_per_100", "bb_per_100_ci95", "adjusted_bb_per_100",
            "adjusted_ci95", "adjusted_ci95_one_look", "verdict",
            "card_luck_bb_per_100", "runout_luck_bb", "cards", "allin")
    summary = luck_results.summarize(lines)
    return ({key: summary.get(key) for key in keep},
            {line["hand_id"]: line["adjusted"] for line in lines},
            {line["hand_id"]: {"runout": line["runout_luck"], "allin": line["allin"]}
             for line in lines})


# -- position -----------------------------------------------------------------------

def table_of(facts, replay):
    """(seats, dealer, straddler, bomb post) of a hand: the dealer the replay
    settled on, else the reader's or the blinds'."""
    seats = facts["seats"]
    dealer = (replay or {}).get("dealer")
    if dealer is None:
        dealer = facts.get("dealer") if facts.get("dealer") in seats else (
            facts.get("blind_dealer"))
    bomb = bomb_post(facts)
    straddler = None
    if dealer in seats and bomb is None and len(seats) >= 4:
        at_ = seats.index(dealer)
        ring = seats[at_:] + seats[:at_]
        straddler = ring[3]
    return seats, dealer if dealer in seats else None, straddler, bomb


def positions(page, seats, dealer, straddler):
    """{seat: (早/中/晚/盲, name)} by the one-page definition (section 1), or {}."""
    if page is None or dealer is None or len(seats) < 2:
        return {}
    return page.seat_classes({"occupied_seats": seats, "dealer_seat": dealer,
                              "straddler_seat": straddler})


# -- the hand's actions -------------------------------------------------------------

def badge_actions(rows):
    """(frame, seat) of each action the reader read off a badge in these rows."""
    seen = set()
    for row in rows:
        for item in (row["fields"].get("actions_tail") or ()):
            if item.get("kind") in BADGES or item.get("glyph") in BADGES:
                seen.add((item.get("frame"), item.get("slot")))
    return seen


def history_actions(rows, frames):
    """The hand's actions as the window's history has them, each marked
    ``inferred`` when no badge was read for it (all in from a stack going
    to 0, a call or raise from a stack drop: ``aa_action_history``)."""
    history = rows[-1]["fields"].get("actions_v1") or {}
    badges = badge_actions(rows)
    found = []
    for frame, street, seat, kind, amount, source in history.get("actions") or ():
        found.append({"frame": frame, "video_seconds": frames.get(frame),
                      "street": street, "seat": seat, "kind": kind,
                      "amount": amount, "source": source,
                      "inferred": (frame, seat) not in badges})
    return found


def video_at(rows):
    """{reader frame: seconds into the video} of these rows."""
    return {row["processed"]: row.get("video_seconds") for row in rows}


def replayed(replay, actions):
    """The replay's own sequence (``public_history``), each step marked with
    whether the window read it (``seen``) or the replay put it in to make the
    betting fit (aligned by seat, street and kind)."""
    arena = (replay or {}).get("arena")
    if arena is None:
        return None
    steps = arena.observe(arena.occupied_seats[0])["public_history"]
    read = Counter()
    for action in actions:
        read[(action["seat"], action["street"], kind_class(action["kind"]))] += 1
    used = Counter()
    out = []
    for step in steps:
        kind = step.get("kind")
        paid = number(step.get("paid")) or Decimal(0)
        simple = ("fold" if kind == "fold" else "raise" if kind == "raise_to"
                  else "call" if paid else "check")
        key = (step["actor"], step["street"], kind_class(simple))
        used[key] += 1
        out.append({"street": step["street"], "seat": step["actor"], "kind": simple,
                    "to": step.get("raise_to"), "paid": step.get("paid"),
                    "seen": used[key] <= read[key]})
    return out


def kind_class(kind):
    return {"all_in": "raise", "bet": "raise"}.get(kind, kind)


# -- 8. the hand records --------------------------------------------------------------

def hand_record(name, rows, facts, replay, hand, start, page, luck_bb):
    frames = video_at(rows)
    actions = history_actions(rows, frames)
    seats, dealer, straddler, bomb = table_of(facts, replay)
    stakes = facts["stakes"]
    stacks = starting_stacks(facts, replay) if (replay or {}).get("status") == "ok" \
        else {}
    first = {}
    for row in rows:
        for seat, value in (row["fields"].get("stacks") or {}).items():
            if value not in (None, "") and int(seat) not in first:
                first[int(seat)] = value
    shown = last_shown(rows)
    mushroom = mode(row["fields"].get("mushroom_pool") for row in rows)
    report = hand or {}
    return {
        "log": name, "hand_id": facts["hand_id"], "complete": facts["complete"],
        "video_seconds": rows[0].get("video_seconds"),
        "started": at(start, rows[0].get("video_seconds")),
        "stakes": {key: money(stakes[key]) for key in
                   ("small_blind", "big_blind", "straddle_amount", "ante")
                   if stakes.get(key) is not None}
        | {"label": stakes_label(stakes), "sure": stakes["source"] != "unsure"},
        "seats": seats, "dealer": dealer, "dealer_source": (replay or {}).get(
            "dealer_source"), "straddler": straddler,
        "positions": {str(seat): place[0] for seat, place in
                      positions(page, seats, dealer, straddler).items()},
        "start_stacks": ({str(seat): money(value) for seat, value in stacks.items()}
                         or None),
        "first_stacks": {str(seat): value for seat, value in sorted(first.items())},
        "your_cards": (report.get("your_cards") or "").split() or None,
        "board": facts["board"],
        "actions": actions,
        "replay": {"status": (replay or {}).get("status"),
                   "reason": (replay or {}).get("reason"),
                   "steps": replayed(replay, actions),
                   "filled_in": len((replay or {}).get("inferred") or ())},
        "shown": {str(seat): item["cards"] for seat, item in shown.items()},
        "bomb_pot": None if bomb is None else money(bomb),
        "mushroom_pool": mushroom,
        "result": {"your_chips": report.get("your_chips"),
                   "bb": in_bb(report.get("your_chips"), stakes["big_blind"]),
                   "bb_luck_adjusted": luck_bb}}


# -- 3, 10. the cards that came up and their ranges --------------------------------

def last_shown(rows):
    """{seat: {"cards", "readings": [[cards, first frame], ...]}}: every pair
    each seat was read showing in the hand, in order; the last is the one
    kept."""
    seats = {}
    for row in rows:
        shown = row["fields"].get("shown_cards") or {}
        for seat, item in (shown.get("seats") or {}).items():
            cards = list(item.get("cards") or ())
            if len(cards) != 2:
                continue
            readings = seats.setdefault(int(seat), [])
            if not readings or readings[-1][0] != cards:
                readings.append([cards, item.get("frame", row["processed"])])
    return {seat: {"cards": readings[-1][0], "readings": readings}
            for seat, readings in seats.items()}


def street_moves(actions, facts):
    """{seat: {street: [(kind, all in)]}} with all-ins made calls, bets or
    raises by what the seat had in on the street against the most anyone
    had (the posts count before the flop), and raises before anyone bet
    after the flop made bets."""
    moves, put, top = {}, {}, {}
    opening = facts.get("opening_wagers") or {}
    for action in actions:
        street, seat, kind = action["street"], action["seat"], action["kind"]
        if street not in STREETS:
            continue
        if street not in put:
            put[street] = ({int(s): Decimal(v) for s, v in opening.items()}
                           if street == "preflop" else {})
            top[street] = max(put[street].values(), default=Decimal(0))
        chips = number(action["amount"]) or Decimal(0)
        level = put[street].get(seat, Decimal(0)) + chips
        all_in = kind == "all_in"
        if kind == "all_in":
            kind = "raise" if level > top[street] else "call"
        if kind == "raise" and street != "preflop" and not top[street]:
            kind = "bet"
        if kind in ("call", "raise", "bet"):
            put[street][seat] = level
            top[street] = max(top[street], level)
        moves.setdefault(seat, {}).setdefault(street, []).append((kind, all_in))
    return moves


def classify_preflop(actions_by_seat_order, bomb):
    """{seat: class} for the preflop actions in table order: (seat, kind,
    all in) each."""
    if bomb is not None:
        return {seat: "bomb" for seat, _, _ in actions_by_seat_order}
    last, raises = {}, 0
    for seat, kind, all_in in actions_by_seat_order:
        if kind == "raise":
            if all_in or raises >= 1:
                last[seat] = "all_in" if all_in and raises == 0 else "three_bet"
            else:
                last[seat] = "raise"
            raises += 1
        elif kind == "call":
            last[seat] = ("limp" if raises == 0 else
                          "call_raise" if raises == 1 else "call_three_bet")
    return last


def preflop_order(actions, facts):
    """(seat, kind, all in) of each preflop action in order (all-ins made
    calls or raises as ``street_moves`` does)."""
    moves = []
    put = {int(s): Decimal(v) for s, v in (facts.get("opening_wagers") or {}).items()}
    top = max(put.values(), default=Decimal(0))
    for action in actions:
        if action["street"] != "preflop":
            continue
        kind, seat = action["kind"], action["seat"]
        chips = number(action["amount"]) or Decimal(0)
        level = put.get(seat, Decimal(0)) + chips
        all_in = kind == "all_in"
        if all_in:
            kind = "raise" if level > top else "call"
        if kind in ("call", "raise"):
            put[seat] = level
            top = max(top, level)
        moves.append((seat, kind, all_in))
    return moves


def range_of(page, cls, place, moves, board, dead, cards):
    """The range section 4 gives a seat (preflop class, then cut once a
    street by its strongest action) and where ``cards`` sit in it, or
    (None, reason)."""
    import numpy as np
    if cls in (None, "bomb"):
        low, high = 0.0, 1.0
    elif cls == "raise":
        low, high = page.PREFLOP_RANGE[{"early": "raise_early", "late": "raise_late"}
                                       .get(place, "raise")]
    else:
        low, high = page.PREFLOP_RANGE["three_bet" if cls == "all_in" else cls]
    key = page.combo_key(tuple(cards))
    try:
        index = page.KEYS.index(key)
    except ValueError:
        return None, "cards_not_a_hand"
    if set(cards) & set(board) or set(cards) & set(dead):
        return None, "cards_clash_with_board_or_yours"
    percentile = float(page.PREFLOP_PLACE[index])
    weights = ((page.PREFLOP_PLACE > low) & (page.PREFLOP_PLACE <= high)
               & page.alive(dead)).astype(float)
    words = page._band_words(low, high)
    steps = []
    for street in STREETS[1:]:
        if len([card for card in board if card]) < BOARD_CARDS[street]:
            break
        strongest = None
        for kind, all_in in moves.get(street, ()):
            if kind in ("call", "bet", "raise") and (
                    strongest is None or ("call", "bet", "raise").index(kind)
                    > ("call", "bet", "raise").index(strongest[0])):
                strongest = (kind, all_in)
        if strongest is None:
            continue
        action = strongest[0]
        if street == "river" and action in ("bet", "raise") and strongest[1]:
            action = "all_in"
        share = page.KEEP[(action, street)]
        cut = board[:BOARD_CARDS[street]]
        strength = page.board_strength(cut)
        alive = weights * page.alive(cut)
        order = np.argsort(-strength, kind="stable")
        ordered = alive[order]
        total = ordered.sum()
        where = None
        if total > 0:
            places = np.empty(len(alive))
            places[order] = (np.cumsum(ordered) - ordered / 2) / total
            where = round(float(places[index]), 3)
        weights = page.keep_top(alive, strength, share)
        words += f"×{share:.0%}"
        steps.append({"street": street, "action": action, "keep": share,
                      "place": where, "in": bool(weights[index] > 0)})
    return {"class": cls, "band": [low, high], "words": words,
            "percentile": round(percentile, 4),
            "preflop_in": bool(low < percentile <= high),
            "in": bool(weights[index] > 0), "steps": steps}, None


def hand_ends(actions, facts):
    """(folded seats, seats still in at the end, whether one of them was all in)."""
    folded = {action["seat"] for action in actions if action["kind"] == "fold"}
    folded |= {seat for seat, state in facts["states"].items() if state == "folded"}
    live = [seat for seat in facts["seats"] if seat not in folded]
    all_in = any(action["kind"] == "all_in" and action["seat"] in live
                 for action in actions) or any(
        facts["states"].get(seat) == "all_in" for seat in live)
    return folded, live, all_in


def how_shown(seat, folded, live, all_in):
    if seat in folded or len(live) < 2:
        return "voluntary"          # after folding, or winning without a call
    return "allin_showdown" if all_in else "showdown"


def shown_block(name, rows, facts, replay, page, your_cards, finished=True):
    """(shown seats, {seat: (class, outcome)}) of one hand. A hand not seen
    from its start (``late``) or cut off by the end of the log
    (``unfinished``) calibrates nothing."""
    frames = video_at(rows)
    actions = history_actions(rows, frames)
    seats, dealer, straddler, bomb = table_of(facts, replay)
    places = positions(page, seats, dealer, straddler)
    classes = classify_preflop(preflop_order(actions, facts), bomb)
    moves = street_moves(actions, facts)
    folded, live, all_in = hand_ends(actions, facts)
    shown = last_shown(rows)
    dead = (your_cards or "").split()
    board = [card for card in facts["board"] if card]
    items = []
    for seat, item in sorted(shown.items()):
        if seat == HERO:
            continue
        how = how_shown(seat, folded, live, all_in)
        place = places.get(seat, (None, ""))[0]
        if page is None:
            reading, why = None, PLAIN_MISSING
        else:
            reading, why = range_of(page, classes.get(seat), place, moves.get(seat, {}),
                                    board, dead, item["cards"])
        corrected = len(item["readings"]) > 1
        items.append({
            "log": name, "hand_id": facts["hand_id"], "seat": seat,
            "cards": item["cards"], "readings": item["readings"],
            "corrected": corrected, "how": how, "position": place,
            "preflop_class": classes.get(seat),
            "actions": {street: [kind + ("（全下）" if all_in_ else "")
                                 for kind, all_in_ in found]
                        for street, found in moves.get(seat, {}).items()},
            "range": reading, "range_missing": why,
            "calibrates": (how in CALIBRATING and not corrected and reading is not None
                           and facts["complete"] is True)})
    outcomes = {}
    showing = {item["seat"]: item for item in items}
    for seat in seats:
        if seat == HERO:
            continue
        if facts["complete"] is not True:
            outcome = "late"
        elif seat in showing:
            outcome = ("corrected" if showing[seat]["corrected"]
                       else showing[seat]["how"])
        elif seat in folded:
            outcome = "folded"
        elif not finished:
            outcome = "unfinished"
        elif len(live) < 2:
            outcome = "won_uncontested"
        else:
            outcome = "mucked"
        outcomes[seat] = (classes.get(seat), outcome)
    return items, outcomes


def denominators(outcomes):
    """{class: {"seats", outcome: count}} over the session's opponent seats
    (``none``: put no chips in before the flop)."""
    table = {}
    for cls, outcome in outcomes:
        group = table.setdefault(cls or "none", Counter())
        group["seats"] += 1
        group[outcome] += 1
    order = [*CLASSES, "all_in", "bomb", "none"]
    return {cls: dict(table[cls]) for cls in order if cls in table}


# -- 2, 4, 6. your decisions -----------------------------------------------------------

def turns_of(pairs):
    """Consecutive (row, report) pairs with your buttons on screen."""
    turns, current = [], None
    for row, report in pairs:
        if not (row["fields"].get("hero_controls") or {}).get("visible"):
            current = None
            continue
        if current is None:
            current = []
            turns.append(current)
        current.append((row, report))
    return turns


def effective(fields, live_opponents):
    """(your stack, effective stack, opponents whose stack was not read):
    the smaller of yours and the deepest read opponent still in (section 1)."""
    stacks = fields.get("stacks") or {}
    mine = number(stacks.get(str(HERO)))
    read = [number(stacks.get(str(seat))) for seat in live_opponents]
    unread = [seat for seat, value in zip(live_opponents, read) if value is None]
    deepest = max((value for value in read if value is not None), default=None)
    if mine is None or deepest is None:
        return mine, None, unread
    return mine, min(mine, deepest), unread


def first_read(turn, pick):
    return next((value for value in (pick(row["fields"]) for row, _ in turn)
                 if value not in (None, "")), None)


def flop_spr(rows):
    """SPR at the flop (section 1): effective stack over the pot on the first
    flop frame that reads both, or None."""
    for row in rows:
        fields = row["fields"]
        if fields.get("street") != "flop":
            continue
        live = [int(seat) for seat, state in (fields.get("participants") or {}).items()
                if state in LIVE and int(seat) != HERO]
        pot = number(fields.get("pot"))
        _, eff, _ = effective(fields, live)
        if pot and eff is not None:
            return round(float(eff / pot), 2)
    return None


def advice_block(report, street):
    """The advice that showed: action, size, and what the one-page rules
    say about it (null for the older advice, which does not say)."""
    if not report:
        return None
    rows = report.get("advice") or [{}]
    first = rows[0]
    page = report.get("plain") or {}
    return {"kind": report.get("kind") or ("preflop" if street == "preflop"
                                           else "solver"),
            "action": first.get("action"), "to": first.get("to"),
            "chips": first.get("chips"),
            "reason": page.get("reason"), "rule": page.get("rule"),
            "rule_label": page.get("rule_label"), "hits": page.get("hits"),
            "range": page.get("range"), "equity": page.get("equity"),
            "need": page.get("need"), "flip": page.get("flip"),
            "tier": page.get("tier"),
            "share": (report.get("range_equity") or {}).get("value")}


def decision_rows(name, pairs, hand_id, facts, replay, page, start, results,
                  big_blind):
    rows = [row for row, _ in pairs]
    history = rows[-1]["fields"]["actions_v1"]
    keys = ("frame", "street", "slot", "kind", "amount", "source")
    actions = [dict(zip(keys, item)) for item in history["actions"]]
    seats, dealer, straddler, _ = table_of(facts, replay)
    places = positions(page, seats, dealer, straddler)
    spr = flop_spr(rows)
    pts = {row["processed"]: row["pts_seconds"] for row in rows}
    out = []
    for turn in turns_of(pairs):
        base = review_decision(name, hand_id, turn, actions)
        street = base["street"]
        first_row = turn[0][0]
        ready = [(row, report) for row, report in turn
                 if report.get("status") == "ready"]
        first_ready = ready[0] if ready else None
        last_ready = ready[-1] if ready else None
        live = [int(seat) for seat, state in
                (first_row["fields"].get("participants") or {}).items()
                if state in LIVE and int(seat) != HERO]
        mine = effective_stack = None
        unread = list(live)
        for row, _ in turn:
            mine, effective_stack, unread = effective(row["fields"], live)
            if effective_stack is not None:
                break
        done = next((item for item in actions if item["slot"] == HERO
                     and item["street"] == street
                     and item["frame"] >= first_row["processed"]), None)
        acted = None if done is None else pts.get(done["frame"])
        shown_at = None if first_ready is None else first_ready[0]["pts_seconds"]
        page_row = ((last_ready[1].get("plain") or {}) if last_ready else {})
        rule = page_row.get("rule")
        to_call = number(base["to_call"])
        pot = number(base["pot"])
        controls = [row["fields"].get("hero_controls") or {} for row, _ in turn]
        price_missing = all(c.get("call_amount") in (None, "") for c in controls
                            if c.get("button") not in ("check", None))
        changes = sum(one["action"] != two["action"]
                      for one, two in zip(base["answers"], base["answers"][1:]))
        out.append({
            "log": name, "hand_id": hand_id, "street": street,
            "video_seconds": base["video_seconds"],
            "wall_clock": at(start, base["video_seconds"]),
            "position": places.get(HERO, (None, ""))[0],
            "seat_name": places.get(HERO, (None, ""))[1] or None,
            "players": len(seats), "opponents": base["opponents"],
            "facing": fly.facing(rows, {"pts": base["pts"], "street": street,
                                        "button": base["button"],
                                        "to_call": base["to_call"]},
                                 number(big_blind)),
            "button": base["button"], "to_call": base["to_call"],
            "to_call_bb": in_bb(to_call, big_blind), "pot": base["pot"],
            "pot_bb": in_bb(pot, big_blind), "your_stack": money(mine),
            "effective": money(effective_stack),
            "effective_bb": in_bb(effective_stack, big_blind),
            "stacks_unread": unread,
            "spr_flop": spr if street != "preflop" else None,
            "hero": base["hero"], "board": base["board"],
            "advice": advice_block(last_ready[1] if last_ready else None, street),
            "answers": len(base["answers"]), "changes": changes,
            "seconds_to_advice": (None if first_ready is None else round(
                first_ready[0]["pts_seconds"] - first_row["pts_seconds"], 2)),
            "ready_waited": page_row.get("waited"),
            "ready_tag": page_row.get("tag"),
            "missing": page_row.get("missing"),
            "defaults": page_row.get("defaults"),
            "iron5": (None if not page_row else
                      rule in ("I5", "S1") or "I5" in (page_row.get("hits") or ())),
            "unspecified": page_row.get("unspecified"),
            "you_did": base["you_did"],
            "you_amount": None if done is None else done["amount"],
            "followed": base.get("followed"),
            "deviation_reason": None,       # the window has no place for it yet
            "acted_seconds": (None if acted is None else round(
                acted - first_row["pts_seconds"], 2)),
            "advice_before_action": (None if acted is None or not ready else
                                     shown_at <= acted),
            "price_missing": bool(controls) and price_missing and any(
                c.get("button") not in ("check", None) for c in controls),
            "pot_missing": base["pot"] in (None, ""),
            "flags": base["flags"],
            "hand_bb": results.get(hand_id, {}).get("bb"),
            "hand_bb_luck_adjusted": results.get(hand_id, {}).get("adjusted")})
    return out


def timing_block(decisions, summary):
    seconds = sorted(item["seconds_to_advice"] for item in decisions
                     if item["seconds_to_advice"] is not None)

    def quantile(share):
        return seconds[min(len(seconds) - 1, int(share * len(seconds)))]
    buckets = Counter()
    for value in seconds:
        bucket = next((f"≤{edge}s" for edge in BUCKETS if value <= edge),
                      f">{BUCKETS[-1]}s")
        buckets[bucket] += 1
    before = [item["advice_before_action"] for item in decisions
              if item["advice_before_action"] is not None]
    return {"decisions": len(decisions), "advised": len(seconds),
            "no_advice": len(decisions) - len(seconds),
            "seconds_to_advice": None if not seconds else {
                "median": quantile(0.5), "p90": quantile(0.9), "max": seconds[-1],
                "buckets": {bucket: buckets[bucket] for bucket in
                            [f"≤{edge}s" for edge in BUCKETS] + [f">{BUCKETS[-1]}s"]
                            if buckets[bucket]}},
            "changes_of_mind": sum(item["changes"] for item in decisions),
            "decisions_changed": sum(item["changes"] > 0 for item in decisions),
            "advice_before_action": [sum(before), len(before)],
            "stalls_over_2s": summary.get("stalls_over_2s")}


def misread_block(hands_report, decisions, shown, records):
    """The screen reading's misses, counted and listed."""
    items = []
    for hand in hands_report:
        if hand["your_cards_readings"] > 1:
            items.append(("your_cards_two_ways", hand))
        if hand["board_slots_with_two_readings"]:
            items.append(("board_two_ways", hand))
        for key in ("unexplained_pot_rises", "unrecorded_folds", "skipped_seats"):
            if hand[key]:
                items.append((key, hand))
    listed = [{"type": kind, "log": hand["log"], "hand_id": hand["hand_id"],
               "video_seconds": hand["video_seconds"]} for kind, hand in items]
    for item in decisions:
        for key in ("price_missing", "pot_missing"):
            if item[key]:
                listed.append({"type": key, "log": item["log"],
                               "hand_id": item["hand_id"],
                               "video_seconds": item["video_seconds"]})
        if item["stacks_unread"]:
            listed.append({"type": "opponent_stack_missing", "log": item["log"],
                           "hand_id": item["hand_id"],
                           "video_seconds": item["video_seconds"],
                           "seats": item["stacks_unread"]})
    for item in shown:
        if item["corrected"]:
            listed.append({"type": "shown_cards_corrected", "log": item["log"],
                           "hand_id": item["hand_id"], "seat": item["seat"],
                           "readings": item["readings"]})
    inferred = sum(action["inferred"] for record in records
                   for action in record["actions"])
    filled = sum(record["replay"]["filled_in"] for record in records)
    counts = Counter(item["type"] for item in listed)
    return {"counts": {**dict(counts.most_common()),
                       "actions_inferred_from_chips": inferred,
                       "actions_filled_in_by_replay": filled,
                       "actions": sum(len(record["actions"]) for record in records),
                       "hands": len(records), "decisions": len(decisions)},
            "items": listed}


# -- 7. versions -----------------------------------------------------------------------

def canonical(value):
    """A constant of the page as JSON that does not depend on set order."""
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in sorted(
            value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(canonical(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value if isinstance(value, (int, float, str, type(None))) else repr(value)


def page_numbers(page):
    """sha256 (16 hex) of every number, hand table and reading of the page
    (its upper-case constants): a rule's wording includes them."""
    numbers = {name: canonical(value) for name, value in sorted(vars(page).items())
               if name.isupper() and not name.startswith("_")
               and isinstance(value, (int, float, str, dict, list, tuple, set,
                                      frozenset))}
    return digest(json.dumps(numbers, ensure_ascii=False, sort_keys=True))


def versions(page, played):
    built = code_version()
    out = {"package": FORMAT, "built_with": built, "played_with": played}
    if page is None:
        out["page"] = None
    else:
        version = re.search(r"v\d+(?:\.\d+)*", page.__doc__ or "")
        numbers = page_numbers(page)
        out["page"] = {
            "version": version.group(0) if version else None,
            "numbers_sha256": numbers,
            # A rule's hash: its name and every number and table of the page
            # (one number changed: every rule counts as another rule, so no
            # two wordings are ever added up together).
            "rules": {rule: {"text": text, "sha256": digest(f"{text}\n{numbers}"),
                             "label_sha256": digest(text)}
                      for rule, text in page.RULES.items()},
            "unspecified": {case: {"text": text, "sha256": digest(text)}
                            for case, text in page.UNSPECIFIED.items()},
            "same_code_as_played": bool(
                played and built.get("commit") and played.get("commit")
                == built.get("commit"))}
    models = {}
    for name in MODELS:
        path = SCOREBOARD / name
        try:
            raw = path.read_bytes()
        except OSError:
            models[name] = None
            continue
        data = json.loads(raw)
        models[name] = {"sha256": hashlib.sha256(raw).hexdigest()[:16],
                        "schema_version": data.get("schema_version"),
                        "logs": len(data.get("logs") or ()) or None}
    out["opponent_models"] = models
    return out


# -- putting it together ---------------------------------------------------------------

def build(folder, *, rows=None, item=None, hands=None, settings=None):
    """The package of one recording folder (a dict)."""
    folder = Path(folder)
    if rows is None:
        rows = fly.load(folder / "frames.jsonl")
    rows = [row for row in rows if row.get("fields")]
    name = folder.name
    meta = read_json(folder / "recording.json") or {}
    sheet = folder / fly.FOLDER
    if item is None or hands is None:
        item = read_json(sheet / "summary.json")
        hands = read_json(sheet / "hands.json")
    if item is None or hands is None:
        summary, hands = fly.session_hands(name, rows)
        item = fly.session_summary(name, fly.code_of(folder, rows), summary, hands)
    page = plain_policy()
    nulls = {}
    report = session_report([(name, rows)])
    code = item.get("code") or fly.code_of(folder, rows)
    try:
        luck, adjusted, runouts = luck_summary(name, rows, code, report)
    except Exception as exc:            # noqa: BLE001 - the rest stands without it
        luck, adjusted, runouts = None, {}, {}
        nulls["session.luck_adjusted"] = f"扣运气没算成：{exc}"
    results = {hand["hand_id"]: {"bb": hand["bb"], "adjusted": adjusted.get(
        hand["hand_id"])} for hand in hands}
    machine, player, player_from = who(folder, settings)
    spectate = not item.get("your_hands") and not item.get("decisions")
    start = wall_clock(meta)
    by_hand = {hand["hand_id"]: hand for hand in report["hands"]}
    grouped = {}
    for row in rows:
        history = row["fields"].get("actions_v1")
        if history and row["fields"].get("scene_supported"):
            grouped.setdefault(history["hand_id"], []).append((row, _advice(row)))
    stakes, earlier = {}, None
    decisions, shown, outcomes, records, shadowed = [], [], [], [], []
    chips = {hand["hand_id"]: hand.get("chips") for hand in hands}
    last = list(grouped)[-1] if grouped else None
    for hand_id, pairs in grouped.items():
        hand_rows = [row for row, _ in pairs]
        facts = hand_facts(hand_rows, earlier)
        if facts["stakes"]["source"] == "table":
            earlier = facts["stakes"]
        stakes[hand_id] = facts["stakes"]
        try:
            replay = replay_hand(facts) if facts["complete"] else None
        except Exception:               # noqa: BLE001 - a hand that does not replay
            replay = None
        hand = by_hand.get(hand_id)
        your_cards = (hand or {}).get("your_cards")
        records.append(hand_record(name, hand_rows, facts, replay, hand, start, page,
                                   results.get(hand_id, {}).get("adjusted")))
        found, ends = shown_block(name, hand_rows, facts, replay, page, your_cards,
                                  finished=hand_id != last)
        shown += found
        outcomes += list(ends.values())
        mine = decision_rows(name, pairs, hand_id, facts, replay, page, start,
                             results, facts["stakes"]["big_blind"])
        decisions += mine
        shadowed.append({"hand_id": hand_id, "rows": hand_rows,
                         "turns": turns_of(pairs), "decisions": mine,
                         "stakes": facts["stakes"], "chips": chips.get(hand_id),
                         "start": stack(hand_rows), "luck": runouts.get(hand_id)})
    if page is None:
        nulls.update({"versions.page": PLAIN_MISSING,
                      "decisions.position": PLAIN_MISSING,
                      "shown.range": PLAIN_MISSING})
    if not any(item_.get("advice") and item_["advice"]["rule"]
               for item_ in decisions):
        nulls["decisions.advice.rule/reason/range/equity/need/flip/iron5/"
              "unspecified/ready"] = ("这一场的建议不是一页纸打法（plain）出的：旧建议"
                                      "不带规则编号、理由句、三个数和翻转条件")
    rules = item.get("rules")
    rule_hits = None
    if rules is not None:
        rule_hits = {"rules": rules, "unspecified": item.get("unspecified") or {},
                     "from": "flywheel/summary.json（体检单的规则命中统计）"}
    else:
        nulls["rule_hits"] = ("体检单没有规则命中统计：这一场没有一页纸打法的建议，"
                              "或写体检单的代码还没有这一栏")
    nulls["identity.table"] = "识别不读桌号"
    nulls["identity.opponents"] = "识别不读对手昵称，没有可以做哈希的东西"
    nulls["decisions.deviation_reason"] = "窗口还没有记你不照建议时理由的地方"
    version_info = versions(page, code)
    try:
        shadow = session_shadow.block(
            rows, shadowed, code=version_info["built_with"],
            page_version=(version_info["page"] or {}).get("version"))
    except Exception as exc:            # noqa: BLE001 - the rest stands without it
        shadow = None
        nulls["shadow"] = f"影子重放没做成：{type(exc).__name__}: {exc}"
    return {
        "schema": "pokersense.session_package", "format": FORMAT,
        "built": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session": session_block(folder, meta, item, luck, machine, spectate),
        "identity": {"player": player, "player_from": player_from,
                     "machine": machine, "table": None,
                     "hands": [record["hand_id"] for record in records],
                     "opponents": None},
        "decisions": decisions,
        "shown": shown,
        "shown_denominators": denominators(outcomes),
        "misreads": misread_block(report["hands"], decisions, shown, records),
        "rule_hits": rule_hits,
        "timing": timing_block(decisions, item),
        "versions": version_info,
        "hands": records,
        "shadow": shadow,
        "nulls": nulls}


def write(folder, package):
    """``flywheel/package.json`` of the folder, written whole or not at all."""
    out = Path(folder) / fly.FOLDER / FILE
    aa_upload.write_json(out, package)
    return out


def make(folder, **known):
    return write(folder, build(folder, **known))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recording", type=Path, action="append", required=True)
    parser.add_argument("--with-sheet", action="store_true",
                        help="先写体检单（flywheel_session.py report），再写场次包")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--no-ledger", action="store_true")
    args = parser.parse_args(argv)
    if args.with_sheet and hasattr(os, "nice"):
        os.nice(10)                 # runs beside the window: stay out of its way
    ledger = None if args.no_ledger else (args.ledger or fly.default_ledger())
    failed = 0
    for folder in args.recording:
        if args.with_sheet:
            print("\n".join(fly.report(folder, ledger)))
        try:
            path = make(folder)
        except Exception as exc:    # noqa: BLE001 - the sheet is there anyway
            failed += 1
            print(f"{folder}：场次包没做成：{type(exc).__name__}: {exc}")
            continue
        package = json.loads(path.read_text(encoding="utf-8"))
        session = package["session"]
        print(f"{path}：{session['hands']} 手，你的决策 {session['decisions']} 次，"
              f"亮牌 {len(package['shown'])} 个，{path.stat().st_size / 1e3:.0f} KB")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
