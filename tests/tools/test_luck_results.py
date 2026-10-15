"""Real results with the luck taken out, and the decision ledger."""

from decimal import Decimal

import pytest

from poker_engine.scoreboard import luck
from tools import luck_results as results

# Four players, dealer 4 (you): small blind 5, big blind 6, straddle 7; you
# act first. You go all in for your last 98 with aces, seat 7 calls with
# kings and the board makes them a set.
ALL_IN = [(10, "preflop", 4, "all_in", "98"), (12, "preflop", 5, "fold", "0"),
          (14, "preflop", 6, "fold", "0"), (16, "preflop", 7, "call", "94")]
BOARD = ["2c", "7d", "9h", "Js", "Kd"]


def facts(actions=ALL_IN, board=BOARD, dealer=4, seats=(4, 5, 6, 7), blind=None):
    return {"hand_id": "hand_1", "complete": True, "dealer": dealer,
            "blind_dealer": blind, "seats": list(seats), "board": list(board),
            "stacks": {}, "opening_pot": Decimal(15),
            "actions": [dict(zip(("frame", "street", "slot", "kind", "amount"), a))
                        for a in actions]}


def hand(shown=(("7", ("Kc", "Ks")),), cards="Ah Ad", chips=-100.0):
    return {"log": "s1", "hand_id": "hand_1", "your_cards": cards, "your_chips": chips,
            "shown_cards": [{"seat": int(seat), "cards": list(held)}
                            for seat, held in shown]}


def test_your_seat_comes_from_the_dealer_or_the_blinds():
    assert results.position(facts()) == (7, None)                     # the dealer
    assert results.position(facts(dealer=7)) == (0, None)             # small blind
    assert results.position(facts(dealer=None, blind=5)) == (2, None)  # straddle
    assert results.position(facts(dealer=None)) == (None, "dealer_unread")
    assert results.position(facts(seats=(5, 6, 7, 8))) == (None, "not_dealt_in")
    assert results.position(facts(seats=(4, 5, 6))) == (None, "players_3")


def test_card_luck_is_taken_out_of_normal_hands_with_cards_read():
    assert results.card_luck({"your_cards": "Ah Ad"}, facts(), False) == (
        luck.hole_luck(["Ah", "Ad"], 7), None)
    assert results.card_luck({"your_cards": "Ah Ad"}, facts(), True) == (
        None, "bomb_pot")
    assert results.card_luck({"your_cards": None}, facts(), False) == (
        None, "cards_unread")
    assert results.card_luck({"your_cards": "Ah Ah"}, facts(), False) == (
        None, "cards_unread")


def test_an_all_in_with_every_hand_shown_is_scored_against_the_average_board():
    found = results.runout(hand(), facts(), 2.0)
    # Pot 207 (antes 8, blinds 3, 100 each from you and seat 7), rake 10:
    # aces win about 81% of 197 against kings; this board lost all 100.
    assert found["allin"] is True and found["why"] is None
    assert found["replay"] == "stacks" and found["settle_matches"] is True
    assert -84 < found["luck"] < -76


def test_an_all_in_that_cannot_be_worked_out_says_why():
    assert results.runout(hand(shown=()), facts(), 2.0)["why"] == "cards_not_shown"
    assert results.runout(hand(), facts(board=BOARD[:4]), 2.0)["why"] == "board_unread"
    clash = hand(shown=(("7", ("Kd", "Ks")),))           # the river king twice
    assert results.runout(clash, facts(), 2.0)["why"] == "cards_conflict"
    found = results.runout(hand(shown=()), facts(), 2.0)
    assert found["allin"] is True and found["luck"] is None


def test_no_runout_when_nothing_was_left_to_come_for_you():
    folded = [(10, "preflop", 4, "fold", "0"), (12, "preflop", 5, "all_in", "98"),
              (14, "preflop", 6, "fold", "0"), (16, "preflop", 7, "call", "94")]
    assert results.runout(hand(), facts(folded), 2.0) == {
        "allin": False, "luck": 0.0, "why": None}
    unfinished = [(10, "preflop", 4, "call", "4")]
    found = results.runout(hand(), facts(unfinished), 2.0)
    assert found == {"allin": None, "luck": None, "why": "replay:not_finished"}
    found = results.runout(hand(), facts(seats=(4, 5, 6)), 2.0)
    assert found == {"allin": None, "luck": None, "why": "replay:players_3"}


def row(frame, *, hand_id="hand_0", turn=False, cards=("As", "Kd"), advice=None,
        stack="100", pot=15, actions=()):
    return {"processed": frame, "pts_seconds": frame * 0.5,
            "timing": {"published_at": frame * 0.5},
            "fields": {"scene_supported": True, "hero": list(cards),
                       "participants": {"4": "active", "5": "active", "6": "active",
                                        "7": "active"},
                       "hero_controls": {"visible": turn, "button": "call"},
                       "street": "preflop", "stacks": {"4": stack}, "pot": pot,
                       "actions_v1": {"hand_id": hand_id, "complete": False,
                                      "start": "boundary", "dealer": 4,
                                      "actions": [list(a) for a in actions]},
                       "solver_advice": advice or {"status": "idle",
                                                   "reason": "not_your_turn"}}}


CALL = {"status": "ready", "kind": "preflop", "advice": [{"action": "call"}]}


def session():
    """You call 4 on the button with ace-king and lose it; then fold 7-2."""
    called = [(6, "preflop", 4, "call", "4", "bet")]
    return ([row(f) for f in range(5)] + [row(5, turn=True, advice=CALL)]
            + [row(6, actions=called, stack="96", pot=19)]
            + [row(f, hand_id="hand_7", cards=("7c", "2d"), stack="96")
               for f in range(7, 12)]
            + [row(f, hand_id="hand_12", cards=("9c", "9d"), stack="96")
               for f in range(12, 15)])


def test_every_hand_gets_its_result_and_luck_and_every_decision_a_line():
    hands, ledger = results.hand_lines("s1", session(), "abc1234")
    first, second = hands
    assert (first["hand_id"], first["seat"], first["bb"]) == ("hand_0", "BTN", -2.0)
    assert first["card_luck"] == round(luck.hole_luck(["As", "Kd"], 7), 3)
    assert first["adjusted"] == round(-2.0 - luck.hole_luck(["As", "Kd"], 7), 3)
    assert first["allin"] is None and first["runout_missing"].startswith("replay:")
    assert first["followed"] == "yes" and first["code"] == "abc1234"
    assert second["bb"] == 0.0 and second["followed"] == "no_decision"
    assert "your_cards" not in first                  # the worth, not the cards
    [decision] = ledger
    assert (decision["advice"], decision["kind"], decision["you_did"],
            decision["followed"]) == ("call", "preflop", "call", True)
    assert decision["hand_bb"] == -2.0
    assert decision["hand_adjusted"] == first["adjusted"]
    assert "hero" not in decision and "board" not in decision


def line(bb, *, adjusted=None, card=0.0, bomb=False, followed="yes", code="c1",
         allin=False, runout=0.0, missing=None):
    return {"bb": bb, "adjusted": bb if adjusted is None else adjusted,
            "card_luck": card, "card_luck_missing": None if card is not None
            else "dealer_unread", "bomb_pot": bomb, "followed": followed,
            "code": code, "allin": allin, "runout_luck": runout,
            "runout_missing": missing, "settle_matches": True if allin else None}


def test_the_summary_splits_by_kind_followed_and_code():
    lines = ([line(3.0, adjusted=2.0, card=1.0)] * 40 + [line(-1.0, card=None)] * 10
             + [line(5.0, bomb=True, followed="no", code="c2")] * 5
             + [line(-50.0, adjusted=-10.0, allin=True, runout=-40.0)]
             + [line(0.0, allin=True, runout=None, missing="cards_not_shown")])
    summary = results.summarize(lines)
    assert summary["hands"] == 57
    assert summary["cards"] == {"taken_out": 42, "normal_hands": 52,
                                "missing": {"dealer_unread": 10}}
    assert summary["allin"] == {"hands": 2, "taken_out": 1, "not_replayed": 0,
                                "missing": {"cards_not_shown": 1},
                                "settle_matches": 1}
    assert summary["runout_luck_bb"] == -40.0
    assert summary["by_kind"]["bomb_pot"]["hands"] == 5
    assert summary["by_followed"]["no"]["hands"] == 5
    assert set(summary["by_code"]) == {"c1", "c2"}
    assert summary["adjusted_ci95"][0] < summary["adjusted_ci95_one_look"][0]
    assert summary["spread_per_hand_bb"]["luck_out"] < summary[
        "spread_per_hand_bb"]["as_played"]


@pytest.mark.parametrize("values,verdict", [
    ([5.0, 6.0] * 50, "赢"), ([-5.0, -6.0] * 50, "输"), ([5.0, -6.0] * 50, "说不准"),
    ([1.0], "说不准")])
def test_the_verdict_needs_the_whole_interval_on_one_side(values, verdict):
    assert results.summarize([line(v) for v in values])["verdict"] == verdict


def test_the_plain_lines_say_the_result_the_luck_and_the_hands_needed():
    lines = ([line(3.0, adjusted=2.0, card=1.0, followed="yes")] * 20
             + [line(-3.0, adjusted=-1.0, card=-2.0, followed="no")] * 20)
    text = results.plain_lines(results.summarize(lines))
    assert text[0].startswith("40 手：打出来 +0 bb/100；扣掉运气 +50 bb/100（95% 区间 ")
    assert text[0].endswith("结论：说不准）")
    assert text[1] == "运气：起手牌运气 -50 bb/100（40/40 手算得出）"
    assert text[2].startswith("按现在的波动，要把区间缩到 ±20 bb/100 共约需 ")
    assert text[3] == ("照建议打的 20 手扣运气后 +200，没照的 20 手 -100"
                       "（是他自己选的，只作参考）")
    assert results.plain_lines(results.summarize([])) == ["没有算得出成绩的手"]
