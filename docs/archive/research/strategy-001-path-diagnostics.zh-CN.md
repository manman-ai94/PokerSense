# STRATEGY-DIAG-R1 · B 阶段：固定策略终局路径诊断与精确收益对账

任务：STRATEGY-DIAG-R1（Issue #23）· 检查点来源 = 评论 5692346242 + 审查 `pullrequestreview-5218709490`
**范围：只有 B（本文件）与 C（另见 `strategy-diag-c-range-experiment.zh-CN.md`）。
D（现有离线复盘的最小接入）本轮 NOT_RUN。**

## 1. 做了什么

在 `src/poker_engine/strategy/threeway_policy_evaluation_v1.py` 上增加**可选** trace：

| 入口 | 语义 |
| --- | --- |
| `evaluate_policy_book(book, world, trace=True, trace_max_nodes=None)` | 关闭时行为与数值完全不变；打开后额外返回 `path_ledgers` |
| `PolicyEvaluation.path_ledgers` | 三套策略（`frozen_policy` / `check_fold` / `check_call`）各一份 `PolicyPathLedger` |
| `TerminalPath` | 一条**终局**公开路径：公开历史、精确到达概率、条件终局 EV、加权贡献 |
| `compare_policy_paths(evaluation, left, right)` | 在两条策略的**路径并集**上逐条相减，返回 `PathReconciliation` |

**没有**改动的部分：solver（`threeway_river_v1.py` 未动）、策略选择、结算、原基线、风险边界、`assumptions` 元组。
trace 是第二次**独立**遍历：Hero 节点按 `_select` 取策略动作（该动作质量 1、其余合法动作质量 0），
对手节点走同一份世界响应分支；因此三套策略枚举出的路径集合**完全相同**，可逐条对齐相减。
trace 只调用 `legal` / `advance` / `terminal` 与既有 `_world_branches`，**不调用**任何优化入口。

## 2. 验收项与实测（可复跑）

```powershell
$env:PYTHONPATH='src;.'; $env:PYTHONUTF8='1'
& $PYTHON tools/threeway_path_diagnostics.py            # 打印摘要
& $PYTHON tools/threeway_path_diagnostics.py --check    # 解析后 JSON 内容一致即 exit 0
```

合成样例（脱敏、机器可读、精确有理数字符串）：

- 世界：`configs/strategy/examples/threeway-path-diagnostics-v1.json`
- 输出：`configs/strategy/examples/threeway-path-diagnostics-sample-v1.json`（`--check` 通过）

| 验收项 | 实测 |
| --- | --- |
| 三套策略互斥完备终局路径 | 每套 **6** 条（路径集合三者相同），可达/不可达分别计数 |
| 每套策略概率和 = 1 | `frozen_policy` / `check_fold` / `check_call` 均 `= 1`（精确 Fraction） |
| 每套策略贡献和 = 原 EV | `19407/242` / `0` / `497/8`，与 `metrics[*].net_ev_chips` 逐位相等 |
| 两策略差值和 = 原总 EV 差 | `frozen - check_fold = 19407/242`；`frozen - check_call = 17491/968` |
| 不可达路径条件 EV 未定义 | 标 `UNREACHABLE`、`conditional_terminal_net_ev_chips = null`、贡献 `0` |
| 祖先/后代不重复加总 | 台账只记录**终局**路径；测试断言无任何行是另一行的前缀 |
| 返回策略/场景哈希与完整性状态 | `policy_book_sha256` / `world_scenario_sha256` / `COMPLETE_TERMINAL_PATH_LEDGER` |
| trace 开关数值一致、策略哈希不变 | 除 `path_ledgers` 外整对象相等（`replace(traced, path_ledgers=()) == plain`） |
| 评估世界禁止调用优化入口 | monkeypatch `analyze_threeway_river` 与 `_Tree.value` 抛错后仍得同一结果 |
| 资源不足显式阻塞 | `--trace-max-nodes 1` → `BLOCKED` / `trace_node_budget_exceeded`，无部分台账 |

`PolicyPathLedger.__post_init__` 会**重算**所有和，并要求贡献和等于独立计算出的策略 EV、
fallback 到达质量等于该策略的 `probability_of_any_fallback`；不满足直接抛错，
因此**不存在**部分对账的台账对象。

## 3. 手算对照小例（独立于实现）

`tests/strategy/test_threeway_policy_evaluation_v1.py::hand_example`：底池 60（三个 ACTIVE 各已投 20），
Hero QQ 对 3c3d / 5h6h **恒赢**，故每条终局路径的值 = 底池收入 − 决策根之后的追加投入（整数）。

| 策略 | 手算可达路径（到达概率 × 条件终局 EV = 贡献） | 手算 EV | 实测 |
| --- | --- | --- | --- |
| `frozen_policy` | 1/4×260=65、1/4×160=40、1/4×160=40、1/4×60=15 | 160 | 160 ✅ |
| `check_fold` | 1/2×60=30、1/4×0=0、1/4×0=0 | 30 | 30 ✅ |
| `check_call` | 1/2×60=30、1/4×260=65、1/4×160=40 | 135 | 135 ✅ |

差值和：`160−30=130`、`160−135=25`，与 `delta_vs_check_fold_chips` / `delta_vs_check_call_chips` 相等。

## 4. 边界（必须与上面数字一起读）

- 报告的是**给定世界下的离线条件期望**，**不是**「哪个动作已被证明最优」，也不是 bb/100、盈利率或 GTO 结论。
- 世界是**合成示例**，不是观测到的 AA 范围或已标定响应模型；它**不在**压力筛选的 `worlds` / 候选集合里，
  也不新增策略族（`tools/validate_threeway_models.py` 的候选、世界、指标与 18 这个计数全部未动）。
- 该合成世界**沿用已提交手工示例的牌面、范围与桌规**（含 `rake_percent 0.03` 与已弃牌座位的死钱），
  只把响应权重换成本示例声明的均匀权重并收窄了动作网格；结算完全走仓库既有代码，没有引入新的口径。
- `strategy_eligible` 与 `advice_emitted` 恒为 `false`；未接影子链路、未接 UI、未产生任何实战建议。
