"""Bomb pots: dealt by the arena, replayed for ranges, scored on the scoreboard."""

from decimal import Decimal
import json
from pathlib import Path

import pytest

from poker_engine.scoreboard.bomb import Bomb
from poker_engine.scoreboard.replay import public_replay
from poker_engine.scoreboard.runner import run_scoreboard
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = AARuleProfileV2.from_dict(json.loads(
    (Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json")
    .read_text(encoding="utf-8")))


def test_a_bomb_pot_starts_on_the_flop_with_everyone_in():
    arena = AAFullHandArena(RULES).reset(3, bomb="14")
    observation = arena.observe(arena.actor)
    seats = len(arena.occupied_seats)
    assert observation["street"] == "flop" and len(observation["board"]) == 3
    assert observation["pot"] == str(14 * seats)
    assert set(observation["contributions"].values()) == {"14"}
    assert observation["public_history"] == []
    assert observation["bomb_pot"] == "14" and observation["straddler_seat"] is None
    assert observation["to_call"] == "0"
    while not arena.terminal:
        arena.step("check_call")
    returns = arena.terminal_returns()
    assert -sum(returns.values()) == 5             # 5% of 112, rounded down
    assert sorted(returns.values())[0] == -14


def test_a_normal_hand_is_unchanged_and_says_it_is_no_bomb_pot():
    plain = AAFullHandArena(RULES).reset(3).observe(0)
    assert plain["street"] == "preflop" and plain["bomb_pot"] is None
    assert plain["straddler_seat"] is not None


def test_a_bomb_post_must_leave_chips_behind():
    with pytest.raises(ValueError):
        AAFullHandArena(RULES).reset(3, bomb=str(RULES.big_blind * 100))


def test_bomb_pots_replay_for_ranges():
    arena = AAFullHandArena(RULES).reset(4, bomb="14")
    first = arena.actor
    arena.step("check_call")
    bet = next(a["id"] for a in arena.observe(arena.actor)["legal_actions"]
               if a["kind"] == "raise_to")
    arena.step(bet)
    decisions = public_replay(arena.observe(arena.actor))
    assert [d.seat for d in decisions][0] == first
    assert [d.street for d in decisions] == ["flop", "flop"]
    assert decisions[1].observation["pot"] == str(14 * len(arena.occupied_seats))


def test_bomb_deals_are_fixed_by_the_seed():
    bomb = Bomb(7, 0.5)
    picks = [bomb.chips(seed, Decimal(2)) for seed in range(400)]
    assert picks == [bomb.chips(seed, Decimal(2)) for seed in range(400)]
    assert set(picks) == {None, "14"}
    assert 0.4 < picks.count("14") / 400 < 0.6
    assert all(Bomb(7, 1.0).chips(seed, 2) == "14" for seed in range(50))
    with pytest.raises(ValueError):
        Bomb(7, 0)


def test_runs_split_normal_hands_and_bomb_pots():
    only = run_scoreboard(RULES, ["population"], deals=2, base_seed=1, pool=("nit",),
                          bomb=Bomb(7, 1.0))
    kinds = only["strategies"]["population"]["by_kind"]
    assert kinds["bomb"]["share"] == 1.0 and kinds["normal"]["share"] == 0.0
    assert only["bomb"] == {"post_big_blinds": 7, "share": 1.0}
    plain = run_scoreboard(RULES, ["population"], deals=2, base_seed=1, pool=("nit",))
    assert "by_kind" not in plain["strategies"]["population"] and plain["bomb"] is None
