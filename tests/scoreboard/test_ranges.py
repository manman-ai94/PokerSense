"""Every opponent's range from the public actions, and equity against them."""

import json
from pathlib import Path
import random

from poker_engine.scoreboard.bots import _rng, make_policy, opponents_in_hand
from poker_engine.scoreboard.population import PopulationBot
from poker_engine.scoreboard.ranges import opponent_ranges, ranges_equity, read_floors
from poker_engine.scoreboard.replay import replay_deck
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


def test_ranges_kept_from_earlier_decisions_are_the_same_as_read_again():
    from poker_engine.scoreboard import ranges
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules).reset(5, bomb="14")
    model = PopulationBot(adjusted=True)
    bots = {seat: make_policy("aa_population").for_game(str(seat))
            for seat in arena.occupied_seats}
    seen = []
    while not arena.terminal and len(seen) < 4:
        observation = arena.observe(arena.actor)
        seen.append(observation)
        opponent_ranges(observation, model)             # fills the cache
        arena.step(bots[arena.actor](observation))
    last = seen[-1]
    kept = opponent_ranges(last, model)
    ranges._KEPT.clear()
    assert kept == opponent_ranges(last, model)


def _three_way_flop(flop):
    """The first decision on ``flop`` after the same preflop line every time:
    the first player raises, the next two call, everyone else folds."""
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules)
    arena.reset(0, deck=replay_deck([{"cards": list(flop)}], len(arena.occupied_seats)))
    arena.step(next(a["id"] for a in arena.observe(arena.actor)["legal_actions"]
                    if a["kind"] == "raise_to"))
    callers = 0
    while arena.street == "preflop":
        arena.step("check_call" if callers < 2 else "fold")
        callers += 1
    observation = arena.observe(arena.actor)
    assert list(observation["board"]) == list(flop)
    assert opponents_in_hand(observation) == 2
    return observation


def test_a_range_kept_in_one_hand_is_not_cut_by_its_board_in_another(monkeypatch):
    from poker_engine.scoreboard import ranges
    model = PopulationBot(adjusted=True)
    spades = _three_way_flop(("As", "Ks", "Qs"))
    low = _three_way_flop(("2c", "3d", "4h"))
    assert low["public_history"] == spades["public_history"]
    monkeypatch.setattr(ranges, "_KEPT", {})
    opponent_ranges(spades, model)
    after_other_hand = opponent_ranges(low, model)
    monkeypatch.setattr(ranges, "_KEPT", {})
    alone = opponent_ranges(low, model)
    assert all(any("As" in (combo[:2], combo[2:]) for combo in weights)
               for weights in alone.values())
    assert after_other_hand == alone


def test_a_shared_cache_reads_every_postflop_range_as_a_fresh_one(monkeypatch):
    from poker_engine.scoreboard import ranges
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules)
    model = PopulationBot(adjusted=True)
    shared = {}
    reads = differ = 0
    for seed in range(5, 10):
        arena.reset(seed)
        bots = {seat: make_policy("aa_population").for_game(f"{seed}-{seat}")
                for seat in arena.occupied_seats}
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            if observation["street"] != "preflop":
                monkeypatch.setattr(ranges, "_KEPT", shared)
                kept = opponent_ranges(observation, model)
                monkeypatch.setattr(ranges, "_KEPT", {})
                fresh = opponent_ranges(observation, model)
                reads += 1
                differ += kept != fresh
                assert not any({combo[:2], combo[2:]} & set(observation["board"])
                               for weights in kept.values() for combo in weights)
            arena.step(bots[arena.actor](observation))
    assert reads >= 30
    assert differ == 0


def _bet_into():
    """A flop where the preflop opener has bet into the observer, and the opener."""
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules).reset(3)
    opener = arena.actor
    arena.step(next(a["id"] for a in arena.observe(opener)["legal_actions"]
                    if a["kind"] == "raise_to"))
    while len(arena.observe(0)["folded"]) < len(arena.occupied_seats) - 2:
        arena.step("fold")
    arena.step("check_call")
    bet = next(a["id"] for a in arena.observe(arena.actor)["legal_actions"]
               if a["kind"] == "raise_to")
    if arena.actor == opener:
        arena.step(bet)
    return arena.observe(arena.actor), opener


def test_reads_widen_the_range_of_a_seat_that_raises_more_than_the_model():
    observation, opener = _bet_into()
    model = PopulationBot(adjusted=True)

    def width(reads):
        weights = opponent_ranges({**observation, "reads": reads} if reads else
                                  observation, model)[opener]
        return sum(weights.values())

    plain = width(None)
    assert width({str(opener): {"hands": 100, "vpip": 0.37, "pfr": 0.115}}) == plain
    wide = width({str(opener): {"hands": 300, "vpip": 0.5, "pfr": 0.35}})
    tight = width({str(opener): {"hands": 300, "vpip": 0.15, "pfr": 0.05}})
    assert tight < plain < wide


def test_only_betting_more_after_the_flop_keeps_extra_hands_after_it():
    observation, opener = _bet_into()
    arena = AAFullHandArena(AARuleProfileV2.from_dict(json.loads(
        RULES.read_text(encoding="utf-8"))))
    arena.reset(3)
    for row in observation["public_history"]:
        arena.step(row["id"])
    while arena.actor != opener:            # check to the opener, who then bets
        arena.step("check_call")
    arena.step(next(a["id"] for a in arena.observe(opener)["legal_actions"]
                    if a["kind"] == "raise_to"))
    observation = arena.observe(arena.actor)
    model = PopulationBot(adjusted=True)
    assert observation["street"] == "flop"
    preflop = {"hands": 300, "vpip": 0.37, "pfr": 0.115}
    seat = str(opener)

    def width(read):
        weights = opponent_ranges({**observation, "reads": {seat: read}}, model)
        return sum(weights[opener].values())

    plain = width(preflop)
    honest = width({**preflop, "postflop": 60, "aggression": 0.21})
    betting = width({**preflop, "postflop": 60, "aggression": 0.6})
    raiser = {"reads": {seat: {**preflop, "pfr": 0.35}}}
    assert read_floors(raiser, model, [opener]) == {opener: 0.0}
    assert honest == plain < betting
