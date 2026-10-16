"""One reading per card in a hand (``aa_card_check``), without recordings."""

import numpy as np

from poker_engine.desktop.aa_card_check import (
    AACardCheck, MARGIN_SECONDS, NEW_DEAL_FRAMES, STALE_EMPTY_FRAMES)

FLOP = ["Ac", "Js", "Jd", None, None]
STEP = 0.1


def run(check, frames, hand="hand_1", start=0.0):
    """[(hero, board, report)] for frames of (hero, board), STEP apart."""
    out = []
    for at, (hero, board) in enumerate(frames):
        out.append(check.observe(hero, board, hand, start + at * STEP))
    return out


def test_the_first_reading_is_shown_at_once():
    hero, board, report = AACardCheck().observe(["Kd", "Qs"], FLOP, "hand_1", 0.0)
    assert hero == ["Kd", "Qs"] and board == FLOP and report["held_back"] is None


def test_a_card_covered_for_half_a_second_is_held_back_then_shown_again():
    # The 10/09 hand: the third card read as the jack of hearts for half a
    # second at an all-in, then as the jack of diamonds again.
    check = AACardCheck()
    run(check, [(None, FLOP)] * 30)
    covered = ["Ac", "Js", "Jh", None, None]
    rows = run(check, [(None, covered)] * 5 + [(None, FLOP)] * 3, start=3.0)
    assert [board[2] for _, board, _ in rows] == [None] * 5 + ["Jd"] * 3
    assert rows[0][2]["held_back"] == {"hero": None, "board": {"2": "Jh"}}
    assert rows[-1][2]["held_back"] is None
    assert [board[:2] for _, board, _ in rows] == [["Ac", "Js"]] * 8


def test_a_card_read_wrong_first_gives_way_once_the_right_one_leads():
    # The flop dealt while the table was covered: the first reading of the
    # third card was the wrong one, read for 0.4 s.
    check = AACardCheck()
    wrong = ["2s", "2c", "Qs", None, None]
    right = ["2s", "2c", "Kc", None, None]
    first = run(check, [(None, wrong)] * 4)
    assert [board[2] for _, board, _ in first] == ["Qs"] * 4
    later = run(check, [(None, right)] * 20, start=0.4)
    shown = [board[2] for _, board, _ in later]
    switch = shown.index("Kc")
    assert shown[:switch] == [None] * switch and set(shown[switch:]) == {"Kc"}
    # Kc leads Qs (0.4 s) by more than the margin only after that long.
    assert (switch + 1) * STEP > 0.4 + MARGIN_SECONDS - 1e-9


def test_dimmed_cards_at_the_showdown_are_held_back():
    check = AACardCheck()
    run(check, [(["3d", "5c"], [None] * 5)] * 40)
    rows = run(check, [(["3s", "5c"], [None] * 5)] * 10, start=4.0)
    assert {tuple(hero or ()) for hero, _, _ in rows} == {()}
    assert rows[0][2]["held_back"]["hero"] == ["3s", "5c"]
    assert not any(report["new_deal"] for _, _, report in rows)


def test_after_you_folded_your_cards_no_longer_change():
    # 杜's P30, 10/16: read for two seconds, folded, then the dimmed cards
    # read with another suit for half a minute.
    check = AACardCheck()
    rows = [check.observe(["3d", "5c"], [None] * 5, "hand_1", at * 0.4)
            for at in range(5)]
    rows += [check.observe(["3s", "5c"], [None] * 5, "hand_1", 2.0 + at * 0.4,
                           folded=True) for at in range(75)]
    assert all(hero is None for hero, _, _ in rows[5:])
    assert rows[-1][2]["folded"] is True
    assert rows[-1][2]["held_back"]["hero"] == ["3s", "5c"]
    # Without the fold the longer reading takes over.
    check = AACardCheck()
    for at in range(5):
        check.observe(["3d", "5c"], [None] * 5, "hand_1", at * 0.4)
    last = [check.observe(["3s", "5c"], [None] * 5, "hand_1", 2.0 + at * 0.4)
            for at in range(75)]
    assert last[-1][0] == ["3s", "5c"]


def test_the_last_hands_fold_does_not_lock_the_new_hands_cards():
    check = AACardCheck()
    for at in range(10):
        check.observe(["Kd", "Qs"], [None] * 5, "hand_1", at * 0.4, folded=at > 4)
    # The new hand: the fold still shows before your new cards are read.
    hero, _, report = check.observe(None, [None] * 5, "hand_2", 4.4, folded=True)
    assert report["folded"] is False
    rows = [check.observe(["Ah", "9s"], [None] * 5, "hand_2", 4.8 + at * 0.4)
            for at in range(3)]
    assert all(hero == ["Ah", "9s"] for hero, _, _ in rows)


def test_the_last_hands_cards_on_screen_do_not_block_the_new_ones():
    check = AACardCheck()
    old = ["Kc", "Kh", "6c", "6h", "6s"]
    run(check, [(["3d", "5c"], old)] * 30)
    # The new hand starts while the last board and cards are still shown.
    rows = run(check, [(["3d", "5c"], old)] * 5, hand="hand_2", start=3.0)
    assert all(board == old and hero == ["3d", "5c"] for hero, board, _ in rows)
    deal = run(check, [(["Ah", "9s"], [None] * 5)] * 3
               + [(["Ah", "9s"], ["Kd", "Kh", "2c", None, None])] * 3,
               hand="hand_2", start=3.5)
    assert all(hero == ["Ah", "9s"] for hero, _, _ in deal)
    # The new flop has a king of hearts where the last board had it too.
    assert deal[-1][1] == ["Kd", "Kh", "2c", None, None]
    assert all(report["held_back"] is None for _, _, report in deal)


def test_the_last_hands_card_is_counted_once_the_slot_went_empty():
    check = AACardCheck()
    run(check, [(None, ["Kc", "Kh", "6c", None, None])] * 30)
    gone = run(check, [(None, [None] * 5)] * STALE_EMPTY_FRAMES, hand="hand_2",
               start=3.0)
    assert all(board == [None] * 5 for _, board, _ in gone)
    flop = ["9d", "8d", "2h", None, None]
    run(check, [(None, flop)] * 20, hand="hand_2", start=4.0)
    # The last hand's king read again in the new hand is a reading like any
    # other, not passed on as the last hand's.
    _, board, report = check.observe(None, ["Kc", "8d", "2h", None, None],
                                     "hand_2", 6.5)
    assert board == [None, "8d", "2h", None, None]
    assert report["held_back"]["board"] == {"0": "Kc"}


def test_a_missed_start_of_a_hand_is_a_new_deal():
    check = AACardCheck()
    run(check, [(["5h", "Jc"], [None] * 5)] * 50)
    rows = run(check, [(["4h", "5d"], [None] * 5)] * (NEW_DEAL_FRAMES + 2), start=5.0)
    shown = [hero for hero, _, _ in rows]
    assert shown[:NEW_DEAL_FRAMES - 1] == [None] * (NEW_DEAL_FRAMES - 1)
    assert set(map(tuple, shown[NEW_DEAL_FRAMES - 1:])) == {("4h", "5d")}
    assert rows[NEW_DEAL_FRAMES - 1][2]["new_deal"] is True


def test_a_whole_new_board_is_a_new_deal_but_two_covered_cards_are_not():
    check = AACardCheck()
    board = ["Qs", "Jh", "Kd", "2h", "Ts"]
    run(check, [(None, board)] * 50)
    covered = run(check, [(None, [None, "Jh", "Qh", "Qd", None])] * 10, start=5.0)
    assert all(shown == [None, "Jh", None, None, None] for _, shown, _ in covered)
    new = ["7c", "7d", "3s", None, None]
    rows = run(check, [(None, new)] * (NEW_DEAL_FRAMES + 1), start=6.0)
    assert rows[-1][1] == new


def test_reset_forgets_the_hand():
    check = AACardCheck()
    run(check, [(None, FLOP)] * 30)
    check.reset()
    _, board, _ = check.observe(None, ["Ac", "Js", "Jh", None, None], "hand_1", 9.0)
    assert board == ["Ac", "Js", "Jh", None, None]


class _Covered:
    """A reader candidate on the flop whose third card is covered (read as
    another card) on frames 20-24."""

    def __init__(self, spec):
        import math
        from types import SimpleNamespace
        self.p = math
        self.audit = spec["audit"]
        scene = {"scene": "AA_TABLE_CANDIDATE"}
        modes = {"block_state_updates": False, "insurance": "UNKNOWN"}
        self.reader = SimpleNamespace(
            recognize=lambda image: dict.fromkeys(map(str, range(8))),
            scene=SimpleNamespace(recognize=lambda image: scene))
        self.modes = SimpleNamespace(recognize=lambda image: modes)
        self.profile = {}
        self.count = 0

    def read(self, image, frame, sample):
        self.count += 1
        third = "Jh" if 20 <= frame < 25 else "Jd"
        glyphs = self.reader.recognize(image)
        return {"frame": frame, "source_sha256": sample["sha256"],
                "scene_supported": True, "special_modes": {}, "pot": {"value": "70"},
                "cards": {"source": self.audit, "hero": ["Kd", "Kc"],
                          "board_slots": ["Ac", "Js", third, None, None]},
                "glyph_transitions": self.tracker.observe(frame, glyphs),
                "glyphs": glyphs, "strategy_eligible": False}


def test_the_reader_shows_the_checked_cards_and_keeps_the_read_ones(tmp_path):
    import json
    from poker_engine.desktop.aa_reader import AA8Reader
    from poker_engine.desktop.aa_session import frame_summary
    spec = {"audit": "a" * 64}
    for key in ("source", "context_source", "late_source", "bomb_pool"):
        (tmp_path / key).mkdir()
        (tmp_path / key / "samples.json").write_text("{}", encoding="utf-8")
        spec[key] = key
    for key in ("bank_path", "heads_path", "reservations"):
        (tmp_path / key).write_text("{}", encoding="utf-8")
        spec[key] = key
    (tmp_path / "profile_path").write_text(json.dumps({
        "canvas": [498, 1080], "hero_slot": 4,
        "slots": [{"slot": i} for i in range(8)]}), encoding="utf-8")
    spec["profile_path"] = "profile_path"
    path = tmp_path / "reader.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    reader = AA8Reader(path, factory=_Covered)
    image = np.zeros((1080, 498, 3), dtype=np.uint8)
    rows = [reader.read(image, i, {"pts_seconds": i / 10, "source_id": "s"})
            for i in range(30)]
    assert [row["cards"]["board_slots"][2] for row in rows[18:27]] == [
        "Jd", "Jd", None, None, None, None, None, "Jd", "Jd"]
    covered = rows[21]
    assert covered["cards"]["board_slots_as_read"][2] == "Jh"
    held = {"hero": None, "board": {"2": "Jh"}}
    assert covered["card_check_v1"]["held_back"] == held
    assert frame_summary(covered)["board"] == ["Ac", "Js", None, None, None]
    assert frame_summary(covered)["cards_held_back"] == held
    assert frame_summary(rows[10])["cards_held_back"] is None
