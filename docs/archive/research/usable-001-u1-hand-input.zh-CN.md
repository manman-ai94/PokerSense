# USABLE-001 U1 · 真实输入适配 + 现有内核计算 + 最小可操作表单

run_id `USABLE-001-U1-20260916T1835Z` · 基线 `7fcd6db030baf7a54a69a41e9fc485e6957f7aac`（#24 已验收 head）
分支 `codex/usable-001-hand-review` · Draft PR（base `codex/strategy-001-research`，依赖 #24 → #20）
**本轮只做 U1**；不重做 DIAG、不启动 U2、不开发自动化、不合并。

## 1. 页面入口与点击步骤（不需要编辑 JSON）

| 步骤 | 操作 |
| --- | --- |
| 1 | 打开本机 AA 观察台（`python -m poker_engine.desktop.aa_server --profile … --records-dir … --rules-path …`），浏览器进 `http://localhost:8771/` |
| 2 | 先到 **「设置与分析」→「本桌规则」** 保存一份完整桌规（未知项不补零；含未支持特殊机制时不能进入条件分析） |
| 3 | 展开 **「高级：手工多人河牌条件分析」**，最上面的 **「录入一手已结束牌局」** 就是本轮入口 |
| 4 | 填：Hero 手牌 / 五张公共牌 / Hero 座位 / 行动顺序 / 显示底池 / 加注尺寸 / 加注次数上限；勾 **本手已结束** 与 **使用本桌已保存规则** |
| 5 | 填四块文本：**座位**（座位号,状态,筹码,已投入）、**公开历史**（座位号,动作,金额）、**对手范围**（座位号,组合,权重）、**响应权重**（座位号,动作,权重） |
| 6 | 点 **「核对输入」** → 出现「已核对」+ 容量与金额表（组合乘积 / 合法联合组合数 / 最高下注 / Hero 应付额 / 推算底池）+ 身份哈希；不通过时列出**中文缺口/不适用原因** |
| 7 | 点 **「按上述假设计算」** → 把本次输入交给下方**已有的条件分析链路**，结果直接出现在「多人河牌条件分析」里 |
| 8 | 任何输入改动都会让「已核对」失效并要求重新核对；结果绑定输入/假设哈希 |

## 2. 本轮新增/修改

| 层 | 文件 | 内容 |
| --- | --- | --- |
| 适配层（新） | `src/poker_engine/desktop/aa_hand_input.py` | facts（逐项 `observed`/`human_confirmed`/`unknown` + 原候选）与 assumptions 分离；编成既有 17 字段场景文档；支持性检查与中文原因；容量测量；从结构化快照带入事实 |
| 服务（改） | `src/poker_engine/desktop/aa_server.py` | `GET /api/hand-input/template`、`GET /api/hand-input/facts/{issue_id}`、`POST /api/hand-input/build`、`GET /hand_input.js`；**计算仍走原有 `/api/analysis`** |
| 前端（新/改） | `ui/aa-live/hand_input.js` + `index.html` 一个 `<section>` | 普通控件 + 四块文本录入；只用 `createElement`/`textContent`；改动即失效；把文档交给既有分析入口 |
| 测试（新） | `tests/desktop/test_aa_hand_input.py`（14 例）、`tests/desktop/test_aa_hand_input_ui.py`（2 例）、`tests/js/hand_input_dom_stub_test.mjs`（17 项检查） | 见 §4 |
| 选样清单（新） | `docs/research/usable-001-u1-sample-selection.zh-CN.md` | 10 个决策点的检查结果与真实样本缺口 |

**没有**做的事：不改 `aa_study_records.py`（登记合成示例语义不变）；不重跑 OCR、不读媒体（`facts_from_snapshot` 只读已保存的结构化 payload，
`scope = SAVED_STRUCTURED_SNAPSHOT_NO_MEDIA_NO_OCR`）；不新造 solver/框架/队列；不改 128/20000 上限；不新增算法或自动化。

## 3. 事实 / 假设分离与支持性检查

- **facts**：`ended_hand_confirmed`、`hero_seat`、`hero_cards`、`board_cards`、`action_order`、`seats`、`history`、
  `pot_display`、`table_rules`、`source`；每项是 `{value, provenance, candidate}`，`unknown` 永远保持 `unknown`。
- **assumptions**：`range_source = manual_unvalidated`、每位对手的具体组合+相对权重、响应权重、加注尺寸与次数上限、`other_fees`。
- **中文拒绝/缺口**（真实驱动内核后发现并落实的规则，全部来自内核本身的要求，不静默处理）：
  1. 未勾「本手已结束」/ 缺少座位状态 / Hero 不在 ACTIVE / 行动顺序与三名 ACTIVE 不一致；
  2. 手牌或公牌重复、牌数不对、范围组合与已知牌面冲突（牌阻断）；
  3. **三名 ACTIVE 的已投入必须相等且为单底池**；有座位投入更高 → 边池不支持；
  4. **显示底池必须与「各座已投入 + 本街历史投入」对账**；不一致时给出两个数字，不平摊、不补零；
  5. 筹码 ≤ 最大加注尺寸 → 全下边界，不支持；
  6. **公开历史里的下注/加注金额必须落在声明的尺寸网格内**（不自动对齐网格）；
  7. **公开历史在该响应假设下必须有正概率**（否则提示给该对手哪一类动作加权）；
  8. 响应权重在「无人下注」与「面对下注」两类节点上都必须有正权重；
  9. 组合乘积 > 128 → 报出实际乘积与上限（本轮不调大上限）；
  10. 范围缺一名对手 / 响应权重缺一名对手 / `other_fees ≠ 0` → 明确拒绝（未知费用不补零）。
- 内核抛出的英文 token 会被翻译成中文并**保留原文**（`translate_reasons`），便于复核。

## 4. 验证（本轮实跑）

| 检查 | 结果 |
| --- | --- |
| `tests/desktop/test_aa_hand_input.py` | **14 passed**：正向到真内核、改输入重算、重复牌/牌阻断、错误行动顺序、底池冲突、缺范围/费用假设、all-in/非 3 人/超预算、历史无概率与尺寸网格、快照不编造账本、已结束确认、build 路由（含 table 规则版本校验）、facts 路由只读结构化快照 |
| 手算核对例 | 两个等权联合牌局（QQ 对 TT 赢、对 KK 输），无抽水：跟注 EV = (130 + (−20)) / 2 = **55**，内核实测 **55** ✅；弃牌 0 |
| 表单交互（真前端 JS + 真后端） | `tests/desktop/test_aa_hand_input_ui.py` → **2 passed**；`node tests/js/hand_input_dom_stub_test.mjs` → **17/17 检查通过**（`verdict ok=true, failed=0`） |
| 浏览器无 JSON 编辑点击演示 | **BROWSER_VISUAL_RUN**：填表 → 核对（容量 4 组合 / 应付 20 / 推算底池 130）→ 计算 → **条件计算完成**：弃牌 **0**、跟注 **64.375**、加注至 40 **83.03125**、加注至 80 **108.90625**（chips） |
| 全仓回归 | **4015 passed / 1 skipped / 2 warnings，63.48 s**（D-R1 基线 3999 = +16 例） |
| `flake8 src tests tools` | **0 项** |

截图（本机，未提交仓库）：`u1-form.png`（44,616 B / `abd1297c3a39ae16`）、`u1-result.png`（29,858 B / `6141f4b8251d189b`）。

## 5. 容量与耗时（如实测量）

| 项 | 实测 |
| --- | --- |
| 示例输入组合乘积 | 4（2×2），合法联合组合数 **4**，上限 128 |
| 内核节点数 | 17（示例），计算耗时 ≈ 0.1–0.3 s（进程内）/ 分析链路含进程启动与轮询（页面实测一轮 < 3 s） |
| 超预算示例 | 13×13 组合（169）→ 直接拒绝并报出「169 超过 128」 |
| 说明 | 128 是**联合组合上限**，不是手牌数或样本数；本轮**未**调大上限、未引入采样近似 |

## 6. 真实样本状态：`REAL_HAND_ACCEPTANCE_PENDING`

- 只读检查 10 个不重复决策点（4 个注册手牌河牌决策点 + 2 个首手帧 + 4 个已审阅动作标签），详见选样清单。
- **阻断缺口**（证据在清单里逐项列出）：① 全部注册手牌的 `hand_ledger_v2.status = HAND_COMMITMENTS_UNKNOWN`、
  `hand_commitments = null`（`opening_post_vector_incomplete`）⇒ 没有每座投入，无法表达单底池；
  ② 河牌帧 `participants` 最多 2 名 `active`，且含 `UNKNOWN`/`FOLDED_CANDIDATE` ⇒ 不满足「恰好 3 ACTIVE」；
  ③ 决策点缺稳定跟注金额；④ 该手在既有 V5 河牌闸门里本身即 `BLOCKED`（7 条中文原因，证据帧 3042）。
- **用户只需补充**：河牌开始时仍争池的 3 个座位号、每座本手已投入、当前最高下注额、Hero 的应付额；其余（牌面/顺序/历史）可从结构化快照带入。
- **没有**把 `HAND_COMMITMENTS_UNKNOWN` 当 0、没有平摊底池、没有把合成记录改名成真实样本。

## 7. 三个状态分开汇报

| 状态 | 结论 |
| --- | --- |
| **功能** | **PASS（U1 范围内）**：普通表单 → 核对 → 现有内核计算 → 结果显示；改输入即重算；不适用/缺项一律中文拒绝 |
| **真实样本验证** | **PENDING**：没有满足内核前提的授权真实样本，缺口已列明；未编造、未外推 |
| **策略强度** | **NOT_ASSESSED**：默认仍是 `manual_hypothesis`/simulation 语义，`strategy_eligible=false`、`advice_emitted=false`；本轮不碰策略优劣、不校准、不实战 |

## 8. 仍不可用的（本轮明确不做）

- 不是 3 名 ACTIVE 的河牌、边池/all-in 跨越、非河牌街、超过 128 联合组合的真实宽范围；
- 未支持特殊机制（保险/炸弹/蘑菇等）与未知桌规：无法进入条件分析；
- 不做 13×13 范围编辑器、不做训练对手模型、不做保存/重开本轮输入的报告（属 U2）；
- 不读取新的私有媒体、不上传真实截图与原始日志、不启动采集、不产生实战建议。

## 9. U1-R1 修正（审查 `pullrequestreview-5221916203`）

本文件记录的是 U1 检查点当时的状态。U1-R1 在同一分支上修掉了审查指出的四项：输入身份绑定、导入不猜、合法 Hero 历史校验、
最小逐行控件与保存记录带入入口（原来的四块自由文本 CSV 输入框已被逐行控件取代，CSV 退居高级辅助）。
数值口径、§5 的容量/耗时、§6 的 `REAL_HAND_ACCEPTANCE_PENDING` 与 §7 的三层状态结论均未变化。
R1 的实际改动、身份守恒证明与端到端证据见 `docs/research/usable-001-u1r1-form-binding.zh-CN.md`。
