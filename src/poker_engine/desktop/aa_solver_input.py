"""The live hand as the solver strategy's input: a replay on the AA table.

The scoreboard's solver strategy works on the simulated AA table
(``AAFullHandArena``): it replays the hand's public actions to work out both
players' ranges. This turns one hand's frame summaries (``frame_summary``:
the rebuilt betting history ``actions_v1``, seat states, board, stacks) into
that replay, and checks the hand on the way:

- **seats**: the seats in the hand when its first action happened, plus any
  seat that acts. The AA rules cover 6 to 8 players;
- **dealer**: the dealer reading, unless the betting order says otherwise.
  Spectating, the button in front of the bottom seat is not read and the
  last reading stays; when the reading does not fit the actions and exactly
  one other dealer replays the whole hand, that one is used;
- **actions**: every action must come from the seat whose turn it is and be
  legal at the table, with raises to what the seat had in plus its chips.
  Two actions read in the same frame may be in either order.

Anything that does not fit stops the replay with a reason: no advice should
be given from such a hand. The opening pot is compared with the antes,
blinds and straddle for the seats found (it differs when extra chips such as
a mushroom or bomb pot go in); the solver should take the pot from the
table, not from the replay.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from poker_engine.scoreboard.replay import replay_deck, with_hole
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

from .aa_action_history import COMPACT_FIELDS

RULES_PATH = (Path(__file__).resolve().parents[3]
              / "configs/game/aa-scoreboard-rules-v1.json")
IN_HAND = frozenset({"active", "folded", "all_in"})
PLAYERS = range(6, 9)               # table sizes the AA rules cover
DEEP = Decimal(100000)              # stacks for checking the betting alone
SAME_FRAME = 2                      # reader frames apart that may be swapped
BOARD = (("flop", 3), ("turn", 4), ("river", 5))


def _rules(players):
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return AARuleProfileV2.from_dict({**raw, "table_size": players})


def hand_facts(rows):
    """What the replay needs from one hand's frame-log rows (oldest first)."""
    history = (rows[-1].get("fields") or {}).get("actions_v1") or {}
    actions = [dict(zip(COMPACT_FIELDS, item)) for item in history.get("actions", [])]
    first = actions[0]["frame"] if actions else None
    fields = [row.get("fields") or {} for row in rows]
    at_first = next((f for row, f in zip(rows, fields)
                     if first is not None and row["processed"] >= first), {})
    seats = {int(seat) for seat, state in (at_first.get("participants") or {}).items()
             if state in IN_HAND} | {action["slot"] for action in actions}
    board = max(([card for card in (f.get("board") or []) if card] for f in fields),
                key=len, default=[])
    stacks = {}
    for f in fields:
        for seat, value in (f.get("stacks") or {}).items():
            if value not in (None, ""):
                stacks[int(seat)] = Decimal(value)
    return {"hand_id": history.get("hand_id"), "complete": history.get("complete"),
            "dealer": history.get("dealer"), "seats": sorted(seats),
            "actions": actions, "board": board, "stacks": stacks,
            "opening_pot": _opening_pot(rows, fields, first)}


def _opening_pot(rows, fields, first):
    """The steady pot before the first action, after the last empty pot."""
    pots = [f.get("pot") for row, f in zip(rows, fields)
            if first is None or row["processed"] <= first]
    pots = [pot for pot in pots if pot not in (None, "")]
    if "0" in pots:
        pots = pots[len(pots) - pots[::-1].index("0"):]
    steady = [a for a, b in zip(pots, pots[1:]) if a == b and a != "0"]
    return Decimal(steady[0]) if steady else None


def board_history(board):
    rows, done = [], 0
    for street, count in BOARD:
        if len(board) >= count:
            rows.append({"street": street, "cards": list(board[done:count])})
            done = count
    return rows


def replay_hand(facts, stacks=None):
    """The hand replayed on the AA table.

    Returns {"status": "ok" | "stopped", "reason", "dealer", "dealer_source",
    "replayed", "arena"}: ``replayed`` actions fitted the table; on "stopped"
    the arena holds the hand up to the action that did not fit.
    """
    seats, actions = facts["seats"], facts["actions"]
    if len(seats) not in PLAYERS:
        return _result("stopped", f"players_{len(seats)}", None, None, 0, None)
    reported = facts["dealer"]
    candidates = ([reported] if reported in seats else []) + [
        seat for seat in seats if seat != reported]
    tried = {}
    for dealer in candidates:
        tried[dealer] = _replay(seats, dealer, actions, facts["board"], stacks)
        if dealer == reported and tried[dealer][0] == "ok":
            return _result("ok", None, dealer, "reader", *tried[dealer][2:])
    fits = [dealer for dealer, outcome in tried.items() if outcome[0] == "ok"]
    if len(fits) == 1:
        source = "betting_order" if reported is not None else "betting_order_only"
        return _result("ok", None, fits[0], source, *tried[fits[0]][2:])
    if len(fits) > 1:
        return _result("stopped", "dealer_ambiguous", None, None, 0, None)
    if reported in seats:
        status, reason, replayed, arena = tried[reported]
        return _result(status, reason, reported, "reader", replayed, arena)
    return _result("stopped", "no_dealer_fits", None, None, 0, None)


def _result(status, reason, dealer, source, replayed, arena):
    return {"status": status, "reason": reason, "dealer": dealer,
            "dealer_source": source, "replayed": replayed, "arena": arena}


def _replay(seats, dealer, actions, board, stacks):
    """(status, reason, replayed, arena) for one dealer; swaps two actions read
    within SAME_FRAME frames of each other when that is what fits."""
    actions = list(actions)
    outcome = _steps(seats, dealer, actions, board, stacks)
    while outcome[0] != "ok":
        at = outcome[2]
        if at + 1 >= len(actions) or abs(actions[at + 1]["frame"]
                                         - actions[at]["frame"]) > SAME_FRAME:
            return outcome
        swapped = actions[:at] + [actions[at + 1], actions[at]] + actions[at + 2:]
        retry = _steps(seats, dealer, swapped, board, stacks)
        if retry[2] <= at + 1:
            return outcome
        actions, outcome = swapped, retry
    return outcome


def _steps(seats, dealer, actions, board, stacks):
    arena = AAFullHandArena(
        _rules(len(seats)), occupied_seats=seats, dealer_seat=dealer,
        starting_stacks={seat: (stacks or {}).get(seat, DEEP) for seat in seats})
    arena.reset(0, deck=replay_deck(board_history(board), len(seats)))
    for index, action in enumerate(actions):
        if arena.terminal:
            return "stopped", "action_after_hand_end", index, arena
        if arena.actor != action["slot"]:
            return "stopped", "not_this_seats_turn", index, arena
        step = _arena_action(arena, action)
        if step is None:
            return "stopped", "raise_without_amount", index, arena
        try:
            arena.step(step)
        except ValueError:
            return "stopped", "illegal_at_the_table", index, arena
    return "ok", None, len(actions), arena


def _arena_action(arena, action):
    """The table action for a rebuilt one: raises go to what the seat had in
    plus its chips; an all-in that does not top the bets is a call."""
    kind = action["kind"]
    if kind == "fold":
        return "fold"
    if kind in ("check", "call"):
        return "check_call"
    if action["amount"] in (None, ""):
        return None
    bets = {int(seat): Decimal(value)
            for seat, value in arena.observe(action["slot"])["bets"].items()}
    target = bets[action["slot"]] + Decimal(action["amount"])
    if kind == "all_in" and target <= max(bets.values()):
        return "check_call"
    return f"raise_to:{target}"


def starting_stacks(facts, replay):
    """Each seat's stack before the hand: its last reading plus what it put in.

    Seats without a reading are left out (unknown).
    """
    if replay["arena"] is None:
        return {}
    put = replay["arena"].observe(facts["seats"][0])["contributions"]
    return {seat: facts["stacks"][seat] + Decimal(put[str(seat)])
            for seat in facts["seats"] if seat in facts["stacks"]}


def solver_observation(facts, seat, cards):
    """(observation, reason): the table as ``seat`` sees it now, holding
    ``cards`` -- what the scoreboard's solver strategy decides from.

    The hand is replayed again from starting stacks (readings plus what each
    seat put in; seats without a reading stay deep). There is no observation
    when the replay stops, when it is not ``seat``'s turn, or when the table
    would have dealt a board card the reader has not seen yet.
    """
    first = replay_hand(facts)
    if first["status"] != "ok":
        return None, first["reason"]
    stacks = starting_stacks(facts, first)
    replay = replay_hand({**facts, "dealer": first["dealer"]}, stacks)
    arena = replay["arena"]
    if replay["status"] != "ok":
        return None, replay["reason"]
    if arena.terminal or arena.actor != seat:
        return None, "not_this_seats_turn"
    observation = arena.observe(seat)
    if len(observation["board"]) > len(facts["board"]):
        return None, "board_not_read"
    missing = [other for other in facts["seats"] if other not in stacks]
    observation = with_hole(observation, cards)
    observation["stacks_unknown"] = missing
    return observation, None


def check_hand(rows):
    """Replay one hand from its frame-log rows; a summary for reports."""
    facts = hand_facts(rows)
    replay = replay_hand(facts)
    players = len(facts["seats"])
    expected = None
    if players in PLAYERS:
        rules = _rules(players)
        expected = (rules.ante * players + rules.small_blind + rules.big_blind
                    + rules.straddle_amount)
    return {"hand_id": facts["hand_id"], "complete": facts["complete"],
            "players": players, "status": replay["status"], "reason": replay["reason"],
            "dealer": replay["dealer"], "dealer_source": replay["dealer_source"],
            "reported_dealer": facts["dealer"], "replayed": replay["replayed"],
            "actions": len(facts["actions"]),
            "opening_pot": None if facts["opening_pot"] is None
            else str(facts["opening_pot"]),
            "opening_pot_matches": facts["opening_pot"] == expected}


__all__ = ["board_history", "check_hand", "hand_facts", "replay_hand",
           "solver_observation", "starting_stacks"]
