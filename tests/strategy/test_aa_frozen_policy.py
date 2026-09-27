from copy import deepcopy
import random

import pytest

from poker_engine.strategy.aa_frozen_policy import (
    FrozenResearchPolicy, canonical_hash, card_bucket, information_key, make_policy,
)
from poker_engine.strategy.aa_jev_shadow import (
    JEV_MODEL, JevShadowAdapter, RecordedJevTransport, synthetic_request,
)


def observation():
    return {"own_hole": ["As", "Kd"], "board": [], "street": "preflop",
            "actor": 3, "observing_seat": 3, "occupied_seats": list(range(6)),
            "dealer_seat": 5, "stacks": {str(i): "200" for i in range(6)},
            "starting_stacks": {str(i): "200" for i in range(6)},
            "straddler_seat": None, "to_call": "2", "rules": {"rake": "0"},
            "arena_version": "aa-full-hand-arena-v1", "simulation_only": True,
            "strategy_eligible": False,
            "bets": {str(i): "0" for i in range(6)}, "folded": [], "pot": "3",
            "public_history": [], "rules_fingerprint": "a" * 64,
            "table_size": 6, "big_blind": "2",
            "legal_actions": [{"id": "fold", "kind": "fold", "raise_to": None},
                              {"id": "check_call", "kind": "check_call",
                               "raise_to": None}]}


def artifact(obs=None):
    obs = obs or observation()
    return make_policy(rules_fingerprint=obs["rules_fingerprint"], table_size=6,
                       stack_depth_bb=100, training={"iterations": 2},
                       policy={information_key(obs): {"fold": 0.0, "check_call": 1.0}})


def test_exact_lookup_and_unknown_abstention_and_scope_refusal():
    policy = FrozenResearchPolicy(artifact())
    obs = observation()
    assert policy.sample(obs, random.Random(1)) == "check_call"
    obs["pot"] = "4"
    assert policy.sample(obs, random.Random(1)) is None
    obs["rules_fingerprint"] = "b" * 64
    with pytest.raises(ValueError, match="scope"):
        policy.sample(obs, random.Random(1))
    with pytest.raises(ValueError, match="live"):
        policy.require_live()


def test_digest_and_rehashed_promotion_both_rejected():
    doc = artifact()
    doc["status"] = "live_approved"
    with pytest.raises(ValueError, match="digest"):
        FrozenResearchPolicy(doc)
    doc.pop("sha256")
    doc["sha256"] = canonical_hash(doc)
    with pytest.raises(ValueError, match="promoted"):
        FrozenResearchPolicy(doc)


def test_observation_cannot_carry_future_or_other_private_cards():
    for key in ("seed", "deck", "future_board", "opponent_hole", "actual_action"):
        obs = observation()
        obs[key] = "forbidden"
        with pytest.raises(ValueError, match="private_or_future"):
            information_key(obs)


def test_preflop_buckets_have_exactly_169_classes():
    ranks = "23456789TJQKA"
    buckets = set()
    for a in ranks:
        for b in ranks:
            buckets.add(card_bucket([a + "s", b + "h"], []))
            if a != b:
                buckets.add(card_bucket([a + "s", b + "s"], []))
    assert buckets == set(range(169))


def test_nested_future_labels_and_out_of_scope_depth_are_refused():
    obs = observation()
    obs["public_history"] = [{"future_board": ["2s"]}]
    with pytest.raises(ValueError, match="future"):
        information_key(obs)
    obs = observation()
    obs["starting_stacks"]["0"] = "100"
    with pytest.raises(ValueError, match="stack_scope"):
        FrozenResearchPolicy(artifact()).distribution(obs)


def response():
    return {"model": JEV_MODEL, "usage": {"input_tokens": 20},
            "answers": {"action": {"type": "choice", "choice": "check_call",
                                   "probabilities": {"fold": 0.2, "check_call": 0.8}}}}


def test_recorded_jev_transport_never_needs_network_and_retains_receipt():
    payload = synthetic_request(observation(), provenance="AA_ARENA_SYNTHETIC_V1")
    transport = RecordedJevTransport({canonical_hash(payload): response()})
    adapter = JevShadowAdapter(transport, max_calls=1)
    assert adapter.decide(observation(), provenance="AA_ARENA_SYNTHETIC_V1") == (
        "check_call")
    assert adapter.receipts[0]["raw_response"] == response()
    assert adapter.receipts[0]["strategy_eligible"] is False
    with pytest.raises(ValueError, match="budget"):
        adapter.decide(observation(), provenance="AA_ARENA_SYNTHETIC_V1")


@pytest.mark.parametrize("failure", ["model", "mass", "illegal", "choice"])
def test_jev_rejects_drift_and_invalid_actions_without_repairs(failure):
    raw = deepcopy(response())
    answer = raw["answers"]["action"]
    if failure == "model":
        raw["model"] = "jev-latest"
    elif failure == "mass":
        answer["probabilities"]["fold"] = 0.8
    elif failure == "illegal":
        answer["probabilities"] = {"allin": 1.0}
    else:
        answer["choice"] = "fold"
    adapter = JevShadowAdapter(lambda payload: raw)
    with pytest.raises(ValueError):
        adapter.decide(observation(), provenance="AA_ARENA_SYNTHETIC_V1")
    assert adapter.receipts[0]["status"] == "ERROR"


def test_jev_never_discards_abstention_mass_or_accepts_real_provenance():
    raw = response()
    raw["answers"]["action"].update(
        choice="__insufficient_evidence__",
        probabilities={"fold": 0.1, "check_call": 0.1,
                       "__insufficient_evidence__": 0.8},
    )
    adapter = JevShadowAdapter(lambda payload: raw)
    assert adapter.decide(observation(), provenance="AA_ARENA_SYNTHETIC_V1") is None
    with pytest.raises(ValueError, match="synthetic"):
        adapter.decide(observation(), provenance="live")
