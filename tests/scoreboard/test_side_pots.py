"""The chips you can win at a decision: main pot, side pots and rake."""

import json
from pathlib import Path
import random

import pytest

from poker_engine.scoreboard import multiway_bot, side_pots
from poker_engine.scoreboard.ranges import ranges_equity
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"
NO_RAKE = {"rake_percent": "0", "rake_cap_bb": "0", "minimum_chip": "1",
           "big_blind": "2"}
RAKE = {**NO_RAKE, "rake_percent": "0.05", "rake_cap_bb": "5"}


def spot(put, stacks, to_call, folded=(), pot=None, rules=NO_RAKE, me=4):
    """You are seat 4; ``put``: {seat: chips in this hand}."""
    return {"observing_seat": me, "occupied_seats": sorted(put), "folded": list(folded),
            "contributions": {str(seat): str(chips) for seat, chips in put.items()},
            "stacks": {str(seat): str(chips) for seat, chips in stacks.items()},
            "pot": str(sum(put.values()) if pot is None else pot),
            "to_call": str(to_call), "rules": rules}


def test_chips_you_cannot_match_are_not_in_the_price():
    # 100 in the pot (50 each); the bettor puts 500 more in, you have 50 left.
    short = spot({4: 50, 5: 550}, {4: 50, 5: 1000}, to_call=50)
    assert side_pots.pots(short) == [(200.0, (5,))]
    assert side_pots.price(short) == pytest.approx(0.25)
    # The old price counted the bettor's 450 you can never win: 50 / 650.
    assert 50 / (600 + 50) == pytest.approx(0.077, abs=1e-3)


def test_an_opponent_all_in_for_less_wins_only_the_main_pot():
    # Seat 2 is all in for 20; seat 5 has bet 40 more than your 60; seat 7
    # folded after putting 10 in.
    table = spot({2: 20, 4: 60, 5: 100, 7: 10}, {2: 0, 4: 300, 5: 300, 7: 90},
                 to_call=40, folded=[7])
    assert side_pots.pots(table) == [(70.0, (2, 5)), (160.0, (5,))]
    assert side_pots.matched(table) == 230
    assert side_pots.price(table) == pytest.approx(40 / 230)


def test_an_opponent_short_of_the_bet_is_in_the_pots_its_stack_reaches():
    # Seat 2 has 30 behind: it can still call, up to 40 in all.
    table = spot({2: 10, 4: 10, 5: 60}, {2: 30, 4: 500, 5: 500}, to_call=50)
    assert side_pots.pots(table) == [(90.0, (2, 5)), (40.0, (5,))]


def test_a_stack_not_read_covers_every_pot():
    # The live window leaves unread stacks deep; one missing counts the same.
    table = spot({2: 20, 4: 60, 5: 60}, {2: 0, 4: 300}, to_call=0)
    assert side_pots.pots(table) == [(60.0, (2, 5)), (80.0, (5,))]


def test_one_depth_and_no_rake_is_the_old_price():
    table = spot({3: 40, 4: 40, 5: 80}, {3: 500, 4: 500, 5: 500}, to_call=40)
    assert side_pots.pots(table) == [(200.0, (3, 5))]
    assert side_pots.price(table) == pytest.approx(40 / (160 + 40))
    # Without the seats' chips (a bare observation) too.
    bare = {"observing_seat": 4, "occupied_seats": [4, 5], "folded": [],
            "pot": "100", "to_call": "20", "rules": {"big_blind": "2"}}
    assert side_pots.pots(bare) == [(120.0, (5,))] and side_pots.kept(bare) == 1.0


def test_the_pot_read_above_the_seats_chips_is_in_the_main_pot():
    table = spot({2: 20, 4: 60, 5: 60}, {2: 0, 4: 300, 5: 300}, to_call=0, pot=150)
    assert side_pots.pots(table) == [(70.0, (2, 5)), (80.0, (5,))]


def test_rake_comes_off_the_chips_matched():
    # 230 matched once you call: 5% is 11.5, floored to 11, capped at 10
    # (5 big blinds of 2).
    table = spot({2: 20, 4: 60, 5: 100, 7: 10}, {2: 0, 4: 300, 5: 300, 7: 90},
                 to_call=40, folded=[7], rules=RAKE)
    assert side_pots.kept(table) == pytest.approx(220 / 230)
    assert side_pots.price(table) == pytest.approx(40 / 220)
    # Below the cap: 100 matched, 5 raked. The bettor's chips above what you
    # can match go back unraked.
    small = spot({4: 25, 5: 300}, {4: 25, 5: 700}, to_call=25, rules=RAKE)
    assert side_pots.kept(small) == pytest.approx(95 / 100)
    assert side_pots.price(small) == pytest.approx(25 / 95)


def test_your_share_of_each_side_pot_is_against_its_players():
    board = ["Kh", "8c", "2d", "5s", "9c"]
    # Seat 2 holds kings (a set): it wins the main pot. Seat 5 holds seven-
    # three: you win the side pot only it is in.
    ranges = {2: {"KsKd": 1.0}, 5: {"7d3h": 1.0}}
    main_only, _ = ranges_equity(["Ah", "As"], board, ranges, trials=200)
    assert main_only == 0.0
    share, counts = ranges_equity(["Ah", "As"], board, ranges, trials=200,
                                  pots=[(70.0, (2, 5)), (160.0, (5,))])
    assert share == pytest.approx(160 / 230) and counts == {2: 1, 5: 1}
    # One pot against everyone is the default, draw for draw.
    wide = {2: {"KsKd": 1.0, "QsQd": 1.0, "JsJd": 1.0},
            5: {"7d3h": 1.0, "Tc9d": 1.0}}
    flop = board[:3]
    assert ranges_equity(["Ah", "As"], flop, wide, trials=300, seed=4) == ranges_equity(
        ["Ah", "As"], flop, wide, trials=300, seed=4, pots=[(5.0, (2, 5))])


def test_the_range_rule_weighs_the_side_pots(monkeypatch):
    seen = {}

    def equity(hole, board, ranges, **kwargs):
        seen.update(kwargs)
        return 0.2, {}

    monkeypatch.setattr(multiway_bot, "opponent_ranges", lambda observation, model: {})
    monkeypatch.setattr(multiway_bot, "ranges_equity", equity)

    class Base:
        adjusted = True

        def decide(self, observation, rng):
            return "base"

    table = {**spot({2: 20, 4: 60, 5: 100, 7: 10}, {2: 0, 4: 300, 5: 300, 7: 90},
                    to_call=40, folded=[7], rules=RAKE),
             "street": "turn", "own_hole": ["Ah", "As"],
             "board": ["Kh", "8c", "2d", "5s"],
             "public_history": [], "bets": {"4": "0", "5": "40"},
             "legal_actions": [{"id": "fold", "kind": "fold"},
                               {"id": "check_call", "kind": "check_call"}]}
    bot = multiway_bot.RangeMultiwayBot(Base())
    # 0.2 beats the price of 40 / 220 = 0.18 (the old one: 40 / 230 = 0.17).
    assert bot.decide(table, random.Random(0)) == "check_call"
    assert seen["pots"] == [(70.0, (2, 5)), (160.0, (5,))]
    assert multiway_bot.cuts(table)["call"] == pytest.approx(40 / 220)


def flop_order(arena, seed, stacks):
    """The seats in the order they act on the flop when everyone calls."""
    arena.reset(seed, stacks={seat: str(chips) for seat, chips in stacks.items()})
    while arena.street == "preflop":
        arena.step("check_call")
    order = []
    while arena.street == "flop":
        order.append(arena.actor)
        arena.step("check_call")
    return order


def test_the_arena_short_stack_call_is_priced_on_what_it_can_win():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules)
    stacks = {seat: 400 for seat in arena.occupied_seats}
    order = flop_order(arena, 3, stacks)
    short = order[-1]
    stacks[short] = 30                            # 15 big blinds
    assert flop_order(arena, 3, stacks) == order
    arena.reset(3, stacks={seat: str(chips) for seat, chips in stacks.items()})
    while arena.street == "preflop":
        arena.step("check_call")
    # The first to act on the flop bets all in; everyone else folds to you.
    shove = max(arena.observe(arena.actor)["legal_actions"],
                key=lambda action: float(action.get("raise_to") or 0))
    arena.step(shove["id"])
    while arena.actor != short:
        arena.step("fold")
    observation = arena.observe(short)
    to_call, pot = float(observation["to_call"]), float(observation["pot"])
    assert to_call == float(observation["stacks"][str(short)])        # all you have
    (chips, rivals), = side_pots.pots(observation)
    put = float(observation["contributions"][str(short)]) + to_call
    assert rivals == (order[0],) and chips == pot + to_call - (400 - put)
    assert side_pots.price(observation) > to_call / (pot + to_call)
