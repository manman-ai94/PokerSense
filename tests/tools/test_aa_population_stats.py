"""AA real-player statistics: replaying read hands and counting decisions."""

import json

from tools import aa_population_stats as stats


def act(street, slot, kind, amount=None, pot=None):
    return {"frame": None, "street": street, "slot": slot, "kind": kind,
            "amount": amount, "source": "reader", "pot_before": pot}


def hand(actions, dealer=5, log="spectate", seats=6, board=3):
    return {"log": log, "hand_id": "h", "complete": True, "dealer": dealer,
            "seats_first": {str(seat): "active" for seat in range(seats)},
            "board_max": board, "actions": actions}


# Six seats, button 5: SB 0, BB 1, straddle 2, HJ 3 acts first, CO 4, BTN 5.
LIMP_ISO_CBET = [
    act("preflop", 3, "call", "4", "20"), act("preflop", 4, "fold"),
    act("preflop", 5, "raise", "24", "24"), act("preflop", 0, "fold"),
    act("preflop", 1, "fold"), act("preflop", 2, "fold"),
    act("preflop", 3, "call", "20", "48"),
    act("flop", 3, "check"), act("flop", 5, "raise", "34", "68"),
    act("flop", 3, "fold"),
]


def test_positions_follow_the_straddle():
    assert stats.position_names(8) == ("SB", "BB", "STR", "UTG1", "LJ", "HJ", "CO",
                                       "BTN")
    assert stats.position_names(5) == ("SB", "BB", "STR", "CO", "BTN")
    assert stats.position_names(4) == ("SB", "BB", "STR", "BTN")


def test_replay_names_spots_choices_and_pot_shares():
    placed = stats.replay(hand(LIMP_ISO_CBET))
    assert placed["dealer"] == "read" and placed["closed"] == ["preflop", "flop"]
    assert placed["remaining"] == [5]
    rows = [(d["position"], d["spot"], d["choice"]) for d in placed["decisions"]]
    assert rows[:3] == [("HJ", "rfi", "call"), ("CO", "vs_limp", "fold"),
                        ("BTN", "vs_limp", "raise")]
    assert rows[7:] == [("HJ", "flop|hu|other|checked_to", "check"),
                        ("BTN", "flop|hu|pfa|checked_to", "bet"),
                        ("HJ", "flop|hu|other|facing_bet", "fold")]
    assert placed["decisions"][8]["share"] == 0.5


def test_a_stale_dealer_is_replaced_by_the_one_the_first_action_implies():
    placed = stats.replay(hand(LIMP_ISO_CBET, dealer=4))
    assert placed["dealer"] == "implied" and placed["players"][5] == "BTN"


def test_a_check_read_as_preflop_after_the_round_closed_is_the_flop():
    actions = LIMP_ISO_CBET[:7] + [act("preflop", 3, "check")] + LIMP_ISO_CBET[8:]
    placed = stats.replay(hand(actions))
    assert placed["decisions"][7]["street"] == "flop"
    assert placed["closed"] == ["preflop", "flop"]


def test_a_missed_action_stops_the_hand_there():
    skipped = [a for a in LIMP_ISO_CBET if not (a["slot"] == 4)]
    assert stats.replay(hand(skipped)) is not None   # seat 4 is taken as sitting out
    broken = LIMP_ISO_CBET[:2] + LIMP_ISO_CBET[3:]   # the button's raise is missed
    assert stats.replay(hand(broken)) is None
    flop_gap = LIMP_ISO_CBET[:8] + LIMP_ISO_CBET[9:]  # the flop bet is missed
    placed = stats.replay(hand(flop_gap))
    assert placed["streets"] == ["preflop"]
    assert all(d["street"] == "preflop" for d in placed["decisions"])


def test_the_hero_seat_is_the_live_windows_bottom_centre_seat():
    assert stats.HERO_SEAT == 4


def test_build_counts_players_and_skips_the_hero_seat():
    # peng sits at seat 4 (CO here) and opens; only the other five count.
    hero_hand = [act("preflop", 3, "fold"), act("preflop", 4, "raise", "30", "20"),
                 act("preflop", 5, "fold"), act("preflop", 0, "fold"),
                 act("preflop", 1, "fold"), act("preflop", 2, "fold")]
    report = stats.build([hand(LIMP_ISO_CBET), hand(hero_hand, log="seated")],
                         hero_logs={"seated"}, minutes={"spectate": 30, "seated": 30})
    every = report["groups"]["ALL"]
    assert report["hands_counted"] == 2
    assert every["player"]["ALL|vpip"]["n"] == 11       # 6 + 5, seat 4 of the hero log
    assert every["player"]["HJ|rfi_limp"] == {
        **every["player"]["HJ|rfi_limp"], "n": 2, "hits": 1}
    assert every["preflop"]["CO|vs_limp"]["fold"]["count"] == 1
    assert every["preflop"]["SB|vs_open"]["fold"]["count"] == 2
    assert "CO|rfi" not in every["preflop"]             # only the hero opened
    assert every["postflop"]["flop|vs_cbet"]["fold"]["count"] == 1
    assert every["player"]["hands|reach_flop"]["hits"] == 1
    assert every["sizes"]["flop_bet"]["median"] == 0.5
    assert every["player"]["ALL|vpip"]["more_video_hours"]["30"] == 1.7
    assert report["groups"]["players_4-6"]["player"]["ALL|vpip"]["n"] == 11


def test_reduce_takes_the_last_history_and_the_pot_before_each_action(tmp_path):
    rows = []
    for frame in range(30):
        pot = "20" if frame < 12 else "24"
        rows.append({"processed": frame, "fields": {
            "pot": pot, "board": [None] * 5,
            "participants": {"0": "active", "1": "empty"},
            "actions_v1": {"hand_id": "x", "complete": True, "dealer": 3,
                           "actions": [[12, "preflop", 3, "call", "4", "pot_rise"]]
                           if frame >= 12 else []}}})
    path = tmp_path / "frames.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    (record,) = stats.reduce_log(stats.load(path), "m")
    assert record["log"] == "m" and record["dealer"] == 3
    assert record["actions"][0]["pot_before"] == "20"
    assert record["seats_first"] == {"0": "active", "1": "empty"}
