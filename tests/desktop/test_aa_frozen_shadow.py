import time

import pytest

from poker_engine.desktop.aa_frozen_shadow import AAFrozenShadowSession
from poker_engine.desktop.aa_turn_runtime import (
    AATurnWindow, TurnEvidence, TurnIdentity,
)
from poker_engine.strategy.aa_frozen_policy import information_key, make_policy
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from tools.aa_full_hand_lab import DEFAULT_RULES, rules_for


@pytest.mark.parametrize("version", [1, 2])
def test_arena_to_artifact_to_preloaded_process_keeps_shadow_boundary(version):
    rules = rules_for(DEFAULT_RULES, 8)
    arena = AAFullHandArena(rules).reset(11)
    observation = arena.observe(arena.actor)
    policy = {row["id"]: float(row["id"] == "check_call")
              for row in observation["legal_actions"]}
    encoder, factory = information_key, make_policy
    if version == 2:
        from poker_engine.strategy.aa_frozen_policy_v2 import make_policy_v2
        from poker_engine.strategy.aa_policy_encoding_v2 import information_key_v2
        encoder, factory = information_key_v2, make_policy_v2
    document = factory(
        rules_fingerprint=rules.fingerprint, table_size=8, stack_depth_bb=100,
        policy={encoder(observation): policy},
        training={"kind": "synthetic_wiring_fixture_not_learned"},
    )
    session = AAFrozenShadowSession(document)
    try:
        session.preload()
        now = time.monotonic()
        identity = TurnIdentity("synthetic", 0, "hand", "turn")
        window = AATurnWindow(
            identity, TurnEvidence("synthetic-only", "verified_onset", now, 10),
            now=now,
        )
        fields = dict(identity=identity, window=window, source_at=now,
                      is_current=lambda binding: True, clock=time.monotonic)
        first = session.lookup(observation, **fields)
        assert first["status"] == "SHADOW_RESULT"
        assert first["action"] == "check_call"
        assert not first["strategy_eligible"] and not first["advice_emitted"]
        repeated = session.lookup(observation, **fields)
        assert repeated["request_key"] == first["request_key"]
        observation["simulation_only"] = False
        with pytest.raises(ValueError, match="synthetic"):
            session.lookup(observation, **fields)
    finally:
        session.close()
