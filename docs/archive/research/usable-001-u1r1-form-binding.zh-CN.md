# USABLE-001 U1-R1 · 表单身份绑定、导入不猜、合法历史校验、逐行控件

run_id `USABLE-001-U1R1-20260916T1900Z` · 基线 `4f79e633b044ae1e1205230a6e9155b91fb6e7f3`（U1 head）
分支 `codex/usable-001-hand-review` · 同一个 Draft PR #28 · 审查 `pullrequestreview-5221916203`（`CHANGES_NEEDED`）
**本轮只修 R1 的四项**；不重做 DIAG、不启动 U2、不开发自动化、不合并。

## 0. 一句话结论

四项修正全部落地，并且**用真实后端把「输入 → 内核计算 → 结果 → 改输入/迟到响应失效 → 重新计算」整条链路跑通**：
两次不同输入的精确条件净 EV 不同（跟注 `515/8` = 64.375 筹码 vs `-20` 筹码，见 §5），输入身份哈希与后端对同一份文档算出的
`input_sha256` **逐字节相等**；改输入或迟到响应一律不显示结果。三个手输测试文件从 **28 failed / 3 passed** 变为 **31 passed / 0 failed**。

## 1. 审查四条 → 落地情况

| 审查要求 | 落地 |
| --- | --- |
| 1. 新表单与原分析结果的失效、取消和输入身份绑定 | `analysis.js` 新增 `analysisExpectedInput`；唯一入口 `analysisInputChanged(reason)` 统一「清身份 + 隐藏结果 + 350ms 去抖取消」；`analysis-start` 在发请求前复核「表单身份 = 场景标签身份 = 面板内容未变」，把身份写进 `analysisBinding`；`renderAnalysis` 每次轮询都复核身份一致，不一致即失效 |
| 2. 结构化导入不得猜座位、状态、顺序；未知历史与费用不得补零 | `facts_from_snapshot` 不再从 `current_actor` 推 Hero 座位、不再按座位号造行动顺序、不再把 `observed_state_v2` 的在场状态当河牌起点状态；`policy: null` 的历史明确记为缺口；`blank_assumptions()["other_fees"]` 初始为 `unknown`，费用必须 `human_confirmed` 或 `assumed` |
| 3. 合法 Hero 历史的校验 | 新增 `_document()` + `_replay()`：用内核自己的 `_Tree` / `_Node` 重放公开历史，非法动作、错序、以及「历史没有停在 Hero 决策点」各自给中文原因；静态检查失败时仍然重放，保证错序被报成错序 |
| 4. 最小逐行控件与保存记录带入入口 | 四块 `#hand-rows-*` 逐行控件（增行/删行）+ `#hand-add-*` 按钮；`#hand-fees` 三选一；`#hand-import-record`；CSV 退居 `<details>` 高级区（只作「转成逐行控件」的辅助） |

## 2. 页面入口与点击步骤（R1 后）

| 步骤 | 操作 |
| --- | --- |
| 1 | 「设置与分析」→「本桌规则」保存完整桌规 |
| 2 | 展开「高级：手工多人河牌条件分析」→「录入一手已结束牌局」 |
| 3 | 填顶部字段（Hero 手牌 / 五张公共牌 / Hero 座位 / 行动顺序 / 显示底池 / 加注尺寸 / 加注次数上限 / **额外费用**），勾「本手已结束」「使用本桌已保存规则」 |
| 4 | 在四块**逐行**控件里逐行填：各座位 / 公开历史 / 对手范围 / 响应权重。点「添加一行」增行，行内「删除此行」删行 |
| 5 | （可选）先在「复查记录」里选中一条记录 → 点「从选中的复查记录带入有证据的字段」：只填有证据的字段，其余留在缺口列表里 |
| 6 | （可选，高级）在 CSV 区粘贴 → 选目标表格 → 点「转成逐行控件」，再逐行核对 |
| 7 | 点「核对输入」→ 「已核对」+ 容量测量 + 金额口径表 + 内核全部合法根动作与追加金额 + 身份哈希 |
| 8 | 点「按上述假设计算」→ 交给下方已有条件分析链路，结果只针对这次输入 |
| 9 | 任何改动（字段、逐行控件、删行）都会立刻作废结果并要求重新核对；迟到的旧结果不会显示 |

## 3. 身份绑定（本轮的核心不变量）

三层身份，全部是「可核对的字符串」而不是「都存在就算数」：

1. **表单身份** `handExpectedInput` = `aa_hand_input.facts_hashes()["input_sha256"]` = `sha256(canonical(document))`，
   其中 `canonical` 为 `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)`。
2. **面板身份** `analysisExpectedInput` = 表单身份（由表单写入）。
3. **报告身份** 后端 `AAConditionalAnalysis.start()` 的 `_json_bytes()` 对同一份文档使用**同一种规范形**，
   于是 `report.input_sha256` 与 (1) **逐字节相等**。

据此写进 `analysisBinding` 并在**每次** `renderAnalysis`（app.js 的轮询也会走到）复核：

- `expected_input_sha256 !== analysisExpectedInput` → 「录入表单的输入身份已变更」并失效；
- `report.input_sha256 !== analysisBinding.input_sha256` → 「这条结果不是针对当前输入算出的」并失效；
- `acceptedAnalysisId === null` → 直接返回（它同时是迟到响应的第一道闸）。

实测（本轮真实运行）：Hero `Qs Qd` 的表单身份与后端身份**同为** `e329cd73bc1070249ad459229e43b8ac7a47ec7c1f7e5e0ddcf8356a066a2148`；
换成 `2h 3d` 后同为 `6d01c65a9e199d1e43aa5e12e3af0c8d336e70893fe203e7121626eedecf1996`。

### 3.1 顺带修掉的两个真实缺陷

- **更具体的提示被覆盖**：原先 `handFailAnalysis` 先写「…结果已失效」再立刻 `cancelAnalysis()`，后者把提示覆盖成通用文案。
  现在取消走同一个去抖入口，提示保持为具体原因。
- **陈旧取消会杀掉新计算**（竞态）：原先在「输入变更」时立即发 `POST /api/analysis/cancel`，若用户紧接着点计算，
  这个仍在路上的取消可能落在新 job 上。现在统一为 350ms 去抖，而 `analysis-start` 会先 `clearTimeout(cancelTimer)` 再自行 await 取消，
  于是取消一定发生在新 job 之前。这条竞态是在把链路跑成端到端测试后才暴露出来的（旧 harness 只统计点击次数，看不到）。

## 4. 导入与未知项

- `facts_from_snapshot(payload, source=...)` 只填「快照**明确陈述**」的字段，并给出具体中文缺口：
  - Hero 座位：只认 `payload["hero_seat"]`；否则 `unknown`，并说明「不按当前行动者或座位号推断」；
  - 行动顺序：只认长度 3 的整数列表；否则 `unknown`，候选里显式记 `{"active_guess_rejected": true}`；
  - 各座状态：只认 `observed_state_v2.participants` 的 `active/folded/all_in` 且**全员明确**，否则记缺口（在场状态 ≠ 河牌起点状态）；
  - 本手已投入：`hand_ledger_v2.status = HAND_COMMITMENTS_UNKNOWN` 或 `hand_commitments = null` → 缺口，**绝不当 0**；
  - 公开历史：只有未确认候选 → 缺口；`policy: null` 的快照也没有候选 → 缺口；
  - Hero 手牌 / 公共牌 / 显示底池：只在快照有值时带出，并保留原候选。
- 费用：`blank_assumptions()["other_fees"] = {"value": None, "provenance": "unknown"}`；
  `human_confirmed` 或 `assumed` 才放行，且值必须为 `0`（非零费用明确列为不支持项，不填估值）。
- 重复项：同一座位的组合重复、同一（座位，动作）的权重重复都拒绝，要求在行内合并而不是重复列行。

## 5. 验证（本轮实跑，非估算）

| 项 | 结果 |
| --- | --- |
| 修复前（HEAD 源码 + 新测试） | `tests/desktop/test_aa_hand_input*.py` **28 failed / 3 passed**（共 31） |
| 修复后 | 同三文件 **31 passed / 0 failed** |
| 表单 harness（`tests/js/hand_input_dom_stub_test.mjs`） | 25 项检查全绿（含逐行控件、未触碰的种子行不算输入、未知费用、尺寸网格、非法顺序、身份绑定） |
| 端到端 harness（`tests/js/analysis_flow_test.mjs`） | 26 项检查全绿（真实 spawn worker + 真实内核 + 真实 `/api/status` 报告） |
| 全量测试 | **4030 passed / 1 skipped / 2 warnings in 64.87s** |
| flake8 | 0 |
| 本轮新增测试 | 15（R1 后端 9 + 表单/端到端 6，另有 2 个既有文件被改写为新契约） |

真实计算结果（`/api/hand-input/build` → `/api/analysis` → `/api/status`，两位对手各 2 个组合、联合组合 4，`to_call = 20`，`implied_pot = 130`）：

| 输入 | `input_sha256`（前 12） | fold | call | raise |
| --- | --- | --- | --- | --- |
| Hero `Qs Qd` | `e329cd73bc10` | `0` | `515/8` = 64.375 | `3485/32` = 108.90625 |
| Hero `2h 3d` | `6d01c65a9e19` | `0` | `-20` | `-2387/40` = -59.675 |

两次 `strategy_eligible = false`、`advice_emitted = false`。**没有**盈利、最优动作或实时建议的含义。

## 6. 三层边界（避免误读）

- **它能做**：把一手人工录入的已结束河牌，经既有内核算出「本决策点、本次假设下」各合法根动作的条件净 EV。
- **它不能做**：不是 GTO、不是整手收益、不是实战胜率、不是盈利证明；换一个范围/权重/费用假设，数字就会变。
- **真实样本**：仍为 `REAL_HAND_ACCEPTANCE_PENDING`（原因见 `usable-001-u1-sample-selection.zh-CN.md`：已登记开发牌局在河牌
  `HAND_COMMITMENTS_UNKNOWN` 且活跃玩家人数不满足单底池三活跃前置条件）。

## 7. 本轮明确不做

不启动 U2；不重做 DIAG（A/B/C/D 未改）；不改策略内核、上限、求解器或任何注册表；不读媒体、不做 OCR；
不新增自动化/Git 工具；不合并；不修改已冻结的 C 协议与数据。

## 8. U1-R2 后续（审查 `pullrequestreview-5222526862`）

本文件记录的是 U1-R1 检查点当时的状态。R2 在同一分支上继续修掉了该审查列出的边界：程序化填充（带入 / CSV / 换来源）
统一作废旧回执与旧结果、迟到与失败回包不恢复旧状态、未知字段与来源保留、河牌起点时点门、
以及「已核对输入 = 面板接受的身份 = 后端报告身份」的真正交叉核对；另修精确金额比较与无尺寸动作的行控件。
R1 的 §3.1 两个缺陷修复、§5 的真实计算读数与 §6 的三层边界结论均未变化。
R2 的实际改动、反例前后与端到端证据见 `docs/research/usable-001-u1r2-import-binding.zh-CN.md`。
