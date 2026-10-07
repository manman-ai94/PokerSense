"""Replaying public actions rebuilds what every player saw when acting."""

import json
from pathlib import Path

from poker_engine.scoreboard.bots import make_policy
from poker_engine.scoreboard.replay import (kind_of, public_replay, replay_deck,
                                            with_hole)
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v1.json"
PUBLIC = ("street", "board", "board_history", "public_history", "pot", "to_call",
          "bets", "stacks", "folded", "legal_actions", "observing_seat", "actor")


def test_replayed_observations_match_the_ones_seen_in_play():
    rules = AARuleProfileV2.from_dict(json.loads(RULES.read_text(encoding="utf-8")))
    arena = AAFullHandArena(rules)
    bots = [make_policy(name) for name in ("population", "lag", "station")]
    checked = 0
    for seed in range(40):
        arena.reset(seed)
        deciders = {seat: bots[seat % 3].for_game(f"replay{seat}")
                    for seat in arena.occupied_seats}
        seen = []
        while not arena.terminal:
            observation = arena.observe(arena.actor)
            seen.append(observation)
            arena.step(deciders[arena.actor](observation))
        last = seen[-1]
        replayed = public_replay(last)
        assert len(replayed) == len(last["public_history"])
        for decision, original in zip(replayed, seen):
            for key in PUBLIC:
                assert decision.observation[key] == original[key], key
            assert decision.seat == original["observing_seat"]
            checked += 1
    assert checked > 300


def test_the_deck_deals_the_known_board():
    history = [{"street": "flop", "cards": ["As", "Kd", "2c"]},
               {"street": "turn", "cards": ["7h"]}]
    deck = replay_deck(history, 8)
    assert len(deck) == 52 == len(set(deck))
    assert deck[17:20] == ["As", "Kd", "2c"] and deck[21] == "7h"


def test_helpers():
    assert with_hole({"own_hole": ["As", "Ah"], "pot": "9"}, ("Kd", "Kc")) == {
        "own_hole": ["Kd", "Kc"], "pot": "9"}
    kinds = [kind_of(a) for a in ("fold", "check_call", "raise_to:17")]
    assert kinds == ["f", "c", "r"]
