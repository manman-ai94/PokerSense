# PokerSense → PHH → PokerKit 影子预言机（P1 第一轮）

> 定位：**旁路差分验证**。用 PokerKit 作为第二个独立意见，检查 PokerSense 自己算出来的东西。
> **不替换生产状态机**，不删除任何现有规则代码，不启动 solver / GTO / Deep CFR。
> 本轮的产出是「能不能安全地喂」以及「喂进去之后两个引擎是否一致」，不是策略。

## 1 一句话结论

**真实已闭合手牌目前无法导出为 PHH，且这是正确结果** —— PHH 的 `NT` 变体要求
`antes` / `blinds_or_straddles` / `min_bet` / `starting_stacks` / `actions` 全部已知，
而本录像的这五项都还没有确认证据。适配器**拒绝导出并逐项点名缺失字段**，而不是写 0、写 False 或写「输家」。
同时，在**六项字段全部已确认**的构造手牌上，PHH 往返与 PokerKit 差分**跑通**
（含主池/边池切分与双向往返），并当场抓到**两个我自己先写错的错误**：一个是 credit 与 `payoffs`
的语义差异（见 §4），一个是边池级别算错、导致在**单池**手牌上误报 `MISMATCH`（见 §5.1）。
两者都留了回归用例，而不是悄悄改掉。

## 2 为什么需要这一层

PokerKit 对缺失字段的态度是**接受**：`antes = [0, 0, 0]` 会被当成「真的没有前注」，
而不是「前注未知」。这意味着一个没被观测到的前注，会以**零**的形式流到下游消费者手里，
于是一手因为前注而少赢的牌，看起来就像一手没有前注的牌。
PokerSense 的全部可信度建立在「证据缺失 → UNKNOWN，绝不猜」上，所以这一层必须由我们自己把关。

## 3 字段映射：PokerSense 证据 → PHH → PokerKit State

单一事实来源是 `src/poker_engine/desktop/aa_phh_shadow.py` 的 `FIELD_MAP` 常量（散文与代码不允许漂移）：

| PHH 字段 | PokerSense 证据 | 何种条件下才算 confirmed |
|---|---|---|
| `variant` | 产品范围：AA 桌面轨道只观察无限注德州 | 产品常量，非屏幕读数 |
| `seat_order` ⚠️**非 PHH 字段** | `live_dealer_candidate` + 座位几何 | 按钮位是 **CONFIRMED**，而不是稳定性门控的 candidate |
| `antes` | 桌规 `ante` + `ante_mode`（人工声明） | 金额已声明且模式非 `unknown`；**声明过的 `0` + `mode=none` 是真零，不是缺值** |
| `blinds_or_straddles` | 桌规 `small_blind` / `big_blind` / `straddle_mode`，经 `seat_order` 按位置落座 | 两个盲注都已声明、straddle 模式已知、且位置顺序已确认 |
| `min_bet` | 桌规 `big_blind` | `big_blind` 已声明（无限注的最小下注额就是大盲） |
| `starting_stacks` | 开局帧的逐座筹码读数 | 每一座的筹码都在**任何强制下注之前**被确认 |
| `actions` | `observed_actions_v2` 的解释结果 | `interpretation_status` 是确认态，而不是 `PRICE_DERIVED_CANDIDATE` |
| `seats`（可选头部） | 同 `seat_order` | 与 `seat_order` 同一前置条件；**写进去，反向才能还原座位号** |

> **口径更正（本轮自查发现）**：`seat_order` **不是 PHH 的字段** —— PHH 记谱里没有这个字段。
> 它是**我们加在 PHH 要求之上的 PokerSense 前置条件**（代码里的 `POKERKIT_NT_REQUIRED`
> 与 `PHH_REQUIRED` 因此分开定义，并有测试断言前者**逐字等于** PokerKit
> `HandHistory.required_field_names['NT']` 去掉 `variant` 后的集合）。上一版本把
> `seat_order` 列在「PHH 字段」一栏，属表述不准，已改。

三条关键约束：

1. **`seat_order` 是全局前置条件。** PHH 的 `antes`、`blinds_or_straddles`、`starting_stacks` 以及
   **每一条 action** 都是按玩家编号 `p1..pn` 索引的。按钮位没确认，就意味着
   「谁交小盲」没确认 —— 一个错位会把某个座位的强制下注**静默挪到另一个座位**上。
   所以位置顺序不确认时，整个导出直接拒绝。
2. **PHH 的 `antes` 与 `blinds_or_straddles` 是「已声明的桌规」，不是「观测到的动作」。**
   桌规文档本身带 `source = MANUAL_DECLARATION` / `visual_verified = False` / `pending_fields`，
   它的自我定位就是「用户声明，永不成为视觉真值」。把它写进 PHH 是合法的，但必须在报告里注明来源；
   因此 `forced_bets` 这一项差分在本轮被标为 `NOT_COMPARABLE`（没有已确认的逐座开局扣款可以拿来对照这份声明）。
3. **`starting_stacks` 的语义是「任何强制下注之前」。** 我们能在开局帧读到各座筹码，
   但无法判定那一帧是在盲注前还是盲注后，所以它是 UNKNOWN 而不是「读到的第一个数」。
4. **必须写 `seats`，否则 PHH 只有位置没有座位。** PHH 的可选头部字段 `seats` 被 PokerKit
   逐字往返（实测 `seats = ['4', '7', '1']` 写入后 `loads` 读回同值，且
   `dumps(loads(dumps)) == dumps` 仍成立）。不写它，反向适配器就**只能**知道 `p1..pn`，
   `p2` 再也对不回座位号 —— 反向因此会返回 `seat_order = None`，而不是把 `p1..pn` 冒充成座位号。

## 4 差分设计，以及一个我先写错、被实测纠正的语义差异

差分报告逐项给出 `MATCH` / `MISMATCH` / `NOT_COMPARABLE`，**无法比对时绝不静默记为通过**。

| 检查项 | PokerKit 一侧 | PokerSense 一侧 | 本轮状态 |
|---|---|---|---|
| `pot_commitment_conservation` | `sum(final_stacks)` vs `sum(starting_stacks)` | 本手未声明抽水 | 见 §5 |
| `payout_per_seat` | 逐座 `ChipsPulling` 金额 | 逐座 `unallocated_positive_cash` 正额 credit | 见 §5 |
| `forced_bets` | PHH 里写入的 antes + blinds | 逐座开局扣款 | `NOT_COMPARABLE`（理由见 §3.2） |
| `side_pot_split` | 主池/边池的金额与**有资格座位** | **无**：普通终局只记一笔逐座未分配 credit，不记池级 | 见 §5（**不是**双引擎比对） |

**关键点：`payout_per_seat` 必须用 `ChipsPulling` 的金额去比，不能用 `payoffs`。**
我最初写成了后者，测试直接红了，实测数据是这样的：

```
final.stacks  = [950, 700, 1350]
final.payoffs = [-50, -300, 350]        ← 净盈亏
ChipsPulling(player_index=2, amount=650) ← 结算时推到该座位的筹码
```

PokerSense 的 credit 记录的是**结算那一刻的余额增量**（`1321 → 1350` 这类），
它在数值上等于 `ChipsPulling` 的金额，而**不等于**净盈亏。
只有当被支付的座位对这个底池零投入时两者才巧合相等 ——
换句话说，用净盈亏去比，会**在每一手分池（chop）上悄悄报错**。
这是本轮最有价值的一条工程结论，已写进 `_pulled_by_seat` 的 docstring 与回归用例。

## 5 构造手牌上的端到端结果（六项字段全部已确认）

这是一手**明确标注为构造夹具**的三人的无限注手牌（`SYNTHETIC_DECLARED_FIXTURE`，不是观测到的真实手牌），
唯一目的是把「映射 → PHH → PokerKit 重放 → 差分」这条链完整地跑一遍：

| 项 | 结果 |
|---|---|
| `status` | `EXPORTED` |
| PHH 文本 | 见下 |
| `phh_text_identity`（`dumps(loads(dumps)) == dumps`） | **True** |
| `physical_seats_carried` | `['4', '7', '1']`（写在 `seats` 头部，见 §3.4） |
| `all_actions_accepted` / `hand_finished` | **True** / **True** |
| `pot_commitment_conservation` | **MATCH**（3000 in → 3000 out，差 0） |
| `payout_per_seat` | **MATCH**（seat 1 推 650 = 该座观测到的正额 credit） |
| `forced_bets` | `NOT_COMPARABLE`（见 §3.2） |
| `side_pot_split` | **MATCH**（单池 650 归 seat 7/1；seat 4 交 50 后弃牌，故只有两座有资格） |
| 反例：把 `seat_order` 打乱 | `payout_per_seat` → **MISMATCH**（650 落到 seat 7）—— 差分不是空断言 |
| 反例：非法动作序列（`p3 cbr 300` 之后 `p1 cbr 100` 加注变小） | `POKERKIT_REJECTED`，`ValueError: Unable to repair the hand history`，且**不带 `phh`** |

> **本轮自查修掉一个自己写的假阴性**：`side_pot_split` 的第一版把「池额 ÷ 有资格人数」当作池的级别，
> 于是在**上面这手最简单的单池手牌上就报了 `MISMATCH`**（650/2 = 325，而没有任何一座交到 325）。
> 级别不是这么算的 —— 正确做法是按**每个不同的正投入额**逐级切片，有资格者是「已交到该级别且未弃牌」的人。
> 该错误已修正并留下回归用例 `test_a_plain_single_pot_hand_is_not_reported_as_a_side_pot_mismatch`。
> 记录下来而不是悄悄删掉，因为它正是一个「看起来在验证、其实什么都没验证」的反面样本。

```text
variant = 'NT'
ante_trimming_status = false
antes = [0, 0, 0]
blinds_or_straddles = [50, 100, 0]
min_bet = 100
starting_stacks = [1000, 1000, 1000]
actions = ['d dh p1 AsKs', 'd dh p2 7d7h', 'd dh p3 QcJd', 'p3 cbr 300',
           'p1 f', 'p2 cc', 'd db Ah2c9s', 'p2 cc', 'p3 cc', 'd db Td',
           'p2 cc', 'p3 cc', 'd db 3h', 'p2 cc', 'p3 cc',
           'p2 sm QcJd', 'p3 sm AsKs']
seats = ['4', '7', '1']
```

### 5.1 边池：另用一手**合法**的短筹码手牌实测

同一夹具改成 `1000 / 300 / 1000`，`p3` 加注到 300、`p1` 再加到 600、`p2` 全下 300、`p3` 跟 600：

| 项 | 结果 |
|---|---|
| 池结构 | **主池 900**（seat 4/7/1）+ **边池 600**（seat 4/1） |
| 逐座投入 | seat 4 = 600、seat 7 = 300、seat 1 = 600 |
| `side_pot_split` | **MATCH**（与「按级别切片」的重算完全一致） |
| `payout_per_seat` | **MATCH**（seat 4 推 1500） |
| `pot_commitment_conservation` | **MATCH**（2300 in → 2300 out） |
| 净盈亏（仅记录，不作比对基准） | `payoffs = [900, -300, -600]` |

**另有一手专门用来区分的构造**：某座**跟满 300 之后在翻牌弃牌** —— 它的 300 在池里，但它对池
**没有任何资格**。该手上 `folded_seats = ['4']`、`contributed_per_seat = {全部 300}`、
而池的 `eligible_seats = ['7','1']`。**「交过钱」≠「有资格」**，因此弃牌状态是这条检查的必要输入；
弃牌与否只从操作日志里的 `Folding` 读（`State.statuses` 不能用于此：它把「弃牌」与
「摊牌被 kill」都记成 `False`，而被 kill 的手**是有资格**的）。

## 6 反向适配：PHH → PokerSense 事实

`shadow_ingest` 是**反方向**：把一份 PHH 读回 PokerSense 的词汇。

三条硬约束：

1. **它产出的任何东西都不带 `CONFIRMED`。** 重建出来的动作状态是 `PHH_ROUND_TRIP`，
   而正向闸门只接受 `CONFIRMED`，所以把 `shadow_ingest` 的输出喂回 `shadow_export` 会**被拒绝**。
   否则反向就成了「把未经确认的事实洗过闸门」的通道 —— 有专门用例钉住这一点。
2. **座位号只来自可选的 `seats` 头部。** 不写 `seats` 的 PHH 只有 `p1..pn`，反向会返回
   `seat_order = None` 并标 `seat_order_confirmed = False`，**不会**把 `p1..pn` 冒充成座位号。
3. **`shadow_round_trip(facts)` 把两个方向对起来。** 它比 `dumps(loads(dumps)) == dumps` 更强：
   后者只保证字节稳定，前者要求**语义**不丢。实测（两个夹具）：

| 往返字段 | 结果 |
|---|---|
| `variant` / `antes` / `blinds_or_straddles` / `min_bet` / `starting_stacks` | 全部 **MATCH** |
| `actions`（逐条文本） | **MATCH** |
| `seats`（座位号） | **MATCH** |
| 总体 | **`ROUND_TRIP_MATCH`**，`mismatched_fields = []` |
| 正向被拒绝时 | `ROUND_TRIP_NOT_RUN`（不伪造往返结果） |

## 7 真实手牌：fail-closed 拒绝，逐项点名

`observed_deal_14593` 是 P0 已经闭合的真实手牌。它的终局证据是齐全的：

```
river 完成 f15033 → latch f15034（记录值 15033）→ pending 50 行 → 后继 epoch 首帧 f15198 确认
seat 4 支付 +134（131 → 265，first 15147 / confirmed 15148）
hero 4s 3s ｜ board 3c 7s 3h Tc 6c ｜ 河牌时 5 座 ｜ pot 70
ledger_status: HAND_COMMITMENTS_UNKNOWN
```

但 PHH 的六个必需字段里，它**一个能提供都没有**。为了让「拒绝」不至于被误读成「我们什么都没给」，
证据脚本递进地喂了四个场景（`p1_shadow_real_hand.py` → `p1_shadow_real_hand.out.txt`）：

| 场景 | 供给 | 缺失字段 | 生成 PHH？ |
|---|---|---|---|
| **A** 真实处境（本录像无已保存桌规） | 只有终局证据 | `seat_order`、`min_bet`、`blinds_or_straddles`、`antes`、`starting_stacks`、`actions` | **否** |
| **B** 假定有一份完整的已声明桌规 | A + 桌规 | `seat_order`、`starting_stacks`、`actions` | **否** |
| **C** B + 已确认的位置顺序 + 开局筹码 | B + 两项 | **`actions`** | **否** |
| **D** C + 一条带「流水线最好状态」的动作 | C + 1 条候选动作 | **`actions`**（理由：`1 of 1 action interpretations are not confirmed`） | **否** |

四个场景**全部拒绝**，**四个场景都没有 `phh` 字段** —— 也就是说**没有任何 PHH 文本被生成过**，
所以一个编造的零、一个 False、一个「输家」不可能流到下游。

**`actions` 是当前唯一一道真正跨不过去的门，且它由代码结构决定。**
`aa_semantics` 只会赋三种状态：`UNKNOWN`、`VISIBLE_LABEL_CANDIDATE`、`PRICE_DERIVED_CANDIDATE`
（`grep interpretation_status src/poker_engine/desktop/aa_semantics.py` 三个赋值点），
**从不赋 `CONFIRMED`**。所以在当前流水线下，任何一手真实牌都不可能导出为 PHH ——
这不是本录像的偶然，而是设计使然。

> **口径说明**：`actions` 的**条数**在本轮未做统计。本轮 P0.1 回放的 harness 是在进程启动**之后**
> 才加上动作状态统计的（进程已加载旧版脚本），产物里没有该字段；因此这里改用**代码级事实**论证，
> 它比计数更强，且不依赖任何一次具体回放。

## 8 边界（本轮不做）

- 不替换、不删除、不绕过任何现有 PokerSense 规则代码；影子层只读。
- 不启动 solver 扩张 / Deep CFR / GTO 策略工作。
- 不因为「想让导出通过」而放宽任何一个字段的确认条件。
- PokerKit 是**可选**依赖（`pyproject.toml` 的 `solver-tools` extra 已固定 `pokerkit==0.7.5`）；
  导入是惰性的，运行时装不到 PokerKit 时报告 `POKERKIT_UNAVAILABLE`，其余功能不受影响。
  这一点在**测试**上有一个容易踩的后果，见 §9。

## 9 测试的运行前置：可选依赖与 CI（本轮修掉的一个真实缺陷）

**事实**：CI（`.github/workflows/ci.yml`）只装 `-e ".[dev,perceptual,desktop]"`，**不含 `solver-tools`** ——
也就是说 **CI 上根本没有 PokerKit**。本模块第一版让 24 个用例**全部硬依赖**它，于是 CI 在
macos / windows 两个 job 的 `pytest` 步**全红**（`ModuleNotFoundError: No module named 'pokerkit'`，
15 failed），而本机因为装了 0.7.5 而全绿。`flake8` 步因 pytest 失败被跳过，
**当轮 CI 实际上只验到了「我的模块坏了」这一件事**。

**修法：按用例的真实依赖定向 skip，而不是整模块 skip。**

| 类别 | 用例数 | 无 PokerKit 时 | 为什么 |
|---|---|---|---|
| 闸门拒绝类（`NOT_EXPORTABLE` / 字段映射 / 不替换生产机 / 反向不洗闸） | **10** | **照常执行** | 拒绝必须**不依赖库**就能到达；否则 CI 上「缺依赖」会被读成「闸门拒绝」，fail-closed 证据就成了空的 |
| 真正驱动 PokerKit 类（导出/重放/差分/往返/库字段对照） | 15 | 按 `skipif` 跳过，理由写明 `the solver-tools extra is not installed` | 没有库就无从驱动，跳过是诚实回答；**不是**把它伪装成绿 |

仓库里原本就有 5 个模块按同一前提处理可选依赖
（`tests/state_engine/test_reviewed_replay.py`、`tests/state_engine/test_reviewed_completion.py`、
`tests/tools/test_nlhe_rulebook.py`、`tests/tools/test_wpk_hand_trace.py`、
`tests/equity/test_phevaluator_backend.py`）；本模块第一版**漏了这条约定**，是自查 CI 日志才发现的。

**定位手段（可复用）**：把 path finder 换成拒绝定位 `pokerkit` 的版本，使 `import` 与
`importlib.util.find_spec` 的行为与「从未安装该包」完全一致，从而**实测**出「到底哪几个用例依赖它」，
而不是靠读代码猜。实测：修复前 **15 failed / 9 passed**，修复后 **15 skipped / 10 passed / 0 failed**。

**新增用例** `test_a_missing_field_refuses_before_the_library_is_consulted` 把「闸门先于库」这一
**顺序**钉住 —— 它是 CI 上那 10 个用例仍然有意义的前提。

> **一个未决的策略问题（见回传「请你裁决」）**：是否让 CI 装上 `solver-tools`，好在 CI 上真正跑完这 15 个用例？
> 本轮**没有**改 `ci.yml`：那是仓库级 CI 策略，会同时把 `phevaluator` 带进来并影响其它跳过项，
> 超出本轮授权范围。
