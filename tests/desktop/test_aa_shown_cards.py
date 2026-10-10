"""Opponents' shown cards: where they are found and how a pair is kept."""

import numpy as np
import pytest

from poker_engine.desktop import aa_shown_cards as shown
from poker_engine.desktop.aa_shown_cards import AAShownCards, face_block, read_pair

AVATAR = (423, 296, 74, 71)          # seat 1
GREEN = (60, 140, 20)


def table():
    return np.full((1080, 498, 3), GREEN, dtype=np.uint8)


def cards(image, x=421, y=305, width=74, back=False):
    """Two white cards side by side, the right one face down if ``back``."""
    image[y:y + 54, x:x + width] = 255
    image[y:y + 54, x + width // 2] = 120             # the edge between them
    if back:
        image[y + 2:y + 52, x + width // 2 + 3:x + width - 2] = (40, 30, 160)
    return image


def test_two_cards_over_a_picture_are_found():
    assert face_block(cards(table()), AVATAR) == (421, 305, 74, 54)


def test_a_picture_card_low_down_does_not_hide_them():
    image = cards(table())
    image[305 + 12:305 + 54, 430:495] = (30, 40, 170)  # a king's robe on both
    assert face_block(image, AVATAR) == (421, 305, 74, 54)


@pytest.mark.parametrize("draw", [
    lambda image: image,                                             # no cards
    lambda image: cards(image, width=40),                            # one card
    lambda image: image.__setitem__((slice(290, 370), slice(423, 497)), 255)
    or image,                                                       # a white picture
])
def test_no_two_cards_no_block(draw):
    assert face_block(draw(table()), AVATAR) is None


def test_a_card_left_face_down_is_not_read(monkeypatch):
    monkeypatch.setattr(shown, "read_card", lambda model, image, rect: "As")
    assert read_pair(object(), cards(table(), back=True), AVATAR) is None


def test_each_card_needs_two_crops_that_agree(monkeypatch):
    reads = iter(["Ah", "Ah", "Ac", "8s", None, "8s"])
    monkeypatch.setattr(shown, "read_card", lambda model, image, rect: next(reads))
    assert read_pair(object(), cards(table()), AVATAR) == ("Ah", "8s")
    reads = iter(["Ah", "Ac", None, "8s", "8s", "8s"])
    assert read_pair(object(), cards(table()), AVATAR) is None


def seat_reads(monkeypatch, pairs):
    """read_pair gives seat 1 the next of ``pairs`` and nobody else anything."""
    pairs = iter(pairs)
    monkeypatch.setattr(shown, "read_pair", lambda model, image, avatar: (
        next(pairs, None) if tuple(avatar) == AVATAR else None))
    return AAShownCards(object(), [{"slot": slot, "avatar": AVATAR if slot == 1 else
                                    (0, 0, 1, 1)} for slot in range(8)])


def test_a_pair_counts_after_three_frames_and_stays_for_the_hand(monkeypatch):
    reader = seat_reads(monkeypatch, [("Kd", "As")] * 3)
    results = [reader.observe(None, frame, "hand_1") for frame in range(5)]
    assert results[:2] == [None, None]
    assert results[2] == results[4] == {
        "hand_id": "hand_1", "seats": {"1": {"cards": ["As", "Kd"], "frame": 2}},
        "unknown": []}
    assert reader.observe(None, 5, "hand_6") is None


def test_two_pairs_in_one_hand_leave_the_seat_unknown(monkeypatch):
    # The winner's glow read an ace of spades and two of diamonds as clubs
    # and hearts.
    reader = seat_reads(monkeypatch, [("As", "2d")] * 4 + [("Ac", "2h")] * 3)
    for frame in range(7):
        result = reader.observe(None, frame, "hand_1")
    assert result == {"hand_id": "hand_1", "seats": {}, "unknown": ["1"]}


def test_a_card_also_read_elsewhere_leaves_the_seat_unknown(monkeypatch):
    reader = seat_reads(monkeypatch, [("As", "Kd")] * 4)
    for frame in range(3):
        reader.observe(None, frame, "hand_1", known=["Qs", None])
    assert reader.observe(None, 3, "hand_1", known=["Kd"])["unknown"] == ["1"]
    # It stays so when the board is no longer read.
    assert reader.observe(None, 4, "hand_1", known=[])["seats"] == {}


def test_no_hand_or_no_model_reads_nothing(monkeypatch):
    reader = seat_reads(monkeypatch, [("As", "Kd")] * 3)
    assert [reader.observe(None, f, None) for f in range(3)] == [None] * 3
    assert AAShownCards(None, [{"slot": 1, "avatar": AVATAR}]).observe(
        table(), 0, "hand_1") is None


def test_unreadable_frames_keep_what_was_read(monkeypatch):
    reader = seat_reads(monkeypatch, [("As", "Kd")] * 3)
    for frame in range(3):
        reader.observe(None, frame, "hand_1")
    assert reader.observe(None, 3, "hand_1", readable=False)["seats"]["1"]["cards"] == [
        "As", "Kd"]
