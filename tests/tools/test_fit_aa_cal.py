"""The calibration fit scores hands exactly as the fidelity measure scores aa_cal."""

import json
import math
from pathlib import Path

import pytest

from poker_engine.scoreboard.aa_real import aa_stats
from poker_engine.scoreboard.calibrated import CalibratedBot
from poker_engine.scoreboard.fidelity import score_hand
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2
from tools import fit_aa_cal
from tools.sim_fidelity import log_name

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"
PARAMS = {"mix": 0.1, "price_slope": -1.0,
          "flop": {"slow": 0.3, "bluff": 0.1, "sticky": 0.1},
          "turn": {"slow": 0.4, "bluff": 0.05, "sticky": 0.2},
          "river": {"slow": 0.2, "bluff": 0.15, "sticky": 0.05}}


def heads_up_hand(seed):
    """A hand in which all but the last two fold and those two bet the flop,
    call and check to the showdown; the task ``sim_fidelity`` would make."""
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules)
    arena.reset(seed)
    for _ in range(len(arena.occupied_seats) - 2):
        arena.step("fold")
    holes = {}
    while not arena.terminal:
        observation = arena.observe(arena.actor)
        holes[arena.actor] = observation["own_hole"]
        raises = [action["id"] for action in observation["legal_actions"]
                  if action["kind"] == "raise_to"]
        bet = observation["street"] == "flop" and not float(observation["to_call"] or 0)
        arena.step(raises[0] if bet and raises else "check_call")
    observation = arena.observe(arena.occupied_seats[0])
    return ({"log": "test", "hand_id": seed}, observation, set(), holes, ())


def test_the_fit_and_the_bot_give_the_same_losses():
    stats = aa_stats()
    tasks = [heads_up_hand(seed) for seed in (2, 5)]
    bot = CalibratedBot(params=PARAMS, stats=stats)
    action = cards = 0.0
    decisions = shown = 0
    for where, observation, skip, held, dead in tasks:
        found, seen = score_hand(observation, bot, skip=skip, shown=held, dead=dead)
        action += sum(record["loss"] for record in found)
        cards += sum(record["loss"] for record in seen)
        decisions, shown = decisions + len(found), shown + len(seen)
    hands = [fit_aa_cal.prepare((task, {"v": stats})) for task in tasks]
    fitted = fit_aa_cal.score(hands, PARAMS, "v", stats)
    assert fitted[1] == decisions > 10 and fitted[3] == shown == 4
    assert fitted[0] == pytest.approx(action, abs=1e-6)
    assert fitted[2] == pytest.approx(cards, abs=1e-6)
    assert math.isfinite(fitted[0])


def test_log_names():
    assert log_name("x/20261009-053249-live/frames.jsonl") == "20261009-053249-live"
    assert log_name("x/frames.jsonl.gz") == "x"
    assert log_name("slim/20261009-053249-live.jsonl.gz") == "20261009-053249-live"
