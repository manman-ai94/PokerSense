"""Review: one piece of advice grades at most one of your actions."""

from poker_engine.desktop.aa_grading import AAGrades

OPTIONS = [{"action": "raise", "chips": 30.0, "big_blinds": 3.0, "to": "12",
            "chips_in": "12"},
           {"action": "call", "chips": 4.0, "big_blinds": 0.4, "chips_in": "4"},
           {"action": "fold", "chips": 0.0, "big_blinds": 0.0}]
READY = {"status": "ready", "options": OPTIONS, "to_call": "4",
         "advice": [{"action": "raise", "frequency": 1.0}]}
BEFORE = [[5, "preflop", 2, "fold", "0", "no_chips"],
          [6, "preflop", 3, "fold", "0", "no_chips"]]


class Advice:
    """The advice for your first preflop decision (two actions before you)."""

    def settled(self):
        return "hand_1", {(2, "preflop"): READY}


def fields(actions, visible):
    return {"street": "preflop", "hero": ["As", "Kd"], "board": [None] * 5,
            "pot": "13", "stacks": {"4": "200"},
            "participants": {str(s): "active" for s in range(6)},
            "hero_controls": {"visible": visible, "button": "call",
                              "call_amount": "4"},
            "actions_v1": {"hand_id": "hand_1", "dealer": 5, "actions": actions}}


def test_a_second_decision_without_advice_is_not_graded_by_the_first():
    grades = AAGrades(Advice(), clock=lambda: 1000.0)
    grades.observe_fields(fields(BEFORE, True), 10)           # your turn: advice
    raised = BEFORE + [[11, "preflop", 4, "raise", "12", "pot_rise"]]
    report = grades.observe_fields(fields(raised, False), 12)
    assert report["graded"] == 1 and report["last"]["grade"] == "best"
    # Seat 5 re-raises; you fold. No advice was made for this second decision
    # (your buttons or cards were not read in time), so it cannot be graded:
    # the first decision's values (raise +3 BB, fold 0) are not this spot's.
    folded = raised + [[15, "preflop", 5, "raise", "40", "pot_rise"],
                       [19, "preflop", 4, "fold", "0", "no_chips"]]
    report = grades.observe_fields(fields(folded, False), 20)
    assert report["graded"] == 1, report["last"]
