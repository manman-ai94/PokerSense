"""Review: advice for one decision is not shown again for a later one."""

from poker_engine.desktop.aa_solver_advice import AASolverAdvice
from tests.desktop.test_aa_solver_advice import Bot, Inline, payload


def test_a_new_price_on_the_same_street_is_not_answered_with_the_old_advice():
    bot = Bot({"CALL": 0.7, "RAISE 30.000000": 0.2, "FOLD": 0.1})
    advice = AASolverAdvice(bot, Inline())
    for frame in range(50):
        first = advice.observe(payload(frame), frame)
    assert first["status"] == "ready" and first["to_call"] == "10"
    # You act (the history has not read it yet), your buttons go away, then
    # come back facing a re-raise: calling now costs 50, not 10.
    for frame in range(50, 56):
        row = payload(frame)
        row["hero_controls_v1"] = {"visible": False}
        advice.observe(row, frame)
    row = payload(56)
    row["hero_controls_v1"] = {"visible": True, "button": "call", "call_amount": "50"}
    again = advice.observe(row, 56)
    # The first decision's "call 10 / raise to 30" must not be shown as the
    # advice for this one.
    assert not (again["status"] == "ready" and again["to_call"] == "10"), again
