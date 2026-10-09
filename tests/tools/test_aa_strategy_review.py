"""The strategy review: each decision's answers, what you did, and the flags."""

from tools.aa_strategy_review import ledger, review


def row(frame, *, turn=True, street="river", board=("Tc", "2s", "7d", "8h", "Qc"),
        cards=("Ad", "Ts"), advice=None, pot="544", players=("4", "7"),
        actions=(), price=None):
    return {"processed": frame, "pts_seconds": frame * 0.1,
            "timing": {"published_at": frame * 0.1},
            "fields": {"scene_supported": True, "hero": list(cards) if cards else None,
                       "board": list(board), "street": street, "pot": pot,
                       "participants": {seat: "active" for seat in players},
                       "hero_controls": {"visible": turn,
                                         "button": "check" if price is None else "call",
                                         "call_amount": price},
                       "stacks": {"4": "600"},
                       "actions_v1": {"hand_id": "hand_1", "complete": False,
                                      "start": "boundary", "dealer": 6,
                                      "actions": [list(a) for a in actions]},
                       "solver_advice": advice or {"status": "idle",
                                                   "reason": "not_your_turn"}}}


def ready(kind, action, share):
    return {"status": "ready", "kind": kind, "advice": [{"action": action}],
            "range_equity": {"value": share}}


def test_a_sure_bet_with_one_pair_and_an_answer_that_changed_under_you():
    # 10/09 hand_37438: top pair on the river read as 100% against a seat that
    # had only checked and called; first the rough rule said check.
    bet = [(30, "river", 4, "raise", "272", "pot_rise")]
    rows = ([row(0, turn=False), row(1, advice=ready("rough", "check", 0.5)),
             row(2, advice=ready("multiway", "bet", 1.0)),
             row(30, turn=False, actions=bet)])
    result = review([("log", rows)])
    (turn,) = result["decisions"]
    assert [a["action"] for a in turn["answers"]] == ["check", "raise"]
    assert turn["you_did"] == "raise" and turn["followed"] is True
    assert set(turn["flags"]) == {"changed", "sure_with_one_pair"}
    assert result["summary"]["flags"]["sure_with_one_pair"] == {"river": 1}


def test_a_rough_check_with_a_strong_hand_and_what_the_screen_missed():
    # Trips checked by the rough rule; the pot and your cards not read.
    rows = [row(0, turn=False),
            row(1, cards=("5s", "6h"), board=("7s", "9s", "5c", "5h"), street="turn",
                pot=None, advice=ready("rough", "check", 0.95)),
            row(2, cards=None, board=("7s", "9s", "5c", "5h"), street="turn",
                pot=None, advice=ready("rough", "check", 0.95))]
    (turn,) = review([("log", rows)])["decisions"]
    assert set(turn["flags"]) == {"rough_final", "strong_check", "pot_unread"}
    # A flush draw at 30% checking is fine; no advice at all is flagged.
    rows = [row(0, turn=False), row(1, street="turn", board=("7s", "9s", "5c", "5h"),
                                    advice=ready("multiway", "check", 0.3))]
    assert review([("log", rows)])["decisions"][0]["flags"] == []
    rows = [row(0, turn=False), row(1, price="40")]
    flags = review([("log", rows)])["decisions"][0]["flags"]
    assert flags == ["no_advice"]


def test_the_ledger_adds_sessions_up_and_replaces_one_run_again(tmp_path):
    path = tmp_path / "ledger.jsonl"
    one = {"decisions": 10, "followed": 8, "followed_of": 9,
           "chips": {"normal": 40.0, "normal_hands": 20, "bomb_pot": -20.0,
                     "bomb_pot_hands": 2}}
    two = {**one, "chips": {"normal": -10.0, "normal_hands": 18}}
    ledger(path, "1009", one)
    ledger(path, "1010", two)
    total = ledger(path, "1010", two)            # the same session again
    assert total["sessions"] == 2 and total["hands"] == 40
    assert total["bb_per_100"] == round(10 / 2 / 40 * 100, 1)
    assert total["normal_bb_per_100"] == round(30 / 2 / 38 * 100, 1)
    assert total["bomb_pot_bb_per_100"] == -500.0
    assert (total["followed"], total["followed_of"]) == (16, 18)
