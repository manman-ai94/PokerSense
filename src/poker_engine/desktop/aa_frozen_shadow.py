"""End-to-end synthetic frozen-policy adapter, deliberately absent from live UI."""
from poker_engine.strategy.aa_frozen_policy import (
    FrozenResearchPolicy, action_ids, canonical_hash, information_key,
)
from .aa_policy_worker import AAIsolatedPolicyWorker


class AAFrozenShadowSession:
    def __init__(self, artifact, *, seed=0):
        if artifact.get("kind") == "AA_FROZEN_POLICY_V2":
            from poker_engine.strategy.aa_frozen_policy_v2 import FrozenResearchPolicyV2
            from poker_engine.strategy.aa_policy_encoding_v2 import information_key_v2
            self.policy = FrozenResearchPolicyV2(artifact)
            self._information_key = information_key_v2
        else:
            self.policy = FrozenResearchPolicy(artifact)
            self._information_key = information_key
        self.worker = AAIsolatedPolicyWorker(self.policy.frozen_map(), seed=seed)

    def preload(self):
        self.worker.preload()

    def close(self):
        self.worker.close()

    def lookup(self, observation, *, identity, window, source_at,
               is_current, clock):
        if (observation.get("simulation_only") is not True
                or observation.get("strategy_eligible") is not False
                or observation.get("arena_version") != "aa-full-hand-arena-v1"):
            raise ValueError("shadow_adapter_requires_synthetic_arena")
        # Validate artifact scope and menu before dispatch; missing coverage is
        # an abstention, never a default fold or a forced random action.
        distribution = self.policy.distribution(observation)
        if distribution is None:
            return {"status": "ABSTAIN", "reason": "POLICY_COVERAGE_MISS",
                    "action": None, "strategy_eligible": False,
                    "advice_emitted": False}
        return self.worker.lookup(
            self._information_key(observation), identity=identity,
            state_key=canonical_hash(observation),
            rules_fingerprint=observation["rules_fingerprint"],
            legal_actions=action_ids(observation), window=window,
            source_at=source_at, is_current=is_current, clock=clock,
        )
