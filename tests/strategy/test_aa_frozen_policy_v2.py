from copy import deepcopy
import random

import pytest

pytest.importorskip("pokerkit")

from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena  # noqa: E402
from poker_engine.strategy.aa_frozen_policy import canonical_hash  # noqa: E402
from poker_engine.strategy.aa_frozen_policy_v2 import (  # noqa: E402
    FrozenResearchPolicyV2, make_policy_v2,
)
from poker_engine.strategy.aa_policy_encoding_v2 import (  # noqa: E402
    ENCODER_VERSION_V2, information_key_v2,
)
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2  # noqa: E402


def arena(n=6, seed=13):
    rule = AARuleProfileV2.from_dict({
        "schema_version": 2, "table_size": n, "small_blind": "1", "big_blind": "2",
        "ante": "0", "ante_mode": "none", "straddle_mode": "none",
        "straddle_amount": "0", "rake_percent": "0", "rake_cap_bb": "0",
        "rake_application": "all_pots", "rake_rounding": "exact",
        "rake_distribution": "proportional_all_pots", "minimum_chip": "1",
        "verification_status": "simulation", "source": "synthetic-v2-policy-test",
    })
    return AAFullHandArena(rule).reset(seed)


def artifact(obs=None):
    game = arena()
    obs = obs or game.observe(game.actor)
    return make_policy_v2(
        rules_fingerprint=obs["rules_fingerprint"], table_size=obs["table_size"],
        stack_depth_bb=100, training={"iterations": 2, "scope": "SYNTHETIC_TEST"},
        policy={information_key_v2(obs): {
            row["id"]: float(row["id"] == "check_call")
            for row in obs["legal_actions"]}},
    )


def rehash(document):
    document.pop("sha256")
    document["sha256"] = canonical_hash(document)
    return document


@pytest.mark.parametrize("n", [6, 7, 8])
def test_real_frozen_asset_completes_predeclared_checkcall_full_hand(n):
    original = arena(n)
    collect = original.clone()
    table = {}
    streets = set()
    while not collect.terminal:
        obs = collect.observe(collect.actor)
        streets.add(obs["street"])
        table[information_key_v2(obs)] = {
            row["id"]: float(row["id"] == "check_call") for row in obs["legal_actions"]}
        collect.step("check_call")
    document = make_policy_v2(
        rules_fingerprint=original.rules.fingerprint, table_size=n,
        stack_depth_bb="100.00", policy=table,
        training={"purpose": "KNOWN_SCRIPT_POSITIVE_CONTROL_NOT_LEARNED"},
    )
    frozen = FrozenResearchPolicyV2(document)
    decide = frozen.for_game("f" * 64)
    while not original.terminal:
        obs = original.observe(original.actor)
        lookup = frozen.inspect_lookup(obs)
        assert lookup["status"] == "HIT"
        assert lookup["encoder"] == ENCODER_VERSION_V2
        assert lookup["encoder_version"] == ENCODER_VERSION_V2
        assert lookup["information_key"] == lookup["abstract_key"]
        assert lookup["exact_key"] != lookup["abstract_key"]
        assert lookup["features"]["street"] == original.street
        assert decide(obs) == decide(obs) == "check_call"
        original.step(decide(obs))
    assert streets == {"preflop", "flop", "turn", "river"}
    assert original.terminal_result() == collect.terminal_result()
    assert document["strategy_eligible"] is document["advice_emitted"] is False


def test_lookup_hit_miss_scope_and_invalid_menu_remain_distinct():
    game = arena()
    obs = game.observe(game.actor)
    frozen = FrozenResearchPolicyV2(artifact(obs))
    assert frozen.sample(obs, random.Random(1)) == "check_call"
    assert frozen.inspect_lookup(obs)["status"] == "HIT"
    changed = deepcopy(obs)
    changed["pot"] = "123"
    result = frozen.inspect_lookup(changed)
    assert result["status"] == "UNKNOWN_INFORMATION_SET"
    assert result["distribution"] is None
    assert result["abstract_key"] is not None
    assert result["information_key"] == result["abstract_key"]
    assert frozen.distribution(changed) is None
    with pytest.raises(ValueError, match="unknown_policy_information_set"):
        frozen.for_game("a" * 64)(changed)
    changed["rules_fingerprint"] = "f" * 64
    assert frozen.inspect_lookup(changed)["status"] == "SCOPE_MISMATCH"
    with pytest.raises(ValueError, match="scope"):
        frozen.distribution(changed)
    changed = deepcopy(obs)
    changed["legal_actions"].append(changed["legal_actions"][0])
    assert frozen.inspect_lookup(changed)["status"] == "INVALID_MENU"
    changed = deepcopy(obs)
    changed.pop("board_history")
    assert frozen.inspect_lookup(changed)["status"] == "INVALID_OBSERVATION"


@pytest.mark.parametrize("salt", [
    None, True, False, 1, 1.0, "a" * 63, "a" * 65,
    "g" * 64, "a" * 64 + "\n", " " * 64, "A" * 64, "Ab" * 32,
])
def test_game_salt_requires_exact_64_hex_string(salt):
    with pytest.raises(ValueError, match="independent_policy_salt"):
        FrozenResearchPolicyV2(artifact()).for_game(salt)


def test_canonical_salt_game_choice_is_stable():
    game = arena()
    obs = game.observe(game.actor)
    doc = artifact(obs)
    ids = [row["id"] for row in obs["legal_actions"]]
    doc["policy"][information_key_v2(obs)] = {action: 1 / len(ids) for action in ids}
    frozen = FrozenResearchPolicyV2(rehash(doc))
    assert len({frozen.for_game("ab" * 32)(obs) for _ in range(10)}) == 1


@pytest.mark.parametrize("field,value", [
    ("encoder", "aa_rank_texture_v1"), ("schema_version", 1),
    ("kind", "AA_FROZEN_POLICY_V1"), ("status", "live_approved"),
    ("strategy_eligible", True), ("advice_emitted", True),
    ("unknown_history", "fold"), ("live_admission", "APPROVED"),
    ("abstraction", "exact poker equivalence"),
])
def test_rehashed_wrong_version_or_promotion_is_rejected(field, value):
    doc = artifact()
    doc[field] = value
    with pytest.raises(ValueError, match="unsupported_or_promoted"):
        FrozenResearchPolicyV2(rehash(doc))


def test_wrong_depth_and_tampered_action_menu_are_refused():
    game = arena()
    obs = game.observe(game.actor)
    frozen = FrozenResearchPolicyV2(artifact(obs))
    changed = deepcopy(obs)
    changed["starting_stacks"]["0"] = "300"
    assert frozen.inspect_lookup(changed)["status"] == "SCOPE_MISMATCH"
    doc = artifact(obs)
    doc["policy"][information_key_v2(obs)] = {"check_call": 1.0}
    frozen = FrozenResearchPolicyV2(rehash(doc))
    assert frozen.inspect_lookup(obs)["status"] == "INVALID_MENU"
    with pytest.raises(ValueError, match="menu_mismatch"):
        frozen.distribution(obs)


def test_maps_reports_and_original_document_are_detached():
    game = arena()
    obs = game.observe(game.actor)
    doc = artifact(obs)
    frozen = FrozenResearchPolicyV2(doc)
    doc["policy"].clear()
    frozen.frozen_map().clear()
    report = frozen.inspect_lookup(obs)
    report["distribution"]["fold"] = 8
    report["features"]["stacks"].clear()
    assert frozen.inspect_lookup(obs)["distribution"]["fold"] == 0
    with pytest.raises(ValueError, match="no_live_admission"):
        frozen.require_live()
    with pytest.raises(ValueError, match="independent_evaluation_salt"):
        frozen(obs)
