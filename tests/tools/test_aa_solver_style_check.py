"""The solver's bluffs and bluff-catches by the opponent's read, from synthetic logs."""

from collections import Counter

from tools.aa_solver_style_check import count, summary, villain_type

PASSIVE = {"hands": 40, "postflop": 30, "aggression": 0.1}
WILD = {"hands": 40, "postflop": 30, "aggression": 0.5}


def row(hero, board, advice, to_call, pot, read, street="river", decision=0, **extra):
    report = {"status": "ready", "street": street, "decision": decision, "hand_id": 7,
              "advice": advice, "to_call": str(to_call), "pot": str(pot),
              "seat_reads": {"2": read}, **extra}
    return {"fields": {"hero": hero, "board": board, "solver_advice": report,
                       "participants": {"4": "active", "2": "active", "6": "folded"}}}


BOARD = ["Ah", "Kd", "7c", "3s", "2d"]


def test_bluffs_and_bluff_catches_are_counted_by_read():
    rows = [
        # Nothing to call with nothing (QJ high): bets 40% of the time.
        row(["Qs", "Jc"], BOARD, [{"action": "check", "frequency": 0.6},
                                  {"action": "bet", "frequency": 0.4}],
            0, 100, PASSIVE),
        # The same decision again on the next frame: counted once.
        row(["Qs", "Jc"], BOARD, [{"action": "bet", "frequency": 1.0}],
            0, 100, PASSIVE),
        # A pot-size bet to call (100 into 100) with a pair of kings: calls 70%.
        row(["Kc", "9h"], BOARD, [{"action": "call", "frequency": 0.7},
                                  {"action": "fold", "frequency": 0.3}], 100, 200, WILD,
            decision=1),
        # A half-pot bet: not big.
        row(["Kc", "9h"], BOARD, [{"action": "call", "frequency": 1.0}], 50, 150, WILD,
            decision=2),
        # Range-rule answers and the rough rule are not the solver's.
        row(["Qs", "Jc"], BOARD, [{"action": "bet", "frequency": 1.0}], 0, 100, PASSIVE,
            decision=3, kind="multiway"),
    ]
    out = summary(count(rows, Counter()))
    assert out["river|passive|open"] == {"decisions": 1, "nothing": 1,
                                         "bluff_weight": 0.4, "bluff_weight_share": 0.4}
    assert out["river|aggressive|facing_big"] == {
        "decisions": 1, "weak": 1, "weak_continue": 0.7, "weak_continue_share": 0.7}
    assert out["river|all|open"]["decisions"] == 1


def test_reads_sort_opponents():
    assert villain_type(None) == "unknown"
    assert villain_type({"postflop": 3, "aggression": 0.0}) == "unknown"
    assert villain_type(PASSIVE) == "passive" and villain_type(WILD) == "aggressive"
    assert villain_type({"postflop": 20, "aggression": 0.3}) == "normal"


def test_the_decisions_a_style_rule_would_change_are_counted_and_listed():
    rows = [
        # QJ high, nothing to call: bets 40% -> the no-bluff rule checks.
        row(["Qs", "Jc"], BOARD, [{"action": "check", "frequency": 0.6},
                                  {"action": "bet", "frequency": 0.4, "chips": "50"}],
            0, 100, PASSIVE),
        # Kings facing 100 into 100 from a passive player: folds.
        row(["Kc", "9h"], BOARD, [{"action": "call", "frequency": 0.7},
                                  {"action": "fold", "frequency": 0.3}],
            100, 200, PASSIVE, decision=1),
        # The same from a player read as aggressive over many decisions: calls.
        row(["Kc", "9h"], BOARD, [{"action": "call", "frequency": 1.0}], 100, 200,
            {"hands": 300, "postflop": 200, "aggression": 0.6}, decision=2),
        # The turn: no rule.
        row(["Qs", "Jc"], BOARD[:4], [{"action": "bet", "frequency": 1.0}], 0, 100,
            PASSIVE, street="turn", decision=3),
    ]
    listed = []
    out = summary(count(rows, Counter(), listed))
    assert out["river|passive|style_nobluff"] == {"decisions": 1, "moved": 0.4}
    assert out["river|passive|style_nocatch"] == {"decisions": 1, "moved": 0.7}
    assert "river|aggressive|style_nocatch" not in out
    assert [(change["decision"], change["rule"]) for change in listed] == [
        (0, "nobluff"), (1, "nocatch")]
