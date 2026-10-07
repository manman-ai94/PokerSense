"""The rebuilt betting history: amounts from pot rises, streets from the board,
hands from pot drops, cleared boards and a moving dealer button."""

from poker_engine.desktop.aa_action_history import AAActionHistory, steady_runs

BOARD = {"preflop": [], "flop": ["5h", "6c", "6s"], "turn": ["5h", "6c", "6s", "Tc"]}


def payload(pot, street="preflop", dealer=7, actions=(), in_hand=True):
    board = BOARD.get(street, [])
    return {"scene_supported": True, "pot": {"value": pot},
            "street_v1": {"street": street if in_hand else None},
            "dealer_seat": dealer,
            "cards": {"board_slots": board + [None] * (5 - len(board)), "hero": []},
            "seat_states_v1": {"seats": {"3": {"state": "active" if in_hand
                                               else "empty"}}},
            "action_history_candidate": list(actions)}


def event(frame, slot, kind, amount=None):
    return {"frame": frame, "slot": slot, "kind": kind, "amount": amount}


def feed(history, frames):
    result = None
    for frame, item in enumerate(frames):
        result = history.observe(item, frame)
    return result


def test_steady_runs_need_two_readings():
    pots = [(0, 1), (1, 1), (2, 5), (3, 7), (4, 7)]
    assert steady_runs(pots) == [(1, 0, 1), (7, 3, 4)]


def test_amounts_come_from_the_pot_rise_next_to_each_action():
    seen = [event(4, 3, "call"), event(9, 5, "aggressive")]
    frames = ([payload("23")] * 3 + [payload("27")] * 5 + [payload("57")] * 20)
    frames = [{**item, "action_history_candidate": seen[:1] if 5 <= i < 10 else
               seen if i >= 10 else []} for i, item in enumerate(frames)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["slot"], a["kind"], a["amount"], a["amount_source"])
            for a in hand["actions"]] == [(3, "call", "4", "pot_rise"),
                                          (5, "raise", "30", "pot_rise")]
    assert hand["pending_amounts"] == hand["missing_amounts"] == 0


def test_without_a_pot_rise_the_reader_amount_or_unknown_is_kept():
    seen = [event(2, 3, "call", "4"), event(3, 6, "call")]
    frames = [{**payload("23"), "action_history_candidate": seen}] * 30
    hand = feed(AAActionHistory(), frames)
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("4", "cash"), (None, "unknown")]
    assert hand["missing_amounts"] == 1


def test_streets_come_from_the_board_at_the_action_frame():
    seen = [event(1, 3, "check"), event(6, 4, "check")]
    frames = [payload("50")] * 4 + [payload("50", "flop")] * 6
    # An action reaches the history a little after its own frame.
    frames = [{**item,
               "action_history_candidate": [e for e in seen if e["frame"] < i]}
              for i, item in enumerate(frames)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["street"], a["amount"]) for a in hand["actions"]] == [
        ("preflop", "0"), ("flop", "0")]


def test_new_hands_start_when_the_pot_drops_or_the_dealer_moves():
    history = AAActionHistory()
    first = feed(history, [payload("23")] * 3 + [payload("88")] * 4)
    assert first["start"] == "first_hand_seen" and first["complete"] is False
    history.observe(payload("23"), 7)
    dropped = history.observe(payload("23"), 8)
    assert dropped["start"] == "pot_went_down" and dropped["complete"] is True
    folded = {**payload("23"), "action_history_candidate": [event(9, 3, "fold")]}
    history.observe(folded, 10)
    history.observe({**payload("23", dealer=0), **{"action_history_candidate": []}}, 11)
    moved = history.observe(payload("23", dealer=0), 12)
    assert moved["start"] == "dealer_moved" and moved["dealer"] == 0
    assert moved["actions"] == []


def test_signals_between_hands_mark_one_start():
    history = AAActionHistory()
    feed(history, [payload("23")] * 3 + [payload("88")] * 4)
    history.observe(payload("23"), 7)
    start = history.observe(payload("23"), 8)
    history.observe(payload("23", dealer=0), 9)
    later = history.observe(payload("23", dealer=0), 10)
    assert later["hand_id"] == start["hand_id"] and later["dealer"] == 0


def test_a_hand_over_ends_the_hand_and_old_actions_stay_with_it():
    history = AAActionHistory()
    feed(history, [payload("23")] * 3 + [payload("40", "flop")] * 3)
    history.observe(payload(None, in_hand=False), 6)
    late = [event(5, 2, "fold")]                  # confirmed after the hand ended
    hand = history.observe({**payload("23"), "action_history_candidate": late}, 7)
    assert hand["start"] == "after_hand_over" and hand["actions"] == []


def test_a_rise_hidden_by_an_unreadable_pot_still_counts():
    # The pot cannot be read for a while right after the call.
    pots = ["48"] * 10 + [None] * 30 + ["67"] * 10
    frames = [{**payload(pot), "action_history_candidate":
               [event(10, 4, "call")] if i > 10 else []} for i, pot in enumerate(pots)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("19", "pot_rise")]


def test_each_action_takes_its_own_rise_across_a_gap():
    # The raise went in while the pot was unreadable; the call follows soon.
    pots = ["67"] * 5 + [None] * 9 + ["111"] * 14 + ["166"] * 13
    seen = [event(15, 3, "aggressive"), event(29, 4, "call")]
    frames = [{**payload(pot), "action_history_candidate":
               [e for e in seen if e["frame"] < i]} for i, pot in enumerate(pots)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["slot"], a["amount"]) for a in hand["actions"]] == [(3, "44"), (4, "55")]


def test_the_rise_from_an_empty_pot_is_the_blinds_not_an_action():
    pots = ["0"] * 5 + ["19"] * 5 + ["23"] * 20
    frames = [{**payload(pot), "action_history_candidate":
               [event(5, 6, "call")] if i > 5 else []} for i, pot in enumerate(pots)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("4", "pot_rise")]


def test_a_call_after_the_flop_is_priced_by_the_betting():
    # The pot is unreadable from the flop call until after the turn bet, so a
    # single rise of 63 holds the call (19) and the turn bet (44).
    pots = ["29"] * 5 + ["48"] * 10 + [None] * 40 + ["111"] * 12 + ["155"] * 20
    streets = ["flop"] * 50 + ["turn"] * 37
    seen = [event(6, 3, "aggressive"), event(16, 4, "call"),
            event(56, 3, "aggressive"), event(68, 4, "call")]
    frames = [{**payload(pot, street), "action_history_candidate":
               [e for e in seen if e["frame"] < i]}
              for i, (pot, street) in enumerate(zip(pots, streets))]
    hand = feed(AAActionHistory(), frames)
    assert [(a["street"], a["slot"], a["amount"], a["amount_source"])
            for a in hand["actions"]] == [
        ("flop", 3, "19", "pot_rise"), ("flop", 4, "19", "street_logic"),
        ("turn", 3, "44", "pot_rise"), ("turn", 4, "44", "pot_rise")]


def test_a_call_without_a_readable_rise_still_gets_what_it_owed():
    pots = ["29"] * 5 + ["48"] * 15 + [None] * 150
    seen = [event(6, 3, "aggressive"), event(20, 4, "call")]
    frames = [{**payload(pot, "flop"), "action_history_candidate":
               [e for e in seen if e["frame"] < i]} for i, pot in enumerate(pots)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("19", "pot_rise"), ("19", "street_logic")]


def test_a_call_after_the_flop_has_its_chips_before_the_pot_is_read():
    pots = ["29"] * 5 + ["48"] * 15 + [None] * 5
    seen = [event(6, 3, "aggressive"), event(20, 4, "call")]
    frames = [{**payload(pot, "flop"), "action_history_candidate":
               [e for e in seen if e["frame"] < i]} for i, pot in enumerate(pots)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("19", "pot_rise"), ("19", "street_logic")]
    assert hand["pending_amounts"] == 0


def stacked(item, stacks):
    return {**item,
            "stacks": {slot: {"value": value} for slot, value in stacks.items()}}


def shove(extra_frames=0, seen=(), seen_from=0):
    """Seat 1 (448 behind) goes all in on the flop: the pot goes 58 -> 506."""
    pots = ["58"] * 10 + ["506"] * (20 + extra_frames)
    return [{**stacked(payload(pot, "flop"), {"1": "448" if i < 10 else "0"}),
             "action_history_candidate": [e for e in seen if i >= seen_from]}
            for i, pot in enumerate(pots)]


def test_a_stack_dropping_to_zero_next_to_a_pot_rise_is_an_all_in():
    hand = feed(AAActionHistory(), shove())
    assert [(a["street"], a["slot"], a["kind"], a["amount"], a["amount_source"])
            for a in hand["actions"]] == [("flop", 1, "all_in", "448", "stack")]


def test_a_stack_at_zero_without_a_pot_rise_adds_nothing():
    frames = [stacked(payload("58", "flop"), {"1": "448" if i < 10 else "0"})
              for i in range(40)]
    assert feed(AAActionHistory(), frames)["actions"] == []


def test_an_all_in_is_not_counted_twice_when_the_reader_sees_it_too():
    before = feed(AAActionHistory(), shove(seen=[event(10, 1, "aggressive")],
                                           seen_from=11))
    assert [(a["kind"], a["amount"]) for a in before["actions"]] == [("raise", "448")]
    later = feed(AAActionHistory(), shove(seen=[event(10, 1, "all_in")], seen_from=20))
    assert [(a["kind"], a["amount"], a["amount_source"]) for a in later["actions"]] == [
        ("all_in", "448", "stack")]


def test_a_call_after_an_all_in_owes_the_all_in():
    frames = shove() + [stacked(payload("954", "flop"), {"1": "0"})] * 20
    frames = [{**item, "action_history_candidate":
               [event(31, 3, "call")] if i > 31 else []}
              for i, item in enumerate(frames)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["slot"], a["kind"], a["amount"], a["amount_source"])
            for a in hand["actions"]] == [(1, "all_in", "448", "stack"),
                                          (3, "call", "448", "pot_rise")]
