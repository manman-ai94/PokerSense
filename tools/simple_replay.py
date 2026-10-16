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
from tools.aa_compare_advice import answer, chips, shown_spot, turns  # noqa: E402
from tools.aa_session_report import _Now, load, plain  # noqa: E402
from tools.aa_strategy_review import mode  # noqa: E402

AGGRESSIVE = ("raise", "bet", "all_in", "allin")
STREETS = ("preflop", "flop", "turn", "river")


class GiveUp:
    """Stands in for TexasSolver: every solve runs out of time, so the window
    shows its range rule (as when a solve takes longer than your turn)."""

    def solved_spot(self, observation, salt):
        raise SolverTimeout("no solver in this replay")


# -- the screen alone ----------------------------------------------------------

def screen_moves(facts, hero=HERO):
    """(``simple.Move`` for every action read but yours, [(seat, kind)] before
    the flop with yours) from the action history alone."""
    stakes = facts.get("stakes") or {}
    pots = facts.get("street_pots") or {}
    seats = list(facts.get("seats") or ())
    folded, moves, preflop_actions = set(), [], []
    raiser, street, pot = None, None, Decimal(0)
    bets, top, raises = {}, Decimal(0), 0
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
        if kind == "fold":
            letter = "f"
        elif kind in AGGRESSIVE and amount is not None and mine + amount > top:
            letter = "r"
        else:
            letter = "c"
        cards = BOARD_CARDS.get(street, 0)
        live = len([s for s in seats if s not in folded]) - 1
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
                size = float(to_call) / max(float(pot - to_call), 1e-9) if to_call else 0.0
            moves.append(simple.Move(seat, street, letter, facing,
                                     "hu" if live == 1 else "multi",
                                     "pfa" if seat == raiser else "other", size,
                                     letter == "c" and to_call == 0,
                                     tuple(board[:cards])))
        if letter == "r":
            raises += 1
            if street == "preflop":
                raiser = seat
        if letter == "f":
            folded.add(seat)
        if amount is not None:
            bets[seat] = mine + amount
            top = max(top, bets[seat])
            pot += amount
    return moves, preflop_actions


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
    moves, preflop_actions = screen_moves(facts)
    moves = [move for move in moves if move.seat in opponents or move.kind == "f"]
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
            return simple.decide(simple.spot_from_observation(observation)), "table", None
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


def replay_log(name, rows, solver=False):
    """Every one of your turns in one log: the window's and the rule's answers."""
    rows = [row for row in rows if row.get("fields")]
    found = turns(rows)
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
        if hero and street in STREETS:
            try:
                advice, source, why = simple_answer(list(window._rows), fields,
                                                    hero.split(), street, window._stakes)
            except Exception as error:
                advice, source, why = None, None, f"failed:{type(error).__name__}"
        else:
            advice, source, why = None, None, "cards_unread" if not hero else "street"
        item["simple"] = None if advice is None else {**advice.row(), "source": source}
        item["simple_why"] = why
        start = rows[indexes[0]]["processed"]
        keys = ("frame", "street", "slot", "kind", "amount", "source")
        done = next((dict(zip(keys, a)) for a in (final.get(hand_id) or {}).get("actions", [])
                     if str(a[2]) == str(HERO) and a[1] == street and a[0] >= start), None)
        item["you_did"] = None if done is None else plain(done["kind"])
        if done is not None and done["kind"] in AGGRESSIVE and done.get("amount"):
            item["you_put"] = done["amount"]
        spot = shown_spot(rows, indexes, hand_id)
        if spot is not None:
            observation, share, cards = spot
            big_blind = float((window.stakes() or {}).get("big_blind") or 2)
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
    gain = [(item["shown"]["simple"] - item["shown"]["window"]) / item["shown"]["big_blind"]
            for item in differ]
    summary["shown"] = {
        "priced": len(priced_items), "differ": len(differ),
        "simple_better": sum(value > 0.01 for value in gain),
        "simple_worse": sum(value < -0.01 for value in gain),
        "simple_minus_window_bb": round(sum(gain), 1),
        "by_street": {street: round(sum(
            g for g, item in zip(gain, differ) if item["street"] == street), 1)
            for street in STREETS}}
    if hands is not None:
        summary["hands"] = hands
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frames", type=Path, action="append", default=[])
    parser.add_argument("--solver", action="store_true",
                        help="solve heads-up turns and rivers with TexasSolver")
    parser.add_argument("--lines", type=Path,
                        help="private folder for every decision")
    parser.add_argument("--out", type=Path, help="summary (totals only)")
    args = parser.parse_args(argv)
    if not args.frames:
        parser.error("give --frames")
    items = []
    for path in args.frames:
        name = path.parent.name
        found = replay_log(name, load(path), solver=args.solver)
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
