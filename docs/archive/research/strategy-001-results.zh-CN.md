# STRATEGY-001 结果、测试与下一步

任务：STRATEGY-001（Issue #23）· run_id `STRATEGY-001-20260915T233757Z-r2`
固定基线：`dc72a4176f81689e95a9238a49fb2d268dcd4a56`

本批状态：**REPORT_AND_REPRO_ONLY**（研究 + 复现 + 归因 + 协议已交付；**未**修改策略内核，**未**做凑数重构）。
原因见 §3：本轮**未**修改策略内核，是因为缺少可检验的分支级证据来支撑任何一处改动，
而不是因为存在需要先修正的统计口径（该说法已按 review 5217785775 撤回）。

---

## 1. 前后对照

| 项 | 值 |
| --- | --- |
| 策略内核代码改动 | **无**（`src/` 未改） |
| 候选集合 / 评价世界 / 指标 | **未改**（保留原候选、原世界、原指标） |
| `screening_status` | `FAIL_STRESS_SCREEN`（复现，未变） |
| 负比较计数 | **18 / 30**（复现，未变） |
| `fallback_cases` | **0**（复现，未变） |
| 结论变化 | 无变化 —— 但**归因与读数问题被首次量化**（见 findings §3） |

**没有把「更保守」当作「更强」**：本批未提交任何声称提升策略的结果。

---

## 2. 测试与检查（本轮实跑）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 聚焦测试 | `pytest tests/strategy tests/tools -q` | **exit 0**（全通过），wall **24 s**；精确用例数本轮未稳定捕获 ⇒ **UNKNOWN** |
| Lint（策略域） | `flake8 --max-line-length=88 --extend-ignore=E203,W503 src/poker_engine/strategy tools` | **0 项**（exit 0，1 s） |
| 空白/冲突检查 | `git diff --check` | **clean** |
| 全仓回归 | — | **NOT_RUN**（本批 `src/` 与 `tests/` 零改动；改动仅限 `docs/research/`） |
| 资产生成器 `--check` | — | **NOT_RUN**（未触碰资产） |
| 外部框架 smoke test | — | **NOT_RUN**（未引入第三方依赖，符合边界） |

> 说明：本批没有代码改动，因此「按改动做相称验证」的要求对应为**确认既有基线仍绿**，而不是新增测试。
>
> **口径边界（2026-09-16 按 review 5218709490 补记）**：上表描述的是**原始 REPORT_AND_REPRO_ONLY 那一轮**，
> 其中 `src/` `tests/` 确实零改动。**当前 head 不再是这个状态**：head `e4e7a56` 已新增计数语义回归
> `tests/tools/test_validate_threeway_models_counting.py`（并更新 `AGENTS.md` 与 PR 正文），
> B 阶段又新增了可选 trace 与 `tools/threeway_path_diagnostics.py`。
> 因此**不得**用旧轮的「tests 零改动」描述当前 head，也不得用旧轮的运行结论代替新 head 的实跑结果。

---

## 3. 为什么是 REPORT_AND_REPRO_ONLY 而不是现在改代码

Issue 允许「没有合理代码改动时明确 REPORT_AND_REPRO_ONLY」。本轮实测给出三条理由：

1. **待检验假设是输入假设**（尚无分支级证据；原文写作「主因」，已降级）：`value_heavy` 世界上 Δvs_check/fold = −80 chips，
   说明在强价值范围下**弃牌本身更优**。30 世界全部 `complete`、`planning_errors` 空、`fallback = 0`，
   只能说明这次评价**没有被中断**；**成功计算不能排除实现缺陷**，`complete` 不等于结算或信息集已被独立验证。
   修它需要**换响应模型/范围假设**，而不是改内核参数。
2. **比较对象在部分世界上退化**：9 个 facing_bet 负比较里，`Δ vs ref` 与 `Δ vs check/call` **精确逐位相同**。
   ⇒ 这只说明这两列给出同一个数；**不构成重复计数**，也**不降低**失败场景数 18（旧推断已撤回）。
   影响的是**报告可读性**，不是可比性，也不需要先修正统计口径。
3. **不新建同功能模块**：Issue 明确「不得再建一套同功能 robust 模块」「保留原候选、原世界、原指标」。
   这**不**全面禁止对照实验：在保留原候选、原世界、原指标的前提下，允许做**只读诊断**与**敏感性/对照**实验，
   本批未做只是因为当时缺少分支级证据，而不是因为被禁止。

因此本轮的正确产出是**如实记录假设状态与比较对象退化的诊断**，并给出可检验的分支级实验协议。

---

## 4. 下一批最多三项任务（按优先级，含失败判据）

### 任务 1（**已作废，替换为下列 B → C → D 次序**）：~~修正筛选口径 —— 比较对象退化检测~~

- ~~假设 H1：18/30 中至少 9 条来自 `ref ≡ check/call` 的重复计数~~ —— **该假设已撤回**
  （被 review 5217785775 与 `tests/tools/test_validate_threeway_models_counting.py` 证伪）。
- 本条目整体作废，原因有二：它建立在已撤回的「重复计数」推断之上；并且它使用了「先冻结对照实现哈希 …
  禁止在看见去重结果后调整去重规则」这类**已过时的实验措辞**。**当前不存在需要先修正的统计口径**。
- 唯一仍有效的部分（比较对象退化的**只读诊断**）不属于实验假设，不得改变原始计数。

**当前已批准次序：B → C → D。**

#### B：固定策略的终局路径诊断与精确收益对账（**已执行，PASS_WITH_SCOPE**）

- **范围**：`threeway_policy_evaluation_v1.py` 增加**可选** trace（`trace=True`）；沿用 `_Evaluation.walk` /
  `evaluate_policy_book`；**不**重写 solver、**不**改策略选择、结算、原基线与风险边界。
- **验收**：frozen_policy / check_fold / check_call 各自给出互斥完备终局路径、公开历史、精确到达概率、
  条件终局 EV、加权贡献；每套策略概率和 = 1、贡献和 = 原 EV；两策略按路径并集相减的差值和 = 原总 EV 差；
  不可达路径的条件 EV 标未定义；祖先与后代不重复加总；返回策略/场景哈希与完整性状态。
- **交付**：`src/poker_engine/strategy/threeway_policy_evaluation_v1.py`（trace）、
  `tools/threeway_path_diagnostics.py`（可复跑）、`tests/strategy/test_threeway_policy_evaluation_v1.py`、
  `tests/tools/test_threeway_path_diagnostics.py`、合成样例
  `configs/strategy/examples/threeway-path-diagnostics{,-sample}-v1.json`。
- **报告**：`docs/research/strategy-001-path-diagnostics.zh-CN.md`。

#### C：一个原失败场景、一项对手范围参数、同一本冻结策略的真实对照（**本轮已执行**）

- **协议先冻结后运行**：`configs/strategy/examples/strategy-diag-c-range-protocol-v1.json`
  （其提交早于结果提交），声明场景 `n6-facing_bet / reference_control`、唯一变化对象
  （seat 1 的 `JhJd` 相对权重）、因子 `0.5 / 1 / 2`，以及因子 1 的期望基线读数。
- **不得在每个扰动世界重新规划 Hero**：两本策略本各编译一次，三个世界复用并校验哈希前后一致。
- **实测**：因子 1 精确复现原失败读数 `-30444/189457`；因子 0.5 变为 **正** `+353982/17719`；
  因子 2 变为 `-5755044/284867` —— 该比较的**符号**随这一个范围参数反转。**不声称策略变强**。
- **负差的正确读法（按 C 审查更正）**：**指定世界内**的负差仍是「该策略劣于该条基线」的事实，
  不因另一世界符号反转而改变，也不能用来抹平原 18/30；被限制的只是**外推到跨世界/真实对手的总体优劣**。
- **报告**：`docs/research/strategy-diag-c-range-experiment.zh-CN.md`。

#### D（**已交付**）：现有离线复盘的最小接入

- **名称**（2026-09-16 按 B 审查更正）：D 的批准目标是**把现有离线复盘以最小方式接入**，
  **不是**「真实数据准入缺口清单」；旧稿把 D 写成数据准入清单属于误标。
- **交付**（2026-09-16）：`aa_study_records.py` + 5 条受控路由 + `ui/aa-live/study.js` + 面板，
  流程 = 合成示例只读预览 → 策略比较与终局路径详情 → 保存独立记录 → 切换记录 → 重开；
  报告见 `strategy-diag-d-offline-review-view.zh-CN.md`。
- **边界提醒（仍然有效）**：不用不足数据拟合、不扫描未授权媒体、不把摊牌子样本当全体范围。

### 任务 2（**已被上面的 C 取代，保留原文以便追溯**）：在固定世界里做响应模型敏感性（不改内核）

- **假设 H2**：`selected` 在 `value_heavy` / `rank_aware` / `check_trap` 上的劣势可由「命中跟注的频率」解释。
- **允许修改范围**：只扩展现有研究路径，在既有公开历史与合法可观察信息上构建**有限候选/敏感性**实验；
  保留原候选、原世界、原指标，同时展示**收益与代价**。
- **失败判据**：若敏感性无法区分 `selected` 与 `manual_reference` 的行为差异，记录为「当前世界不具区分度」并停止扩大。

### 任务 3（**已被上面的 D 取代，保留原文以便追溯**）：真实数据准入缺口清单（不猜值）

- 依 `opponent_dataset_v1` 的严格口径列出：需要哪些字段、需要几个完整会话、
  当前已审阅记录缺哪些字段（已知：完整合法菜单、决策前状态、动作时点）。
- **禁止**：用不足数据拟合、扫描未授权媒体、把摊牌子样本当全体范围。

---

## 5. 局限（必须与结果一起读）

- 结论只在**给定世界与假设**下成立；手写压力世界不是代表性对手池，**不是**独立真实对手验证。
- 金额是**预先指定的 river 条件净增量 chips**；不能乘以 100 冒充全手 bb/100，也不为给定模型下的精确期望编造置信区间。
- 6/7/8 人桌在本轮**始终只有 3 个 ACTIVE**；不得据桌人数宣称多人能力。
- straddle 子类型、抽水、封顶保持 **UNKNOWN**；未确认为零。
- 环境依赖与 `pyproject.toml` pin 不一致（numpy 2.3.5 vs 2.4.6、opencv 4.10.0 vs 4.14.0.94）—— 需单独处理。
- 未安装、未运行、未训练任何第三方 solver；`NOT_RE_VERIFIED_THIS_RUN` 项目的许可证按 UNKNOWN 对待。

---

## 6. 本批边界确认

冻结视觉/采集/UI；未改识别模板与阈值；未启动真实采集；未读未授权私有媒体；未自动点击；
未实战输出策略；未 merge / release；未调用 Codex / Hermes / OpenAI API；未启用 fallback；
未启动子代理或并行写入者；未把未知桌规当 0；未把 heads-up 保证冒充多人保证；
未把合成实验冒充真实对手验证；未把局部 river EV 冒充整场 bb/100。
