"""The rebuilt hand replayed on the simulated AA table for the solver."""

from decimal import Decimal

from poker_engine.desktop.aa_solver_input import (check_hand, fill_to_seat, hand_facts,
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


def test_five_players_replay_with_the_straddle_on_the_seat_after_the_big_blind():
    # Five players, dealer 4: small blind 0, big blind 1, straddle 2; seat 3 acts first.
    five = [(10, "preflop", 3, "call", "4"), (12, "preflop", 4, "fold", "0"),
            (14, "preflop", 0, "fold", "0"), (16, "preflop", 1, "fold", "0"),
            (18, "preflop", 2, "check", "0"), (30, "flop", 2, "check", "0"),
            (32, "flop", 3, "raise", "10"), (34, "flop", 2, "call", "10")]
    result = replay_hand(facts(five, dealer=4, seats=range(5)))
    assert (result["status"], result["dealer"], result["replayed"]) == (
        "ok", 4, len(five))


def test_four_players_replay_with_the_dealer_first_to_act():
    # As on 10/08: dealer 3, small blind 0, big blind 1, straddle 2; the
    # dealer acts first. The hand opens with 4 antes of 2 + 1 + 2 + 4 = 15.
    four = [(10, "preflop", 3, "fold", "0"), (12, "preflop", 0, "fold", "0"),
            (14, "preflop", 1, "raise", "14"), (16, "preflop", 2, "call", "10"),
            (30, "flop", 1, "check", "0"), (32, "flop", 2, "check", "0")]
    result = replay_hand(facts(four, dealer=3, seats=range(4)))
    assert (result["status"], result["dealer"], result["replayed"]) == (
        "ok", 3, len(four))


def test_three_players_are_not_covered_by_the_aa_rules():
    result = replay_hand(facts(seats=range(3)))
    assert (result["status"], result["reason"]) == ("stopped", "players_3")


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


def test_an_unread_dealer_comes_from_the_blinds_on_the_table():
    from poker_engine.desktop.aa_solver_input import blind_dealer
    # Dealer 5: small blind 1 on seat 0, big blind 2 on seat 1, straddle 4.
    found = rows()
    for row in found:
        row["fields"]["actions_v1"] = {**row["fields"]["actions_v1"], "dealer": None}
        if row["processed"] >= 3:
            row["fields"]["street_wagers"] = {"0": "1", "1": "2", "2": "4"}
    facts = hand_facts(found)
    assert facts["blind_dealer"] == 5
    result = replay_hand(facts)
    assert (result["status"], result["dealer"], result["dealer_source"]) == (
        "ok", 5, "blinds")
    # Two seats with a big blind in front (one posting on coming back), or a
    # big blind not next to the small one: no dealer from the blinds.
    seats = [0, 1, 2, 3, 4, 5]
    two_bigs = {"street_wagers": {"0": "1", "1": "2", "3": "2"}}
    assert blind_dealer([two_bigs], seats) is None
    assert blind_dealer([{"street_wagers": {"0": "1", "2": "2"}}], seats) is None
    assert blind_dealer([{"street_wagers": {"3": "1", "4": "2"}}], [0, 2, 3, 4]) == 2


def test_the_last_hands_board_still_on_screen_is_not_this_hands_board():
    found = rows()
    for row in found[3:6]:                  # the last hand's cards, not cleared yet
        row["fields"] = {**row["fields"], "board": ["Jd", "As", "6d", "9c", "Td"]}
    found[36]["fields"] = {**found[36]["fields"], "board": [None] * 5}   # a miss
    assert hand_facts(found)["board"] == BOARD


def test_a_board_with_an_unread_card_before_a_read_one_is_left_out():
    found = rows()[:32]
    gapped = [None, "Kd", "7c", "2s", None]
    found[-1]["fields"] = {**found[-1]["fields"], "board": gapped}
    assert hand_facts(found)["board"] == BOARD


def test_before_any_action_the_seats_come_from_the_latest_reading():
    early = [row for row in rows() if row["processed"] < 8]
    for row in early:
        row["fields"] = {**row["fields"], "actions_v1": {
            **row["fields"]["actions_v1"], "actions": []}}
    found = hand_facts(early)
    assert found["seats"] == [0, 1, 2, 3, 4, 5] and found["actions"] == []


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
    assert solver_observation(hand, 5, ["Qs", "Qh"]) == (None, "not_your_turn_yet")
    joined = {**hand, "complete": False}
    assert solver_observation(joined, 2, ["Qs", "Qh"]) == (None, "hand_incomplete")


def test_an_action_on_another_street_than_the_table_stops_the_replay():
    # Preflop actions read as the flop's must not pass for preflop calls.
    shifted = ACTIONS[:2] + [(a[0], "flop", *a[2:]) for a in ACTIONS[2:6]]
    result = replay_hand(facts(shifted))
    assert (result["status"], result["reason"]) == ("stopped", "street_mismatch")


def test_the_first_action_of_a_street_may_be_read_before_its_board():
    early = list(ACTIONS)
    early[6] = (30, "preflop", 2, "check", "0")       # the first flop check
    assert replay_hand(facts(early))["status"] == "ok"


def test_a_hand_without_preflop_betting_is_not_replayed():
    # Its first pot (19) is the blinds, not a bomb pot's: the preflop was missed.
    flop_only = [(a[0], "flop", *a[2:]) for a in ACTIONS[6:]]
    result = replay_hand(facts(flop_only))
    assert (result["status"], result["reason"]) == ("stopped", "starts_after_preflop")


def test_stacks_that_do_not_fit_the_betting_give_no_observation():
    from poker_engine.desktop.aa_solver_input import solver_observation
    # Seat 5's stack already shows a shove the history has not read: with 0
    # behind it would have been all in on the flop.
    stacks = {seat: Decimal(100) for seat in range(6)}
    hand = {**facts(stacks={**stacks, 5: Decimal(0)}), "board": BOARD + ["2s"]}
    assert solver_observation(hand, 2, ["Qs", "Qh"]) == (None, "stacks_do_not_fit")


def test_a_stack_the_table_cannot_start_with_is_taken_as_unknown():
    from poker_engine.desktop.aa_solver_input import solver_observation
    # 10/09: seat 3's stack read 0 after its ante of 2 went in. Starting the
    # table with 2 chips is refused, and the error stopped the window; the
    # seat is now replayed as deep, like a seat without a reading.
    stacks = {seat: Decimal(100) for seat in range(6)}
    hand = {**facts(stacks={**stacks, 3: Decimal(0)}), "board": BOARD + ["2s"]}
    assert 3 not in starting_stacks(hand, replay_hand(hand))
    observation, reason = solver_observation(hand, 2, ["Qs", "Qh"])
    assert reason is None and observation["stacks_unknown"] == [3]
    # Stacks the table refuses outright stop the replay instead of raising.
    assert replay_hand(hand, {**stacks, 3: Decimal(2)})["reason"] == "stacks_do_not_fit"


def test_a_fold_read_again_for_a_folded_seat_is_skipped():
    repeated = ACTIONS[:4] + [(15, "preflop", 3, "fold", "0")] + ACTIONS[4:]
    assert replay_hand(facts(repeated))["status"] == "ok"


def test_a_missed_fold_is_filled_in_from_the_table():
    missing = ACTIONS[:1] + ACTIONS[2:]              # seat 4's fold was not read
    hand = {**facts(missing), "states": {seat: "active" for seat in range(6)} | {
        3: "folded", 4: "folded", 0: "folded", 1: "folded"}, "price": None}
    result = replay_hand(hand)
    assert (result["status"], result["replayed"]) == ("ok", len(ACTIONS))
    assert [(a["slot"], a["kind"], a["source"]) for a in result["inferred"]] == [
        (4, "fold", "inferred")]


def test_a_check_missed_before_the_next_seats_bet_is_filled_in():
    # Seat 2's flop check is not read; seat 5 bets 10 and seat 2 calls.
    call = (40, "flop", 2, "call", "10")
    missed = ACTIONS[:6] + [ACTIONS[7], call]
    hand = {**facts(missed), "states": {seat: "active" for seat in range(6)}}
    result = replay_hand(hand)
    assert (result["status"], result["replayed"]) == ("ok", len(ACTIONS))
    assert [(a["slot"], a["kind"]) for a in result["inferred"]] == [(2, "check")]
    # Read a moment late, after the bet: the same check, not a second one.
    late = ACTIONS[:6] + [ACTIONS[7], (36, "flop", 2, "check", "0"), call]
    result = replay_hand({**hand, "actions": facts(late)["actions"]})
    assert (result["status"], result["replayed"]) == ("ok", len(ACTIONS))
    # A bet of seat 2's own on the table: it did not check.
    result = replay_hand({**hand, "board": BOARD, "wagers": {2: Decimal(6)}})
    assert result["status"] == "stopped"


def test_a_bet_read_after_the_calls_is_moved_before_them():
    late = ACTIONS[:7] + [(34, "flop", 2, "call", "10"), (36, "flop", 5, "raise", None)]
    hand = {**facts(late), "states": {2: "active", 5: "active"}, "price": None}
    result = replay_hand(hand)
    assert (result["status"], result["replayed"]) == ("ok", len(ACTIONS))
    assert [(a["slot"], a["kind"], a["amount"]) for a in result["inferred"]] == [
        (5, "raise", "10")]
    # Without the seat states nothing is filled in.
    assert replay_hand(facts(late))["status"] == "stopped"


def test_a_missed_raise_is_filled_in_from_the_seats_bet_on_the_table():
    # 10/08, five-handed plus one: dealer 2, small blind 3, big blind 4 (you),
    # straddle 5. Seat 0's raise to 27 was not read; the next seat folded to it,
    # so only its bet still on the table tells what it did.
    seen = [(133, "preflop", 7, "fold", "0"), (203, "preflop", 2, "fold", "0"),
            (240, "preflop", 3, "raise", "134")]
    hand = {**facts(seen, dealer=2, seats=[0, 2, 3, 4, 5, 7]), "board": [],
            "states": {0: "active", 2: "folded", 3: "active", 4: "active",
                       5: "active", 7: "folded"},
            "wagers": {0: Decimal(27), 4: Decimal(2), 5: Decimal(4)},
            "price": Decimal(133)}
    result = replay_hand(hand)
    assert (result["status"], result["replayed"]) == ("ok", len(seen) + 1)
    assert [(a["slot"], a["kind"], a["amount"]) for a in result["inferred"]] == [
        (0, "raise", "27")]
    assert result["arena"].actor == 4
    # A bet that only matches the price was a call; without a bet, no telling.
    called = replay_hand({**hand, "wagers": {0: Decimal(4)},
                          "actions": hand["actions"][:2]})
    assert [(a["slot"], a["kind"]) for a in called["inferred"]] == [(0, "call")]
    assert replay_hand({**hand, "wagers": {}})["status"] == "stopped"
    # A bet left from an earlier street says nothing about this one.
    flop = replay_hand({**hand, "board": ["Ah", "Kd", "7c"]})
    assert flop["status"] == "stopped"


def test_the_seats_before_yours_are_filled_in_from_your_price():
    hand = {**facts(ACTIONS[:6]), "states": {2: "active", 5: "active"},
            "price": Decimal(10)}
    arena = replay_hand(hand)["arena"]
    assert arena.actor == 2
    assert [(a["slot"], a["kind"], a["amount"]) for a in fill_to_seat(
        arena, 5, hand)] == [(2, "raise", "10")]
    checked = fill_to_seat(arena, 5, {**hand, "price": Decimal(0)})
    assert [(a["slot"], a["kind"]) for a in checked] == [(2, "call")]
    assert fill_to_seat(arena, 5, {**hand, "price": None}) is None
    # Your price unread: after the flop, the bets on the table give it.
    # Not in your turn's first frames: the action before yours is usually
    # read a moment after your buttons show.
    bets = {**hand, "price": None, "wagers": {2: Decimal(10)}, "turn_frames": 2}
    assert fill_to_seat(arena, 5, bets) is None
    assert [(a["slot"], a["kind"], a["amount"]) for a in fill_to_seat(
        arena, 5, {**bets, "turn_frames": 3})] == [(2, "raise", "10")]


def test_the_losers_fold_badge_at_the_showdown_does_not_stop_the_replay():
    checked_down = ACTIONS + [
        (40, "turn", 2, "check", "0"), (42, "turn", 5, "check", "0"),
        (50, "river", 2, "check", "0"), (52, "river", 5, "fold", "0")]
    result = replay_hand(facts(checked_down))
    assert (result["status"], result["replayed"]) == ("ok", len(checked_down))
    assert result["arena"].terminal                  # the fold counted as a check
    all_in = ACTIONS[:7] + [
        (32, "flop", 5, "all_in", "96"), (34, "flop", 2, "all_in", "96"),
        (60, "river", 5, "fold", "0"), (60, "river", 2, "fold", "0")]
    assert replay_hand(facts(all_in))["status"] == "ok"
    folded = ACTIONS[:8] + [(34, "flop", 2, "fold", "0"), (40, "flop", 5, "fold", "0")]
    assert replay_hand(facts(folded))["status"] == "ok"


def comeback(price, wagers=None):
    """Seat 3 is first to act after posting a big blind on coming back: 100
    before the hand, 2 ante, 2 posted, 96 behind."""
    stacks = {seat: Decimal(96 if seat == 3 else 100) for seat in range(6)}
    return {**facts(actions=[], stacks=stacks), "board": [],
            "wagers": wagers or {0: Decimal(1), 1: Decimal(2), 2: Decimal(4),
                                 3: Decimal(2)},
            "price": price}


def test_a_big_blind_posted_on_coming_back_is_live():
    from poker_engine.desktop.aa_solver_input import solver_observation
    observation, reason = solver_observation(comeback(Decimal(2)), 3, ["Qs", "Qh"])
    assert reason is None
    assert (observation["to_call"], observation["pot"], observation["posted"]) == (
        "2", "21", "2")                     # 6 antes + 1 + 2 + 4 + the post
    assert observation["bets"]["3"] == "2" and observation["stacks"]["3"] == "96"
    assert observation["betting"]["max_raise_to"] == "98"
    assert "raise_to:98" in [action["id"] for action in observation["legal_actions"]]


def test_a_post_counts_only_when_your_button_shows_the_price_it_leaves():
    from poker_engine.desktop.aa_solver_input import solver_observation
    plain, reason = solver_observation(comeback(Decimal(4), {}), 3, ["Qs", "Qh"])
    assert reason is None and plain["to_call"] == "4" and "posted" not in plain
    assert solver_observation(comeback(Decimal(3)), 3, ["Qs", "Qh"]) == (
        None, "price_does_not_match")
    unread, reason = solver_observation(comeback(None), 3, ["Qs", "Qh"])
    assert unread["to_call"] == "4" and "posted" not in unread


def short(behind, price=None, all_in=False):
    """Seat 3 first to act with 4 to call (no post) and ``behind`` left."""
    hand = comeback(price, {})
    return {**hand, "stacks": {**hand["stacks"], 3: behind}, "all_in": all_in}


def test_calling_your_whole_stack_needs_an_all_in_button():
    from poker_engine.desktop.aa_solver_input import solver_observation
    observation, reason = solver_observation(short(Decimal(3), all_in=True), 3,
                                             ["Qs", "Qh"])
    assert reason is None and observation["stacks"]["3"] == "3"
    # The table asks for every chip, but the button shows a check or a price
    # other than the stack: the hand was rebuilt wrong.
    for price in (Decimal(0), Decimal(4)):
        assert solver_observation(short(Decimal(3), price), 3, ["Qs", "Qh"]) == (
            None, "price_does_not_match")
    # "All in" with chips left after calling: wrong as well.
    assert solver_observation(short(Decimal(96), all_in=True), 3, ["Qs", "Qh"]) == (
        None, "price_does_not_match")


def test_an_all_in_button_counts_once_your_stack_is_read():
    shown = {"visible": True, "button": "all_in", "call_amount": "3"}
    found = rows()
    found[-1]["fields"] = {**found[-1]["fields"], "hero_controls": shown}
    assert hand_facts(found)["all_in"] is True and hand_facts(found)["price"] is None
    found[-1]["fields"]["hero_controls"] = {**shown, "call_amount": None}
    assert hand_facts(found)["all_in"] is False
    assert hand_facts(rows())["all_in"] is False


def test_only_chips_in_before_acting_beyond_the_blinds_are_a_post():
    from poker_engine.desktop.aa_solver_input import own_post
    hand = comeback(Decimal(2))
    observation = {"street": "preflop", "bets": {"1": "2", "3": "0"}}
    assert own_post(hand, observation, 3) == 2
    assert own_post(hand, observation, 1) == 0          # the big blind itself
    acted = {**hand, "actions": [{"frame": 1, "street": "preflop", "slot": 3,
                                  "kind": "call", "amount": "4"}]}
    assert own_post(acted, observation, 3) == 0
    assert own_post(hand, {**observation, "street": "flop"}, 3) == 0


# A bomb pot of six players, dealer 5: everyone put in 14; the flop is checked
# to seat 5, who bets 20.
BOMB_ACTIONS = [(30 + seat, "flop", seat, "check", "0") for seat in range(5)] + [
    (36, "flop", 5, "raise", "20")]


def bomb_hand(pot=Decimal(84), actions=BOMB_ACTIONS):
    return {**facts(actions=actions), "opening_pot": pot, "wagers": {}, "price": None}


def test_an_all_in_short_of_a_full_raise_is_the_seats_last_chips():
    # Seat 5 bets 10 on the flop; seat 2, with no stack reading, goes all in
    # for 12: short of a raise to 20, which only a seat's last chips may be.
    short = ACTIONS[:8] + [(34, "flop", 2, "all_in", "12")]
    result = replay_hand(facts(actions=short))
    assert (result["status"], result["replayed"]) == ("ok", len(short))
    seen = result["arena"].observe(5)
    assert (seen["stacks"]["2"], seen["bets"]["2"], seen["actor"]) == ("0", "12", 5)


def test_a_bomb_pot_is_replayed_from_the_flop():
    from poker_engine.desktop.aa_solver_input import bomb_post, solver_observation
    assert bomb_post(bomb_hand()) == 14
    result = replay_hand(bomb_hand())
    assert (result["status"], result["replayed"]) == ("ok", len(BOMB_ACTIONS))
    observation, reason = solver_observation(bomb_hand(), 0, ["Qs", "Qh"])
    assert reason is None
    assert (observation["street"], observation["bomb_pot"], observation["to_call"],
            observation["pot"]) == ("flop", "14", "20", "104")
    assert observation["straddler_seat"] is None


def test_only_a_flop_start_with_every_seat_posting_seven_big_blinds_is_a_bomb_pot():
    from poker_engine.desktop.aa_solver_input import bomb_post
    assert bomb_post(bomb_hand(pot=Decimal(85))) is None
    preflop = [(20, "preflop", 3, "fold", "0")] + BOMB_ACTIONS
    assert bomb_post(bomb_hand(actions=preflop)) is None
    assert bomb_post(bomb_hand(pot=None)) is None
    stopped = replay_hand(bomb_hand(pot=Decimal(85)))
    assert (stopped["status"], stopped["reason"]) == ("stopped", "starts_after_preflop")


def with_sources(actions, sources):
    hand = facts(actions)
    for action, source in zip(hand["actions"], sources):
        action["source"] = source
    return hand


def test_a_call_or_raise_seen_from_a_stack_drop_goes_by_its_chips():
    # Seat 5's flop bet of 10 and seat 2's call, both seen only from the stacks
    # and named the other way round.
    named_wrong = ACTIONS[:7] + [(32, "flop", 5, "call", "10"),
                                 (34, "flop", 2, "raise", "10")]
    sources = [None] * 7 + ["stack_drop", "stack_drop"]
    assert replay_hand(with_sources(named_wrong, sources))["status"] == "ok"
    short = ACTIONS[:8] + [(34, "flop", 2, "call", "5")]
    result = replay_hand(with_sources(short, [None] * 8 + ["stack_drop"]))
    assert (result["status"], result["reason"]) == ("stopped", "raise_without_amount")


def test_a_seat_all_in_without_a_stack_reading_is_not_asked_to_act_again():
    # Dealer 5: seat 3 goes all in for 10 more, seat 4 raises to 40, seat 5 calls.
    actions = [(10, "preflop", 3, "all_in", "10"), (12, "preflop", 4, "raise", "40"),
               (14, "preflop", 5, "call", "40"), (16, "preflop", 0, "fold", "0"),
               (18, "preflop", 1, "fold", "0"), (20, "preflop", 2, "fold", "0"),
               (30, "flop", 4, "check", "0"), (32, "flop", 5, "check", "0")]
    result = replay_hand(facts(actions))
    assert (result["status"], result["replayed"]) == ("ok", len(actions))
    assert result["arena"].street == "turn" and result["arena"].actor == 4


def test_another_seats_post_on_coming_back_counts_in_its_raise():
    # Seat 3 posted 2 on coming back, then put 19 more in: a raise to 21.
    actions = [(10, "preflop", 3, "raise", "19"), (12, "preflop", 4, "fold", "0"),
               (14, "preflop", 5, "fold", "0"), (16, "preflop", 0, "fold", "0"),
               (18, "preflop", 1, "fold", "0"), (20, "preflop", 2, "call", "17")]
    hand = {**facts(actions=actions), "board": [],
            "opening_wagers": {0: Decimal(1), 1: Decimal(2), 2: Decimal(4),
                               3: Decimal(2)}}
    result = replay_hand(hand)
    assert result["status"] == "ok"
    put = result["arena"].observe(3)["contributions"]
    assert (put["3"], put["2"]) == ("23", "23")         # 2 ante + 21
    unposted = replay_hand({**hand, "opening_wagers": {}})
    assert unposted["arena"].observe(3)["contributions"]["3"] == "21"


def test_the_bets_before_the_first_action_skip_the_antes_and_a_missed_badge():
    found = rows()
    for row in found:
        frame = row["processed"]
        wagers = ({str(seat): "2" for seat in range(6)} if frame == 3 else
                  {"0": "1", "1": "2", "2": "4", "3": "2"} if frame < 9 else
                  {"0": "1", "1": "2", "2": "4", "3": None} if frame == 9 else
                  {"3": "6"})
        row["fields"] = {**row["fields"], "street_wagers": wagers}
    assert hand_facts(found)["opening_wagers"] == {
        0: Decimal(1), 1: Decimal(2), 2: Decimal(4), 3: Decimal(2)}


def test_a_bet_missed_before_a_fold_comes_from_the_seats_bet_on_the_table():
    # Seat 5's flop bet of 10 is not read; seat 2 folds to it.
    missed = ACTIONS[:7] + [(36, "flop", 2, "fold", "0")]
    hand = {**facts(missed), "states": {2: "folded", 5: "active"}, "price": None,
            "wagers": {5: Decimal(10)}}
    result = replay_hand(hand)
    assert (result["status"], result["replayed"]) == ("ok", len(missed) + 1)
    assert [(a["slot"], a["kind"], a["amount"]) for a in result["inferred"]] == [
        (5, "raise", "10")]
    assert replay_hand({**hand, "wagers": {}})["status"] == "stopped"
