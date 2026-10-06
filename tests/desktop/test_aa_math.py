"""Table math from one reader payload: stated basis, explicit gaps."""

import pytest

from poker_engine.desktop.aa_math import AATableMath


def payload(*, hero=("5d", "6d"), board=(None,) * 5, states=None, pot="100",
            stacks=None, controls=None):
    states = states or {"0": "folded", "1": "active", "2": "folded",
                        "3": "all_in", "4": "active", "5": "folded",
                        "6": "empty", "7": "waiting"}
    stacks = stacks or {"1": "300", "3": "40", "4": "250"}
    return {
        "cards": {"hero": list(hero), "board_slots": list(board)},
        "pot": {"value": pot},
        "stacks": {slot: {"value": value} for slot, value in stacks.items()},
        "observed_state_v2": {"participants": {
            slot: {"state": state} for slot, state in states.items()}},
        "hero_controls_v1": controls or {"visible": False, "call_amount": None},
    }


@pytest.fixture(scope="module")
def math():
    return AATableMath(trials=400)


def test_equity_against_random_hands_of_opponents_still_in(math):
    result = math.compute(payload(board=("5h", "6c", "6s", None, None)))
    equity = result["equity"]
    assert equity["available"] and equity["opponents"] == 2
    assert equity["basis"] == "uniform_random_opponents"
    assert 0.85 < equity["value"] <= 1.0   # full house on the flop
    assert math.compute(payload(board=("5h", "6c", "6s", None, None)))[
        "equity"] == equity                 # cached, identical


@pytest.mark.parametrize("change, reason", [
    ({"hero": (None, None)}, "hero_cards_unknown"),
    ({"board": ("5h", None, "6s", None, None)}, "board_incomplete"),
    ({"board": ("5h", "6c", None, None, None)}, "board_incomplete"),
    ({"board": ("5d", "6c", "6s", None, None)}, "cards_inconsistent"),
    ({"states": {"4": "active"}}, "participants_unknown"),
    ({"states": {slot: "folded" for slot in "01234567"}}, "hero_not_in_hand"),
    ({"states": {**{slot: "folded" for slot in "01235667"}, "4": "active"}},
     "no_opponents"),
])
def test_equity_gaps_are_named_not_guessed(math, change, reason):
    assert math.compute(payload(**change))["equity"] == {
        "available": False, "reason": reason}


def test_pot_odds_only_on_hero_turn_with_a_read_call(math):
    assert math.compute(payload())["pot_odds"]["reason"] == "not_hero_turn"
    unknown = payload(controls={"visible": True, "call_amount": None})
    assert math.compute(unknown)["pot_odds"]["reason"] == "call_amount_unknown"
    odds = math.compute(payload(controls={"visible": True, "call_amount": "25"}))[
        "pot_odds"]
    assert odds["available"] and odds["ratio"] == pytest.approx(4.0)
    assert odds["required_equity"] == pytest.approx(0.2)
    check = payload(controls={"visible": True, "call_amount": "0"})
    assert math.compute(check)["pot_odds"]["reason"] == "nothing_to_call"


def test_spr_uses_the_effective_stack(math):
    spr = math.compute(payload())["spr"]
    # Hero 250 against the deepest remaining opponent 300 -> effective 250.
    assert spr["available"] and spr["value"] == pytest.approx(2.5)
    assert spr["effective_stack"] == "250"
    missing = payload(stacks={"1": "300", "4": "250"})
    assert math.compute(missing)["spr"]["reason"] == "opponent_stack_unknown"
    assert math.compute(payload(pot="0"))["spr"]["reason"] == "pot_unknown"


def test_current_evidence_seat_states_take_precedence(math):
    current = payload(board=("5h", "6c", "6s", None, None))
    current["seat_states_v1"] = {"seats": {
        slot: {"state": "folded"} for slot in "01235667"}}
    current["seat_states_v1"]["seats"].update(
        {"4": {"state": "active"}, "1": {"state": "active"}})
    assert math.compute(current)["equity"]["opponents"] == 1
    current["seat_states_v1"]["seats"]["7"] = {"state": "unknown"}
    assert math.compute(current)["equity"]["reason"] == "participants_unknown"
