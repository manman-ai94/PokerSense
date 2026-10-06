# STRATEGY-DIAG R1 · C 阶段：一项对手范围参数的单因素对照实验

任务：STRATEGY-DIAG（Issue #23）· 检查点来源 = 评论 5692717861 + B 审查 `pullrequestreview-5218962168`
**范围：只有 C。D（现有离线复盘的最小接入）本轮 NOT_RUN。A/B 未重做。**

## 1. 实验设计（协议先冻结、后运行）

| 项 | 值 |
| --- | --- |
| 协议（先提交） | `configs/strategy/examples/strategy-diag-c-range-protocol-v1.json` |
| 协议父提交 | `a1367c5`（B 阶段 head）；协议自身提交 **早于** 任何扰动世界运行 |
| 场景 | `n6-facing_bet / reference_control`（原 30-world 失败集内，`delta_vs_reference = -30444/189457`） |
| 唯一变化对象 | seat 1 的 `JhJd` 相对权重（该范围内**唯一**打败 Hero QQ 的组合） |
| 因子 | `0.5` / `1` / `2`（`1` = 原基准） |
| 未触碰 | seat 2 范围、双方响应模型、overrides、桌规/费用、座位/筹码、公牌、公开历史、行动顺序、动作网格、预算 |
| 驱动 | `tools/threeway_range_experiment.py`（复用 `evaluate_policy_book(..., trace=True)` 与路径对账） |
| 结果样例 | `configs/strategy/examples/strategy-diag-c-range-experiment-v1.json` |

**为什么该场景适用**：`reference_control` 保留原始的两组合对手范围（seat 1 `{JhJd:1, TcTd:3}`、
seat 2 `{7c7s:1, KhTh:3}`），因此存在**非空且非整段**的组合子集；`value_heavy` 把两侧范围压成单一组合，
无法承载合规子集，故不选。角色理由：seat 1 是公开历史里下注的一方（动作最相关），
而 `JhJd` 是该范围内唯一形成暗三条、打败 Hero 超对的组合。

**不得在每个扰动世界重新规划 Hero**：两本策略本（`manual_reference`、`training_selected`）
各**编译一次**（`book_sha256` 分别为 `5838804b…`、`420a3331…`），三个世界复用；
运行前后哈希逐一相等，且每个世界都断言 `policy_hash_before == policy_hash_after == book_sha256`。

## 2. 三组实测（精确值，非小数）

| 因子 | seat1 `JhJd` 权重 | `training_selected` 冻结 EV | `manual_reference` 冻结 EV | selected − reference | Δ vs check/fold | Δ vs check/call | 历史似然 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **0.5** | 0.5 | `144130669/1931371` | `77437/1417` | **`+353982/17719`** | `144130669/1931371` | `+353982/17719` | `2834/39445` |
| **1** | 1 | `737057752/20650813` | `543196/15151` | **`-30444/189457`** | `737057752/20650813` | `-30444/189457` | `15151/180320` |
| **2** | 2 | `-94917448/31050503` | `390596/22781` | **`-5755044/284867`** | `-94917448/31050503` | `-5755044/284867` | `22781/225400` |

- **因子 1 精确复现原失败读数**：`-30444/189457`，`world_scenario_sha256` 与原 30-world 报告一致
  （`1b45ef6b…`），两本策略本哈希也一致 ⇒ `baseline_verification.matches_original_reading = true`。
- **失败闸门**：因子 0.5 → **无**闸门触发；因子 1 → 触发 `delta_vs_reference`、`delta_vs_check_call`；
  因子 2 → 额外触发 `delta_vs_check_fold`。
- **方向（仅描述，不构成改进主张）**：随因子增大，两个 EV、两个差值与历史似然均为单调；
  其中 `selected − reference` 由 **正** 转负 —— 该比较的**符号**在固定策略下随这一个范围参数反转。
- `manual_reference` 的冻结本在三组里都恒等于 `check/call`（其根动作为 call），
  因此「Δ vs reference」与「Δ vs check/call」两列逐位相同 —— 与 findings §3 记录的**比较对象退化**一致。
- 历史似然随 `JhJd` 权重单调上升（`2834/39445 → 15151/180320 → 22781/225400`）：
  范围权重变化**没有被锁回旧后验**，而是作为公开历史条件化的一部分被如实重算。

## 3. 主要分支差异（并集精确对账）

每个世界都输出：20 条终局路径的并集、其中**差值非零**的 5 条、以及全部同本/跨本对账。
跨本对账（`distinct_books = true`）列出的 5 条差异：

| 因子 | 路径（公开历史） | 归属 | 贡献差（chips） |
| --- | --- | --- | --- |
| 0.5 | `…0:raise:80|1:call|2:call` | selected 独有 | `10360642/205465` |
| 0.5 | `…0:raise:80|1:call|2:fold` | selected 独有 | `2381568/205465` |
| 0.5 | `…0:raise:80|1:fold|2:call` | selected 独有 | `17507370/1931371` |
| 0.5 | `…0:raise:80|1:fold|2:fold` | selected 独有 | `6846525/1931371` |
| 0.5 | `…0:call` | reference 独有 | `-77437/1417` |
| 1 | 同上 5 条 | — | `45451936/2196895`、`12231744/2196895`、`140058960/20650813`、`54772200/20650813`、`-543196/15151` |
| 2 | 同上 5 条 | — | `-29414464/3303245`、`-1409856/3303245`、`140058960/31050503`、`54772200/31050503`、`-390596/22781` |

- 差异只来自**根动作不同**：`training_selected` 的冻结本在根上选 `raise:80`（4 条可达终局路径），
  `manual_reference` 的冻结本选 `call`（1 条）。因子 2 时 selected 的两条 `1:call|2:call` / `1:call|2:fold`
  贡献转负，正是「范围更偏向暗三条时，加注被跟注变为负 EV」的直接读数。
- **精确对账**：每套策略 `reach_probability_sum = 1`、贡献和 = 该策略 EV；每个对账
  `Σ(逐路径贡献差) = 报告出的 EV 差`；跨本对账的差值总和 = `selected − reference`。
  不可达路径条件 EV 为 `null`、贡献 `0`；只加总终局路径，所以祖先不会与后代重复计入。

## 4. 可复跑

```powershell
$env:PYTHONPATH='src;.'; $env:PYTHONUTF8='1'
& $PYTHON tools/threeway_range_experiment.py --check      # 解析后 JSON 内容一致（计时字段除外），exit 0
& $PYTHON tools/threeway_range_experiment.py --output <新文件.json>
& $PYTHON -m pytest tests/tools/test_threeway_range_experiment.py tests/strategy/test_threeway_policy_evaluation_v1.py -v
& $PYTHON tools/validate_threeway_models.py --input configs/strategy/examples/threeway-river-response-manual.json --protocol configs/strategy/examples/threeway-validation-protocol-v1.json --output <dir>
```

## 5. 结论与边界

- **可以说**：在**固定策略**下，原失败场景的 `selected − manual_reference` 对**一名对手的一个组合权重**
  敏感，且符号会反转（0.5 为正、1 为负、2 更负）；这解释了为什么这种小幅度负比较不宜当作「策略总体更差」的证据。
  历史似然与后验随范围权重如实变化（未锁回旧后验），主要差异全部落在根动作产生的 5 条终局路径上。
- **负差的正确读法（按 C 审查更正措辞）**：**指定世界内**的负差仍然**是劣于该条基线的事实**
  —— 因子 1 与因子 2 的世界里 `selected` 的条件 EV 确实低于 `manual_reference`，
  这个事实**不会**因为另一个世界的符号反转而改变，也**不能**用来抹平原 30-world 的 18 条负比较。
  被限制的只是**外推**：不能由这些指定世界推出「跨世界/真实对手上的总体更差或总体更好」。
- **关于「不宣称排序反转」**：冻结协议里的 `no ranking reversal is claimed regardless of outcome` 指的是
  **不宣称全局排名或最优策略发生反转**；本轮如实报告的是**指定比较在该三组因子下的实测符号变化**，
  两者不冲突。协议参数、因子、期望值与提交均未改动（协议文件哈希仍为 `7b77d280…`）。
- **不能说**：本轮**没有**得到新的最优策略、**没有**证明任何策略变强或排序稳定；
  所有数字仍是**给定合成世界下的离线条件 EV**，不是 bb/100、不是盈利率、不是真实对手验证、不是 GTO；
  `strategy_eligible` / `advice_emitted` 恒为 `false`。
- 扰动的组合权重是**手写示例范围的声明式变化**，不是观测频率；本实验**不**进入压力筛选的候选/世界集合。
- **措辞更正（不改协议、不改数据）**：协议 `selection_rationale` 中把 `TcTd` 写成「超对」不准确
  —— J 高牌面下 TT 不是超对（它输给 Hero 的 QQ，也低于牌面 J）。该组合的**身份与权重**未变，
  更正只落在解释文字；协议文件保持字节不变以保住结果 JSON 里记录的协议哈希链。
- D（现有离线复盘的最小接入）**已在 2026-09-16 交付**，见 `strategy-diag-d-offline-review-view.zh-CN.md`。
