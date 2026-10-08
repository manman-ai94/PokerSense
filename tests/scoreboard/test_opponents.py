"""Tougher scoreboard opponents: legal, true to their profile, usable as pools."""

from collections import Counter
import json
from pathlib import Path

import pytest

from poker_engine.scoreboard.bots import OPPONENT_NAMES, make_policy
from poker_engine.scoreboard.opponents import (PROFILES, minimum_defence,
                                               postflop_plan, preflop_shares)
from poker_engine.scoreboard.population import MAX_CONTINUE
from poker_engine.scoreboard.population import preflop_shares as population_shares
from poker_engine.scoreboard.runner import POOLS
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"
POSITIONS = ("EP", "LJ", "HJ", "CO", "BTN", "SB")
FACING = ("vs_open", "vs_3bet_cold", "limp_vs_raise", "call_vs_3bet", "open_vs_3bet",
          "3bet_vs_4bet")


@pytest.fixture(scope="module")
def rules():
    return AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))


def test_every_opponent_plays_legal_repeatable_actions(rules):
    arena = AAFullHandArena(rules)
    bots = [make_policy(name) for name in (*OPPONENT_NAMES, "aa_population")]
    for seed in range(10):
        arena.reset(seed)
        deciders = {seat: bots[(seat + seed) % len(bots)].for_game(f"salt{seat}")
                    for seat in arena.occupied_seats}
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            action = deciders[arena.actor](observation)
            assert action in {a["id"] for a in observation["legal_actions"]}
            assert deciders[arena.actor](arena.observe(arena.actor)) == action
            arena.step(action)


def test_preflop_shares_follow_each_profile():
    for name in POSITIONS:
        players = population_shares(name, "rfi")
        reg = preflop_shares(PROFILES["reg"], name, "rfi")
        maniac = preflop_shares(PROFILES["maniac"], name, "rfi")
        nit = preflop_shares(PROFILES["nit"], name, "rfi")
        assert reg[1] == 0 and nit[1] == 0                 # never limp first in
        assert reg[0] > players[0]                          # its limps raise
        assert maniac[0] > reg[0] > nit[0]
        assert sum(nit) < sum(players) < sum(maniac)
        for spot in FACING:
            three = [preflop_shares(PROFILES[n], name, spot)[0]
                     for n in ("nit", "reg", "maniac")]
            assert three == sorted(three)
            for profile in PROFILES.values():
                assert sum(preflop_shares(profile, name, spot)) <= MAX_CONTINUE + 1e-9


def postflop(to_call, pot, folded=(2, 3, 4, 5, 6, 7)):
    return {"pot": pot, "to_call": to_call, "occupied_seats": list(range(8)),
            "folded": list(folded), "observing_seat": 0}


def test_minimum_defence_against_a_bet():
    assert minimum_defence(postflop("10", "30")) == pytest.approx(2 / 3)  # half pot
    assert minimum_defence(postflop("20", "40")) == pytest.approx(0.5)    # pot
    assert minimum_defence(postflop("0", "20")) == 1.0


def test_regular_bluffs_at_its_ratio_and_defends_heads_up():
    plan = postflop_plan(PROFILES["reg"], postflop("0", "20"), "flop|hu|pfa|checked_to")
    assert plan["bluff"] == pytest.approx(plan["bet"] * 0.4)
    assert plan["bet"] + plan["bluff"] <= 0.75 + 1e-9
    # Facing a pot-sized river bet the players fold 53%; the regular keeps half.
    spot = "river|hu|other|facing_bet"
    plan = postflop_plan(PROFILES["reg"], postflop("20", "40"), spot)
    assert plan["continue"] >= 0.5
    multiway = postflop_plan(PROFILES["reg"], postflop("20", "40", folded=(4, 5, 6, 7)),
                             "river|multi|other|facing_bet")
    assert multiway["continue"] < 0.5                   # no minimum defence there
    assert postflop_plan(PROFILES["nit"], postflop("0", "20"),
                         "flop|hu|pfa|checked_to")["bluff"] == 0


def test_self_play_frequencies_order_the_profiles(rules):
    """Maniac plays and bets most and folds least; the nit the other way."""
    arena = AAFullHandArena(rules)
    names = ("nit", "reg", "maniac")
    bots = {name: make_policy(name) for name in names}
    played, dealt = Counter(), Counter()
    bets, free, folds, facing = Counter(), Counter(), Counter(), Counter()
    for seed in range(300):
        arena.reset(seed)
        seats = arena.occupied_seats
        style = {seat: names[(index + seed) % 3] for index, seat in enumerate(seats)}
        deciders = {seat: bots[style[seat]].for_game(f"f{seed}:{seat}")
                    for seat in seats}
        entered = set()
        while not arena.terminal:
            seat = arena.actor
            observation = arena.observe(seat)
            action = deciders[seat](observation)
            paying = float(observation["to_call"] or 0) > 0
            if observation["street"] == "preflop":
                if action.startswith("raise") or (action == "check_call" and paying):
                    entered.add(seat)
            elif paying:
                facing[style[seat]] += 1
                folds[style[seat]] += action == "fold"
            else:
                free[style[seat]] += 1
                bets[style[seat]] += action.startswith("raise")
            arena.step(action)
        for seat in seats:
            dealt[style[seat]] += 1
            played[style[seat]] += seat in entered
    vpip = [played[n] / dealt[n] for n in names]
    bet = [bets[n] / free[n] for n in names]
    fold = [folds[n] / facing[n] for n in names]
    assert vpip == sorted(vpip) and vpip[0] < 0.16 and vpip[2] > 0.3
    assert bet == sorted(bet)
    assert fold == sorted(fold, reverse=True)


def test_every_pool_member_is_a_policy():
    for name, pool in POOLS.items():
        for member in pool:
            assert make_policy(member).name == member, name
