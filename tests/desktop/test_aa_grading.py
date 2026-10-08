"""Grading your decisions against the advice once you have acted."""

from concurrent.futures import Future
from decimal import Decimal

from poker_engine.desktop.aa_grading import AAGrades, preflop_grade, solver_grade
from poker_engine.desktop.aa_solver_advice import AASolverAdvice
from tests.desktop.test_aa_solver_advice import Bot, Inline, payload, preflop_turn

MIX = {"CALL": 0.7, "RAISE 30.000000": 0.2, "FOLD": 0.1}


class Later:
    """Holds each job until ``finish`` is called."""

    def __init__(self):
        self.jobs = []

    def submit(self, function, *args):
        future = Future()
        self.jobs.append((future, function, args))
        return future

    def finish(self):
        for future, function, args in self.jobs:
            future.set_result(function(*args))


def feed(advice, grades, rows):
    report = None
    for frame, row in rows:
        advice.observe(row, frame)
        report = grades(row, frame)
    return report


def acted(frame, kind, amount, street="turn", at=46, hero=("Qs", "Qh"), **options):
    """A frame after you acted: your action is in the history, buttons gone."""
    row = payload(frame, hero=hero, **options)
    row["hero_controls_v1"] = {"visible": False}
    source = "no_chips" if kind in ("fold", "check") else "pot_rise"
    row["action_history_v1"]["actions"].append(
        {"frame": at, "street": street, "slot": 4, "kind": kind, "amount": amount,
         "amount_source": source})
    return row


def preflop_acted(kind, amount, hero):
    """Your preflop action at frame 12 as the history read it."""
    row = payload(13, hero=hero, extra_pot=0)
    for action in row["action_history_v1"]["actions"]:
        if action["slot"] == 4:
            source = "no_chips" if kind in ("fold", "check") else "pot_rise"
            action.update(kind=kind, amount=amount, amount_source=source)
    return row


def turn_decision(kind, amount, bot=None, executor=None):
    advice = AASolverAdvice(bot or Bot(MIX), executor or Inline())
    grades = AAGrades(advice, clock=lambda: 1000.0)
    rows = [(frame, payload(frame)) for frame in range(50)]
    return advice, grades, feed(advice, grades, rows + [(50, acted(50, kind, amount))])


def test_your_turn_action_is_graded_by_how_often_the_solver_takes_it():
    expected = {("call", "10"): ("best", 0.7), ("raise", "30"): ("fine", 0.2),
                ("fold", "0"): ("slip", 0.1)}
    for (kind, amount), (grade, share) in expected.items():
        report = turn_decision(kind, amount)[2]
        last = report["last"]
        assert (last["grade"], last["frequency"]) == (grade, share)
        assert last["chosen"] == kind
        assert last["street"] == "turn" and last["hand_id"] == "hand_1"
        assert last["hero"] == ["Qs", "Qh"] and last["board"][:4] == [
            "Ah", "Kd", "7c", "2s"]
        assert last["to_call"] == "10" and last["stack"] == "200"
        assert last["facing"] == {"slot": 2, "kind": "raise", "amount": "10",
                                  "raises": 1}
        assert last["dealt"] == [0, 1, 2, 3, 4, 5] and last["dealer"] == 5
        assert last["action"] == {"kind": kind, "amount": amount}
        assert last["advice"][0] == {"action": "call", "frequency": 0.7}
        assert last["at"] == 1000.0 and "options" not in last
        assert (report["graded"], report["hands"]) == (1, 1)
        assert report["best"] == (grade == "best")
        assert report["rows"] == [last] and report["acts_on_client"] is False


def test_a_solve_finishing_after_you_acted_still_grades_the_action():
    executor = Later()
    advice, grades, report = turn_decision("call", "10", executor=executor)
    assert report["graded"] == 0                 # still being worked out
    executor.finish()
    report = feed(advice, grades, [(51, acted(51, "call", "10"))])
    assert report["graded"] == 1 and report["last"]["grade"] == "best"
    # The same action is graded once.
    assert feed(advice, grades, [(52, acted(52, "call", "10"))])["graded"] == 1


def test_no_advice_or_an_impossible_action_gives_no_grade():
    assert turn_decision("call", "10", bot=Bot(error="own_hand_not_in_range"))[2][
        "graded"] == 0
    # Checking while facing a bet cannot be matched to the solver's options.
    assert turn_decision("check", "0")[2]["graded"] == 0
    # An action whose amount is still being read waits for it.
    advice = AASolverAdvice(Bot(MIX), Inline())
    grades = AAGrades(advice)
    row = acted(50, "call", "10")
    row["action_history_v1"]["actions"][-1]["amount_source"] = "pending"
    rows = [(frame, payload(frame)) for frame in range(50)]
    assert feed(advice, grades, rows + [(50, row)])["graded"] == 0
    assert feed(advice, grades, [(51, acted(51, "call", "10"))])["graded"] == 1


def test_a_preflop_action_is_graded_by_the_big_blinds_it_gives_up():
    for kind, amount, best in (("fold", "0", True), ("call", "4", False)):
        advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
        grades = AAGrades(advice)
        report = feed(advice, grades, [(12, preflop_turn(("7c", "2d"))),
                                       (13, preflop_acted(kind, amount, ("7c", "2d")))])
        last = report["last"]
        assert last["street"] == "preflop" and last["chosen"] == kind
        assert {row["action"] for row in last["options"]} == {"fold", "call", "raise"}
        assert "advice" not in last and last["to_call"] == "4"
        if best:
            assert (last["grade"], last["lost_big_blinds"]) == ("best", 0.0)
        else:
            assert last["lost_big_blinds"] > 0 and last["grade"] != "best"
            assert report["preflop_lost_big_blinds"] == last["lost_big_blinds"]


def test_a_new_hand_keeps_the_grades_and_counts_hands_you_were_dealt():
    advice, grades, report = turn_decision("call", "10")
    nxt = payload(60)
    nxt["action_history_v1"] = {**nxt["action_history_v1"], "hand_id": "hand_60",
                                "actions": []}
    blind = {**payload(61, hero=()), "action_history_v1": {
        **nxt["action_history_v1"], "hand_id": "hand_61"}}
    report = feed(advice, grades, [(60, nxt), (61, blind)])
    assert (report["hands"], report["graded"]) == (2, 1)
    grades.reset()
    assert grades.report() == {
        "schema_version": 1, "hands": 0, "graded": 0, "best": 0,
        "preflop_lost_big_blinds": 0.0, "last": None, "rows": [],
        "acts_on_client": False}


def test_the_report_lists_the_newest_twenty_first():
    advice, grades, _ = turn_decision("call", "10")
    grades._rows = [{"grade": "best", "n": n} for n in range(25)]
    rows = grades.report()["rows"]
    assert [row["n"] for row in rows] == list(range(24, 4, -1))
    assert grades.report()["last"]["n"] == 24


def options(*values):
    return [{"action": name, "big_blinds": value} for name, value in values]


def mix(*values):
    return [{"action": name, "frequency": share} for name, share in values]


OPTIONS = options(("raise", 3.1), ("call", 1.9), ("fold", 0.0))
D = Decimal


def test_preflop_bands_and_all_in_by_your_stack():
    assert preflop_grade("raise", OPTIONS, Decimal(4), Decimal(200))["grade"] == "best"
    assert preflop_grade("call", OPTIONS, Decimal(4), Decimal(200)) == {
        "chosen": "call", "lost_big_blinds": 1.2, "grade": "slip"}
    assert preflop_grade("fold", OPTIONS, D(4), D(200))["grade"] == "mistake"
    near = options(("raise", 1.0), ("call", 0.7))
    assert preflop_grade("call", near, Decimal(4), Decimal(200))["grade"] == "fine"
    # All in for less than the price is a call; for more, a raise.
    assert preflop_grade("all_in", OPTIONS, Decimal(10), Decimal(8))["chosen"] == "call"
    assert preflop_grade("all_in", OPTIONS, D(10), D(80))["chosen"] == "raise"
    # Nothing to call: a call read off the screen is the check.
    free = options(("raise", 0.4), ("check", 0.3))
    assert preflop_grade("call", free, Decimal(0), Decimal(80))["chosen"] == "check"
    assert preflop_grade("check", OPTIONS, Decimal(4), Decimal(80)) is None


def test_solver_sizes_count_together_and_the_top_action_is_best():
    rows = [{"action": "check", "frequency": 0.45}, {"action": "bet", "frequency": 0.3},
            {"action": "bet", "frequency": 0.25}]
    assert solver_grade("raise", rows, Decimal(0), Decimal(90)) == {
        "chosen": "raise", "frequency": 0.55, "grade": "best"}
    assert solver_grade("check", rows, Decimal(0), Decimal(90))["grade"] == "fine"
    assert solver_grade("call", rows, Decimal(0), Decimal(90))["chosen"] == "check"
    assert solver_grade("fold", rows, Decimal(0), Decimal(90)) == {
        "chosen": "fold", "frequency": 0.0, "grade": "mistake"}
    split = mix(("call", 0.4), ("fold", 0.35), ("raise", 0.24), ("allin", 0.01))
    assert solver_grade("fold", split, Decimal(10), Decimal(90))["grade"] == "fine"
    assert solver_grade("call", split, Decimal(10), Decimal(90))["grade"] == "best"
    assert solver_grade("all_in", split, Decimal(10), Decimal(90))["frequency"] == 0.25
    assert solver_grade("all_in", split, Decimal(100), Decimal(90))["chosen"] == "call"
    rare = [{"action": "call", "frequency": 0.9}, {"action": "fold", "frequency": 0.1}]
    assert solver_grade("raise", rare + [{"action": "raise", "frequency": 0.01}],
                        Decimal(10), Decimal(90))["grade"] == "mistake"
