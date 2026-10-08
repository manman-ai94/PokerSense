"""Every opponent's range from the public actions, and equity against them."""

import json
from pathlib import Path
import random

from poker_engine.scoreboard.bots import _rng, make_policy, opponents_in_hand
from poker_engine.scoreboard.population import PopulationBot
from poker_engine.scoreboard.ranges import opponent_ranges, ranges_equity
from poker_engine.scoreboard.strength import equity
from poker_engine.solver.texassolver import all_combos
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


def test_against_every_hand_it_is_equity_against_random_hands():
    hero, board = ("Ah", "Kd"), ("Qs", "7h", "2c")
    every = {key: 1.0 for key in all_combos(board)}
    value, counts = ranges_equity(hero, board, {1: every, 2: every}, trials=20000)
    assert abs(value - equity(hero, board, 2, 20000, random.Random(1))) < 0.02
    assert counts == {1: 1081, 2: 1081}         # 49 cards left: 49 * 48 / 2


def test_known_hands_and_hands_that_cannot_be_dealt():
    board = ("2c", "3d", "4h", "7s", "9c")
    assert ranges_equity(("Ah", "As"), board, {1: {"KhKs": 1.0}})[0] == 1.0
    split = ranges_equity(("Ah", "Kc"), board, {1: {"AdKd": 1.0}, 2: {"AcKs": 1.0}})
    assert abs(split[0] - 1 / 3) < 1e-9
    # A hand using your card or a board card is left out; nothing left is None.
    assert ranges_equity(("Ah", "As"), board, {1: {"AhKs": 1.0}}) == (None, {1: 0})
    # Two opponents who could only hold the same cards cannot both be dealt.
    assert ranges_equity(("Ah", "As"), board,
                         {1: {"KhKs": 1.0}, 2: {"KhKs": 1.0}})[0] is None


def test_every_opponent_still_in_gets_a_range_read_from_their_actions():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules)
    pool, model = make_policy("aa_population"), PopulationBot(adjusted=True)
    for seed in range(40):
        arena.reset(seed)
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            postflop = observation["street"] != "preflop"
            if postflop and opponents_in_hand(observation) >= 2:
                ranges = opponent_ranges(observation, model)
                me = observation["observing_seat"]
                live = {seat for seat in observation["occupied_seats"]
                        if seat not in observation["folded"]} - {me}
                assert set(ranges) == live
                every = len(all_combos(observation["board"]))
                assert all(0 < len(hands) < every for hands in ranges.values())
                value, _ = ranges_equity(observation["own_hole"], observation["board"],
                                         ranges, trials=500)
                assert 0 <= value <= 1
                return
            arena.step(pool.decide(observation, _rng("test", observation)))
    raise AssertionError("no multiway postflop decision in 40 deals")
