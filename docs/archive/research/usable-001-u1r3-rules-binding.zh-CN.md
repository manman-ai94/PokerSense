# USABLE-001 U1-R3 · 核对回执绑定桌规版本 + UNKNOWN 字段原候选保留

run_id `USABLE-001-U1-R3-20260916T2125Z` · 基线 `81b0f2a9bd1e4cb1858076b8f9e9afd9a9387f68`（R2 head）
分支 `codex/usable-001-hand-review` · 同一个 Draft PR #28 · 审查 `pullrequestreview-5223174943`（`CHANGES_NEEDED`）
**本轮只补两条**；不启动 U2、不重做 A/B/C/D、不换模型、不扩算法/容量、不合并。

## 0. 一句话结论

把「核对时实际使用的桌规版本」放进回执，并让**同页保存/重置、跨页保存、轮询发现、在途核对**四条路径都作废旧回执；
发起计算时请求携带**已核对版本**而不是当前页面看到的版本，因此另一页面刚保存的新规则会被**服务端**拒绝而不是被静默接受。
同时把导入时「未知但带候选」的事实块（历史、时点不成立的 seats）的**原候选独立保留**，未知仍是未知、绝不因保留候选而变成确认值。
反例先在旧 head 上跑出真 RED（两个 harness 各 12 / 3 项失败），再修；修后全绿。

## 1. 审查两条 → 落地对照

| 审查要求 | 落地 |
| --- | --- |
| **R3-A** 把核对时实际使用的桌规版本放进回执；同页/跨页规则变化、旧 build 晚到、reset 均使旧回执失效；compute 不能临时用新 revision 给旧输入补标；后端按已核对版本拒绝陈旧请求 | build 回包新增 `verified_rules = {rules_source, rules_revision, effective_rules_sha256}`；`handReceipt` 记录它。`handRulesChanged()`（同页保存/重置，**在请求发出前**就作废）与 `handRulesRevisionSeen()`（由页面自己的 `poll()` 调用）都走 `handInvalidate`，即**令牌前进 + 丢回执 + 清结果 + 保留手填字段**。`handCompute` 再核对一次回执版本，并把**已核对 revision**（`analysisExpectedRulesRevision`）随请求发出——服务端 `start_analysis` 本就要求 `body.rules_revision == current.revision`，所以本页尚未轮询到的外部改动会被**服务端**拒绝。`renderAnalysis` 追加「面板接受的身份 = 报告身份 = 已核对版本」的对齐检查 |
| **R3-B** 保留导入中 UNKNOWN 字段的原 candidate（尤其历史与起点证据不足的 seats），人工补录后仍可追溯；不把候选变成确认事实 | `handApplyImportedFacts` 改为**先独立保留每个返回事实块的 provenance/candidate，再决定是否填控件**；`history` 与「时点不成立」的 `seats` 都保留候选。`handFact()` 对「控件为空」返回 `unknown + 原候选`，对「控件有值」返回 `human_confirmed + 原候选`（值为空是唯一可能是未知的情形）。`handFillRows` 不再丢弃已保留的候选。不做 U2 存储 |

### 1.1 顺带修掉的两个真实缺陷（本轮自测暴露）

1. **在途核对不受规则变化保护**：`handRulesChanged` 最初写成「有回执才作废」，于是**核对请求在途时**规则变化不会推进令牌 ⇒ 迟到的 build 回包把「已核对」恢复了。现在它总是走 `handInvalidate`；`handRulesRevisionSeen` 也用 `handRulesInFlight` 覆盖「回执还没落地」的窗口。
2. **人工作废/替换整块时原候选被丢弃**：`handFillRows` 的 `handClearRows` 会删掉 `handOrigin[block]`，随后写入 `candidate: null` ⇒ CSV 替换或人工补齐后原候选消失。现在先取出已保留的候选再清空。

## 2. 页面入口与点击步骤（R3 后）

1. 「设置与分析」→「本桌规则」保存桌规 R1。
2. 「录入一手已结束牌局」填完并点「核对输入」→ 身份哈希面板里新增 **`verified_rules`**（`rules_source` / `rules_revision` / `effective_rules_sha256`），即本次核对**真正使用**的桌规版本。
3. 若此时在本页保存或重置桌规 → 立刻显示「本桌规则正在保存为新版本…旧核对已失效」，`按上述假设计算` 变灰，**手填字段保留**，只需重新核对。
4. 若另一页面保存了桌规而本页还没轮询 → 直接点计算，页面会发出**已核对版本**，服务端拒绝并显示「本桌规则已变更，请重新检查分析输入」，不显示任何结果。
5. 等页面轮询到新版本 → 旧回执与旧结果自动作废。
6. 重新核对 → 计算 → 正向路径照常（规则、版本、输入身份三者一致）。

## 3. 验证（本轮实跑）

对照方式：在上一轮 head `81b0f2a9` 建**独立只读 worktree**，把本轮新测试原样放进去跑，跑完 `git worktree remove --force`。

| 项 | 修复前（旧 head + 新测试） | 修复后 |
| --- | --- | --- |
| `tests/js/hand_rules_flow_test.mjs`（36 项检查，新增） | **24 passed / 12 failed** | **36/36 通过** |
| `tests/js/hand_import_flow_test.mjs`（47 项检查） | **44 passed / 3 failed**（R3-B 三项） | **47/47 通过** |
| `tests/ui/test_aa_analysis_ui.js`（确定性 DOM） | 37 例 + 3 例新版本用例失败 | **39 例通过** |
| `tests/desktop/test_aa_hand_input_ui.py`（11 例） | 2 例失败 | **11 passed** |
| `tests/desktop/test_aa_analysis_ui.py` | 1 例失败 | **passed** |
| 全量 `pytest` | — | **4048 passed / 1 skipped / 2 warnings，116.26s** |
| `flake8 src tests tools` | — | **0 项** |

旧 head 上失败的 12 项规则检查（节选）：`the_page_scripts_are_loaded`、`the_receipt_carries_the_verified_rules_revision`、
`case1_r1_compute_is_accepted_and_aligned`、`case2_the_same_page_save_voids_the_hand_receipt`、
`case2_the_old_receipt_cannot_be_computed`、`the_receipt_names_r2`、
`case3b_the_poll_voids_the_receipt_for_the_external_change`、`the_receipt_names_r4`、
`case5_the_re_verified_input_computes_with_aligned_versions`、`the_export_names_the_verified_rules`、
`case6_the_reset_voids_the_receipt`、`case6b_the_failed_save_reports_and_keeps_the_receipt_dead`。

### 3.1 「本页保存」真的走了 controls.js 与 `/api/rules`

`tests/js/hand_rules_flow_test.mjs` **按页面顺序加载 `app.js` + `controls.js` + `analysis.js` + `hand_input.js`**
（不是只加载后两个、也不是只手改 sandbox）：

- 首次保存与后续每次保存都通过 `el("rules-form")` 的 **submit 事件**触发 `controls.js::saveRules`，
  真的 `POST /api/rules`，并等到**服务端修订与本页 `rulesRevision`/`statusData` 三者一致**才继续；
- 「另一页面保存」用一条绕开页面的真实 `POST /api/rules`，本页 `statusData` 保持旧值，验证服务端按**已核对版本**拒绝；
- 「轮询发现」调用**页面自己的 `poll()`**；「在途核对」用延迟的 build 响应 + 真实保存；
- 「reset / 保存失败」分别走 `rules-reset` 点击与一个陈旧的 `rulesRevision`（服务端 400）。

## 4. 反例修复前后（逐条）

| 反例 | 旧 head 行为 | 现在 |
| --- | --- | --- |
| R1 核对 → 同页保存 R2 → 点计算 | 旧回执仍在、按钮可点，发出的 `rules_revision=R2` 而 `document.rules` 仍是 R1 | 回执与结果立即作废、按钮变灰、不发任务；手填字段保留 |
| R1 核对 → 另一页面保存 R2 → 本页未轮询就计算 | 临时改用当前 revision 发送，等同于给旧输入补标新规则 | 请求携带**已核对 R1** → 服务端拒绝，不显示结果 |
| R1 核对在途 → 保存 R2 → R1 回包晚到 | 迟到的回包把「已核对」恢复 | 令牌已前进，回包被丢弃；`hand-input-tag` 保持「未核对」 |
| 轮询发现外部版本变化 | 只清下方分析报告，不清回执 | `handRulesRevisionSeen()` 作废回执与结果 |
| 重新核对 → 计算 | — | 真内核运行；`expected_rules_revision == binding.table_rules_revision == 请求 revision` |
| reset / 保存失败 | 回执仍在 | 作废；保存失败不会让回执复活 |
| 导入「历史未知但有候选 + seats 时点不成立但有候选」 | 候选被丢弃 | 两者都保留原候选且**不自动成为事实**；人工补齐后 facts 与导出仍带原候选 |

## 5. 边界（避免误读）

- **能做**：把一手人工录入或从结构化快照带入的已结束河牌，经既有内核算出「本决策点、**本次核对时的桌规版本与假设**下」各合法根动作的条件净 EV。
- **不能做**：不是 GTO、不是整手收益、不是实战胜率、不是盈利证明。
- **真实样本**：仍为 `REAL_HAND_ACCEPTANCE_PENDING`（独立保留，本轮**没有**用合成记录替代；合成记录只用于编码与反例验证）。
- **策略强度**：`NOT_ASSESSED`。本轮**没有**新增真实起点证据，也不声称「只差补几项就必然真实可用」。

## 6. 本轮明确不做

不启动 U2；不重做 A/B/C/D 与冻结的 C 协议数据；不换模型；不扩 solver/容量/上限；不改 #24/#20；
不新增 Git/MCP/自动化；不合并、不发布。
