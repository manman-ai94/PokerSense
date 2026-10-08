"""Reads on opponents: measured shares, sampled reads, and how aa_preflop uses them."""

import json
from pathlib import Path

import pytest

from poker_engine.scoreboard.bots import make_policy, raise_toward
from poker_engine.scoreboard.preflop_policy import AAPreflopPolicy, read_shares
from poker_engine.scoreboard.reads import (FACTOR_RANGE, MODEL, READ_PRIOR, factors,
                                           measure, sample)
from poker_engine.scoreboard.runner import play_hand, run_scoreboard
from poker_engine.scoreboard.strength import DECK, class_combos, hand_class
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RAKED = json.loads((Path(__file__).resolve().parents[2]
                    / "configs/game/aa-scoreboard-rules-v2.json").read_text(
                        encoding="utf-8"))
RULES = AARuleProfileV2.from_dict(RAKED)
AA = MODEL["aa_population"]
HANDS = {}
for first in DECK:
    for second in DECK:
        if first != second:
            HANDS.setdefault(hand_class((first, second)), [first, second])


def test_no_read_or_a_read_like_the_model_changes_nothing():
    assert factors(None, AA) == (1.0, 1.0)
    assert factors({"hands": 200, **AA}, AA) == pytest.approx((1.0, 1.0))
    assert read_shares(0.6, 0.5) == (0.6, 0.5)


def test_a_read_is_pulled_toward_the_model_by_the_prior():
    read = {"hands": READ_PRIOR, "vpip": AA["vpip"], "pfr": 3 * AA["pfr"]}
    raise_factor, call_factor = factors(read, AA)
    assert raise_factor == pytest.approx(2.0)       # halfway from 1 to 3
    assert call_factor < 1.0                         # same vpip, more of it raises
    longer = factors({**read, "hands": 20 * READ_PRIOR}, AA)
    assert longer[0] > raise_factor
    assert factors({"hands": 10_000, "vpip": 1.0, "pfr": 1.0}, AA)[0] == FACTOR_RANGE[1]
    assert factors({"hands": 10_000, "vpip": 0.0, "pfr": 0.0}, AA) == (
        FACTOR_RANGE[0], FACTOR_RANGE[0])


def test_scaled_shares_stay_below_the_continue_cap():
    raise_share, call_share = read_shares(0.4, 0.4, (3.0, 3.0))
    assert raise_share + call_share == pytest.approx(0.98)
    assert raise_share == pytest.approx(0.98)


def test_samples_are_reproducible_and_skip_the_hero():
    shares = {"a": {"vpip": 0.5, "pfr": 0.2}, "b": {"vpip": 0.1, "pfr": 0.05}}
    styles = {0: "a", 1: "b", 2: "a"}
    reads = sample(shares, styles, 1, seed=4, hands=2000)
    assert reads == sample(shares, styles, 1, seed=4, hands=2000)
    assert set(reads) == {"0", "2"}
    assert reads["0"]["hands"] == 2000
    assert reads["0"]["vpip"] == pytest.approx(0.5, abs=0.05)
    assert reads["2"]["pfr"] == pytest.approx(0.2, abs=0.05)
    assert reads["0"]["pfr"] <= reads["0"]["vpip"]


def test_measured_shares_tell_tight_and_loose_players_apart():
    shares = measure(RULES, ("nit", "aa_population"), deals=30)
    assert set(shares) == {"nit", "aa_population"}
    assert shares["nit"]["vpip"] < shares["aa_population"]["vpip"]
    for value in shares.values():
        assert 0 <= value["pfr"] <= value["vpip"] <= 1


def facing_an_open(seed=3):
    arena = AAFullHandArena(RULES)
    arena.reset(seed)
    opener = arena.actor
    arena.step(raise_toward(arena.observe(opener), 0.5))
    return opener, arena.observe(arena.actor)


def continued(policy, observation):
    return sum(class_combos(name) for name in HANDS
               if policy.choose({**observation, "own_hole": HANDS[name]})["action"]
               != "fold")


def test_a_wide_raiser_is_played_back_at_more_often():
    opener, facing = facing_an_open()
    policy = AAPreflopPolicy()
    maniac = {str(opener): {"hands": 300, "vpip": 0.5, "pfr": 0.4}}
    rock = {str(opener): {"hands": 300, "vpip": 0.1, "pfr": 0.04}}
    plain = continued(policy, facing)
    assert continued(policy, {**facing, "reads": maniac}) > plain
    assert continued(policy, {**facing, "reads": rock}) < plain


def test_noreads_ignores_the_reads():
    opener, facing = facing_an_open()
    view = {**facing, "own_hole": HANDS["KJo"],
            "reads": {str(opener): {"hands": 300, "vpip": 0.6, "pfr": 0.5}}}
    blind = make_policy("noreads+aa_preflop").for_game("x")
    plain = make_policy("aa_preflop").for_game("x")
    assert blind(view) == plain({k: v for k, v in view.items() if k != "reads"})


def test_only_the_hero_is_given_the_reads():
    arena = AAFullHandArena(RULES)
    seen = []

    def watch(seat):
        def decide(observation):
            seen.append((seat, "reads" in observation))
            return "fold" if observation["to_call"] not in (None, "0") else "check_call"
        return decide

    deciders = {seat: watch(seat) for seat in arena.occupied_seats}
    play_hand(arena, 5, deciders, 2, reads={"1": {"hands": 1, "vpip": 1, "pfr": 0}})
    assert {seat for seat, has in seen if has} <= {2}
    assert all(has for seat, has in seen if seat == 2)


def test_runs_with_reads_say_so():
    report = run_scoreboard(RULES, ["aa_preflop", "noreads+aa_preflop"], deals=2,
                            base_seed=2, pool=("nit",), reads=50)
    assert report["reads"]["hands"] == 50
    assert set(report["reads"]["shares"]) == {"nit"}
    assert run_scoreboard(RULES, ["aa_preflop"], deals=2, base_seed=2,
                          pool=("nit",))["reads"] is None
