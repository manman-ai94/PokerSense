from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import numpy as np
import cv2
import pytest

from poker_engine.desktop import aa_hero_controls
from poker_engine.desktop.aa_live_context import (
    LiveStateAdapter, LiveHandLedger, LiveCausalWagers, LiveFrameEvidence,
)
from tools.aa_seat_candidate import plus_mask
from poker_engine.desktop.aa_river_strategy import current_river_study
from poker_engine.perceptual.vision.gray_amount_recognizer import GrayRead
from poker_engine.strategy.river_bounds_v1 import (
    river_payoff_bounds, tying_opponents_upper_bound,
)


HERO = ["6d", "9c"]
BOARD = ["7h", "Ad", "5s", "2h", "8s"]


def test_nut_straight_bound_and_fee_are_exact_without_a_range_distribution():
    result = river_payoff_bounds(HERO, BOARD, "448", "260", 1)
    assert result["share_floor"]["exact"] == "1/2"
    assert result["call_gross_lower"]["exact"] == "94"
    assert result["call_net_lower"] is None
    assert result["strength_evidence"]["combos_examined"] == 990
    assert result["win_probability"] is None
    assert result["strategy_eligible"] is False
    net = river_payoff_bounds(HERO, BOARD, "448", "260", 1, max_hero_deduction="5")
    assert net["call_net_lower"]["exact"] == "89"


def test_multiway_floor_is_not_heads_up_relabelled():
    result = river_payoff_bounds(HERO, BOARD, "448", "260", 3)
    assert result["share_floor"]["exact"] == "1/4"
    assert result["call_gross_lower"]["exact"] == "-83"
    assert "preferred_action" not in result
    # Only three other sixes and three other nines remain: at most three ties,
    # even when seven opponents contest. No independent-hand double counting.
    seven = river_payoff_bounds(HERO, BOARD, "448", "260", 7)
    assert seven["share_floor"]["exact"] == "1/4"


def test_tie_matching_upper_bound_respects_shared_cards():
    assert tying_opponents_upper_bound([(1, 2), (1, 3), (1, 4)]) == 1
    assert tying_opponents_upper_bound([(1, 2), (3, 4), (5, 6)]) == 3
    assert tying_opponents_upper_bound([]) == 0


def test_board_royal_flush_always_splits_and_unique_royal_wins():
    split = river_payoff_bounds(["2c", "3d"], ["Th", "Jh", "Qh", "Kh", "Ah"],
                                "70", "10", 7)
    assert split["share_floor"]["exact"] == "1/8"
    assert split["call_gross_lower"]["exact"] == "0"
    win = river_payoff_bounds(["As", "9d"], ["Ks", "Qs", "Js", "Ts", "2d"],
                              "70", "10", 7)
    assert win["share_floor"]["exact"] == "1"
    assert win["call_gross_lower"]["exact"] == "70"


def test_beatable_hand_is_not_a_fold_recommendation():
    result = river_payoff_bounds(["Ac", "Ad"], ["Kh", "Qd", "Jh", "9s", "2c"],
                                 "100", "20", 1)
    assert result["call_gross_lower"]["exact"] == "-20"
    assert result["advice_emitted"] is False
    assert result["strength_evidence"]["exhaustive"] is False


@pytest.mark.parametrize("cards,pot,cost,n", [
    (["6d", "6d"], "10", "1", 1), (HERO, "NaN", "1", 1),
    (HERO, "10", "0", 1), (HERO, "10", "1", True),
    (HERO, "10", "1", 8), (HERO, 10, "1", 1),
    (HERO, "1e-1000000", "1", 1),
])
def test_bad_money_cards_or_opponent_count_reject(cards, pot, cost, n):
    with pytest.raises(ValueError):
        river_payoff_bounds(cards, BOARD, pot, cost, n)


def green_button(*bands):
    """Hero's green button with white text blocks at (top, bottom, left, right)."""
    image = np.zeros((1080, 498, 3), dtype=np.uint8)
    cv2.circle(image, (369, 875), 44, (60, 200, 40), -1)
    for top, bottom, left, right in bands:
        image[top:bottom + 1, left:right + 1] = 255
    return image


CALL_BUTTON = ((857, 871, 360, 378), (881, 892, 355, 383))   # amount over "跟注"


def test_button_price_requires_positive_controls_actor_and_stability(monkeypatch):
    image = green_button(*CALL_BUTTON)
    bank = SimpleNamespace(
        diagnose=lambda patch: GrayRead("260", "260", "candidate", ()))
    reader = aa_hero_controls.AAHeroControls(bank)
    monkeypatch.setattr(aa_hero_controls, "hero_turn_candidate",
                        lambda image: {"hero_turn": True})
    row = {"frame": 0, "scene_supported": True, "current_actor": 4}
    assert reader.observe(image, row)["call_amount"] is None
    row["frame"] = 1
    assert reader.observe(image, row)["call_amount"] == "260"
    row["frame"] = 3
    assert reader.observe(image, row)["call_amount"] is None
    row.update(frame=4, current_actor=7)
    assert reader.observe(image, row)["call_amount"] is None
    row.update(frame=5, current_actor=4, special_modes={"insurance": "VISIBLE"})
    assert reader.observe(image, row)["visible"] is False


def test_a_doubtful_price_is_taken_only_when_the_chips_in_front_give_it(monkeypatch):
    # 10/09 live: "74 跟注" facing an all in of 124 with 50 in front went
    # unread for 13 seconds; the reader was not sure of the 7.
    image = green_button(*CALL_BUTTON)
    bank = SimpleNamespace(
        diagnose=lambda patch: GrayRead(None, "74", "ambiguous", ()))
    reader = aa_hero_controls.AAHeroControls(bank)
    monkeypatch.setattr(aa_hero_controls, "hero_turn_candidate",
                        lambda image: {"hero_turn": True})
    row = {"frame": 0, "scene_supported": True, "current_actor": 4,
           "street_wagers": {"0": "124", "1": None, "4": "50"}}
    assert reader.observe(image, row)["call_amount"] is None       # once
    row["frame"] = 1
    result = reader.observe(image, row)
    assert (result["call_amount"], result["price_confirmed"]) == ("74", True)
    assert result["diagnostic"]["value_source"] == (
        "doubtful_reading_matches_chips_in_front")
    # Anything else stays unread: another number, your own chips unread
    # (the chips give 124), or no opponent's chips read.
    for frame, wagers in ((10, {"0": "124", "4": "40"}), (20, {"0": "124", "4": None}),
                          (30, {"0": None, "4": "50"})):
        reader.observe(image, {**row, "frame": frame, "street_wagers": wagers})
        result = reader.observe(image, {**row, "frame": frame + 1,
                                        "street_wagers": wagers})
        assert result["call_amount"] is None
        assert result["reason"] == "price_or_actor_unknown"


@pytest.mark.parametrize("bands, button, amount", [
    (((867, 881, 354, 366), (867, 881, 370, 383)), "check", "0"),    # "让牌"
    (((868, 880, 349, 357), (868, 880, 361, 362), (868, 880, 365, 366),
      (868, 880, 374, 374), (871, 880, 378, 389)), "all_in", "150"),  # "All in"
])
def test_check_and_all_in_buttons_give_their_call_amount(monkeypatch, bands,
                                                         button, amount):
    bank = SimpleNamespace(diagnose=lambda patch: pytest.fail("no digits to read"))
    reader = aa_hero_controls.AAHeroControls(bank)
    monkeypatch.setattr(aa_hero_controls, "hero_turn_candidate",
                        lambda image: {"hero_turn": True})
    image = green_button(*bands)
    row = {"frame": 0, "scene_supported": True, "current_actor": 4,
           "stacks": {"4": {"value": "150"}}}
    assert reader.observe(image, row)["button"] == button
    row["frame"] = 1
    result = reader.observe(image, row)
    assert result["call_amount"] == amount and result["price_confirmed"] is True
    assert result["all_in_call"] is (button == "all_in")
    if button == "all_in":
        row.update(frame=2, stacks={})
        assert reader.observe(image, row)["reason"] == "all_in_stack_unknown"


@pytest.mark.parametrize("bands, kind", [
    (((868, 880, 349, 357), (871, 880, 378, 389)), "all_in"),   # faint "ll"
    (((867, 881, 354, 366), (867, 881, 370, 383)), "check"),
    (((867, 881, 351, 387),), None),                            # 37 wide
])
def test_all_in_and_check_are_told_apart_by_the_width_of_the_text(bands, kind):
    # In the Mac capture the thin "ll" of "All in" can drop out entirely.
    assert aa_hero_controls.button_text(green_button(*bands))["kind"] == kind


def test_button_text_reads_digits_at_stack_height_and_ignores_rim_specks():
    image = green_button(*CALL_BUTTON)
    image[846:848, 349:351] = 255                   # rim speck near the edge
    text = aa_hero_controls.button_text(image)
    assert text["kind"] == "call"
    assert text["digits"].shape[0] == round(21 * 12 / 15)  # 15-row digits -> 12
    assert text["digits"].max() == 255 and text["digits"][0].max() < 255
    assert aa_hero_controls.button_text(green_button())["kind"] is None
    off_centre = green_button((882, 892, 355, 383))
    assert aa_hero_controls.button_text(off_centre) == {
        "kind": None, "reason": "unexpected_button_text"}


def test_positive_empty_plus_cannot_override_visible_money():
    image = np.zeros((1080, 498, 3), dtype=np.uint8)
    image[154:222, 213:285] = (20, 65, 0)
    cv2.line(image, (249, 177), (249, 199), (255, 255, 255), 3)
    cv2.line(image, (238, 188), (260, 188), (255, 255, 255), 3)
    template = plus_mask(image[154:222, 213:285]) > 0
    profile = {"slots": [{"slot": 0, "avatar": [213, 154, 72, 68]}]}
    bank = SimpleNamespace(diagnose=lambda patch: GrayRead(None, None, "empty", ()))
    for money, expected in ((None, [0]), ("100", [])):
        probe = LiveFrameEvidence(bank, profile, template)
        for frame in range(2):
            row = {"frame": frame, "scene_supported": True,
                   "stacks": {"0": {"value": money}},
                   "participation": {"slots": {"0": {"current": "UNKNOWN"}}}}
            probe(image, row)
        assert row["empty_seats_v1"] == expected


def live_row(frame, dealer, pot="0", board=0, cash=None):
    return {"frame": frame, "scene_supported": True, "source_sha256": "a" * 64,
            "live_dealer_candidate": dealer, "board_count": board,
            "cards": {"hero": [None, None], "board_slots": [None] * 5},
            "pot": {"value": pot}, "stacks": {str(s): {
                "value": str((cash or {}).get(s, 100)), "scores": [frame]}
                for s in range(8)}, "participation": {"slots": {}}}


def test_dealer_advance_starts_context_but_never_invents_posting():
    adapter = LiveStateAdapter()
    adapter.observe(live_row(0, 1))
    adapter.observe(live_row(1, 1))
    adapter.epoch = "old"
    adapter.observe(live_row(2, 2, pot="50"))
    result = adapter.observe(live_row(3, 2, pot="50"))
    assert result["live_boundary_reset"]
    assert result["observed_epoch"] != "old"
    assert adapter.epoch_events[-1]["status"] == "DEALER_ADVANCE_CONTEXT_CANDIDATE"
    assert adapter.epoch_events[-1]["posting_comparison"] is None
    assert not result["complete_legal_state"]


def test_score_noise_does_not_prevent_exact_posting_comparison():
    adapter = LiveStateAdapter()
    adapter.observe(live_row(0, 1))
    adapter.observe(live_row(1, 1))
    cash = {0: 96, 1: 94, 2: 92}
    adapter.observe(live_row(2, 2, pot="18", cash=cash))
    adapter.observe(live_row(3, 2, pot="18", cash=cash))
    event = adapter.epoch_events[-1]
    assert event["status"] == "MULTI_POST_DEAL_CANDIDATE"
    assert sum(map(Decimal, event["posting_comparison"]["debits"].values())) == 18


def test_midstreet_badge_or_gap_cannot_create_an_opening():
    adapter = LiveStateAdapter()
    adapter.observe(live_row(0, 1))
    adapter.observe(live_row(1, 1))
    adapter.observe(live_row(2, 2, board=3))
    result = adapter.observe(live_row(3, 2, board=3))
    assert not result["live_boundary_reset"]
    assert result["live_boundary_invalidated"]
    assert not adapter.observe(live_row(4, 2, board=0))["live_boundary_reset"]
    assert not adapter.observe(live_row(9, 3))["live_boundary_reset"]


def test_one_frame_post_debit_cannot_become_opening_money():
    adapter = LiveStateAdapter()
    for frame, dealer in ((0, 1), (1, 1), (2, 2)):
        adapter.observe(live_row(frame, dealer))
    adapter.observe(live_row(3, 2, pot="18", cash={0: 96, 1: 94, 2: 92}))
    assert adapter.epoch_events[-1]["status"] == "DEALER_ADVANCE_CONTEXT_CANDIDATE"
    assert adapter.epoch_events[-1]["posting_comparison"] is None
    adapter.observe(live_row(4, 2))
    assert not adapter.opening_updates


def test_late_stable_opening_gets_separate_receipt_without_rewriting_context():
    adapter, ledger = LiveStateAdapter(), LiveHandLedger()
    rows = [live_row(0, 1), live_row(1, 1), live_row(2, 2),
            live_row(3, 2, pot="18", cash={0: 96, 1: 94, 2: 92}),
            live_row(4, 2, pot="18", cash={0: 96, 1: 94, 2: 92})]
    for row in rows:
        row["observed_state_v2"] = adapter.observe(row)
        result = ledger.observe(row, adapter)
    assert adapter.epoch_events[-1]["status"] == "DEALER_ADVANCE_CONTEXT_CANDIDATE"
    assert adapter.epoch_events[-1]["posting_comparison"] is None
    assert result["observed_total"] == "18"
    assert result["opening_evidence"]["reconciliation"]["frame"] == 4
    assert len(adapter.opening_updates) == 1


def test_intervening_action_blocks_late_opening_reanchor():
    adapter = LiveStateAdapter()
    for row in [live_row(0, 1), live_row(1, 1), live_row(2, 2),
                live_row(3, 2, pot="18", cash={0: 96, 1: 94, 2: 92})]:
        adapter.observe(row)
    next_row = live_row(4, 2, pot="18", cash={0: 96, 1: 94, 2: 92})
    next_row["glyph_transitions"] = [{"frame": 4, "slot": 4, "glyph": "fold"}]
    adapter.observe(next_row)
    assert not adapter.opening_updates
    assert adapter.epoch_events[-1]["posting_comparison"] is None


def test_late_opening_reaches_causal_partition_without_changing_original_events():
    adapter, wagers = LiveStateAdapter(), LiveCausalWagers()
    for frame in range(10):
        posted = frame >= 5
        row = live_row(frame, 1 if frame < 2 else 2, pot="18" if posted else "0",
                       cash={0: 96, 1: 94, 2: 92} if posted else None)
        row["current_actor"] = 4
        row["actor_evidence"] = {"hero_turn": True}
        row["observed_state_v2"] = adapter.observe(row)
        amounts = {str(s): str([4, 6, 8][s]) if posted and s < 3 else None
                   for s in range(8)}
        visibility = {s: {"status": "VISIBLE_COIN_CANDIDATE" if v is not None
                          else "VISIBLE_EMPTY_CANDIDATE"} for s, v in amounts.items()}
        partition = {"title": row["pot"]["value"], "center": {"value": "0"},
                     "wagers": amounts, "visibility": visibility}
        result = wagers.observe(row, adapter, partition)
    assert adapter.epoch_events[-1]["status"] == "DEALER_ADVANCE_CONTEXT_CANDIDATE"
    assert result["status"] == "OBSERVED_STREET_WAGERS_CANDIDATE"
    assert result["street_price"] == "8"
    assert result["strategy_eligible"] is False
    assert adapter.cash  # Original opening cash evidence was retained.


def test_current_study_uses_explicit_unknown_and_short_call_guards():
    row = {"frame": 1, "source_frame": 50, "scene_supported": True,
           "board_count": 5, "cards": {"hero": HERO, "board_slots": BOARD},
           "current_actor": 4, "pot": {"value": "448"},
           "hero_controls_v1": {"price_confirmed": True, "call_amount": "260"},
           "empty_seats_v1": [0], "stacks": {"4": {"value": "290"},
                                             "7": {"value": "0"}},
           "street_wagers": {"7": "260"}, "participation": {"slots": {
               str(s): {"current": "FOLDED_CANDIDATE"} for s in (1, 2, 3, 5, 6)}}}
    result = current_river_study(row)
    assert result["status"] == "CONDITIONAL_STUDY"
    assert result["result"]["call_gross_lower"]["exact"] == "94"
    assert not result["eligibility_condition_verified"]
    short = deepcopy(row)
    short["stacks"]["4"]["value"] = "200"
    assert current_river_study(short)["status"] == "BLOCKED"
    short["stacks"]["4"]["value"] = "260"
    assert current_river_study(short)["status"] == "BLOCKED"
    unknown = deepcopy(row)
    unknown["empty_seats_v1"] = []
    assert current_river_study(unknown)["status"] == "BLOCKED"
