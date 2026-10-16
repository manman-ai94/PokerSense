"""Replay real hands with the 大道至简 rule next to the window's advice.

The challenger (``scoreboard.simple``) is not wired into the live window.
This works out, from the window's own logs (``frames.jsonl``), what it
would have said at every one of your turns, next to what the window (this
checkout's ``AASolverAdvice``) says there, and prices both where the
opponents still in showed their cards (``aa_compare_advice.shown_spot``:
your share of the pot against the cards shown on the board of that moment;
a fold 0, a check or call that share of the pot after calling less the
call, a bet or raise the same with every opponent still in calling it).

Your turn is the frames with your buttons on screen, as the window's
(``aa_compare_advice.turns``); both answers are taken at its last frame.
The rule reads the hand replayed on the AA table where the window can
(``solver_observation``, ``source`` "table"), and otherwise the screen
alone (``source`` "screen": the actions read, the pot, your button), as the
window's rough rule does; so it answers wherever your cards and the board
are read.

A heads-up turn or river is solved with TexasSolver when ``--solver`` is
given (it must be installed); without it the solve gives up at once and the
window shows its range rule there, as it does when a solve runs out of time.

    PYTHONPATH=src:. .venv/bin/python tools/simple_replay.py \\
        --frames <recording>/frames.jsonl [...] [--solver] \\
        [--lines <private folder>] [--out summary.json]

``--lines`` writes every decision (cards, board, both answers, the shown
cards) to the private folder; only totals go to ``--out``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poker_engine.desktop.aa_solver_advice import (  # noqa: E402
    BOARD_CARDS, HERO, IN_HAND, AASolverAdvice, _decimal, open_level, pot_on_screen,
    put_in, rough_winnable)
from poker_engine.desktop.aa_solver_input import (  # noqa: E402
    bomb_post, hand_facts, solver_observation)
from poker_engine.scoreboard import simple  # noqa: E402
from poker_engine.scoreboard.spots import preflop_spot  # noqa: E402
from poker_engine.solver.texassolver import SolverTimeout  # noqa: E402
from tools import flywheel_session as fly  # noqa: E402
from tools import luck_results  # noqa: E402
from tools.aa_compare_advice import answer, chips, shown_spot, turns  # noqa: E402
from tools.aa_session_report import _Now, load, number, plain, stack  # noqa: E402
from tools.aa_strategy_review import mode  # noqa: E402

AGGRESSIVE = ("raise", "bet", "all_in", "allin")
WENT_ON = ("call", "raise")      # what you did, plainly: you put chips in
STREETS = ("preflop", "flop", "turn", "river")
BIG_LOSS = 50.0         # big blinds: a big pot lost (after the all-in luck)
MUSHROOM_BB = Decimal(3)    # the dealer's mushroom post (蘑菇:3BB)


class GiveUp:
    """Stands in for TexasSolver: every solve runs out of time, so the window
    shows its range rule (as when a solve takes longer than your turn)."""

    def solved_spot(self, observation, salt):
        raise SolverTimeout("no solver in this replay")


# -- the screen alone ----------------------------------------------------------

def screen_moves(facts, hero=HERO):
    """(``simple.Move`` for every action read but yours, [(seat, kind)] before
    the flop with yours, {street: the seat that bet or raised last}) from the
    action history alone."""
    stakes = facts.get("stakes") or {}
    pots = facts.get("street_pots") or {}
    seats = list(facts.get("seats") or ())
    folded, moves, preflop_actions = set(), [], []
    raiser, street, pot = None, None, Decimal(0)
    bets, top, raises, last = {}, Decimal(0), 0, {}
    board = list(facts.get("board") or ())
    for action in facts.get("actions") or ():
        seat, kind = action["slot"], str(action["kind"]).lower()
        if action["street"] != street:
            street = action["street"]
            begun = (pots.get(street) or (None, None))[0]
            pot = begun if begun is not None else pot
            if street == "preflop":
                bets = {int(seat): Decimal(value) for seat, value in
                        (facts.get("opening_wagers") or {}).items()}
                top = max([open_level(stakes) if stakes else Decimal(0),
                           *bets.values()], default=Decimal(0))
            else:
                bets, top = {}, Decimal(0)
            raises = 0
        amount = _decimal(action.get("amount"))
        mine = bets.get(seat, Decimal(0))
        to_call = max(Decimal(0), top - mine)
        live = len([s for s in seats if s not in folded]) - 1
        if (seat == hero and street != "preflop" and kind not in AGGRESSIVE
                and kind != "fold" and amount is not None and amount > to_call
                and (to_call == 0 or amount >= 2 * to_call)):
            # You called a bet or raise that was not read: read it the way
            # it would be, by every opponent still in (the careful side).
            facing = ("checked_to", "facing_bet", "facing_raise")[min(raises, 2)]
            size = float(mine + amount) / max(float(pot), 1e-9)
            moves += [simple.Move(other, street, "r", facing,
                                  "hu" if live == 1 else "multi", "other", size,
                                  board=tuple(board[:BOARD_CARDS.get(street, 0)]))
                      for other in seats if other != hero and other not in folded]
            raises += 1
            last[street] = None
            pot += mine + amount
            top = mine + amount
            to_call = amount
        if kind == "fold":
            letter = "f"
        elif kind in AGGRESSIVE and amount is not None and mine + amount > top:
            letter = "r"
        else:
            letter = "c"
        cards = BOARD_CARDS.get(street, 0)
        if street == "preflop":
            spot = preflop_spot(preflop_actions, seat)
            preflop_actions.append((seat, letter))
            if seat != hero:
                moves.append(simple.Move(seat, street, letter, spot,
                                         free=letter == "c" and to_call == 0))
        elif seat != hero:
            facing = ("checked_to", "facing_bet", "facing_raise")[min(raises, 2)]
            if letter == "r":
                size = float(amount) / max(float(pot), 1e-9)
            else:
                size = (float(to_call) / max(float(pot - to_call), 1e-9)
                        if to_call else 0.0)
            moves.append(simple.Move(seat, street, letter, facing,
                                     "hu" if live == 1 else "multi",
                                     "pfa" if seat == raiser else "other", size,
                                     letter == "c" and to_call == 0,
                                     tuple(board[:cards])))
        if letter == "r":
            raises += 1
            last[street] = seat
            if street == "preflop":
                raiser = seat
        if letter == "f":
            folded.add(seat)
        if amount is not None:
            bets[seat] = mine + amount
            top = max(top, bets[seat])
            pot += amount
    return moves, preflop_actions, last


def missed_raise(moves, opponents, wagers, mine, to_call, pot, board, street):
    """The bet or raise you face when it was not read (a slow machine misses
    actions): read the way it would be, by the opponents whose bet matches
    it on screen, else by every opponent whose bet was not read (the
    careful side). Its size from your price: it put in your bet and the
    call over the pot before it."""
    top = mine + to_call
    seen = [seat for seat in opponents if wagers.get(str(seat)) == top]
    if not seen:
        seen = [seat for seat in opponents if not wagers.get(str(seat))]
    raised = any(move.street == street and move.kind == "r" for move in moves)
    facing = ("facing_raise" if raised else "facing_bet" if mine > 0
              else "checked_to")
    size = float(top) / max(float(pot - top), 1e-9)
    return [simple.Move(seat, street, "r", facing,
                        "hu" if len(opponents) == 1 else "multi", "other", size,
                        board=board) for seat in seen]


def _order(seats, dealer, seat):
    """Where ``seat`` acts after the flop (0 first); None without the dealer."""
    if dealer not in seats:
        return None
    start = seats.index(dealer)
    clockwise = seats[start:] + seats[:start]
    return (clockwise.index(seat) - 1) % len(clockwise)


def screen_spot(fields, rows, facts, cards, street, stakes):
    """A ``simple.Spot`` from the screen alone, or (None, why)."""
    # The frame that ends your turn can show the next card already, or none:
    # the cards of your street, from the hand's board if this frame missed them.
    count = BOARD_CARDS.get(street, -1)
    board = tuple(card for card in fields.get("board") or () if card)
    if len(board) < count:
        board = tuple(card for card in facts.get("board") or () if card)
    board = board[:count]
    if len(board) != count:
        return None, "board_unread"
    seats = fields.get("participants") or {}
    opponents = tuple(sorted(int(seat) for seat, state in seats.items()
                             if seat != str(HERO) and state in IN_HAND))
    if not opponents:
        return None, "no_opponent_read"
    pot = _decimal(fields.get("pot"))
    if pot is None:
        pot = pot_on_screen(fields, rows)
    if pot is None:
        return None, "pot_unread"
    wagers = {seat: _decimal(value) or Decimal(0)
              for seat, value in (fields.get("street_wagers") or {}).items()}
    for seat, put in put_in(fields, street).items():
        wagers[seat] = max(wagers.get(seat, Decimal(0)), put)
    mine = wagers.get(str(HERO), Decimal(0))
    top = max([mine, *(wagers.get(str(seat), Decimal(0)) for seat in opponents)])
    controls = fields.get("hero_controls") or {}
    if controls.get("button") == "check":
        to_call = Decimal(0)
    else:
        to_call = _decimal(controls.get("call_amount"))
        if to_call is None and top > mine:
            to_call = top - mine
        if to_call is None:
            return None, "price_unread"
    stack = _decimal((fields.get("stacks") or {}).get(str(HERO)))
    if stack is None:
        stack = Decimal(10 ** 6)
    if 0 < stack <= to_call:
        to_call = stack
    price = 0.0
    if to_call > 0:
        price = float(to_call / rough_winnable(wagers, mine, pot, to_call, stakes))
    moves, preflop_actions, last = screen_moves(facts)
    moves = [move for move in moves if move.seat in opponents or move.kind == "f"]
    if to_call > 0 and street != "preflop" and last.get(street) in (None, HERO):
        moves += missed_raise(moves, opponents, wagers, mine, to_call, pot, board,
                              street)
    acted = {seat for seat, _ in preflop_actions}
    big_blind = float(Decimal((stakes or {}).get("big_blind") or 2))
    stacks = {int(seat): _decimal(value) for seat, value in
              (fields.get("stacks") or {}).items() if _decimal(value) is not None}
    reach = [float(stacks[seat] + wagers.get(str(seat), Decimal(0)))
             for seat in opponents if seat in stacks]
    effective = min(float(stack + mine), max(reach, default=float(stack + mine)))
    all_seats = sorted(set(facts.get("seats") or ()) | set(opponents) | {HERO})
    dealer = facts.get("dealer") if facts.get("dealer") in all_seats else facts.get(
        "blind_dealer")
    mine_at = _order(all_seats, dealer, HERO)
    in_position = mine_at is not None and all(
        (_order(all_seats, dealer, seat) or 0) < mine_at for seat in opponents)
    spot = simple.Spot(
        hero=tuple(cards), board=board, street=street, opponents=opponents,
        moves=tuple(moves), pot=float(pot), to_call=float(to_call), stack=float(stack),
        bet=float(mine), top=float(top), big_blind=big_blind, price=price,
        all_in=tuple(seat for seat in opponents if stacks.get(seat) == 0),
        posted=tuple(seat for seat in opponents if wagers.get(str(seat), 0) > 0),
        can_raise=stack > to_call, max_raise_to=float(stack + mine),
        preflop_spot=preflop_spot(preflop_actions, HERO),
        raises=sum(kind == "r" for _, kind in preflop_actions),
        behind=sum(seat not in acted for seat in opponents),
        in_position=in_position,
        effective_bb=effective / big_blind if big_blind else 100.0,
        bomb=bomb_post(facts) is not None,
        seed=sum(map(ord, "".join(cards) + "".join(board))) + len(moves))
    return spot, None


# -- what a fold would have kept -----------------------------------------------

def final_stacks(rows):
    """{hand id: (your chips at its start, once it was over)}. The start is
    ``aa_session_report.stack`` (read after the antes and blinds); the end is
    the next hand's start plus what you posted for it, or 0 after a bust
    (your last stack read 0 and the next hand dealt you no cards or read no
    stack, or the log ended), as ``luck_results`` counts it; None when not
    known. A hand that goes on with your same two cards (split in two) is
    one hand, from the first part's start."""
    grouped = fly.by_hand(rows)
    stakes = fly.hand_stakes(grouped)
    ids = list(grouped)
    cards = {hand_id: mode(" ".join(row["fields"]["hero"]) for row in part
                           if row["fields"].get("hero") and all(row["fields"]["hero"]))
             for hand_id, part in grouped.items()}
    found, begin = {}, None
    for index, hand_id in enumerate(ids):
        before = ids[index - 1] if index else None
        if not (before and cards[hand_id] and cards[hand_id] == cards[before]):
            begin = stack(grouped[hand_id])
        later = next((other for other in ids[index + 1:]
                      if not (cards[other] and cards[other] == cards[hand_id])), None)
        start = stack(grouped[later]) if later is not None else None
        readings = [number((row["fields"].get("stacks") or {}).get(str(HERO)))
                    for row in grouped[hand_id]]
        last = next((value for value in reversed(readings) if value is not None), None)
        if last == 0 and (later is None or not start or not cards[later]):
            found[hand_id] = (begin, 0.0)
            continue
        if later is None or not start:
            found[hand_id] = (begin, None)
            continue
        found[hand_id] = (begin, float(Decimal(str(start)) + posted(
            hand_facts(grouped[later], stakes[later]))))
    return found


def posted(facts, seat=HERO):
    """What ``seat`` put in before a hand's first action: the bomb pot's post,
    or the ante, the blind or straddle of its place (as read, else from the
    dealer) and the mushroom post (蘑菇: the dealer's 3 big blinds, four
    players or more)."""
    bomb = bomb_post(facts)
    if bomb is not None:
        return bomb
    stakes = facts.get("stakes") or {}
    total = Decimal(stakes.get("ante") or 0)
    seats = list(facts.get("seats") or ())
    dealer = facts.get("dealer")
    if dealer not in seats:
        dealer = facts.get("blind_dealer")
    wagers = facts.get("opening_wagers") or {}
    if seat in wagers:
        total += Decimal(wagers[seat])
    elif dealer in seats and seat in seats:
        after = (seats.index(seat) - seats.index(dealer)) % len(seats)
        blinds = (stakes.get("small_blind"), stakes.get("big_blind"),
                  stakes.get("straddle_amount"))
        if 1 <= after <= 3 and blinds[after - 1]:
            total += Decimal(blinds[after - 1])
    if dealer == seat and len(seats) >= 4 and stakes.get("big_blind"):
        total += MUSHROOM_BB * Decimal(stakes["big_blind"])
    return total


def results(name, rows):
    """{hand id: (your result in big blinds, all-in luck in big blinds)} as
    ``luck_results`` counts them (the luck is used here)."""
    lines, _ = luck_results.hand_lines(name, rows)
    return {line["hand_id"]: (line["bb"], line["runout_luck"] or 0.0) for line in lines}


# -- one turn ------------------------------------------------------------------

def simple_answer(rows, fields, cards, street, stakes):
    """(``simple.Advice``, source, why): the rule's answer at this frame."""
    facts = hand_facts(rows, stakes)
    try:
        observation, reason = solver_observation(facts, HERO, cards)
    except Exception as error:                # as the window: the screen answers
        observation, reason = None, f"table_failed:{type(error).__name__}"
    if observation is not None and observation["street"] == street:
        pot = _decimal(fields.get("pot"))
        if pot is not None and pot > Decimal(observation["pot"]):
            observation = {**observation, "pot": str(pot)}
        pool = _decimal(fields.get("mushroom_pool"))
        if pool is not None and pool > 0:
            observation = {**observation, "mushroom_pool": str(pool)}
        try:
            spot = simple.spot_from_observation(observation)
            return simple.decide(spot), "table", None
        except Exception as error:            # the screen still answers
            reason = f"table_failed:{type(error).__name__}"
    spot, why = screen_spot(fields, rows, facts, cards, street, facts.get("stakes"))
    if spot is None:
        return None, None, why or reason
    return simple.decide(spot), "screen", reason


def priced(item, observation, share):
    """``aa_compare_advice.chips`` for an answer (a bet priced as a raise)."""
    if not item or not item.get("action"):
        return None
    action = {"bet": "raise"}.get(item["action"], item["action"])
    return chips({**item, "action": action}, observation, share)


def turn_key(item, before):
    """(hand id, street, how many turns on that street of that hand come
    before it in ``before``: earlier items, or keys already made)."""
    if isinstance(before, dict):
        count = sum(key[:2] == (item["hand_id"], item["street"]) for key in before)
    else:
        count = sum((other["hand_id"], other["street"])
                    == (item["hand_id"], item["street"]) for other in before)
    return item["hand_id"], item["street"], count


def replay_log(name, rows, solver=False, cached=None):
    """Every one of your turns in one log: the window's and the rule's answers.
    ``cached``: the window's answers from an earlier run of this log
    ({(hand id, street, n-th turn on it): answer}), used instead of its own
    (the window still follows the log, without solving)."""
    rows = [row for row in rows if row.get("fields")]
    found = turns(rows)
    finals = final_stacks(rows)
    outcome = results(name, rows)
    last = {indexes[-1]: indexes for indexes in found}
    now = [0.0]
    window = AASolverAdvice(None if solver else GiveUp(), _Now(), clock=lambda: now[0])
    reports, items = [], []
    final = {}
    for row in rows:
        history = row["fields"].get("actions_v1")
        if history and history.get("hand_id") is not None:
            final[history["hand_id"]] = history
    for index, row in enumerate(rows):
        now[0] = row.get("pts_seconds") or now[0]
        reports.append(window.observe_fields(row["fields"], row["processed"]))
        if index not in last:
            continue
        indexes = last[index]
        fields = row["fields"]
        street = mode(rows[i]["fields"].get("street") for i in indexes)
        hero = mode(" ".join(rows[i]["fields"]["hero"]) for i in indexes
                    if rows[i]["fields"].get("hero") and all(rows[i]["fields"]["hero"]))
        hand_id = fields["actions_v1"]["hand_id"]
        item = {"log": name, "hand_id": hand_id, "street": street, "hero": hero,
                "board": " ".join(card for card in fields.get("board") or () if card),
                "pot": fields.get("pot"),
                "to_call": (fields.get("hero_controls") or {}).get("call_amount"),
                "button": (fields.get("hero_controls") or {}).get("button"),
                "video_seconds": rows[indexes[0]].get("video_seconds")}
        ready = [answer(reports[i], street) for i in indexes
                 if reports[i].get("status") == "ready"]
        item["window"] = ready[-1] if ready else None
        if cached is not None:
            key = turn_key(item, items)
            item["window"] = cached.get(key, item["window"])
        if hero and street in STREETS:
            try:
                advice, source, why = simple_answer(
                    list(window._rows), fields, hero.split(), street, window._stakes)
            except Exception as error:
                advice, source, why = None, None, f"failed:{type(error).__name__}"
        else:
            advice, source, why = None, None, "cards_unread" if not hero else "street"
        item["simple"] = None if advice is None else {**advice.row(), "source": source}
        item["simple_why"] = why
        start = rows[indexes[0]]["processed"]
        keys = ("frame", "street", "slot", "kind", "amount", "source")
        actions = (final.get(hand_id) or {}).get("actions", [])
        done = next((dict(zip(keys, a)) for a in actions
                     if str(a[2]) == str(HERO) and a[1] == street and a[0] >= start),
                    None)
        item["you_did"] = None if done is None else plain(done["kind"])
        if done is not None and done["kind"] in AGGRESSIVE and done.get("amount"):
            item["you_put"] = done["amount"]
        now_stack = number(mode((rows[i]["fields"].get("stacks") or {}).get(str(HERO))
                                for i in indexes))
        item["stack"] = now_stack
        begin, ended = finals.get(hand_id) or (None, None)
        luck = (outcome.get(hand_id) or (None, 0.0))[1]
        big_blind = float((window.stakes() or {}).get("big_blind") or 2)
        if now_stack is not None and ended is not None:
            # Folding here keeps what you have now; the hand ended with
            # ``ended`` (less the all-in luck, as the results count it).
            item["fold_keeps_bb"] = round((now_stack - ended) / big_blind + luck, 2)
        if begin is not None and ended is not None:
            item["hand_bb"] = round((ended - begin) / big_blind, 2)
            item["hand_luck_bb"] = luck
        spot = shown_spot(rows, indexes, hand_id)
        if spot is not None:
            observation, share, cards = spot
            item["shown"] = {
                "cards": cards, "share": round(share, 3), "big_blind": big_blind,
                "window": priced(item["window"], observation, share),
                "simple": priced(item["simple"], observation, share)}
        items.append(item)
    return items


# -- the summary ---------------------------------------------------------------

def _act(item, key):
    found = item.get(key) or {}
    return found.get("action")


def summarize(items, hands=None):
    """Totals only: coverage, where the answers differ, the shown-card value."""
    turns_all = len(items)
    read = [item for item in items if item["hero"]]
    summary = {
        "turns": turns_all, "cards_read": len(read),
        "window_answered": sum(bool(item["window"]) for item in read),
        "simple_answered": sum(bool(item["simple"]) for item in read),
        "simple_by_source": dict(Counter((item["simple"] or {}).get("source")
                                         for item in read if item["simple"])),
        "simple_missing": dict(Counter(item["simple_why"] for item in read
                                       if not item["simple"])),
        "window_by_kind": dict(Counter((item["window"] or {}).get("kind")
                                       for item in read if item["window"])),
    }
    both = [item for item in read if item["window"] and item["simple"]]
    summary["both_answered"] = len(both)
    summary["same_action"] = sum(_act(item, "window") == _act(item, "simple")
                                 for item in both)
    summary["pairs"] = {f"{w}->{s}": n for (w, s), n in Counter(
        (_act(item, "window"), _act(item, "simple")) for item in both).most_common()}
    by_street = {}
    for street in STREETS:
        part = [item for item in both if item["street"] == street]
        by_street[street] = {"decisions": len(part),
                             "same": sum(_act(item, "window") == _act(item, "simple")
                                         for item in part)}
    summary["by_street"] = by_street
    priced_items = [item for item in both if item.get("shown")
                    and item["shown"]["window"] is not None
                    and item["shown"]["simple"] is not None]
    differ = [item for item in priced_items
              if _act(item, "window") != _act(item, "simple")
              or (item["window"] or {}).get("to") != (item["simple"] or {}).get("to")]
    gain = [(item["shown"]["simple"] - item["shown"]["window"])
            / item["shown"]["big_blind"] for item in differ]
    summary["shown"] = {
        "priced": len(priced_items), "differ": len(differ),
        "simple_better": sum(value > 0.01 for value in gain),
        "simple_worse": sum(value < -0.01 for value in gain),
        "simple_minus_window_bb": round(sum(gain), 1),
        "by_street": {street: round(sum(
            g for g, item in zip(gain, differ) if item["street"] == street), 1)
            for street in STREETS}}
    summary["folds"] = {key: fold_value(read, key) for key in ("window", "simple")}
    # The check on that sum: where you folded, folding keeps what you had.
    yours = [item["fold_keeps_bb"] for item in read if item.get("you_did") == "fold"
             and item.get("fold_keeps_bb") is not None]
    summary["fold_check"] = {"your_folds": len(yours),
                             "exact": sum(abs(value) < 0.5 for value in yours),
                             "sum_bb": round(sum(yours), 1)}
    summary["big_losses"] = big_losses(read)
    if hands is not None:
        summary["hands"] = hands
    return summary


def _first_folds(items, key):
    """Per hand, the first turn where ``key`` said fold to a bet and you put
    chips in."""
    found = {}
    for item in items:
        if (_act(item, key) == "fold" and item.get("you_did") in WENT_ON
                and item.get("button") != "check"
                and item.get("fold_keeps_bb") is not None):
            found.setdefault((item["log"], item["hand_id"]), item)
    return found


def fold_value(items, key):
    """What following ``key``'s folds would have kept, in big blinds: at the
    first turn of each hand where it said fold and you went on, the chips you
    had then against how the hand ended (less the all-in luck)."""
    values = [item["fold_keeps_bb"] for item in _first_folds(items, key).values()]
    return {"hands": len(values), "kept_bb": round(sum(values), 1),
            "saved": sum(value > 0.5 for value in values),
            "cost": sum(value < -0.5 for value in values)}


def big_losses(items, line=BIG_LOSS):
    """The hands you lost at least ``line`` big blinds in (after the all-in
    luck): how many each rule folds before the end, and what that keeps."""
    hands = {}
    for item in items:
        if item.get("hand_bb") is not None:
            hands.setdefault((item["log"], item["hand_id"]),
                             item["hand_bb"] - item.get("hand_luck_bb", 0.0))
    lost = {key for key, value in hands.items() if value <= -line}
    part = [item for item in items if (item["log"], item["hand_id"]) in lost]
    found = {"hands": len(lost),
             "lost_bb": round(sum(hands[key] for key in lost), 1)}
    for key in ("window", "simple"):
        folds = _first_folds(part, key)
        found[key] = {"folds_in": len(folds), "kept_bb": round(sum(
            item["fold_keeps_bb"] for item in folds.values()), 1)}
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", default=[])
    parser.add_argument("--solver", action="store_true",
                        help="solve heads-up turns and rivers with TexasSolver")
    parser.add_argument("--lines", type=Path,
                        help="private folder for every decision")
    parser.add_argument("--window", type=Path,
                        help="a folder of earlier --lines: the window's answers "
                             "from there where the log is in it (no solving)")
    parser.add_argument("--out", type=Path, help="summary (totals only)")
    args = parser.parse_args(argv)
    if not args.frames:
        parser.error("give --frames")
    items = []
    for path in args.frames:
        name = path.parent.name
        cached = None
        earlier = args.window / f"{name}.jsonl" if args.window else None
        if earlier is not None and earlier.exists():
            cached = {}
            for item in map(json.loads, earlier.open(encoding="utf-8")):
                cached[turn_key(item, cached)] = item.get("window")
        found = replay_log(name, load(path), solver=args.solver and cached is None,
                           cached=cached)
        items += found
        print(f"{name}: {len(found)} turns", flush=True)
        if args.lines:
            args.lines.mkdir(parents=True, exist_ok=True)
            (args.lines / f"{name}.jsonl").write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in found),
                encoding="utf-8")
    summary = summarize(items)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out:
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                            encoding="utf-8")


if __name__ == "__main__":
    main()
