"""Checks filled in from the table (``aa_solver_input._checked_around``) only
when the table's pots agree (nightly code check 10/16, synthetic hands).

Six players, dealer 5: small blind 0, big blind 1, straddle 2 (the shared
1/2/4(2) rules)."""

from decimal import Decimal

from poker_engine.desktop.aa_solver_input import (hand_facts, replay_hand,
                                                  solver_observation)

FLOP = ["Ah", "Kd", "7c"]
TURN = FLOP + ["2s"]


def history(hand, read, frame):
    return {"hand_id": hand, "complete": True, "start": "pot_went_down",
            "dealer": 5, "actions": [list(a) + ["pot_rise"] for a in read
                                     if a[0] <= frame]}


# Preflop seat 4 (you) and seat 5 limp, seat 2 checks its option: pot 27.
# Flop (order 2, 4, 5): seat 2 and you check (the P30 never reads a check
# badge), seat 5 bets 10 (badge missed), seat 2 calls 10 and you call 10
# (both read): pot 57. Turn: seat 2 bets 20; your button says call 20.
MISSED_BET = [
    (10, "preflop", 3, "fold", "0"), (12, "preflop", 4, "call", "4"),
    (14, "preflop", 5, "call", "4"), (16, "preflop", 0, "fold", "0"),
    (18, "preflop", 1, "fold", "0"), (20, "preflop", 2, "check", "0"),
    (36, "flop", 2, "call", "10"), (38, "flop", 4, "call", "10"),
    (50, "turn", 2, "raise", "20"),
]


def missed_bet_pot(frame):
    for until, pot in ((3, "0"), (12, "19"), (14, "23"), (33, "27"), (36, "37"),
                       (38, "47"), (50, "57")):
        if frame < until:
            return pot
    return "77"


def missed_bet_rows():
    rows = []
    for frame in range(56):
        states = {str(seat): "active" for seat in range(6)}
        for f, _, slot, kind, _ in MISSED_BET:
            if kind == "fold" and f <= frame:
                states[str(slot)] = "folded"
        board = (TURN + [None] if frame >= 45 else FLOP + [None, None] if frame >= 30
                 else [None] * 5)
        controls = ({"visible": True, "button": "call", "call_amount": "20"}
                    if frame >= 52 else {"visible": False})
        rows.append({"processed": frame, "fields": {
            "pot": missed_bet_pot(frame), "participants": states, "board": board,
            "stacks": {}, "street_wagers": {"2": "20"} if frame >= 50 else {},
            "hero_controls": controls,
            "actions_v1": history("hand_0", MISSED_BET, frame)}})
    return rows


def test_a_street_with_chips_in_it_is_not_taken_as_checked():
    facts = hand_facts(missed_bet_rows())
    # The flop began at 27 and the turn at 57: 30 chips went in on the flop,
    # which a replay of checks does not hold.
    assert facts["street_pots"]["flop"][0] == Decimal(27)
    assert facts["street_pots"]["turn"][0] == Decimal(57)
    assert not [a for a in replay_hand(facts)["inferred"] if a["street"] == "flop"]
    observation, reason = solver_observation(facts, 4, ["Qs", "Qh"])
    assert observation is None and reason


# Seat 2 checks its option (not read); flop: seat 2 checks (not read), seat 5
# bets 10, seat 2 calls.
OPTION = [
    (10, "preflop", 3, "fold", "0"), (12, "preflop", 4, "fold", "0"),
    (14, "preflop", 5, "call", "4"), (16, "preflop", 0, "fold", "0"),
    (18, "preflop", 1, "fold", "0"),
    (32, "flop", 5, "raise", "10"), (34, "flop", 2, "call", "10"),
]


def option_rows(stale):
    rows = []
    for frame in range(40):
        pot = ("0" if frame < 3 else "19" if frame < 14 else "23" if frame < 32
               else "33" if frame < 34 else "43")
        board = FLOP + [None, None] if frame >= 30 else [None] * 5
        if stale and 3 <= frame < 6:
            board = ["Jd", "As", "6d", None, None]     # the last hand's flop
        rows.append({"processed": frame, "fields": {
            "pot": pot, "participants": {str(seat): "active" for seat in range(6)},
            "board": board, "stacks": {},
            "actions_v1": history("hand_1", OPTION, frame)}})
    return rows


def test_the_last_hands_board_does_not_count_in_this_hands_pots():
    for stale in (False, True):
        facts = hand_facts(option_rows(stale))
        assert facts["board"] == FLOP
        assert facts["street_pots"]["flop"][0] == Decimal(23)
        result = replay_hand(facts)
        # The straddle's option check (unread) is filled in from the pots.
        assert result["status"] == "ok"
        assert [(a["slot"], a["street"], a["kind"]) for a in result["inferred"]] == [
            (2, "preflop", "check")]
