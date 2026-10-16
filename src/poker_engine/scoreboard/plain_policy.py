"""一页纸打法 ``plain``：按《一页纸打法 v3.1》（2026-10-16）原样实现，翻前翻后都在这里。

v3.1 是唯一的规则来源：不加规则、不顺手优化、不用人群模型的 EV 调数字。v3.1 没写的
情形按铁律 5（面对下注弃、没人下注过牌），建议里记一条 ``unspecified`` 汇总给主人。
v3.1 有两种读法的地方，这里选了一种，写在 ``READINGS``（PR 描述里同样列出）。

零、灵魂（v3.1 原文）
=====================

**人设**：松桌上收账的老派紧凶玩家——不偷、不护、不斗气，开口就按这桌的大价钱要。

**永远会做**：表内的牌开到底池大小；当翻前加注者时翻牌打一枪、转牌停；强牌要大钱（翻后下
2/3 底池，被下注就加到 3 倍）。
**永远不会做**：表外的牌不加注，前注再厚也不偷；转牌、河牌被加注，一对不管价格一律放；
河牌不诈唬。

**每个决定都走一遍的六步**（人 12 秒走得完；软件的一句话理由就是这六步串起来）：

| 步 | 问题 | 输出 | 对应能力 |
|---|---|---|---|
| 1 | 看清了吗？牌、公牌、底池、筹码、各人动作有没有 `UNKNOWN`？ | 全清 / 缺项（缺项直接走铁律 5） | 读牌 · 纪律 |
| 2 | 什么局？街道、对手数、前面有没有下注、我是不是翻前加注者、SPR | 局面码 | 读牌 |
| 3 | 他们拿什么？翻前最后动作定范围，翻后按街缩一次；谁加注谁强 | 每个对手的范围 | 读牌 |
| 4 | 我比他强吗？翻前看表内外；翻后定档、按公牌降档，对第 3 步的范围算胜率 | 档 + 领先 / 落后 / 听牌 + 胜率 | 读牌 → 策略 |
| 5 | 什么被禁？过五条铁律和"被加注"规则 | 允许的动作集合 | 纪律 |
| 6 | 允许的里哪个最赚？跟注比胜率和价格，下注按本桌尺寸 | 动作 + 尺寸 | 策略 |

理由句示例："转牌单挑被下注 2/3；他翻前加注、翻牌跟注，范围前 12%×35%；我弱顶对 C 档，
胜率 28%，需要 40%；C 档转牌被下注——弃。"

代码怎么对应六步
================

``decide(observation)`` 按顺序走：``_clear``（第 1 步）→ ``Table``（第 2 步：位置按座位数、
SPR、对手数、谁是翻前加注者）→ ``ranges``（第 3 步：第四节的固定范围、按街缩一次）→
``classify``（第 4 步：五档、降档、补牌）→ 翻前 ``_preflop`` / 翻后 ``_postflop`` 查表
（第 6 步）→ ``_banned``（第 5 步：五条铁律、"被加注"规则和直接全下的三条阈值，查完表再
过一遍，改了动作就记下是哪一条）。每条建议是一个 ``Advice``：动作、尺寸、一句话理由、
命中的规则编号（``RULES``）、三个数（对手范围、我的胜率、所需胜率）和翻转条件。

记分牌上 ``plain`` 翻前翻后都这样打（``PlainBot``，每条规则命中几次记在 ``counts``）；
实时窗口在设置里打开开关后全程用它（``desktop/aa_solver_advice``）。软件只显示建议，
人来操作。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
from itertools import combinations
import random

import numpy as np
from phevaluator import _pheval

from poker_engine.solver.texassolver import combo_key

from .bots import _Policy
from .ranges import ranges_equity
from .side_pots import matched as matched_pot
from .side_pots import pots as side_pots
from .strength import CARD_ID, DECK, RANKS, combo_percentile, hand_class, range_equity

# -- 二、翻前：手牌表（v3.1 原文的写法） -----------------------------------------


def _rank(letter):
    return RANKS.index(letter)


def hands(spec):
    """v3.1 的手牌写法展开成 169 类的名字：``"77+ AJs+ KQs 22-66 A2s-A9s 65s-T9s AK"``。"""
    found = set()
    for item in spec.split():
        found |= _hands(item)
    return frozenset(found)


def _hands(item):
    plus = item.endswith("+")
    item = item.rstrip("+")
    if "-" in item:
        low, high = item.split("-")
        if len(low) == 2:                                   # 22-66
            return {RANKS[r] * 2 for r in range(_rank(low[0]), _rank(high[0]) + 1)}
        suffix = low[2]
        if low[0] == high[0]:                               # A2s-A9s
            return {low[0] + RANKS[r] + suffix
                    for r in range(_rank(low[1]), _rank(high[1]) + 1)}
        step = _rank(high[0]) - _rank(low[0])               # 65s-T9s：一起往上
        gap = _rank(low[0]) - _rank(low[1])
        return {RANKS[_rank(low[0]) + i] + RANKS[_rank(low[0]) + i - gap] + suffix
                for i in range(step + 1)}
    if len(item) == 2 and item[0] == item[1]:               # 77 / 77+
        top = len(RANKS) - 1 if plus else _rank(item[0])
        return {RANKS[r] * 2 for r in range(_rank(item[0]), top + 1)}
    high, low = item[0], item[1]
    suffixes = item[2:] or "so"                             # AK = AKs + AKo
    lows = range(_rank(low), _rank(high)) if plus else (_rank(low),)
    return {high + RANKS[r] + suffix for r in lows for suffix in suffixes}


# 表 1 · 没人加注时（前面全弃或只有平跟）
TABLE1 = {
    "early": {"raise": hands("77+ AJs+ KQs AQo+"), "limp": hands("22-66 A2s-A9s")},
    "middle": {"raise": hands("55+ ATs+ KJs+ QJs JTs AJo+ KQo"),
               "limp": hands("22-44 A2s-A9s 65s-T9s")},
    "late": {"raise": hands("22+ A2s+ K9s+ Q9s+ J9s+ T9s 98s 87s A9o+ KTo+ QTo+ JTo"),
             "limp": hands("76s 65s")},
}
OPEN_LIMP = ("early",)              # "首个入池也可以"只写在早位
ISOLATE_MANY = hands("TT+ AJs+ AQo+ KQs")          # ≥ 2 个平跟者只用这些隔离
# 表 2 · 面对一次加注
THREE_BET = hands("QQ+ AK")
THREE_BET_VS_LATE = hands("JJ AQs")
FLAT = hands("TT-JJ AQs AJs ATs KQs AQo")
PRICE_CALL = hands("22-99 65s-T9s")
BLIND_DEFEND = hands("22+ A2s+ K9s+ Q9s+ J9s+ 54s-T9s KJo+ ATo+")
SHORT_CALL = hands("55+ A8s+ ATo+ KQ")
SHORT_CALL_ONE = hands("99+ AQ+")
# 表 3 · 面对再加注（3-bet）
JAM = hands("QQ+ AK")
FOUR_BET = hands("KK+")
CALL_THREE_BET = hands("QQ JJ AK")
CALL_THREE_BET_IP = hands("AQs")
VS_FOUR_BET = hands("KK+")
PUSH = hands("77+ ATs+ AJo+ KQs")
PUSH_BUTTON = hands("55+ A2s+ KJo+")
# 蘑菇池（小盲）：池 ≥ 20 个大盲再加
MUSHROOM_WIDE = hands("22+ A2s+ K9s+")

# -- v3.1 的数字 ---------------------------------------------------------------
OPEN_CAP = 1 / 5                    # 开池加注封顶有效筹码的 1/5
THREE_BET_TIMES = 3                 # 再加注到 3 倍加注额，每个跟注者再加 1 倍
PRICE_SHARE = 0.15                  # 看价格跟注：跟注额 ≤ 有效筹码 15%
BLIND_CALLERS = 2                   # 盲位防守：≥ 2 人已跟
BLIND_POT = 0.25                    # 且跟注 ≤ 底池 1/4
SHORT_ALL_IN_BB = 15                # 面对 ≤ 15 个大盲的翻前全下
JAM_SHARE = 0.30                    # 表 3：再加注额占有效筹码 ≥ 30%
PUSH_FOLD_BB = 20                   # 表 3：有效筹码 ≤ 20 个大盲改推弃
SPR_LOW = 2                         # 翻牌 SPR ≤ 2
SPR_OPPONENTS = 2                   # 且对手 ≤ 2 个时 B 档视同 A 档
BET = {"A": 2 / 3, "A_river_hu": 3 / 4, "B": 1 / 2, "B_river": 1 / 3,
       "D_strong": 2 / 3, "D": 1 / 2, "C": 1 / 3, "mushroom": 1 / 3}
RAISE_TIMES = 3                     # 翻后加注到 3 倍
B_CALL_HU = {"flop": 2 / 3, "turn": 2 / 3, "river": 1 / 2}
B_CALL_TWO = 1.0                    # 还剩 2 个对手：下注 ≤ 1 倍底池跟
B_CALL_MANY = 1 / 2                 # ≥ 3 个对手：≤ 1/2 底池跟
C_CALL_FLOP = 1 / 2                 # C 档单挑翻牌跟一次 ≤ 1/2 底池
D_STRONG_RAISE = 1 / 2              # D-强 翻牌面对 ≤ 1/2 底池的下注加注
OUT_SHARE, OUT_SHARE_ALL_IN = 0.02, 0.04       # 胜率 = 补牌 × 2%（对方全下 × 4%）
ALL_IN_MARGIN = 0.05                # 面对全下：胜率 ≥ 所需胜率 + 5% 才跟
B_RAISED_SPR = 1                    # B 档翻牌被加注：跟注后 SPR ≤ 1 才算
IRON_SHARE = 1 / 3                  # 铁律 1：翻后投入 ≤ 有效筹码的 1/3
JAM_AFTER_CALL = 1 / 2              # 跟注后剩余 ≤ 1/2 底池 → 按面对全下
JAM_RAISE_SHARE = 0.40              # A 档加注到 3 倍 ≥ 剩余筹码 40% → 全下
MUSHROOM_BB, MUSHROOM_WIDE_BB = 10, 20
MUSHROOM_PLAYERS = 4                # 蘑菇池满 4 人才有（scoreboard.mushroom）
# 四、对手范围：翻前按最后一个动作（169 类按强度排）
PREFLOP_RANGE = {"limp": (0.04, 0.50), "raise": (0.0, 0.12),
                 "raise_early": (0.0, 0.10), "raise_late": (0.0, 0.15),
                 "call_raise": (0.06, 0.31), "three_bet": (0.0, 0.06),
                 "call_three_bet": (0.03, 0.10)}
# 翻后每条街缩一次（按这副公共牌上对随机手的胜率排序，从翻前范围连乘）
KEEP = {("call", "flop"): 0.35, ("call", "turn"): 0.55, ("call", "river"): 0.45,
        ("bet", "flop"): 0.40, ("bet", "turn"): 0.40, ("bet", "river"): 0.40,
        ("raise", "flop"): 0.10, ("raise", "turn"): 0.08, ("raise", "river"): 0.05,
        ("all_in", "river"): 0.05}

# v3.1 有两种读法的地方选了哪一种（PR 1 描述里同样列出，主人可以改）。
READINGS = {
    "iso_many": "≥ 2 个平跟者时不在隔离表里、在本位置加注表里的牌（A9o/KTo 这类）"
                "'改为平跟或弃'：在本位置平跟表里就平跟，否则弃（拿不准就弃）",
    "limp_first": "'首个入池也可以'只写在早位：中位、晚位的平跟表要前面已有人平跟",
    "blind_one_limper": "盲位面对 1 个平跟者'用本位置的加注范围'，盲位没有加注范围：抓头过牌，"
                        "小盲、大盲没写 → 铁律 5",
    "mushroom_iso": "小盲蘑菇池隔离：1 个平跟者用晚位加注表，≥ 2 个用 TT+、AJs+、AQo+、KQs，"
                    "池 ≥ 20 个大盲时再加 22+、A2s+、K9s+",
    "push_fold": "'有效筹码 ≤ 20 个大盲改推弃'写在表 3 下面：只用于面对再加注",
    "four_bet_size": "表 3 的 4-bet 没写尺寸：按 3 倍再加注额，剩余 ≤ 底池就全下",
    "call_ip": "表 3 跟注一行'（有位置）'只管 AQs",
    "full_house": "降档只降暗三和两对：葫芦以上比同花顺子大，不降",
    "four_straight": "'四张连牌'按字面：公共牌里有四张点数相连",
    "board_pair": "'公共牌对子 + 你的高牌'：公共牌有对子、你自己没成对，都算 C",
    "board_plays": "河牌五张公共牌自己成顺子、同花、葫芦以上，你的牌用不上：档分不出 → 铁律 5",
    "outs": "补牌按同花听 9 张、顺子听每个能成顺的点数 4 张（去掉看得见的），两样重叠的只算一次；"
            "高牌不算补牌",
    "one_street": "翻后'每条街缩一次'：这条街他最凶的那个动作（加注 > 下注 > 跟注）",
    "river_raise": "B 档河牌'这手没人加注过'：翻牌以后没人加注过（翻前加注不算）",
    "iron1_stack": "铁律 1 和 SPR 的有效筹码：翻牌开始时你和还在局里最深的对手较小的那个",
    "iron1_spr": "铁律 1 的'例外：翻牌 SPR ≤ 2'和 SPR 规则一样只在对手 ≤ 2 个时用",
    "d_all_in": "听牌面对全下按 D 档那一行（补牌 × 4% 比所需胜率，不加 5%）；"
                "没人全下、跟注后剩余 ≤ 1/2 底池时按阈值 2 原文加 5%",
    "j2_jam": "直接全下阈值 2'按面对全下规则决定'：胜率够就直接全下（这一节叫'直接全下'），"
              "不够就弃；多人底池里 B 档以下的全下再被铁律 2 改回跟注",
    "checked_blind": "翻前只过牌的盲位（没投钱）范围不缩",
    "b_bigger": "B 档单挑面对更大的下注'铁律 1'：跟了以后这手翻后投入仍 ≤ 有效筹码 1/3 就跟，"
                "否则弃",
    "outs_all_in": "'对方全下 × 4%'只在翻牌（还要发两张）；转牌全下只剩一张，仍 × 2%",
    "mushroom_price": "蘑菇池'看价格跟注门槛放到 15%'：v3.1 的门槛本来就是 15%，"
                      "小盲有蘑菇池时不变，其余条件照旧",
    "spr_many_streets": "≥ 3 个对手、SPR ≤ 2 的 B 档'没人下注下 1/2'只在翻牌；"
                        "转牌、河牌照多人 B 档那一行过牌",
    "iron4_bet": "铁律 4'不加注'只禁加注：表里 D 档单挑翻牌下 1/2 照下；"
                 "面对下注时只有单挑翻牌 D-强 能加注",
    "iron1_draws": "铁律 1'一对不送筹码，B 档及以下'不管 D 档听牌：听牌按铁律 4 的价格"
                   "（不然'补牌够价可以跟全下'永远用不上）；B、C、E 档照铁律 1",
    "r_b_iron1": "铁律高于所有表：B 档翻牌被加注'跟注后 SPR ≤ 1 算胜率全下'碰到铁律 1"
                 "（翻后投入 ≤ 1/3）时弃；翻牌 SPR ≤ 2 时 B 已视同 A，所以这一行实际总是弃",
    "spr_many_jam": "≥ 3 个对手、SPR ≤ 2 的 B 档'下 1/2'：下完剩的 ≤ 底池，按直接全下阈值 1 "
                    "变全下，再被铁律 1 拦下 → 实际过牌",
    "j2_all_in": "直接全下阈值 2（跟注后剩 ≤ 1/2 底池）不管对手已经全下：翻前按表 2 短筹码行和"
                 "表 3 第一行，翻后按'面对全下'",
    "range_now": "缩范围算上你正面对的这一下（面对翻牌加注按'前 10%'、河牌全下按'前 5%'）；"
                 "灵魂里理由句示例没把转牌这一注算进去，按第四节的表算",
}

# -- 规则编号：日志、体检单和窗口都用这些 ----------------------------------------
RULES = {
    "S1": "第 1 步·看不清 → 铁律 5",
    "T1.raise": "表 1·表内开池加注",
    "T1.limp": "表 1·平跟",
    "T1.out": "表 1·表外不入池（不偷）",
    "T1.iso1": "表 1·隔离 1 个平跟者",
    "T1.iso2": "表 1·≥ 2 个平跟者只用 TT+、AJs+、AQo+、KQs 隔离",
    "T1.iso2.no": "表 1·≥ 2 个平跟者，这手改为平跟或弃",
    "T1.straddle": "表 1·抓头面对平跟不加注就过牌",
    "T2.3bet": "表 2·再加注到 3 倍",
    "T2.call": "表 2·跟注（不限筹码）",
    "T2.price": "表 2·看价格跟注",
    "T2.blind": "表 2·盲位 / 抓头防守",
    "T2.short": "表 2·面对 ≤ 15 个大盲的全下",
    "T2.fold": "表 2·弃牌",
    "T3.allin": "表 3·面对翻前全下按第一行",
    "T3.jam": "表 3·再加注占筹码 ≥ 30%",
    "T3.4bet": "表 3·4-bet KK+",
    "T3.call": "表 3·跟注再加注",
    "T3.fold": "表 3·弃牌",
    "T3.push20": "表 3·有效筹码 ≤ 20 个大盲推弃",
    "T3.vs4bet": "表 3·被 4-bet 只有 KK+ 继续",
    "M.iso": "蘑菇池·小盲按晚位表隔离",
    "M.flop": "蘑菇池·小盲翻牌下 1/3 一次",
    "N.A": "没人下注·A 档",
    "N.B": "没人下注·B 档",
    "N.D_strong": "没人下注·D-强",
    "N.D": "没人下注·D 档",
    "N.C": "没人下注·C 档",
    "N.E": "没人下注·E 档",
    "N.turn": "转牌不追",
    "F.A": "面对下注·A 档",
    "F.B": "面对下注·B 档",
    "F.D_strong": "面对下注·D-强",
    "F.D": "面对下注·D 档按补牌",
    "F.C": "面对下注·C 档",
    "F.E": "面对下注·E 档",
    "R.A": "面对加注·A 档",
    "R.B": "面对加注·B 档",
    "R.D": "面对加注·D 档按补牌",
    "R.CE": "面对加注·C、E 档弃",
    "SPR.A": "SPR ≤ 2 且对手 ≤ 2：B 档视同 A 档",
    "SPR.many": "SPR ≤ 2、≥ 3 个对手：B 档下 1/2、跟一次、被加注弃",
    "ALLIN": "面对全下：胜率 ≥ 所需 + 5% 才跟",
    "J1": "直接全下·下注后剩余 ≤ 底池",
    "J2": "直接全下·跟注后剩余 ≤ 1/2 底池按面对全下",
    "J3": "直接全下·A 档加注 ≥ 剩余筹码 40%",
    "I1": "铁律 1·一对不送筹码",
    "I2": "铁律 2·多人底池只打 A 档",
    "I3": "铁律 3·河牌不诈唬",
    "I4": "铁律 4·听牌按价格",
    "I5": "铁律 5·拿不准就弃",
    "DOWN": "公共牌三张同花或四张连牌：降一档",
}
# v3.1 没写的情形（按铁律 5，记 unspecified）
UNSPECIFIED = {
    "blind_unopened": "盲位前面全弃（没人平跟）：v3.1 没写",
    "blind_one_limper": "小盲、大盲面对 1 个平跟者：盲位没有加注范围",
    "blind_not_isolating": "小盲、大盲面对平跟者、这手不隔离：补齐还是弃没写",
    "board_plays": "五张公共牌自己成牌，你的牌用不上：档分不出",
    "no_range": "对手范围算不出来",
    "b_two_texture": "B 档还剩 2 个对手、公共牌三张同花或四张连牌时面对下注：没写",
    "seats": "人数不在 4–8 人",
}
STREETS = ("preflop", "flop", "turn", "river")
STREET_WORD = {"preflop": "翻前", "flop": "翻牌", "turn": "转牌", "river": "河牌"}
POSITION_WORD = {"early": "早位", "middle": "中位", "late": "晚位", "blind": "盲位"}
TIER_WORD = {"A": "A 档", "B": "B 档", "D": "D 档", "D_strong": "D-强", "C": "C 档",
             "E": "E 档"}
TRIALS, PREFLOP_TRIALS = 2500, 1500
FLOP_RUNOUTS = 40                   # 翻牌上给每手牌排强弱时发的转牌、河牌
EPSILON = 1e-9


# -- 第 4 步：牌力（五档、降档、补牌） -----------------------------------------
_EVAL = {5: _pheval.evaluate_5cards, 6: _pheval.evaluate_6cards,
         7: _pheval.evaluate_7cards}
# phevaluator 的名次（越小越强）分界：同花顺 10、四条 166、葫芦 322、同花 1599、
# 顺子 1609、三条 2467、两对 3325、一对 6185
CATEGORY = ((10, "straight_flush"), (166, "quads"), (322, "full_house"),
            (1599, "flush"), (1609, "straight"), (2467, "trips"),
            (3325, "two_pair"), (6185, "pair"), (7462, "high_card"))
MADE = ("straight_flush", "quads", "full_house", "flush", "straight")
BEATS_STRAIGHT = ("straight_flush", "quads", "full_house")


def best(cards):
    """phevaluator 名次（越小越强）。"""
    return _EVAL[len(cards)](*(CARD_ID[card] for card in cards))


def category(rank):
    return next(name for top, name in CATEGORY if rank <= top)


def value(card):
    return _rank(card[0]) + 2


def _straight_in(values):
    """一组点数（含 A 当 1）里有没有五张相连。"""
    present = set(values) | ({1} if 14 in values else set())
    return any(all(low + i in present for i in range(5)) for low in range(1, 11))


def suited_three(board):
    return any(sum(card[1] == suit for card in board) >= 3 for suit in "cdhs")


def four_straight(board):
    """公共牌里有四张点数相连（A 可当 1）。"""
    present = {value(card) for card in board}
    present |= {1} if 14 in present else set()
    return any(all(low + i in present for i in range(4)) for low in range(1, 12))


@dataclass(frozen=True)
class Strength:
    tier: str                   # A B D C E（D-强 也是 D）
    strong_draw: bool = False   # D-强
    was: str | None = None      # 降档前的档
    made: str = "high_card"     # 成牌种类
    words: str = ""             # 说给人听："暗三"、"顶对踢脚 K"、"同花听牌"
    outs: int = 0
    flush_draw: bool = False
    straight_outs: int = 0
    board_plays: bool = False   # 五张公共牌自己成牌，你的牌用不上


def classify(hole, board):
    """五档（A → B → D → C → E 第一条命中）和降档；只在翻后用。"""
    hole, board = tuple(hole), tuple(board)
    mine = best(hole + board)
    made = category(mine)
    hv = sorted((value(card) for card in hole), reverse=True)
    bv = sorted((value(card) for card in board), reverse=True)
    pocket = hv[0] == hv[1]
    top = bv[0]
    board_plays = len(board) == 5 and made in MADE and mine == best(board)
    paired = [v for v in hv if v in bv]
    tier, words = None, ""
    if board_plays:
        return Strength("E", made=made, words="公共牌自己成牌", board_plays=True)
    if made in MADE:
        tier, words = "A", {"straight_flush": "同花顺", "quads": "四条",
                            "full_house": "葫芦", "flush": "同花", "straight": "顺子"}[made]
    elif pocket and hv[0] in bv:
        tier, words = "A", "暗三"
    elif not pocket and hv[0] in bv and hv[1] in bv:
        tier, words = "A", "两对"
    elif pocket and hv[0] > top:
        tier, words = "B", "超对"
    elif not pocket and top in hv:
        kicker = hv[1] if hv[0] == top else hv[0]
        if kicker >= 10:
            tier, words = "B", f"顶对踢脚 {RANKS[kicker - 2]}"
    draws = _draws(hole, board) if len(board) < 5 else (False, 0, 0)
    flush_draw, straight_outs, outs = draws
    strong = flush_draw and (hv[0] > top or straight_outs >= 8)
    if tier is None and (flush_draw or straight_outs >= 8):
        tier = "D"
        words = ("同花听牌" if flush_draw else "两头顺听牌") + (
            "加两头顺" if flush_draw and straight_outs >= 8 else
            "加高张" if strong else "")
    if tier is None:
        if pocket:
            tier, words = "C", "中对"
        elif paired:
            tier, words = "C", ("弱顶对" if paired[0] == top
                                else "第二对" if len(set(bv)) > 1 and paired[0] == sorted(
                                    set(bv), reverse=True)[1] else "底对")
        elif len(set(bv)) < len(bv):
            tier, words = "C", "公共牌对子 + 你的高牌"
        else:
            tier, words = "E", "空气"
    was = None
    if suited_three(board) or four_straight(board):
        if tier == "A" and made not in MADE:
            tier, was = "B", "A"
        elif tier == "B":
            tier, was = "C", "B"
    return Strength(tier, strong and tier == "D", was, made, words, outs if tier == "D"
                    else 0, flush_draw, straight_outs, False)


def _draws(hole, board):
    """(同花听牌, 顺子补牌张数, 补牌总张数)：只算用得上你手牌的。"""
    cards = hole + board
    seen = set(cards)
    flush_suit = next((suit for suit in "cdhs"
                       if sum(card[1] == suit for card in cards) == 4
                       and any(card[1] == suit for card in hole)), None)
    outs = set()
    if flush_suit:
        outs |= {card for card in DECK if card[1] == flush_suit and card not in seen}
    values = {value(card) for card in cards}
    board_values = {value(card) for card in board}
    straight = set()
    if not _straight_in(values):
        for rank in range(2, 15):
            if (_straight_in(values | {rank})
                    and not _straight_in(board_values | {rank})):
                straight |= {card for card in DECK if value(card) == rank
                             and card not in seen}
    outs |= straight
    return bool(flush_suit), len(straight), len(outs)


def nuts(hole, board):
    """现在这副公共牌上没有任何两张能赢你。"""
    seen = set(hole) | set(board)
    mine = best(tuple(hole) + tuple(board))
    rest = [card for card in DECK if card not in seen]
    return all(best((a, b) + tuple(board)) >= mine for a, b in combinations(rest, 2))


# -- 第 2 步：什么局（从牌桌的观察里读出来） ----------------------------------

@dataclass(frozen=True)
class Act:
    seat: int
    street: str
    kind: str                   # fold check call bet raise
    paid: float
    to: float | None            # 下注、加注：这条街他一共下到多少
    pot: float                  # 这个动作之前的底池
    facing: int                 # 这条街在它之前有几次下注、加注
    all_in: bool                # 做完这个动作他没筹码了
    callers: int = 0            # 翻前：这次加注之前有几个人平跟


def seat_classes(observation):
    """{座位: (早/中/晚/盲, 名字)}：抓头后 2 人早位、再 2 人中位、CO 和庄位晚位；
    人少时先去掉早位；小盲、大盲、抓头为盲位。"""
    occupied = list(observation["occupied_seats"])
    start = occupied.index(observation["dealer_seat"])
    clockwise = occupied[start:] + occupied[:start]          # 庄、小盲、大盲……
    straddler = observation.get("straddler_seat")
    names = {}
    if len(clockwise) >= 3:
        names[clockwise[1]], names[clockwise[2]] = "SB", "BB"
    elif len(clockwise) == 2:
        names[clockwise[0]], names[clockwise[1]] = "SB", "BB"
    if straddler is not None:
        names[straddler] = "STR"
    blinds = [seat for seat in clockwise if seat in names]
    last = max(clockwise.index(seat) for seat in blinds) if blinds else 0
    others = (clockwise[last + 1:]
              + [seat for seat in clockwise[:1] if seat not in names])
    late = min(2, len(others))
    middle = min(2, len(others) - late)
    classes = {}
    for index, seat in enumerate(others):
        from_end = len(others) - index
        classes[seat] = ("late" if from_end <= late else
                         "middle" if from_end <= late + middle else "early")
    if others:
        names.setdefault(others[-1], "BTN")
        if len(others) >= 2:
            names.setdefault(others[-2], "CO")
    return {seat: (classes.get(seat, "blind"), names.get(seat, ""))
            for seat in occupied}


class Table:
    """第 2 步：牌桌上的事实，都从观察（``AAFullHandArena.observe``）里来。

    实时窗口（``aa_plain_advice``）给的观察里，没读到筹码的对手不在 ``stacks`` 里：
    他不算进有效筹码（按最深的已读对手，补充一澄清 2），也不当他全下；
    ``flop_pot`` 给了就用它当翻牌开始时的底池（按手锁存的那个）。"""

    def __init__(self, observation):
        o = self.observation = observation
        self.me = o["observing_seat"]
        self.hole = tuple(o["own_hole"])
        self.board = tuple(card for card in o["board"] if card)
        self.street = o["street"]
        self.big_blind = float(o["big_blind"] if "big_blind" in o
                               else o["rules"]["big_blind"])
        self.bomb = o.get("bomb_pot") is not None
        folded = set(o["folded"])
        self.live = [seat for seat in o["occupied_seats"] if seat not in folded]
        self.opponents = [seat for seat in self.live if seat != self.me]
        self.pot = float(o["pot"])
        self.to_call = float(o["to_call"] or 0)
        bets = {int(seat): float(chips) for seat, chips in o["bets"].items()}
        self.my_bet = bets[self.me]
        self.top = max(bets.values())
        self.behind = {int(seat): float(chips) for seat, chips in o["stacks"].items()}
        self.stack = self.behind[self.me]
        betting = o.get("betting") or {}
        self.can_raise = bool(betting.get("can_raise", True))
        self.min_raise_to = _number(betting.get("min_raise_to"))
        self.max_raise_to = _number(betting.get("max_raise_to"))
        self.chip = float((o.get("rules") or {}).get("minimum_chip") or 1)
        self.classes = seat_classes(o)
        self.acts, self.flop_pot, self.flop_behind, self.totals = self._read(o)
        preflop = [act for act in self.acts if act.street == "preflop"]
        raisers = [act.seat for act in preflop if act.kind == "raise"]
        self.raiser = raisers[-1] if raisers and not self.bomb else None   # 翻前加注者
        self.mushroom = self._mushroom(o)

    def _read(self, o):
        """每个动作的种类、之前的底池、全下没有；翻牌开始时的底池和每人剩的筹码。"""
        rows = o["public_history"]
        paid = {}
        for row in rows:
            chips = float(row.get("paid") or 0)
            paid[row["actor"]] = paid.get(row["actor"], 0.0) + chips
        contributions = {int(seat): float(chips)
                         for seat, chips in o["contributions"].items()}
        start = {seat: chips - paid.get(seat, 0.0)
                 for seat, chips in contributions.items()}
        totals = {seat: self.behind[seat] + chips
                  for seat, chips in contributions.items() if seat in self.behind}
        behind = {seat: totals[seat] - start[seat] for seat in totals}
        pot = self.pot - sum(paid.values())
        ante = 0.0 if self.bomb else float((o.get("rules") or {}).get("ante") or 0)
        street_bets = {seat: max(0.0, start[seat] - ante) for seat in start}
        street, facing, limps = "preflop", 0, 0
        acts, flop_pot, flop_behind = [], None, None
        if self.bomb:
            street, street_bets = "flop", dict.fromkeys(start, 0.0)
        for row in rows:
            if row["street"] != street:
                street, facing = row["street"], 0
                street_bets = dict.fromkeys(street_bets, 0.0)
            if street != "preflop" and flop_pot is None:
                flop_pot, flop_behind = pot, dict(behind)
            seat, chips = row["actor"], float(row.get("paid") or 0)
            top = max(street_bets.values())
            if row["kind"] == "fold":
                kind = "fold"
            elif row["kind"] == "check_call":
                kind = "call" if chips > 0 else "check"
            else:
                kind = "bet" if street != "preflop" and top <= 0 else "raise"
            to = float(row["raise_to"]) if row.get("raise_to") is not None else None
            if seat in behind:
                behind[seat] -= chips
            acts.append(Act(seat, street, kind, chips, to, pot, facing,
                            kind != "fold" and behind.get(seat, 1.0) <= EPSILON,
                            limps if kind == "raise" and street == "preflop" else 0))
            if street == "preflop" and kind == "call" and facing == 0:
                limps += 1
            street_bets[seat] += chips
            pot += chips
            if kind in ("bet", "raise"):
                facing += 1
        if self.street != "preflop" and flop_pot is None:
            flop_pot, flop_behind = pot, dict(behind)
        if o.get("flop_pot") is not None and self.street != "preflop":
            flop_pot = float(o["flop_pot"])
        return acts, flop_pot, flop_behind, totals

    def _mushroom(self, o):
        """小盲且蘑菇池 ≥ 10 个大盲时的池（大盲数），否则 0：不在小盲位一律不算。"""
        pool = _number(o.get("mushroom_pool"))
        if (not pool or len(o["occupied_seats"]) < MUSHROOM_PLAYERS
                or self.classes[self.me][1] != "SB"):
            return 0.0
        pool_bb = pool / self.big_blind
        return pool_bb if pool_bb >= MUSHROOM_BB else 0.0

    # -- 局面里常用的数 ---------------------------------------------------------

    def bb(self, chips):
        return chips / self.big_blind

    def street_acts(self, street=None):
        street = street or self.street
        return [act for act in self.acts if act.street == street]

    def facing(self):
        """这条街在你之前有几次下注、加注。"""
        return sum(act.kind in ("bet", "raise") for act in self.street_acts())

    def aggressor(self):
        """这条街最后一个下注、加注的动作。"""
        return next((act for act in reversed(self.street_acts())
                     if act.kind in ("bet", "raise")), None)

    def effective(self):
        """有效筹码（这手开始时）：你和还在局里最深的对手较小的那个；筹码没读到的
        对手不算，一个都没读到就按你的。"""
        deepest = max((self.totals[seat] for seat in self.opponents
                       if seat in self.totals), default=self.totals[self.me])
        return min(self.totals[self.me], deepest)

    def effective_flop(self):
        """翻牌开始时的有效筹码（剩在手里的）。"""
        behind = self.flop_behind or self.behind
        deepest = max((behind[seat] for seat in self.opponents if seat in behind),
                      default=behind[self.me])
        return min(behind[self.me], deepest)

    def spr(self):
        """SPR = 翻牌时有效筹码 ÷ 底池。"""
        pot = self.flop_pot if self.flop_pot is not None else self.pot
        return self.effective_flop() / pot if pot > 0 else float("inf")

    def need(self):
        """所需胜率 = 你要跟的金额 ÷（底池 + 你要跟的金额）；面对短筹码的全下按他的
        筹码算（你赢得到的部分）；小盲的蘑菇池全额算进底池。"""
        if self.to_call <= 0:
            return 0.0
        pot = matched_pot(self.observation) + self.mushroom * self.big_blind
        return self.to_call / pot if pot > 0 else 1.0

    def postflop_put(self):
        """你这手翻牌以后已经投入的筹码。"""
        return sum(act.paid for act in self.acts
                   if act.seat == self.me and act.street != "preflop")

    def in_position(self, other):
        """翻后你在 ``other`` 后面说话（小盲先说，庄位最后）。"""
        occupied = list(self.observation["occupied_seats"])
        start = occupied.index(self.observation["dealer_seat"])
        clockwise = occupied[start:] + occupied[:start]
        order = {seat: (clockwise.index(seat) - 1) % len(clockwise)
                 for seat in clockwise}
        return order[self.me] > order[other]

    def raised_after_flop(self):
        return any(act.kind == "raise" and act.street != "preflop" for act in self.acts)


def _number(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


# -- 第 3 步：他们拿什么（第四节的固定范围） -----------------------------------
PAIRS = list(combinations(range(52), 2))
KEYS = [combo_key((DECK[a], DECK[b])) for a, b in PAIRS]
_FIRST = np.array([a for a, _ in PAIRS])
_SECOND = np.array([b for _, b in PAIRS])
_HOLDS = np.array([(_FIRST == card) | (_SECOND == card) for card in range(52)])
PREFLOP_PLACE = np.array([combo_percentile((DECK[a], DECK[b])) for a, b in PAIRS])


def alive(cards):
    ids = [CARD_ID[card] for card in cards if card]
    if not ids:
        return np.ones(len(PAIRS), bool)
    return ~_HOLDS[ids].any(axis=0)


@lru_cache(maxsize=4096)
def _strength(board):
    """每两张牌在这副公共牌上对一手随机牌的胜率（河牌精确、转牌发完每张河牌、翻牌发
    ``FLOP_RUNOUTS`` 组转牌河牌）；用到公共牌的为 -1。"""
    rest = [card for card in range(52) if card not in board]
    if len(board) == 5:
        runouts = [()]
    elif len(board) == 4:
        runouts = [(card,) for card in rest]
    else:
        rng = random.Random(hashlib.sha256(repr(board).encode()).digest())
        runouts = [tuple(rng.sample(rest, 5 - len(board))) for _ in range(FLOP_RUNOUTS)]
    total = np.zeros(len(PAIRS))
    count = np.zeros(len(PAIRS))
    evaluate = _pheval.evaluate_7cards
    for extra in runouts:
        full = (*board, *extra)
        live = ~_HOLDS[list(full)].any(axis=0)
        index = np.flatnonzero(live)
        ranks = np.array([evaluate(int(_FIRST[i]), int(_SECOND[i]), *full)
                          for i in index])
        order = np.sort(ranks)
        worse = len(ranks) - np.searchsorted(order, ranks, side="right")
        ties = (np.searchsorted(order, ranks, side="right")
                - np.searchsorted(order, ranks, side="left") - 1)
        total[index] += (worse + 0.5 * ties) / max(len(ranks) - 1, 1)
        count[index] += 1
    strength = np.full(len(PAIRS), -1.0)
    seen = count > 0
    strength[seen] = total[seen] / count[seen]
    return strength


def board_strength(board):
    return _strength(tuple(sorted(CARD_ID[card] for card in board)))


def keep_top(weights, strength, share):
    """留下范围里最强的 ``share``（按权重）。"""
    order = np.argsort(-strength, kind="stable")
    ordered = weights[order]
    total = ordered.sum()
    if total <= 0:
        return weights
    place = np.empty(len(weights))
    place[order] = (np.cumsum(ordered) - ordered / 2) / total
    return np.where(place <= share, weights, 0.0)


@dataclass
class Read:
    """一个对手的范围和怎么来的（"前 12%×35%"）。"""
    seat: int
    weights: np.ndarray
    preflop: str                # 翻前最后动作：limp raise call_raise three_bet ...
    words: str                  # "前 12%×35%"
    story: str                  # "他翻前加注、翻牌跟注"


ACTION_WORD = {"limp": "平跟", "raise": "加注", "call_raise": "跟注了加注",
               "three_bet": "再加注", "all_in": "全下", "call_three_bet": "跟注了再加注",
               None: "没投钱", "bomb": "暴击局"}
STREET_ACTION_WORD = {"call": "跟注", "bet": "下注", "raise": "加注", "all_in": "全下"}


def preflop_action(table, seat):
    """他翻前最后一个动作在第四节的哪一行，和用的范围（下限, 上限）。"""
    if table.bomb:
        return "bomb", (0.0, 1.0)
    last = None
    raises = 0
    for act in table.street_acts("preflop"):
        if act.seat == seat:
            if act.kind == "raise":
                if act.all_in or raises >= 1:
                    last = "all_in" if act.all_in and raises == 0 else "three_bet"
                else:
                    last = "raise"
            elif act.kind == "call":
                last = ("limp" if raises == 0 else
                        "call_raise" if raises == 1 else "call_three_bet")
        if act.kind == "raise":
            raises += 1
    if last is None:
        return None, (0.0, 1.0)
    if last == "raise":
        where = table.classes[seat][0]
        key = {"early": "raise_early", "late": "raise_late"}.get(where, "raise")
        return last, PREFLOP_RANGE[key]
    return last, PREFLOP_RANGE["three_bet" if last == "all_in" else last]


def _band_words(low, high):
    if high >= 1.0 and low <= 0:
        return "全部的牌"
    text = f"前 {high:.0%}"
    return text + (f" 去掉前 {low:.0%}" if low > 0 else "")


def read_range(table, seat):
    """第四节：翻前最后动作定范围，翻后每条街按他最凶的动作缩一次。"""
    kind, (low, high) = preflop_action(table, seat)
    dead = alive(table.hole)
    weights = ((PREFLOP_PLACE > low) & (PREFLOP_PLACE <= high) & dead).astype(float)
    words = _band_words(low, high)
    story = [f"翻前{ACTION_WORD[kind]}"] if kind not in (None, "bomb") else []
    for street in STREETS[1:STREETS.index(table.street) + 1]:
        mine = [act for act in table.street_acts(street) if act.seat == seat]
        order = ("call", "bet", "raise")
        strongest = None
        for act in mine:
            if act.kind in order and (strongest is None or order.index(act.kind)
                                      > order.index(strongest[0])):
                strongest = (act.kind, act)
        if strongest is None:
            continue
        action, act = strongest
        if street == "river" and action in ("bet", "raise") and act.all_in:
            action = "all_in"
        share = KEEP[(action, street)]
        board = table.board[:{"flop": 3, "turn": 4, "river": 5}[street]]
        weights = keep_top(weights * alive(board), board_strength(board), share)
        words += f"×{share:.0%}"
        story.append(f"{STREET_WORD[street]}{STREET_ACTION_WORD[action]}")
    weights = weights * alive(table.board)
    return Read(seat, weights, kind, words, "、".join(story) or ACTION_WORD[kind])


def ranges(table):
    return {seat: read_range(table, seat) for seat in table.opponents}


def equity(table, reads, trials=None):
    """你对他们范围的胜率（有边池时每个池对能赢它的人算）；算不出来为 None。"""
    if not reads:
        return None
    weights = {seat: {KEYS[i]: float(read.weights[i])
                      for i in np.flatnonzero(read.weights > 0)}
               for seat, read in reads.items()}
    if not all(weights.values()):
        return None
    layers = side_pots(table.observation) if table.street != "preflop" else None
    if len(weights) == 1 and len(table.board) >= 4 and not (layers and len(layers) > 1):
        (single,) = weights.values()
        value, _ = range_equity(table.hole, table.board, single)
        return value
    digest = hashlib.sha256("|".join((",".join(table.hole), ",".join(table.board),
                                      str(len(table.acts)))).encode()).digest()
    value, _ = ranges_equity(
        table.hole, table.board, weights,
        trials=trials or (PREFLOP_TRIALS if table.street == "preflop" else TRIALS),
        seed=int.from_bytes(digest[:4], "big"),
        pots=layers if layers and len(layers) > 1 else None)
    return value


# -- 建议 ----------------------------------------------------------------------

@dataclass
class Advice:
    action: str                 # fold check call bet raise
    to: float | None = None     # 下注、加注：这条街你一共下到多少
    rule: str = ""              # 定生死的那一条（``RULES``）
    hits: list = field(default_factory=list)   # 一路命中的规则，最后一条定生死
    all_in: bool = False
    unspecified: str | None = None             # v3.1 没写的情形（``UNSPECIFIED``）
    tier: str | None = None
    hand: str = ""              # "AJo" 或 "顶对踢脚 K"
    equity: float | None = None
    need: float | None = None
    range_words: str = ""       # "前 12%×35%"
    situation: str = ""         # 第 2 步说的话
    story: str = ""             # 第 3 步说的话
    flip: str = ""              # 翻转条件
    reason: str = ""            # 一句话理由（六步串起来）

    def hit(self, rule):
        self.hits.append(rule)
        self.rule = rule
        return self

    def row(self):
        """日志和窗口用的样子。"""
        item = {"action": self.action, "rule": self.rule,
                "rule_label": RULES[self.rule],
                "hits": list(self.hits), "reason": self.reason, "flip": self.flip,
                "range": self.range_words,
                "equity": None if self.equity is None else round(self.equity, 3),
                "need": None if self.need is None else round(self.need, 3),
                "tier": self.tier, "hand": self.hand, "all_in": self.all_in}
        if self.to is not None:
            item["to"] = round(self.to, 2)
        if self.unspecified:
            item["unspecified"] = self.unspecified
        return item


def _fold_or_check(table):
    return "fold" if table.to_call > 0 else "check"


def iron5(table, rule="I5", unspecified=None):
    """铁律 5：面对下注弃，没人下注过牌。"""
    advice = Advice(_fold_or_check(table), unspecified=unspecified)
    return advice.hit(rule)


def _round(table, to):
    chip = table.chip or 1.0
    to = round(to / chip) * chip
    if table.min_raise_to is not None:
        to = max(to, table.min_raise_to)
    if table.max_raise_to is not None:
        to = min(to, table.max_raise_to)
    return to


def _all_in_to(table):
    return table.max_raise_to if table.max_raise_to is not None else (
        table.my_bet + table.stack)


def _aggressive(table, advice, to):
    """下注或加注到 ``to``；直接全下阈值 1：下注或加注后剩余 ≤ 底池 → 全下。"""
    if not table.can_raise or table.stack <= table.to_call + EPSILON:
        advice.action = "call" if table.to_call > 0 else "check"
        advice.to = None
        return advice
    to = _round(table, to)
    left = table.my_bet + table.stack - to
    pot_after = table.pot + (to - table.my_bet)
    if left <= pot_after + EPSILON and to < _all_in_to(table):
        to = _all_in_to(table)
        advice.hit("J1")
    advice.action = "raise" if table.to_call > 0 or table.street == "preflop" else "bet"
    advice.to = to
    advice.all_in = to >= _all_in_to(table) - EPSILON
    return advice


def _bet(table, advice, share):
    return _aggressive(table, advice, table.my_bet + share * table.pot)


def _raise_times(table, advice, times=RAISE_TIMES):
    return _aggressive(table, advice, times * table.top)


# -- 第 6 步（翻前）：三张表 ----------------------------------------------------

def _preflop(table, advice):
    cls = hand_class(table.hole)
    where, name = table.classes[table.me]
    advice.hand = cls
    acts = table.street_acts("preflop")
    raises = [act for act in acts if act.kind == "raise"]
    if not raises:
        return _table1(table, advice, cls, where, name, acts)
    if len(raises) == 1:
        return _table2(table, advice, cls, name, acts, raises[0])
    if len(raises) == 2:
        return _table3(table, advice, cls, name, raises[-1])
    advice.situation = "翻前被 4-bet"
    if cls in VS_FOUR_BET:
        return _aggressive(table, advice.hit("T3.vs4bet"), _all_in_to(table))
    return _fold(advice, "T3.vs4bet")


def _fold(advice, rule):
    advice.action, advice.to = "fold", None
    return advice.hit(rule)


def _call(table, advice, rule):
    advice.action, advice.to = ("call" if table.to_call > 0 else "check"), None
    return advice.hit(rule)


def _open_to(table):
    """开到和底池一样大（每多一个平跟者底池多 2 个大盲），封顶有效筹码的 1/5。"""
    return min(table.pot, OPEN_CAP * table.effective())


def _table1(table, advice, cls, where, name, acts):
    limpers = sum(act.kind == "call" for act in acts)
    advice.situation = (f"翻前{POSITION_WORD[where]}，" +
                        ("前面没人入池" if not limpers else f"前面 {limpers} 人平跟"))
    if where != "blind":
        chart = TABLE1[where]
        if limpers == 0:
            if cls in chart["raise"]:
                return _aggressive(table, advice.hit("T1.raise"), _open_to(table))
            if cls in chart["limp"] and where in OPEN_LIMP:
                return _call(table, advice, "T1.limp")
            return _fold(advice, "T1.out")
        if limpers == 1 and cls in chart["raise"]:
            return _aggressive(table, advice.hit("T1.iso1"), _open_to(table))
        if limpers >= 2 and cls in ISOLATE_MANY:
            return _aggressive(table, advice.hit("T1.iso2"), _open_to(table))
        if cls in chart["limp"]:
            return _call(table, advice, "T1.limp")
        if limpers >= 2 and cls in chart["raise"]:
            return _fold(advice, "T1.iso2.no")
        return _fold(advice, "T1.out")
    # 盲位 / 抓头：面对平跟者按隔离规则；小盲见蘑菇池
    if table.mushroom and name == "SB" and limpers:
        wide = (TABLE1["late"]["raise"] if limpers == 1 else
                ISOLATE_MANY | (MUSHROOM_WIDE if table.mushroom >= MUSHROOM_WIDE_BB
                                else frozenset()))
        if cls in wide:
            return _aggressive(table, advice.hit("M.iso"), _open_to(table))
        return _unspecified(table, advice, "blind_not_isolating")
    if not limpers:
        if table.to_call <= 0:
            return _call(table, advice, "T1.straddle")
        return _unspecified(table, advice, "blind_unopened")
    if limpers >= 2 and cls in ISOLATE_MANY:
        return _aggressive(table, advice.hit("T1.iso2"), _open_to(table))
    if name == "STR":
        return _call(table, advice, "T1.straddle")
    return _unspecified(table, advice, "blind_one_limper" if limpers == 1
                        else "blind_not_isolating")


def _unspecified(table, advice, case):
    advice.unspecified = case
    advice.action, advice.to = _fold_or_check(table), None
    return advice.hit("I5")


def _table2(table, advice, cls, name, acts, raise_act):
    raiser = raise_act.seat
    after = next(index for index, act in enumerate(acts) if act is raise_act)
    callers = sum(act.kind == "call" for act in acts[after + 1:])
    raiser_where = table.classes[raiser][0]
    what = "全下" if raise_act.all_in else "加注"
    advice.situation = (f"翻前{POSITION_WORD[table.classes[table.me][0]]}，面对"
                        f"{POSITION_WORD[raiser_where]}{what}"
                        + (f"、{callers} 人已跟" if callers else ""))
    if raise_act.all_in:
        if table.bb(raise_act.to) <= SHORT_ALL_IN_BB and callers <= 1:
            wanted = SHORT_CALL if callers == 0 else SHORT_CALL_ONE
            if cls in wanted:
                return _call(table, advice, "T2.short")
            return _fold(advice, "T2.short")
        return _table3_first_row(table, advice, cls)
    three = THREE_BET | (THREE_BET_VS_LATE if raiser_where == "late" else frozenset())
    if cls in three and table.can_raise:
        to = THREE_BET_TIMES * raise_act.to + callers * raise_act.to
        return _aggressive(table, advice.hit("T2.3bet"), to)
    if cls in FLAT or cls in three:
        return _call(table, advice, "T2.call")
    if (cls in PRICE_CALL and table.to_call <= PRICE_SHARE * table.effective()
            and (callers >= 1 or table.in_position(raiser))):
        return _call(table, advice, "T2.price")
    if (name in ("SB", "BB", "STR") and callers >= BLIND_CALLERS
            and table.to_call <= BLIND_POT * table.pot and cls in BLIND_DEFEND):
        return _call(table, advice, "T2.blind")
    return _fold(advice, "T2.fold")


def _table3_first_row(table, advice, cls):
    if cls in JAM:
        return _aggressive(table, advice.hit("T3.allin"), _all_in_to(table))
    return _fold(advice, "T3.allin")


def _table3(table, advice, cls, name, raise_act):
    advice.situation = "翻前面对再加注" + ("全下" if raise_act.all_in else "")
    effective = table.effective()
    if table.bb(effective) <= PUSH_FOLD_BB:
        wanted = PUSH | (PUSH_BUTTON if name == "BTN" else frozenset())
        if cls in wanted:
            return _aggressive(table, advice.hit("T3.push20"), _all_in_to(table))
        return _fold(advice, "T3.push20")
    if raise_act.all_in:
        return _table3_first_row(table, advice, cls)
    if raise_act.to >= JAM_SHARE * effective:
        if cls in JAM:
            return _aggressive(table, advice.hit("T3.jam"), _all_in_to(table))
        return _fold(advice, "T3.jam")
    if cls in FOUR_BET and table.can_raise:
        return _aggressive(table, advice.hit("T3.4bet"), THREE_BET_TIMES * raise_act.to)
    if cls in CALL_THREE_BET or cls in FOUR_BET or (
            cls in CALL_THREE_BET_IP and table.in_position(raise_act.seat)):
        return _call(table, advice, "T3.call")
    return _fold(advice, "T3.fold")


# -- 第 6 步（翻后）：没人下注、面对下注、面对加注 ---------------------------------

def _size_words(size):
    for value, words in ((1 / 3, "1/3"), (1 / 2, "1/2"), (2 / 3, "2/3"), (3 / 4, "3/4"),
                         (1.0, "1 倍")):
        if abs(size - value) < 0.03:
            return words + ("" if words.endswith("倍") else " ") + "底池"
    return f"{size:.0%} 底池"


def _my_acts(table, street=None):
    return [act for act in table.acts if act.seat == table.me
            and act.street != "preflop" and (street is None or act.street == street)]


def _postflop(table, advice, context):
    strength = classify(table.hole, table.board)
    context["strength"] = strength
    if strength.board_plays:
        advice.hand = strength.words
        return _unspecified(table, advice, "board_plays")
    opponents = len(table.opponents)
    hu = opponents == 1
    street = table.street
    facing = table.facing()
    agg = table.aggressor()
    advice.tier = "D_strong" if strength.strong_draw else strength.tier
    advice.hand = strength.words
    if strength.was:
        advice.hits.append("DOWN")
    spr = table.spr()
    tier = strength.tier
    spr_a = tier == "B" and spr <= SPR_LOW and opponents <= SPR_OPPONENTS
    spr_many = tier == "B" and spr <= SPR_LOW and opponents > SPR_OPPONENTS
    plays = "A" if spr_a else tier
    context.update(plays=plays, spr=spr, spr_many=spr_many)
    who = "单挑" if hu else f"{opponents + 1} 人"
    if facing == 0:
        advice.situation = f"{STREET_WORD[street]}{who}没人下注"
        return _checked_to(table, advice, strength, plays, spr_many, hu, opponents)
    size = agg.paid / agg.pot if agg.pot > 0 else 1.0
    context["size"] = size
    if facing == 1:
        advice.situation = (f"{STREET_WORD[street]}{who}被"
                            + ("全下" if agg.all_in else f"下注 {_size_words(size)}"))
        return _facing_bet(table, advice, strength, plays, spr_many, hu, opponents,
                           size, agg, context)
    advice.situation = (f"{STREET_WORD[street]}{who}被"
                        + ("加注全下" if agg.all_in else "加注"))
    return _facing_raise(table, advice, strength, plays, spr_many, agg, context)


def _checked_to(table, advice, strength, plays, spr_many, hu, opponents):
    street = table.street
    pfr = table.raiser == table.me
    bet_flop = any(act.kind in ("bet", "raise") for act in _my_acts(table, "flop"))
    if plays == "A":
        share = BET["A_river_hu"] if hu and street == "river" else BET["A"]
        rule = "SPR.A" if strength.tier == "B" else "N.A"
        return _bet(table, advice.hit(rule), share)
    if spr_many:                                 # 下 1/2 只在翻牌（READINGS spr_many_streets）
        if street == "flop":
            return _bet(table, advice.hit("SPR.many"), BET["B"])
        return _call(table, advice, "SPR.many")
    if plays == "B":
        advice.hit("N.B")
        texture = suited_three(table.board) or four_straight(table.board)
        if street == "flop":
            return _bet(table, advice, BET["B"])
        if street == "turn":
            if (hu and not texture) or (not hu and opponents <= 2):
                return _bet(table, advice, BET["B"])
            return _call(table, advice, "N.B")
        if hu and not table.raised_after_flop():
            return _bet(table, advice, BET["B_river"])
        return _call(table, advice, "N.B")
    if street == "turn" and bet_flop:
        return _mushroom_flop(table, _call(table, advice, "N.turn"), opponents)
    if plays == "D":
        if hu and street == "flop":
            if strength.strong_draw:
                return _bet(table, advice.hit("N.D_strong"), BET["D_strong"])
            return _bet(table, advice.hit("N.D"), BET["D"])
        rule = "N.D_strong" if strength.strong_draw else "N.D"
        return _mushroom_flop(table, _call(table, advice, rule), opponents)
    rule = "N.C" if plays == "C" else "N.E"
    if street == "flop" and pfr and opponents <= 2:
        return _bet(table, advice.hit(rule), BET["C"])
    return _mushroom_flop(table, _call(table, advice, rule), opponents)


def _mushroom_flop(table, advice, opponents):
    """蘑菇池：小盲翻牌没人下注且 ≤ 2 个对手时下 1/3 一次。"""
    if (table.mushroom and table.street == "flop" and opponents <= 2
            and advice.action == "check"):
        return _bet(table, advice.hit("M.flop"), BET["mushroom"])
    return advice


def _outs_equity(table, strength, all_in):
    share = OUT_SHARE_ALL_IN if all_in and table.street == "flop" else OUT_SHARE
    return min(1.0, strength.outs * share)


def _by_outs(table, advice, strength, rule, all_in):
    advice.equity = _outs_equity(table, strength, all_in)
    advice.need = table.need()
    if advice.equity >= advice.need - EPSILON:
        return _call(table, advice, rule)
    return _fold(advice, rule)


def _a_raise(table, advice, rule):
    """A 档加注到 3 倍；阈值 3：加注额 ≥ 剩余筹码 40% → 全下。"""
    advice.hit(rule)
    to = RAISE_TIMES * table.top
    if not table.can_raise:
        return _call(table, advice, rule)
    if to - table.my_bet >= JAM_RAISE_SHARE * table.stack:
        advice.hit("J3")
        return _aggressive(table, advice, _all_in_to(table))
    return _aggressive(table, advice, to)


def _facing_bet(table, advice, strength, plays, spr_many, hu, opponents, size, agg,
                context):
    street = table.street
    if plays == "A":
        rule = "SPR.A" if strength.tier == "B" else "F.A"
        if street == "river" and not nuts(table.hole, table.board):
            return _call(table, advice, rule)
        return _a_raise(table, advice, rule)
    if spr_many:
        called = any(act.kind == "call" for act in _my_acts(table))
        if size <= B_CALL_MANY + EPSILON and not called:
            return _call(table, advice, "SPR.many")
        return _fold(advice, "SPR.many")
    if plays == "B":
        if hu:
            if size <= B_CALL_HU[street] + EPSILON:
                return _call(table, advice, "F.B")
            context["bigger"] = True
            advice.hits.append("F.B")
            if _within_iron1(table, table.to_call):
                return _call(table, advice, "I1")
            return _fold(advice, "I1")
        if opponents == 2 and (suited_three(table.board) or four_straight(table.board)):
            return _unspecified(table, advice, "b_two_texture")
        limit = B_CALL_TWO if opponents == 2 else B_CALL_MANY
        if size <= limit + EPSILON:
            return _call(table, advice, "F.B")
        return _fold(advice, "F.B")
    if plays == "D":
        if (strength.strong_draw and hu and street == "flop"
                and size <= D_STRONG_RAISE + EPSILON and table.can_raise
                and not agg.all_in):
            return _raise_times(table, advice.hit("F.D_strong"))
        rule = "F.D_strong" if strength.strong_draw else "F.D"
        return _by_outs(table, advice, strength, rule, agg.all_in)
    if plays == "C":
        if hu and street == "flop" and size <= C_CALL_FLOP + EPSILON:
            return _call(table, advice, "F.C")
        return _fold(advice, "F.C")
    return _fold(advice, "F.E")


def _facing_raise(table, advice, strength, plays, spr_many, agg, context):
    street = table.street
    if plays == "A":
        rule = "SPR.A" if strength.tier == "B" else "R.A"
        if nuts(table.hole, table.board) and table.can_raise and not agg.all_in:
            return _a_raise(table, advice, rule)
        return _call(table, advice, rule)
    if spr_many:
        return _fold(advice, "SPR.many")
    if plays == "B":
        if street != "flop":
            return _fold(advice, "R.B")
        behind = table.stack - table.to_call
        his = table.behind.get(agg.seat, float("inf"))
        pot = table.pot + table.to_call
        if min(behind, his) / pot > B_RAISED_SPR + EPSILON:
            return _fold(advice, "R.B")
        advice.equity = context["equity"]()
        advice.need = table.need()
        if advice.equity is None:
            return _unspecified(table, advice, "no_range")
        if advice.equity >= advice.need + ALL_IN_MARGIN:
            advice.hit("R.B")
            return _aggressive(table, advice, _all_in_to(table))
        return _fold(advice, "R.B")
    if plays == "D":
        return _by_outs(table, advice, strength, "R.D", agg.all_in)
    return _fold(advice, "R.CE")


# -- 第 5 步：什么被禁（面对全下、直接全下、五条铁律） ---------------------------

def _within_iron1(table, chips):
    """铁律 1：B 档及以下这手翻后投入 ≤ 有效筹码的 1/3（例外：翻牌 SPR ≤ 2 且对手 ≤ 2）。"""
    if table.spr() <= SPR_LOW and len(table.opponents) <= SPR_OPPONENTS:
        return True
    return table.postflop_put() + chips <= IRON_SHARE * table.effective_flop() + EPSILON


def _put_now(table, advice):
    if advice.action == "call":
        return table.to_call
    if advice.action in ("bet", "raise") and advice.to is not None:
        return advice.to - table.my_bet
    return 0.0


def _banned(table, advice, context):
    strength = context.get("strength")
    plays = context.get("plays")
    raises = [act for act in table.street_acts() if act.kind in ("bet", "raise")]
    facing_all_in = bool(raises) and raises[-1].all_in
    # 面对全下（翻后）：胜率 ≥ 所需胜率 + 5% 才跟；听牌按 D 档那一行（已按补牌比过）
    if (facing_all_in and table.street != "preflop" and plays != "D"
            and advice.action in ("call", "raise")):
        advice.equity = context["equity"]()
        advice.need = table.need()
        if advice.equity is None:
            _unspecified(table, advice, "no_range")
        elif advice.equity < advice.need + ALL_IN_MARGIN:
            _fold(advice, "ALLIN")
        else:
            advice.action, advice.to = "call", None
            advice.hit("ALLIN")
    # 直接全下阈值 2：跟注后剩余 ≤ 1/2 底池 → 按面对全下决定（够就全下，不够就弃），
    # 不"跟了再看"；对手已经全下时不用它：翻前按表，翻后按面对全下（READINGS j2_all_in）
    if advice.action == "call" and not facing_all_in:
        left = table.stack - table.to_call
        if left <= JAM_AFTER_CALL * (table.pot + table.to_call) + EPSILON:
            if plays == "D":
                advice.equity = _outs_equity(table, strength, True)
            else:
                advice.equity = context["equity"]()
            advice.need = table.need()
            if advice.equity is None:
                _unspecified(table, advice, "no_range")
            elif advice.equity >= advice.need + ALL_IN_MARGIN:
                advice.hit("J2")
                if left > EPSILON and table.can_raise:
                    _aggressive(table, advice, _all_in_to(table))
                advice.all_in = True
            else:
                _fold(advice, "J2")
    if table.street == "preflop" or strength is None or plays is None:
        return advice
    weak = plays != "A"                          # B 档及以下（SPR ≤ 2 的 B 已视同 A）
    one_pair = plays in ("B", "C", "E")          # 铁律 1 不管听牌（READINGS iron1_draws）
    opponents = len(table.opponents)
    # 铁律 4：听牌不加注（单挑翻牌 D-强 例外）；没人下注时的下注按表（READINGS iron4_bet）
    if (plays == "D" and advice.action == "raise" and table.to_call > 0
            and not (strength.strong_draw and opponents == 1
                     and table.street == "flop")):
        _call(table, advice, "I4")
    # 铁律 3：河牌只有 A 档下大注；B 档最多 1/3；C 档以下不下注
    if table.street == "river" and weak and advice.action in ("bet", "raise"):
        if plays in ("C", "D", "E") or (
                advice.to is not None and advice.to - table.my_bet
                > BET["B_river"] * table.pot + table.chip):
            _call(table, advice, "I3")
    # 铁律 2：≥ 2 个对手 B 档以下不加注；≥ 3 个对手不跟 > 1/2 底池的注
    if weak and opponents >= 2 and advice.action == "raise" and table.to_call > 0:
        _call(table, advice, "I2")
    if (weak and opponents >= 3 and advice.action == "call"
            and context.get("size", 0) > B_CALL_MANY + EPSILON):
        _fold(advice, "I2")
    # 铁律 1：B 档及以下这手翻后投入 ≤ 有效筹码的 1/3
    if one_pair and advice.action in ("call", "bet", "raise"):
        if not _within_iron1(table, _put_now(table, advice)):
            if advice.action == "bet":
                _call(table, advice, "I1")
            elif advice.action == "raise" and _within_iron1(table, table.to_call):
                _call(table, advice, "I1")
            else:
                _fold(advice, "I1")
    return advice


# -- 六步串起来 ---------------------------------------------------------------

def _clear(observation):
    """第 1 步：牌、公牌、筹码、动作有没有缺项；有就返回缺的是什么。"""
    hole = [card for card in observation.get("own_hole") or () if card]
    if len(hole) != 2:
        return "你的牌没读全"
    need = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[observation["street"]]
    if len([card for card in observation.get("board") or () if card]) != need:
        return "公共牌没读全"
    folded = set(observation["folded"])
    unknown = [seat for seat in observation.get("stacks_unknown") or ()
               if seat not in folded]
    if unknown:
        return "有人筹码没读到"
    if observation.get("unknown_actions"):
        return "有动作没读到"
    return None


def decide(observation, *, numbers=True):
    """一条建议（``Advice``）。``numbers``：把三个数都算出来（窗口用；记分牌上只在规则
    要用胜率时才算）。"""
    missing = _clear(observation)
    if missing:
        advice = iron5_from(observation, "S1")
        advice.situation = f"看不清：{missing}"
        return _finish(None, advice, {})
    if len(observation["occupied_seats"]) not in range(4, 9):
        advice = iron5_from(observation, unspecified="seats")
        advice.situation = f"{len(observation['occupied_seats'])} 人桌"
        return _finish(None, advice, {})
    table = Table(observation)
    context = {}
    cache = {}

    def reads():
        if "reads" not in cache:
            cache["reads"] = ranges(table)
        return cache["reads"]

    def equity_now():
        if "equity" not in cache:
            involved = {seat: read for seat, read in reads().items()
                        if table.street != "preflop" or read.preflop is not None
                        or seat in _posted(table)}
            cache["equity"] = equity(table, involved)
        return cache["equity"]

    context["reads"], context["equity"] = reads, equity_now
    advice = Advice("fold")
    if table.street == "preflop":
        _preflop(table, advice)
    else:
        _postflop(table, advice, context)
    _banned(table, advice, context)
    if numbers:
        if advice.need is None:
            advice.need = table.need()
        if advice.equity is None and advice.tier not in ("D", "D_strong"):
            advice.equity = equity_now()
        elif advice.equity is None:
            agg = table.aggressor()
            advice.equity = _outs_equity(table, context["strength"],
                                         bool(agg and agg.all_in))
    return _finish(table, advice, context if numbers else {})


def _posted(table):
    """翻前已经投了钱的对手（盲位、抓头）：在没人加注的底池里他们免费看翻牌。"""
    bets = table.observation["bets"]
    return {seat for seat in table.opponents if float(bets[str(seat)]) > 0}


def unread(action, situation, rule="S1"):
    """铁律 5，只看屏幕（实时窗口的第 1 步：这手接不上，或来不及算完）。"""
    advice = Advice(action).hit(rule)
    advice.situation = situation
    return _finish(None, advice, {})


def iron5_from(observation, rule="I5", unspecified=None):
    to_call = float(observation.get("to_call") or 0)
    advice = Advice("fold" if to_call > 0 else "check", unspecified=unspecified)
    return advice.hit(rule)


# -- 一句话理由和翻转条件 -------------------------------------------------------

def _chips(value):
    return f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"


def action_words(table, advice):
    if advice.action == "fold":
        return "弃"
    if advice.action == "check":
        return "过牌"
    if advice.action == "call":
        return f"跟注 {_chips(table.to_call)}" if table else "跟注"
    if advice.all_in:
        return "全下"
    if advice.action == "bet":
        return f"下注 {_chips(advice.to - table.my_bet)}"
    return f"加注到 {_chips(advice.to)}"


def _story(table, context, advice):
    if table is None:
        return ""
    reads = context.get("reads")
    if not reads:
        return ""
    found = reads()
    if table.street == "preflop":
        found = {seat: read for seat, read in found.items() if read.preflop is not None}
        if not found:
            return "后面的人还没动作"
    agg = table.aggressor()
    if agg is not None and agg.seat in found:
        main = found[agg.seat]
        advice.range_words = main.words
        text = f"他{main.story}，范围{main.words}"
        others = len(found) - 1
        return text + (f"（另 {others} 人）" if others else "")
    if len(found) == 1:
        (main,) = found.values()
        advice.range_words = main.words
        return f"他{main.story}，范围{main.words}"
    advice.range_words = "；".join(read.words for read in list(found.values())[:3])
    return f"{len(found)} 个对手，范围" + "；".join(
        f"{read.words}" for read in list(found.values())[:3])


def _mine(table, advice):
    if table is None:
        return ""
    if table.street == "preflop":
        text = f"我 {advice.hand}"
    else:
        text = f"我{advice.hand} {TIER_WORD.get(advice.tier or '', '')}".rstrip()
    parts = [text]
    if advice.equity is not None:
        parts.append(f"胜率 {advice.equity:.0%}")
    if advice.need:
        parts.append(f"需要 {advice.need:.0%}")
    return "，".join(parts)


def _finish(table, advice, context):
    advice.story = _story(table, context, advice) if context else ""
    pieces = [advice.situation, advice.story, _mine(table, advice) if table else ""]
    label = RULES[advice.rule]
    if advice.unspecified:
        label = f"{UNSPECIFIED[advice.unspecified]}，按铁律 5"
    pieces.append(f"{label}——{action_words(table, advice)}")
    advice.reason = "；".join(piece for piece in pieces if piece) + "。"
    advice.flip = flip(table, advice, context)
    return advice


def flip(table, advice, context):
    """翻转条件：一句话，边界在哪里。"""
    rule = advice.rule
    if advice.unspecified or rule == "S1":
        return "v3.1 没写或看不清时先弃 / 过牌；看清了、表里有了再按表打"
    pot_before = None
    agg = table.aggressor() if table else None
    if agg is not None and table.street != "preflop":
        pot_before = agg.pot
    effective = table.effective() if table else 0.0
    texts = {
        "T1.raise": "前面有人加注就改按表 2",
        "T1.limp": "前面有人加注就改按表 2",
        "T1.out": "表外的牌前注再厚也不入池；换到表里的位置才打",
        "T1.iso1": "再多一个平跟者就只用 TT+、AJs+、AQo+、KQs 隔离",
        "T1.iso2": "有人加注就改按表 2",
        "T1.iso2.no": "只有 1 个平跟者时就按本位置加注表隔离",
        "T1.straddle": "≥ 2 个平跟者且拿到 TT+、AJs+、AQo+、KQs 才隔离",
        "T2.3bet": "被 4-bet 只有 KK+ 继续",
        "T2.call": "被再加注就按表 3",
        "T2.price": f"跟注超过 {_chips(PRICE_SHARE * effective)} 就弃",
        "T2.blind": (f"跟注超过 {_chips(BLIND_POT * table.pot)} 或已跟的人不到 2 个就弃"
                     if table else ""),
        "T2.short": "他的全下超过 15 个大盲就只留 QQ+、AK",
        "T2.fold": "这手不在表 2 任何一行，价格再好也弃",
        "T3.allin": "面对全下只留 QQ+、AK",
        "T3.jam": "再加注不到有效筹码 30% 时 KK+ 4-bet、QQ/JJ/AK 跟",
        "T3.4bet": "被 5-bet 就全下",
        "T3.call": f"再加注到 {_chips(JAM_SHARE * effective)} 以上就只留 QQ+、AK",
        "T3.fold": "只有 KK+ 4-bet，QQ、JJ、AK（有位置的 AQs）跟",
        "T3.push20": "有效筹码超过 20 个大盲就按表 3 正常打",
        "T3.vs4bet": "只有 KK+ 继续",
        "M.iso": "蘑菇池不到 10 个大盲、或你不在小盲，就不按晚位表",
        "M.flop": "对手多于 2 个就不下这一注",
        "N.A": "被加注时坚果再加注，否则跟",
        "N.B": "被加注就弃（翻牌跟注后 SPR ≤ 1 时才算胜率全下）",
        "N.D_strong": "被加注就按补牌价格",
        "N.D": "被下注就按补牌价格",
        "N.C": "被跟以后不再下注；有人下注就按面对下注表",
        "N.E": "被跟以后不再下注；有人下注就弃",
        "N.turn": "翻牌下过注的 C/D/E 档转牌一律过牌",
        "F.A": "河牌我是坚果就加注，否则跟",
        "F.D_strong": "下注超过 1/2 底池就只按补牌价格跟或弃",
        "F.C": "转牌、河牌再被下注就弃",
        "F.E": "E 档面对下注一律弃",
        "R.A": "我是坚果就再加注",
        "R.B": "转牌、河牌被加注一律弃；翻牌跟注后 SPR ≤ 1 才算胜率",
        "R.CE": "被加注一律弃",
        "SPR.A": "对手多于 2 个或 SPR 大于 2 就按 B 档正常打",
        "SPR.many": "下注超过 1/2 底池、被加注或已经跟过一次就弃",
        "J1": "下注后剩余会不到底池，直接全下",
        "J3": "加注到 3 倍会占剩余筹码 40% 以上，直接全下",
        "I2": "多人底池 B 档以下不加注，≥ 3 个对手不跟超过 1/2 底池的注",
        "I3": "河牌只有 A 档下大注，B 档最多 1/3",
        "I4": "听牌只按补牌价格跟，不加注",
        "I5": "拿不准就弃；看清了再按表打",
    }
    if rule == "F.B" and table and pot_before is not None:
        opponents = len(table.opponents)
        limit = (B_CALL_HU[table.street] if opponents == 1 else
                 B_CALL_TWO if opponents == 2 else B_CALL_MANY)
        then = "按铁律 1" if opponents == 1 else "弃"
        return f"他下到 {_chips(limit * pot_before)} 以上就{then}"
    if rule in ("F.D", "R.D") or (rule == "F.D_strong" and advice.action != "raise"):
        if advice.equity is not None and advice.equity < 1 and table:
            before = matched_pot(table.observation) - table.to_call
            most = advice.equity * before / (1 - advice.equity)
            return f"跟注 {_chips(most)} 以内才跟（补牌胜率 {advice.equity:.0%}）"
    if rule in ("ALLIN", "J2") and advice.need is not None:
        return f"胜率要到 {advice.need + ALL_IN_MARGIN:.0%} 才跟（所需 {advice.need:.0%} + 5%）"
    if rule == "I1" and table:
        cap = IRON_SHARE * table.effective_flop()
        return f"这手翻后最多投入 {_chips(cap)}（已投 {_chips(table.postflop_put())}）"
    return texts.get(rule, "")


# -- 记分牌 ---------------------------------------------------------------------

def action_id(advice, observation):
    """牌桌的动作编号。"""
    to_call = float(observation["to_call"] or 0)
    if advice.action in ("bet", "raise") and advice.to is not None:
        betting = observation.get("betting") or {}
        if betting.get("can_raise", True):
            amount = advice.to
            low, high = _number(betting.get("min_raise_to")), _number(
                betting.get("max_raise_to"))
            if low is not None:
                amount = max(amount, low)
            if high is not None:
                amount = min(amount, high)
            text = (str(int(round(amount))) if abs(amount - round(amount)) < 1e-9
                    else repr(round(amount, 6)))
            return f"raise_to:{text}"
        return "check_call"
    if advice.action == "fold" and to_call > 0:
        return "fold"
    return "check_call"


class PlainBot(_Policy):
    """``plain``：翻前翻后都按 v3.1；``counts`` 记每条规则定了几次、没写的情形几次。"""

    name = "plain"

    def __init__(self):
        from collections import Counter
        self.counts = Counter()

    def for_game(self, salt):
        def policy(observation):
            return self.act(observation)
        return policy

    def decide(self, observation, rng):
        return self.act(observation)

    def act(self, observation):
        advice = decide(observation, numbers=False)
        self.counts[f"rule:{advice.rule}"] += 1
        if advice.unspecified:
            self.counts[f"unspecified:{advice.unspecified}"] += 1
        return action_id(advice, observation)


__all__ = ["Advice", "PlainBot", "READINGS", "RULES", "Strength", "Table",
           "UNSPECIFIED", "action_id", "classify", "decide", "hands", "nuts",
           "read_range", "seat_classes", "unread"]
