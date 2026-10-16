"""The 大道至简 rule: read each opponent's hands by what he did, then your
share of the pot against the price. Synthetic spots only."""

import json
from pathlib import Path

import numpy as np
import pytest

from poker_engine.scoreboard import simple
from poker_engine.scoreboard.bots import _rng, make_policy
from poker_engine.scoreboard.simple import Move, Spot
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"
FLOP, TURN, RIVER = ("Ks", "9c", "5d"), ("Ks", "9c", "5d", "2h"), (
    "Ks", "9c", "5d", "2h", "7s")
# Seat 0 opened, you called; he bet the flop, checked the turn.
BEFORE_RIVER = (
    Move(0, "preflop", "r", "rfi"),
    Move(0, "flop", "r", "checked_to", "hu", "pfa", 0.5, board=FLOP),
    Move(0, "turn", "c", "checked_to", "hu", "pfa", free=True, board=TURN),
)


def river(hero, last=None, to_call=0.0, pot=40.0, **values):
    """You on the river, heads-up against seat 0; ``last`` his river action."""
    moves = BEFORE_RIVER + ((last,) if last else ())
    return Spot(hero=tuple(hero.split()), board=RIVER, street="river",
                opponents=(0,), moves=moves, pot=pot + to_call, to_call=to_call,
                stack=400.0, bet=0.0, top=to_call, big_blind=2.0,
                price=to_call / (pot + 2 * to_call) if to_call else 0.0, **values)


def shove(size):
    return Move(0, "river", "r", "checked_to", "hu", "pfa", size, board=RIVER)


def test_every_action_keeps_every_hand_possible():
    place = np.linspace(0, 1, 101)
    moves = [Move(0, "preflop", kind, spot) for kind in "rc"
             for spot in simple.PREFLOP]
    moves += [Move(0, street, kind, facing, width, role, size, kind == "c" and
                   facing == "checked_to")
              for street in ("flop", "turn", "river") for kind in "rc"
              for facing in ("checked_to", "facing_bet", "facing_raise")
              for width in ("hu", "multi") for role in ("pfa", "other")
              for size in (0.3, 1.0, 3.0)]
    for move in moves:
        weights = simple.likelihood(move, place)
        assert weights.min() > 0 and weights.max() == 1.0, move


def test_a_bigger_bet_keeps_fewer_hands_and_the_best_ones_whole():
    dead = ("Qh", "Qd", *RIVER)
    half = simple.read_ranges(BEFORE_RIVER + (shove(0.5),), (0,), dead)[0]
    jam = simple.read_ranges(BEFORE_RIVER + (shove(2.0),), (0,), dead)[0]
    assert jam.sum() < half.sum()
    strength = simple.board_strength(RIVER)
    nuts = int(np.argmax(np.where(half > 0, strength, -1)))
    assert sorted((simple.KEYS[nuts][:2], simple.KEYS[nuts][2:]))[0][0] in "86"
    # The best hands are read the same; the middle is cut; air keeps its
    # bluffing weight, so a shove is never read as nothing but the nuts.
    assert jam[nuts] == half[nuts] > 0
    assert (jam < half).any()
    air = simple.KEYS.index(next(key for key in simple.KEYS
                                 if sorted((key[:2], key[2:])) == ["3c", "4h"]))
    assert jam[air] == half[air] > 0


def test_one_pair_folds_to_a_big_river_shove_and_the_nuts_call():
    spot = river("5c 4c", shove(2.0), to_call=80.0)
    advice = simple.decide(spot)
    assert advice.action == "fold" and advice.equity < advice.need
    nuts = river("8h 6h", shove(2.0), to_call=80.0, all_in=(0,), can_raise=False)
    assert simple.decide(nuts).action == "call"


def test_the_nuts_raise_a_small_bet_and_bet_when_checked_to():
    small = river("8h 6h", shove(0.3), to_call=12.0)
    advice = simple.decide(small)
    assert advice.action == "raise" and advice.rule == "value_raise"
    assert advice.to > 12.0
    checked = Move(0, "river", "c", "checked_to", "hu", "pfa", free=True, board=RIVER)
    advice = simple.decide(river("8h 6h", checked))
    assert advice.action == "bet" and advice.rule == "value_bet"
    # Two thirds of the pot.
    assert advice.to == pytest.approx(simple.BET_SIZE * 40.0)


def test_no_bluffs():
    checked = Move(0, "river", "c", "checked_to", "hu", "pfa", free=True, board=RIVER)
    assert simple.decide(river("4h 3h", checked)).action == "check"


def preflop(hero, **values):
    spot = dict(hero=tuple(hero.split()), board=(), street="preflop",
                opponents=tuple(range(1, 8)), moves=(), pot=14.0, to_call=8.0,
                stack=392.0, bet=0.0, top=8.0, big_blind=4.0, price=8 / 22,
                posted=(5, 6, 7), behind=7, preflop_spot="rfi")
    spot.update(values)
    return Spot(**spot)


def test_first_in_raises_the_top_of_the_chart_and_folds_the_rest():
    aces = simple.decide(preflop("As Ah"))
    assert aces.action == "raise" and aces.rule == "open"
    assert aces.to == pytest.approx(8.0 + 14.0 + 8.0)       # a pot-sized raise
    assert simple.decide(preflop("7c 2d")).action == "fold"
    # Short: the raise is all in.
    short = simple.decide(preflop("As Ah", stack=40.0, effective_bb=10.0))
    assert short.action == "raise" and short.to == 40.0


def test_against_raises_the_best_hands_go_all_in_and_the_rest_price_it():
    raised = (Move(0, "preflop", "r", "rfi"), Move(1, "preflop", "r", "vs_open"))
    four = simple.decide(preflop("As Ah", opponents=(0, 1), moves=raised, raises=2,
                                 pot=150.0, to_call=96.0, top=96.0, price=96 / 246,
                                 behind=0, preflop_spot="vs_3bet_cold"))
    assert four.action == "raise" and four.to == 392.0
    # Kings against an all in: the share against his range, nothing to realize.
    jam = simple.decide(preflop("Ks Kh", opponents=(0,), moves=raised[:1], raises=1,
                                pot=420.0, to_call=392.0, top=400.0, price=392 / 820,
                                all_in=(0,), can_raise=False, behind=0,
                                preflop_spot="vs_open"))
    assert jam.action == "call" and jam.equity > jam.need
    trash = simple.decide(preflop("7c 2d", opponents=(0,), moves=raised[:1], raises=1,
                                  pot=420.0, to_call=392.0, top=400.0, price=392 / 820,
                                  all_in=(0,), can_raise=False, behind=0,
                                  preflop_spot="vs_open"))
    assert trash.action == "fold"


def test_it_plays_whole_hands_on_the_scoreboard_table():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena, pool = AAFullHandArena(rules), make_policy("aa_population")
    rule = make_policy("simple")
    assert make_policy("simple+aa_preflop").base is not None
    actions = []
    for seed in range(3):
        arena.reset(seed)
        seat = arena.occupied_seats[seed]
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            if arena.actor == seat:
                action = rule.decide(observation, None)
                actions.append((observation["street"], action))
            else:
                action = pool.decide(observation, _rng("test", observation))
            arena.step(action)
    assert actions and all(action == "fold" or action == "check_call"
                           or action.startswith("raise_to:") for _, action in actions)
