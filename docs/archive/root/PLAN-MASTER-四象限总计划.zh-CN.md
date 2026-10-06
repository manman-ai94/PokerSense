# PLAN-MASTER · 四象限总计划（可盈利 / 稳定 / 快速 / 自我进化）

> 2026-09-08 用户更新：当前执行顺序以 [WPK 视频优先工作计划](PLAN-WPK-video-first.zh-CN.md) 为准。
> 先用 G 盘 WPK 录像完成软件回放、识别/状态/策略验证，最后做真机差异验收；AA 第二阶段。本文件保留为总体能力目标。

> 编制 2026-09-06 · owner 定调：全部本地运行，GitHub 仓库（windgeek/PokerSense）仅作技术路线参考源，不再回推。
> 本计划取代四板块计划（PLAN-A/B/C/D）作为顶层路线；A/B/C/D 作为各 Phase 的细化附件继续有效。
> 硬红线不变：绝不自动点击/下注/控制客户端；失败即关闭（UNKNOWN/ABSTAIN）；不宣称 GTO。

---

## 0. 目标定义与量化验收

| 象限 | 定义 | 量化验收（达到才算完） |
|---|---|---|
| **快速** | 实时建议不拖慢真人决策 | p95 首次建议 ≤ 300ms（当前 282.5ms 已达标，需保不住回退）；帧泵跟随真实采集速率 |
| **稳定** | 长运行不崩、不飘、可复现 | ①真机 30 分钟连续运行零崩溃；②一致性五判据（确定性哈希/状态一致率 100%/权益偏差 P95≤0.005/AAR≥99%/flip rate=0）；③缓存语义自洽（Phase 1 三暗伤清零）；④回归全绿 |
| **可盈利** | 建议具备 EV 依据，覆盖真实盈利决策点 | ①翻后（river→turn→flop）有策略覆盖；②建议带 EV 比较与加注尺寸；③200–500 个 golden spots 通过求解器基准校验；④能力清单只写有证据的场景 |
| **自我进化** | 打牌数据回流，系统越用越强 | ①每手牌自动 Debrief（EV loss/漏点分类）；②同类漏点自动生成训练题；③对手画像分桶更新并影响后续范围先验；④Live 建议与 Debrief 对同一节点口径一致 |

## 1. 当前基线（2026-09-06 实跑）

- 回归：**2266 passed / 0 failed / 1 skipped / ~31s**
- 延迟：vision 11.6ms / state 0.085ms / 权益 MC 263.9ms（96%）/ total p95 282.5ms
- 策略覆盖：{6,7,8,9} 人 / PREFLOP / unopened / 100bb / HEURISTIC，无 EV 无尺寸；**翻后零覆盖**
- 采集：ADB 9 字段全标定；capture-card 仅 card（B 板块收尾中）
- 求解器结论：无开源多人翻后求解器；TexasSolver 为翻后最省事路径（river 0.06s / turn 4.21s / flop 98s 须离线）

## 2. 阶段路线

### Phase 1 · 稳定加固（先行，工作量小、风险高）✅ 已完成 2026-09-06
1. ✅ 修 `adaptive_equity.py`：被墙钟截断的 MC（`samples < planned trials`）一律不入缓存，脏命中消除
2. ✅ exact/MC 滞回：`exact_method_hysteresis=0.10` 滞回带 + MC 路径优先探测 exact 缓存键（deadline 收缩不再退化为 MC PARTIAL）
3. ✅ `EquityCache` 新增 `default_ttl_seconds=300.0`，与 `StrategyCache` 语义对齐
4. ✅ 本机实测（Core Ultra 5 245KF）：exact 9.38 outcomes/ms → `exact_outcomes_per_ms` 3→4（0.5 安全系数），新标定文件 `adaptive-equity-core-ultra-5-245kf-v1.json`，engine_version → v3
5. ✅ 新增 12 个测试全部钉死；回归 **2278 passed / 1 skipped**（基线 2266 → 2278）

### Phase 2 · 采集卡九字段全通（板块 B 收尾，B1–B6）
pot 识别器 → actor 识别器 → street 派生 → 生产模板资产 → ROI/布局补全 → 标定落地工具。
验收：`load_measured_calibrations()` 返回 9 字段（Wilson 下界、0≤ceiling<floor≤1）；采集卡端到端 READY。
**复用价值**：标定落地工具做完，AA 平台直接复用同一流程。

### Phase 3 · 可盈利核心：翻后策略（板块 C2，最大工程）
按架构 L0–L4 分层落地，**river 先行**：
1. **C2.0 求解器接入**：TexasSolver（AGPL-3.0，自用不商用已放开范围）Windows 预编译 + CLI，独立进程调用；影子模式运行，绝不进同步 Fast Path。`b-inary/postflop-solver` 的 bunching effect 把 6-8 人桌翻后拆解为单挑子问题。
2. **C2.1 river resolver**（L4）：0.06s 可实时，先接 river subgame，输出 action EV + 频率 + 尺寸。
3. **C2.2 L2 预解缓存**：flop 98s 必须离线 → 批量预解标准节点建 canonical cache（5–20ms 命中）。
4. **C2.3 L3 轻量近似**：cache miss 时的 policy/value 近似（10–80ms）。
5. **C2.4 golden spots**：200–500 个节点人工/求解器基准校验，EV 偏差达标才准入能力清单。
6. 路由升级 `TieredStrategyRouter`，全部层 miss 返回 NO_STRATEGY，不构造伪 candidate。

### Phase 4 · 自我进化（M3/M4，依赖 Phase 3 的 EV）
1. Hand Debrief：消费与 Live 相同的状态/事件/策略接口，逐节点算 EV loss
2. 漏点分类 + 同类训练题生成（Learner Profile）
3. OpponentProfile 实质化：位置/街道/pot type 分桶后验，KL-regularized 剥削融合
4. 数据回流：实际动作 → 范围先验更新 → 影响下一手建议
5. 参考 rlcard / PyPokerEngine 等开源框架做自我对弈评估沙盒（执行时调研核实）

### Phase 5 · 发布就绪与持续优化（板块 D 收尾）
D2 测试基建（fastapi）、D3 UI 遗留、D4 真机验证（干净安装/30 分钟/拔插恢复）、R0–R6 门槛逐项勾选。

## 3. 开源参考清单（自用不商用，范围放开）

| 项目 | 用途 | 状态 |
|---|---|---|
| `bupticybee/TexasSolver` | 翻后求解主力（Windows 预编译 + CLI） | 已调研，Phase 3 接入 |
| `b-inary/postflop-solver` | bunching effect 多人→单挑拆解 | 已调研，Phase 3 |
| `MatthewPDingle/GTOpen` | 翻前多人范围本地交叉验证 | 已构建于 `.upstream/`，仅离线 |
| `datamllab/rlcard` | 自我对弈/训练沙盒参考 | Phase 4 调研核实 |
| `ishikota/PyPokerEngine` | 对弈引擎与对手建模参考 | Phase 4 调研核实 |
| DeepStack/Pluribus 论文与开源复现 | L3 轻量 policy/value 思路 | Phase 3.5 调研核实 |

> 合规说明：自用、不对外提供网络服务。求解器仍以独立进程隔离（工程理由：延迟与稳定性，不仅是许可证）；源码/二进制不进仓库。

## 4. 工程红线（全过程有效）

- 全部本地运行；不推远程、不做 CI/CD；本地用 `git add -A` + `git commit` 做检查点
- 中文路径仓库禁止 `checkout -b`/`stash`/`rebase`/`gc`/`prune`
- 外部 C/C++/Rust 构建一律在 ASCII 路径编译再复制回来
- 慢求解器只跑影子模式；永远不实时的：标定统计、ROI/座位映射、GTO 范围表、翻后批量求解
- 每 Phase 结束：回归全绿 + 更新本文件状态 + 追加工作日志
