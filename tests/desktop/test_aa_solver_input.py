"""The rebuilt hand replayed on the simulated AA table for the solver."""

from decimal import Decimal

from poker_engine.desktop.aa_solver_input import (check_hand, hand_facts,
                                                  replay_hand, starting_stacks)

# Six players, dealer 5: small blind 0, big blind 1, straddle 2; seat 3 acts first.
ACTIONS = [
    (10, "preflop", 3, "fold", "0"), (12, "preflop", 4, "fold", "0"),
    (14, "preflop", 5, "call", "4"), (16, "preflop", 0, "fold", "0"),
    (18, "preflop", 1, "fold", "0"), (20, "preflop", 2, "check", "0"),
    (30, "flop", 2, "check", "0"), (32, "flop", 5, "raise", "10"),
    (34, "flop", 2, "call", "10"),
]
BOARD = ["Ah", "Kd", "7c"]


def facts(actions=ACTIONS, dealer=5, seats=range(6), stacks=None):
    return {"hand_id": "hand_1", "complete": True, "dealer": dealer,
            "seats": list(seats), "board": BOARD, "stacks": stacks or {},
            "opening_pot": Decimal(19),
            "actions": [dict(zip(("frame", "street", "slot", "kind", "amount"), a))
                        for a in actions]}


def test_a_hand_that_fits_replays_with_the_dealer_read():
    result = replay_hand(facts())
    assert (result["status"], result["dealer"], result["dealer_source"],
            result["replayed"]) == ("ok", 5, "reader", len(ACTIONS))


def test_a_dealer_the_betting_order_rules_out_is_replaced():
    result = replay_hand(facts(dealer=4))
    assert (result["status"], result["dealer"], result["dealer_source"]) == (
        "ok", 5, "betting_order")


def test_an_action_out_of_turn_stops_the_replay():
    missing = ACTIONS[:1] + ACTIONS[2:]              # seat 4's fold was not read
    result = replay_hand(facts(missing))
    assert (result["status"], result["reason"], result["replayed"]) == (
        "stopped", "not_this_seats_turn", 1)


def test_two_actions_read_in_the_same_frame_may_be_swapped():
    swapped = list(ACTIONS)
    swapped[3], swapped[4] = (17, "preflop", 1, "fold", "0"), (17, "preflop", 0,
                                                               "fold", "0")
    assert replay_hand(facts(swapped))["status"] == "ok"


def test_five_players_are_not_covered_by_the_aa_rules():
    result = replay_hand(facts(seats=range(5)))
    assert (result["status"], result["reason"]) == ("stopped", "players_5")


def test_starting_stacks_add_back_what_each_seat_put_in():
    current = {seat: Decimal(100) for seat in range(6)}
    hand = facts(stacks=current)
    result = replay_hand(hand)
    stacks = starting_stacks(hand, result)
    # Antes 2 each; seat 0 posted 1, seat 1 posted 2; seats 2 and 5 put in 4 + 10.
    assert stacks == {0: Decimal(103), 1: Decimal(104), 2: Decimal(116),
                      3: Decimal(102), 4: Decimal(102), 5: Decimal(116)}


def rows():
    """Frame-log rows of one hand: the pot resets, blinds go in, then actions."""
    history = {"hand_id": "hand_1", "complete": True, "start": "pot_went_down",
               "dealer": 5, "actions": [list(a) + ["no_chips"] for a in ACTIONS]}
    result = []
    for frame in range(40):
        pot = "0" if frame < 3 else "19" if frame < 14 else "23"
        states = {str(seat): "active" for seat in range(6)}
        states["7"] = "waiting"
        result.append({"processed": frame, "fields": {
            "pot": pot, "participants": states,
            "board": BOARD + [None, None] if frame >= 30 else [None] * 5,
            "stacks": {"5": "96" if frame >= 14 else "100"},
            "actions_v1": history}})
    return result


def test_hand_facts_come_from_the_frame_log():
    found = hand_facts(rows())
    assert found["seats"] == [0, 1, 2, 3, 4, 5]          # seat 7 was waiting
    assert found["board"] == BOARD and found["stacks"] == {5: Decimal(96)}
    assert found["opening_pot"] == Decimal(19)


def test_a_checked_hand_reports_the_replay_and_the_opening_pot():
    report = check_hand(rows())
    assert report["status"] == "ok" and report["players"] == 6
    assert report["opening_pot_matches"] is True        # 6 antes of 2 + 1 + 2 + 4


def test_the_seat_to_act_gets_the_observation_the_solver_strategy_uses():
    from poker_engine.desktop.aa_solver_input import solver_observation
    from poker_engine.scoreboard.replay import public_replay
    hand = {**facts(stacks={seat: Decimal(100) for seat in range(6)}),
            "board": BOARD + ["2s"]}
    observation, reason = solver_observation(hand, 2, ["Qs", "Qh"])
    assert reason is None
    assert (observation["street"], observation["actor"], observation["own_hole"]) == (
        "turn", 2, ["Qs", "Qh"])
    assert observation["stacks"]["2"] == "100" and observation["stacks_unknown"] == []
    assert [d.seat for d in public_replay(observation)] == [a[2] for a in ACTIONS]


def test_no_observation_before_the_board_card_is_read_or_out_of_turn():
    from poker_engine.desktop.aa_solver_input import solver_observation
    assert solver_observation(facts(), 2, ["Qs", "Qh"]) == (None, "board_not_read")
    hand = {**facts(), "board": BOARD + ["2s"]}
    assert solver_observation(hand, 5, ["Qs", "Qh"]) == (None, "not_this_seats_turn")
