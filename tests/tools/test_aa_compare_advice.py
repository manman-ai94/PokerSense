"""Replaying advice before and after the reading change, on synthetic frames."""

import json

import pytest

from tools.aa_compare_advice import cards_of, compare, main

# A 2/4/8(4) table, eight players, you (seat 4) on the button: small blind 5,
# big blind 6, straddle 7; seat 0 acts first. 8 x 4 + 2 + 4 + 8 = 46 to start.
# Seat 0 limps, you raise to 40, seat 0 re-raises to 170 (162 more).
LIMP_RAISE = [
    (10, "preflop", 0, "call", "8"), (11, "preflop", 1, "fold", "0"),
    (12, "preflop", 2, "fold", "0"), (13, "preflop", 3, "fold", "0"),
    (14, "preflop", 4, "raise", "40"), (15, "preflop", 5, "fold", "0"),
    (16, "preflop", 6, "fold", "0"), (17, "preflop", 7, "fold", "0"),
    (18, "preflop", 0, "raise", "162"),
]
STACKS = {"0": "226", "1": "396", "2": "396", "3": "396", "4": "356",
          "5": "394", "6": "392", "7": "388"}


def rows(hero=("Ad", "Qd"), hand_id="hand_1", you_call=False):
    actions = LIMP_RAISE + ([(28, "preflop", 4, "call", "130")] if you_call else [])
    history = {"hand_id": hand_id, "complete": True, "start": "pot_went_down",
               "dealer": 4}
    result = []
    for frame in range(30):
        if frame == 3:
            wagers = {str(seat): "4" for seat in range(8)}
        elif 4 <= frame < 10:
            wagers = {"5": "2", "6": "4", "7": "8"}
        else:
            wagers = {}
        turn = 20 <= frame < 28
        fields = {
            "pot": "0" if frame < 3 else "46" if frame < 19 else "256",
            "street": "preflop",
            "participants": {str(seat): "active" for seat in range(8)},
            "street_wagers": wagers, "board": [None] * 5, "hero": list(hero),
            "stacks": STACKS if frame >= 19 else {},
            "scene_supported": True,
            "hero_controls": {"visible": turn, "button": "call",
                              "call_amount": "130" if turn else None},
            "actions_v1": {**history, "actions": [
                list(a) + ["no_chips"] for a in actions if a[0] <= frame]}}
        result.append({"processed": frame, "pts_seconds": frame * 0.1,
                       "fields": fields})
    return result


def test_cards_are_read_however_they_are_written():
    assert cards_of("A♦ 9♠") == cards_of("Ad9s") == cards_of("ad 9S") == {"Ad", "9s"}
    assert cards_of("10d 9s") == {"Td", "9s"}
    with pytest.raises(ValueError):
        cards_of("Ad")


def test_a_limp_raise_shove_turns_into_a_call():
    (item,) = compare([("log", rows())], heroes=["A♦ Q♦"])
    assert (item["hand_id"], item["street"], item["hero"]) == ("hand_1", "preflop",
                                                               "Ad Qd")
    assert item["before"]["kind"] == item["after"]["kind"] == "preflop"
    assert item["before"]["action"] == "raise" and item["after"]["action"] == "call"
    assert item["changed"] is True
    # The shove's worth fell; aces would still shove.
    assert item["after"]["options"]["raise"] < item["before"]["options"]["raise"]
    (aces,) = compare([("log", rows(("As", "Ah")))], hands=["hand_1"])
    assert aces["before"]["action"] == aces["after"]["action"] == "raise"
    assert aces["changed"] is False


def test_hands_are_picked_by_cards_or_id_and_unchanged_ones_left_out(tmp_path):
    logs = [("one", rows(hand_id="hand_1")),
            ("two", rows(("As", "Ah"), hand_id="hand_2"))]
    assert [item["hand_id"] for item in compare(logs)] == ["hand_1"]
    every = compare(logs, every=True)
    assert {item["hand_id"] for item in every} == {"hand_1", "hand_2"}
    assert [item["hand_id"] for item in compare(logs, hands=["hand_2"])] == ["hand_2"]
    assert compare(logs, heroes=["Kc Kd"]) == []
    # The command line: frames.jsonl in a recording folder, a JSON out.
    folder = tmp_path / "20261011-rec"
    folder.mkdir()
    frames = folder / "frames.jsonl"
    frames.write_text("".join(json.dumps(row) + "\n" for row in rows(you_call=True)),
                      encoding="utf-8")
    out = tmp_path / "compare.json"
    main(["--frames", str(frames), "--hero", "AdQd", "--out", str(out)])
    (item,) = json.loads(out.read_text(encoding="utf-8"))
    assert item["log"] == "20261011-rec" and item["you_did"] == "call"
    # Every recording under a folder.
    main(["--recordings", str(tmp_path), "--hero", "A♦ Q♦", "--out", str(out)])
    assert len(json.loads(out.read_text(encoding="utf-8"))) == 1


def test_answers_are_priced_with_your_cards_against_the_cards_shown():
    found = rows()
    found[-1]["fields"]["shown_cards"] = {"seats": {"0": {"cards": ["Kc", "Kd"]}}}
    (item,) = compare([("log", found)], heroes=["A♦ Q♦"])
    shown = item["shown"]
    # A♦ Q♦ (not the replay's placeholder cards) against K♣ K♦: about 31%.
    assert shown["cards"] == {"0": "Kc Kd"} and 0.28 < shown["share"] < 0.34
    # Calling 130 into 256 for 31% of 386 loses; the raise puts in more.
    assert shown["after"] < 0 and shown["before"] < shown["after"]
