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
