"""Review 2026-10-08: the live hand rebuilt for advice must match your price.

When the action history misses an action, ``solver_observation`` fills it in
(``_fill``) or picks another dealer that fits the betting order. In the
hands below the rebuilt table asks you to put in a different amount than
your call button shows, and the advice is still given from it.
"""

from decimal import Decimal

from poker_engine.desktop.aa_solver_input import solver_observation

HERO = 4


def _actions(rows):
    return [{"frame": frame, "street": street, "slot": slot, "kind": kind,
             "amount": amount, "source": "no_chips"}
            for frame, street, slot, kind, amount in rows]


def test_a_missed_raise_from_a_seat_that_folded_later_is_not_read_as_a_fold():
    # Seven players, dealer 5: SB 6, BB 7, straddle 1; seat 2 acts first.
    # Seat 3 raised to 29 (not read) and folded to the later raise, so the
    # table shows it folded now. The fill reads its missing action as a fold
    # at that point; your call of 29 is then replayed as a call of 4, and the
    # rebuilt table asks 50 where your button says 25.
    hand = {
        "hand_id": "h", "complete": True, "dealer": 5,
        "seats": [1, 2, 3, 4, 5, 6, 7], "board": [], "opening_pot": None,
        "actions": _actions([
            (10, "preflop", 2, "fold", "0"),
            (16, "preflop", 4, "call", "29"),
            (19, "preflop", 5, "fold", "0"),
            (22, "preflop", 6, "raise", "53"),
            (25, "preflop", 7, "call", "52"),
            (28, "preflop", 1, "call", "50"),
            (31, "preflop", 3, "fold", "0")]),
        "stacks": {1: Decimal(344), 2: Decimal(398), 3: Decimal(369),
                   4: Decimal(369), 5: Decimal(398), 6: Decimal(344),
                   7: Decimal(344)},
        "states": {1: "active", 2: "folded", 3: "folded", 4: "active",
                   5: "folded", 6: "active", 7: "active"},
        "price": Decimal(25)}
    observation, reason = solver_observation(hand, HERO, ["Qs", "Qh"])
    assert observation is None or Decimal(observation["to_call"]) == hand["price"], (
        f"advice built for a price of {observation['to_call']}, your button says 25")


def test_a_missed_first_action_does_not_move_the_dealer():
    # Six players, dealer 5 (read right): SB 0, BB 1, straddle 2, seat 3 first.
    # Seat 3's limp is not read; it is still in the hand. Dealer 0 then fits
    # the betting order, so seat 2 is read as the big blind and you as first
    # to act, and the rebuilt table asks 42 where your button says 44.
    hand = {
        "hand_id": "h", "complete": True, "dealer": 5,
        "seats": [0, 1, 2, 3, 4, 5], "board": [], "opening_pot": None,
        "actions": _actions([
            (13, "preflop", 4, "raise", "16"),
            (16, "preflop", 5, "fold", "0"),
            (19, "preflop", 0, "fold", "0"),
            (22, "preflop", 1, "fold", "0"),
            (25, "preflop", 2, "raise", "56"),
            (28, "preflop", 3, "call", "56")]),
        "stacks": {seat: Decimal(300) for seat in range(6)},
        "states": {0: "folded", 1: "folded", 2: "active", 3: "active",
                   4: "active", 5: "folded"},
        "price": Decimal(44)}
    observation, reason = solver_observation(hand, HERO, ["Qs", "Qh"])
    assert observation is None or (
        Decimal(observation["to_call"]) == hand["price"]
        and observation["dealer_seat"] == 5), (
        f"dealer {observation['dealer_seat']}, price {observation['to_call']}")
