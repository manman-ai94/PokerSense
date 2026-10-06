# USABLE-001 U2-R1 · 历史重算接回核对流程、请求身份保护、落盘内容完整校验

run_id `USABLE-001-U2-R1-20260916T1640Z` · 增量基线 `3f56d4d06a3c87650b914310cc4121456c17efa8`（U2 head）
分支 `codex/usable-001-hand-review` · 同一个 Draft PR #28 · 依据审查 `pullrequestreview-5225415635`
与执行单 `issuecomment-5700916216`。
**本轮只补 U2-R1 三项 + P2 可读性**；不重做 U1/U2、不重写启动器、不升级环境、不扩算法/容量、不合并、不覆盖用户旧程序。

## 0. 一句话结论

两种历史重算现在**真正走回已验收的核对/失效流程**（先作废旧输入与结果，再载入该记录的事实+假设+原候选+独立的
`parent_analysis_record_id`，由人工点「核对输入」后重新计算），并按新 job/新记录保存；
打开/重算/保存的回包绑定「当次 epoch + 请求记录号 + 响应记录号 + 当前选择 + 当次表单令牌」；
落盘记录在保存时封存**整份内容的一致性摘要**（显式 schema），读取/列表/幂等查找/重算都走同一校验，
并且**逐项**核对目录号=记录号、job/输入/来源/规则关联、根动作 actor 与合法尺寸与追加额、派生底池/金额/容量。
真实样本仍为 `REAL_HAND_ACCEPTANCE_PENDING`，策略强度 `NOT_ASSESSED`，两者独立保留、状态未变。

## 1. 三个问题的修法与落点

### A / P1 两种重算接回已验收流程（`ui/aa-live/analysis_records.js` + `ui/aa-live/hand_input.js`）

旧缺陷：`current` 分支直接调 `handApplyImportedFacts`，没有先失效，于是「表单显示 B、`handBuilt`/`handReceipt`/
`acceptedAnalysisId` 仍属 A」且计算仍可提交 A；同时不载入 `body.assumptions`（会把 B 的事实与 A 的对手模型混在一起），
并把 analysis-record 号当 observed-review 的 `issue_id`。`saved` 分支只填 JSON + `analysisEdited()`，从不建立可保存回执，
所以「重算 → 保存新记录」根本走不通。

| 修法 | 落点 |
| --- | --- |
| **发起时先失效**（在任何请求发出前） | `recordsRecompute` 先 `recordVoid()`（推进 `recordsEpoch`、清空详情、禁用两个重算按钮），再 `handResetForSource(...)`（推进 `handToken`、丢弃 `handBuilt`/`handReceipt`、清空字段/结束确认/对手假设、并经既有的 350 ms 去抖取消在途分析） |
| **完整载入事实** | 复用 U1 的唯一填充入口：`handApplyFacts(facts)`（由 `handApplyImportedFacts` 抽出，两条导入路径共用，`provenance` 与原候选处理不可能分叉） |
| **完整载入假设** | 新增 `handApplyAssumptions`：范围/响应权重/加注尺寸/加注上限/费用情景**整块替换**，旧值不再可能被继承 |
| **来源命名空间** | `handSource` 新增 `analysis_record_id` 与 `parent_analysis_record_id`；`issue_id` **只放原复查记录号**（`parent.view.source.issue_id`，没有就是 null）。保存时 `source.parent_analysis_record_id` 写入新记录 |
| **两种规则情景** | 新增 `handScenario`：`saved` 分支把该记录的规则作为本场景规则注入 `facts.table_rules`，并以 `rules_source="document"` 走**既有的** `/api/hand-input/build` + `/api/analysis` 合同（不写回全局桌规）；`current` 分支 `handScenario=null`，走既有 `rules_source="table"` |
| **要求明确核对** | 载入后不自动计算：状态为「待重新核对」，由人工点「核对输入」；`hand-compute` 在核对前保持禁用 |
| **原记录不改** | 重算只产生**新 job、新记录**，`parent_analysis_record_id` 指回原记录；`scenario` 只读 |

### B / P1 打开/重算/保存的请求身份与迟到回包

| 修法 | 落点 |
| --- | --- |
| 单一失效入口 | `recordVoid(message)`：推进 `recordsEpoch`、清空 `records-view`、禁用两个重算按钮 |
| 发起前失效 | `recordsOpen` / `recordsRecompute` **在 fetch 之前**调用 `recordVoid`（打开失败也不留下上一条的可用按钮） |
| 变更即失效 | `records-select` 的 `change` 调 `recordVoid`（选项变化/清空）；切换重算目标亦然 |
| 只允许已核验且仍选中 | `recordsRecompute` 要求 `openedRecord.record_id === 当前选择` 且 `display_permitted === true` |
| 回包四重绑定 | 接受回包同时验证 ① 当次 `recordsEpoch` ② 请求的 `record_id` ③ 响应自己的 `record_id` ④ 当前 `select.value`；重算额外验证 ⑤ 当次 `handToken`（清空/改表单/换规则都会推进它） |
| 保存绑定 | `recordsSave` 记下发起时的 `acceptedAnalysisId`/`analysisBinding`，回包时若面板已换目标就如实说明「保存的是发起时那次分析」，不当作当前结果的成功；回执 `display_permitted !== true` 一律按失败处理 |
| 列表刷新不抢选择 | `recordsRefresh` 在**应用回包时**读取当前 `select.value` 并在重建选项后恢复它（改为在 `replaceChildren()` 前读取，旧实现读的是请求发起时的值，会把用户新选择切走） |

### C / P1 落盘内容的结果/来源/动作/金额/记录号完整校验（`aa_analysis_records.py`）

| 修法 | 落点 |
| --- | --- |
| **内容封存** | `content_seal {schema, sha256}`：保存时对「除封存自身以外的整份记录」取摘要，`schema = CONTENT_SEAL_SCHEMA`；读取时重算比对 |
| **逐项核对**（先于封存，命名具体） | 目录号 = 记录号；`identity.source_issue_id == source.issue_id`；`identity.parent_analysis_record_id == source.parent_analysis_record_id`；`job.job_id == identity.job_id`；`input/facts/assumptions/规则四类摘要 + job.verified_rules` 链条一致；`source_kind` 必须等于由来源推出的类型 |
| **根动作** | `action.actor` 必须等于冻结输入的 Hero 座位；`bet/raise` 尺寸必须落在此前核对确认的合法动作网格内（**不自动对齐**）；`additional_cost` 必须等于该网格行的追加额；`call` 的追加额等于核对时的应付额 |
| **派生数值** | `support` / `amounts` / `capacity` 三块互相核对（`to_call`/`current_bet`/`implied_pot`/`hero_street_wager`/`unit`/动作网格），视图里的容量与金额**由已验证的 `support` 块重新生成** |
| **同一校验覆盖所有读路径** | `get` / `recent` / `scenario` / `_find_existing` 都调用 `_verify`；幂等查找遇到「关联相同但校验不过」的文件时**拒绝并说明**，既不返回它也不重复新增 |
| **独立 INVALID** | 单条坏记录只影响它自己：列表其余记录照常 `CURRENT`，且不返回可用数值；**文件不删不改** |
| **旧格式不静默通过** | 缺少内容封存摘要 → 新状态 `UNVERIFIED_FORMAT`（`display_permitted=false`，说明「旧格式无法校验内容」），不再当作已通过 |
| **来源类型显式** | `SOURCE_KIND_MANUAL`（默认，未经观测验证）/ `SOURCE_KIND_LINKED`（关联复查记录）/ `SOURCE_KIND_RECOMPUTED`（由另一条分析记录重算而来），保存时推导、读取时校验 |
| **详情可读（P2）** | `renderRecord` 展示来源类型（中文+机器值）、原复查关联、重算父记录、**核对时使用的规则数值表**、**实际对手范围/响应权重/尺寸/费用**（折叠块 + 普通表格），不再只显示修订摘要 |

不新增密钥或签名服务，不重开就跑 solver，内容摘要只是**覆盖率**修正（审查表里没有一个反例重签过摘要）。

## 2. 验证（本轮实跑）

| 项 | 上一 head `3f56d4d0`（独立只读 worktree，仅换新测试） | 本轮 |
| --- | --- | --- |
| `tests/desktop/test_aa_analysis_records.py` | **15 failed / 19 passed** | **34 passed / 0 failed** |
| `tests/desktop/test_aa_analysis_records_ui.py`（三阶段真实重启） | run1 多项失败（见下） | **run1 44/44 + run2 14/14 + run3 9/9** |
| `flake8 src tests tools` | 0 项 | **0 项** |

### 2.1 上一 head 的 RED（逐项，非崩溃）

服务端（`red-probe-unit.txt`，15 failed）：改动 `EV.exact`+`decimal` **同时**、`raise` 目标额 999、`additional_cost`、
`source.issue_id`、`job.job_id`、`capacity.implied_pot`、`amounts.current_bet`、`support.root_actions[].additional_chips`、
根动作 `actor`、记录号与目录不符、`get/recent/scenario/幂等查找` 一致性、旧格式缺封存、封存 schema、
来源类型默认未验证——每项都**只改了内容、没动任何身份摘要**，旧实现全部返回 `CURRENT`。

端到端（`red-probe-ui.txt`）：旧 head 上 run1 以命名失败退出（`the_page_scripts_are_loaded` 缺少
`handScenario`/`handLoadRecordScenario`；`the_saved_record_states_the_sample_type_in_words`；
`the_saved_record_shows_the_assumptions_and_the_rule_values`；`recompute_with_current_rules_voids_the_old_receipt_and_result`；
`recompute_with_current_rules_loads_A_own_opponent_assumptions`；`recompute_with_current_rules_is_not_wired_to_an_analysis_record_id`；
`the_new_current_rules_record_names_its_parent_and_its_own_rules`；`an_out_of_order_open_paints_only_the_current_selection`；
`a_response_for_another_record_is_refused_without_numbers`；`a_failed_open_leaves_no_numbers_and_no_recompute`；
`a_late_recompute_answer_does_not_touch_a_form_cleared_while_it_flew`；`a_late_list_refresh_does_not_steal_the_selection`；
`every_rewritten_content_field_is_refused_on_every_read_path`；`a_legacy_record_without_a_content_seal_is_not_silently_accepted`）。

### 2.2 两种规则重算 → 保存新结果 → 真实重启重开（三阶段，三个真实服务进程）

`tests/desktop/test_aa_analysis_records_ui.py` 起**三个**独立服务进程共享同一记录目录：

- **run1（服务 A）**：经 `controls.js` 保存桌规 R1（rake 0）→ 合成输入一 A（`Qs Qd`，范围/权重一套）核对+计算→保存 →
  合成输入二 B（`2h 3d`，**不同组合、不同权重**）核对+计算→保存 → 重复保存不新增 → 改输入后旧任务不可保存 →
  改桌规到 R2（rake 5%）且旧记录不被改写、仍可作历史查看 →
  **A/P1**：先算一次 B（持活回执）→ 打开 A → 「用当前桌规重算」：回执/`handBuilt`/`acceptedAnalysisId` 立即归零，
  A 的事实**与假设**载入，出 `handSource` 里 `issue_id=null`、`parent_analysis_record_id=A` → 核对 → **真实内核计算** →
  保存为**新记录 C**（C 的规则是当前 R2，`rake=0.05`，`parent=A`，job 与 A 不同；A 未被改动）→
  **B/P1**：反序打开 A/B、伪造「响应记录号 ≠ 请求记录号」、打开失败、重算中途清空表单、迟到列表刷新 →
  **C/P1**：8 类内容改写 + 旧格式在全读路径上被拒、文件不删不改、还原后可读。
- **run2（新进程，同一目录）**：重开三张记录数值完全一致且**没有任何 `/api/analysis` POST** →
  **全新页面无回执** → 打开 A → 「按保存条件重算」：载入 A 的冻结事实、假设与原规则情景（`hand-use-rules` 关闭、
  `rake_percent=0`）、全局桌规未变 → 核对 → **真实内核计算** → 保存为**新记录 D**（D 用的是 A 的规则而不是当前规则，
  `parent=A`）→ A 未被改动、桌规仍未变。
- **run3（第三个进程）**：四张记录全部存活、各自自洽校验通过、逐字段与重启前**完全一致**，
  且两条重算记录分别以自己的规则情景可读（一条 `rake=0.05` 用当前规则，一条 `rake=0` 用保存规则），**重开零分析请求**。

### 2.3 反例清单（都在真实路径上验证）

| 反例 | 结果 |
| --- | --- |
| 打开 A 后选 B、先回 B 再回 A（反序） | 只画 B；迟到 A 回包被 epoch 丢弃，选择不被切走 |
| 回包自报的记录号 ≠ 请求的记录号 | 拒绝并说明，不展示任何数值，两个重算按钮保持禁用 |
| 打开失败（400） | 无残留数值、按钮保持禁用 |
| 重算在途时清空表单 / 改输入 / 换桌规 | 回包被丢弃，不改动表单、不恢复可计算内容 |
| 列表刷新在途时切换选择 | 刷新应用时保留**当前**选择 |
| 只改 `raise` 目标额（追加额不变） | 不在核对确认的合法动作网格内 → 拒绝 |
| 只改 `additional_cost` / `capacity.implied_pot` / `amounts.current_bet` / 根动作 `actor` | 各自命名拒绝 |
| `EV.exact` 与 `decimal` **同时**改写（彼此仍自洽） | 内容封存不符 → 拒绝 |
| 只改 `source.issue_id` / `job.job_id` | 与身份块不一致 → 拒绝 |
| 记录号与所在目录不符 | 拒绝，并按目录号报告该记录 |
| 旧格式（缺内容封存） | `UNVERIFIED_FORMAT`，不当作已通过；文件保留 |
| 幂等查找命中一条校验不过的记录 | 拒绝并说明，不返回它、也不重复新增 |

## 3. 页面操作步骤

1. 「设置与分析 → 本桌规则」保存完整桌规。
2. 「录入一手已结束牌局」填完 → **核对输入** → **计算条件收益** → 保存本次分析。
3. 关掉程序再启动 → **刷新记录** → 选一条 → **打开已保存分析**（只读，不重算）。
4. 需要重算时二选一：
   - **按保存条件重算**：把该记录冻结的事实、假设与**它当时的规则情景**载回录入区（本桌规则不被改动）→ **核对输入** → **计算** → 保存为**新记录**。
   - **用当前桌规重算**：只把该记录的事实与假设载回录入区，规则用**本桌当前**版本 → **核对输入** → **计算** → 保存为**新记录**。
   两种方式都不会改动原记录；新记录会在详情里显示「重算来源的分析记录」与自己的规则数值。

## 4. 当前可用范围与剩余阻碍

- **可用**：河牌、恰好三名活跃玩家、单底池、人工录入或从结构化快照带入的已结束牌局；本次输入的条件净 EV；
  保存 / 列表 / 只读重开 / 两类显式重算并另存新记录；隔离的离线试用入口（`launch/u2-trial/`，本轮未改动）。
- **不可用**：边池/全下跨越、翻牌与转牌、非三人活跃场景、超过 128 联合组合、未支持特殊机制；不做范围编辑器、
  不给实战提示、不自动点击。
- **真实样本**：`REAL_HAND_ACCEPTANCE_PENDING` **独立保留、状态未变**；本轮全部用明确标记的合成输入
  （`source_kind=manual_hypothesis_unverified`）与真实记录标签分开。
- **策略强度**：`NOT_ASSESSED`。

## 5. 本轮明确不做

不启动下一检查点；不重做 U1/U2/DIAG/论文；不重写或升级 `launch/` 启动器；不换模型；不扩 solver/容量/上限；
不改 #24/#20；不新增 Git/MCP/Agent/自动循环；不读新私有媒体、不开采集或视觉 API；不合并、不发布、不覆盖用户旧程序；
不为 `launch/` 的 lint 扩大 CI workflow 权限。

## 6. 与 U2 文档的关系

`docs/research/usable-001-u2-save-reopen.zh-CN.md` 中「两类重算仅载入/仅要求重新核对」「记录标记
`rubric=synthetic_input_labelled`」的表述**已由本文档取代**；该文档其余内容（保存/只读重开/启动器/真实样本状态）仍然有效。
