# USABLE-001 U1-R2 · 程序化填充的失效、未知与来源保留、身份真正交叉核对

run_id `USABLE-001-U1-R2-20260916T2025Z` · 基线 `5bed8cfa678094b59d414b856bf25f572279cc00`（R1 head）
分支 `codex/usable-001-hand-review` · 同一个 Draft PR #28 · 审查 `pullrequestreview-5222526862`（`CHANGES_NEEDED`）
**本轮只修该审查列出的边界**；不启动 U2、不重做 DIAG、不换模型、不扩算法/容量、不合并。

## 0. 一句话结论

三项 P1 与两项 P2 全部落地：**任何程序化填充都会立即作废旧回执与旧结果**，导入响应绑定请求目标与规则修订、
迟到/失败回包不恢复旧状态；**未知字段与来源不再被上一手填充**，历史区分「未知 / 已填 / 明确确认无行动」，
空座位号明确拒绝；**已核对输入、面板接受的身份与后端报告身份三者必须相等**，缺失或错配一律拒绝展示与导出。
反例先在旧 head 上跑出真 RED（49 例中 15 failed），再修；修后同范围全绿。

## 1. 审查三条 P1 + 两条 P2 → 落地对照

| 审查要求 | 落地 |
| --- | --- |
| **P1-1** 带入/CSV/换来源统一作废旧回执与旧结果；迟到/失败回包不恢复旧状态 | 新增单一入口 `handInvalidate`（`++handToken` + 丢回执 + 清结果），所有替换路径都走它：`handImportRecord`（**发起时先作废**）、`handCsvApply`、`handSourceChanged`、`handClear`、`handVerify` 开始与失败。`handImportRecord` 捕获 `token=handToken` 与发起时的规则修订，回包时校验 token 未变、修订未变、`body.source.issue_id` 等于请求目标，任一不符即放弃。批量填充后**不自动恢复为已核对**（`hand-compute` 保持禁用） |
| **P1-2** 未知与来源保留；快照时点守住 | 换来源时旧事实、旧结束确认、旧对手假设**全部作废**并给出中文说明；`handSource` 记录 `kind / issue_id / saved_at / preview_sha256 / source_frame / revised_by_human`（内存中，不做 U2 持久化）；`handOrigin` 逐字段保留 `{provenance, candidate}`，人工修改后降级为 `human_confirmed` 但**保留原候选**；历史新增 `#hand-no-history` 三态确认；空座位号经 `handSeatId` 明确拒绝（不会被 `Number("")` 变 0）。后端新增 `river_start_evidence()` 时点门（见 §3） |
| **P1-3** 预期 / 实际规范 / 后端结果身份三者相等 | `analysis-start` 发请求前复核身份连续性；收到回执后若为表单发起则要求 `result.input_sha256` 是 64 位十六进制**且等于表单核对过的身份**，否则拒绝接受；`renderAnalysis` 每次轮询要求「面板接受的身份 = 报告身份」，且表单路径下二者都等于表单身份；**报告缺身份不再跳过**；完成报告还须匹配同一 job、kind、来源、规则修订 |
| **P2-a** `_replay` 精确金额比较 | 不再用 `str(action.target) == item["target"]`，改为构造内核自己的 `RiverAction(actor, kind, Decimal(target))` 并用 `in tree.legal(node)` 判断——直接用内核的相等语义，20 与 20.0 视为同一金额 |
| **P2-b** 无尺寸动作不让用户猜哨兵值 | 行控件对 `check/call/fold` **禁用并自动生成**内核的 `0`；新增可选「跟注追加额」独立字段，与重放算出的应付额对账，不一致即中文拒绝。不改任何扑克结算规则 |

## 2. 页面入口与点击步骤（R2 后）

1. 「设置与分析」→「本桌规则」保存完整桌规。
2. 展开「高级：手工多人河牌条件分析」→「录入一手已结束牌局」。
3. 顶部字段（含**额外费用**三选一）+ 四块**逐行**控件；`check/call/fold` 的金额列自动显示 `0` 且不可编辑，只有下注/加注需要填。
4. 「公开历史」上方新增勾选：**确认本手没有任何公开行动**（不勾且留空 = 未知，不能计算；勾了又填行会被拒绝）。
5. （可选）在「复查记录」选中一条 → 「从选中的复查记录带入有证据的字段」：只填有证据的字段，其余列为未知；`hand-ended`、费用与对手假设 **不会被带入**，必须人工确认。
6. 「核对输入」→ 中文缺口 / 容量 / 金额口径 / 合法根动作 / 身份哈希（哈希面板新增 `source` 与逐字段 `provenance`）。
7. 「按上述假设计算」→ 结果只针对这次输入；**切换复查记录、应用 CSV、清空、带入**都会立即作废旧结果。

## 3. 河牌起点时点门（后端新增不变量）

`facts_from_snapshot` 只有在 payload **自证是河牌起点帧**时才把当前筹码/投入/参与状态标为 `observed`：

1. `observed_state_v2.observed_epoch` 非空；
2. `observed_state_v2.street_candidate == "river"` 且公共牌是五张互不相同的合法河牌；
3. `hand_ledger_v2.status == "OBSERVED_HAND_COMMITMENTS_CANDIDATE"` 且 `taint_reasons == []`；
4. `hand_ledger_v2.epoch == observed_epoch`（同一手，排除另一手账本）；
5. `causal_street_wagers_v2` 是与中控对账过的候选，且**每个座位本街投入都为 0**（排除街中快照）。

任一条不成立 → `seats` 保持 `unknown`，给出具体中文缺口语（并保留 `hand_ledger_v2` / `street_wagers` / `stacks` / `participants` 作为候选）。
R1 的旧测试夹具用的是**自造的账本状态**且没有任何起点证据，属于「正例不成立」，本轮把它改成真证据正例，
缺口变体移入 R2 负例。

## 4. 验证（本轮实跑）

对照方式：在固定基线 `5bed8cf` 上建**独立只读 worktree**，把本轮新测试原样放进去跑，跑完即删（不污染本轮工作区）。

| 项 | 修复前（旧 head + 新测试） | 修复后 |
| --- | --- | --- |
| `tests/desktop/test_aa_hand_input{,_r1,_r2,_ui}.py` + `tests/desktop/test_aa_analysis_ui.py`（49 例） | **15 failed / 34 passed** | **49 passed / 0 failed** |
| 其中 `test_aa_hand_input_r2.py`（16 例，新增） | **11 failed / 5 passed** | **16 passed** |
| 其中 import harness `tests/js/hand_import_flow_test.mjs`（39 项检查，新增） | **22 项失败** | **39/39 通过** |
| 其中确定性 DOM 回归 `tests/ui/test_aa_analysis_ui.js` | 34 例通过 + 3 例新身份用例失败 | **37 例通过** |
| 全量 `pytest` | — | **4047 passed / 1 skipped / 2 warnings，68.77s** |
| `flake8 src tests tools` | — | **0 项** |

端到端 harness 是**原样 `hand_input.js` + `analysis.js` + 真实后端**，跑：
算 A（真实内核 COMPLETE）→ 导入不完整 B → 拒绝沿用 A → 人工补齐并确认 → 真实算 B；
外加反序回包、导入中人工改/清空、导入失败、CSV 替换、未知历史、原候选与来源、身份错配/缺失/起始回执不符。

## 5. 反例修复前后（逐条）

| 反例 | 旧 head 行为 | 现在 |
| --- | --- | --- |
| A 已算完 → 导入 B | 表单显示 B，但仍把 A 的文档交给分析；旧结果与导出保留 | 立即作废回执与结果；`hand-compute` 禁用；不产生新的 `/api/analysis` |
| 导入 B（字段缺失） | B 的未知字段残留 A 的值（含结束确认与对手假设） | 换来源即清空；未带入的项列入中文缺口 |
| 导入中人工改 / 清空 | 迟到回包覆盖更晚的表单 | token 不符即丢弃 |
| 两个导入反序完成 | 后到的旧目标覆盖当前选中 | 只保留最新目标的回包 |
| 导入失败 | 旧状态与旧结果仍在 | 保持已作废状态，来源记为 `import_failed` |
| 未填历史 | 被写成「已确认无公开行动」 | `unknown`；显式勾选才成为 `human_confirmed: []` |
| 空座位号 | `Number("") → 0`，静默变成座位 0 | 中文拒绝，绝不造座位 0 |
| 20 与 20.0 | 被当成不在尺寸网格 / 不是同一动作 | 按精确数值视为同一金额 |
| `check/call/fold` 的金额 | 要求用户手填内核哨兵值 `0` | 控件自动生成并只读；跟注追加额改为可选独立字段并与重放对账 |
| 预期 A、后端 B | 结果照常渲染与导出 | 起始回执即被拒绝，不进入渲染 |
| 报告缺身份 | 第二条身份检查被跳过 | 缺失即拒绝，不再跳过 |

## 6. 边界（避免误读）

- **能做**：把一手人工录入或从结构化快照带入的已结束河牌，经既有内核算出「本决策点、本次假设下」各合法根动作的条件净 EV。
- **不能做**：不是 GTO、不是整手收益、不是实战胜率、不是盈利证明；换一个范围/权重/费用假设数字就会变。
- **真实样本**：仍为 `REAL_HAND_ACCEPTANCE_PENDING`（独立保留，本轮**没有**用合成记录替代；合成记录只用于编码与反例验证）。
- **策略强度**：`NOT_ASSESSED`。本轮**没有**新增真实起点证据，也没有宣称「只差补几项就必然真实可用」。

## 7. 本轮明确不做

不启动 U2；不重做 DIAG（A/B/C/D 与冻结的 C 协议数据未动）；不换模型；不扩 solver/容量/上限；
不改 #24/#20；不开发 Git/MCP/轮询工具；不合并、不发布。

## 8. U1-R3 后续（审查 `pullrequestreview-5223174943`）

本文件记录的是 U1-R2 检查点当时的状态。R3 在同一分支上继续补了两件事：**把核对回执绑定到核对时实际使用的桌规版本**
（同页保存/重置、跨页保存、轮询发现、在途核对四条路径都作废旧回执，且请求携带已核对版本由服务端拒绝陈旧请求），
以及**保留导入中 UNKNOWN 字段的原候选**（历史、时点不成立的 seats）而不把它变成确认事实。
R2 的导入/CSV 作废、身份交叉核对、时点门与精确金额结论均未变化。
R3 的实际改动、规则生命周期前后对比与端到端证据见 `docs/research/usable-001-u1r3-rules-binding.zh-CN.md`。
