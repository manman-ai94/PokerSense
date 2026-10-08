"""Advice for your preflop decisions, and solver advice for your heads-up turn
and river decisions in the background."""

from concurrent.futures import Future

import pytest

from poker_engine.desktop.aa_session import frame_summary
from poker_engine.desktop.aa_solver_advice import AASolverAdvice
from poker_engine.scoreboard.solver_bot import Fallback

# Six players, dealer 5 (blinds 0 and 1, straddle 2). You (seat 4) limp, seat 2
# checks its option; the flop is checked; on the turn seat 2 bets 10 into 23.
ACTIONS = [
    (10, "preflop", 3, "fold", "0", "no_chips"), (12, "preflop", 4, "call", "4",
                                                  "pot_rise"),
    (14, "preflop", 5, "fold", "0", "no_chips"), (16, "preflop", 0, "fold", "0",
                                                  "no_chips"),
    (18, "preflop", 1, "fold", "0", "no_chips"), (20, "preflop", 2, "check", "0",
                                                  "no_chips"),
    (30, "flop", 2, "check", "0", "no_chips"), (32, "flop", 4, "check", "0",
                                                "no_chips"),
    (40, "turn", 2, "raise", "10", "pot_rise"),
]
BOARD = {"preflop": [], "flop": ["Ah", "Kd", "7c"], "turn": ["Ah", "Kd", "7c", "2s"]}


def payload(frame, hero=("Qs", "Qh"), extra_pot=2, seats=6, drop=(), shown=42,
            turn=41, complete=True):
    seen = [a for i, a in enumerate(ACTIONS) if a[0] < frame and i not in drop]
    street = seen[-1][1] if seen else "preflop"
    street = "turn" if frame >= turn else "flop" if frame > 25 else street
    pot = 19 + (4 if frame > 12 else 0) + (10 if frame > 40 else 0) + extra_pot
    board = BOARD[street]
    return {
        "scene_supported": True, "pot": {"value": str(pot)}, "dealer_seat": 5,
        "street_v1": {"street": street},
        "cards": {"hero": list(hero), "board_slots": board + [None] * (5 - len(board))},
        "seat_states_v1": {"seats": {
            str(s): {"state": "active" if s < seats else "empty"} for s in range(8)}},
        "stacks": {str(s): {"value": "200"} for s in range(seats)},
        "hero_controls_v1": {"visible": frame >= shown, "button": "call",
                             "call_amount": "10"},
        "action_history_v1": {
            "hand_id": "hand_1", "complete": complete, "start": "pot_went_down",
            "dealer": 5, "actions": [dict(zip(("frame", "street", "slot", "kind",
                                               "amount", "amount_source"), a))
                                     for a in seen]}}


class Bot:
    # The opponent's range at the decision: on Ah Kd 7c 2s, kings up beat
    # your queens, a seven does not.
    RANGE = {"KhKc": 1.0, "AcKs": 1.0, "7d7h": 0.5, "Qc7s": 2.0, "QsJd": 1.0}

    def __init__(self, strategy=None, error=None, villain=None):
        self.strategy, self.error, self.seen = strategy, error, []
        self.villain = self.RANGE if villain is None else villain

    def solved_spot(self, observation, salt):
        self.seen.append(observation)
        if self.error:
            raise Fallback(self.error)
        return self.strategy, self.villain


class Inline:
    """Runs a job at once, or never (``finish=False``)."""

    def __init__(self, finish=True):
        self.finish, self.submitted = finish, 0

    def submit(self, function, *args):
        self.submitted += 1
        future = Future()
        if self.finish:
            future.set_result(function(*args))
        return future


def run(advice, frames, **options):
    return [advice.observe(payload(frame, **options), frame) for frame in frames]


def test_your_turn_on_the_turn_gets_the_solvers_frequencies():
    bot = Bot({"CALL": 0.7, "RAISE 30.000000": 0.2, "FOLD": 0.1})
    advice = AASolverAdvice(bot, Inline())
    results = run(advice, range(50))
    assert results[30]["status"] == "idle" and results[30]["reason"] == "not_your_turn"
    ready = results[-1]
    assert (ready["status"], ready["street"], ready["advice_emitted"]) == (
        "ready", "turn", True)
    assert ready["advice"] == [
        {"action": "call", "frequency": 0.7},
        {"action": "raise", "frequency": 0.2, "chips": "30", "to": "30"},
        {"action": "fold", "frequency": 0.1}]
    # The table shows 2 chips more than the AA rules post: the solver sees them.
    assert ready["pot_offset"] == "2" and bot.seen[0]["pot_offset"] == "2"
    assert len(bot.seen) == 1 and ready["acts_on_client"] is False
    # Your equity against his range there, exact over the river cards; QsJd
    # uses your queen of spades and is left out.
    assert ready["range_equity"]["hands"] == 4
    assert 0.1 < ready["range_equity"]["value"] < 0.5
    assert frame_summary({"solver_advice_v1": ready})["solver_advice"][
        "range_equity"] == ready["range_equity"]


def test_an_empty_or_unreadable_range_gives_advice_without_range_equity():
    for villain in ({"QsJd": 1.0}, {"XxYy": 1.0}):
        advice = AASolverAdvice(Bot({"CALL": 1.0}, villain=villain), Inline())
        ready = run(advice, range(50))[-1]
        assert ready["status"] == "ready" and ready["range_equity"] is None


def test_the_solve_runs_in_the_background_once_per_decision():
    executor = Inline(finish=False)
    advice = AASolverAdvice(Bot({"CALL": 1.0}), executor)
    results = run(advice, range(50))
    assert results[-1]["status"] == "computing" and executor.submitted == 1


def test_decisions_the_solver_does_not_cover_stay_idle():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    assert run(advice, range(50), hero=())[-1]["reason"] == "your_cards_not_read"
    flop = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    first = flop.observe({**payload(31), "hero_controls_v1": {"visible": True}}, 31)
    assert (first["reason"], first["street"]) == ("street_not_covered", "flop")


def preflop_turn(hero):
    """Your first preflop decision: seat 3 folded, it is seat 4's turn."""
    return {**payload(12, hero=hero, extra_pot=0),
            "hero_controls_v1": {"visible": True, "button": "call",
                                 "call_amount": "4"}}


def test_your_preflop_turn_gets_the_most_valuable_option_and_every_value():
    bot = Bot({"CALL": 1.0})
    advice = AASolverAdvice(bot, Inline())
    aces = advice.observe(preflop_turn(("As", "Ah")), 12)
    assert (aces["status"], aces["street"]) == ("ready", "preflop")
    assert aces["advice"][0]["action"] == "raise" and aces["advice"][0]["to"]
    options = {row["action"]: row for row in aces["options"]}
    assert set(options) == {"fold", "call", "raise"}
    assert options["fold"]["chips"] == 0
    assert options["raise"]["chips"] > options["call"]["chips"] > 0
    assert options["raise"]["big_blinds"] == pytest.approx(
        options["raise"]["chips"] / 2, abs=0.05)
    assert options["raise"]["to"] == aces["advice"][0]["to"]
    assert aces["options"][0]["action"] == "raise"       # most valuable first
    assert "AA players" in aces["basis"] and bot.seen == []
    trash = AASolverAdvice(bot, Inline()).observe(preflop_turn(("7c", "2d")), 12)
    assert trash["advice"] == [{"action": "fold", "frequency": 1.0}]
    summary = frame_summary({"solver_advice_v1": aces})["solver_advice"]
    assert summary["options"] == aces["options"]


def test_extra_chips_on_screen_count_in_the_preflop_pot():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    result = advice.observe({**preflop_turn(("Ks", "Qs")), "pot": {"value": "40"}}, 12)
    assert result["status"] == "ready" and result["pot"] == "40"
    assert result["pot_offset"] == "21"           # the six-seat opening pot is 19


def test_a_solver_fallback_abstains_with_its_reason():
    advice = AASolverAdvice(Bot(error="own_hand_not_in_range"), Inline())
    result = run(advice, range(50))[-1]
    assert (result["status"], result["reason"]) == ("abstain", "own_hand_not_in_range")


def test_a_hand_that_does_not_replay_abstains():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    result = run(advice, range(50), drop=(0,))[-1]      # seat 3's fold was missed
    assert (result["status"], result["reason"]) == ("abstain", "not_this_seats_turn")


def test_the_frame_log_keeps_the_advice_status():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    result = run(advice, range(50))[-1]
    summary = frame_summary({"solver_advice_v1": result})["solver_advice"]
    assert summary["status"] == "ready" and summary["advice"] == [
        {"action": "call", "frequency": 1.0}]
    assert "basis" not in summary


def test_your_buttons_before_the_last_action_is_read_wait_for_it():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    results = run(advice, range(50), shown=37, turn=37)   # seat 2's bet read at 41
    assert [r["reason"] for r in results[37:41]] == ["waiting_for_last_action"] * 4
    assert results[-1]["status"] == "ready"


def test_a_hand_joined_midway_gets_no_advice():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    result = run(advice, range(50), complete=False)[-1]
    assert (result["status"], result["reason"]) == ("abstain", "hand_incomplete")


def test_settled_lists_this_hands_decisions_and_a_new_source_forgets_them():
    executor = Inline(finish=False)
    advice = AASolverAdvice(Bot({"CALL": 1.0}), executor)
    run(advice, range(50))
    assert advice.settled() == ("hand_1", {(9, "turn"): None})    # still computing
    done = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    run(done, range(50))
    hand, outcomes = done.settled()
    assert hand == "hand_1" and outcomes[(9, "turn")]["status"] == "ready"
    done.reset()
    assert done.settled() == (None, {})
