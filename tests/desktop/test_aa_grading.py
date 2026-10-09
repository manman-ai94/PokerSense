"""Grading your decisions against the advice once you have acted."""

from concurrent.futures import Future
from decimal import Decimal

from poker_engine.desktop.aa_grading import (AAGrades, HeroChips, multiway_grade,
                                             preflop_grade, solver_grade)
from poker_engine.desktop.aa_solver_advice import AASolverAdvice
from tests.desktop.test_aa_solver_advice import (Bot, Inline, payload, preflop_turn,
                                                 three_handed)

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


def turn_decision(kind, amount, bot=None, executor=None, frames=50, **options):
    advice = AASolverAdvice(bot or Bot(MIX), executor or Inline())
    grades = AAGrades(advice, clock=lambda: 1000.0)
    rows = [(frame, payload(frame, **options)) for frame in range(frames)]
    return advice, grades, feed(advice, grades, rows + [
        (frames, acted(frames, kind, amount, **options))])


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
    # Seat 3's fold was missed: the hand does not replay.
    assert turn_decision("call", "10", drop=(0,))[2]["graded"] == 0
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
        "schema_version": 1, "hands": 0, "decisions": 0, "advised": 0, "graded": 0,
        "best": 0, "grades": {"best": 0, "fine": 0, "slip": 0, "mistake": 0},
        "preflop_lost_big_blinds": 0.0, "net_chips": None, "net_big_blinds": None,
        "rebuys": 0, "last": None, "rows": [], "acts_on_client": False}


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


def test_a_multiway_action_is_graded_against_the_range_rule():
    advice = AASolverAdvice(Bot(MIX), Inline())
    grades = AAGrades(advice, clock=lambda: 1000.0)
    rows = [(frame, three_handed(frame)) for frame in range(50)]
    after = three_handed(50)
    after["hero_controls_v1"] = {"visible": False}
    after["action_history_v1"]["actions"].append(
        {"frame": 46, "street": "turn", "slot": 4, "kind": "call", "amount": "10",
         "amount_source": "pot_rise"})
    last = feed(advice, grades, rows + [(50, after)])["last"]
    share = last["share"]
    assert last["kind"] == "multiway" and last["cuts"]["call"] == round(10 / 47, 3)
    assert last["advice"][0]["action"] in ("fold", "call", "raise")
    if last["advice"][0]["action"] == "call":
        assert last["grade"] == "best"
    else:
        assert last["grade"] != "best" and last["gap"] > 0 and 0 < share < 1


def test_multiway_grades_by_how_far_the_share_is_from_your_action():
    def outcome(action, share, **cuts):
        return {"kind": "multiway", "advice": [{"action": action, "frequency": 1.0}],
                "cuts": cuts or {"call": 0.25, "raise": 0.6},
                "range_equity": {"value": share}}
    raise_ = outcome("raise", 0.63)
    assert multiway_grade("raise", raise_, D(10), D(90))["grade"] == "best"
    assert multiway_grade("call", raise_, D(10), D(90)) == {
        "chosen": "call", "share": 0.63, "gap": 0.03, "grade": "fine"}
    assert multiway_grade("fold", raise_, D(10), D(90))["grade"] == "mistake"
    fold = outcome("fold", 0.15)
    assert multiway_grade("call", fold, D(10), D(90))["grade"] == "slip"
    assert multiway_grade("all_in", fold, D(10), D(90))["grade"] == "mistake"
    assert multiway_grade("check", fold, D(10), D(90)) is None
    bet = outcome("bet", 0.42, bet=0.4)
    assert multiway_grade("raise", bet, D(0), D(90))["grade"] == "best"
    assert multiway_grade("call", bet, D(0), D(90))["chosen"] == "check"
    assert multiway_grade("check", bet, D(0), D(90))["grade"] == "fine"
    assert multiway_grade("fold", bet, D(0), D(90)) is None
    unread = {**raise_, "range_equity": None}
    assert multiway_grade("call", unread, D(10), D(90)) is None


def test_the_session_counts_your_actions_the_advice_and_each_grade():
    # Your preflop call and flop check had no advice here; the turn call did.
    report = turn_decision("call", "10")[2]
    assert (report["decisions"], report["advised"], report["graded"]) == (3, 1, 1)
    assert report["grades"] == {"best": 1, "fine": 0, "slip": 0, "mistake": 0}
    report = turn_decision("call", "10", drop=(0,))[2]
    assert (report["decisions"], report["advised"], report["graded"]) == (3, 0, 0)
    # The range rule's action where the solve cannot answer: advised and graded.
    report = turn_decision("call", "10", bot=Bot(error="own_hand_not_in_range"))[2]
    assert (report["decisions"], report["advised"], report["graded"]) == (3, 1, 1)
    assert report["last"]["kind"] == "multiway"
    # The rough rule's action a second into your turn: advised, too rough to grade.
    report = turn_decision("call", "10", frames=60, drop=(0,))[2]
    assert (report["decisions"], report["advised"], report["graded"]) == (3, 1, 0)
    # Advice that cannot be matched to what you did: advised, not graded.
    report = turn_decision("check", "0")[2]
    assert (report["decisions"], report["advised"], report["graded"]) == (3, 1, 0)


def seen(stack, state="active", front=None, hand="h1", times=2):
    """A reading of your seat, ``times`` frames in a row."""
    return [({"stacks": {"4": stack}, "street_wagers": {"4": front},
              "participants": {"4": state}}, hand)] * times


def chips_after(*readings, dealt=True):
    chips = HeroChips()
    for fields, hand in [item for group in readings for item in group]:
        chips.observe(fields, hand, dealt)
    return chips


def test_your_chips_count_from_when_you_are_dealt_with_rebuys_left_out():
    chips = chips_after(seen("198", front="2"))       # a blind is still yours
    assert (chips.start, chips.net()) == (Decimal(200), 0)
    # All in and lost: the result moves once you are out of the hand.
    lost = [seen("0", "all_in", front="198"), seen("0", "all_in")]
    chips = chips_after(seen("198", front="2"), *lost)
    assert chips.net() == 0                           # the pot is still played
    chips = chips_after(seen("198", front="2"), *lost, seen("0", "waiting"))
    assert chips.net() == -200
    # A rebuy is not a result; the hand after it is.
    after = [seen("200", "waiting"), seen("198", front="2", hand="h2"),
             seen("260", hand="h2")]
    chips = chips_after(seen("198", front="2"), *lost, seen("0", "waiting"), *after)
    assert (chips.net(), chips.rebuys, chips.added) == (-200, 1, Decimal(200))
    chips = chips_after(seen("198", front="2"), *lost, seen("0", "waiting"), *after,
                        seen("259", front="1", hand="h3"))
    assert chips.net() == -140
    # One frame is not a reading.
    chips = chips_after(seen("198", front="2"), *lost, seen("0", "waiting"), *after,
                        seen("500", hand="h3", times=1))
    assert chips.net() == -140


def test_a_pot_won_all_in_is_a_result_and_a_new_buy_in_is_not():
    won = chips_after(seen("150"), seen("0", "all_in", front="150"),
                      seen("0", "all_in"), seen("300"),
                      seen("298", front="2", hand="h2"))
    assert (won.net(), won.rebuys) == (150, 0)
    # The seat was read empty: sitting down again with other chips is a buy-in.
    back = chips_after(seen("150"), seen("120", "folded", hand="h2"),
                       seen(None, "empty", hand="h3"),
                       seen("300", "waiting", hand="h3"),
                       seen("300", hand="h4"))
    assert (back.net(), back.rebuys, back.added) == (-30, 1, Decimal(180))
    # After you fold only the stack is yours: what is in front is lost.
    folded = chips_after(seen("150"), seen("140", "folded", front="10"))
    assert folded.net() == -10
    # Not dealt in yet (watching): no result.
    assert chips_after(seen("150"), dealt=False).net() is None


def test_the_report_gives_your_result_in_big_blinds():
    advice, grades, _ = turn_decision("call", "10")
    for frame, stack in ((60, "200"), (61, "200"), (62, "175"), (63, "175"),
                         (64, "175")):
        row = payload(frame)
        row["action_history_v1"]["hand_id"] = "hand_2" if frame < 64 else "hand_3"
        row["stacks"]["4"]["value"] = stack
        report = grades(row, frame)
    assert (report["net_chips"], report["net_big_blinds"], report["rebuys"]) == (
        "-25", -12.5, 0)
