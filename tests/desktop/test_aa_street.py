"""Street from the board cards on screen, without private recordings."""

import pytest

from poker_engine.desktop.aa_street import AAStreet, board_count, street_evidence


def frame(board=0, *, hero=False, active_seat=False, supported=True, insurance=None):
    cards = ["Ah", "Kd", "7c", "2s", "9h"][:board] + [None] * (5 - board)
    return {"scene_supported": supported,
            "special_modes": {"insurance": insurance},
            "cards": {"hero": ["Qs", "Qh"] if hero else [None, None],
                      "board_slots": cards},
            "seat_states_v1": {"seats": {"2": {"state": "active" if active_seat
                                               else "folded"}}}}


@pytest.mark.parametrize("board, expected", [(3, "flop"), (4, "turn"), (5, "river"),
                                             (1, None), (2, None)])
def test_board_cards_name_the_street(board, expected):
    assert street_evidence(frame(board)) == expected


def test_preflop_needs_a_hand_in_play():
    assert street_evidence(frame(0)) == "hand_over"
    assert street_evidence(frame(0, hero=True)) == "preflop"
    assert street_evidence(frame(0, active_seat=True)) == "preflop"


def test_an_unread_middle_card_still_counts_and_unreadable_frames_give_none():
    gap = frame(3)
    gap["cards"]["board_slots"] = ["Ah", None, "7c", "2s", None]
    assert board_count(gap) == 4 and street_evidence(gap) == "turn"
    assert street_evidence(frame(5, supported=False)) is None
    assert street_evidence(frame(5, insurance="VISIBLE")) is None


def test_joining_mid_hand_knows_the_street_on_the_first_frame():
    assert AAStreet().observe(frame(4), 300.0)["street"] == "turn"


def test_dealing_and_overlays_keep_the_street_for_readable_seconds_only():
    street = AAStreet(hold_seconds=2.0)
    assert street.observe(frame(3), 10.0)["street"] == "flop"
    held = street.observe(frame(1), 10.5)            # turn card being dealt
    assert held == {"schema_version": 1, "street": "flop", "source": "held",
                    "age_seconds": 0.5, "basis": "board_card_count"}
    for second in range(1, 10):                       # insurance window
        assert street.observe(frame(insurance="VISIBLE"), 10.5 + second)[
            "street"] == "flop"
    assert street.observe(frame(2), 20.0)["street"] == "flop"      # 1.0 s readable
    assert street.observe(frame(2), 21.5)["street"] is None        # 2.5 s readable
    assert street.observe(frame(0, hero=True), 22.0)["street"] == "preflop"
    assert street.observe(frame(4), 22.5)["street"] == "turn"
    assert street.observe(frame(0), 22.6)["street"] == "turn"      # may be a blink
    assert street.observe(frame(0), 24.1)["street"] is None        # hand over
    street.reset()
    assert street.observe(frame(1), 23.0)["street"] is None


def showdown(board=0, pot="294", **kwargs):
    item = frame(board, **kwargs)
    item["pot"] = {"value": pot}
    return item


def test_board_unread_for_a_moment_at_the_showdown_keeps_the_street():
    street = AAStreet()
    assert street.observe(showdown(5), 10.0)["street"] == "river"
    for second in (10.1, 10.5, 11.0):           # board not read, same pot
        assert street.observe(showdown(0, active_seat=True), second)[
            "street"] == "river"
    assert street.observe(showdown(0), 11.1)["street"] == "river"   # seats too
    assert street.observe(showdown(5), 11.2)["street"] == "river"


def test_an_empty_board_after_the_flop_counts_once_it_lasts():
    street = AAStreet()
    street.observe(showdown(5), 10.0)
    assert street.observe(showdown(0, hero=True), 10.1)["street"] == "river"
    assert street.observe(showdown(0, hero=True), 11.5)["street"] == "river"
    assert street.observe(showdown(0, hero=True), 11.7)["street"] == "preflop"
    street = AAStreet()
    street.observe(showdown(5), 10.0)
    assert street.observe(showdown(0), 10.1)["street"] == "river"
    assert street.observe(showdown(0), 11.7)["street"] is None      # hand over


def test_a_smaller_pot_on_two_frames_is_the_next_hand_at_once():
    street = AAStreet()
    street.observe(showdown(4, pot="140"), 10.0)
    assert street.observe(showdown(0, pot="7", hero=True), 10.1)["street"] == "turn"
    assert street.observe(showdown(0, pot="7", hero=True), 10.2)["street"] == "preflop"
    street = AAStreet()
    street.observe(showdown(4, pot="140"), 10.0)
    street.observe(showdown(0, pot="7", hero=True), 10.1)       # one misread
    assert street.observe(showdown(0, pot="140", hero=True), 10.2)[
        "street"] == "turn"
