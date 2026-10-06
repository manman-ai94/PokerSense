# PokerSense 开发分支测试与性能报告

> 报告类型：开发分支验证，不是发布验收报告
> 测试日期：2026-08-23
> 测试分支：`codex/multiplayer-strategy-system`
> 被测源码：`8f969fd544609e8c755852c2cadbf1cfc4cdd4e2`
> 当前正式发布版：`v0.1.11`；本报告不改变正式发布能力声明

## 1. 结论摘要

| 结论项 | 结果 | 判定 |
|---|---|---|
| 策略专项回归 | 1,080 passed，0 failed | PASS |
| 可用全量回归 | 1,766 passed，3 skipped，0 failed | PASS，排除了 Quartz 权限文件 |
| Quartz 专项 | 6 passed，7 failed，1 skipped | ENVIRONMENT BLOCKED |
| Mock fixture | 298 个，生成内容与仓库一致 | PASS |
| Python lint | 全量 Flake8 通过 | PASS |
| JavaScript 语法 | `ui/app.js` 通过 `node --check` | PASS |
| Git 文本检查 | `git diff --check` 通过 | PASS |
| Adaptive Equity 性能 | 三个固定 workload 均完成；保守预算仍为 exact=3、MC=2 units/ms | PASS，限当前硬件 |
| 真实 WPK raw-frame Replay | 未提供 | NOT TESTED / RELEASE BLOCKER |
| WPK→Advice→UI 产品 E2E | 未执行 | NOT TESTED / RELEASE BLOCKER |
| 安装包与干净安装 | 未执行 | NOT TESTED / RELEASE BLOCKER |

当前结果证明多人状态/策略核心、合同、Mock 场景和数值引擎在开发环境中回归稳定；它不证明
真实 WPK 多人识别、实时首个建议延迟、交互 UI 或安装包已经达到发布条件。

## 2. 测试环境

| 项目 | 值 |
|---|---|
| 机器 | MacBook Pro `MacBookPro18,3` |
| 芯片 | Apple M1 Pro，10 cores（8 performance + 2 efficiency） |
| 内存 | 32 GB |
| 操作系统 | macOS 26.5.2，build 25F84 |
| Python | 3.13.12 |
| OpenCV | 4.14.0 |
| NumPy | 2.4.6 |
| pytest | 9.1.1 |
| 测试状态 | 本地 `.venv` editable install |

报告不记录设备序列号、Hardware UUID 或其他机器私有标识。

## 3. 本次执行的测试

### 3.1 自动化结果

| Test ID | 命令/范围 | 结果 | 用时 | 说明 |
|---|---|---:|---:|---|
| TR-001 | `pytest tests/strategy` | 1,080 passed | 4.10s | 策略、状态派生、Router、Advice、Equity、Provider、Replay 合同 |
| TR-002 | 全量测试，排除 `tests/perceptual/test_quartz_capture.py` | 1,766 passed，3 skipped | 23.55s | 3 个 skip 均为非 Windows 环境下的 Windows DPI 测试 |
| TR-003 | `tests/perceptual/test_quartz_capture.py` | 6 passed，7 failed，1 skipped | 0.30s | 当前 Python 可执行文件无 Screen Recording 权限 |
| TR-004 | Mock fixture regeneration check | 298 fixtures current | <1s | 固定 schema、manifest 和 hash 一致 |
| TR-005 | `flake8 src tests` | passed | <1s | 全量 Python lint |
| TR-006 | `node --check ui/app.js` | passed | <1s | JavaScript 语法检查 |
| TR-007 | `git diff --check` | passed | <1s | 无 whitespace/error marker |

### 3.2 主要已覆盖功能

| 功能域 | 本次覆盖的代表性内容 | 结果 | 剩余限制 |
|---|---|---|---|
| Temporal/State | 连续帧、UNKNOWN/CONFLICT、换手、原子状态、事件重建 | PASS | 缺真实 WPK raw-frame Replay |
| 2–9 人状态 | 座位映射、人数切换、合法动作、all-in、主池/边池 | PASS | WPK 实际 slot/ROI 未标定 |
| DecisionContext | identity、deadline、输入来源、质量门、缺失字段 | PASS | Live 输入目前不能填满 actor/stack/action-line |
| Range | blocker、贝叶斯更新、小样本收缩、多人组合碰牌 | PASS | 真实 3–9 人范围资产不完整 |
| Equity | HU/multiway exact、Monte Carlo、CI、cache、side-pot share | PASS | 本次未测真实整条 Fast Advice p95 |
| Provider | HU Blueprint、JSON asset、Heuristic、local resolver、GTOpen Adapter | PASS | GTOpen 许可和独立 Golden 仍缺 |
| Router/Fusion | capability、exact/approx、fallback、合法化、拒答、置信度 | PASS | 生产 live Router 尚未注册可发布 Provider |
| Advice/UI wire | READY/PARTIAL/ABSTAIN/STALE、expiry、identity、来源和证据 | PASS | 未做真实窗口 UI 交互验收；逐尺度独立频率尚未进入 wire |
| Training | actual action identity、偏差、已知 EV loss、整手聚合 | PASS | 缺真实行动 Replay 和完整 counterfactual EV |

### 3.3 Quartz 结果解释

Quartz 专项的 7 个失败具有相同前置原因：`QuartzBackend._resolve_window()` 在进入各测试
模拟的“窗口不存在、重名、最小化、边界非法、显式 index”等分支前，先检测到当前
`.venv/bin/python` 没有 macOS Screen Recording 权限并抛出权限错误。因此：

| 项目 | 判断 |
|---|---|
| 是否是策略回归失败 | 否 |
| 是否可以记为通过 | 否 |
| 当前记录方式 | `ENVIRONMENT BLOCKED`，保留 7 failed |
| 完成条件 | 给同一路径 Python/PokerSense 授权后重新运行该文件 |
| 真实 capture smoke | 因权限不可用而 skip，不能视为真实捕获通过 |

后续应让权限检测在这些纯窗口解析单元测试中可注入或被 mock；在修复测试隔离前，仍需保留
独立的真实 capture smoke 来验证 TCC 和真实窗口行为。

## 4. 本次性能结果

### 4.1 Benchmark 定义

运行：

```bash
./.venv/bin/python tools/benchmark_adaptive_equity.py \
  --repeats 5 \
  --hardware-label 'MacBookPro18,3 Apple M1 Pro 10-core 32GB'
```

每个 case 先 warm-up 一次，再记录 5 次；当前脚本的 p95 在 5 个样本中等于最慢样本。
因此这些数字适合作为固定机器上的工程预算校准，不应解释为大规模统计性能结论。

### 4.2 实测数据

| Case | 工作量 | Median | p95 | Maximum | p95 吞吐 |
|---|---:|---:|---:|---:|---:|
| Exact HU flop，8 assignments | 7,920 outcomes | 1,050.542ms | 1,065.064ms | 1,065.064ms | 7.436 outcomes/ms |
| MC HU flop | 10,000 trials | 1,358.545ms | 1,373.229ms | 1,373.229ms | 7.282 trials/ms |
| MC 3-way flop | 10,000 trials | 2,005.105ms | 2,006.896ms | 2,006.896ms | 4.983 trials/ms |

### 4.3 与仓库既有校准比较

既有校准位于 `configs/strategy/adaptive-equity-m1-pro-v1.json`，使用同一硬件、Python
3.12.2 和 5 次重复。本次 Python 3.13.12 结果如下：

| Case | 既有 p95 | 本次 p95 | 变化 | 结论 |
|---|---:|---:|---:|---|
| Exact HU | 1,102.117ms | 1,065.064ms | -3.36% | 略快 |
| MC HU | 1,434.451ms | 1,373.229ms | -4.27% | 略快 |
| MC 3-way | 2,102.024ms | 2,006.896ms | -4.53% | 略快 |

由于环境和 Python 版本不同，本次结果不替换既有版本化校准。两组数据都支持继续采用约
50% 安全系数的保守预算：

| 策略预算 | 当前值 |
|---|---:|
| Exact outcomes per ms | 3 |
| Monte Carlo trials per ms | 2 |
| Safety factor | 0.5 |

### 4.4 已有 GTOpen 执行证据

以下为当前分支已有、但本报告没有重新运行的历史证据，不能与本次 Equity benchmark
混成同一性能样本：

| 项目 | 已有结果 | 本报告判定 |
|---|---|---|
| GTOpen 上游 Solver tests | 104 passed，1 benchmark ignored | 历史通过，本次未重跑 |
| 3-player 20BB 小树 API probe | 13 nodes、6 action nodes、0.016224MB；25 iterations 时 gap 0.0004571471BB | API 可执行性证据，不是稳定延迟基准 |
| 3-player AKo Slow Advice E2E | 4,270 nodes、1,710 action nodes、5.771688MB；100 iterations 时 gap 0.008207490846030292BB | 策略链证据；没有重复分布，不能报告 p95 |

## 5. 性能目标完成情况

| Metric | 目标 | 当前证据 | 状态 |
|---|---:|---|---|
| `PERF-CTX` | Stable state→Context p95 ≤10ms | 只有功能测试，没有独立当前 p95 报告 | NOT MEASURED |
| `PERF-LOOKUP` | 热 preflop lookup p95 ≤10ms | Cache/lookup 功能测试通过，未生成当前分布 | NOT MEASURED |
| `PERF-FIRST` | Stable state→first Advice p95 ≤300ms | Adaptive budget 已校准；真实 capture/Provider/UI 未闭环 | NOT PROVEN |
| `PERF-UI` | WebSocket receive→paint p95 ≤25ms | Wire/sequence 测试通过，未在真实浏览器测 paint | NOT MEASURED |
| `PERF-STABILITY` | 长 session 无闪回/持续内存增长 | 过期/identity 测试通过；未做长时 RSS soak | PARTIAL |
| `PERF-SLOW` | 报告 resolver 分布和 timeout rate | timeout/故障功能路径通过；无重复延迟分布 | PARTIAL |
| Equity operation budget | 目标硬件保守吞吐 | 本次三项 benchmark + 既有校准 | MEASURED |

不能用“10,000 次 MC 在约 1.4–2.0 秒完成”直接判断 `PERF-FIRST` 失败，因为生产 Adaptive
Equity 会根据 Advice deadline 选择更小 trial budget 并允许 PARTIAL；同样也不能据此声明
`PERF-FIRST` 已通过，必须测量真实 stable-state→render 链路。

## 6. 需求与测试判定

| 能力 | 功能测试 | 性能/真实证据 | 当前判定 |
|---|---|---|---|
| 2–9 人策略核心 | 完整通过 | Mock/参数化为主 | IMPLEMENTED，未发布 |
| Multiway Equity | 完整通过 | 当前 M1 Pro benchmark 已测 | IMPLEMENTED |
| GTOpen Preflop Adapter | 21 个 Adapter 测试和策略回归通过 | 有一次真实 API E2E，无稳定 p95；许可缺失 | RESEARCH ONLY |
| WPK Hero cards | 现有功能测试 | 已有平台基线 | 当前发布支持 |
| WPK dealer/actor/stack/action/pot/board | 合同和 Synthetic 测试通过 | 无授权真实 Replay | PLANNED / BLOCKED |
| Advice wire/UI 状态机 | 自动测试通过 | 无真实窗口和浏览器 paint 数据 | IMPLEMENTED，验收未完成 |
| 完整产品 E2E | 各模块测试大部分通过 | 无 WPK raw-frame→UI 证据 | NOT COMPLETE |
| 发布候选 | 不适用 | 缺 R6、包构建和干净安装 | NOT READY |

## 7. 未完成项与下一次测试计划

| 优先级 | 缺口 | 下一步测试产物 |
|---:|---|---|
| P0 | Quartz 单元测试受真实 TCC 前置门影响 | 注入 permission probe；单元测试无 TCC 依赖，真实 smoke 单独保留 |
| P0 | 缺 WPK 真实多人识别 | 授权 raw-frame Replay、mapping/calibration hash、逐字段质量报告 |
| P0 | 缺产品 E2E | 固定版本执行 `capture→state→context→Advice→WebSocket→paint` |
| P0 | 缺 Fast Advice 用户性能 | 记录各阶段 p50/p95/p99 和 total p95 |
| P0 | 缺真实 UI 验收 | READY/ABSTAIN/STALE/Fast→Slow 截图、录屏和 paint latency |
| P1 | 缺长时稳定性 | 30–60 分钟 soak、RSS、cache hit/eviction、旧 Advice 闪回计数 |
| P1 | 缺 GTOpen 延迟分布 | 固定 trees 重复运行，记录 solve p50/p95、timeout、gap 和 CPU/RSS |
| P1 | 缺发布包证据 | PyInstaller、bundle version、codesign structure、干净安装和权限 |

## 8. 最终判定

本次开发分支满足“策略核心进入协作/代码评审”的自动化门槛：策略专项、可用全量、lint、
Mock 和 Adaptive Equity 校准均有通过证据。当前不能进入发布候选，也不能宣称完整产品端到
端完成，主要阻断项是 WPK 真实识别 Replay、Quartz/TCC 验收、真实 UI、Fast Advice 全链
性能和安装包验证。

伙伴的识别/UI 交付任务见 `docs/recognition-ui-handoff.md`；测试定义和发布门槛见
`docs/strategy-regression-test-matrix.md`。
