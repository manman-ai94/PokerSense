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


def dealt(hero, pot="23", **kwargs):
    item = payload(pot, **kwargs)
    return {**item, "cards": {**item["cards"], "hero": list(hero)}}


def test_your_new_cards_start_a_hand_the_other_signals_missed():
    # 杜's PC, 10/16: a hand that ended before the flop with no action read,
    # the pot never read going down and the button unread, then the next deal.
    history = AAActionHistory()
    feed(history, [dealt(["Kd", "7c"], dealer=None)] * 6)
    frames = [dealt(["4h", "Js"], dealer=None)] * 5
    hands = [history.observe(item, 6 + at) for at, item in enumerate(frames)]
    first = hands[0]["hand_id"]
    same = [hand["hand_id"] == first for hand in hands]
    assert same == [True, True, False, False, False]
    assert hands[2]["start"] == "new_hole_cards" and hands[2]["complete"] is False
    assert hands[4]["hand_id"] == hands[2]["hand_id"]


def test_a_card_read_another_way_or_the_last_hands_cards_are_no_new_deal():
    history = AAActionHistory()
    feed(history, [dealt(["3d", "5c"])] * 6)
    # Dimmed after the fold: one card read with another suit.
    dim = [history.observe(dealt(["3s", "5c"]), 6 + at) for at in range(6)]
    assert {hand["hand_id"] for hand in dim} == {"hand_0"}
    # The next hand starts by the pot; your last cards are still on screen.
    history.observe(dealt(["3d", "5c"], pot="88"), 12)
    history.observe(dealt(["3d", "5c"], pot="88"), 13)
    history.observe(dealt(["3d", "5c"]), 14)
    start = history.observe(dealt(["3d", "5c"]), 15)
    assert start["start"] == "pot_went_down"
    new = [history.observe(dealt(["Ah", "9s"]), 16 + at) for at in range(5)]
    assert {hand["hand_id"] for hand in new} == {start["hand_id"]}


def test_cards_read_only_a_moment_are_no_new_deal():
    history = AAActionHistory()
    feed(history, [dealt(["Kd", "7c"])] * 6)
    blip = [dealt(["4h", "Js"])] * 2 + [dealt(["Kd", "7c"])] + [dealt(["4h", "Js"])] * 2
    hands = [history.observe(item, 6 + at) for at, item in enumerate(blip)]
    assert {hand["hand_id"] for hand in hands} == {"hand_0"}


def watch(history, start=0):
    frame = start

    def see(item):
        nonlocal frame
        snap = history.observe(item, frame)
        frame += 1
        return snap
    return see


def test_a_deal_after_a_played_hand_with_no_action_read_is_no_missed_start():
    # Nightly check 10/17 (#125): hand B is played (the pot rises) with no
    # action read; the pot going down starts the next deal and is taken as
    # B's start again, B's cards still on screen. The new cards must not
    # then start a hand "whose start was missed".
    see = watch(AAActionHistory())
    folded = [event(1, 2, "fold")]
    for _ in range(4):
        see({**dealt(["Ad", "Qc"], pot="88"), "action_history_candidate": folded})
    see({**dealt(["Kd", "7c"]), "action_history_candidate": folded})
    b = see({**dealt(["Kd", "7c"]), "action_history_candidate": folded})
    assert b["start"] == "pot_went_down" and b["complete"] is True
    for pot in ["31"] * 4 + ["23"] * 2:
        see({**dealt(["Kd", "7c"], pot=pot), "action_history_candidate": folded})
    c = [see({**dealt(["4h", "Js"]), "action_history_candidate": folded})
         for _ in range(5)]
    assert {hand["hand_id"] for hand in c} == {b["hand_id"]}
    assert c[-1]["complete"] is True


def test_signals_after_your_new_cards_mark_the_same_deal():
    # Your new cards are read before the pot (unreadable as the deal starts)
    # is read going down: one deal, and the next deal's cards start a hand.
    see = watch(AAActionHistory())
    for _ in range(6):
        see(dealt(["Kd", "7c"], pot="88"))
    deal = [see(dealt(["4h", "Js"], pot=None)) for _ in range(4)]
    deal += [see(dealt(["4h", "Js"])) for _ in range(3)]
    assert len({hand["hand_id"] for hand in deal[2:]}) == 1
    assert deal[-1]["start"] == "new_hole_cards"
    nxt = [see(dealt(["Qs", "Qh"])) for _ in range(4)]
    assert nxt[-1]["hand_id"] != deal[-1]["hand_id"]
    assert nxt[-1]["start"] == "new_hole_cards"


def test_the_button_read_after_your_new_cards_keeps_them_this_hands():
    # The pot goes down, your new cards are read, then the button is read
    # moving: the same start, and the cards stay this hand's, so the next
    # deal's cards still start a hand when nothing else is read.
    see = watch(AAActionHistory())
    for _ in range(4):
        see({**dealt(["Ad", "Qc"], pot="88"),
             "action_history_candidate": [event(1, 2, "fold")]})
    see(dealt(["Ad", "Qc"], pot="0"))
    start = see(dealt(["Ad", "Qc"], pot="0"))
    assert start["start"] == "pot_went_down"
    for pot in ["0", "19", "19"]:
        see(dealt(["Kd", "7c"], pot=pot))
    moved = [see(dealt(["Kd", "7c"], pot="19", dealer=0)) for _ in range(3)]
    assert {hand["hand_id"] for hand in moved} == {start["hand_id"]}
    nxt = [see(dealt(["4h", "Js"], pot="19", dealer=0)) for _ in range(4)]
    assert nxt[-1]["start"] == "new_hole_cards"


def test_a_played_deal_found_by_your_cards_ends_at_the_next_pot_drop():
    see = watch(AAActionHistory())
    for _ in range(6):
        see(dealt(["Kd", "7c"], pot="88"))
    pots = [None] * 4 + ["23"] * 3 + ["40"] * 3   # the pot rises: it is played
    deal = [see(dealt(["4h", "Js"], pot=pot)) for pot in pots]
    assert len({hand["hand_id"] for hand in deal[2:]}) == 1
    assert deal[-1]["start"] == "new_hole_cards"
    drop = [see(dealt(["4h", "Js"])) for _ in range(2)]
    assert drop[-1]["hand_id"] != deal[-1]["hand_id"]
    assert drop[-1]["start"] == "pot_went_down" and drop[-1]["complete"] is True


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


def unread_pot_bet(street="flop", frames=40, back=None):
    """Seat 3 bets 44 on ``street`` while the pot cannot be read; its bet on
    the table reads 44. With ``back`` the pot comes back at that value."""
    pots = ["29"] * 5 + [None] * frames + ([back] * 10 if back else [])
    return [{**payload(pot, street),
             "street_wagers": {"3": "44" if i >= 7 else None},
             "action_history_candidate": [event(6, 3, "aggressive")] if i > 6 else []}
            for i, pot in enumerate(pots)]


def test_a_bet_while_the_pot_is_unreadable_is_priced_by_the_bet_on_the_table():
    # 10/09: bets and all-ins waited for an unreadable pot, and the replay
    # stopped on a raise without an amount at your turn.
    hand = feed(AAActionHistory(), unread_pot_bet())
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("44", "wager")]
    assert hand["pending_amounts"] == 0
    # The pot read again settles it: the rise holds just that bet.
    hand = feed(AAActionHistory(), unread_pot_bet(back="73"))
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("44", "pot_rise")]
    # Before the flop the blinds are in the bet too: it waits for the pot.
    hand = feed(AAActionHistory(), unread_pot_bet("preflop"))
    assert [a["amount_source"] for a in hand["actions"]] == ["pending"]


def test_an_all_in_while_the_pot_is_unreadable_is_confirmed_by_the_bet_on_the_table():
    frames = [{**item, "pot": {"value": None if i >= 10 else item["pot"]["value"]},
               "street_wagers": {"1": "448" if i >= 10 else None}}
              for i, item in enumerate(shove())]
    hand = feed(AAActionHistory(), frames)
    assert [(a["kind"], a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("all_in", "448", "stack")]
    # Without the bet read it still waits for the pot.
    frames = [{**item, "street_wagers": {}} for item in frames]
    hand = feed(AAActionHistory(), frames)
    assert [a["amount_source"] for a in hand["actions"]] == ["pending"]


def test_a_moment_with_nobody_read_after_the_flop_does_not_end_the_hand():
    history = AAActionHistory()
    feed(history, [payload("23")] * 3 + [payload("40", "flop")] * 3)
    # Board and seats unread for a frame while the street layer holds the flop.
    blink = {**payload("40", "flop", in_hand=False), "street_v1": {"street": "flop"}}
    blink["cards"] = {"board_slots": [None] * 5, "hero": []}
    first = history.observe(blink, 6)
    later = history.observe(payload("40", "flop"), 7)
    assert later["hand_id"] == first["hand_id"] == "hand_0"


def bet_unread(seat="0", drop=51, rise=51, fold=False, unread=0):
    """Seat ``seat`` bets on the flop without its badge being read: its stack
    goes 590 -> 590 - drop while the pot goes 47 -> 47 + rise. ``unread``
    frames of no stack reading before the drop; ``fold``: the seat folded
    preflop (its fold read)."""
    frames = [stacked(payload("17"), {seat: "590", "3": "500"})] * 5
    frames += [stacked(payload("47", "flop"), {seat: "590", "3": "500"})] * 5
    frames += [stacked(payload("47", "flop"), {"3": "500"})] * unread
    frames += [stacked(payload(str(47 + rise), "flop"),
                       {seat: str(590 - drop), "3": "500"})] * 20
    if fold:
        frames = [{**item, "action_history_candidate":
                   [event(2, int(seat), "fold")] if i > 2 else []}
                  for i, item in enumerate(frames)]
    return frames


def test_a_bet_whose_badge_was_missed_is_seen_from_the_stack_drop():
    hand = feed(AAActionHistory(), bet_unread())
    assert [(a["street"], a["slot"], a["kind"], a["amount"], a["amount_source"])
            for a in hand["actions"]] == [("flop", 0, "raise", "51", "stack_drop")]


def test_a_stack_drop_needs_a_pot_rise_of_just_those_chips():
    assert feed(AAActionHistory(), bet_unread(drop=50))["actions"] == []


def test_a_folded_seat_or_a_stack_unread_for_a_while_adds_nothing():
    folded = feed(AAActionHistory(), bet_unread(fold=True))
    assert [(a["slot"], a["kind"]) for a in folded["actions"]] == [(0, "fold")]
    assert feed(AAActionHistory(), bet_unread(unread=40))["actions"] == []


def test_blinds_going_in_before_the_hands_first_pot_add_nothing():
    # The last hand's pot is taken away; antes and blinds go in, then the pot shows.
    frames = [stacked(payload("300", "river"), {"0": "590", "7": "246"})] * 5
    frames += [stacked(payload("0"), {"0": "590", "7": "246"})] * 5
    frames += [stacked(payload("0"), {"0": "586", "7": "243"})] * 5
    frames += [stacked(payload("17"), {"0": "586", "7": "243"})] * 10
    assert feed(AAActionHistory(), frames)["actions"] == []


def test_a_badge_read_after_the_stack_drop_names_the_action_once():
    frames = bet_unread()
    frames = [{**item, "action_history_candidate":
               [event(10, 0, "call")] if i > 14 else []}
              for i, item in enumerate(frames)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["slot"], a["kind"], a["amount"], a["amount_source"])
            for a in hand["actions"]] == [(0, "call", "51", "stack_drop")]


def test_a_call_badge_read_again_is_one_call():
    frames = [payload("17")] * 3 + [payload("21")] * 10 + [payload("21")] * 10
    frames = [{**item, "action_history_candidate":
               [event(3, 5, "call")] + ([event(15, 5, "call")] if i > 15 else [])}
              for i, item in enumerate(frames)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["frame"], a["slot"], a["kind"]) for a in hand["actions"]] == [
        (3, 5, "call")]


def test_badges_read_again_after_a_stall_are_left_out():
    # After a stall the reader starts over and reads every badge still on the
    # table again: the checks and the fold are already in, the bet is new.
    first = [event(2, 0, "check"), event(3, 3, "fold"), event(4, 7, "check")]
    again = [event(12, 0, "check"), event(12, 3, "fold"), event(12, 7, "check")]
    frames = [payload("70", "flop", actions=first)] * 12 + [
        payload("70", "flop", actions=again)] * 3 + [
        payload("70", "flop", actions=again + [event(15, 1, "raise")])] * 2 + [
        payload("112", "flop", actions=again + [event(15, 1, "raise")])] * 15
    hand = feed(AAActionHistory(), frames)
    assert [(a["frame"], a["slot"], a["kind"], a["amount"])
            for a in hand["actions"]] == [
        (2, 0, "check", "0"), (3, 3, "fold", "0"), (4, 7, "check", "0"),
        (15, 1, "raise", "42")]


def raise_from_empty_pot(drop_at=8, stack="446"):
    """10/10 A6: the pot is first read at 35 with the blinds (19) and seat 2's
    raise (16) in it; seat 2's stack was read going 462 -> 446."""
    frames = [stacked(payload("0"), {"2": "462"})] * 5
    frames += [stacked(payload("35"), {"2": "462" if i < drop_at - 5 else stack})
               for i in range(5, 40)]
    return [{**item, "action_history_candidate":
             [event(6, 2, "aggressive")] if i > 6 else []}
            for i, item in enumerate(frames)]


def test_a_raise_in_the_first_rise_from_an_empty_pot_is_priced_by_its_stack_drop():
    hand = feed(AAActionHistory(), raise_from_empty_pot())
    assert [(a["slot"], a["kind"], a["amount"], a["amount_source"])
            for a in hand["actions"]] == [(2, "raise", "16", "stack_drop")]
    # A drop far from the badge is some other chips: still unknown.
    hand = feed(AAActionHistory(), raise_from_empty_pot(drop_at=30))
    assert hand["actions"][0]["amount_source"] == "unknown"


def test_a_raise_before_the_flop_while_the_pot_is_unreadable_takes_its_stack_drop():
    frames = [{**stacked(item, {"3": "500" if i < 7 else "456"}),
               "pot": {"value": item["pot"]["value"]}}
              for i, item in enumerate(unread_pot_bet("preflop"))]
    hand = feed(AAActionHistory(), frames)
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("44", "stack_drop")]
    # The pot read again settles it: a smaller rise wins.
    frames = [{**stacked(item, {"3": "500" if i < 7 else "456"})}
              for i, item in enumerate(unread_pot_bet("preflop", back="69"))]
    hand = feed(AAActionHistory(), frames)
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("40", "pot_rise")]


def test_two_seats_putting_chips_in_while_the_pot_is_unreadable_each_get_their_own():
    # 10/09 053249: the pot went 25 -> 62 unread; the whole 37 used to go to
    # your raise and the call after it had no amount. Stacks: 286 -> 267,
    # 500 -> 482; the call takes what is left of the rise.
    pots = ["25"] * 5 + [None] * 40 + ["62"] * 10
    frames = [{**stacked(payload(pot), {"4": "286" if i < 7 else "267",
                                        "6": "500" if i < 12 else "482"}),
               "action_history_candidate":
               [e for e in (event(6, 4, "aggressive"), event(11, 6, "call"))
                if e["frame"] < i]}
              for i, pot in enumerate(pots)]
    hand = feed(AAActionHistory(), frames)
    assert [(a["slot"], a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        (4, "19", "stack_drop"), (6, "18", "pot_rise")]


def test_a_stack_read_while_its_chips_moved_counts_both_steps():
    frames = [{**stacked(item, {"3": "500" if i < 7 else "480" if i < 10 else "456"}),
               "pot": {"value": item["pot"]["value"]}}
              for i, item in enumerate(unread_pot_bet("preflop"))]
    hand = feed(AAActionHistory(), frames)
    assert [(a["amount"], a["amount_source"]) for a in hand["actions"]] == [
        ("44", "stack_drop")]
