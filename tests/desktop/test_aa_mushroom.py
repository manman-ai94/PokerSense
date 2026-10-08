"""The mushroom pool read from the badge at the top left of the AA table."""

import copy

import cv2
import numpy as np

from poker_engine.desktop.aa_mushroom import (
    DIGITS, ICON, AAMushroomPool, glyph_patches, icon_visible, load_bank, read_digits)
from poker_engine.perceptual.vision.gray_amount_recognizer import (
    GrayAmountRecognizer, gray_glyphs)

FONT = cv2.FONT_HERSHEY_SIMPLEX


def badge(text, at=12, gap=1):
    """A dark badge the size of the digit box with ``text`` in white, each
    digit ``gap`` pixels after the one before (``gap`` < 0: they touch)."""
    patch = np.full((DIGITS[3], DIGITS[2], 3), 20, np.uint8)
    x = at
    for digit in text:
        (width, _), _ = cv2.getTextSize(digit, FONT, .45, 1)
        cv2.putText(patch, digit, (x, 14), FONT, .45, (255, 255, 255), 1, cv2.LINE_AA)
        x += width + gap
    return patch


def bank():
    features = [gray_glyphs(badge(digit))[0][0][0] for digit in "0123456789"]
    return GrayAmountRecognizer(features, list("0123456789"), margin=.03, augment=True)


def table(text=None, icon=True):
    image = np.full((1080, 498, 3), (40, 90, 20), np.uint8)
    if icon:
        x, y, w, h = ICON
        cv2.ellipse(image, (x + w // 2, y + h // 3), (w // 2 - 2, h // 4), 0, 0, 360,
                    (30, 30, 220), -1)
    if text is not None:
        x, y, w, h = DIGITS
        image[y:y + h, x:x + w] = badge(text)
    return image


def row(frame):
    return {"frame": frame, "scene_supported": True}


def test_the_icon_shows_the_mushroom_mode():
    assert icon_visible(table("48"))
    assert not icon_visible(table("48", icon=False))


def test_a_value_counts_once_two_frames_in_a_row_read_the_same():
    reader = AAMushroomPool(bank())
    first = reader.observe(table("48"), row(10))
    assert (first["visible"], first["value"], first["raw"], first["reason"]) == (
        True, None, "48", "waiting_stability")
    second = reader(table("48"), row(11))["mushroom_pool_v1"]
    assert (second["value"], second["reason"]) == ("48", "stable")
    # A skipped frame or a new value starts again.
    assert reader.observe(table("48"), row(13))["value"] is None
    assert reader.observe(table("54"), row(14))["value"] is None
    assert reader.observe(table("54"), row(15))["value"] == "54"


def test_a_copy_shares_the_bank_and_keeps_its_place():
    reader = AAMushroomPool(bank())
    reader.observe(table("12"), row(1))
    copied = copy.deepcopy(reader)
    assert copied.bank is reader.bank
    assert copied.observe(table("12"), row(2))["value"] == "12"
    assert copy.deepcopy(AAMushroomPool(load=lambda: None)).bank is None


def test_without_the_icon_the_bank_or_a_clear_table_nothing_is_read():
    reader = AAMushroomPool(bank())
    reader.observe(table("6"), row(1))
    gone = reader.observe(table("6", icon=False), row(2))
    assert (gone["visible"], gone["value"], gone["reason"]) == (
        False, None, "no_mushroom_icon")
    covered = reader.observe(table("6"), {"frame": 3, "scene_supported": False})
    assert covered["reason"] == "unsupported_or_obstructed_scene"
    missing = AAMushroomPool(load=lambda: None).observe(table("6"), row(4))
    assert (missing["value"], missing["reason"]) == (None, "bank_missing")


def test_touching_digits_are_split_and_read_one_by_one():
    patch = badge("48", gap=-2)
    assert len(gray_glyphs(patch)[0]) <= 1          # one run of ink for two digits
    assert len(glyph_patches(patch)) == 2
    assert read_digits(bank(), patch).value == "48"


def test_a_number_cut_by_the_box_edge_is_not_read():
    read = read_digits(bank(), badge("666", at=-3))
    assert read.value is None


def test_the_bank_is_optional(tmp_path):
    assert load_bank(tmp_path / "missing.npz") is None
    features = np.array([gray_glyphs(badge(d))[0][0][0] for d in "0123456789"])
    np.savez_compressed(tmp_path / "bank.npz", features=features,
                        labels=np.array(list("0123456789")))
    assert read_digits(load_bank(tmp_path / "bank.npz"), badge("30")).value == "30"
