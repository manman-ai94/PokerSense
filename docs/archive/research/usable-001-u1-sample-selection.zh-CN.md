# USABLE-001 U1 · 真实输入选样清单（脱敏）

run_id `USABLE-001-U1-20260916T1835Z` · 基线 `7fcd6db030baf7a54a69a41e9fc485e6957f7aac`
**只读**已授权的结构化开发产物（JSONL / JSON），**未**打开任何媒体、未扫描整盘、未上传原始记录。
每行只保留结构性事实与缺口证据；不含牌桌昵称、截图、原始日志或玩家身份。

## 1. 检查范围

| 来源（授权结构化产物） | 形态 | 检查的决策点数 |
| --- | --- | --- |
| `aa-development-001-replay-v1/observations.jsonl` | 注册手牌 H02–H07 等 9 手，13,415 帧 | 4 |
| `aa-first-hand-review-20260915-v1/observations.jsonl` 与 `aa-strategy-entry-20260916-v1/first-hand-final-v2/first-hand-new-observations.jsonl` | 同一手 `observed_deal_17`，各 2,060 帧 | 2 |
| `configs/reproduction/aa8_late_action_review_v1.json` | 36 条已审阅动作标签（A01–A36） | 4 |
| 合计 | — | **10**（不重复决策点） |

## 2. 逐项判定（结束 / 河牌 / 3 ACTIVE / 普通池 / 缺失字段与证据）

| # | 来源 | 决策点 | 已结束 | 河牌 | 3 ACTIVE | 普通单底池 | 缺失字段与证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | development replay | `observed_deal_17` @ frame 1782（首个河牌帧，actor=1） | ✅（后续帧 pot 623、`current_actor=null`） | ✅（`street_candidate=river`，5 张公牌） | ❌ | ❌ | `hand_ledger_v2.status=HAND_COMMITMENTS_UNKNOWN`、`hand_commitments=null`、`taint=opening_post_vector_incomplete`；`participants` 中 1/5/6 为 `UNKNOWN` 或 `FOLDED_CANDIDATE`；跟注金额未知 |
| 2 | development replay | `observed_deal_17` @ frame 2038（末帧） | ✅ | ✅ | ❌ | ❌ | 与 #1 同一手（不重复计为独立决策点）；同上缺口 |
| 3 | development replay | `H03` 河牌帧（172 河牌帧 / 80 有 actor） | ✅ | ✅ | ❌（`folded=5, active=2`） | ❌ | 同 `HAND_COMMITMENTS_UNKNOWN`；仅 2 名活跃 → 不满足「河牌开始恰好 3 ACTIVE」 |
| 4 | development replay | `H07` 河牌帧（186 / 95） | ✅ | ✅ | ❌（`folded=6, active=1`） | ❌ | 同上；单人活跃 |
| 5 | development replay | `H02` 河牌帧（90 / 0） | ✅ | ✅ | ❌（`folded=5`） | ❌ | 无 actor 帧；commitments 未知 |
| 6 | development replay | `H05` 河牌帧（89 / 0） | ✅ | ✅ | ❌（`folded=5, active=2`） | ❌ | 无 actor 帧；commitments 未知 |
| 7 | late action review | `A01`（flop，slot 5，check，amount 0） | 未知（标签级） | ❌（flop） | 未知 | 未知 | 标签只含 `actor_slot/actual_action/amount/street/review_status`，无 Hero 牌/公牌/底池/投入 |
| 8 | late action review | `A02`（同上形态） | 未知 | ❌ | 未知 | 未知 | 同上 |
| 9 | late action review | `A03`（同上形态） | 未知 | ❌ | 未知 | 未知 | 同上 |
| 10 | late action review | `A04`（同上形态） | 未知 | ❌ | 未知 | 未知 | 同上 |

统一结论：**9 个已注册开发手牌的 `hand_ledger_v2` 全部为 `HAND_COMMITMENTS_UNKNOWN` 且 `hand_commitments=null`**，
河牌帧的 `participants` 最多只有 **2** 名 `active`；`configs/reproduction/*.json` 的 36 条标签不含牌面/底池。

## 3. 真实样本状态

**`REAL_HAND_ACCEPTANCE_PENDING`**（不是「已跑通真实一手」）。

- **内核当前要求**（`threeway_river_v1`）：河牌开始**恰好 3 名 ACTIVE**、单底池、各座 `hand_committed` 完整且相等、
  行动顺序与公开历史明确、跟注/加注到金额可核对。
- **现有授权产物缺什么**：① 每座本手投入（`hand_commitments`，现为 UNKNOWN，且明确标注
  `opening_post_vector_incomplete`）；② 河牌开始时的 3 名 ACTIVE 身份（现为 UNKNOWN / FOLDED_CANDIDATE）；
  ③ 决策点的跟注金额与稳定价格（现为未知）；④ 该手的普通单底池确认（现无法与显示底池对账）。
- **用户只需补充这些字段**：河牌开始时仍争池的座位号（恰好 3 个）、每座本手已投入筹码、当前最高下注额、
  Hero 的跟注应付额；其余（牌面、顺序、历史）可从结构化快照带入。
- **不做的事**：不把 `HAND_COMMITMENTS_UNKNOWN` 当 0、不平摊底池、不虚构各弃牌者投入、不用摊牌结果回填决策时的未知信息、
  不把这手合成成「真实样本」。这一手在 V5 河牌策略闸门里本身就是 `BLOCKED`（7 条中文原因，证据帧 3042）。

## 4. 对 U1 实现的影响

1. 表单/适配层必须能**从结构化快照带入可用字段**（牌面、行动者候选、显示底池、座位筹码），
   同时把 `hand_commitments`、`participants` 等 `UNKNOWN` 如实标成缺口并**拒绝计算**，而不是补零。
2. 合法的可算输入只能来自：用户手工核对/补录的已结束牌局（普通表单）或测试用合成局面；
   两者都在**现有内核真实入口**（`analyze_threeway_river`）上计算，不取登记 C 示例的数。
3. 「容量」按组合乘积/合法联合组合/节点/耗时如实测量，超限展示拒绝原因。
