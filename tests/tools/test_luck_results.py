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


def test_an_all_in_the_replay_settles_otherwise_keeps_its_luck():
    # The table took 100 from you; a replay paying out 60 more or less than
    # that (more than 5% of the pot) put in other chips than the table did.
    for chips in (-40.0, -160.0):
        found = results.runout(hand(chips=chips), facts(), 2.0)
        assert found["allin"] is True and found["luck"] is None
        assert found["why"] == "settle_mismatch" and found["settle_matches"] is False


def test_a_small_blind_all_in_won_with_the_mushroom_pool_has_its_luck_out():
    """A small blind who wins the pot takes the mushroom pool too, which is
    not in the replay: its luck comes out whoever won (until 10/17 only when
    you lost, so the results leaned your way)."""
    # Dealer 7: you (4) are the small blind and shove your last 97 with
    # aces, seat 6 calls 94 with kings.
    shove = [(10, "preflop", 7, "fold", "0"), (12, "preflop", 4, "all_in", "97"),
             (14, "preflop", 5, "fold", "0"), (16, "preflop", 6, "call", "94")]
    kings = (("6", ("Kc", "Ks")),)
    lost = results.runout(hand(kings, chips=-100.0), facts(shove, dealer=7), 2.0)
    assert lost["luck"] is not None and lost["settle_matches"] is True
    # Won: 206 less 10 rake less your 100, and the pool's 30 (not read).
    won_board = BOARD[:4] + ["3d"]
    won = results.runout(hand(kings, chips=126.0), facts(shove, won_board, dealer=7),
                         2.0)
    assert won["luck"] is not None and won["settle_matches"] is True
    assert won["luck"] == pytest.approx(lost["luck"] + 98)
    # More than the pool can hold (40 big blinds when not read) or than the
    # pool read: a misread, its luck kept.
    for chips, pool in ((226.0, None), (156.0, "30")):
        rows = [{"fields": {"mushroom_pool": pool}}]
        found = results.runout(hand(kings, chips=chips),
                               facts(shove, won_board, dealer=7), 2.0, rows)
        assert found["why"] == "settle_mismatch", (chips, pool)


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


# The same all-in as the frames show it: you (seat 4) all in for your last
# 100 with aces, seat 7 with kings. The pot holds 15 of blinds and antes;
# the screen's pot keeps a bet you could not call until the hand is paid.
STREETS = ["preflop", "flop", "flop", "turn", "river", "river"]


def frame(at, *, street="preflop", pot=15, you="100", them="300", you_state="active",
          them_state="active"):
    return {"processed": at, "pts_seconds": at * 0.5,
            "fields": {"street": street, "pot": pot, "stacks": {"4": you, "7": them},
                       "participants": {"4": you_state, "5": "folded", "6": "folded",
                                        "7": them_state}}}


def runout_frames(kind):
    """``called``: you shove, seat 7 calls (300 behind); ``both``: seat 7
    shoves 300, you call all in; ``raised``: seat 7 (500) bets 300, you call
    all in, and his 200 you could not call goes back with the pot."""
    them = "500" if kind == "raised" else "300"
    rows = [frame(at, them=them) for at in range(5)]
    gone = {"you": "0", "you_state": "all_in"}
    if kind == "called":
        rows += [frame(at, pot=115, **gone) for at in range(5, 8)]
        paid, left = "405", "200"
    elif kind == "both":
        rows += [frame(at, pot=315, them="0", them_state="all_in")
                 for at in range(5, 8)]
        paid, left = "405", "0"
    else:
        rows += [frame(at, pot=315, them="200") for at in range(5, 8)]
        paid, left = "605", "200"
    pot = 215 if kind == "called" else 415
    rows += [frame(at, street=street, pot=pot, them=left, **gone)
             for at, street in zip(range(8, 14), STREETS)]
    return rows + [frame(at, street="river", pot=pot, them=paid, **gone)
                   for at in (14, 15)]


SCREEN = {"board": BOARD, "seats": [4, 5, 6, 7], "stakes": None}


def test_an_all_in_that_does_not_replay_is_worked_out_from_the_screen():
    # The pot played for is 215, 205 after rake, however it was read: the
    # pot when seat 7 called; the pot less his 200 over your 100 with both
    # all in; what he won (105) plus what you lost.
    found = [results.screen_runout(hand(), runout_frames(kind), SCREEN, 2.0)
             for kind in ("called", "both", "raised")]
    assert all(item["allin"] is True and item["why"] is None
               and item["replay"] == "screen" for item in found)
    assert -86 < found[0]["luck"] < -80
    assert found[0]["luck"] == pytest.approx(found[1]["luck"])
    assert found[0]["luck"] == pytest.approx(found[2]["luck"])
    # The river not read: your result says you lost, the luck is the same.
    cut = results.screen_runout(hand(), runout_frames("called"),
                                {**SCREEN, "board": BOARD[:4]}, 2.0)
    assert cut["luck"] == pytest.approx(found[0]["luck"])
    # Three seats dealt (the AA rules cover 4-8): the same rake.
    three = results.screen_runout(hand(), runout_frames("called"),
                                  {**SCREEN, "seats": [4, 5, 7]}, 2.0)
    assert three["luck"] == pytest.approx(found[0]["luck"])
    # runout() takes it when the hand does not replay.
    unfinished = facts([(10, "preflop", 4, "call", "4")])
    assert results.runout(hand(), unfinished, 2.0, runout_frames("called")) == found[0]


def test_a_screen_all_in_whose_result_does_not_add_up_keeps_its_luck():
    # 160 lost where you had 100: no reading of the pot agrees.
    for kind in ("called", "both"):
        found = results.screen_runout(hand(chips=-160.0), runout_frames(kind),
                                      SCREEN, 2.0)
        assert found["allin"] is True and found["luck"] is None
        assert found["why"] == "settle_mismatch"


def test_the_screen_says_when_nothing_was_left_to_come_or_cards_are_missing():
    rows = runout_frames("called")
    found = results.screen_runout(hand(shown=()), rows, SCREEN, 2.0)
    assert (found["allin"], found["luck"], found["why"]) == (True, None,
                                                             "cards_not_shown")
    # Seat 7 folded (and showed his cards anyway): you won it without a runout.
    folded = [frame(at, them_state="active") for at in range(3)] + [
        frame(at, them_state="folded") for at in range(3, 8)]
    found = results.screen_runout(hand(), folded, SCREEN, 2.0)
    assert (found["allin"], found["luck"]) == (False, 0.0)
    # You folded.
    yours = [frame(at) for at in range(3)] + [frame(at, you_state="folded")
                                              for at in range(3, 8)]
    assert results.screen_runout(hand(), yours, SCREEN, 2.0)["allin"] is False
    # All in on the river: nothing left to come.
    late = [{**item, "fields": {**item["fields"], "street": "river"}} for item in rows]
    assert results.screen_runout(hand(), late, SCREEN, 2.0)["allin"] is False
    # Never dealt in: the screen cannot tell.
    away = [frame(at, you_state="waiting") for at in range(8)]
    assert results.screen_runout(hand(), away, SCREEN, 2.0) is None


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
    # It does not replay; the screen shows nobody all in.
    assert first["allin"] is False and first["runout_missing"] is None
    assert first["runout_from"] == "screen"
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
                                "settle_matches": 1, "from_screen": 0,
                                "screen_checked": 0}
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
    assert text[2].startswith("按现在的波动，区间缩到 ±100 bb/100 共约需 ")
    assert "、±20 bb/100 共约需 " in text[2]
    assert text[3] == ("照建议打的 20 手扣运气后 +200，没照的 20 手 -100"
                       "（是他自己选的，只作参考）")
    assert results.plain_lines(results.summarize([])) == ["没有算得出成绩的手"]
