# USABLE-001：开局边界重复 epoch 修复 + 普通河牌终局（ORDINARY_RIVER_CLOSED）

状态（三段分开记，不要混成一个）：
- 桌面层重复 epoch 缺陷：**`FIX_ACCEPTED_WITH_SCOPE`**（审查已接受）；
- 普通河牌终局语义：**已由 `P0_FIRST_REAL_HAND_CLOSE` 修复 `river_frame` 过早清零，真实录像命中见第 4 节**；
- 真实牌局验收：**`PENDING`**（`ORDINARY_RIVER_CLOSED` 是一手**已结束**牌局的终局证据，但不等于可核对完整手牌）；策略强度：**`NOT_ASSESSED`**。

范围：桌面层边界缺陷 + 新的**并列**终局类型。未改内核、未改求解器、未改计算上限、未重标 ROI、未放宽任何 `UNKNOWN`、
**未为追求命中而改动任何规则**。

## 1 桌面层重复 epoch（已修，含回归）

### 1.1 症状

同一段历史回放（源帧 1260–1290）在桌面链上：

| 帧 | epoch | 状态 | 账本 |
|---|---|---|---|
| 1264 | `observed_deal_1263` | `MULTI_POST_DEAL_CANDIDATE`（7 座扣款） | `OBSERVED_HAND_COMMITMENTS_CANDIDATE` |
| 1278 | `observed_deal_1277` | `DEALER_ADVANCE_CONTEXT_CANDIDATE`（0 扣款） | 回到 `HAND_COMMITMENTS_UNKNOWN` + `opening_post_vector_incomplete` |

即：**已经解析出来的开局账本，在 14 帧后被一个重复 epoch 覆盖并重新污染**。对照组（纯 `AA8StateAdapterV2`，历史成功运行使用的那条链）在同一批帧上**连续 67 帧保持已解析**。

### 1.2 机制

`aa_live_context.LiveStateAdapter.observe()` 的 dealer 前移分支只要求

- `dealer_run >= 2`，且 `dealer_value != detected`，且 `row["board_count"] == 0`

**没有排除「本手已经拿到合格 opening」**。因此 dealer 座位读数变化（此录像中为读数抖动）会无条件 `_new_epoch()`，而 `AA8HandLedgerCandidate._reset()` 对新 epoch 找不到 multi-post ⇒ 追加 taint，账本失效。

### 1.3 修复

新增 `LiveStateAdapter._anchored_opening()`，**逐条镜像 `_reset` 的合格判据**（同 epoch 恰好 1 个事件、`status == "MULTI_POST_DEAL_CANDIDATE"`、`debits` ≥ 3 座、本 epoch 尚无已观察动作），命中时该分支**只更新 dealer 读数、不新开 epoch**。

刻意保持最小：
- 只保护「**已被账本接受**的开局」，不扩大语义；
- 只覆盖**已证明**的情形（空 board、pot 仍为 0、本手无动作）；
- 「本手已有动作后的读数变化」**不在本轮范围**（未被证明），代码注释已显式标注，需要结算证据才能处理，本守卫不声称覆盖它。

### 1.4 回归测试

`tests/desktop/test_aa_live_opening_boundary.py` + 夹具
`tests/fixtures/aa_reference_hands/opening_rows_1260_1290_v1.json`
（源帧 1260–1290 的 **adapter 之前** 的行，逐字段取自冻结的开发录像；1260–1262 来自 `aa8_first_hand_entry_dense_v2`，1263+ 来自 `aa8_first_hand_full_v1`，因此 **CI 不需要 `G:` 私有池**）。

夹具与仓库内**人工复核**的 `eight_session_boundary_v1.json` 独立对上：`initial_posting_slots = [0,1,2,3,4,5,7]`、空座 6、hero `200 → 196`（与修复前的实测 `258/294/528/340/200/286/None/256 → 255/290/522/338/196/284/None/248` 逐座一致）。

反例先行（新测试拷到上一 head `064894b` 的独立只读 worktree 实跑）：**8 failed / 2 passed**；本轮 **3 passed**。两条在旧 head 上即为绿的用例是**防止过度修复**的守卫（夹具自检、以及「无合格 opening 时 dealer 前移仍必须重锚」）。

## 2 本次牌桌的强制投入规则（已核查，**未改 ≥3 座**）

### 2.1 可确认：强制投入总额恰为 17

三手牌**各自**在开局首次出现非零底池，且**都恰好是 17**：

| 帧 | 底池 | 底池非零帧 |
|---|---|---|
| 8647 | 0 → 17 | 8647 |
| 9814 | 0 → 17 | 9814 |
| 11130 | （已是）17 | 11130 |

仓库内 `configs/game/aa-shadow-rules-v2.json` 声明该桌为
`small_blind 1 / big_blind 2 / ante 2（per_dealt_player）/ mandatory_utg straddle 4`，8 人桌。该桌本次连续三手都被观测到 **5 个已发牌座位**（空座恒为 0、2、6），于是：

```
5 座 × ante 2 = 10，+ SB 1 + BB 2 + UTG straddle 4 = 17
```

**与观测到的开局底池逐手吻合。**

### 2.2 因此：`>= 3 seats` 本来就**可满足**，不得放宽

按上述结构，该桌开局有 **5 个座位同时扣款**（全部已发牌座位都下 ante，其中 3 座另加盲注/抓头）⇒ `posting_comparison` 与 `HandTransitionCandidates.min_posting_seats` 的 ≥3 座要求**在该桌成立**。**本轮未改动任何座位数门槛**，也不建议改。

### 2.3 真正的阻塞是「扣款不可见」，不是座位数

三个开局窗口内，**没有任何座位的识别筹码出现过下降**（`distinct seats that ever decreased = []`），而同窗口 `pot` 在变。`causal_street_wagers_v2.status = WAGERS_UNKNOWN`、`street_price = None`、glyph 全为 null ⇒ **价格通道也不可用**。

结论：`posting_comparison` 是**基于筹码差值**的方法，而本次录像的筹码读数在开局前后不变，因此该方法在此录像上**结构性看不到**强制投入。这是读数/显示问题，与座位门槛无关。

> 证据分级：2.1 的算术吻合是**推断**（配置自身标注 `verification_status: "simulation"`，其 source 亦写明 “not verified live room accounting”）；要把它升级为**已确认**，需要用户从客户端确认该桌结构，或取得**至少一帧筹码确实下降**的开局证据。

## 3 普通河牌终局：`ORDINARY_RIVER_CLOSED`

### 3.1 定位与边界（避免假装覆盖全部结束方式）

新增**并列**终局，**不改动**现有 all-in 终局（`closed` / `full_river` / `terminal` 一字未动）：

- `hand_phase.ordinary_terminal.kind == "ORDINARY_RIVER_CLOSED"`
- `hand_phase.ordinary_terminal_semantics == "ORDINARY_RIVER_CLOSED_ONLY; preflop/flop/turn fold-out endings are NOT covered"`

**只覆盖**：普通（非两家人 all-in）牌局走到**完整河牌**并完成结算。
**不覆盖**：翻前 / 翻牌 / 转牌弃牌结束 —— 后续单独实现（本轮不做）。

### 3.2 后验确认三条件

| | 条件 | 实现 |
|---|---|---|
| **C1 河牌完成** | 实现为 `full_river and not closed`：`street_candidate == "river"` + 5 张合法互异公牌（复用既有 `full_river` 谓词），且 **`closed`（all-in 摊牌）为假** | 记录 `river_complete_frame`（本 epoch **第一次**满足的那一帧，不随后续帧前移，且同 epoch 内 **sticky**，见 4.5） |

> ⚠️ **文档与实现的偏差（如实记录，未擅自改代码）**：本表早期版本把 `pending_actions == 0` 写成 C1 的条件，但**实现的 C1 并不检查它**
> （`pending_actions == 0` 只出现在 all-in `closed` 的判据里，`aa_semantics.py:239`）。真实回放也证实了这一点：
> `observed_deal_8622` 在其 epoch 内存在 `pending_actions != 0` 的帧，仍然被确认为 `ORDINARY_RIVER_CLOSED`。
> **本轮授权只覆盖 `river_frame` 的 sticky 修复**，因此**没有**擅自补这个条件；是否要把 `pending_actions == 0` 纳入 C1 需另行裁决。
| **C2 结算正证据** | 同 epoch 内 `confirmed_frame > river_complete_frame` 的 `unallocated_positive_cash`（余额增加）。**底池读数为 0 本身不足以推断结算**；底池读不到也不阻塞 | 形成 `settlement` 证据列表 |
| **C3 下一手边界** | **唯一确认器**：观察到**新的、非空** epoch，且该帧 `> river_complete_frame` | 置 `confirmed_by_epoch_frame` |

参与座位取自**本 epoch 自己的 `participants`**（状态 ∈ {active, all_in, folded}，≥2 座），**不读 `ledger.opening_evidence`** ⇒ 开局账本缺口不会连带禁掉本终局。

关于 C3 用「事件帧」：`_new_epoch()` 用**创建它的那一帧**给事件打戳，而创建发生在 `observe()` 同一次调用内 ⇒ **首次观察到新 epoch 的帧就是事件帧**，故 `frame > river_complete_frame` 等价于设计要求的「新 epoch 事件帧晚于河牌完成帧」。epoch 变成 `None`（场景失支持/遮挡）是**挂起**，**永不确认**。

### 3.3 三条限制（写入输出而非注释）

- **L1 一手之隔**：普通终局只能在下一手开始后才确认 ⇒ **录像最后一手永远无法确认**。硬停止的录像最后一手只能是 PENDING。这是「不猜」的代价。
- **L2 不依赖 ledger**：如上，参与集合不取自开局账本。`ledger_status` 原样记入证据，供下游**分开**要求账本。
- **L3 不弱化 all-in**：`ordinary_terminal` 一律 `canonical_verified = False`、`strategy_eligible = False`、`card_showdown_verified = False`、`rake_verified = False`；不设置 `settlement_rules_verified`；不占用 `terminal_observation_frame`；不与 `closed` 同时成立。

### 3.5 生命周期契约（在任何下游消费者出现之前钉死）

`ordinary_terminal` **是确认事件，不是状态**：

| 字段 | 语义 | 存活范围 |
|---|---|---|
| `hand_phase.ordinary_terminal` | **确认事件**。只在**确认那一行**出现，之后立即清空 | 一行 |
| `hand_phase.last_ordinary_terminal` | **最近一次确认的持久快照**，带自己的 `epoch` 与 `belongs_to_current_epoch` | 直到下一次确认 |
| `hand_phase.ordinary_river_pending` | C1+C2 已成立、C3 未到，**只是等待**，不是结果 | 逐行判断 |

清空发生在 `observe()` 里 `_phase()` 返回之后，因此**覆盖 `_phase` 的每一条 return 路径**（包含被遮挡/丢 epoch 的早退），事件不可能跨行残留。

`last_ordinary_terminal.belongs_to_current_epoch` 每行重新计算（`epoch == hand_phase.epoch`），因此**旧手的终局不可能被误当成当前手**；消费者也可以直接比较 `last_ordinary_terminal.epoch` 与 `hand_phase.epoch`。

守护测试（`tests/desktop/test_aa_ordinary_river_terminal.py`）：
确认行之后连续三行 `ordinary_terminal is None`；跨第 2/3/4 个 epoch 时 `last_ordinary_terminal.epoch == "h"` 且 `belongs_to_current_epoch is False`；
遮挡行既不带事件也不带 pending；未确认前两个字段都为空。

### 3.5 已知局限（如实标注）

C2 依赖「结算出现**可见的余额增加**」。§2.3 曾测得**本次录像的筹码读数在开局前后不变**，据此怀疑该录像的支付不可见。
第 4 节的**逐帧重测推翻了这个怀疑**：**5 手 full-river 牌局全部在本 epoch 内出现过河牌后的正额支付**，
但**每手的支付确认帧都晚于该手最后一张完整公牌帧** —— 这正是 P0 缺口的成因（见 4.2 / 4.3）。

> **修订（2026-09-17）**：本节初版写的是「多数手上不可见（3/5）」。该说法**已撤回**，它是旧探针只在**公牌仍然完整**的帧上统计 credit 造成的假象。

### 3.6 反例测试（`tests/desktop/test_aa_ordinary_river_terminal.py`，16 项）

1. 确认只发生在下一手边界之后（边界前只有 `AWAITING_NEXT_HAND_BOUNDARY`）。
2. `ordinary_terminal_semantics` 明示不覆盖范围。
3. 底池 0 但无支付证据 ⇒ 不结算。
4. 河牌后 **epoch 丢失（None）⇒ 永不确认**（对应本次 157.7 s 静止缺口这一类）。
5. 河牌后录像立即结束 ⇒ 只 PENDING（对应硬停止）。
6. **两家人 all-in ⇒ 只走 all-in 终局，不产生普通终局**（互斥）。
7. 遮挡帧（`insurance: VISIBLE`）⇒ `SUSPENDED`，既不确认也不显示 PENDING。
8. 翻前弃牌结束 ⇒ 本终局不覆盖（不产生任何普通终局声明）。
9. **确认事件一次性**：确认行之后连续三行 `ordinary_terminal is None`。
10. **快照不泄漏**：跨第 2/3/4 个 epoch，`last_ordinary_terminal.epoch` 仍是 `"h"` 且 `belongs_to_current_epoch is False`；回到该 epoch 时该标志翻为 `True`（证明它是算出来的，不是常量）。
11. 未确认前 `last_ordinary_terminal is None`。
12. 确认事件不随「状态标志」存活：紧随其后的遮挡行不再带事件。

**P0 新增 4 项**（守住 sticky 修复，逐条见 4.5）：13–16。

反例先行：最初 12 项拷到上一 head `064894b` 实跑 **全部失败**；P0 新增项在不含修复的 head `f4b0298` 上实跑 **2 failed / 14 passed**（另 2 项是两侧都必须绿的「防过度修复」守卫）；修复后 **16 passed**。

## 4 真实录像连续回放（`aa-live-20260917-0430`）

只读、**连续顺序**（`grab()` 逐帧、不 seek、不稀疏孤帧），整段 **0–27,287 帧**一次跑完；**每一帧都送进同一条
`AA8Reader` 时序链**（跳过任何一帧就会打断链，孤立单帧在本项目是已知的**假失败**来源）。

### 4.1 命中统计（修复前 → 修复后）

| 指标 | 修复前（`fbda7c52` / `f4b0298`） | 修复后（代码提交 `3d4f390`） |
|---|---|---|
| epoch（含 `None` 挂起段） | 25 | 25 |
| 达到 **full river** 的 epoch | **6** | 6 |
| 产生 `ordinary_river_pending` | **1**（`observed_deal_14593`） | 5（除 `None` 段外的**全部** full-river 手） |
| 产生 `ORDINARY_RIVER_CLOSED` | **0** | **5** |

6 个 full-river epoch：`None`、`observed_deal_8622`、`observed_deal_11609`、`observed_deal_14593`、`observed_deal_17323`、`observed_deal_24560`。
`None` 段没有 epoch 名，按设计**永不确认**（C3 需要一个「新的、非空」epoch）⇒ 本录像的上限就是 **5**。

### 4.2 逐手证据（**修复前**的归因，已在 `f4b0298` 上逐帧重测）

> **更正说明**：本节初版把 3/5 手记为 `payout_credit_not_visible`（"河牌后没有可见支付"）。**这个结论是错的**，
> 它是当时度量规则的假象：旧探针只在**公牌仍然完整**的帧上统计 credit，而这几手的支付恰恰是在公牌读数丢失
> **之后**才被确认的，于是被漏数。用逐帧重测（同一份录像、同一 head `f4b0298`）后，**5 手全部在本 epoch 内有
> 一条河牌后的 payout credit**，且**每手的 credit 确认帧都晚于该手最后一张完整公牌帧**：

| epoch | river 帧 | 完整公牌帧范围 | 公牌读数丢失 | 本 epoch 的 payout credit | 旧实现 C2 窗口 |
|---|---|---|---|---|---|
| `None`（挂起段） | 8397 | — | — | 5 条，都不属于任何一手 | epoch 为空，按设计永不确认 |
| `observed_deal_8622` | 9512 | 9512–9679（168 帧） | 9680–9786（107 帧） | seat 3 **+33**，确认 **9680**，545→578 | 止于 9679 ⇒ **提前关闭** |
| `observed_deal_11609` | 12325 | 12325–12391（67 帧） | 12392–12489（98 帧） | seat 5 **+172**，确认 **12398**，1021→1193 | 止于 12391 ⇒ **提前关闭** |
| **`observed_deal_14593`** | 15033 | 15033–15185（153 帧） | 15186–15197（**12 帧**） | seat 4 **+134**，确认 **15148**，131→265 | 窗口内（故 pending 出现过），随后被 12 帧抖动**撤销** |
| `observed_deal_17323` | 18170 | 18170–18318（149 帧） | 18319–18426（108 帧） | seat 4 **+239**，确认 **18323**，167→406 | 止于 18318 ⇒ **提前关闭** |
| `observed_deal_24560` | 25674 | 25674–25824（151 帧） | 25825–25926（102 帧） | seat 1 **+123**，确认 **25825**，1117→1240 | 止于 25824 ⇒ **提前关闭** |

⇒ **真实第一阻塞只有一个**：`river_frame` 在**同 epoch 内**因公牌读数丢失被清零，使 C2 的窗口
（`river_complete_frame < confirmed_frame <= frame`）在**支付被确认之前**就关闭。
这 5 手不是"支付不可见"的证据缺口，而是**同一个代码缺口的 5 次同构表现**——4 手窗口提前关闭，
1 手（`observed_deal_14593`）窗口内成立过、却被随后的 12 帧收尾动画撤销。因此 4.3 的改法**一次覆盖全部 5 手**。

> 关于 credit 通道：`unallocated_positive_cash` 是**累积列表**（`AA8StateAdapterV2.snapshot` 返回
> `list(self.credits)`，只增不减），因此"某帧该列表非空"并不说明什么。上表用的是严格口径：
> **该 epoch 自己的、`confirmed_frame > river_complete_frame` 的正额余额增加**。

### 4.3 唯一实现缺口：`observed_deal_14593` 为何成立却没被确认（帧级证据）

C1+C2 在真实数据上**可以**成立——这手在 **f15033** 河牌完成（`rf=15033`），并且在 **f15148–f15185** 连续 **38 行**带着有效 pending（`settle=1, seats=5, pend_act=0, pending=True`；起点 15148 正是该手 payout credit 的确认帧）。随后：

```
f15186–f15197  complete=False → rf=None → settle=0 → pending=False   ← 12 帧河牌读数中断，pending 被撤回
f15198         epoch 切到 observed_deal_15197（与上一 epoch 直接相邻，中间没有 None）
```

⇒ 到 f15198 发生 epoch 切换时，**`self.ordinary_river` 已经被清空**，C3 没有可确认的对象。

成因（**我的实现缺陷，不是设计上的"丢 epoch"**）：`river_frame` 在**河牌完整性一旦中断**就被清零，而 hand 收尾动画会让 5 张公牌的读数短暂消失 12 帧。也就是说，「这手有完整河牌」是一个**已经成立的本手事实**，却被一次显示抖动撤销了。注意 epoch 序列显示这里是 **A→B 直接切换，中间没有 `None`**，因此这不是 3.4 第 4 条所覆盖的场景。

**最小改法（已获授权并执行，见 4.5）**：`river_frame` 只在 **epoch 变化**时清零，不再因公牌读数抖动而清零；`closed`（all-in）仍在 eligibility 层抑制。残余风险如实标注：若 adapter 长时间不切 epoch，pending 会挂在该 epoch 上；但 C3 要求 pending 的 epoch == 刚刚结束的 epoch，且 epoch 名唯一，因此不会跨手错误归属。

### 4.4 结论

4.2 与 4.3 描述的是**同一个**缺口的 5 次同构表现：4 手窗口提前关闭，1 手窗口内成立过却被 12 帧收尾动画撤销。
因此 4.5 的那一处最小改动**一次覆盖全部 5 手**，真实回放命中数由 **0 → 5**（逐手帧级证据见 4.6）。

### 4.5 P0 修复：`river_frame` 对「本 epoch 曾确认过完整河牌」改为 sticky

**授权**：`P0_FIRST_REAL_HAND_CLOSE`（`issuecomment-5713265121`），明确限定为「有界代码缺口，不是放宽规则」。

**改法**（`src/poker_engine/desktop/aa_semantics.py`，仅两行语义）：

```python
if closed:
    self.river_frame = None            # all-in 摊牌自身解释了结局 ⇒ 撤回（互斥不变）
elif full_river and self.river_frame is None:
    self.river_frame = row["frame"]    # 只记录「本 epoch 第一次确认完整河牌」
```

即：同 epoch 内某一帧 `full_river=False` **不再**清零 `river_frame`；清零只发生在 **epoch 变化**、**`reset()`**、
以及 **`closed`（all-in）成立**时。

**未改动**（按授权原样保留）：C2 的 payout 要求、C3 的新 epoch 确认器、all-in terminal、视觉阈值、`_posting`、`expires`、座位门槛。

**fail-closed 未被削弱**：`reset()`（source 变化 / 帧序列跳变）仍丢弃全部跨帧事实，包含 `river_frame`——
新增用例专门守住这一点，防止「修复把 sticky 变成跨会话继承」。

**反例先行**：新用例在修复前 head `f4b0298` 的独立只读 worktree 上 **2 failed / 14 passed**；
两条在两侧都绿的用例是**防止过度修复**的守卫（sticky 不得跨 reset、sticky 不得让 all-in 变成普通终局）。修复后终局测试文件 **16 passed**（终局 16 + 开局边界 3 = **19 passed**）。

**测试清单**（`tests/desktop/test_aa_ordinary_river_terminal.py`，16 项）新增 4 项：
1. `test_a_transient_board_loss_after_the_river_never_withdraws_the_pending_close` —— 收尾动画清空公牌，pending 与被记录的 river 帧必须存活，边界到达时**恰好确认一次**。
2. `test_a_transient_board_loss_never_moves_the_recorded_river_frame` —— sticky ≠ 重打戳：仍是**第一次**完整河牌的帧号。
3. `test_a_sticky_river_is_still_retracted_by_an_all_in_showdown` —— sticky 不得让 all-in 终局伪装成普通终局（互斥）。
4. `test_a_source_discontinuity_still_discards_the_old_river_fact` —— 会话边界（source 变化 / 帧跳变）后不得沿用旧 river 帧。

### 4.6 修复后的真实回放（逐手）

同一份录像、同一段 0–27,287 帧连续回放。修复后 5 手**全部闭合**，**每手恰好一次**，每次都在**后继 epoch 的第一帧**上：

| epoch | river 完成帧 | 完整公牌帧数 | pending 帧数 | **确认帧** | 承载确认的后继 epoch | Hero | Board | 底池 |
|---|---|---|---|---|---|---|---|---|
| `observed_deal_8622` | 9512 | 168 | 107 | **9787** | `observed_deal_9786` | `6d Kc` | `Ks Qh 7h 9h 9s` | 34 |
| `observed_deal_11609` | 12325 | **67** | 92 | **12490** | `observed_deal_12489` | `2d Kh` | `6h Ad 5s 4s 6d` | 140 |
| **`observed_deal_14593`** | **15033** | 153 | **50** | **15198** | `observed_deal_15197` | **`4s 3s`** | **`3c 7s 3h Tc 6c`** | — |
| `observed_deal_17323` | 18170 | 149 | 104 | **18427** | `observed_deal_18426` | `Ah Jh` | `2s Th Qs Ad 9s` | 252 |
| `observed_deal_24560` | 25674 | 151 | 102 | **25927** | `observed_deal_25926` | `5h 5s` | `9s Jc 2d Jh 3s` | 90 |

（`None` 挂起段：river 8397、`complete_frames=119`，但 epoch 名为空 ⇒ 按设计**永不确认**，故本录像的上限就是 5。）

**两次独立全量回放**（`after` / `after2`，同一份代码、各自从头跑完 0–27,287）给出**完全相同**的结论：
`epochs with ORDINARY_RIVER_CLOSED = 5`、`closed NOT exactly once: none`、`retrieve_fail / read_fail = 0 / 0`；
并且 25 个 epoch 中 `terminal_rows` **恰好 5 次为 1、其余 20 次为 0** —— **没有任何一个 epoch 出过第二个确认事件**。

P0 判据逐条核对（授权原文的验收条件）：

| P0 判据 | 结果 |
|---|---|
| `river_complete_frame` 熬过收尾抖动 | ✅ `14593` 的 15033 熬过 f15186–15197 的 12 帧公牌丢失 |
| 确认前的 pending **真存在过**（不是事后补记） | ✅ `14593`：seat 4 余额原始变化在 **f15147**、适配器确认 **f15148**，**此时公牌仍然完整**；pending 自 f15148 起真实存在 50 帧 |
| `ORDINARY_RIVER_CLOSED` **恰好一次** | ✅ `closed NOT exactly once: none`；`terminal_rows` 25 个 epoch 中 **5×1 + 20×0**；无重复 epoch 名 |
| `last_ordinary_terminal` 保留旧 epoch 且 `belongs_to_current_epoch=false` | ✅ 确认行之后逐行核过 |
| 后续行 `ordinary_terminal is None` | ✅ 一次性事件契约成立 |
| **不得把任何其它无 payout / 无合法边界的手误判为 CLOSED** | ✅ 无「无 payout 的确认」，无「无 full river 的确认」；**19 个 river=None 的 epoch 全部 terminal_rows=0**（**但见 4.7 的反例余量**） |

> **度量口径（如实标注）**：`first_frame` / `confirmed_frame` 是**适配器**的记账（需稳定可读才确认），与屏幕上的**原始**余额变化帧可能相差几帧。
> 实测 `11609`：seat 5 原始余额在 **f12392** 就变了，但该座在 f12393–12396 不可读，适配器因此记 `first=12397 / confirmed=12398`。
> 两者都晚于各自 epoch 的 river 帧，**不影响任何结论**；这是既有适配器行为，本次改动未触碰。

5 条确认全部携带 `ledger_status: HAND_COMMITMENTS_UNKNOWN`，且 `canonical_verified / card_showdown_verified / rake_verified / strategy_eligible` 全为 `False`
—— 本终局**不声称**任何 GTO 资格，也不等于一份可核对的完整手牌记录。

**每手携带的那一条结算证据**（`source` 全为 `stable_visual_balance_increase`，且 `confirmed_frame` 都晚于该手自己的 river 帧）：

| 闭合手 epoch | 座位 | 金额 | confirmed_frame |
|---|---|---|---|
| `observed_deal_8622` | seat 3 | 33 | 9680 |
| `observed_deal_11609` | seat 5 | 172 | 12398 |
| **`observed_deal_14593`** | **seat 4** | **134** | **15148** |
| `observed_deal_17323` | seat 4 | 239 | 18323 |
| `observed_deal_24560` | seat 1 | 123 | 25825 |

> **一处口径问题（如实记录，未擅自改）**：`observed_deal_8622` 在其 epoch 内有 **13 行** `pending_actions != 0`，仍然被闭合。
> 实现的 C1 只检查 `full_river and not closed`，**不检查** `pending_actions == 0`（该条件只出现在 all-in `closed` 的判据里，
> `aa_semantics.py:239`）；而 §3.2 早前的文档版本把它写成了 C1 的条件。本轮授权**未覆盖**该条件，故未改动，见 §3.2 的偏差说明。

### 4.7 反例余量（**如实标注，未擅自加固**）

对抗性验证（差分 harness：只把 `river_frame` 那一段换回修复前的写法，其余代码不动）找到**一个**由本次修复新引入的假阳性：

- **构造**：某 epoch 的第一帧出现**自相矛盾的单帧读数**（`street_candidate == "river"` + 5 张合法互异公牌），但该手**从未真正走到河牌**；随后公牌清空、出现一次 `confirmed_frame` 余额增加、再切到新 epoch ⇒ 修复后发出 `ORDINARY_RIVER_CLOSED`（`river_complete_frame=0`），修复前不发。
- **可达性**：需要一帧不一致读数（客户端把上一手的公牌拖过 epoch 翻转，或街/牌误读）。
- **危害上限**：C2 仍要求**钱真的动过**，所以失败模式是**误分类**，不是「提前收盘」。
- **本录像可达性**：**不可达** —— 5 手真实牌局的 `complete_frames` 为 168 / **67** / 153 / 149 / 151，最小值 **67**，单帧闪烁构不成完整河牌窗口。
- **P0 当时的决定：只报告、不修补。** 授权被明确限定为「`river_frame` 只在 epoch 真正变化 / `reset()` 时清零」；加守卫会**收窄**该语义，属越权。守卫方案随回传提交待裁决 ⇒ **已在 P0.1 获授权并落地**，见 §7。

本次改动影响的行为差异**只有一个组合**：
`not closed ∧ not full_river ∧ river_frame 已置` ⇒ 修复前**清零**，修复后**保留**。

### 4.8 尚未闭合的部分与一处口径偏差（如实标注）

**仍未闭合的字段**：5 手的 `ledger_status` 全部是 `HAND_COMMITMENTS_UNKNOWN` —— 即 4.2 的开局/账本缺口仍在。
`ORDINARY_RIVER_CLOSED` 证明的是「**这手已经结束**」，**不等于**「开局投入已对账」，也不等于一份可核对的完整手牌记录。
`REAL_HAND_ACCEPTANCE_PENDING` 因此保持不变。

**一处口径偏差（P0 授权未覆盖，故 P0 未改动）**：`observed_deal_8622` 在其 epoch 内有 **13 行** `pending_actions != 0`，
仍然被闭合 —— 即实现的 C1 **不检查** `pending_actions == 0`，详见 §3.2 的偏差说明。
⇒ **已在 P0.1 获授权并修复**，见 §7。

> 本节与 4.6 的各手帧号、结算 seat/金额由**一名独立复核者**用自写脚本另行推导，与本报告一致。

## 5 本轮未做

未改 else 分支的语义、未改 `closed`/`full_river`/`terminal`、未改座位门槛、未改 `_posting` 的比较锚点与 `expires`、未重标 ROI、未调阈值、未动 `LiveCausalWagers`、未改前端、未合并发布。翻前/翻牌/转牌弃牌结束**未实现**（后续单独做）。

**已定位成因、且本轮（P0 授权）已修**：4.3 的 `river_frame` 过早清零 —— 见 4.5、4.6。

**原「两类阻塞」中的 `payout_credit_not_visible` 已撤回**（更正说明见 4.2）：它不是证据缺口，而是同一次度量假象。
**C2 一个字都没有放宽** —— 既没有降低 payout 要求，也没有扩大 credit 通道的接受范围。

## 6 验证

- **本轮代码提交**：`3d4f390b2d20590f90ed43d40ae6a245ee0168d9`（`fix(usable-001): keep a completed river sticky for the rest of its epoch`）。
  本报告为该提交**之后**的 docs-only 更新；代码与测试字节未再变动。
- 全仓 `pytest -v`：**4128 passed / 1 skipped / 2 warnings / 419.46s**（上一基线 4124/1，本轮 +4 = sticky river 三项 + 会话边界守卫一项）。
- 终局 + 开局边界两组测试：**19 passed**（`tests/desktop` 全目录 **445 passed**）。
- `flake8 src tests tools`：0 项。
- 反例先行：终局测试文件在修复前 head `f4b0298` 上 **2 failed / 14 passed** → 修复后 **16 passed**。
- 真实回放：见第 4 节（连续 0–27,287 帧，`ORDINARY_RIVER_CLOSED` 命中 **5**，两次独立回放一致，P0 判据逐条核对见 4.6，反例余量见 4.7）。
- 独立复核：另起一个不了解本改动的复核者，用**自写脚本**直接从原始 JSON 重算（不使用本报告的 `analyse_p0.py`）：(a) 各手确实达到完整河牌、(b) 各手确实有 `confirmed_frame > river` 的 payout、(c) 无完整河牌的 epoch 确实无终局、(e) `observed_deal_14593` 帧号逐项一致 —— **全部 CONFIRMED**。
- 端到端回放（真实池帧 1260–1330）：桌面链 epoch 由「1264 MULTI_POST + 1278 DEALER_ADVANCE」变为「**仅 1264 MULTI_POST**」，与纯 `AA8StateAdapterV2` 的历史行为一致。

## 7 P0.1：终局 fail-closed 加固（`ORDINARY_TERMINAL_FAIL_CLOSED_GUARD`）

授权：`issuecomment-5714727922`。本轮把 §4.7 的反例余量与 §4.8 的口径偏差一起收紧，
**不新开功能** —— 目的是在把终局当作 PHH / PokerKit 的边界输入之前，先堵掉已知的不安全语义。

### 7.1 G1：单帧假 river 不得建立 sticky river fact

**改法**：`river_frame` **首次建立之前**要求 **≥2 个连续观测一致**。
计数沿用既有的连续量概念（`clear_streak` 的同构），**没有按本录像的 67/149/168 帧硬编码任何阈值**；
latch 时记录的是**该连续段的第一帧**，所以守卫只增加一帧延迟，**不会把河牌帧向后改写**。

```python
if closed:
    self.river_frame = None
    self.river_streak = 0
elif full_river and state.get("pending_actions") == 0:
    self.river_streak += 1
    if self.river_frame is None and self.river_streak >= 2:
        self.river_frame = row["frame"] - (self.river_streak - 1)
else:
    self.river_streak = 0
```

**一旦 latch，sticky 语义完全不变**：收尾动画、公牌读数回退、后续动作计数变化都**不得撤销**它；
只有 epoch 真正变化 / `reset()` / `closed`（all-in 摊牌）才清空。

### 7.2 G2：C1 恢复 `pending_actions == 0`，但只在 latch 时

`pending_actions == 0` 重新并入 C1 **谓词**，但**只在 latch 那一刻**被查阅。
latch 之后该字段**不再参与任何判断** —— 一条已经成立的历史事实，不会被后来的读数撤销。

### 7.3 边界上的一个判断（如实说明）

**被阻塞的行不能充当「两个一致观测」中的第二个。** `blocked(row)`（overlay / 场景不支持 / block-state 更新）
对公牌什么都没说，所以它让连续段**重新开始**。方向上是 fail-closed。
本录像 5 手真实牌局的 `blocked_frames` **全部为 0**，因此这个选择**没有代价**。

### 7.4 反例先行（RED → GREEN）

终局测试文件从 16 项加到 **21 项**，新增 5 项：

| # | 用例 | 在不含修复的 head 上 |
|---|---|---|
| 1 | `test_a_single_frame_river_glitch_never_latches_a_river_fact` | **FAIL（RED）** |
| 2 | `test_two_agreeing_river_rows_latch_on_the_first_of_them` | pass（两侧都必须绿的「不得过度修复」守卫） |
| 3 | `test_an_unresolved_action_count_never_latches_a_river_fact` | **FAIL（RED）** |
| 4 | `test_a_latched_river_is_not_revoked_by_a_later_action_count` | pass（同上，防过度修复） |
| 5 | `test_a_blocked_row_makes_the_stability_run_start_over` | **FAIL（RED）** |

修复前实测 **3 failed / 18 passed**，修复后 **21 passed**。

## 8 P0.1 验证与真实回放

- **代码改动**：`src/poker_engine/desktop/aa_semantics.py` **+39 / −12**（含注释）；测试 **+117**。无其它文件被改。
- 真实回放（`aa-live-20260917-0430`，连续、顺序、不 seek、不稀疏抽帧、**不跳任何一帧**；
  0–27,287 帧整段一次跑完，耗时 23m20s，`retrieve_fail / read_fail = 0 / 0`）：

| 指标 | 结果 |
|---|---|
| 达到 **full river** 的 epoch | **6**（含无名的 `None` 挂起段） |
| **latch** 出 river fact 的 epoch | **5** —— 恰好是 5 手具名牌局 |
| 产生 `ordinary_river_pending` | **5** |
| 产生 `ORDINARY_RIVER_CLOSED` | **5** |
| `closed NOT exactly once` | **none** |
| 逐手第一阻塞 | `CONFIRMED_ORDINARY_RIVER_CLOSED` ×5；`no_complete_river_observed` ×14；`no_real_hand_board` ×5；`suspended_bucket` ×1 |

- **latch 逐手明细**（`p01_replay_after_audit.txt`）：river 帧与 P0 **逐一相同**，
  latch 落在**第二帧**，且 latch 前**只看到 1 帧**完整河牌：

| epoch | river 帧 | latch 帧 | latch 值 | latch 前完整帧 | 其中 `pending_actions != 0` |
|---|---|---|---|---|---|
| `observed_deal_8622` | 9512 | 9513 | **9512** | 1 | 0 |
| `observed_deal_11609` | 12325 | 12326 | **12325** | 1 | 0 |
| **`observed_deal_14593`** | **15033** | **15034** | **15033** | 1 | 0 |
| `observed_deal_17323` | 18170 | 18171 | **18170** | 1 | 0 |
| `observed_deal_24560` | 25674 | 25675 | **25674** | 1 | 0 |

  ⇒ **G1 的代价恰好是 1 帧延迟，G2 的代价是 0** —— 两处守卫都**没有丢掉任何一手**。

- **目标手 `observed_deal_14593` 仍然闭合**：river 15033 → latch 15034（记录值 15033）→
  pending 连续 **50 行**（f15148–15197）→ **f15198** 由后继 epoch `observed_deal_15197` 的首帧确认。
  Hero `4s 3s` ｜ board `3c 7s 3h Tc 6c` ｜ 结算 seat 4 `+134`（131 → 265，first 15147 / confirmed 15148）。

- **误确认审计**（`p01_audit.py`，逐条 10 项 × 5 手）：**PROBLEMS: none**。
  否证项包括「无完整河牌却被确认」「同一 epoch 确认两次」「payload 的 river 帧 ≠ latch 值」
  「确认帧 ≠ 后继 epoch 首帧」「无结算证据」「声称任何可用性」，全部为空。

- **一处如实标注的未归因事实**：无名 `None` 挂起段有 **119 帧**完整河牌却**未 latch**。
  该段共 6569 帧、其中 **5126 帧被 block**，因此「连续段被逐帧打断」是合理解释，
  但本轮**没有对该段做逐帧归因**，故只报事实、不报成因。
  该段按设计（无 epoch 名 ⇒ C3 永不成立）本来也**永不确认**，因此无功能影响。
