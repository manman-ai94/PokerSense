"""Replaying real hands with the 大道至简 rule next to the window, on
synthetic frames."""

from decimal import Decimal

from tests.tools.test_aa_compare_advice import rows
from tools.simple_replay import (fold_value, missed_raise, posted, replay_log,
                                 screen_moves, summarize)


def test_both_answer_every_turn_and_are_priced_against_the_cards_shown():
    found = rows()
    found[-1]["fields"]["shown_cards"] = {
        "seats": {"0": {"cards": ["Kc", "Kd"]}}, "unknown": []}
    (item,) = replay_log("log", found)
    assert item["street"] == "preflop" and item["hero"] == "Ad Qd"
    assert item["window"]["action"] in ("call", "raise", "fold")
    assert item["simple"]["source"] == "table"
    assert item["simple"]["action"] in ("call", "raise", "fold")
    shown = item["shown"]
    assert shown["cards"] == {"0": "Kc Kd"}
    assert shown["simple"] is not None and shown["window"] is not None
    summary = summarize([item])
    assert summary["simple_answered"] == summary["window_answered"] == 1
    assert summary["shown"]["priced"] == 1


def test_the_screen_reads_raises_calls_and_checks():
    facts = {"seats": [0, 4, 5, 6, 7], "stakes": {
        "small_blind": Decimal(1), "big_blind": Decimal(2),
        "straddle_amount": Decimal(4), "ante": Decimal(2)},
        "street_pots": {"preflop": (Decimal(17), None), "flop": (Decimal(30), None)},
        "opening_wagers": {5: Decimal(1), 6: Decimal(2), 7: Decimal(4)},
        "board": ["Ks", "9c", "5d"],
        "actions": [
            {"slot": 0, "street": "preflop", "kind": "raise", "amount": "12"},
            {"slot": 4, "street": "preflop", "kind": "call", "amount": "12"},
            {"slot": 5, "street": "preflop", "kind": "fold", "amount": None},
            {"slot": 6, "street": "preflop", "kind": "fold", "amount": None},
            {"slot": 7, "street": "preflop", "kind": "fold", "amount": None},
            {"slot": 0, "street": "flop", "kind": "raise", "amount": "20"}]}
    moves, preflop_actions, last = screen_moves(facts)
    assert [(move.seat, move.street, move.kind) for move in moves] == [
        (0, "preflop", "r"), (5, "preflop", "f"), (6, "preflop", "f"),
        (7, "preflop", "f"), (0, "flop", "r")]
    assert preflop_actions[:2] == [(0, "r"), (4, "c")]
    assert last == {"preflop": 0, "flop": 0}
    bet = moves[-1]
    # Seat 0 raised before the flop, so he bets the flop as the raiser, into 30.
    assert bet.spot == "checked_to" and bet.role == "pfa"
    assert bet.board == ("Ks", "9c", "5d") and abs(bet.size - 20 / 30) < 1e-9


def test_what_you_posted_follows_your_place():
    stakes = {"small_blind": "1", "big_blind": "2", "straddle_amount": "4", "ante": "2"}
    facts = {"seats": [0, 1, 2, 3, 4, 5, 6, 7], "dealer": 1, "stakes": stakes,
             "opening_wagers": {}, "actions": [{"street": "preflop"}],
             "opening_pot": Decimal(23)}
    # Seat 4 is the straddle three seats after the dealer: ante 2 + 4.
    assert posted(facts) == Decimal(6)
    assert posted({**facts, "opening_wagers": {4: Decimal(4)}}) == Decimal(6)
    # The dealer also pays the mushroom post, 3 big blinds.
    assert posted({**facts, "dealer": 4}) == Decimal(2 + 6)
    assert posted({**facts, "dealer": 0}) == Decimal(2)


def test_a_fold_is_worth_what_you_had_against_how_the_hand_ended():
    items = [
        {"log": "a", "hand_id": "h1", "street": "flop", "hero": "Ad Qd",
         "window": {"action": "call"}, "simple": {"action": "fold"},
         "you_did": "call", "fold_keeps_bb": 40.0},
        {"log": "a", "hand_id": "h1", "street": "turn", "hero": "Ad Qd",
         "window": {"action": "call"}, "simple": {"action": "fold"},
         "you_did": "call", "fold_keeps_bb": 60.0},
        {"log": "a", "hand_id": "h2", "street": "river", "hero": "Kc Kd",
         "window": {"action": "fold"}, "simple": {"action": "fold"},
         "you_did": "call", "fold_keeps_bb": -25.0},
        {"log": "a", "hand_id": "h3", "street": "river", "hero": "Kc Kd",
         "window": {"action": "fold"}, "simple": {"action": "call"},
         "you_did": "fold", "fold_keeps_bb": 0.0}]
    # Only each hand's first such fold counts: after it you are out.
    assert fold_value(items, "simple") == {"hands": 2, "kept_bb": 15.0,
                                           "saved": 1, "cost": 1}
    assert fold_value(items, "window") == {"hands": 1, "kept_bb": -25.0,
                                           "saved": 0, "cost": 1}


def test_a_bet_the_actions_missed_is_still_read():
    facts = {"seats": [0, 4], "stakes": {
        "small_blind": Decimal(1), "big_blind": Decimal(2),
        "straddle_amount": Decimal(4), "ante": Decimal(2)},
        "street_pots": {"flop": (Decimal(40), None)}, "opening_wagers": {},
        "board": ["Ks", "9c", "5d"],
        "actions": [
            {"slot": 4, "street": "flop", "kind": "check", "amount": None},
            # Seat 0's bet of 30 was not read; you called it.
            {"slot": 4, "street": "flop", "kind": "call", "amount": "30"}]}
    moves, _, last = screen_moves(facts)
    (bet,) = moves
    assert (bet.seat, bet.kind, bet.spot) == (0, "r", "checked_to")
    assert abs(bet.size - 30 / 40) < 1e-9 and last["flop"] is None
    # A call that matches the bet read adds nothing.
    facts["actions"][0] = {"slot": 0, "street": "flop", "kind": "raise", "amount": "30"}
    moves, _, last = screen_moves(facts)
    assert [(move.seat, move.kind) for move in moves] == [(0, "r")]
    assert last["flop"] == 0
    # Facing a raise nobody was read making: the opponents whose bet is not
    # on screen made it, sized from your price.
    (raised,) = missed_raise([], (0,), {"4": Decimal(61)}, Decimal(61),
                             Decimal(145), Decimal(388), ("Th", "7s", "2d"), "flop")
    assert (raised.seat, raised.kind, raised.spot) == (0, "r", "facing_bet")
    assert abs(raised.size - 206 / 182) < 1e-9


def test_the_window_answers_of_an_earlier_run_can_stand_in():
    cached = {("hand_1", "preflop", 0): {"kind": "preflop", "action": "fold"}}
    (item,) = replay_log("log", rows(), cached=cached)
    assert item["window"] == {"kind": "preflop", "action": "fold"}
    assert item["simple"]["source"] == "table"
