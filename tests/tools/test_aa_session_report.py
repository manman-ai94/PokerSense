"""The session report counts your decisions, the advice and why none came."""

from tools.aa_session_report import session_report


def row(frame, pts, *, hand="hand_0", turn=False, cards=("As", "Kd"), advice=None,
        published=None, stack="100", pot=10, actions=()):
    return {"processed": frame, "pts_seconds": pts,
            "timing": {"published_at": pts if published is None else published},
            "fields": {"scene_supported": True, "hero": list(cards) if cards else None,
                       "participants": {"4": "active", "5": "active"},
                       "hero_controls": {"visible": turn}, "street": "preflop",
                       "stacks": {"4": stack}, "pot": pot,
                       "actions_v1": {"hand_id": hand, "complete": False,
                                      "start": "boundary", "dealer": 5,
                                      "actions": [list(a) for a in actions]},
                       "solver_advice": advice or {"status": "idle",
                                                   "reason": "not_your_turn"}}}


def test_decisions_advice_causes_and_stalls_are_counted():
    ready = {"status": "ready", "kind": "preflop", "advice": [{"action": "FOLD"}]}
    waiting = {"status": "idle", "reason": "waiting_for_last_action"}
    rows = ([row(f, f * 0.1) for f in range(5)]
            + [row(5, 0.5, turn=True, advice=waiting),
               row(6, 0.6, turn=True, advice=ready)]
            + [row(f, f * 0.1, hand="hand_9") for f in range(7, 12)]
            + [row(12, 1.2, hand="hand_9", turn=True, cards=None,
                   advice={"status": "idle", "reason": "your_cards_not_read"}),
               row(13, 1.3, hand="hand_9", published=5.0)])
    report = session_report([("log", rows)])
    summary = report["summary"]
    counts = summary["hands"], summary["your_decisions"], summary["advised"]
    assert counts == (2, 2, 1)
    assert summary["no_advice_causes"] == {"idle:your_cards_not_read": 1}
    assert summary["stalls_over_2s"] == 1
    # One hand of two had advice on every one of your decisions; neither
    # went past the flop.
    assert summary["fully_advised"] == {"hands": 2, "advised": 1, "past_preflop": 0,
                                        "past_preflop_advised": 0}
    assert summary["advised_by_kind"] == {"preflop": 1}
    first, second = report["hands"]
    assert first["decisions"][0]["first_ready"] == 0.1
    assert first["your_cards"] == "As Kd" and first["your_cards_readings"] == 1
    assert second["decisions"][0]["cards_read"] is False


def test_a_card_read_two_ways_in_one_hand_is_flagged():
    rows = ([row(f, f * 0.1) for f in range(4)]
            + [row(f, f * 0.1, cards=("Ah", "Kd")) for f in range(4, 8)])
    for item in rows:
        item["fields"]["board"] = ["7c", "8d", "9h", None, None]
    for item in rows[3:6]:
        item["fields"]["board"] = ["7c", "8d", "9s", None, None]
    summary = session_report([("log", rows)])["summary"]
    assert summary["hand_problems"] == {"your_cards_read_two_ways": 1,
                                        "board_card_read_two_ways": 1}
    # The last hand's board still showing as this one starts does not count.
    for item in rows[:3]:
        item["fields"]["board"] = ["Qs", "Js", "2d", None, None]
    for item in rows[3:]:
        item["fields"]["board"] = ["7c", "8d", "9h", None, None]
    summary = session_report([("log", rows)])["summary"]
    assert summary["hand_problems"] == {"your_cards_read_two_ways": 1}


def test_what_you_did_your_chips_and_a_hand_split_in_two():
    raise_ = {"status": "ready", "kind": "preflop", "advice": [{"action": "raise"}]}
    you = [(5, "preflop", 4, "all_in", "100", "pot_rise")]
    rows = ([row(f, f * 0.1, stack="100") for f in range(4)]
            + [row(4, 0.4, turn=True, advice=raise_),
               row(5, 0.5, actions=you, stack="0", pot=210)]
            # The same hand goes on as if a new one had started.
            + [row(f, f * 0.1, hand="hand_6", stack="0", pot=210) for f in range(6, 9)]
            + [row(f, f * 0.1, hand="hand_9", cards=("2c", "7d"), stack="205")
               for f in range(9, 12)])
    report = session_report([("log", rows)])
    first, second, third = report["hands"]
    assert first["decisions"][0]["you_did"] == "raise"
    assert first["decisions"][0]["followed"] is True
    assert (first["your_chips"], second["your_chips"]) == (105.0, None)
    assert second["split_from"] == "hand_0"
    summary = report["summary"]
    assert summary["hand_problems"]["hand_split_in_two"] == 1
    assert summary["followed_advice"] == summary["advised_and_action_seen"] == 1
    assert summary["your_chips_by_advice"]["yes"] == {"hands": 1, "chips": 105.0}
    assert summary["by_players"][2]["advised"] == 1


def busted_rows(after, *, rebuy=None):
    """You (100 chips) go all in and lose: your stack reads 0 to the end of
    the hand. ``after``: "sits out" (a whole hand goes by without you, your
    stack 0, then ``rebuy`` read late in it), "dealt in" (the next hand deals
    you in with 205) or "ends" (the recording stops)."""
    rows = ([row(f, f * 0.1, stack="100") for f in range(4)]
            + [row(f, f * 0.1, stack="0", pot=210) for f in range(4, 8)])
    for item in rows:
        item["fields"]["actions_v1"]["complete"] = True
    if after == "sits out":
        for f in range(8, 16):
            late = rebuy if rebuy and f >= 14 else "0"
            item = row(f, f * 0.1, hand="hand_8", cards=None, stack=late, pot=30)
            item["fields"]["participants"] = {"4": "waiting", "5": "active"}
            item["fields"]["actions_v1"]["complete"] = True
            rows.append(item)
        rows += [row(f, f * 0.1, hand="hand_16", cards=("2c", "7d"),
                     stack=rebuy or "200") for f in range(16, 22)]
    elif after == "dealt in":
        rows += [row(f, f * 0.1, hand="hand_8", cards=("2c", "7d"), stack="205")
                 for f in range(8, 14)]
    return rows


def test_a_bust_costs_your_whole_stack():
    # Sat out the next hand: until 10/16 no stack was read after the hand,
    # so it was left out.
    first = session_report([("log", busted_rows("sits out"))])["hands"][0]
    assert first["your_chips"] == -100.0
    # A rebuy read in the hand sat out is not what you had after the bust
    # (10/07: 186 all in, lost, rebought 196, counted +10).
    first = session_report([("log", busted_rows("sits out", rebuy="110"))])["hands"][0]
    assert first["your_chips"] == -100.0
    # The recording ends after the hand you busted in.
    first = session_report([("log", busted_rows("ends"))])["hands"][0]
    assert first["your_chips"] == -100.0
    # Dealt in the next hand with chips: you won, as before.
    first = session_report([("log", busted_rows("dealt in"))])["hands"][0]
    assert first["your_chips"] == 105.0


def test_a_hand_cut_off_all_in_is_not_a_bust():
    rows = busted_rows("ends")
    for item in rows:
        item["fields"]["actions_v1"]["complete"] = False
    assert session_report([("log", rows)])["hands"][0]["your_chips"] is None


def test_buttons_read_while_your_seat_sits_out_are_not_a_turn():
    sitting = row(3, 0.3, turn=True, cards=None,
                  advice={"status": "idle", "reason": "your_cards_not_read"})
    sitting["fields"]["participants"] = {"4": "waiting", "5": "active"}
    rows = [row(f, f * 0.1) for f in range(3)] + [sitting, row(4, 0.4)]
    assert session_report([("log", rows)])["summary"]["your_decisions"] == 0
    # Dealt in a frame later, cards read: still not a turn.
    dealt = row(4, 0.4, turn=True)
    rows = [row(f, f * 0.1) for f in range(3)] + [sitting, dealt, row(5, 0.5)]
    assert session_report([("log", rows)])["summary"]["your_decisions"] == 0
    # Seated, cards unread: a turn without advice.
    seated = {**sitting, "fields": {**sitting["fields"],
                                    "participants": {"4": "active", "5": "active"}}}
    rows = [row(f, f * 0.1) for f in range(3)] + [seated, row(4, 0.4)]
    assert session_report([("log", rows)])["summary"]["your_decisions"] == 1


def test_cards_shown_with_the_seat_s_actions():
    acts = [(1, "preflop", 5, "call", "2", "pot_rise"),
            (2, "flop", 5, "check", "0", "glyph"),
            (3, "flop", 4, "bet", "6", "pot_rise"),
            (4, "flop", 5, "call", "6", "pot_rise")]
    rows = [row(f, f * 0.1, actions=acts[:f]) for f in range(5)]
    rows[-1]["fields"]["shown_cards"] = {
        "hand_id": "hand_0", "seats": {"5": {"cards": ["Qh", "Qs"], "frame": 4}},
        "unknown": ["2"]}
    report = session_report([("log", rows)])
    hand = report["hands"][0]
    # The hand was joined midway: it does not replay, so no range was read.
    assert hand["shown_cards"] == [{"seat": 5, "cards": ["Qh", "Qs"], "actions": {
        "preflop": ["call 2"], "flop": ["check", "call 6"]},
        "range_read": {"skipped": "no_replay"}}]
    assert hand["shown_unknown"] == [2]
    assert report["summary"]["shown_cards"] == {"hands": 1, "seats": 1,
                                                "seats_unknown": 1}


def test_each_hand_pays_its_own_blinds_antes_and_mushroom_post():
    """Your stack is read once the pot holds the hand's blinds and antes, so
    each hand's chips add back what it posted (10/17: a hand counted the next
    hand's posts instead, a folded small blind cost 4 big blinds on
    1/2/4(2), the dealer's mushroom post and ante)."""
    def hand(name, start, dealer, stack, cards):
        rows = [row(start + f, (start + f) * 0.1, hand=name, stack=stack, cards=cards)
                for f in range(6)]
        for item in rows:
            item["fields"]["participants"] = {str(seat): "active" for seat in range(8)}
            item["fields"]["actions_v1"]["dealer"] = dealer
        return rows
    # 100 chips: the small blind (1 and the ante 2), fold; the dealer
    # (ante 2 and the mushroom post of 3 big blinds), fold; then the cutoff.
    rows = (hand("hand_0", 0, 3, "97", ("7c", "2d"))
            + hand("hand_6", 6, 4, "89", ("8c", "3d"))
            + hand("hand_12", 12, 5, "87", ("9c", "4d")))
    first, second, third = session_report([("log", rows)])["hands"]
    assert (first["your_chips"], second["your_chips"]) == (-3.0, -8.0)
    assert third["your_chips"] is None
    # The small blind wins and takes the mushroom pool: more than the pot (10)
    # with the posts back, still counted.
    won = [{**item, "fields": {**item["fields"], "stacks": {"4": "106"}}}
           for item in rows[6:12]]
    first = session_report([("log", rows[:6] + won + rows[12:])])["hands"][0]
    assert first["your_chips"] == 14.0
    # The dealer not read: the hand counts as before.
    for item in rows[6:12]:
        item["fields"]["actions_v1"]["dealer"] = None
    first, second, _ = session_report([("log", rows)])["hands"]
    assert (first["your_chips"], second["your_chips"]) == (-11.0, 0.0)


def test_a_hand_you_folded_only_costs():
    """A rise in a hand you folded is a rebuy or a table change, left out
    even when the pot read was big enough (until 10/17 a rebuy right after a
    folded bomb pot counted as its win)."""
    fold = [(2, "flop", 4, "fold", "0", "no_chips")]

    def rows(after):
        first = [row(f, f * 0.1, stack="100", pot=600, actions=fold[:f // 2])
                 for f in range(6)]
        return first + [row(f, f * 0.1, hand="hand_6", cards=("2c", "7d"), stack=after)
                        for f in range(6, 12)]
    assert session_report([("log", rows("500"))])["hands"][0]["your_chips"] is None
    assert session_report([("log", rows("90"))])["hands"][0]["your_chips"] == -10.0
    # Not folded: a win up to the pot counts, as before.
    won = [{**item, "fields": {**item["fields"],
                               "actions_v1": {**item["fields"]["actions_v1"],
                                              "actions": []}}}
           for item in rows("500")]
    assert session_report([("log", won)])["hands"][0]["your_chips"] == 400.0
    # All in and won, then the next hand read with the same cards, folded:
    # the two count as one, and the fold is not this hand's.
    shove = [(2, "flop", 4, "all_in", "100", "stack")]
    rows = ([row(f, f * 0.1, stack="100", pot=600, actions=shove[:f // 2])
             for f in range(6)]
            + [row(f, f * 0.1, hand="hand_6", stack="250", actions=fold)
               for f in range(6, 12)]
            + [row(f, f * 0.1, hand="hand_12", cards=("2c", "7d"), stack="250")
               for f in range(12, 18)])
    assert session_report([("log", rows)])["hands"][0]["your_chips"] == 150.0
