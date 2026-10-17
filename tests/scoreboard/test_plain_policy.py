"""一页纸打法 ``plain``（《一页纸打法 v3.3c》）：每条规则至少一个用例。

牌局都是合成的：按指定的牌发牌（``spot``），在 AA 8 人桌上照写好的动作走到要测的那一步，
再看 ``plain`` 的建议。8 人桌：0 小盲、1 大盲、2 抓头、3 早位、4 和 5 中位、6 CO、7 庄位；
翻前 3 先说，翻后 0 先说。每人前注 2、盲注 1/2、抓头 4，默认筹码 200（100 个大盲）。
"""

import json
from pathlib import Path
import re

import pytest

from poker_engine.scoreboard import plain_policy as plain
from poker_engine.scoreboard.bots import make_policy
from poker_engine.scoreboard.runner import run_scoreboard
from poker_engine.scoreboard.strength import DECK
from poker_engine.strategy.aa_full_hand_arena import AAFullHandArena
from poker_engine.strategy.aa_rules_v2 import AARuleProfileV2

RULES = Path(__file__).resolve().parents[2] / "configs/game/aa-scoreboard-rules-v2.json"
RULES_DICT = json.loads(RULES.read_text(encoding="utf-8"))
PROFILE = AARuleProfileV2.from_dict(RULES_DICT)
HU = "3f 4f 5f 6f 7r23 0f 1f 2c"            # 庄位开 23，抓头跟：翻牌单挑，底池 65
THREE_WAY = "3f 4f 5f 6f 7r23 0f 1c 2c"     # 大盲、抓头跟：翻牌 3 人，底池 86
FOUR_WAY = "3f 4f 5f 6r23 7c 0f 1c 2c"      # CO 开，庄位、大盲、抓头跟：翻牌 4 人，底池 109


def cards(text):
    text = text.replace(" ", "")
    return [text[i:i + 2] for i in range(0, len(text), 2)]


def spot(holes, board="", actions="", *, seats=8, stacks=None, bomb=None,
         mushroom=None):
    """按 ``holes``（{座位: "AsKs"}）和 ``board`` 发牌，走完 ``actions``（"3f" 弃、"2c"
    过牌或跟注、"7r23" 加注到 23；数字是座位，每一步核对轮到的是他），返回轮到的人看到的。"""
    profile = AARuleProfileV2.from_dict(RULES_DICT | {"table_size": seats})
    arena = AAFullHandArena(profile, occupied_seats=list(range(seats)))
    holes = {seat: cards(text) for seat, text in holes.items()}
    board = cards(board)
    used = {card for hole in holes.values() for card in hole} | set(board)
    rest = [card for card in DECK if card not in used]
    deck = []
    for seat in arena._seats:                 # 小盲先拿牌，庄位最后
        deck += holes.get(seat) or [rest.pop(), rest.pop()]
    board += [rest.pop() for _ in range(5 - len(board))]
    deck += [rest.pop(), *board[:3], rest.pop(), board[3], rest.pop(), board[4], *rest]
    if isinstance(stacks, int):
        stacks = dict.fromkeys(range(seats), stacks)
    arena.reset(0, deck=deck, bomb=bomb, stacks=stacks)
    for token in actions.split():
        if "r" in token:
            seat, amount = token.split("r")
            move = f"raise_to:{amount}"
        else:
            seat, move = token[:-1], {"f": "fold", "c": "check_call"}[token[-1]]
        assert arena.actor == int(seat), (token, arena.actor)
        arena.step(move)
    observation = arena.observe(arena.actor)
    if mushroom is not None:
        observation["mushroom_pool"] = mushroom
    return observation


def decide(*args, **kwargs):
    return plain.decide(spot(*args, **kwargs))


@pytest.fixture
def equity_is(monkeypatch):
    """把对范围的胜率定死（这些用例测的是规则，不是胜率怎么算）。"""
    def fix(value):
        monkeypatch.setattr(plain, "equity", lambda *args, **kwargs: value)
    return fix


# -- 定义：手牌写法、位置按座位数 ----------------------------------------------

def test_hands_are_written_like_the_page():
    assert plain.hands("77+") == {"77", "88", "99", "TT", "JJ", "QQ", "KK", "AA"}
    assert plain.hands("22-44") == {"22", "33", "44"}
    assert plain.hands("A2s-A5s") == {"A2s", "A3s", "A4s", "A5s"}
    assert plain.hands("65s-98s") == {"65s", "76s", "87s", "98s"}
    assert plain.hands("AJs+") == {"AJs", "AQs", "AKs"}
    assert plain.hands("KTo+") == {"KTo", "KJo", "KQo"}
    assert plain.hands("AK") == {"AKs", "AKo"}
    assert plain.hands("AQ+") == {"AQs", "AQo", "AKs", "AKo"}
    assert "TT" in plain.FLAT and "JJ" in plain.FLAT and "99" not in plain.FLAT
    assert plain.hands("54s-T9s") == plain.hands("54s 65s 76s 87s 98s T9s")
    assert plain.hands("75s-J9s") == plain.hands("75s 86s 97s T8s J9s")
    assert plain.hands("KTs-KJs") == {"KTs", "KJs"}


def test_speculative_hands_are_defined_once():
    # 所有对子、所有同花 A、K5s+、同花连张和隔张 54s+（含 75s、86s、97s、T8s、J9s、Q9s）、
    # 两张 T 以上（同花不同花都算）、A8o+
    spec = plain.SPECULATIVE
    assert {"22", "A2s", "K5s", "54s", "75s", "Q9s", "JTo", "KTo", "A8o"} <= spec
    assert not {"K4s", "64s", "53s", "A7o", "K9o", "J9o", "T9o", "Q8s"} & spec
    assert plain.TABLE1["middle"]["limp"] == spec
    # 晚位平跟再加 Q8s、J8s、T8s、97s、86s、75s、A2o+、K9o+、Q9o+（v3.3a 撤回了 v3.3 的再放宽）
    assert plain.TABLE1["late"]["limp"] - spec == plain.hands(
        "Q8s J8s A2o-A7o K9o Q9o")


@pytest.mark.parametrize("seats, expected", [
    (8, "blind blind blind early middle middle late late"),
    (7, "blind blind blind middle middle late late"),
    (6, "blind blind blind middle late late"),
    (5, "blind blind blind late late"),
    (4, "blind blind blind late"),
])
def test_positions_follow_the_number_of_seats(seats, expected):
    found = plain.seat_classes(spot({}, seats=seats))
    assert [found[seat][0] for seat in range(seats)] == expected.split()
    assert found[0][1] == "SB" and found[1][1] == "BB" and found[2][1] == "STR"
    assert found[seats - 1][1] == "BTN"
    if seats >= 5:
        assert found[seats - 2][1] == "CO"


# -- 表 1 · 没人加注时 -------------------------------------------------------------

@pytest.mark.parametrize("actions, hand, action, to, rule", [
    ("", "AsJs", "raise", 23, "T1.raise"),               # 早位表内：开到底池 23
    ("", "6c6d", "raise", 23, "T1.raise"),               # v3.2 早位宽一档：66+、ATs+、AJo+
    ("", "AsTs", "raise", 23, "T1.raise"),
    ("", "AcJd", "raise", 23, "T1.raise"),
    ("", "Ac7d", "fold", None, "T1.out"),                 # 加注表、平跟表都不在
    ("", "5c5d", "call", None, "T1.limp"),                # 早位平跟：对子、同花 A
    ("", "As9s", "call", None, "T1.limp"),
    ("", "7s6s", "call", None, "T1.limp"),                # 同花连张 65s+
    ("", "KsJs", "call", None, "T1.limp"),                # 两张 T 以上的同花
    ("", "9s7s", "fold", None, "T1.out"),                 # 隔张不在早位平跟表里
    ("", "KcJd", "fold", None, "T1.out"),
    ("3f", "KcQd", "raise", 23, "T1.raise"),              # 中位
    ("3f", "4c4d", "raise", 23, "T1.raise"),              # v3.2 中位：44+、A9s+、ATo+
    ("3f", "AcTd", "raise", 23, "T1.raise"),
    ("3f", "3c3d", "call", None, "T1.limp"),              # 首个入池也可以平跟
    ("3f", "Ks5s", "call", None, "T1.limp"),              # 投机牌全部
    ("3f", "Ac8d", "call", None, "T1.limp"),
    ("3f", "Kc9d", "fold", None, "T1.out"),
    ("3c", "6s5s", "call", None, "T1.limp"),
    ("3c", "KcQd", "raise", 27, "T1.iso1"),               # 隔离 1 个平跟者：底池 27
    ("3f 4f 5f", "Ac9d", "raise", 23, "T1.raise"),        # 晚位
    ("3f 4f 5f", "Ac8d", "raise", 23, "T1.raise"),        # v3.2 晚位加 A8o+
    ("3f 4f 5f", "7s6s", "call", None, "T1.limp"),
    ("3f 4f 5f", "Ks8s", "call", None, "T1.limp"),
    ("3f 4f 5f", "Ac2d", "call", None, "T1.limp"),        # 晚位平跟再加 A2o+、K9o+、Q9o+
    ("3f 4f 5f", "Qc9d", "call", None, "T1.limp"),
    ("3f 4f 5f", "Js8s", "call", None, "T1.limp"),
    ("3f 4f 5f", "8c7d", "fold", None, "T1.out"),
    ("3f 4f 5f", "Jc9d", "fold", None, "T1.out"),         # v3.3a 撤回晚位再放宽
    ("3f 4f 5f", "Ks2s", "fold", None, "T1.out"),
    ("3f 4f 5f", "4s3s", "fold", None, "T1.out"),
    ("3f 4f 5f", "Kc8d", "fold", None, "T1.out"),
    ("3c 4f 5f", "7s6s", "call", None, "T1.limp"),
    ("3c 4c 5f", "TcTd", "raise", 31, "T1.iso2"),         # ≥ 2 个平跟者：TT+ 隔离，底池 31
    ("3c 4c 5f", "KsQs", "raise", 31, "T1.iso2"),
    ("3c 4c 5f", "Ac9d", "call", None, "T1.limp"),        # 加注表里、隔离表外：平跟
    ("3c 4c 5f", "AcJd", "call", None, "T1.limp"),
])
def test_table_1(actions, hand, action, to, rule):
    seat = 3 + len(actions.split())
    advice = decide({seat: hand}, actions=actions)
    assert (advice.action, advice.to, advice.rule) == (action, to, rule)


def test_open_is_capped_at_a_fifth_of_the_effective_stack():
    advice = decide({3: "AsJs"}, stacks=100)                  # 有效 100 → 封顶 20
    assert (advice.action, advice.to, advice.rule) == ("raise", 20, "T1.raise")


def test_preflop_raises_are_not_turned_into_all_in():
    # 筹码 30：开到 8 后剩 20 ≤ 底池 31。v3.2 直接全下只管 A 档、表 3 和推弃表：照表加
    advice = decide({3: "AsJs"}, stacks=30)
    assert (advice.action, advice.to, advice.rule) == ("raise", 8, "T1.raise")
    assert "J1" not in advice.hits and not advice.all_in


@pytest.mark.parametrize("actions, hand, action, to", [
    ("3c 4f 5f 6f 7f 0f 1f", "KcQd", "raise", 27),        # 1 个平跟者：底池 27
    ("3c 4f 5f 6f 7f 0f 1f", "Kc9d", "check", None),
    ("3c 4c 5f 6f 7f 0f 1f", "KcQd", "raise", 31),        # 不管几个平跟者（v3.2 这里过牌）
    ("3c 4c 5c 6f 7f 0f 1f", "2c2d", "raise", 35),
    ("3c 4c 5c 6f 7f 0f 1f", "Ac8d", "raise", 35),
    ("3c 4c 5c 6f 7f 0c 1c", "Ks9s", "raise", 40),        # 盲位也补齐了：底池 40
    ("3c 4c 5c 6f 7f 0f 1f", "Ac7d", "check", None),
    ("3c 4c 5c 6f 7f 0f 1f", "8s3s", "check", None),
])
def test_straddle_raises_limpers_with_the_late_chart_else_checks(
        actions, hand, action, to):
    advice = decide({2: hand}, actions=actions)
    rule = "T1.str" if action == "raise" else "T1.straddle"
    assert (advice.action, advice.to, advice.rule) == (action, to, rule)
    assert advice.unspecified is None


def test_straddle_raise_is_capped_at_a_fifth_of_the_effective_stack():
    advice = decide({2: "AcKd"}, actions="3c 4c 5c 6f 7f 0f 1f", stacks=100)
    assert (advice.action, advice.to, advice.rule) == ("raise", 20, "T1.str")


# -- 盲位三种情形 ----------------------------------------------------------------------

@pytest.mark.parametrize("actions, seat, hand, action, to, rule", [
    # a. 小盲、大盲面对只有平跟者、这手不隔离：补齐到抓头（大盲付 2、小盲付 3），其余弃
    ("3c 4c 5f 6f 7f", 0, "Ks9s", "call", None, "T1.a"),
    # 小盲：+ A2o+、K9o+、Q9o+、JTo（v3.3a 撤回 v3.3 的再放宽，回到 v3.2 的表）
    ("3c 4c 5f 6f 7f", 0, "Ac2d", "call", None, "T1.a"),
    ("3c 4c 5f 6f 7f", 0, "Js8s", "fold", None, "T1.a.fold"),
    ("3c 4c 5f 6f 7f", 0, "Jc9d", "fold", None, "T1.a.fold"),
    ("3c 4c 5f 6f 7f", 0, "Ks2s", "fold", None, "T1.a.fold"),
    ("3c 4c 5f 6f 7f", 0, "Kc8d", "fold", None, "T1.a.fold"),
    ("3c 4c 5f 6f 7f", 0, "QcQd", "raise", 31, "T1.iso2"),
    # 大盲：+ 两张 8 以上的同花、A2o+、K9o+、Q9o+、J9o+、T9o（v3.3a 回到 v3.2 的表）
    ("3c 4c 5f 6f 7f 0f", 1, "Js8s", "call", None, "T1.a"),
    ("3c 4c 5f 6f 7f 0f", 1, "Jc9d", "call", None, "T1.a"),
    ("3c 4c 5f 6f 7f 0f", 1, "Tc9d", "call", None, "T1.a"),
    ("3c 4c 5f 6f 7f 0f", 1, "8c3d", "fold", None, "T1.a.fold"),
    ("3c 4c 5f 6f 7f 0f", 1, "4s3s", "fold", None, "T1.a.fold"),
    ("3c 4c 5f 6f 7f 0f", 1, "Kc7d", "fold", None, "T1.a.fold"),
    ("3c 4c 5f 6f 7f 0f", 1, "9c7d", "fold", None, "T1.a.fold"),
    ("3c 4c 5f 6f 7f 0c", 1, "7s3s", "fold", None, "T1.a.fold"),
    # b. 小盲、大盲面对 1 个平跟者：中位加注表隔离，不在表内按 a 补齐
    ("3c 4f 5f 6f 7f", 0, "AcTd", "raise", 27, "T1.b"),
    ("3c 4f 5f 6f 7f", 0, "Ks9s", "call", None, "T1.a"),
    ("3c 4f 5f 6f 7f", 0, "8c3d", "fold", None, "T1.a.fold"),
    ("3c 4f 5f 6f 7f 0f", 1, "4c4d", "raise", 27, "T1.b"),
    ("3c 4f 5f 6f 7f 0f", 1, "Tc9d", "call", None, "T1.a"),
    # c. 前面全弃到盲位：晚位加注表开到 1 倍底池，其余按 a 补齐；抓头面对补齐其余过牌
    ("3f 4f 5f 6f 7f", 0, "Ks9s", "raise", 23, "T1.c"),
    ("3f 4f 5f 6f 7f", 0, "Kc9d", "call", None, "T1.a"),
    ("3f 4f 5f 6f 7f", 0, "7c2d", "fold", None, "T1.a.fold"),
    ("3f 4f 5f 6f 7f 0c", 1, "Ac8d", "raise", 26, "T1.c"),     # 大盲面对小盲补齐
    ("3f 4f 5f 6f 7f 0c", 1, "Jc9d", "call", None, "T1.a"),
    ("3f 4f 5f 6f 7f 0c", 1, "8c3d", "fold", None, "T1.a.fold"),
    ("3f 4f 5f 6f 7f 0f", 1, "Q9s", "raise", 23, "T1.c"),      # 小盲弃了：按小盲那一行
    ("3f 4f 5f 6f 7f 0f", 1, "Qc9d", "call", None, "T1.a"),
    ("3f 4f 5f 6f 7f 0c 1c", 2, "Ks9s", "raise", 28, "T1.c"),  # 抓头面对补齐
    ("3f 4f 5f 6f 7f 0c 1c", 2, "Kc9d", "check", None, "T1.straddle"),
    ("3f 4f 5f 6f 7f 0f 1c", 2, "8c3d", "check", None, "T1.straddle"),
])
def test_the_three_blind_cases(actions, seat, hand, action, to, rule):
    if len(hand) == 3:
        hand = f"{hand[0]}s{hand[1]}s"
    advice = decide({seat: hand}, actions=actions)
    assert (advice.action, advice.to, advice.rule) == (action, to, rule)
    assert advice.unspecified is None


@pytest.mark.parametrize("actions, seat", [
    ("3f 4f 5f 6f 7f", 0), ("3c 4f 5f 6f 7f", 0), ("3c 4c 5f 6f 7f 0f", 1),
    ("3f 4f 5f 6f 7f 0c", 1), ("3c 4f 5f 6f 7f 0c 1c", 2)])
def test_iron_law_5_never_decides_a_blind_nobody_raised(actions, seat):
    for hand in ("AcKd", "QsQd", "Ks9s", "8c3d", "7c2d", "6s5s", "Tc9d", "Jc8d"):
        advice = decide({seat: hand}, actions=actions)
        assert advice.rule != "I5" and advice.unspecified is None, hand
        assert advice.action != "fold" or advice.rule == "T1.a.fold"


# -- 蘑菇池：小盲专用 ---------------------------------------------------------------

def test_small_blind_isolates_with_the_late_chart_when_the_pool_is_10_bb():
    one = "3c 4f 5f 6f 7f"
    advice = decide({0: "Ks9s"}, actions=one, mushroom=24)            # 12 个大盲
    assert (advice.action, advice.to, advice.rule) == ("raise", 27, "M.iso")
    advice = decide({0: "Ks9s"}, actions=one)                         # 没有池：情形 b → a
    assert (advice.action, advice.rule) == ("call", "T1.a")
    advice = decide({0: "Ks9s"}, actions=one, mushroom=18)            # 9 个大盲：不算
    assert (advice.action, advice.rule) == ("call", "T1.a")
    advice = decide({0: "8c3d"}, actions=one, mushroom=24)            # 不隔离：按 a
    assert (advice.action, advice.rule) == ("fold", "T1.a.fold")


def test_small_blind_adds_small_pairs_and_suited_aces_at_20_bb():
    two = "3c 4c 5f 6f 7f"
    advice = decide({0: "As5s"}, actions=two, mushroom=24)
    assert (advice.action, advice.rule) == ("call", "T1.a")
    advice = decide({0: "As5s"}, actions=two, mushroom=40)
    assert (advice.action, advice.to, advice.rule) == ("raise", 31, "M.iso")


def test_the_pool_counts_only_for_the_small_blind():
    advice = decide({1: "Ks9s"}, actions="3c 4f 5f 6f 7f 0f", mushroom=40)
    assert (advice.action, advice.rule) == ("call", "T1.a")
    observation = spot({1: "Ks9s"}, actions="3c 4f 5f 6f 7f 0f", mushroom=40)
    assert plain.Table(observation).mushroom == 0


def test_small_blind_price_call_goes_to_20_percent_with_the_pool():
    # 3 号加到 40、4 号跟：小盲跟 39，有效 200 的 15% 是 30、20% 是 40
    actions = "3r40 4c 5f 6f 7f"
    advice = decide({0: "7c7d"}, actions=actions, mushroom=40)
    assert (advice.action, advice.rule) == ("call", "T2.price")
    advice = decide({0: "7c7d"}, actions=actions)
    assert (advice.action, advice.rule) == ("fold", "T2.fold")


def test_small_blind_counts_the_whole_pool_in_the_price():
    # 小盲翻牌过牌，3 号下 30、4 号弃：跟 30 赢 91 + 30 + 30，蘑菇池 40 全额算进去
    without = spot({0: "7c7d"}, "Kh Tc 2d", "3r23 4c 5f 6f 7f 0c 1f 2f 0c 3r30 4f")
    assert plain.Table(without).need() == pytest.approx(30 / 151)
    pooled = dict(without, mushroom_pool=40)
    assert plain.Table(pooled).need() == pytest.approx(30 / 191)
    small = dict(without, mushroom_pool=18)                 # 不到 10 个大盲：不算
    assert plain.Table(small).need() == pytest.approx(30 / 151)


def test_small_blind_bets_a_third_once_on_the_flop_with_two_opponents():
    actions = "3r23 4c 5f 6f 7f 0c 1f 2f"        # 小盲看价格跟，3 人看翻牌
    advice = decide({0: "7c7d"}, "Ah Kc 2d", actions, mushroom=40)
    assert (advice.action, advice.rule) == ("bet", "M.flop")
    assert advice.to == pytest.approx(91 / 3, abs=1)        # 底池 91 的 1/3
    advice = decide({0: "7c7d"}, "Ah Kc 2d", actions)
    assert (advice.action, advice.rule) == ("check", "N.C")


# -- 表 2 · 面对一次加注 -------------------------------------------------------------

@pytest.mark.parametrize("actions, seat, hand, action, to, rule", [
    ("3r23", 4, "QcQd", "raise", 69, "T2.3bet"),          # 3 倍加注额
    ("3r23", 4, "AcKd", "raise", 69, "T2.3bet"),
    ("3r23", 4, "JcJd", "call", None, "T2.call"),         # JJ 只在面对晚位时再加注
    ("3f 4f 5f 6r23", 7, "JcJd", "raise", 69, "T2.3bet"),
    ("3f 4f 5f 6r23", 7, "AsQs", "raise", 69, "T2.3bet"),
    ("3r23", 4, "TcTd", "call", None, "T2.call"),
    ("3r23", 4, "AcQd", "call", None, "T2.call"),
    ("3r23", 4, "AsTs", "call", None, "T2.call"),
    ("3r23 4f 5f 6f", 7, "7c7d", "call", None, "T2.price"),   # 有位置、≤ 15%
    ("3r23 4c", 5, "6s5s", "call", None, "T2.price"),         # 已有人跟
    ("3r23 4c", 5, "5s4s", "call", None, "T2.price"),         # v3.2 加 54s、同花 A、
    ("3r23 4c", 5, "As5s", "call", None, "T2.price"),         # KJs–KTs、QJs
    ("3r23 4c", 5, "KsTs", "call", None, "T2.price"),
    ("3r23 4c", 5, "QsJs", "call", None, "T2.price"),
    ("3r23 4c", 5, "JsTs", "fold", None, "T2.fold"),
    ("3r40 4f 5f 6f", 7, "7c7d", "fold", None, "T2.fold"),    # 40 > 30（15%）
    ("3f 4f 5f 6r23 7f 0f", 1, "7c7d", "fold", None, "T2.fold"),  # 没位置、没人跟
    ("3r23 4c 5c 6f 7f 0f", 1, "Ks9s", "call", None, "T2.blind"),  # 2 人已跟、21 ≤ 92/4
    ("3r23 4c 5c 6f 7f 0f", 1, "Ks8s", "fold", None, "T2.fold"),
    ("3r23", 4, "KcJd", "fold", None, "T2.fold"),
])
def test_table_2(actions, seat, hand, action, to, rule):
    advice = decide({seat: hand}, actions=actions)
    assert (advice.action, advice.to, advice.rule) == (action, to, rule)


def test_three_bet_adds_one_raise_per_caller():
    advice = decide({5: "QcQd"}, actions="3r23 4c", stacks=1000)
    assert (advice.action, advice.to, advice.rule) == ("raise", 92, "T2.3bet")


SHORT = {seat: 200 for seat in range(8)} | {3: 32}       # 3 号全下 30 = 15 个大盲


@pytest.mark.parametrize("actions, seat, hand, action", [
    ("3r30", 4, "5c5d", "call"),
    ("3r30", 4, "4c4d", "fold"),
    ("3r30", 4, "As8s", "call"),
    ("3r30", 4, "KcQd", "call"),
    ("3r30 4c", 5, "8c8d", "fold"),                       # 已有 1 人跟：99+、AQ+
    ("3r30 4c", 5, "AcQd", "call"),
])
def test_facing_a_short_all_in(actions, seat, hand, action):
    advice = decide({seat: hand}, actions=actions, stacks=SHORT)
    assert (advice.action, advice.rule) == (action, "T2.short")


def test_facing_a_deeper_all_in_uses_the_first_row_of_table_3():
    stacks = {seat: 200 for seat in range(8)} | {3: 62}   # 全下 60 = 30 个大盲
    advice = decide({4: "JcJd"}, actions="3r60", stacks=stacks)
    assert (advice.action, advice.rule) == ("fold", "T3.allin")
    advice = decide({4: "QcQd"}, actions="3r60", stacks=stacks)
    assert advice.rule == "T3.allin" and advice.all_in


# -- 表 3 · 面对再加注 ---------------------------------------------------------------

FACING_3BET = "3r23 4r69 5f 6f 7f 0f 1f 2f"


@pytest.mark.parametrize("stacks, hand, action, rule", [
    (200, "QcQd", "raise", "T3.jam"),           # 69 ≥ 有效 200 的 30%：QQ+、AK 全下
    (200, "AcKd", "raise", "T3.jam"),
    (200, "JcJd", "fold", "T3.jam"),
    (1000, "KcKd", "raise", "T3.4bet"),         # < 30%：KK+ 4-bet
    (1000, "QcQd", "call", "T3.call"),
    (1000, "AcKd", "call", "T3.call"),
    (1000, "AsQs", "fold", "T3.fold"),          # v3.3：AQs 弃
    (1000, "TcTd", "fold", "T3.fold"),
])
def test_table_3(stacks, hand, action, rule):
    advice = decide({3: hand}, actions=FACING_3BET, stacks=stacks)
    assert (advice.action, advice.rule) == (action, rule)
    if rule == "T3.jam" and action == "raise":
        assert advice.all_in
    if rule == "T3.4bet":
        assert advice.to == 207


def test_table_3_folds_ace_queen_suited_in_position_too():
    advice = decide({7: "AsQs"}, actions="3f 4f 5f 6f 7r23 0r69 1f 2f", stacks=1000)
    assert (advice.action, advice.rule) == ("fold", "T3.fold")


LIMP_RERAISE = "3c 4f 5f 6f 7r27 0f 1f 2f 3r81"     # 早位平跟、庄位加注、早位再加注


@pytest.mark.parametrize("stacks, hand, action, rule", [
    (1000, "KcKd", "raise", "T3.4bet"), (1000, "QcQd", "call", "T3.call"),
    (1000, "AcKd", "call", "T3.call"),
    (200, "AcKd", "raise", "T3.jam"), (200, "7c7d", "fold", "T3.jam"),
    (40, "9c9d", "call", "T3.push20"),                  # 他全下，跟就是全下
])
def test_a_limper_who_reraises_is_the_usual_table_3(stacks, hand, action, rule):
    # v3.3b 撤回“平跟后再加注只 KK+”：和别的再加注一样按表 3
    actions = LIMP_RERAISE if stacks > 40 else "3c 4f 5f 6f 7r10 0f 1f 2f 3r38"   # 他全下
    advice = decide({7: hand}, actions=actions, stacks=stacks)
    assert (advice.action, advice.rule) == (action, rule)
    assert "T3.limp" not in plain.RULES


def test_a_limper_who_reraises_is_read_as_a_reraise():
    table = plain.Table(spot({7: "KcKd"}, actions=LIMP_RERAISE, stacks=1000))
    read = plain.read_range(table, 3)
    assert (read.preflop, read.words) == ("three_bet", "前 6%")


def test_a_reraise_over_someone_else_s_raise_is_the_usual_table_3():
    # 你跟了别人的加注，平跟的人再加注：不是"你加注、他再加注"，按表 3 平常的行
    actions = "3c 4r20 5f 6f 7c 0f 1f 2f 3r80 4f"
    advice = decide({7: "QcQd"}, actions=actions, stacks=1000)
    assert (advice.action, advice.rule) == ("call", "T3.call")


@pytest.mark.parametrize("actions, seat, hand, action", [
    ("3f 4f 5f 6f 7r8 0r24 1f 2f", 7, "5c5d", "raise"),   # 庄位加 55+、A2s+、KJo+
    ("3f 4f 5f 6f 7r8 0r24 1f 2f", 7, "4c4d", "fold"),
    ("3r8 4r24 5f 6f 7f 0f 1f 2f", 3, "5c5d", "fold"),
    ("3r8 4r24 5f 6f 7f 0f 1f 2f", 3, "7c7d", "raise"),
    ("3r8 4r24 5f 6f 7f 0f 1f 2f", 3, "KsQs", "raise"),
])
def test_push_or_fold_at_20_big_blinds(actions, seat, hand, action):
    advice = decide({seat: hand}, actions=actions, stacks=40)
    assert (advice.action, advice.rule) == (action, "T3.push20")
    assert advice.all_in == (action == "raise")


@pytest.mark.parametrize("hand, action", [("KcKd", "raise"), ("QcQd", "fold")])
def test_facing_a_four_bet_only_kings_and_aces_go_on(hand, action):
    advice = decide({4: hand}, actions=FACING_3BET + " 3r207", stacks=1000)
    assert (advice.action, advice.rule) == (action, "T3.vs4bet")
    assert advice.all_in == (action == "raise")


def test_facing_an_all_in_three_bet_uses_the_first_row():
    advice = decide({3: "JcJd"}, actions="3r23 4r198 5f 6f 7f 0f 1f 2f")
    assert (advice.action, advice.rule) == ("fold", "T3.allin")
    advice = decide({3: "AcKd"}, actions="3r23 4r198 5f 6f 7f 0f 1f 2f")
    assert (advice.action, advice.rule, advice.hits) == ("call", "T3.allin",
                                                         ["T3.allin"])


# -- 五档、两对、降档、补牌 -------------------------------------------------------------

@pytest.mark.parametrize("hole, board, tier, words", [
    ("7c7d", "7h Kc 2d", "A", "暗三"),
    ("Kc7d", "Kh 7c 2d", "A", "两对"),
    ("QcJd", "Qs Tc Qh", "A", "明三条"),                 # v3.3c：公共牌对子 + 你一张（hand_15812）
    ("7c2d", "Kh 7h 7d", "A", "明三条"),                 # 踢脚小也是
    ("AsJs", "Jh 7s 2s", "A", "顶对踢脚 A加同花听牌"),  # v3.3c：顶对 + 坚果同花听（杜的 A♠J♠）
    ("QcQd", "Jh Tc 9d", "A", "超对加两头顺听牌"),       # 超对 + 两头顺
    ("AcKd", "Kh Qc Td", "B", "顶对踢脚 A"),             # 卡顺只有 4 张补牌：还是 B
    ("9c8d", "7h 6c 5d", "A", "顺子"),
    ("Ah2h", "Kh 7h 3h", "A", "同花"),                   # 有同花不降
    ("7c7d", "7h Kc Kd 2h", "A", "葫芦"),
    ("KcKd", "Qh Qc 5d", "B", "超对"),                   # 口袋对子 + 公共牌对子：超对
    ("5c5d", "Qh Qc 9d", "C", "中对"),                   # ……或中对
    ("AcTd", "Ah 7c 7d", "B", "顶对踢脚 T"),             # 一张配公共牌、一张没配：不是两对
    ("Ac9d", "Ah 7c 7d", "C", "弱顶对"),
    ("QcQd", "Jh 7c 2d", "B", "超对"),
    ("AcKd", "Ah 7c 2d", "B", "顶对踢脚 K"),
    ("Ac9d", "Ah 7c 2d", "C", "弱顶对"),
    ("8c7d", "Ah 7c 2d", "C", "第二对"),
    ("3c2s", "Ah 7c 2d", "C", "底对"),
    ("9c9d", "Kh Tc 2d", "C", "中对"),
    ("AcKd", "Qh Qc 5d", "C", "公共牌对子 + 你的高牌"),
    ("6h5h", "Kh 7h 2c", "D", "同花听牌"),
    ("9c8d", "7h 6c 2d", "D", "两头顺听牌"),
    ("4c3d", "Kh Tc 8d", "E", "空气"),
])
def test_tiers(hole, board, tier, words):
    found = plain.classify(cards(hole), cards(board))
    assert (found.tier, found.words) == (tier, words)


def test_strong_draws_and_outs():
    flush_high = plain.classify(cards("Ah5h"), cards("Kh 7h 2c"))
    assert flush_high.tier == "D" and flush_high.strong_draw and flush_high.outs == 9
    both = plain.classify(cards("9h8h"), cards("7h 6h 2c"))
    assert both.strong_draw and both.outs == 15             # 9 张同花 + 6 张不同花的顺子
    plain_flush = plain.classify(cards("6h5h"), cards("Kh 7h 2c"))
    assert not plain_flush.strong_draw and plain_flush.outs == 9
    straight = plain.classify(cards("9c8d"), cards("7h 6c 2d"))
    assert straight.outs == 8 and not straight.strong_draw
    river = plain.classify(cards("6h5h"), cards("Kh 7h 2c 9s Jd"))
    assert river.tier == "E" and river.outs == 0            # 河牌没有听牌


@pytest.mark.parametrize("hole, board, tier, was", [
    ("7c7d", "7h Kh 2h", "B", "A"),                         # 三同花：暗三降到 B
    ("9c8d", "9h 8c 7d 6s", "B", "A"),                      # 四连牌：两对降到 B
    ("QcJd", "Qh Qs 9h 2h", "B", "A"),                      # 三同花：明三条也降到 B
    ("AsJc", "Js 7s 2s", "B", "A"),                         # 三同花：带大听牌的顶对按 A 降到 B
    ("QcQd", "Jh 9h 2h", "C", "B"),                         # 超对降到 C
    ("AcAd", "Jh Tc 9d 8s", "C", "B"),
    ("Ah2h", "Kh 7h 3h", "A", None),                        # 同花、顺子、葫芦不降
    ("7c7d", "7h Kh Kc 2h", "A", None),
])
def test_three_suited_or_four_straight_boards_drop_one_tier(hole, board, tier, was):
    found = plain.classify(cards(hole), cards(board))
    assert (found.tier, found.was) == (tier, was)


def test_dropping_a_tier_is_logged():
    advice = decide({7: "7c7d"}, "7h Kh 2h", HU + " 2c", stacks=400)
    assert advice.tier == "B" and advice.hits == ["DOWN", "N.B"]
    assert advice.action == "bet"


def test_board_that_plays_itself_is_not_classified():
    found = plain.classify(cards("2c2d"), cards("5h 6c 7d 8s 9h"))
    assert found.board_plays
    actions = HU + " 2c 7c 2c 7c 2c"
    advice = decide({7: "2c2d"}, "5h 6c 7d 8s 9h", actions)
    assert (advice.action, advice.rule, advice.unspecified) == (
        "check", "I5", "board_plays")


# -- 翻后 · 没人下注 ---------------------------------------------------------------

@pytest.mark.parametrize("hand, board, actions, action, size, rule", [
    ("7c7d", "7h Kc 2d", HU + " 2c", "bet", 2 / 3, "N.A"),
    ("7c7d", "7h Kc 2d 9s 4c", HU + " 2c 7c 2c 7c 2c", "bet", 3 / 4, "N.A"),  # 单挑河牌
    ("AsKd", "Ah 7c 2d", HU + " 2c", "bet", 1 / 2, "N.B"),
    ("AsKd", "Ah 7c 2d 9s", HU + " 2c 7c 2c", "bet", 1 / 2, "N.B"),     # 翻牌没下过注
    ("AsKd", "Ah 7c 2d 9s", HU + " 2c 7r20 2c 2c", "check", None, "N.B.second"),  # 翻牌被跟
    ("AsKd", "Ah 7c 2d 9s", HU + " 2r20 7c 2c", "bet", 1 / 2, "N.B"),   # 你跟了别人的注
    ("7c7d", "7h Kh 2h 9c", HU + " 2c 7c 2c", "check", None, "N.B"),   # 降到 B、三同花
    ("AsKd", "Ah 7c 2d 9s 4c", HU + " 2c 7c 2c 7c 2c", "bet", 1 / 3, "N.B"),
    ("AsKd", "Ah 7c 2d 9s 4c", HU + " 2c 7r30 2r90 7c 2c 7c 2c", "check", None,
     "N.B"),                                                            # 翻牌有人加注过
    ("Ah5h", "Kh 7h 2c", HU + " 2c", "bet", 2 / 3, "N.D_strong"),
    ("6h5h", "Kh 7h 2c", HU + " 2c", "bet", 1 / 2, "N.D"),
    ("6h5h", "Kh 7h 2c 3s", HU + " 2c 7c 2c", "check", None, "N.D"),   # D 转牌过牌
    ("9c9d", "Kh Tc 2d", HU + " 2c", "bet", 1 / 3, "N.C"),             # 翻前加注者
    ("4c3d", "Kh Tc 8d", HU + " 2c", "bet", 1 / 3, "N.E"),
    ("9c9d", "Kh Tc 2d 5s", HU + " 2c 7r22 2c 2c", "check", None, "N.turn"),
])
def test_checked_to_heads_up(hand, board, actions, action, size, rule):
    advice = decide({7: hand}, board, actions, stacks=400)
    assert (advice.action, advice.rule) == (action, rule)
    if size is not None:
        observation = spot({7: hand}, board, actions, stacks=400)
        assert advice.to == pytest.approx(size * float(observation["pot"]), abs=1)


def test_checked_to_without_raising_preflop():
    advice = decide({2: "9c9d"}, "Kh Tc 2d", HU, stacks=400)          # 抓头先说
    assert (advice.action, advice.rule) == ("check", "N.C")


@pytest.mark.parametrize("hand, board, actions, action, rule", [
    ("AsKd", "Ah 7c 2d 9s", THREE_WAY + " 1c 2c 7c 1c 2c", "bet", "N.B"),   # 2 个对手
    ("AsKd", "Ah 7c 2d 9s", THREE_WAY + " 1c 2c 7r30 1c 2c 1c 2c", "check",
     "N.B.second"),
    ("AsKd", "Ah 7c 2d 9s", THREE_WAY + " 1c 2c 7r30 1c 2f 1c", "check", "N.B.second"),
    ("AsKd", "Ah 7c 2d 9s 4c", THREE_WAY + " 1c 2c 7c 1c 2c 7c 1c 2c", "check", "N.B"),
    ("Ah5h", "Kh 7h 2c", THREE_WAY + " 1c 2c", "check", "N.D_strong"),
    ("6h5h", "Kh 7h 2c", THREE_WAY + " 1c 2c", "check", "N.D"),
    ("9c9d", "Kh Tc 2d", THREE_WAY + " 1c 2c", "bet", "N.C"),     # ≤ 2 个对手、翻前加注者
    ("7c7d", "7h Kc 2d", THREE_WAY + " 1c 2c", "bet", "N.A"),
])
def test_checked_to_multiway(hand, board, actions, action, rule):
    advice = decide({7: hand}, board, actions, stacks=400)
    assert (advice.action, advice.rule) == (action, rule)


def test_checked_to_with_three_opponents():
    board, actions = "Ah 7c 2d 9s", FOUR_WAY + " 1c 2c 6c 7c 1c 2c 6c"
    advice = decide({7: "AsKd"}, board, actions, stacks=400)
    assert (advice.action, advice.rule) == ("check", "N.B")          # 转牌 ≥ 3 对手过牌
    advice = decide({6: "9c9d"}, "Kh Tc 2d", FOUR_WAY + " 1c 2c", stacks=400)
    assert (advice.action, advice.rule) == ("check", "N.C")


# -- 翻后 · 面对下注 ---------------------------------------------------------------

@pytest.mark.parametrize("hand, board, actions, action, rule", [
    ("7c7d", "7h Kc 2d", HU + " 2r10", "raise", "F.A"),                 # 加注到 3 倍
    ("7c7d", "7h Kc 2d 9s 4c", HU + " 2c 7c 2c 7c 2r20", "call", "F.A"),  # 河牌不是坚果
    ("KcKd", "Kh 7c 2d 9s 4c", HU + " 2c 7c 2c 7c 2r20", "raise", "F.A"),  # 河牌坚果
    ("AsKd", "Ah 7c 2d", HU + " 2r40", "call", "F.B"),                  # ≤ 2/3
    ("AsKd", "Ah 7c 2d 9s 4c", HU + " 2c 7c 2c 7c 2r30", "call", "F.B"),  # 河牌 ≤ 1/2
    ("AsKd", "Ah 7c 2d 9s 4c", HU + " 2c 7c 2c 7c 2r40", "call", "I1"),   # 更大：铁律 1
    ("Ah5h", "Kh 7h 2c", HU + " 2r30", "raise", "F.D_strong"),         # ≤ 1/2：加注
    ("Ah5h", "Kh 7h 2c", HU + " 2r40", "fold", "F.D_strong"),          # 更大：按补牌
    ("6h5h", "Kh 7h 2c", HU + " 2r10", "call", "F.D"),                 # 18% ≥ 10/85
    ("6h5h", "Kh 7h 2c", HU + " 2r40", "fold", "F.D"),                 # 18% < 40/145
    ("9c9d", "Kh Tc 2d", HU + " 2r30", "call", "F.C"),                 # 翻牌 ≤ 1/2 跟一次
    ("9c9d", "Kh Tc 2d", HU + " 2r40", "fold", "F.C"),
    ("9c9d", "Kh Tc 2d 5s", HU + " 2c 7c 2r20", "fold", "F.C"),         # 转牌弃
    ("4c3d", "Kh Tc 8d", HU + " 2r10", "fold", "F.E"),
])
def test_facing_a_bet_heads_up(hand, board, actions, action, rule):
    advice = decide({7: hand}, board, actions, stacks=400)
    assert (advice.action, advice.rule) == (action, rule)
    if action == "raise" and rule != "F.A" or "2r10" in actions and rule == "F.A":
        observation = spot({7: hand}, board, actions, stacks=400)
        assert advice.to == 3 * max(float(bet) for bet in observation["bets"].values())


def test_one_pair_facing_a_bigger_bet_folds_past_a_third_of_the_stack():
    # 有效 175、翻后 1/3 = 58：跟 50 可以，跟 60 不行
    advice = decide({7: "AsKd"}, "Ah 7c 2d", HU + " 2r50")
    assert (advice.action, advice.rule, advice.hits) == ("call", "I1", ["F.B", "I1"])
    advice = decide({7: "AsKd"}, "Ah 7c 2d", HU + " 2r60")
    assert (advice.action, advice.rule) == ("fold", "I1")


@pytest.mark.parametrize("bet, action", [("85", "call"), ("90", "fold")])
def test_top_pair_against_two_opponents_calls_up_to_the_pot(bet, action):
    advice = decide({7: "AsKd"}, "Ah 7c 2d", THREE_WAY + f" 1r{bet} 2c", stacks=400)
    assert (advice.action, advice.rule) == (action, "F.B")


@pytest.mark.parametrize("bet, action", [("54", "call"), ("56", "fold")])
def test_top_pair_against_three_opponents_calls_up_to_half_the_pot(bet, action):
    actions = FOUR_WAY + f" 1r{bet} 2c 6c"
    advice = decide({7: "AsKd"}, "Ah 7c 2d", actions, stacks=400)
    assert (advice.action, advice.rule) == (action, "F.B")


def test_middle_pair_folds_to_a_bet_in_a_multiway_pot():
    advice = decide({7: "9c9d"}, "Kh Tc 2d", THREE_WAY + " 1r20 2f", stacks=400)
    assert advice.action == "call"                         # 2 人：单挑了
    advice = decide({7: "9c9d"}, "Kh Tc 2d", THREE_WAY + " 1r20 2c", stacks=400)
    assert (advice.action, advice.rule) == ("fold", "F.C")


def test_top_pair_with_two_opponents_on_a_suited_board_is_not_written():
    advice = decide({7: "7c7d"}, "7h Kh 2h", THREE_WAY + " 1r20 2c", stacks=400)
    assert advice.tier == "B"
    assert (advice.action, advice.unspecified) == ("fold", "b_two_texture")


@pytest.mark.parametrize("street, bet, action", [
    ("turn", "43", "call"), ("turn", "44", "fold"),      # 转牌 2 个对手：≤ 1/2 底池
    ("river", "43", "call"), ("river", "44", "fold"),    # 河牌 2 个对手：≤ 1/2 底池
])
def test_top_pair_against_two_opponents_after_the_flop_calls_up_to_half(
        street, bet, action):
    checks = " 1c 2c 7c" + (" 1c 2c 7c" if street == "river" else "")
    board = "Ah 7c 2d 9s" + (" 4c" if street == "river" else "")
    advice = decide({7: "AsKd"}, board, THREE_WAY + checks + f" 1r{bet} 2c", stacks=400)
    assert (advice.action, advice.rule) == (action, "F.B")


@pytest.mark.parametrize("bet, action", [("36", "call"), ("37", "fold")])
def test_top_pair_against_three_opponents_on_the_turn_calls_up_to_a_third(bet, action):
    actions = FOUR_WAY + f" 1c 2c 6c 7c 1r{bet} 2c 6c"
    advice = decide({7: "AsKd"}, "Ah 7c 2d 9s", actions, stacks=400)
    assert (advice.action, advice.rule) == (action, "F.B")


def test_top_pair_against_three_opponents_folds_any_river_bet():
    actions = FOUR_WAY + " 1c 2c 6c 7c 1c 2c 6c 7c 1r10 2c 6c"
    advice = decide({7: "AsKd"}, "Ah 7c 2d 9s 4c", actions, stacks=400)
    assert (advice.action, advice.rule) == ("fold", "F.B")
    assert "一律弃" in advice.flip


def test_a_suited_board_with_two_opponents_is_written_on_the_turn():
    actions = THREE_WAY + " 1c 2c 7c 1r43 2c"
    advice = decide({7: "7c7d"}, "7h Kh 2c 9h", actions, stacks=400)
    assert advice.tier == "B" and advice.unspecified is None
    assert (advice.action, advice.rule) == ("call", "F.B")


# -- 翻后 · 面对加注 ---------------------------------------------------------------

@pytest.mark.parametrize("hand, board, actions, action, rule", [
    ("7c7d", "7h Kc 2d", HU + " 2c 7r30 2r90", "call", "R.A"),           # 不是坚果：跟
    ("KcKd", "Kh 7c 2d", HU + " 2c 7r30 2r90", "raise", "J3"),           # 坚果：再加注
    ("AsKd", "Ah 7c 2d 9s", HU + " 2c 7c 2c 7r30 2r90", "fold", "R.B"),  # 转牌被加注
    ("AsKd", "Ah 7c 2d", HU + " 2c 7r30 2r90", "fold", "R.B"),           # SPR > 1
    ("Ah5h", "Kh 7h 2c", HU + " 2c 7r10 2r40", "fold", "R.D"),           # 18% < 30/145
    ("Ah5h", "Kh 7h 2c", HU + " 2c 7r10 2r25", "call", "R.D"),           # 18% ≥ 15/115
    ("9c9d", "Kh Tc 2d", HU + " 2c 7r20 2r60", "fold", "R.CE"),
    ("4c3d", "Kh Tc 8d", HU + " 2c 7r20 2r60", "fold", "R.CE"),
])
def test_facing_a_raise(hand, board, actions, action, rule):
    advice = decide({7: hand}, board, actions, stacks=400)
    assert (advice.action, advice.rule) == (action, rule)


@pytest.mark.parametrize("actions, action, rule", [
    (HU + " 2c 7r30 2r90", "call", "R.A"),                 # 单挑被加注：B 是 R.B 弃
    (THREE_WAY + " 1c 2c 7r30 1r90 2f", "call", "R.A"),    # 多人下注被加注：B 也是弃
    (THREE_WAY + " 1r60 2c", "raise", "J3"),               # 多人面对下注：B 只跟
])
def test_top_pair_with_a_big_draw_plays_like_a_strong_hand(actions, action, rule):
    # v3.3c 原文漏写：顶对 + 坚果同花听（9 张补牌）视同 A 档（主人 10-17，杜的 A♠J♠）
    advice = decide({7: "AsJs"}, "Jh 7s 2s", actions, stacks=400)
    assert advice.tier == "A" and (advice.action, advice.rule) == (action, rule)


@pytest.mark.parametrize("value, hits", [(0.5, ["R.B", "I1"]), (0.2, ["R.B"])])
def test_top_pair_raised_on_the_flop_is_all_in_or_fold_and_iron_law_1_wins(
        equity_is, value, hits):
    # 跟 60 后剩 85、底池 245：SPR ≤ 1；所需 60/245 = 24%，+5% = 29%。胜率够时这一行
    # 要全下，可全下超过铁律 1 的 1/3 有效筹码（翻牌 SPR 2.7 > 2，没有例外）：铁律优先，弃
    equity_is(value)
    advice = decide({7: "AsKd"}, "Ah 7c 2d", HU + " 2c 7r30 2r90")
    assert advice.action == "fold" and advice.hits == hits


# -- SPR 规则 ----------------------------------------------------------------------

def test_low_spr_heads_up_plays_top_pair_like_a_strong_hand():
    # 筹码 100：翻牌剩 75、底池 65，SPR 1.2 → B 视同 A：下 2/3，剩的 ≤ 底池 → 全下
    advice = decide({7: "AsKd"}, "Ah 7c 2d", HU + " 2c", stacks=100)
    assert advice.hits == ["SPR.A", "J1"] and advice.all_in
    assert (advice.action, advice.to) == ("bet", 75)


def test_low_spr_top_pair_is_not_stopped_by_iron_law_1(equity_is):
    equity_is(0.6)
    advice = decide({7: "AsKd"}, "Ah 7c 2d", HU + " 2r60", stacks=100)
    assert advice.rule in ("SPR.A", "J3", "ALLIN") and advice.action != "fold"


def test_low_spr_with_three_opponents_keeps_top_pair_a_one_pair_hand(equity_is):
    # 4 人、筹码 200：翻牌剩 177、底池 109，SPR 1.6。≤ 1/2 底池跟一次（v3.3b 回到 v3.2）；
    # 跟完剩 123 ≤ 底池一半，按阈值 2 决定：胜率够要全下，多人底池 B 档不加注（铁律 2）→ 跟
    actions = FOUR_WAY + " 1r54 2c 6c"
    equity_is(0.5)
    advice = decide({7: "AsKd"}, "Ah 7c 2d", actions)
    assert advice.action == "call" and advice.hits == ["SPR.many", "J2", "I2"]
    equity_is(0.2)
    advice = decide({7: "AsKd"}, "Ah 7c 2d", actions)
    assert advice.action == "fold" and advice.hits == ["SPR.many", "J2"]
    advice = decide({7: "AsKd"}, "Ah 7c 2d", FOUR_WAY + " 1r56 2c 6c")
    assert (advice.action, advice.rule) == ("fold", "SPR.many")         # 超过 1/2
    advice = decide({7: "AsKd"}, "Ah 7c 2d", FOUR_WAY + " 1r20 2c 6r60")
    assert (advice.action, advice.rule) == ("fold", "SPR.many")         # 被加注弃


def test_low_spr_three_opponents_half_pot_bet_leaving_less_than_the_pot_checks():
    # B 档的 1/2 注下出去剩的 ≤ 底池：不改全下，不下注（过牌）
    advice = decide({7: "AsKd"}, "Ah 7c 2d", FOUR_WAY + " 1c 2c 6c")
    assert advice.hits == ["SPR.many", "J1.no"]
    assert (advice.action, advice.rule) == ("check", "J1.no")
    advice = decide({7: "AsKd"}, "Ah 7c 2d 9s", FOUR_WAY + " 1c 2c 6c 7c 1c 2c 6c")
    assert (advice.action, advice.rule) == ("check", "SPR.many")


def test_bomb_pot_follows_the_postflop_tables():
    observation = spot({7: "7c7d"}, "7h Kc 2d", "0c 1c 2c 3c 4c 5c 6c", bomb=14,
                       stacks=400)
    assert observation["street"] == "flop"
    advice = plain.decide(observation)
    assert (advice.action, advice.rule) == ("bet", "N.A")
    table = plain.Table(observation)
    assert table.raiser is None and len(table.opponents) == 7


# -- 面对全下、直接全下的三条阈值 ---------------------------------------------------------

def test_no_range_means_iron_law_5(equity_is):
    equity_is(None)
    advice = decide({7: "7c7d"}, "7h Kc 2d 9s", HU + " 2c 7c 2r175")
    assert (advice.action, advice.unspecified) == ("fold", "no_range")
    assert advice.rule == "I5"


@pytest.mark.parametrize("value, action", [(0.6, "call"), (0.45, "fold")])
def test_facing_an_all_in_needs_five_points_over_the_price(equity_is, value, action):
    # 跟 175 赢 415：所需 42%，+5% = 47%
    equity_is(value)
    advice = decide({7: "7c7d"}, "7h Kc 2d 9s", HU + " 2c 7c 2r175")
    assert (advice.action, advice.rule) == (action, "ALLIN")
    assert advice.need == pytest.approx(175 / 415, abs=0.001)
    assert "所需" in advice.flip


def test_a_draw_facing_an_all_in_uses_four_percent_an_out_on_the_flop():
    advice = decide({7: "9h8h"}, "7h 6h 2c", HU + " 2r175")       # 15 张 × 4% = 60%
    assert (advice.action, advice.rule) == ("call", "F.D_strong")
    assert advice.equity == pytest.approx(0.60)
    advice = decide({7: "9h8h"}, "7h 6h 2c Ks", HU + " 2c 7c 2r175")  # 转牌只 × 2%
    assert (advice.action, advice.equity) == ("fold", pytest.approx(0.30))


@pytest.mark.parametrize("value, action", [(0.6, "raise"), (0.3, "fold")])
def test_a_call_that_leaves_half_the_pot_is_decided_like_an_all_in(equity_is, value,
                                                                   action):
    # 筹码 58：跟 23 后剩 33 ≤（46 + 23）/ 2
    equity_is(value)
    stacks = {seat: 200 for seat in range(8)} | {4: 58}
    advice = decide({4: "AcQd"}, actions="3r23", stacks=stacks)
    assert advice.hits == ["T2.call", "J2"] and advice.rule == "J2"
    assert advice.action == action and advice.all_in == (action == "raise")


def test_a_bet_that_leaves_less_than_the_pot_goes_all_in():
    advice = decide({7: "7c7d"}, "7h Kc 2d", HU + " 2c", stacks=100)
    assert advice.hits == ["N.A", "J1"] and advice.all_in and advice.to == 75


@pytest.mark.parametrize("hand, board, rule", [
    ("9c9d", "Kh Tc 2d", "N.C"),            # C 档 1/3 注：筹码 60，下 22 剩 13 ≤ 底池
    ("Jc4d", "Kh Tc 2d", "N.E"),            # E 档 1/3 注
    ("6h5h", "Kh 7h 2c", "N.D"),            # D 档 1/2 注
])
def test_small_bets_that_leave_less_than_the_pot_check_instead(hand, board, rule):
    advice = decide({7: hand}, board, HU + " 2c", stacks=60)
    assert (advice.action, advice.rule) == ("check", "J1.no")
    assert advice.hits == [rule, "J1.no"] and not advice.all_in
    advice = decide({7: hand}, board, HU + " 2c", stacks=400)
    assert (advice.action, advice.rule, advice.all_in) == ("bet", rule, False)


def test_a_strong_draw_raise_that_leaves_less_than_the_pot_goes_by_the_outs():
    # 筹码 120：加到 30 剩 65 ≤ 底池 105 → 不加；补牌 9 × 2% = 18% ≥ 所需 10/85
    advice = decide({7: "AhQh"}, "Kh 7h 2c", HU + " 2r10", stacks=120)
    assert (advice.action, advice.rule) == ("call", "F.D_strong")
    assert "J1.no" in advice.hits
    advice = decide({7: "AhQh"}, "Kh 7h 2c", HU + " 2r10", stacks=400)
    assert (advice.action, advice.to, advice.rule) == ("raise", 30, "F.D_strong")


def test_a_big_raise_with_a_strong_hand_goes_all_in():
    advice = decide({7: "7c7d"}, "7h Kc 2d", HU + " 2r30", stacks=400)   # 90 < 40%
    assert (advice.action, advice.to, advice.rule) == ("raise", 90, "F.A")
    advice = decide({7: "7c7d"}, "7h Kc 2d", HU + " 2r30")               # 90 ≥ 70
    assert advice.hits == ["F.A", "J3"] and advice.all_in


# -- 五条铁律 ----------------------------------------------------------------------

def _context(table, plays):
    return {"strength": plain.classify(table.hole, table.board), "plays": plays,
            "equity": lambda: None}


def test_iron_law_1_one_pair_never_puts_in_more_than_a_third():
    advice = decide({7: "AsKd"}, "Ah 7c 2d", HU + " 2r60")
    assert advice.rule == "I1" and advice.action == "fold"
    assert "最多投入 58" in advice.flip


def test_iron_law_2_multiway_one_pair_and_draws_do_not_raise_or_call_big():
    # 4 人：D-强 15 张补牌（30%）够价，但 ≥ 3 个对手翻牌不跟超过 1/2 底池的注
    actions = FOUR_WAY + " 1r70 2c 6c"
    advice = decide({7: "9h8h"}, "7h 6h 2c", actions, stacks=400)
    assert (advice.action, advice.rule) == ("fold", "I2")
    # v3.3：转牌不跟超过 1/3 底池的注（补牌 15 张、转牌 × 2% = 30%，价格都够）
    turn = FOUR_WAY + " 1c 2c 6c 7c 1r{} 2c 6c"
    advice = decide({7: "9h8h"}, "7h 6h 2c Kd", turn.format(54), stacks=400)
    assert (advice.action, advice.rule) == ("fold", "I2")
    advice = decide({7: "9h8h"}, "7h 6h 2c Kd", turn.format(36), stacks=400)
    assert (advice.action, advice.rule) == ("call", "F.D_strong")
    table = plain.Table(spot({7: "9c9d"}, "Kh Tc 2d", THREE_WAY + " 1r20 2c",
                             stacks=400))
    advice = plain._banned(table, plain.Advice("raise", to=60), _context(table, "C"))
    assert (advice.action, advice.rule) == ("call", "I2")


def test_iron_law_3_no_river_bluffs_and_one_pair_bets_a_third_at_most():
    table = plain.Table(spot({7: "4c3d"}, "Kh Tc 8d 9s 2c", HU + " 2c 7c 2c 7c 2c",
                             stacks=400))
    advice = plain._banned(table, plain.Advice("bet", to=30), _context(table, "E"))
    assert (advice.action, advice.rule) == ("check", "I3")
    advice = plain._banned(table, plain.Advice("bet", to=40), _context(table, "B"))
    assert (advice.action, advice.rule) == ("check", "I3")
    advice = plain._banned(table, plain.Advice("bet", to=21), _context(table, "B"))
    assert advice.action == "bet"


def test_iron_law_4_draws_do_not_raise_except_a_strong_draw_heads_up_on_the_flop():
    table = plain.Table(spot({7: "6h5h"}, "Kh 7h 2c", THREE_WAY + " 1r20 2c",
                             stacks=400))
    advice = plain._banned(table, plain.Advice("raise", to=60), _context(table, "D"))
    assert (advice.action, advice.rule) == ("call", "I4")
    table = plain.Table(spot({7: "Ah5h"}, "Kh 7h 2c", HU + " 2r20", stacks=400))
    advice = plain._banned(table, plain.Advice("raise", to=60), _context(table, "D"))
    assert advice.action == "raise"


@pytest.mark.parametrize("change, missing", [
    (lambda o: o.update(own_hole=["As", None]), "你的牌没读全"),
    (lambda o: o.update(board=o["board"][:2]), "公共牌没读全"),
    (lambda o: o.update(stacks_unknown=[2]), "有人筹码没读到"),
    (lambda o: o.update(unknown_actions=1), "有动作没读到"),
])
def test_iron_law_5_unclear_reads_fold_or_check(change, missing):
    facing = spot({7: "AsKd"}, "Ah 7c 2d", HU + " 2r20")
    change(facing)
    advice = plain.decide(facing)
    assert (advice.action, advice.rule) == ("fold", "S1")
    assert missing in advice.reason
    checked = spot({7: "AsKd"}, "Ah 7c 2d", HU + " 2c")
    change(checked)
    assert plain.decide(checked).action == "check"


def test_tables_outside_four_to_eight_seats_use_the_nearest_table():
    # 9 人：多一个早位（座位 8 坐在 3 号后面、已弃），中位 4 号照中位表开池
    observation = spot({4: "KcQd"}, actions="3f")
    observation["occupied_seats"] = [0, 1, 2, 3, 8, 4, 5, 6, 7]
    observation["folded"] = sorted(observation["folded"] + [8])
    for key, chips in (("bets", "0"), ("stacks", "198"), ("contributions", "2")):
        observation[key]["8"] = chips
    observation["pot"] = str(float(observation["pot"]) + 2)
    classes = plain.seat_classes(observation)
    assert [classes[seat][0] for seat in (3, 8, 4, 5, 6, 7)] == [
        "early", "early", "middle", "middle", "late", "late"]
    advice = plain.decide(observation)
    assert (advice.action, advice.to, advice.rule) == ("raise", 25, "T1.raise")
    three = {"occupied_seats": [0, 1, 7], "dealer_seat": 7, "straddler_seat": None}
    assert plain.seat_classes(three) == {0: ("blind", "SB"), 1: ("blind", "BB"),
                                         7: ("late", "BTN")}


# -- 对手范围（第四节） ----------------------------------------------------------------

def test_ranges_follow_the_last_preflop_action_and_shrink_once_a_street():
    observation = spot({2: "Ac9d", 7: "KcKd"}, "Ah 7c 2d Ks",
                       HU + " 2r20 7c 2c 7r70")
    reads = plain.ranges(plain.Table(observation))
    assert reads[7].preflop == "raise" and reads[7].words == "前 15%×35%×40%"
    assert reads[7].story == "翻前加注、翻牌跟注、转牌下注"
    limp = plain.Table(spot({}, "", "3c"))
    assert plain.preflop_action(limp, 3) == ("limp", (0.04, 0.50))
    early = plain.Table(spot({}, "", "3r23"))
    assert plain.preflop_action(early, 3) == ("raise", (0.0, 0.10))
    three = plain.Table(spot({}, "", "3r23 4r69 5f 6f 7f 0f 1f 2f 3c"))
    assert plain.preflop_action(three, 4) == ("three_bet", (0.0, 0.06))
    assert plain.preflop_action(three, 3) == ("call_three_bet", (0.03, 0.10))
    called = plain.Table(spot({}, "", "3r23 4c"))
    assert plain.preflop_action(called, 4) == ("call_raise", (0.06, 0.31))
    middle = plain.Table(spot({}, "", "3f 4r23"))
    assert plain.preflop_action(middle, 4) == ("raise", (0.0, 0.12))


def test_a_range_keeps_the_strongest_share_of_combos():
    observation = spot({7: "QcQd"}, "Ah 7c 2d", HU + " 2r20")
    read = plain.ranges(plain.Table(observation))[2]
    assert read.words == "前 31% 去掉前 6%×40%"
    strength = plain.board_strength(cards("Ah 7c 2d"))
    band = ((plain.PREFLOP_PLACE > 0.06) & (plain.PREFLOP_PLACE <= 0.31)
            & plain.alive(cards("Ah 7c 2d QcQd")))
    dropped = band & (read.weights == 0)
    assert strength[read.weights > 0].min() >= strength[dropped].max() - 1e-9
    assert (read.weights > 0).sum() == pytest.approx(0.40 * band.sum(), rel=0.1)


# -- 一句话理由、三个数、翻转条件 --------------------------------------------------------

def test_reason_strings_the_six_steps_together(equity_is):
    equity_is(0.28)
    # v3.1 的理由句示例：转牌单挑被下注 2/3，他翻前加注、翻牌跟注，我弱顶对 C 档
    observation = spot({2: "Ac9d", 7: "KcQc"}, "Ah 7c 2d Ks", HU + " 2r20 7c 2c 7r70")
    advice = plain.decide(observation)
    # 范围也按他正下的这一注缩（第四节"主动下注 前 40%"）
    assert advice.reason == ("转牌单挑被下注 2/3 底池；他翻前加注、翻牌跟注、转牌下注，"
                             "范围前 15%×35%×40%；我弱顶对 C 档，胜率 28%，需要 29%；"
                             "面对下注·C 档——弃。")
    assert advice.range_words == "前 15%×35%×40%"
    assert (advice.equity, advice.need) == (0.28, pytest.approx(70 / 245))
    assert advice.flip == "转牌、河牌再被下注就弃"


def test_preflop_reason_and_flip():
    advice = decide({3: "AsJs"})
    assert advice.reason.startswith("翻前早位，前面没人入池；后面的人还没动作；我 AJs，胜率 ")
    assert advice.reason.endswith("；表 1·表内开池加注——加注到 23。")
    assert advice.flip == "前面有人加注就改按表 2"
    advice = decide({7: "7c7d"}, actions="3r40 4f 5f 6f")
    assert "他翻前加注，范围前 10%" in advice.reason
    assert advice.reason.endswith("表 2·弃牌——弃。")


def test_flip_for_one_pair_facing_a_bet_names_the_size():
    advice = decide({7: "AsKd"}, "Ah 7c 2d", HU + " 2r40", stacks=400)
    assert advice.flip == "他下到 43.3 以上就按铁律 1"
    advice = decide({7: "6h5h"}, "Kh 7h 2c", HU + " 2r10", stacks=400)
    assert advice.flip.startswith("跟注 ") and "补牌胜率 18%" in advice.flip


def test_row_carries_rule_numbers_and_the_three_numbers():
    row = decide({7: "AsKd"}, "Ah 7c 2d", HU + " 2r40", stacks=400).row()
    assert row["action"] == "call" and row["rule"] == "F.B"
    assert row["rule_label"] == "面对下注·B 档" and row["hits"] == ["F.B"]
    assert row["tier"] == "B" and row["hand"] == "顶对踢脚 K"
    assert row["range"] and row["equity"] is not None
    assert row["need"] == pytest.approx(40 / 145, abs=0.001)
    assert row["reason"].endswith("——跟注 40。") and row["flip"]
    unknown = decide({7: "7c7d"}, "7h Kh 2h", THREE_WAY + " 1r20 2c").row()
    assert unknown["unspecified"] == "b_two_texture"


def test_every_rule_and_case_has_a_label():
    assert set(plain.RULES) >= {"S1", "I1", "I2", "I3", "I4", "I5", "J1", "J2", "J3",
                                "ALLIN", "SPR.A", "SPR.many", "DOWN"}
    assert all(plain.RULES.values()) and all(plain.UNSPECIFIED.values())
    assert all(plain.READINGS.values())


# -- 记分牌 -----------------------------------------------------------------------

def test_scoreboard_plays_plain_and_counts_the_rules():
    policy = make_policy("plain")
    observation = spot({3: "AsJs"})
    assert policy.for_game(1)(observation) == "raise_to:23"
    assert policy.counts["rule:T1.raise"] == 1
    assert plain.action_id(plain.Advice("fold"), spot({7: "AsKd"}, "Ah 7c 2d",
                                                      HU + " 2c")) == "check_call"
    report = run_scoreboard(PROFILE, ["plain"], deals=2, base_seed=1, pool=("nit",))
    counts = report["decision_counts"]["plain"]
    assert sum(value for key, value in counts.items() if key.startswith("rule:")) > 0


# -- 翻转条件和建议用同一个底池、同一个门槛（夜间代码检查 10-17） -------------------------

def test_draw_flip_counts_the_mushroom_pool():
    # 小盲 6h5h 同花听面对 12，蘑菇池 40：所需胜率把蘑菇池算进底池，翻转条件也要算
    advice = decide({0: "6h5h"}, "Kh 9h 2c", "3c 4f 5f 6f 7f 0c 1c 2c 0c 1r12 2f 3f",
                    stacks=200, mushroom="40")
    assert (advice.action, advice.rule) == ("call", "F.D")
    most = float(re.search(r"跟注 ([\d.]+) 以内才跟", advice.flip).group(1))
    assert most >= 12, advice.flip


def test_price_call_flip_uses_the_mushroom_threshold():
    # 小盲 77 面对开到 36、一人跟，蘑菇池 40：门槛 20% × 200 = 40，翻转条件也写 40
    advice = decide({0: "7c7d"}, "", "3f 4f 5r36 6c 7f", stacks=200, mushroom="40")
    assert (advice.action, advice.rule) == ("call", "T2.price")
    assert "跟注超过 40 就弃" in advice.flip, advice.flip
