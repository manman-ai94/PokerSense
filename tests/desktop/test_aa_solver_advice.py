"""Advice for your preflop decisions, solver advice for your heads-up turn
and river decisions in the background, and the range rule's elsewhere: the
engine before the vision contract (``legacy``), kept for replays; the default
now runs the old strategy under the contract (``test_aa_classic_live``)."""

from concurrent.futures import Future, ThreadPoolExecutor, wait as real_wait
from decimal import Decimal
from functools import partial
import sys
import threading
import time

import pytest

from poker_engine.core.enums import Position
from poker_engine.desktop import aa_solver_advice
from poker_engine.desktop.aa_session import frame_summary
from poker_engine.desktop.aa_solver_advice import (
    LEGACY, multiway_row, pot_on_screen, solver_threads)
from poker_engine.scoreboard.multiway_bot import DEFAULTS
from poker_engine.scoreboard.solver_bot import Fallback
from tests.timing import Stopwatch, budget, over, timing, within_budget

AASolverAdvice = partial(aa_solver_advice.AASolverAdvice, strategy=LEGACY)

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

TURN_KEY = (9, "turn", "call:10", 0, ("Qh", "Qs"), ("Ah", "Kd", "7c", "2s"))


def payload(frame, hero=("Qs", "Qh"), extra_pot=2, seats=6, drop=(), shown=42,
            turn=41, complete=True, stacks_read=True, priced=0, pot_gone=None,
            late=0):
    seen = [a for i, a in enumerate(ACTIONS) if a[0] < frame and i not in drop
            and not (a[0] == 40 and frame < late)]
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


def test_the_solve_leaves_half_the_computer_to_recognition(monkeypatch):
    # 4 on the Mac (10) as before, 2 on a laptop with 2 cores and 4 threads.
    assert [solver_threads(cpus) for cpus in (1, 2, 3, 4, 6, 8, 10, 16)] == [
        1, 1, 1, 2, 3, 4, 4, 4]
    monkeypatch.setattr(aa_solver_advice.os, "cpu_count", lambda: None)
    assert solver_threads() == 1
    monkeypatch.setattr(aa_solver_advice.os, "cpu_count", lambda: 4)
    assert solver_threads() == 2


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
    assert advice.settled() == ("hand_1", {TURN_KEY: None})
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
    # of the hands the model would not bet (its floor over the bluff weight;
    # here seat 2's turn bet, three-handed). One that only raises more before
    # the flop does not: read that way, a tight-aggressive player who bets
    # honestly was taken as bluffing.
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
        report = [advice.observe(three_handed(frame), frame) for frame in range(50)][-1]
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
    # Calling makes it 47, and the table rakes 2 of it (5%, to the chip).
    assert report["pot"] == "37" and report["pot_offset"] == "2"
    assert report["cuts"] == {"call": round(10 / 45, 3), "raise": DEFAULTS["raise"]}
    share, [row] = edge["value"], report["advice"]
    expected = ("raise" if share >= DEFAULTS["raise"] else
                "call" if share >= 10 / 45 else "fold")
    assert row["action"] == expected and row["frequency"] == 1.0
    assert bot.seen == [] and report["advice_emitted"] is True
    assert "no multiway solver" in report["basis"]
    # The ranges are worked out in the background: the report does not wait.
    waiting = AASolverAdvice(bot, Inline(finish=False))
    report = [waiting.observe(three_handed(frame), frame) for frame in range(50)][-1]
    assert report["status"] == "computing"


def test_the_range_rule_weighs_each_side_pot_against_its_players(monkeypatch):
    # Seat 2 is all in for 20; seat 5 bets 40 more than your 60.
    seen = {}

    def equity(hole, board, ranges, **kwargs):
        seen.update(kwargs)
        return 0.5, {2: 10, 5: 20}

    monkeypatch.setattr(aa_solver_advice, "opponent_ranges",
                        lambda observation, model: {2: {}, 5: {}})
    monkeypatch.setattr(aa_solver_advice, "ranges_equity", equity)
    observation = {
        "observing_seat": 4, "occupied_seats": [2, 4, 5, 7], "folded": [7],
        "contributions": {"2": "20", "4": "60", "5": "100", "7": "10"},
        "stacks": {"2": "0", "4": "300", "5": "300", "7": "90"},
        "pot": "190", "to_call": "40", "own_hole": ["Ah", "As"],
        "board": ["Kh", "8c", "2d", "5s"]}
    report = AASolverAdvice(Bot({"CALL": 1.0}), Inline())._ranges(observation)
    assert seen["pots"] == [(70.0, (2, 5)), (160.0, (5,))]
    assert report["side_pots"] == [{"chips": 70.0, "seats": ["2", "5"]},
                                   {"chips": 160.0, "seats": ["5"]}]
    # No side pot, nothing more in the report.
    level = {**observation, "contributions": {"2": "60", "4": "60", "5": "100",
                                              "7": "10"},
             "stacks": {"2": "300", "4": "300", "5": "300", "7": "90"}, "pot": "230"}
    report = AASolverAdvice(Bot({"CALL": 1.0}), Inline())._ranges(level)
    assert seen["pots"] == [(270.0, (2, 5))] and "side_pots" not in report


def test_the_opponents_ranges_are_read_while_they_act(monkeypatch):
    from poker_engine.scoreboard import ranges

    def counted(advice, frames, fresh=True):
        if fresh:                          # nothing read before
            monkeypatch.setattr(ranges, "_KEPT", {})
        calls = []
        for name in ("kept", "soft_kept"):          # before / after the flop
            read = getattr(ranges, name)
            monkeypatch.setattr(ranges, name, lambda *a, read=read, **k:
                                calls.append(1) or read(*a, **k))
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
    graded = advice.settled()[1][TURN_KEY]
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
    # Seat 2's bet of 10 into 35: the call needs 10 of 45, less 2 of rake.
    assert (rough["to_call"], rough["pot"], rough["required"]) == ("10", "35", 0.233)
    edge = rough["range_equity"]
    assert edge["opponents"] == 1 and 0 < edge["value"] < 1
    assert rough["advice"] == [{"action": "call" if edge["value"] >= 0.233 else "fold",
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
                        lambda fields, cards, street, pot=None, stakes=None, bomb=False:
                        next(answers))
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                            rough_executor=Inline(), clock=still)
    results = run(advice, range(65))
    # No price on the first ask (57): asked again RETRY frames on.
    assert [r["status"] for r in results[57:60]] == ["computing"] * 3
    assert (results[60]["status"], results[60]["kind"]) == ("ready", "rough")


ROUGH_CALL = {"kind": "rough", "advice": [{"action": "call", "frequency": 1.0}]}


def frame_wait(in_time, asked):
    """``wait`` for the advice module: a wait with a timeout (the frame that
    asks for the rough rule) is recorded in ``asked`` and then plays out as if
    the job finished inside it (``in_time``) or did not, without real time."""
    def wait(futures, timeout=None, **options):
        if timeout is None:
            return real_wait(futures, **options)
        asked.append(timeout)
        return real_wait(futures, timeout=5 if in_time else 0, **options)

    return wait


def test_the_rough_rule_shows_in_the_frame_that_asks_for_it(monkeypatch):
    # 10/07 at real pace: after a stall the frame that made it due was the
    # turn's last, and the rough rule, done a moment later, never showed.
    gate = threading.Event()

    def answer(fields, cards, street, pot=None, stakes=None, bomb=False):
        gate.wait(5)
        return ROUGH_CALL

    asked = []
    monkeypatch.setattr(aa_solver_advice, "rough_advice",
                        lambda *args: ROUGH_CALL)
    monkeypatch.setattr(aa_solver_advice, "wait", frame_wait(True, asked))
    with ThreadPoolExecutor(max_workers=1) as own:
        advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                                rough_executor=own, clock=still)
        results = run(advice, range(58))
        assert results[56]["status"] == "computing"
        assert (results[57]["status"], results[57]["kind"]) == ("ready", "rough")
    assert asked == [aa_solver_advice.ROUGH_WAIT]     # the frame waits that long
    # Longer than that the frame goes on without it, and a later frame shows it.
    asked.clear()
    monkeypatch.setattr(aa_solver_advice, "rough_advice", answer)
    monkeypatch.setattr(aa_solver_advice, "wait", frame_wait(False, asked))
    with ThreadPoolExecutor(max_workers=1) as own:
        advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                                rough_executor=own, clock=still)
        results = run(advice, range(58))
        assert results[57]["status"] == "computing"
        assert asked == [aa_solver_advice.ROUGH_WAIT]
        gate.set()
        own.submit(lambda: None).result(timeout=5)       # the rough job is done
        later = advice.observe(payload(58), 58)
        assert (later["status"], later["kind"]) == ("ready", "rough")
    assert asked == [aa_solver_advice.ROUGH_WAIT]     # shown, not asked again


@timing
def test_the_rough_rule_shows_in_that_frame_at_real_pace(monkeypatch):
    # The live window relies on this: a rough rule that is done well inside
    # ROUGH_WAIT (live it takes under 0.1 s) shows in the frame that asked, on
    # a real worker thread; one that is slow holds the frames up no longer.
    def quick(fields, cards, street, pot=None, stakes=None, bomb=False):
        time.sleep(0.03)
        return ROUGH_CALL

    def attempt():
        monkeypatch.setattr(aa_solver_advice, "rough_advice", quick)
        with ThreadPoolExecutor(max_workers=1) as own:
            advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                                    rough_executor=own, clock=still)
            results = run(advice, range(58))
        assert results[56]["status"] == "computing"
        if results[57]["status"] == "ready":
            assert results[57]["kind"] == "rough"
            missed = []
        else:
            assert results[57]["status"] == "computing"
            missed = ["a 0.03 s rough rule did not show in the frame that asked"]
        gate = threading.Event()

        def answer(fields, cards, street, pot=None, stakes=None, bomb=False):
            gate.wait(5)
            return ROUGH_CALL

        monkeypatch.setattr(aa_solver_advice, "rough_advice", answer)
        with ThreadPoolExecutor(max_workers=1) as own:
            advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(finish=False),
                                    rough_executor=own, clock=still)
            try:
                watch = Stopwatch()
                results = run(advice, range(58))
                took = watch()
            finally:
                gate.set()
        assert results[57]["status"] == "computing"
        return missed + over("58 frames with a slow rough rule", took, budget(2))

    within_budget(attempt)


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
    assert (rough["to_call"], rough["required"]) == ("65", round(65 / (228 - 10), 3))
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
    # 72 offsuit against a raise to 40 before the flop: 40 of 87 (83 after
    # the rake) is too much.
    junk = rough("preflop", hero=("7c", "2d"), price="40", pot="47",
                 wagers={"2": "40", "4": "0"})
    assert junk["advice"][0]["action"] == "fold" and junk["required"] == 0.482
    aces = rough("preflop", hero=("Ac", "Ad"), price="40", pot="47",
                 wagers={"2": "40", "4": "0"})
    assert aces["advice"][0]["action"] == "call"
    # Before the flop 80% of the share counts (the betting still to come),
    # all of it when the call puts you all in, for what you have.
    assert aces["range_equity"]["realize"] == 0.8
    short = rough("preflop", hero=("Ac", "Ad"), price="40", pot="47",
                  wagers={"2": "40", "4": "0"}, stack="30")
    assert (short["to_call"], short["range_equity"]["realize"]) == ("30", 1.0)
    # All in for 30 of the 40: the other 10 go back to the raiser. You can
    # win 47 + 30 - 10 = 67, 64 after the rake (before: 30 of 77).
    assert short["required"] == round(30 / 64, 3)
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
    computing = {TURN_KEY: None}
    assert advice.settled() == ("hand_1", computing)
    done = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    run(done, range(50))
    hand, outcomes = done.settled()
    assert hand == "hand_1" and outcomes[TURN_KEY]["status"] == "ready"
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
    assert report["cuts"]["call"] == round(20 / (124 - 6), 3)     # 6 raked
    # A normal hand's report says it is not one.
    normal = [advice.observe(three_handed(frame), frame) for frame in range(50)][-1]
    assert normal["bomb_pot"] is None


def test_an_error_working_out_the_advice_leaves_it_to_the_rough_rule(monkeypatch):
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline(), clock=still)

    def broken(*args):
        raise ValueError("stack must cover ante and align to minimum chip")

    monkeypatch.setattr(advice, "_start", broken)
    reports = [advice.observe(payload(frame), frame) for frame in range(42, 60)]
    assert (reports[0]["status"], reports[0]["reason"]) == ("abstain", "advice_failed")
    assert reports[-1]["kind"] == "rough"


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


def _rough_fields(button, call=None, wagers=None):
    return {"board": ["7s", "9s", "5c", "5h", None], "pot": "135",
            "participants": {"2": "active", "4": "active"},
            "street_wagers": wagers or {}, "stacks": {"4": "400", "2": "300"},
            "hero_controls": {"visible": True, "button": button, "call_amount": call}}


def test_after_the_flop_the_rough_rule_bets_and_raises_by_the_range_rule_lines():
    # 10/09 live, hand_33520: trips on the turn, checked to you; the rough rule
    # only knew check, call and fold and said check (twice, turn and river).
    trips = aa_solver_advice.rough_advice(_rough_fields("check"), ["5s", "6h"], "turn")
    assert trips["range_equity"]["value"] >= 0.55
    # Two thirds of the pot is played as the range rule plays it on the
    # scoreboard's table: half the pot, the closest size it offers.
    assert trips["advice"] == [{"action": "bet", "frequency": 1.0,
                                "chips": "67", "to": "67"}]
    # Facing a bet of 40 with the same hand: a pot-sized raise after calling.
    raised = aa_solver_advice.rough_advice(
        _rough_fields("call", "40", {"2": "40"}), ["5s", "6h"], "turn")
    assert raised["advice"][0]["action"] == "raise"
    assert raised["advice"][0]["to"] == str(40 + 135 + 40)
    # A weak hand still checks; before the flop nothing changes.
    weak = aa_solver_advice.rough_advice(_rough_fields("check"), ["2d", "3c"], "turn")
    assert weak["advice"] == [{"action": "check", "frequency": 1.0}]
    row = {"action": "check", "frequency": 1.0}
    assert aa_solver_advice.rough_aggression(
        row, 0.25, 2, Decimal(100), Decimal(0), Decimal(0), Decimal(0),
        Decimal(500)) is row
    # The bet never asks for more than your stack.
    capped = aa_solver_advice.rough_aggression(
        row, 0.9, 1, Decimal(300), Decimal(0), Decimal(0), Decimal(0), Decimal(50))
    assert capped["to"] == "50"
    # Into three or more opponents the bet is the pot (multiway_bot's size3).
    assert aa_solver_advice.rough_aggression(
        row, 0.5, 3, Decimal(120), Decimal(0), Decimal(0), Decimal(0),
        Decimal(500))["to"] == "120"


def test_a_rough_bet_that_would_leave_little_behind_is_all_in():
    # A bet of two thirds of 120 is 80; with 90 behind that left 10. The
    # range rule's table offers half the pot (60), the pot (all of the 90)
    # or all in: all in is the closest.
    row = {"action": "check", "frequency": 1.0}
    bet = aa_solver_advice.rough_aggression(
        row, 0.9, 1, Decimal(120), Decimal(0), Decimal(0), Decimal(0), Decimal(90))
    assert (bet["action"], bet["to"]) == ("bet", "90")
    # With deep stacks the same bet is half the pot.
    deep = aa_solver_advice.rough_aggression(
        row, 0.9, 1, Decimal(120), Decimal(0), Decimal(0), Decimal(0), Decimal(900))
    assert deep["to"] == "60"


def _history(*actions):
    return {"hand_id": "hand_1", "actions": [
        [frame, street, slot, kind, None, "read"]
        for frame, (street, slot, kind) in enumerate(actions)]}


def test_the_rough_rule_remembers_a_bet_on_an_earlier_street():
    # An opponent who bet the flop and checks the turn was read as any of
    # his top 40% of hands, as if he had never bet.
    fields = {**_rough_fields("check"), "board": ["Jd", "8c", "4s", "Ah", None]}
    quiet = aa_solver_advice.rough_advice(
        {**fields, "actions_v1": _history(("flop", 2, "check"), ("flop", 4, "check"),
                                          ("turn", 2, "check"))}, ["Qs", "Jc"], "turn")
    bet = aa_solver_advice.rough_advice(
        {**fields, "actions_v1": _history(("flop", 2, "raise"), ("flop", 4, "call"),
                                          ("turn", 2, "check"))}, ["Qs", "Jc"], "turn")
    assert bet["range_equity"]["value"] < quiet["range_equity"]["value"]
    # Before the flop no bet narrows; an all in with its chips unread counts.
    assert aa_solver_advice.aggression(
        {"actions_v1": _history(("preflop", 2, "raise"), ("flop", 3, "all_in"),
                                ("turn", 5, "raise"))}, "turn", None) == [
        ("3", "flop", False), ("5", "turn", False)]
    assert aa_solver_advice.aggression({}, "flop", None) == []


def test_in_a_bomb_pot_the_rough_rule_takes_any_two_cards():
    # In a bomb pot everyone holds a random hand; read as the top 40% of
    # hands, a made flush came out far weaker than it is.
    fields = {**_rough_fields("check"), "board": ["2h", "9h", "Kc", "5h", None]}
    normal = aa_solver_advice.rough_advice(fields, ["Jh", "2c"], "turn")
    bomb = aa_solver_advice.rough_advice(fields, ["Jh", "2c"], "turn", bomb=True)
    hands = [advice["range_equity"]["hands_each"]["2"] for advice in (bomb, normal)]
    assert hands[0] > hands[1]
    assert bomb["range_equity"]["value"] > normal["range_equity"]["value"]


class FirstOnly(Inline):
    """Runs the first ``count`` jobs at once; the later ones never finish."""

    def __init__(self, count):
        super().__init__()
        self.count = count

    def submit(self, function, *args):
        self.finish = self.submitted < self.count
        return super().submit(function, *args)


def test_an_inferred_action_read_for_real_keeps_the_advice_while_it_is_redone():
    # Seat 2's turn bet is on the table as your buttons show (and filled in),
    # but read into the history only at frame 50: the same price, one more
    # action read. Until that decision is worked out the earlier advice
    # stays, instead of the rough rule's (10/10: fold, rough call, fold).
    advice = AASolverAdvice(Bot({"FOLD": 1.0}), FirstOnly(2), clock=still)
    results = run(advice, range(70), late=50)
    before, after = results[45], results[65]
    assert before["status"] == "ready" and before["inferred_actions"] == 1
    assert (after["status"], after["advice"], after["carried_from"]) == (
        "ready", before["advice"], before["decision"])
    assert after["decision"] == before["decision"] + 1
    assert "rough_for" not in after


def test_a_new_price_is_not_carried_over():
    advice = AASolverAdvice(Bot({"FOLD": 1.0}), FirstOnly(2), clock=still)
    results = [advice.observe(payload(frame), frame) for frame in range(50)]
    raised = payload(50)
    raised["hero_controls_v1"]["call_amount"] = "30"
    late = [advice.observe(raised, frame) for frame in range(50, 70)]
    assert results[-1]["status"] == "ready"
    assert all("carried_from" not in report for report in late)


def test_the_big_pot_guard_holds_back_a_pair_in_the_solvers_advice():
    # 10/09 and 10/10 live: river bets with a pair into pots of 30 big blinds
    # and more, the share against the read range 0.79-1.0 (2026-10-13 sheet).
    # Your queens on Ah Kd 7c 2s face a bet of 10; the pot on screen is 60
    # chips more than the rules post: 47 big blinds of 2.
    ahead = {"JdJc": 1.0}                      # the read range: you are ahead
    raise_ = {"RAISE 60.000000": 1.0}
    report = run(AASolverAdvice(Bot(raise_, villain=ahead), Inline()), range(50),
                 extra_pot=62)[-1]
    assert report["advice"] == [{"action": "call", "frequency": 1.0}]
    guard = report["guard"]
    assert guard["was"]["action"] == "raise" and guard["street"] == "turn"
    assert guard["pot_big_blinds"] >= DEFAULTS["guard"]
    # A raise with a share under a half is a bluff: the solver's own.
    behind = run(AASolverAdvice(Bot(raise_, villain={"KhKc": 1.0}), Inline()),
                 range(50), extra_pot=62)[-1]
    assert behind["advice"][0]["action"] == "raise" and "guard" not in behind
    # A small pot is not guarded.
    small = run(AASolverAdvice(Bot(raise_, villain=ahead), Inline()), range(50))[-1]
    assert small["advice"][0]["action"] == "raise" and "guard" not in small


def test_a_style_rule_in_the_window_changes_the_solvers_advice(monkeypatch):
    calls = Bot({"CALL": 0.7, "FOLD": 0.3})
    # Off by default: the solver's answer as it is.
    report = run(AASolverAdvice(calls, Inline()), range(50))[-1]
    assert report["advice"][0]["action"] == "call" and "style" not in report
    seen = []

    def fold(strategy, observation, rules):
        seen.append((observation, rules))
        return {"FOLD": 1.0}, "nocatch"

    monkeypatch.setattr(aa_solver_advice, "STYLE_RULES", frozenset({"nocatch"}))
    monkeypatch.setattr(aa_solver_advice, "style_adjust", fold)
    calls = Bot({"CALL": 0.7, "FOLD": 0.3})
    report = run(AASolverAdvice(calls, Inline()), range(50))[-1]
    assert report["advice"] == [{"action": "fold", "frequency": 1.0}]
    assert report["style"] == {"rule": "nocatch",
                               "was": {"action": "call", "frequency": 0.7}}
    # The rule sees the pot on screen and the rules named.
    observation, rules = seen[-1]
    assert rules == {"nocatch"} and observation["street"] == "turn"


def test_the_big_pot_guard_holds_back_a_pair_in_the_range_rule(monkeypatch):
    advice = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    monkeypatch.setattr(advice, "_ranges", lambda observation: {
        "value": 0.95, "opponents": 2, "hands": None, "hands_each": {}})
    report = [advice.observe(three_handed(frame, extra_pot=80), frame)
              for frame in range(50)][-1]
    assert report["kind"] == "multiway"
    assert report["advice"] == [{"action": "call", "frequency": 1.0}]
    assert report["guard"]["was"]["action"] == "raise"
    # A pot under 30 big blinds keeps the raise.
    small = AASolverAdvice(Bot({"CALL": 1.0}), Inline())
    monkeypatch.setattr(small, "_ranges", lambda observation: {
        "value": 0.95, "opponents": 2, "hands": None, "hands_each": {}})
    report = [small.observe(three_handed(frame), frame) for frame in range(50)][-1]
    assert report["advice"][0]["action"] == "raise" and "guard" not in report


def test_the_big_pot_guard_holds_back_a_pair_in_the_rough_rule():
    board = ["7s", "9s", "5c", "5h"]
    bet = {"action": "bet", "frequency": 1.0, "chips": "89", "to": "89"}
    check = {"action": "check", "frequency": 1.0}
    guard = aa_solver_advice.rough_guard
    # Nines and the board's fives: one pair of your own, 135 chips is 67 big
    # blinds of 2 (the rule set's): at most half the pot on the turn.
    row, report = guard(bet, check, ["9h", "2c"], board, "turn", Decimal(135),
                        Decimal(0))
    assert (row["chips"], row["to"]) == ("68", "68") and report["was"] == bet
    row, report = guard(bet, check, ["9h", "2c"], board + ["Kd"], "river",
                        Decimal(135), Decimal(0))
    assert row == check and report["street"] == "river"
    raise_ = {"action": "raise", "frequency": 1.0, "chips": "215", "to": "215"}
    call = {"action": "call", "frequency": 1.0}
    assert guard(raise_, call, ["9h", "2c"], board, "turn", Decimal(175),
                 Decimal(0))[0] == call
    # Trips, a small pot, a big blind of 8 or a check: nothing changes.
    for hole, pot, stakes in ((["5s", "6h"], 135, None), (["9h", "2c"], 50, None),
                              (["9h", "2c"], 135, {"big_blind": "8"})):
        assert guard(bet, check, hole, board, "turn", Decimal(pot), Decimal(0),
                     stakes) == (bet, None)
    assert guard(check, check, ["9h", "2c"], board, "turn", Decimal(135),
                 Decimal(0)) == (check, None)


def test_your_cards_read_anew_are_worked_out_again():
    # Audit 10/14 (P-01): 72o got a fold, the same turn read again as AA kept
    # the fold. Cards corrected within one decision start a new solve.
    bot = Bot({"CALL": 1.0})
    advice = AASolverAdvice(bot, Inline())
    first = run(advice, range(50))[-1]
    again = [advice.observe(payload(frame, hero=("Ac", "Ad")), frame)
             for frame in range(50, 55)][-1]
    assert first["status"] == again["status"] == "ready"
    assert len(bot.seen) == 2 and sorted(bot.seen[-1]["own_hole"]) == ["Ac", "Ad"]
    # The earlier cards' advice is not carried over to the new ones.
    assert "carried_from" not in again


def test_a_stack_read_late_is_worked_out_then():
    # Audit 10/14 (P-01): your stack unread at your turn left the decision at
    # "stack unknown" after it was read.
    bot = Bot({"CALL": 1.0})
    advice = AASolverAdvice(bot, Inline(), clock=still)
    unread = run(advice, range(45), stacks_read=False)[-1]
    assert unread["reason"] == "stack_unknown" or unread["kind"] == "rough"
    read = run(advice, range(45, 60))[-1]
    assert (read["status"], read.get("kind")) == ("ready", None) and bot.seen


def _rough_seats(participants, hero, button="call", price="10"):
    fields = {"board": BOARD["turn"] + [None], "participants": participants,
              "pot": "35", "street_wagers": {},
              "hero_controls": {"visible": True, "button": button,
                                "call_amount": price}, "stacks": {"4": "200"}}
    return aa_solver_advice.rough_advice(fields, list(hero), "turn")


def test_the_rough_rule_counts_seats_not_read_as_maybe_in():
    # Audit 10/14 (P-02): one opponent known and five seats unknown was
    # answered as heads-up. The answer stands only when it is the same with
    # the unknown seats in the hand; else the answer with them in does (it
    # was none, and your turn went without advice).
    known = {"2": "active", "3": "folded", "4": "active"}
    unread = {**known, **{seat: "unknown" for seat in "01567"}}
    queens = _rough_seats(known, ("Qs", "Qh"))
    assert queens["advice"][0]["action"] == "call" and "unknown_seats" not in queens
    six = _rough_seats(unread, ("Qs", "Qh"))
    assert (six["advice"][0]["action"], six["unknown_seats"]) == ("fold", 5)
    assert six["unknown_in"] and six["range_equity"]["opponents"] == 6
    weak = _rough_seats(unread, ("Js", "Ts"))              # a fold either way
    assert (weak["advice"][0]["action"], weak["unknown_seats"]) == ("fold", 5)
    assert weak["range_equity"]["opponents"] == 1


def test_the_rough_rule_counts_a_draws_implied_odds_as_the_range_rule_does(monkeypatch):
    # A draw just short of the price folded however deep the stacks were.
    # Off while the range rule's ``implied`` is 0.
    fields = {"board": ["Jd", "9c", "2s", None, None], "pot": "60",
              "participants": {"1": "active", "2": "active", "4": "active",
                               "6": "active"},
              "street_wagers": {"2": "20"}, "stacks": {"4": "220", "2": "300",
                                                       "1": "80", "6": "200"},
              "hero_controls": {"visible": True, "button": "call",
                                "call_amount": "20"}}
    off = aa_solver_advice.rough_advice(fields, ["Qs", "Th"], "flop")
    monkeypatch.setitem(aa_solver_advice.MULTIWAY_LINES, "implied", 0.25)
    on = aa_solver_advice.rough_advice(fields, ["Qs", "Th"], "flop")
    # 20 to win 60 + 20 less rake, and a quarter of the 200 left behind.
    assert on["required"] < off["required"]
    assert on["required"] == pytest.approx(20 / (20 / off["required"] + 200 / 4),
                                           abs=0.001)
    dry = aa_solver_advice.rough_advice(fields, ["Ah", "Kd"], "flop")
    assert dry["required"] == off["required"]


def test_a_shove_read_only_from_the_history_is_in_the_pot_worked_out():
    # Code check 10/16: on the turn a shove of 500 was read only from the
    # stack drop, the pot (100 before it) and the chips in front unread, and
    # you all in for 50: 100 + 50 - 450 made what a call can win negative and
    # the rough rule called with any two cards.
    fields = {"street": "turn", "pot": None, "board": ["Ks", "Qd", "9h", "4c", None],
              "participants": {"2": "all_in", "4": "active"}, "street_wagers": {},
              "stacks": {"4": "50", "2": "0"},
              "hero_controls": {"visible": True, "button": "all_in",
                                "call_amount": None},
              "actions_v1": {"hand_id": "h1", "actions": [
                  [10, "flop", 2, "check", None, "read"],
                  [11, "flop", 4, "check", None, "read"],
                  [20, "turn", 2, "all_in", "500", "stack_drop"]]}}
    rows = [{"processed": 15, "fields": {"street": "turn", "pot": "100",
                                         "street_wagers": {}}}]
    pot = aa_solver_advice.pot_on_screen(fields, rows)
    rough = aa_solver_advice.rough_advice(fields, ["7c", "2d"], "turn", pot)
    assert rough["to_call"] == "50"
    # 50 to win 100 + 50 + 50 of the shove, less rake.
    assert 0.25 < rough["required"] < 0.3
    assert rough["advice"][0]["action"] == "fold"
    # What a call can win is never below the call (nor 0 to divide by).
    assert aa_solver_advice.rough_winnable(
        {"2": Decimal(500), "4": Decimal(0)}, Decimal(0), Decimal(100),
        Decimal(50)) == Decimal(50)


def _bets(*actions):
    return {"hand_id": "hand_1", "actions": [
        [frame, street, slot, kind, chips, "read"]
        for frame, (street, slot, kind, chips) in enumerate(actions)]}


def test_the_rough_rule_reads_a_pot_sized_bet_on_the_board():
    # A pair under the board's top card facing a bet of the pot: read as any
    # of the bettor's top 40% of hands it came out at 0.64 and called (real
    # hands of 10/07-10/16 like it were behind with 0-0.25).
    fields = {"board": ["Qd", "9c", "3c", None, None], "pot": "160",
              "participants": {"2": "active", "5": "folded"},
              "street_wagers": {"2": "80"}, "stacks": {"4": "1000", "2": "1000"},
              "hero_controls": {"visible": True, "button": "call", "call_amount": "80"},
              "actions_v1": _bets(("flop", 2, "raise", "80"),
                                  ("flop", 5, "fold", "0"))}
    advice = aa_solver_advice.rough_advice(fields, ["Jh", "Jd"], "flop")
    assert advice["range_equity"]["value"] < 0.3
    assert advice["advice"][0]["action"] == "fold"


def test_the_rough_rule_reads_a_caller_who_leads_the_turn_and_bets_the_river():
    # Top pair with a weak kicker: the opponent called the flop, led the turn
    # and bet the river. It came out at 0.65 and called both.
    fields = {"board": ["8c", "Kh", "3d", "Ts", "Js"], "pot": "430",
              "participants": {"2": "active"},
              "street_wagers": {"2": "150"}, "stacks": {"4": "1000", "2": "1000"},
              "hero_controls": {"visible": True, "button": "call",
                                "call_amount": "150"},
              "actions_v1": _bets(
                  ("flop", 2, "check", "0"), ("flop", 4, "raise", "40"),
                  ("flop", 2, "call", "40"), ("turn", 2, "raise", "70"),
                  ("turn", 4, "call", "70"), ("river", 2, "raise", "150"))}
    advice = aa_solver_advice.rough_advice(fields, ["Kd", "5c"], "river")
    assert advice["advice"][0]["action"] == "fold"


def test_the_rough_rule_reads_a_check_raise_stronger_than_a_bet():
    fields = {"board": ["Jd", "8c", "4s", None, None], "pot": "120",
              "participants": {"2": "active"}, "stacks": {"4": "1000", "2": "1000"},
              "hero_controls": {"visible": True, "button": "call", "call_amount": "40"}}
    check_raise = aa_solver_advice.rough_advice(
        {**fields, "street_wagers": {"4": "20", "2": "60"},
         "actions_v1": _bets(("flop", 2, "check", "0"), ("flop", 4, "raise", "20"),
                             ("flop", 2, "raise", "60"))}, ["Js", "5c"], "flop")
    bet = aa_solver_advice.rough_advice(
        {**fields, "pot": "60", "street_wagers": {"2": "20"},
         "hero_controls": {"visible": True, "button": "call", "call_amount": "20"},
         "actions_v1": _bets(("flop", 2, "raise", "20"))}, ["Js", "5c"], "flop")
    assert check_raise["range_equity"]["value"] < bet["range_equity"]["value"] - 0.1
    # A bet the history has not got yet is read from the chips in front: a
    # raise over yours as a raise.
    unread = aa_solver_advice.rough_advice(
        {**fields, "street_wagers": {"4": "20", "2": "60"},
         "actions_v1": _bets(("flop", 2, "check", "0"))}, ["Js", "5c"], "flop")
    values = [advice["range_equity"]["value"] for advice in (unread, check_raise)]
    assert abs(values[0] - values[1]) < 0.06


def test_a_bet_of_the_pot_or_an_all_in_counts_as_a_raise():
    history = _bets(("flop", 2, "raise", "30"), ("flop", 3, "call", "30"),
                    ("turn", 2, "raise", "100"), ("turn", 3, "all_in", "60"),
                    ("river", 3, "all_in", "40"))
    # The pot before the turn bet: 300 less the chips from it on (100 + 60 +
    # 40); the all in for 60 only calls it.
    found = aa_solver_advice.aggression({"actions_v1": history}, "river", Decimal(300))
    assert found == [("2", "flop", False), ("2", "turn", True), ("3", "river", False)]
