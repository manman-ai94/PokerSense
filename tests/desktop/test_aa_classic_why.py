"""The default advice's one sentence, three numbers and flip condition
(``aa_classic_why``): every number is the old strategy's own at that decision.

The spots are ``test_plain_policy.spot``'s: 8 seats, dealer 7 (0 small blind,
1 big blind, 2 straddle), 1/2/4(2), 200 each; you are seat 4.
"""

from poker_engine.desktop.aa_classic_advice import ClassicPolicy
from poker_engine.desktop.aa_classic_why import call_limit, facing, spaced
from poker_engine.scoreboard.preflop_policy import Table, multiway
from poker_engine.scoreboard.side_pots import price
from tests.scoreboard.test_plain_policy import spot

POLICY = ClassicPolicy()


def test_after_the_flop_the_numbers_are_the_range_rule_s_own():
    observation = spot({4: "QsQh"}, "AhKd7c", "3f 4r12 5f 6f 7f 0f 1f 2c 2r20")
    report = POLICY.decide(observation)
    why = report["why"]
    assert why["equity"] == report["range_equity"]["value"]
    assert (why["need"], why["need_for"]) == (report["cuts"]["call"], "call")
    assert why["range"].startswith("对手范围约 ") and set(why["range_shares"]) == {"2"}
    assert f"你能赢 {why['equity'] * 100:.0f}%" in why["reason"]
    assert why["reason"].endswith("。") and why["flip"]


def test_a_call_flips_at_the_chips_where_the_price_passes_your_share():
    observation = spot({4: "QsQh"}, "AhKd7c", "3f 4r12 5f 6f 7f 0f 1f 2c 2r20")
    report = POLICY.decide(observation)
    value, cut = report["range_equity"]["value"], report["cuts"]["call"]
    margin = cut - price(observation)
    limit, everything = call_limit(observation, 2,
                                   lambda moved: value >= price(moved) + margin)
    assert not everything
    assert value >= price(facing(observation, limit, 2)) + margin
    assert value < price(facing(observation, limit + 1, 2)) + margin
    action = report["advice"][0]["action"]
    word = "超过" if action in ("call", "raise") else "不到"
    assert f"要跟的{word} {limit:.0f}" in report["why"]["flip"] or action == "raise"


def test_facing_a_bet_moves_the_bettor_s_chips_and_the_pot_together():
    observation = spot({4: "QsQh"}, "AhKd7c", "3f 4r12 5f 6f 7f 0f 1f 2c 2r20")
    moved = facing(observation, 30, 2)
    assert moved["to_call"] == 30 and moved["pot"] == float(observation["pot"]) + 10
    assert moved["bets"]["2"] == float(observation["bets"]["2"]) + 10
    assert moved["stacks"]["2"] == float(observation["stacks"]["2"]) - 10
    assert moved["contributions"]["2"] == float(observation["contributions"]["2"]) + 10


def test_with_nothing_to_call_the_need_is_the_bet_line():
    observation = spot({4: "JsTh"}, "Jd8c2h", "3c 4c 5f 6f 7f 0f 1f 2c 2c 3c")
    report = POLICY.decide(observation)
    why = report["why"]
    assert (why["need"], why["need_for"]) == (report["cuts"]["bet"], "bet")
    assert "下注要" in why["reason"]
    assert why["flip"].startswith("胜率")


def test_before_the_flop_your_share_is_against_the_raiser_s_range_as_priced():
    observation = spot({4: "AhJd"}, "", "3r12")
    report = POLICY.decide(observation)
    why = report["why"]
    table = Table(observation, POLICY.preflop_policy().params,
                  POLICY.preflop_policy().adjusted)
    assert why["equity"] == round(multiway([table.equity(table.band(3))]), 3)
    to_call = float(observation["to_call"])
    assert why["need"] == round(to_call / (float(observation["pot"]) + to_call), 3)
    assert why["range"].startswith("加注的那位范围约 ")
    assert "对他胜率" in why["reason"] and "跟注要" in why["reason"]


def test_a_preflop_fold_or_call_flips_where_aa_preflop_s_call_value_does():
    for hole in ("AhJd", "9h8h", "KsQd", "7c2d"):
        observation = spot({4: hole}, "", "3r12")
        report = POLICY.decide(observation)
        best = report["advice"][0]["action"]
        if best not in ("fold", "call"):
            continue
        policy = POLICY.preflop_policy()
        found = call_limit(observation, 3, lambda moved: Table(
            moved, policy.params, policy.adjusted).call_value() > 0)
        assert found is not None
        flip = report["why"]["flip"]
        if best == "call" and not found[1]:
            assert f"超过 {found[0]:.0f}" in flip or f"超过 {found[0]:.1f}" in flip
        if best == "fold" and found[0] >= 1:
            assert "就跟" in flip


def test_nobody_in_before_you_has_no_range_and_no_price():
    observation = spot({4: "AhKd"}, "", "3f")
    why = POLICY.decide(observation)["why"]
    assert why["range"].startswith("前面没人入池")
    assert why["equity"] is None and why["need"] is None
    assert "值最多" in why["reason"] or "其余都不如" in why["reason"]


def test_numbers_are_spaced_from_the_words():
    assert spaced("范围约36%的牌，跟注4") == "范围约 36% 的牌，跟注 4"
    assert spaced("比跟注 4多赢 1.2 大盲") == "比跟注 4 多赢 1.2 大盲"


def test_a_range_s_share_counts_every_hand_an_opponent_could_hold():
    from poker_engine.desktop.aa_classic_why import range_share
    dead = {"Qs", "Qh", "Ah", "Kd", "7c"}
    assert range_share({"AcAd": 1.0, "KcKs": 0.5}, dead) == 1.5 / (47 * 46 / 2)
    assert range_share({"QsQd": 1.0}, dead) == 0.0          # holds one of your cards
