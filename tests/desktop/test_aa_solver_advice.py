"""Advice for your preflop decisions, solver advice for your heads-up turn
and river decisions in the background, and the range rule's elsewhere."""

from concurrent.futures import Future, ThreadPoolExecutor
from decimal import Decimal
import sys
import threading
import time

import pytest

from poker_engine.core.enums import Position
from poker_engine.desktop import aa_solver_advice
from poker_engine.desktop.aa_session import frame_summary
from poker_engine.desktop.aa_solver_advice import (
    AASolverAdvice, multiway_row, pot_on_screen)
from poker_engine.scoreboard.multiway_bot import DEFAULTS
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
            turn=41, complete=True, stacks_read=True, priced=0, pot_gone=None):
    seen = [a for i, a in enumerate(ACTIONS) if a[0] < frame and i not in drop]
    if frame < priced:              # the turn bet's chips not read yet
        seen = [a if a[0] != 40 else a[:4] + (None, "pending") for a in seen]
    street = seen[-1][1] if seen else "preflop"
    street = "turn" if frame >= turn else "flop" if frame > 25 else street
    pot = 19 + (4 if frame > 12 else 0) + (10 if frame > 40 else 0) + extra_pot
    board = BOARD[street]
    return {
        "scene_supported": True, "dealer_seat": 5,
        "pot": {"value": None if pot_gone is not None and frame >= pot_gone
                else str(pot)},
        "street_v1": {"street": street},
        "cards": {"hero": list(hero), "board_slots": board + [None] * (5 - len(board))},
        "seat_states_v1": {"seats": {
            str(s): {"state": "active" if s < seats else "empty"} for s in range(8)}},
        "stacks": {str(s): {"value": "200" if stacks_read or s != 4 else None}
                   for s in range(seats)},
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


def still():
    """A clock that never moves: only frames count toward the rough rule."""
    return 0.0


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
    advice = AASolverAdvice(Bot({"CALL": 1.0}), executor, clock=still)
    results = run(advice, range(50))
    # The solve and the range rule next to it, once.
    assert results[-1]["status"] == "computing" and executor.submitted == 2


def test_a_bet_whose_chips_are_read_late_is_worked_out_again():
    # The pot was unread as seat 2 bet: its chips come in a few frames into
    # your turn, and the advice with them.
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    results = run(advice, range(50), priced=46)
    assert (results[44]["status"], results[44]["reason"]) == (
        "abstain", "raise_without_amount")
    assert results[-1]["status"] == "ready"


class RuleOnly(Inline):
    """Runs the range rule at once; the solve never finishes."""

    def submit(self, function, *args):
        self.finish = function.__name__ == "_quick_rule"
        return super().submit(function, *args)


def test_until_the_solve_is_done_the_range_rule_gives_provisional_advice():
    advice = AASolverAdvice(Bot({"RAISE 30.000000": 1.0}), RuleOnly())
    early = run(advice, range(50))[-1]
    shown = (early["status"], early["kind"], early["heads_up"], early["provisional"])
    assert shown == ("ready", "multiway", True, True)
    assert early["advice"][0]["action"] in ("call", "fold", "raise")
    assert "until the heads-up solve is done" in early["basis"]
    assert advice.settled() == ("hand_1", {(9, "turn", "call:10", 0): None})
    done = AASolverAdvice(Bot({"RAISE 30.000000": 1.0}), Inline())
    final = run(done, range(50))[-1]
    assert final["advice"][0]["action"] == "raise" and "provisional" not in final


def test_without_your_cards_there_is_no_advice():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    assert run(advice, range(50), hero=())[-1]["reason"] == "your_cards_not_read"


def flop_turn(advice, **options):
    """Your turn on the flop, checked to you by seat 2."""
    row = {**payload(31, **options), "hero_controls_v1": {"visible": True,
                                                          "button": "check"}}
    return advice.observe(row, 31)


def test_the_heads_up_flop_gets_the_range_rules_action_with_its_cuts(monkeypatch):
    bot = Bot({"CALL": 1.0})
    # A clock that stands still: on a busy machine the reading here takes
    # long enough for the rough rule.
    report = flop_turn(AASolverAdvice(bot, Inline(), clock=still))
    assert (report["status"], report["kind"], report["heads_up"], report["street"]) == (
        "ready", "multiway", True, "flop")
    assert report["cuts"] == {"bet": DEFAULTS["hu_bet"]}
    edge, [row] = report["range_equity"], report["advice"]
    assert edge["opponents"] == 1 and edge["hands"] > 0
    assert row["action"] == ("bet" if edge["value"] >= DEFAULTS["hu_bet"] else "check")
    assert bot.seen == [] and "heads-up cuts" in report["basis"]
    assert report["inferred_actions"] == 0
    # Without your stack the share only; without the range nothing.
    unread = flop_turn(AASolverAdvice(bot, Inline(), clock=still), stacks_read=False)
    assert (unread["status"], unread["reason"]) == ("idle", "heads_up_flop")
    assert 0 < unread["range_equity"]["value"] < 1
    blind = AASolverAdvice(bot, Inline(), clock=still)
    monkeypatch.setattr(blind, "_ranges", lambda observation: None)
    report = flop_turn(blind)
    assert (report["reason"], "range_equity" in report) == ("heads_up_flop", False)


def test_the_opponents_reads_go_to_the_range_reading_after_the_flop(monkeypatch):
    # A seat that bets far more than the AA players after the flop keeps more
    # of the hands the model would not play that way. One that only raises
    # more before the flop does not: read that way, a tight-aggressive player
    # who bets honestly was taken as bluffing.
    seen, real = [], aa_solver_advice.opponent_ranges
    monkeypatch.setattr(aa_solver_advice, "opponent_ranges",
                        lambda observation, model: seen.append(observation)
                        or real(observation, model))
    plain = flop_turn(AASolverAdvice(Bot({"CALL": 1.0}), Inline()))
    assert "reads" not in seen[-1] and plain["reads_hands"] == 0

    def equity(**postflop):
        reads = {"2": {"hands": 30, "vpip": 0.6, "pfr": 0.4, **postflop}}
        advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
        monkeypatch.setattr(advice.reads, "snapshot", lambda: reads)
        report = flop_turn(advice)
        assert seen[-1]["reads"] == reads and report["status"] == "ready"
        assert report["reads_hands"] == 30
        return report["range_equity"]

    honest = equity(postflop=40, aggression=0.21)
    assert equity() == honest                       # no postflop numbers yet
    assert equity(postflop=40, aggression=0.6) != honest


# The same hand three-handed: seat 1 completes its big blind and checks along.
MULTI = [
    (10, "preflop", 3, "fold", "0", "no_chips"), (12, "preflop", 4, "call", "4",
                                                  "pot_rise"),
    (14, "preflop", 5, "fold", "0", "no_chips"), (16, "preflop", 0, "fold", "0",
                                                  "no_chips"),
    (18, "preflop", 1, "call", "2", "pot_rise"), (20, "preflop", 2, "check", "0",
                                                  "no_chips"),
    (28, "flop", 1, "check", "0", "no_chips"), (30, "flop", 2, "check", "0",
                                                "no_chips"),
    (32, "flop", 4, "check", "0", "no_chips"), (36, "turn", 1, "check", "0",
                                                "no_chips"),
    (40, "turn", 2, "raise", "10", "pot_rise"),
]


def three_handed(frame, **options):
    row = payload(frame, **options)
    row["action_history_v1"]["actions"] = [
        dict(zip(("frame", "street", "slot", "kind", "amount", "amount_source"), a))
        for a in MULTI if a[0] < frame]
    row["pot"] = {"value": str(int(row["pot"]["value"]) + (2 if frame > 18 else 0))}
    return row


def test_more_than_one_opponent_gets_the_range_rules_action():
    bot = Bot({"CALL": 1.0})
    advice = AASolverAdvice(bot, Inline())
    report = [advice.observe(three_handed(frame), frame) for frame in range(50)][-1]
    assert (report["status"], report["kind"]) == ("ready", "multiway")
    edge = report["range_equity"]
    assert edge["opponents"] == 2 and edge["hands"] is None
    assert set(edge["hands_each"]) == {"1", "2"} and 0 < edge["value"] < 1
    # Seat 2 bets 10 into a pot of 37 on screen (2 more than the rules post).
    assert report["pot"] == "37" and report["pot_offset"] == "2"
    assert report["cuts"] == {"call": round(10 / 47, 3), "raise": DEFAULTS["raise"]}
    share, [row] = edge["value"], report["advice"]
    expected = ("raise" if share >= DEFAULTS["raise"] else
                "call" if share >= 10 / 47 else "fold")
    assert row["action"] == expected and row["frequency"] == 1.0
    assert bot.seen == [] and report["advice_emitted"] is True
    assert "no multiway solver" in report["basis"]
    # The ranges are worked out in the background: the report does not wait.
    waiting = AASolverAdvice(bot, Inline(finish=False))
    report = [waiting.observe(three_handed(frame), frame) for frame in range(50)][-1]
    assert report["status"] == "computing"


def test_the_opponents_ranges_are_read_while_they_act(monkeypatch):
    from poker_engine.scoreboard import ranges

    def counted(advice, frames, fresh=True):
        if fresh:                          # nothing read before
            monkeypatch.setattr(ranges, "_KEPT", {})
        calls = []
        kept = ranges.kept
        monkeypatch.setattr(ranges, "kept",
                            lambda *a, **k: calls.append(1) or kept(*a, **k))
        reports = [advice.observe(three_handed(frame), frame) for frame in frames]
        return reports, len(calls)

    warm = Inline()
    ahead = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), warm_executor=warm)
    _, before_turn = counted(ahead, range(42))
    # From the flop on, once per new action: on the flop and the five
    # actions after it (a reading kept from the one before covers the actions
    # it read); every opponent action is read by then.
    assert warm.submitted == 6 and before_turn == 11
    reports, at_turn = counted(ahead, range(42, 50), fresh=False)
    plain = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    alone, every = counted(plain, range(50))
    # At your turn nothing is left to read, and the advice is the same.
    assert (at_turn, every) == (0, 6)
    assert reports[-1]["range_equity"] == alone[-1]["range_equity"]
    assert reports[-1]["advice"] == alone[-1]["advice"]
    # Given an executor for the solve and none for this, a replay reads
    # nothing ahead; the live window reads on a worker of its own.
    assert plain._warming is None
    live = AASolverAdvice()
    try:
        live._hand_id = "hand_1"
        live._warm({"street": "flop"}, {"actions": []})
        assert live._warming[1].result(5) is False      # no hand to read yet
    finally:
        live._warm_executor.shutdown()


def test_checked_to_in_a_multiway_pot_bets_or_checks_by_the_share():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    rows = [three_handed(frame, shown=31, turn=99) for frame in range(32)]
    for row in rows:                   # nothing to call: your button is a check
        row["hero_controls_v1"].update(button="check", call_amount="0")
    report = [advice.observe(row, frame) for frame, row in enumerate(rows)][-1]
    assert report["cuts"] == {"bet": DEFAULTS["bet"]}
    [row] = report["advice"]
    if report["range_equity"]["value"] >= DEFAULTS["bet"]:
        assert row["action"] == "bet" and int(row["to"]) == int(row["chips"]) > 0
    else:
        assert row == {"action": "check", "frequency": 1.0}


def test_multiway_without_ranges_or_your_stack_gives_the_share_or_nothing(monkeypatch):
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still)
    monkeypatch.setattr(advice, "_ranges", lambda observation: None)
    report = [advice.observe(three_handed(frame), frame) for frame in range(50)][-1]
    assert (report["status"], report["reason"]) == ("idle", "more_than_one_opponent")
    assert "range_equity" not in report
    unread = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still)
    rows = [three_handed(frame) for frame in range(50)]
    for row in rows:
        row["stacks"]["4"] = {"value": None}
    report = [unread.observe(row, frame) for frame, row in enumerate(rows)][-1]
    assert (report["status"], report["reason"]) == ("idle", "more_than_one_opponent")
    assert 0 < report["range_equity"]["value"] < 1


def test_a_range_rule_action_as_an_advice_row():
    facing = {"to_call": "10", "bets": {"4": "0", "2": "10"}, "observing_seat": 4}
    assert multiway_row("fold", facing) == {"action": "fold", "frequency": 1.0}
    assert multiway_row("check_call", facing) == {"action": "call", "frequency": 1.0}
    assert multiway_row("raise_to:45", facing) == {
        "action": "raise", "frequency": 1.0, "chips": "45", "to": "45"}
    free = {**facing, "to_call": "0", "bets": {"4": "0"}}
    assert multiway_row("check_call", free)["action"] == "check"
    assert multiway_row("raise_to:24", free)["action"] == "bet"


def test_the_flop_gets_equity_against_the_opponents_range():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    report = advice.observe({**payload(31), "hero_controls_v1": {"visible": True}}, 31)
    edge = report["range_equity"]
    assert edge["opponents"] == 1 and edge["hands"] == edge["hands_each"]["2"] > 0
    assert 0 < edge["value"] < 1


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


class Preflop:
    """A preflop policy that keeps what it was shown."""

    def __init__(self):
        self.seen = []

    def choose(self, observation):
        self.seen.append(observation)
        return {"values": {"fold": 0.0, "call": 1.0}}


def test_the_mushroom_pool_on_screen_goes_to_the_preflop_policy(monkeypatch):
    def turn(pool):
        policy = Preflop()
        frame = {**preflop_turn(("Ks", "Qs")), "mushroom_pool_v1": {"value": pool}}
        result = AASolverAdvice(Bot(), Inline(), preflop=policy).observe(frame, 12)
        return policy.seen[-1], result

    seen, result = turn("48")
    assert seen["mushroom_pool"] == "48"
    assert result["mushroom_pool"] is None      # not counted: not the small blind
    assert "mushroom_pool" not in turn(None)[0]
    monkeypatch.setattr(aa_solver_advice, "position", lambda observation: Position.SB)
    assert turn("48")[1]["mushroom_pool"] == "48"
    assert frame_summary({"mushroom_pool_v1": {"value": "48"}})["mushroom_pool"] == "48"
    monkeypatch.setattr(aa_solver_advice, "MIN_PLAYERS", 7)    # fewer players: no pool
    seen, result = turn("48")
    assert "mushroom_pool" not in seen and result["mushroom_pool"] is None


def test_the_opponents_reads_from_finished_hands_go_to_the_preflop_policy():
    policy = Preflop()
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), preflop=policy)
    first = advice.observe(preflop_turn(("Ks", "Qs")), 12)
    assert "reads" not in policy.seen[-1] and first["reads_hands"] == 0
    run(advice, range(13, 50))                       # hand_1: you limp, seat 2 checks
    turn = preflop_turn(("Ks", "Qs"))
    turn["action_history_v1"] = {**turn["action_history_v1"], "hand_id": "hand_2"}
    result = advice.observe(turn, 70)
    reads = policy.seen[-1]["reads"]
    assert reads["3"] == {"hands": 1, "vpip": 0.0, "pfr": 0.0, "postflop": 0,
                          "aggression": 0.0} and "4" not in reads
    assert result["reads_hands"] == 1
    assert result["seat_reads"]["3"] == {"hands": 1, "vpip": 0.0, "pfr": 0.0,
                                         "postflop": 0, "aggression": 0.0,
                                         "tag": None}
    assert frame_summary({"solver_advice_v1": result})["solver_advice"][
        "reads_hands"] == 1
    advice.reset()                                   # a new observation
    assert advice.reads.snapshot() == {}


def test_when_the_solve_cannot_answer_the_range_rule_does(monkeypatch):
    advice = AASolverAdvice(Bot(error="own_hand_not_in_range"), Inline())
    result = run(advice, range(50))[-1]
    shown = (result["status"], result["kind"], result["solver_gave_up"])
    assert shown == ("ready", "multiway", "own_hand_not_in_range")
    assert "provisional" not in result and "heads-up cuts" in result["basis"]
    # Grading goes by the action shown.
    graded = advice.settled()[1][(9, "turn", "call:10", 0)]
    assert (graded["kind"], graded["solver_gave_up"]) == ("multiway",
                                                          "own_hand_not_in_range")
    # Without the range rule's action the reason shows until the rough rule.
    blind = AASolverAdvice(Bot(error="own_hand_not_in_range"), Inline(), clock=still)
    monkeypatch.setattr(blind, "_ranges", lambda observation: None)
    result = run(blind, range(50))[-1]
    assert (result["status"], result["reason"]) == ("abstain", "own_hand_not_in_range")


def test_a_hand_that_does_not_replay_abstains():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still)
    result = run(advice, range(50), drop=(0,))[-1]      # seat 3's fold was missed
    assert (result["status"], result["reason"]) == ("abstain", "not_this_seats_turn")


def test_the_frame_log_keeps_the_advice_status():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    result = run(advice, range(50))[-1]
    summary = frame_summary({"solver_advice_v1": result})["solver_advice"]
    assert summary["status"] == "ready" and summary["advice"] == [
        {"action": "call", "frequency": 1.0}]
    assert "basis" not in summary


def test_your_buttons_before_the_last_action_is_read():
    # Seat 2's bet is read at 41; your price (call 10) fills it in at once.
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    results = run(advice, range(50), shown=37, turn=37)
    assert [r["status"] for r in results[37:41]] == ["ready"] * 4
    assert results[37]["inferred_actions"] == 1
    assert (results[-1]["status"], results[-1]["inferred_actions"]) == ("ready", 0)
    # Without your price there is nothing to fill it in from: wait for it.
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    frames = [payload(frame, shown=37, turn=37) for frame in range(50)]
    for frame in frames:
        frame["hero_controls_v1"]["call_amount"] = None
    results = [advice.observe(frame, index) for index, frame in enumerate(frames)]
    assert [r["reason"] for r in results[37:41]] == ["waiting_for_last_action"] * 4
    assert results[-1]["status"] == "ready"


def test_a_hand_joined_midway_gets_no_advice():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still)
    result = run(advice, range(50), complete=False)[-1]
    assert (result["status"], result["reason"]) == ("abstain", "hand_incomplete")


def heads_up(row, wagers=None):
    """``row`` with only you and seat 2 in, and the chips in front on this street."""
    row["seat_states_v1"] = {"seats": {str(s): {"state": "active" if s in (2, 4) else
                                                "folded" if s < 6 else "empty"}
                                       for s in range(8)}}
    row["street_wagers"] = wagers or {}
    return row


def test_a_moment_into_your_turn_without_advice_the_rough_rule_answers():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still)
    results = [advice.observe(heads_up(payload(frame, complete=False)), frame)
               for frame in range(60)]
    # Your turn shows at 42; for ROUGH_FRAMES frames the reason, then an action.
    assert {r["reason"] for r in results[42:52]} == {"hand_incomplete"}
    rough = results[52]
    assert (rough["status"], rough["kind"], rough["rough_for"]) == (
        "ready", "rough", "hand_incomplete")
    # Seat 2's bet of 10 into 35: the call needs 10 of 45.
    assert (rough["to_call"], rough["pot"], rough["required"]) == ("10", "35", 0.222)
    edge = rough["range_equity"]
    assert edge["opponents"] == 1 and 0 < edge["value"] < 1
    assert rough["advice"] == [{"action": "call" if edge["value"] >= 0.222 else "fold",
                                "frequency": 1.0}]
    assert "rough rule" in rough["basis"] and rough["advice_emitted"] is True
    logged = frame_summary({"solver_advice_v1": rough})["solver_advice"]
    assert logged["kind"] == "rough"


def test_the_rough_rule_counts_your_turn_from_the_start_of_the_street():
    # 10/09 live: your buttons showed while the board still read as the last
    # street, and the rough rule answered the moment the flop was read, then
    # the range rule changed it.
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still)
    results = [advice.observe(heads_up(payload(frame, complete=False, shown=30)), frame)
               for frame in range(60)]
    assert results[40]["kind"] == "rough" and results[40]["street"] == "flop"
    assert [r.get("kind") for r in results[41:51]] == [None] * 10
    assert (results[51]["kind"], results[51]["street"]) == ("rough", "turn")


def test_the_rough_rule_waits_while_the_proper_advice_is_coming():
    # Work that is still running past ROUGH_FRAMES gets the rough rule next to it.
    executor = Inline(finish=False)
    advice = AASolverAdvice(Bot({"CALL": 1.0}), executor, clock=still)
    results = run(advice, range(60))
    assert executor.submitted == 3 and results[-1]["status"] == "computing"
    # Advice that comes in time is never replaced.
    done = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still)
    assert {r.get("kind", "solver") for r in run(done, range(60))[42:]} == {"solver"}


def test_the_rough_rule_does_not_wait_behind_the_solve():
    # On 10/08 and 10/07 the heads-up solve and its range rule held both
    # workers, and the rough rule queued behind them: your turn stayed blank.
    busy, own = Inline(finish=False), Inline()
    advice = AASolverAdvice(Bot({"CALL": 1.0}), busy, rough_executor=own, clock=still)
    results = run(advice, range(60))
    assert busy.submitted == 2 and own.submitted == 1     # the solve, the range rule
    # While the proper advice is being worked out the rough rule holds back
    # longer (HOLD_FRAMES): on 10/09 it showed first and the range rule
    # changed it a second later, after you had acted on it.
    assert [r["status"] for r in results[42:57]] == ["computing"] * 15
    rough = results[57]
    assert (rough["status"], rough["kind"], rough["rough_for"]) == (
        "ready", "rough", "computing")
    # On its own the advice starts a worker for the rough rule apart from the
    # solve's.
    alone = AASolverAdvice(Bot({"CALL": 1.0}))
    assert alone._submit_rough(lambda: "rough").result(timeout=5) == "rough"
    assert alone._executor is None and alone._rough_executor is not None
    alone._rough_executor.shutdown()


def test_a_stall_counts_toward_the_rough_rule():
    # Frames are dropped while recognition stalls: the clock still runs.
    now = [0.0]
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                            rough_executor=Inline(), clock=lambda: now[0])
    results = []
    for frame in range(42, 46):
        now[0] = {44: 1.6, 45: 1.7}.get(frame, 0.0)        # 1.6 s between 43 and 44
        results.append(advice.observe(payload(frame), frame))
    assert [r["status"] for r in results] == ["computing"] * 2 + ["ready"] * 2
    assert results[2]["kind"] == "rough"


def test_the_rough_rule_is_asked_again_when_the_screen_was_not_ready(monkeypatch):
    call = {"kind": "rough", "advice": [{"action": "call", "frequency": 1.0}]}
    answers = iter([None, call])
    monkeypatch.setattr(aa_solver_advice, "rough_advice",
                        lambda fields, cards, street, pot=None: next(answers))
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                            rough_executor=Inline(), clock=still)
    results = run(advice, range(65))
    # No price on the first ask (57): asked again RETRY frames on.
    assert [r["status"] for r in results[57:60]] == ["computing"] * 3
    assert (results[60]["status"], results[60]["kind"]) == ("ready", "rough")


def test_the_rough_rule_shows_in_the_frame_that_asks_for_it(monkeypatch):
    # 10/07 at real pace: after a stall the frame that made it due was the
    # turn's last, and the rough rule, done a moment later, never showed.
    call = {"kind": "rough", "advice": [{"action": "call", "frequency": 1.0}]}
    gate = threading.Event()

    def answer(fields, cards, street, pot=None):
        gate.wait(5)
        return call

    def quick(fields, cards, street, pot=None):
        time.sleep(0.03)                                 # well inside ROUGH_WAIT
        return call

    monkeypatch.setattr(aa_solver_advice, "rough_advice", quick)
    with ThreadPoolExecutor(max_workers=1) as own:
        advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                                rough_executor=own, clock=still)
        results = run(advice, range(58))
        assert results[56]["status"] == "computing"
        assert (results[57]["status"], results[57]["kind"]) == ("ready", "rough")
    # Longer than that the frame goes on without it, and a later frame shows it.
    monkeypatch.setattr(aa_solver_advice, "rough_advice", answer)
    with ThreadPoolExecutor(max_workers=1) as own:
        advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                                rough_executor=own, clock=still)
        started = time.monotonic()
        results = run(advice, range(58))
        assert time.monotonic() - started < 2
        assert results[57]["status"] == "computing"
        gate.set()
        own.submit(lambda: None).result(timeout=5)       # the rough job is done
        later = advice.observe(payload(58), 58)
        assert (later["status"], later["kind"]) == ("ready", "rough")


def rough(street="turn", hero=("Qs", "Qh"), button="call", price="10", pot="35",
          wagers=None, board=None, stack="200"):
    fields = {"board": board if board is not None else
              BOARD.get(street, ["Ah", "Kd", "7c", "2s", "9h"]) + [None] * 5,
              "participants": {"2": "active", "3": "folded", "4": "active"},
              "pot": pot, "street_wagers": wagers or {},
              "hero_controls": {"visible": True, "button": button,
                                "call_amount": price}, "stacks": {"4": stack}}
    return aa_solver_advice.rough_advice(fields, list(hero), street)


def test_the_rough_rule_works_out_the_pot_when_it_is_not_read():
    # 10/09 live: a player went all in before the flop and it came to you
    # with the pot unread for 10 s; your turn got no advice at all.
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                            rough_executor=Inline(), clock=still)
    rough = run(advice, range(60), pot_gone=42)[57]
    assert (rough["status"], rough["kind"], rough["pot"], rough["pot_read"]) == (
        "ready", "rough", "35", False)                   # the pot last read
    read = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                          rough_executor=Inline(), clock=still)
    assert run(read, range(60))[57]["pot_read"] is True


def test_the_pot_is_worked_out_from_the_last_one_read_and_the_chips_in_front():
    def row(street, pot, wagers):
        return {"fields": {"street": street, "pot": pot, "street_wagers": wagers}}

    # Before the flop the pot on screen is the chips in front plus 16.
    blinds = row("preflop", "42", {"0": "2", "1": "4", "4": "20"})
    shove = row("preflop", None, {"0": "2", "1": "4", "2": None, "4": "20",
                                  "7": "206"})["fields"]
    assert pot_on_screen(shove, [blinds, row("preflop", None, {})]) == Decimal(248)
    assert pot_on_screen(shove, []) == Decimal(232)       # no pot read yet
    assert pot_on_screen({**shove, "pot": "260"}, [blinds]) == Decimal(260)
    # On a new street the last pot read carries over whole.
    bet = row("turn", None, {"2": "30"})["fields"]
    flop = row("flop", "100", {"2": "20", "4": "20"})
    assert pot_on_screen(bet, [flop]) == Decimal(130)
    assert pot_on_screen(bet, []) is None


def test_the_rough_rule_takes_the_price_from_the_history_when_it_is_not_read():
    # 10/09 live: a turn bet of 65 was in the history from the pot rise, the
    # price on your button and the chips in front both unread for 9 seconds.
    history = {"actions": [[1, "flop", 2, "check", "0", "no_chips"],
                           [2, "turn", 2, "raise", "65", "pot_rise"]]}
    fields = {"board": BOARD["turn"] + [None], "pot": "163",
              "participants": {"2": "active", "4": "active"},
              "street_wagers": {"2": None, "4": None}, "actions_v1": history,
              "hero_controls": {"visible": True, "button": "call",
                                "call_amount": None},
              "stacks": {"4": "300"}}
    rough = aa_solver_advice.rough_advice(fields, ["Qs", "Qh"], "turn")
    assert (rough["to_call"], rough["required"]) == ("65", 0.285)
    # Seat 2 bet: it holds the top 20% of hands, not 40%.
    assert rough["range_equity"]["value"] < aa_solver_advice.rough_advice(
        {**fields, "hero_controls": {**fields["hero_controls"], "call_amount": "65"},
         "actions_v1": None}, ["Qs", "Qh"], "turn")["range_equity"]["value"]
    # An action still waiting for its chips gives nothing to go on.
    pending = [3, "turn", 3, "call", None, "pending"]
    waiting = {"actions": history["actions"] + [pending]}
    assert aa_solver_advice.rough_advice({**fields, "actions_v1": waiting},
                                         ["Qs", "Qh"], "turn") is None
    assert aa_solver_advice.put_in({**fields, "street": "preflop"}, "preflop") == {}


def test_the_rough_rule_checks_when_free_and_calls_or_folds_by_the_price():
    free = rough(button="check", price=None)
    assert (free["advice"][0]["action"], free["to_call"], free["required"]) == (
        "check", "0", 0.0)
    # 72 offsuit against a raise to 40 before the flop: 40 of 87 is too much.
    junk = rough("preflop", hero=("7c", "2d"), price="40", pot="47",
                 wagers={"2": "40", "4": "0"})
    assert junk["advice"][0]["action"] == "fold" and junk["required"] == 0.46
    aces = rough("preflop", hero=("Ac", "Ad"), price="40", pot="47",
                 wagers={"2": "40", "4": "0"})
    assert aces["advice"][0]["action"] == "call"
    # Before the flop 80% of the share counts (the betting still to come),
    # all of it when the call puts you all in, for what you have.
    assert aces["range_equity"]["realize"] == 0.8
    short = rough("preflop", hero=("Ac", "Ad"), price="40", pot="47",
                  wagers={"2": "40", "4": "0"}, stack="30")
    assert (short["to_call"], short["range_equity"]["realize"]) == ("30", 1.0)
    assert short["range_equity"]["value"] > aces["range_equity"]["value"]
    assert rough()["range_equity"]["realize"] == 1.0


def test_the_one_who_bet_or_raised_to_you_holds_a_stronger_range():
    plain = rough()["range_equity"]["value"]
    bet = rough(wagers={"2": "10"})["range_equity"]["value"]
    assert bet < plain
    # Before the flop the straddle (4) is not a raise; more is.
    limp = rough("preflop", price="2", pot="17", wagers={"2": "4", "4": "2"})
    raise_ = rough("preflop", price="2", pot="17", wagers={"2": "5", "4": "3"})
    assert raise_["range_equity"]["value"] < limp["range_equity"]["value"]


def test_the_rough_rule_needs_the_board_and_a_price():
    assert rough(board=["Ah", "Kd", "7c", None, None]) is None    # turn card unread
    assert rough(price=None) is None                               # nothing to price
    # The price from the chips in front when the button's is not read.
    assert rough(price=None, wagers={"2": "10", "4": "0"})["to_call"] == "10"


def test_settled_lists_this_hands_decisions_and_a_new_source_forgets_them():
    executor = Inline(finish=False)
    advice = AASolverAdvice(Bot({"CALL": 1.0}), executor)
    run(advice, range(50))
    computing = {(9, "turn", "call:10", 0): None}
    assert advice.settled() == ("hand_1", computing)
    done = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    run(done, range(50))
    hand, outcomes = done.settled()
    assert hand == "hand_1" and outcomes[(9, "turn", "call:10", 0)]["status"] == "ready"
    done.reset()
    assert done.settled() == (None, {})


# A bomb pot of six (dealer 5): each put in 14 and the flop came at once;
# seat 0 bets 20 into 84 and seats 1 to 3 fold to you.
BOMB = [(30, "flop", 0, "raise", "20", "pot_rise")] + [
    (31 + seat, "flop", seat, "fold", "0", "no_chips") for seat in (1, 2, 3)]


def bomb_turn(frame):
    row = payload(frame)
    row["pot"] = {"value": "84" if frame <= 30 else "104"}
    row["street_v1"] = {"street": "flop"}
    row["cards"]["board_slots"] = BOARD["flop"] + [None, None]
    row["stacks"] = {str(s): {"value": "186"} for s in range(6)}
    row["hero_controls_v1"] = {"visible": frame >= 35, "button": "call",
                               "call_amount": "20"}
    row["action_history_v1"]["actions"] = [
        dict(zip(("frame", "street", "slot", "kind", "amount", "amount_source"), a))
        for a in BOMB if a[0] < frame]
    return row


def test_a_bomb_pot_gets_advice_after_the_flop_like_any_other_hand():
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    report = [advice.observe(bomb_turn(frame), frame) for frame in range(36)][-1]
    assert (report["status"], report["kind"], report["street"]) == (
        "ready", "multiway", "flop")
    assert report["bomb_pot"] == "14" and report["pot"] == "104"
    assert report["range_equity"]["opponents"] == 2
    assert report["cuts"]["call"] == round(20 / 124, 3)
    # A normal hand's report says it is not one.
    normal = [advice.observe(three_handed(frame), frame) for frame in range(50)][-1]
    assert normal["bomb_pot"] is None


def test_the_background_thread_lets_recognition_get_the_lock_back_quickly():
    before = sys.getswitchinterval()
    advice = AASolverAdvice()
    try:
        sys.setswitchinterval(0.005)          # Python's default
        assert advice._submit(lambda: "done").result(5) == "done"
        assert sys.getswitchinterval() == pytest.approx(aa_solver_advice.SWITCH_SECONDS)
        # The rough rule's worker too, when it starts first.
        rough = AASolverAdvice()
        sys.setswitchinterval(0.005)
        assert rough._submit_rough(lambda: "rough").result(5) == "rough"
        assert sys.getswitchinterval() == pytest.approx(aa_solver_advice.SWITCH_SECONDS)
        rough._rough_executor.shutdown()
    finally:
        advice._executor.shutdown()
        sys.setswitchinterval(before)
