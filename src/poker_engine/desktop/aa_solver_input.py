"""The live hand as the solver strategy's input: a replay on the AA table.

The scoreboard's solver strategy works on the simulated AA table
(``AAFullHandArena``): it replays the hand's public actions to work out both
players' ranges. This turns one hand's frame summaries (``frame_summary``:
the rebuilt betting history ``actions_v1``, seat states, board, stacks) into
that replay, and checks the hand on the way:

- **seats**: the seats in the hand when its first action happened, plus any
  seat that acts. The AA rules cover 5 to 8 players;
- **dealer**: the dealer reading, unless the betting order says otherwise.
  The button can still show the last hand's dealer when the hand starts;
  when the reading does not fit the actions and exactly one other dealer
  replays the whole hand, that one is used;
- **actions**: every action must come from the seat whose turn it is, never
  on a later street than the table is on, and be legal at the table, with
  raises to what the seat had in plus its chips. (Without the street check,
  a hand joined after preflop can fit a wrong dealer with its flop checks
  taken for preflop calls. An earlier street is fine: the first action on a
  new street is often read before its board cards.) Two actions read in the
  same frame may be in either order; a fold read again for a seat that already
  folded is skipped. A seat that went all in with no stack reading is given
  what it had put in by then as its stack (it is not asked to act again). At
  the showdown the loser's cards are thrown away under the fold badge: a fold
  after the betting is over or from a seat that went all in is skipped, and a
  fold on the river with nothing to call is a check.

An action the reader missed can be filled in from the table, at most
``MAX_INFERRED`` per hand and only with the dealer that was read, when only
one action fits (``inferred``):

- the next seat called or folded with nothing to call: the seat bet, as much
  as that call (or the next call, or your price) says; the same seat's bet
  read later on that street is that bet, read late;
- otherwise, a seat whose turn it was and is folded on the table now folded,
  unless it acts again later on that street (it folded then; what it missed
  here can be a raise);
- otherwise, a seat whose turn it was and does not act again on that street
  called or raised to the bet it still has on the table, while the table is
  on that street (10/08: a raise to 27 missed, the next seat folded to it);
- before your turn, the seats still to act folded (folded on the table) or
  checked or called, unless your price (the button's call amount) is more
  than that leaves you: then the one of them still in bet up to it.

Anything else that does not fit stops the replay with a reason: no advice
should be given from such a hand. The opening pot is compared with the antes,
blinds and straddle for the seats found (it differs when extra chips such as
a mushroom or bomb pot go in); the solver should take the pot from the
table, not from the replay.

A bomb pot (暴击: everyone puts in 7 big blinds, no preflop betting, the
hand starts on the flop) is told by its first pot (``bomb_post``) and
replayed as one; the observation then says ``bomb_pot`` and the range and
solver replays rebuild it so. Any other hand whose first action read is
after the flop stops ("starts_after_preflop").

A big blind posted on coming back to the table (after a rebuy or on sitting
down) is not in the replay either. For the seat asking for advice it is read
from its bet before it has acted and, when the button's price agrees, put
into the observation: the post is live, so calling costs that much less
(``with_post``).
"""

from __future__ import annotations

from copy import deepcopy
import json
from decimal import Decimal
from pathlib import Path

from poker_engine.scoreboard.replay import replay_deck, with_hole
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

from .aa_action_history import COMPACT_FIELDS

RULES_PATH = (Path(__file__).resolve().parents[3]
              / "configs/game/aa-scoreboard-rules-v2.json")
IN_HAND = frozenset({"active", "folded", "all_in"})
PLAYERS = range(5, 9)               # table sizes the AA rules cover
DEEP = Decimal(100000)              # stacks for checking the betting alone
SAME_FRAME = 2                      # reader frames apart that may be swapped
MAX_INFERRED = 3                    # missed actions filled in from the table
BOARD = (("flop", 3), ("turn", 4), ("river", 5))
STREETS = ("preflop", "flop", "turn", "river")
HERO = 4                            # your seat: bottom centre
BOMB_BIG_BLINDS = 7                 # the table setting "暴击:7BB"


def _rules(players):
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return AARuleProfileV2.from_dict({**raw, "table_size": players})


def hand_facts(rows):
    """What the replay needs from one hand's frame-log rows (oldest first)."""
    history = (rows[-1].get("fields") or {}).get("actions_v1") or {}
    actions = [dict(zip(COMPACT_FIELDS, item)) for item in history.get("actions", [])]
    first = actions[0]["frame"] if actions else None
    fields = [row.get("fields") or {} for row in rows]
    if first is not None:
        at_first = next((f for row, f in zip(rows, fields)
                         if row["processed"] >= first), {})
    else:
        # Nobody has acted yet (you are first to act): the latest seat reading.
        at_first = next((f for f in reversed(fields) if f.get("participants")), {})
    seats = {int(seat) for seat, state in (at_first.get("participants") or {}).items()
             if state in IN_HAND} | {action["slot"] for action in actions}
    board = _board(fields)
    stacks = {}
    for f in fields:
        for seat, value in (f.get("stacks") or {}).items():
            if value not in (None, ""):
                stacks[int(seat)] = Decimal(value)
    latest = fields[-1] if fields else {}
    return {"hand_id": history.get("hand_id"), "complete": history.get("complete"),
            "dealer": history.get("dealer"), "seats": sorted(seats),
            "actions": actions, "board": board, "stacks": stacks,
            "opening_pot": _opening_pot(rows, fields, first),
            "states": {int(seat): state for seat, state in
                       (latest.get("participants") or {}).items()},
            "wagers": {int(seat): Decimal(value) for seat, value in
                       (latest.get("street_wagers") or {}).items()
                       if value not in (None, "")},
            "price": _price(latest.get("hero_controls") or {}),
            "all_in": _all_in(latest.get("hero_controls") or {})}


def _price(controls):
    """What your button says you have to put in: 0 for a check, the call
    amount for a call, None otherwise (an all-in call, no buttons)."""
    if not controls.get("visible"):
        return None
    if controls.get("button") == "check":
        return Decimal(0)
    amount = controls.get("call_amount")
    if controls.get("button") == "call" and amount not in (None, ""):
        return Decimal(str(amount))
    return None


def _all_in(controls):
    """Your button says "All in" (with your stack read): calling takes every
    chip you have."""
    return bool(controls.get("visible") and controls.get("button") == "all_in"
                and controls.get("call_amount") not in (None, ""))


def _board(fields):
    """The longest board read that agrees with the latest board reading.

    A new hand's first frames can still show the last hand's board (the pot
    resets before the cards are cleared). Those readings disagree with this
    hand's board once its flop is read, so they are left out; a board with an
    unread card before a read one is too.
    """
    readings = [list(f.get("board") or []) for f in fields]
    latest = next((board for board in reversed(readings) if any(board)), [])
    boards = []
    for board in readings:
        cards = [card for card in board if card]
        if (board[:len(cards)] == cards
                and all(a == b for a, b in zip(board, latest) if a and b)):
            boards.append(cards)
    return max(boards, key=len, default=[])


def _opening_pot(rows, fields, first):
    """The steady pot before the first action, after the last empty pot."""
    pots = [f.get("pot") for row, f in zip(rows, fields)
            if first is None or row["processed"] <= first]
    pots = [pot for pot in pots if pot not in (None, "")]
    if "0" in pots:
        pots = pots[len(pots) - pots[::-1].index("0"):]
    steady = [a for a, b in zip(pots, pots[1:]) if a == b and a != "0"]
    return Decimal(steady[0]) if steady else None


def bomb_post(facts):
    """Each player's post in chips when the hand is a bomb pot (暴击), else
    None.

    A bomb pot has every player put in the same amount (7 big blinds) and
    starts on the flop: no preflop action is read, and the hand's first pot
    is that post from every seat in it (98 = 7 players x 14 on the 9/9
    recording, 112 = 8 x 14 on 10/07). A normal hand's first pot is the
    antes, blinds and straddle, even when its preflop actions were missed.
    """
    if facts.get("opening_pot") is None or not facts["seats"] or any(
            action.get("street") in (None, "preflop") for action in facts["actions"]):
        return None
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    post = Decimal(raw["big_blind"]) * BOMB_BIG_BLINDS
    return post if facts["opening_pot"] == post * len(facts["seats"]) else None


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
    bomb = bomb_post(facts)
    if bomb is None and actions and actions[0].get("street") not in (None, "preflop"):
        # No preflop betting, and not the pot a bomb pot opens with.
        return _result("stopped", "starts_after_preflop", None, None, 0, None)
    reported = facts["dealer"]
    candidates = ([reported] if reported in seats else []) + [
        seat for seat in seats if seat != reported]
    tried = {}
    for dealer in candidates:
        table = facts if dealer == reported else None
        tried[dealer] = _replay(seats, dealer, actions, facts["board"], stacks, table,
                                bomb)
        if dealer == reported and tried[dealer][0] == "ok":
            return _result("ok", None, dealer, "reader", *tried[dealer][2:])
    fits = [dealer for dealer, outcome in tried.items() if outcome[0] == "ok"]
    if len(fits) == 1:
        source = "betting_order" if reported is not None else "betting_order_only"
        return _result("ok", None, fits[0], source, *tried[fits[0]][2:])
    if len(fits) > 1:
        return _result("stopped", "dealer_ambiguous", None, None, 0, None)
    if reported in seats:
        status, reason, replayed, arena, inferred = tried[reported]
        return _result(status, reason, reported, "reader", replayed, arena, inferred)
    return _result("stopped", "no_dealer_fits", None, None, 0, None)


def _result(status, reason, dealer, source, replayed, arena, inferred=()):
    return {"status": status, "reason": reason, "dealer": dealer,
            "dealer_source": source, "replayed": replayed, "arena": arena,
            "inferred": list(inferred)}


def _replay(seats, dealer, actions, board, stacks, table=None, bomb=None):
    """(status, reason, replayed, arena, inferred) for one dealer; swaps two
    actions read within SAME_FRAME frames of each other when that is what
    fits, and with ``table`` (the hand's facts) fills in missed actions.
    ``bomb``: each player's post when the hand is a bomb pot."""
    actions, inferred = list(actions), []
    outcome = _steps(seats, dealer, actions, board, stacks, bomb)
    while outcome[0] != "ok":
        at = outcome[2]
        if at + 1 < len(actions) and abs(actions[at + 1]["frame"]
                                         - actions[at]["frame"]) <= SAME_FRAME:
            swapped = actions[:at] + [actions[at + 1], actions[at]] + actions[at + 2:]
            retry = _steps(seats, dealer, swapped, board, stacks, bomb)
            if retry[2] > at + 1:
                actions, outcome = swapped, retry
                continue
        filled = (_fill(outcome[3], actions, at, table)
                  if table is not None and outcome[1] == "not_this_seats_turn"
                  and len(inferred) < MAX_INFERRED else None)
        if filled is None:
            return (*outcome, inferred)
        retry = _steps(seats, dealer, filled, board, stacks, bomb)
        if retry[2] <= at + 1:
            return (*outcome, inferred)
        inferred.append(filled[at])
        actions, outcome = filled, retry
    return (*outcome, inferred)


def _missed(arena, seat, table, amount_from):
    """The action ``seat`` must have taken, or None when more than one fits.
    ``amount_from``: (seat, chips) a later call put in, or None."""
    street = arena.street
    if table["states"].get(seat) == "folded":
        return {"slot": seat, "kind": "fold", "street": street, "amount": "0"}
    if amount_from is None:
        return {"slot": seat, "kind": "call", "street": street, "amount": None}
    bets = {int(key): Decimal(value)
            for key, value in arena.observe(seat)["bets"].items()}
    caller, chips = amount_from
    level = bets[caller] + chips
    if level <= max(bets.values()):
        return None
    return {"slot": seat, "kind": "raise", "street": street,
            "amount": str(level - bets[seat])}


def _fill(arena, actions, at, table):
    """``actions`` with the action the reader missed before ``actions[at]``
    put in (see the module notes), or None."""
    seat, nxt = arena.actor, actions[at]
    if (not table.get("states") or seat is None or seat == nxt["slot"]
            or nxt.get("street") != arena.street):
        return None
    bets = {int(key): Decimal(value)
            for key, value in arena.observe(seat)["bets"].items()}
    to_call = max(bets.values()) - bets[nxt["slot"]]
    later = [index for index in range(at + 1, len(actions))
             if actions[index]["slot"] == seat
             and actions[index]["street"] == arena.street]
    if nxt["kind"] in ("call", "fold") and to_call == 0:
        source = next((action for action in actions[at:]
                       if action["kind"] == "call"
                       and action["amount"] not in (None, "")
                       and action["street"] == arena.street), None)
        late = next((index for index in later if actions[index]["kind"] in
                     ("raise", "all_in")), None)
        if source is not None:
            amount_from = (source["slot"], Decimal(source["amount"]))
        elif late is not None and actions[late]["amount"] not in (None, ""):
            amount_from = (seat, Decimal(actions[late]["amount"]))
        elif table.get("price") is not None:
            amount_from = (HERO, table["price"])
        else:
            return None
        action = _missed(arena, seat, {**table, "states": {}}, amount_from)
        rest = [a for index, a in enumerate(actions) if index != late]
    elif table["states"].get(seat) == "folded" and not later:
        action = _missed(arena, seat, table, None)
        rest = list(actions)
    elif not later:
        action = _from_wager(arena, seat, table)
        rest = list(actions)
    else:
        return None             # it checked, called or raised: no telling
    if action is None:
        return None
    action.update(frame=nxt["frame"], source="inferred")
    return rest[:at] + [action] + rest[at:]


def _from_wager(arena, seat, table):
    """The call or raise ``seat`` made, told by its bet still on the table
    while the table is on the replay's street; None when there is no telling."""
    wager = (table.get("wagers") or {}).get(seat)
    street = next((name for name, count in reversed(BOARD)
                   if len(table.get("board") or ()) >= count), "preflop")
    if wager is None or street != arena.street:
        return None
    bets = {int(key): Decimal(value)
            for key, value in arena.observe(seat)["bets"].items()}
    top = max(bets.values())
    if wager == top:
        return {"slot": seat, "kind": "call", "street": street, "amount": None}
    if wager > top:
        return {"slot": seat, "kind": "raise", "street": street,
                "amount": str(wager - bets[seat])}
    return None


def fill_to_seat(arena, seat, table):
    """The actions of the seats still to act before ``seat``, from the table
    (see the module notes), or None when they cannot be told."""
    if table.get("price") is None or not table.get("states"):
        return None
    frame = max((action["frame"] for action in table["actions"]), default=0)
    filled, probe = [], arena
    for _ in range(MAX_INFERRED):
        if probe.terminal or probe.actor == seat:
            break
        actor = probe.actor
        mine = Decimal(probe.observe(seat)["bets"][str(seat)])
        level = mine + table["price"]
        top = max(Decimal(value) for value in probe.observe(seat)["bets"].values())
        if table["states"].get(actor) == "folded":
            action = {"slot": actor, "kind": "fold", "street": probe.street,
                      "amount": "0"}
        elif level > top:
            behind = _still_to_act(probe, seat, table)
            if behind != [actor]:
                return None
            action = _missed(probe, actor, {**table, "states": {}},
                             (seat, table["price"]))
        else:
            action = {"slot": actor, "kind": "call", "street": probe.street,
                      "amount": None}
        if action is None:
            return None
        action.update(frame=frame, source="inferred")
        step = _arena_action(probe, action)
        probe = deepcopy(probe)
        probe.step(step)
        filled.append(action)
    if probe.terminal or probe.actor != seat:
        return None
    return filled


def _still_to_act(arena, seat, table):
    """The seats acting before ``seat`` that are not folded, at the table or
    in the replay."""
    seats, folded = arena.occupied_seats, set(arena.observe(seat)["folded"])
    order, index = [], seats.index(arena.actor)
    while seats[index] != seat:
        if (seats[index] not in folded
                and table["states"].get(seats[index]) != "folded"):
            order.append(seats[index])
        index = (index + 1) % len(seats)
    return order


def _steps(seats, dealer, actions, board, stacks, bomb=None):
    """Replay ``actions``; a seat that went all in without a stack reading is
    given what it had put in by then as its stack, so it is not asked to act
    again (it was taken as deep)."""
    stacks = dict(stacks or {})
    while True:
        outcome = _steps_once(seats, dealer, actions, board, stacks, bomb)
        if outcome[0] != "all_in_again":
            return outcome
        seat, chips = outcome[1]
        stacks[seat] = chips


def _steps_once(seats, dealer, actions, board, stacks, bomb):
    arena = AAFullHandArena(
        _rules(len(seats)), occupied_seats=seats, dealer_seat=dealer,
        starting_stacks={seat: stacks.get(seat, DEEP) for seat in seats})
    arena.reset(0, deck=replay_deck(board_history(board), len(seats)),
                bomb=None if bomb is None else _money(bomb))
    folded, all_in, put_in = set(), set(), {}
    for index, action in enumerate(actions):
        if action["kind"] == "fold" and action["slot"] in folded:
            continue                  # the same fold read again (badge flicker)
        if action["kind"] == "fold" and (arena.terminal or action["slot"] in all_in):
            continue                  # cards thrown away at the showdown
        if arena.terminal:
            return "stopped", "action_after_hand_end", index, arena
        if arena.actor in put_in:
            return "all_in_again", (arena.actor, put_in[arena.actor]), index, arena
        if arena.actor != action["slot"]:
            return "stopped", "not_this_seats_turn", index, arena
        street = action.get("street")
        if street in STREETS and STREETS.index(street) > STREETS.index(arena.street):
            return "stopped", "street_mismatch", index, arena
        step = _arena_action(arena, action)
        if step is None:
            return "stopped", "raise_without_amount", index, arena
        if step == "fold" and arena.street == "river" and not _to_call(arena):
            step = "check_call"       # the loser throwing the cards away
        try:
            arena.step(step)
        except ValueError:
            return "stopped", "illegal_at_the_table", index, arena
        if action["kind"] == "fold":
            folded.add(action["slot"])
        elif action["kind"] == "all_in":
            all_in.add(action["slot"])
            if action["slot"] not in stacks:
                put_in[action["slot"]] = Decimal(arena.observe(action["slot"])[
                    "contributions"][str(action["slot"])])
    if not arena.terminal and arena.actor in put_in:
        return "all_in_again", (arena.actor, put_in[arena.actor]), len(actions), arena
    return "ok", None, len(actions), arena


def _to_call(arena):
    """What the seat to act must put in to call."""
    bets = {int(seat): Decimal(value)
            for seat, value in arena.observe(arena.actor)["bets"].items()}
    return max(bets.values()) - bets[arena.actor]


def _arena_action(arena, action):
    """The table action for a rebuilt one: raises go to what the seat had in
    plus its chips; an all-in that does not top the bets is a call. A call or
    raise seen from the seat's stack going down (source "stack_drop") is a
    call when its chips come to the highest bet and a raise when they top it."""
    kind = action["kind"]
    if kind == "fold":
        return "fold"
    dropped = action.get("source") == "stack_drop" and kind in ("call", "raise")
    if kind == "check" or (kind == "call" and not dropped):
        return "check_call"
    if action["amount"] in (None, ""):
        return None
    bets = {int(seat): Decimal(value)
            for seat, value in arena.observe(action["slot"])["bets"].items()}
    target = bets[action["slot"]] + Decimal(action["amount"])
    top = max(bets.values())
    if (kind == "all_in" and target <= top) or (dropped and target == top):
        return "check_call"
    if dropped and target < top:
        return None                   # short of a call: a stack read wrong
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
    for a hand joined midway (its first actions are unknown), when the replay
    stops, when it is not ``seat``'s turn yet ("not_your_turn_yet": usually the
    action before has not been read yet), when the stack readings do not fit
    the betting, when the table would have dealt a board card the reader
    has not seen, or when the price to call is not what your button shows
    (``facts["price"]``, or your whole stack when it says "All in").
    """
    if facts.get("complete") is not True:
        return None, "hand_incomplete"
    first = replay_hand(facts)
    if first["status"] != "ok":
        return None, first["reason"]
    if not first["arena"].terminal and first["arena"].actor != seat:
        filled = (fill_to_seat(first["arena"], seat, facts)
                  if first["dealer_source"] == "reader" else None)
        if filled:
            facts = {**facts, "actions": facts["actions"] + filled}
            first = replay_hand(facts)
    if (first["status"] != "ok" or first["arena"].terminal
            or first["arena"].actor != seat):
        return None, "not_your_turn_yet"
    # Only now: a stack can already show an action the history has not read yet.
    stacks = starting_stacks(facts, first)
    replay = replay_hand({**facts, "dealer": first["dealer"]}, stacks)
    arena = replay["arena"]
    if replay["status"] != "ok" or arena.terminal or arena.actor != seat:
        return None, "stacks_do_not_fit"
    observation = arena.observe(seat)
    if len(observation["board"]) > len(facts["board"]):
        return None, "board_not_read"
    to_call = Decimal(observation["to_call"])
    post = own_post(facts, observation, seat)
    if post and to_call - post == facts.get("price"):
        observation, to_call = with_post(observation, seat, post), to_call - post
    stack = Decimal(observation["stacks"][str(seat)])
    shown = stack if facts.get("all_in") else facts.get("price")
    if shown is not None and min(to_call, stack) != shown:
        # A missed action rebuilt wrong (or a dealer moved by one seat): the
        # table asks a price your button does not show.
        return None, "price_does_not_match"
    missing = [other for other in facts["seats"] if other not in stacks]
    observation = with_hole(observation, cards)
    observation["stacks_unknown"] = missing
    observation["inferred_actions"] = len(replay["inferred"]) + sum(
        action.get("source") == "inferred" for action in facts["actions"])
    return observation, None


def _money(value):
    """Chips as the table writes them ("25", "0.5")."""
    return format(value.normalize(), "f") if value else "0"


def own_post(facts, observation, seat):
    """Chips ``seat`` posted on coming back to the table (after a rebuy or on
    sitting down): before it has acted preflop, its bet on the table above
    the blind or straddle the replay has it put in. 0 when there is none."""
    if observation["street"] != "preflop" or any(
            action["slot"] == seat and action["street"] == "preflop"
            for action in facts["actions"]):
        return Decimal(0)
    read = facts.get("wagers", {}).get(seat)
    owed = Decimal(observation["bets"][str(seat)])
    return read - owed if read is not None and read > owed else Decimal(0)


def with_post(observation, seat, post):
    """``observation`` with ``post`` more of ``seat``'s chips in its bet.

    AA has a player who comes back post a big blind, and it is live: calling
    costs that much less, the pot holds it, and going all in raises to that
    much more. The replay has no such post; the stack behind is already the
    one read on the table.
    """
    key, extra = str(seat), Decimal(post)
    result = deepcopy(observation)

    def more(value):
        return _money(Decimal(value) + extra)

    top = observation["betting"]["max_raise_to"]
    result["to_call"] = _money(Decimal(observation["to_call"]) - extra)
    result["pot"] = more(observation["pot"])
    for part in ("bets", "contributions", "starting_stacks"):
        result[part][key] = more(observation[part][key])
    if top is not None:
        result["betting"]["max_raise_to"] = more(top)
        for action in result["legal_actions"]:
            if action["kind"] == "raise_to" and action["raise_to"] == top:
                action["raise_to"] = more(top)
                action["id"] = "raise_to:" + action["raise_to"]
    result["posted"] = _money(extra)
    return result


def check_hand(rows):
    """Replay one hand from its frame-log rows; a summary for reports."""
    facts = hand_facts(rows)
    replay = replay_hand(facts)
    players = len(facts["seats"])
    expected, bomb = None, bomb_post(facts)
    if bomb is not None:
        expected = bomb * players
    elif players in PLAYERS:
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
            "opening_pot_matches": facts["opening_pot"] == expected,
            "bomb_pot": None if bomb is None else _money(bomb)}


__all__ = ["BOMB_BIG_BLINDS", "board_history", "bomb_post", "check_hand",
           "fill_to_seat", "hand_facts", "own_post", "replay_hand",
           "solver_observation", "starting_stacks", "with_post"]
