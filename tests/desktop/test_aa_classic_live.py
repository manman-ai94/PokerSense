"""The default advice (classic) under the vision contract (补充二): the old
strategy's decisions from the hand's latched state; ready conditions, each
decision worked out once and kept, defaults for what is missing, the iron rule
5 after 2 s; no solver and no rough rule (``aa_classic_advice``).

The screens are ``test_aa_plain_live.Screen``'s: 8 seats, dealer 7 (0 small
blind, 1 big blind, 2 straddle), 1/2/4(2), 200 each; you are seat 4.
"""

import random
import threading

import pytest

from poker_engine.desktop import aa_classic_advice as classic
from poker_engine.desktop.aa_classic_advice import (AAClassicAdvice, ClassicPolicy,
                                                    table_state)
from poker_engine.desktop.aa_solver_advice import LEGACY, AASolverAdvice
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
from tests.desktop.test_aa_plain_live import HERO, Clock, Screen, ready
from tests.desktop.test_aa_solver_advice import Bot, Inline, run
from tests.scoreboard.test_plain_policy import RULES_DICT, spot


def same(report, observation):
    """The window's advice is the old strategy's on the scoreboard table at the
    same step."""
    expected = ClassicPolicy().decide(observation)
    assert (report["kind"], report["advice"]) == (expected["kind"], expected["advice"])
    if expected["kind"] == "preflop":
        assert report["options"] == expected["options"]
    else:
        assert report["range_equity"] == expected["range_equity"]
        assert report["heads_up"] == expected["heads_up"]


# -- the old strategy, as on the scoreboard table -----------------------------------

def test_preflop_facing_an_open_is_the_old_strategy_on_the_scoreboard_table():
    screen = Screen(AAClassicAdvice(clock=Clock()), hero=("Qs", "Qh"))
    screen.deal()
    screen.put(3, 12, badge="raise")
    report = ready(screen, call=12)
    assert report["street"] == "preflop" and report["acts_on_client"] is False
    same(report, spot({4: "QsQh"}, "", "3r12"))
    assert report["contract"]["tag"].startswith("就绪 ")
    assert report["contract"]["defaults"] == []


def test_heads_up_flop_facing_a_bet_reads_the_range_without_a_solver():
    screen = Screen(AAClassicAdvice(), hero=("Qs", "Qh"))
    screen.deal()
    screen.fold(3)
    ready(screen, call=4)
    screen.put(HERO, 12)
    screen.acted()
    for seat in (5, 6, 7, 0, 1):
        screen.fold(seat)
    screen.put(2, 12)
    screen.street("flop", "Ah", "Kd", "7c")
    screen.put(2, 20)
    report = ready(screen, call=20)
    assert report["kind"] == "multiway" and report["heads_up"] is True
    same(report, spot({4: "QsQh"}, "AhKd7c", "3f 4r12 5f 6f 7f 0f 1f 2c 2r20"))


def test_checks_nobody_reads_are_filled_in_as_the_table_asks():
    screen = Screen(AAClassicAdvice(), hero=("Js", "Th"))
    screen.deal()
    screen.put(3, 4)
    ready(screen, call=4)
    screen.put(HERO, 4)
    screen.acted()
    for seat in (5, 6, 7, 0, 1):
        screen.fold(seat)
    screen.street("flop", "Jd", "8c", "2h")
    ready(screen)                                       # the straddle and 3 check
    screen.acted()
    screen.street("turn", "5s")
    screen.put(2, 10)
    screen.put(3, 10)
    report = ready(screen, call=10)
    assert report["kind"] == "multiway" and report["heads_up"] is False
    same(report, spot({4: "JsTh"}, "Jd8c2h5s",
                      "3c 4c 5f 6f 7f 0f 1f 2c 2c 3c 4c 2r10 3c"))
    assert report["inferred_actions"] >= 4              # the checks and the option


def test_the_old_strategy_knows_tables_of_four_to_eight():
    observation = spot({4: "QsQh"}, "", "3r12")
    three = {**observation, "occupied_seats": [2, 3, 4]}
    assert ClassicPolicy().decide(three) == "seats"


# -- ready conditions: nothing is worked out before ----------------------------------

def opened(clock=None, **options):
    screen = Screen(AAClassicAdvice(clock=clock or Clock()), **options)
    screen.deal()
    screen.put(3, 12)
    return screen


def test_the_price_must_hold_three_frames():
    screen = opened()
    first = screen.turn(call=12, frames=2)
    assert (first["status"], first["reason"], first["kind"]) == (
        "reading", "price_not_steady", "classic")
    assert "advice" not in first
    assert screen.turn(call=12, frames=1)["status"] == "ready"


def test_your_cards_must_be_read():
    screen = opened(hero=(None, None))
    assert screen.turn(call=12)["reason"] == "hero_cards"


def test_cards_read_two_ways_in_a_hand_are_never_ready():
    screen = opened()
    screen.show(3, hero=["Qs", "Jh"])
    assert screen.turn(call=12)["reason"] == "card_conflict"


# -- once per decision, never changed -----------------------------------------------

def test_a_decision_is_worked_out_once_and_kept(monkeypatch):
    calls = []
    decide = ClassicPolicy.decide
    monkeypatch.setattr(ClassicPolicy, "decide",
                        lambda self, observation: calls.append(1) or decide(
                            self, observation))
    screen = opened()
    first = ready(screen, call=12)
    screen.fields["actions_v1"]["actions"].append(          # a badge read late
        [screen.frame, "preflop", 3, "raise", "12", "pot_rise"])
    again = screen.turn(call=12, frames=10)
    assert again["advice"] == first["advice"] and len(calls) == 1


def test_a_new_price_is_a_new_decision_with_the_old_one_beside_it():
    clock = Clock()
    screen = opened(clock)
    first = ready(screen, call=12)
    screen.put(HERO, 12)
    screen.acted()
    screen.put(5, 40)
    report = ready(screen, call=28)
    assert report["price"] == "28" and report["facing"] == "40"
    assert report["previous"]["advice"] == first["advice"]
    clock.now += 3
    assert "previous" not in screen.turn(call=28, frames=1)


# -- defaults and the iron rule 5 ------------------------------------------------------

def test_an_opponent_stack_never_read_is_taken_as_deep():
    screen = Screen(AAClassicAdvice(clock=Clock()))
    screen.hidden = {3}
    screen.deal()
    screen.put(3, 12)
    report = ready(screen, call=12)
    assert report["kind"] == "preflop"
    assert report["contract"]["defaults"] == ["缺对手筹码→按很深算"]


def test_two_seconds_not_ready_is_the_iron_rule_5_with_what_is_missing():
    clock = Clock()
    screen = opened(clock, hero=(None, None))
    assert screen.turn(call=12, frames=19)["status"] == "reading"
    report = screen.turn(call=12, frames=2)
    assert (report["status"], report["kind"]) == ("ready", "unread")
    assert report["advice"] == [{"action": "fold", "frequency": 1.0}]
    assert report["contract"]["missing"][0] == "hero_cards"
    assert report["contract"]["tag"] == "铁律 5：缺你的手牌"


def test_the_iron_rule_5_checks_when_it_is_free(monkeypatch):
    monkeypatch.setattr(classic, "table_state", _broken)
    screen = Screen(AAClassicAdvice(clock=Clock()))
    screen.deal()
    screen.put(3, 4)
    assert ready(screen, call=4)["advice"] == [{"action": "fold", "frequency": 1.0}]
    screen.put(HERO, 4)
    screen.acted()
    for seat in (5, 6, 7, 0, 1):
        screen.fold(seat)
    screen.street("flop", "Jd", "8c", "2h")
    report = ready(screen)
    assert report["kind"] == "unread" and report["contract"]["missing"] == ["actions"]
    assert report["advice"] == [{"action": "check", "frequency": 1.0}]


def _broken(observation, partial=False):
    raise ValueError("an action left over")


# -- the hand put together on the scoreboard table -------------------------------------

def _hand(seed):
    """A hand of random legal actions up to one of your turns, or None."""
    chance = random.Random(seed)
    rules = AARuleProfileV2.from_dict(RULES_DICT | {"table_size": 8})
    arena = AAFullHandArena(rules, occupied_seats=list(range(8)))
    arena.reset(seed)
    while not arena.terminal:
        if arena.actor == HERO and chance.random() < 0.4:
            return arena.observe(HERO)
        rows = arena.legal_actions()
        weights = [1 if row.kind == "fold" else 4 if row.kind == "check_call" else 1
                   for row in rows]
        arena.step(chance.choices(rows, weights)[0])
    return None


def _as_read(observation):
    """The actions as the screen reads them: from the chips, so no checks."""
    rows = [row for row in observation["public_history"]
            if not (row["kind"] == "check_call" and row["paid"] == "0")]
    return {**observation, "public_history": rows}


@pytest.mark.parametrize("seed", range(40))
def test_the_screen_s_actions_play_out_to_the_same_table(seed):
    observation = _hand(seed)
    if observation is None:
        return
    table, filled = table_state(_as_read(observation))
    assert [row["id"] for row in table["public_history"]] == [
        row["id"] for row in observation["public_history"]]
    assert filled == len(observation["public_history"]) - len(
        _as_read(observation)["public_history"])
    assert (table["to_call"], table["pot"], table["legal_actions"]) == (
        observation["to_call"], observation["pot"], observation["legal_actions"])


def test_each_seat_s_actions_are_played_in_turn_whatever_order_they_were_read():
    observation = spot({4: "QsQh"}, "Ah7d2c", "3c 4r12 5f 6c 7f 0f 1f 2c 3c 2r8 3c")
    rows = _as_read(observation)["public_history"]
    swapped = [rows[1], rows[0], *rows[2:]]           # 4's raise read before 3's call
    table, _ = table_state({**observation, "public_history": swapped})
    assert table["to_call"] == observation["to_call"]
    assert [row["id"] for row in table["public_history"]] == [
        row["id"] for row in observation["public_history"]]


def test_a_fold_read_with_nothing_to_call_is_a_check_and_counted_folded():
    observation = spot({4: "QsQh"}, "Ah7d2c", "3c 4c 5f 6f 7f 0f 1f 2c 2c 3c")
    rows = _as_read(observation)["public_history"]
    folded = {**observation, "folded": sorted({*observation["folded"], 2}),
              "public_history": [*rows, {**rows[-1], "actor": 2, "street": "flop",
                                         "id": "fold", "kind": "fold", "paid": "0"}]}
    table, _ = table_state(folded)
    assert 2 in table["folded"] and table["to_call"] == "0"


def test_a_raise_the_table_does_not_allow_is_moved_to_the_nearest_it_does():
    observation = spot({4: "QsQh"}, "", "3r12")
    rows = _as_read(observation)["public_history"]
    small = [{**rows[0], "id": "raise_to:5", "raise_to": "5"}]       # under the minimum
    table, _ = table_state({**observation, "public_history": small})
    assert table["public_history"][0]["id"] == "raise_to:8"


def test_an_action_that_does_not_fit_is_the_iron_rule_5(monkeypatch):
    observation = spot({4: "QsQh"}, "", "3r12")
    rows = _as_read(observation)["public_history"]
    late = {**rows[0], "street": "flop"}            # 3 again, on a street not dealt
    with pytest.raises(ValueError):
        table_state({**observation, "public_history": [*rows, late]})
    # Played out, the table asks a price your button does not show.
    monkeypatch.setattr(classic, "table_state", lambda observation, partial=False: (
        {**spot({4: "QsQh"}, "", "3r20"), "inferred_actions": 0}, 0))
    report = ready(opened(), call=12)
    assert report["kind"] == "unread" and report["contract"]["missing"] == ["actions"]


# -- reading ahead, and no solver -----------------------------------------------------

def test_the_ranges_are_read_ahead_while_the_opponents_act(monkeypatch):
    threads = []
    reader = classic.opponent_ranges
    monkeypatch.setattr(classic, "opponent_ranges", lambda *args, **kwargs: (
        threads.append(threading.current_thread().name) or reader(*args, **kwargs)))
    screen = Screen(AAClassicAdvice(), hero=("Qs", "Qh"))
    screen.deal()
    screen.fold(3)
    ready(screen, call=4)
    screen.put(HERO, 12)
    screen.acted()
    for seat in (5, 6, 7, 0, 1):
        screen.fold(seat)
    screen.put(2, 12)
    screen.street("flop", "Ah", "Kd", "7c")
    screen.put(2, 20)
    screen.advice._ahead[1].result()
    assert any(name.startswith("range-ahead") for name in threads)
    report = ready(screen, call=20)
    assert report["kind"] == "multiway"


def test_the_default_runs_no_solver_and_the_old_engine_is_kept_for_replays():
    bot = Bot({"CALL": 1.0})
    results = run(AASolverAdvice(bot, Inline()), range(50))
    assert not bot.seen
    assert {result.get("kind") for result in results} <= {None, "classic", "multiway"}
    old = run(AASolverAdvice(Bot({"CALL": 1.0}), Inline(), strategy=LEGACY), range(50))
    assert old[-1]["status"] == "ready" and old[-1].get("kind") is None
