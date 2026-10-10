"""Playing multiway pots after the flop by equity against every opponent's range."""

import json
from pathlib import Path
import random

import pytest

from poker_engine.scoreboard import multiway_bot
from poker_engine.scoreboard.bots import (_rng, make_policy, opponents_in_hand,
                                          raise_toward)
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


class Base:
    adjusted = True

    def decide(self, observation, rng):
        return "base"


def spots(count=40):
    """Postflop observations from simulated AA hands: (heads-up, heads-up flop
    checked to, multiway checked to, multiway facing a bet)."""
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena, pool = AAFullHandArena(rules), make_policy("aa_population")
    found = {}
    for seed in range(count):
        arena.reset(seed)
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            if observation["street"] != "preflop":
                others = opponents_in_hand(observation)
                price = float(observation["to_call"] or 0)
                kind = ("heads_up" if others == 1 else
                        "facing" if price > 0 else "checked_to")
                found.setdefault(kind, observation)
                if others == 1 and price == 0 and observation["street"] == "flop":
                    found.setdefault("heads_up_flop", observation)
            if len(found) == 4:
                return found
            arena.step(pool.decide(observation, _rng("test", observation)))
    raise AssertionError(f"only found {sorted(found)}")


@pytest.fixture(scope="module")
def table():
    return spots()


def bot_with(monkeypatch, share, **params):
    monkeypatch.setattr(multiway_bot, "opponent_ranges", lambda observation, model: {})
    monkeypatch.setattr(multiway_bot, "ranges_equity",
                        lambda *args, **kwargs: (share, {}))
    return multiway_bot.RangeMultiwayBot(Base(), **params)


def test_only_multiway_pots_after_the_flop_are_played_by_range(monkeypatch, table):
    bot = bot_with(monkeypatch, 0.9)
    assert bot.decide(table["heads_up"], random.Random(0)) == "base"
    assert bot.decide(table["checked_to"], random.Random(0)) != "base"
    assert bot.counts["decided"] == 1


def test_bet_when_ahead_of_the_field_else_check(monkeypatch, table):
    spot = table["checked_to"]
    assert bot_with(monkeypatch, 0.45).decide(spot, random.Random(0)).startswith(
        "raise_to")
    assert bot_with(monkeypatch, 0.35).decide(spot, random.Random(0)).startswith(
        "raise_to")                             # the line is 0.3 since 2026-10-09
    assert bot_with(monkeypatch, 0.25).decide(spot, random.Random(0)) == "check_call"


def test_the_bet_is_the_pot_into_three_or_more_opponents(monkeypatch, table):
    spot = table["checked_to"]
    others = [seat for seat in spot["occupied_seats"]
              if seat != spot["observing_seat"]]
    two = {**spot, "folded": others[2:]}
    three = {**spot, "folded": others[3:]}
    assert opponents_in_hand(two) == 2 and opponents_in_hand(three) == 3
    pot, two_thirds = raise_toward(three, 1.0), raise_toward(two, 0.66)
    assert pot != two_thirds
    assert bot_with(monkeypatch, 0.9).decide(three, random.Random(0)) == pot
    assert bot_with(monkeypatch, 0.9).decide(two, random.Random(0)) == two_thirds
    assert bot_with(monkeypatch, 0.9, size3=0.66).decide(
        three, random.Random(0)) == raise_toward(three, 0.66)


def test_facing_a_bet_raise_call_or_fold_by_the_price(monkeypatch, table):
    spot = table["facing"]
    to_call = float(spot["to_call"])
    price = to_call / (float(spot["pot"]) + to_call)
    assert bot_with(monkeypatch, 0.7).decide(spot, random.Random(0)).startswith(
        "raise_to") or not any(a["kind"] == "raise_to" for a in spot["legal_actions"])
    assert bot_with(monkeypatch, price + 0.01).decide(spot, random.Random(0)) == (
        "check_call")
    assert bot_with(monkeypatch, price - 0.01).decide(spot, random.Random(0)) == "fold"
    assert bot_with(monkeypatch, price + 0.01, margin=0.03).decide(
        spot, random.Random(0)) == "fold"


def test_no_equity_falls_back_to_the_base_policy(monkeypatch, table):
    bot = bot_with(monkeypatch, None)
    assert bot.decide(table["checked_to"], random.Random(0)) == "base"
    assert bot.counts["no_equity"] == 1


def test_parameters_come_with_the_name():
    bot = make_policy("range_multiway@bet=0.4:raise=0.6:margin=0+aa_preflop")
    assert bot.params == {**multiway_bot.DEFAULTS, "bet": 0.4, "raise": 0.6,
                          "margin": 0.0}
    assert bot.name == "range_multiway@bet=0.4:raise=0.6:margin=0+aa_preflop"
    assert make_policy("range_multiway+aa_preflop").params == multiway_bot.DEFAULTS
    with pytest.raises(ValueError):
        make_policy("range_multiway@width=1+aa_preflop")


def test_with_hu_the_heads_up_flop_is_played_with_its_own_cuts(monkeypatch, table):
    spot = table["heads_up_flop"]
    assert bot_with(monkeypatch, 0.9).decide(spot, random.Random(0)) == "base"
    assert bot_with(monkeypatch, 0.6, hu=1).decide(spot, random.Random(0)).startswith(
        "raise_to")
    assert bot_with(monkeypatch, 0.5, hu=1).decide(spot, random.Random(0)) == (
        "check_call")                          # a multiway pot bets from 0.3
    turn = {**spot, "street": "turn"}           # the solver plays heads-up turns
    assert bot_with(monkeypatch, 0.9, hu=1).decide(turn, random.Random(0)) == "base"
    assert multiway_bot.street_params(spot, multiway_bot.DEFAULTS)["bet"] == 0.55
