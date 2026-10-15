"""How much an opponent model plays like the recorded players: the log losses."""

import json
import math
from pathlib import Path

import pytest

from poker_engine.scoreboard.bots import make_policy
from poker_engine.scoreboard.fidelity import (FLOOR, chances, floored, options,
                                              price_bucket, score_hand, summarize)
from poker_engine.scoreboard.strength import DECK
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"


@pytest.fixture(scope="module")
def arena():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    return AAFullHandArena(rules)


def played(arena, seed, first="check_call"):
    """A hand in which the first player to act does ``first`` and everyone
    else checks and calls to the end."""
    arena.reset(seed)
    arena.step(first)
    while not arena.terminal:
        arena.step("check_call")
    return arena.observe(arena.occupied_seats[0])


class Halves:
    """Calls or raises half the time each, whatever the cards."""
    name = "halves"

    def distribution(self, observation, rng):
        return {"c": 0.5, "r": 0.5}


def test_forecasts_are_floored_over_the_open_options(arena):
    arena.reset(3)
    first = arena.observe(arena.actor)
    assert options(first) == ("f", "c", "r")
    mixed = floored({"c": 1.0}, ("f", "c", "r"))
    assert mixed == pytest.approx({"f": FLOOR / 3, "c": 1 - FLOOR + FLOOR / 3,
                                   "r": FLOOR / 3})
    assert sum(mixed.values()) == pytest.approx(1)
    assert [price_bucket(p) for p in (0.1, 0.25, 0.35, 0.5)] == \
        ["small", "medium", "large", "huge"]


def test_a_model_that_plays_as_the_hand_went_loses_only_the_floor(arena):
    observation = played(arena, 5)
    decisions, cards = score_hand(observation, make_policy("always_call"))
    assert len(decisions) == len(observation["public_history"])
    for record in decisions:
        kinds = 3 if record["facing"] else 2
        assert record["loss"] == pytest.approx(-math.log(1 - FLOOR + FLOOR / kinds),
                                               abs=0.01)
        assert not record["impossible"]
    assert cards == []


def test_an_action_the_model_never_takes_is_counted_impossible(arena):
    observation = played(arena, 5, first="fold")
    decisions, _ = score_hand(observation, make_policy("always_call"))
    first = decisions[0]
    assert first["action"] == "f" and first["impossible"]
    assert first["loss"] == pytest.approx(-math.log(FLOOR / 3))
    summary = summarize(decisions)["decisions"]
    assert summary["all"]["impossible"] == 1
    assert summary["preflop|first_in"]["real"]["f"] > 0
    real = [share for share in summary["all"]["real"].values() if share]
    assert summary["all"]["guess"] == pytest.approx(
        -sum(share * math.log(share) for share in real), abs=0.01)


def test_cards_a_model_says_nothing_about_score_zero(arena):
    observation = played(arena, 7)
    seat = observation["occupied_seats"][1]
    free = [card for card in DECK if card not in observation["board"]]
    _, cards = score_hand(observation, make_policy("always_call"),
                          shown={seat: free[:2]})
    assert len(cards) == 1
    assert cards[0]["loss"] == pytest.approx(0, abs=1e-9)
    assert not cards[0]["excluded"]
    summary = summarize([], cards)
    assert summary["cards"]["n"] == 1


def test_a_mixing_model_forecasts_its_mix(arena):
    observation = played(arena, 9)
    decisions, _ = score_hand(observation, Halves())
    assert decisions[0]["forecast"] == {"f": 0.0, "c": 0.5, "r": 0.5}
    assert chances(Halves(), observation, None) == {"c": 0.5, "r": 0.5}
    assert chances(make_policy("always_call"), observation, None) == {"c": 1.0}
