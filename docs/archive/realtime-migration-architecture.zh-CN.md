# 从离线预计算迁移到实时计算 —— 架构方案与实现要点清单

- 版本：v1.0
- 日期：2026-09-06
- 范围：PokerSense（德州扑克**训练陪练**工具，**不是外挂**）
- 立场：本文件为**设计方案 + 验收标准**，不改动任何生产代码。全部工作可在本地完成，无需进仓库。
- 读者：需要按此清单执行并进行验收的人。

---

## 0. 结论先行

### 0.1 先纠正一个前提：本系统**不是**"纯离线预计算"

实测代码后的现状是**混合态**，而且实时的部分比想象中多：

| 层 | 现状 | 性质 |
|---|---|---|
| 帧采集 | `DeviceFrameSource` + `RealtimePipeline.step()`，change-gated | **已经是流式** |
| 感知确认 | `realtime/temporal_consensus.py`（N 帧连续确认） | **已经是流式增量** |
| 手牌边界 | `realtime/hand_boundary.py`（fail-closed） | **已经是流式** |
| 状态重建 | `state_engine/action_reconstruction.py`，事件流 → 快照，`state_version` 严格单调 | **已经是增量** |
| 权益 | `strategy/adaptive_equity.py`，**deadline-aware**，exact/MC 自动选择，seed=42 | **已经是实时计算（带 deadline）** |
| 对手范围 | `strategy/range_tracker.py` 逐步过滤 | **已经是增量** |
| 策略建议 | `PreflopRfiHeuristicProvider` 读 `preflopr-explicit-rfi-ranges.json` | **离线预计算 + 查表** |
| 视觉标定 | `configs/vision/*/calibration.json`，Wilson 95% 下界 | **离线统计，只读** |
| ROI/座位映射 | `configs/vision/*/*_slot_layout.json`、`configs/platform/*.json` | **离线标注，只读** |

所以"改造为实时计算"**不是推倒重来**，而是补 4 件事：

1. **把 1 秒轮询改成事件驱动帧泵**（延迟可控）—— 当前 `desktop/live.py::live_analysis_stream` 是 `await asyncio.sleep(interval_seconds)` 固定 1.0s 轮询，与 pipeline 的 change-gated 设计互相打架。**实测：这一条让端到端延迟被放大约 4.6 倍**（见 §0.2）。
2. **把"纯内存态"改成"可持久化事件流"**（可复现 / 可回测）—— 现在进程一崩，整手状态全丢，且没有任何落盘事件日志（grep 全仓无 sqlite / jsonl 写入）。
3. **把"每次重算"改成"增量流式 + 影子全量双轨校验"**（一致性）。
4. **把"异常即抛"改成"降级 + 告警 + 缺口标记"**（可靠）—— 当前采集异常直接 `raise LiveCaptureError` 终止整条流。

### 0.2 实测延迟基线（2026-09-06 实跑，非估算）

用仓库里已有的 `tools/benchmark_realtime_latency.py --repeats 20` 跑出来的数字：

| 阶段 | p50 | p95 | 备注 |
|---|---|---|---|
| capture | 0.0 ms | 0.0 ms | **合成帧，no-op，不反映真实采集** |
| vision | 11.6 ms | 13.3 ms | |
| state | 0.085 ms | 0.095 ms | |
| **equity（MC 2000 trials）** | **263.9 ms** | **272.8 ms** | **占总耗时的 96%** |
| **total** | **275.4 ms** | **282.5 ms** | 现有判据 p50<500 且 p95<500 → **PASS** |
| equity（exact，仅河牌） | **0.006 ms** | 0.007 ms | 比 MC 快约 4.4 万倍 |

三个直接推论，决定了改造的先后顺序：

1. **轮询是当前延迟的最大放大器。** 纯计算只要 275ms，但 1.0s 的固定轮询把实际端到端拉到约 **1000 + 275 ≈ 1.28 s**。去掉轮询，端到端直接降到约 275ms + 真实采集耗时。**这是投入产出比最高的一改，也是 S1 唯一的重点。**
2. **权益是唯一瓶颈，且余量只有 36 ms。** 264ms 的 MC 顶着 `default_deadline_ms=300`，机器一忙就会触发墙钟截断 → 采样数不足 → 数值抖动。这直接印证了 §8 陷阱 #1。
3. **河牌的 exact/MC 选择需要重新标定（P3-7）。** 河牌 exact 枚举极快（实测 0.006ms），但 `adaptive_equity` 里预算判据是 `estimated_outcomes <= min(100_000, deadline_ms × exact_outcomes_per_ms)`，而 `exact_outcomes_per_ms=3` 这个常数把预算压到只有 **900 outcomes**。
   - ⚠️ **更正**：初版此处写成"河牌应强制走 exact"，**这是错的** —— 河牌 `board_needed=0` → `runouts=1`，`estimated_outcomes` 就等于 `assignments`，代码**已经**在 `assignments ≤ 900` 时自动选 exact，不需要强制。
   - **真正的问题**是反向的：当河牌 `assignments > 900`（多人底池很常见）时，会掉进 MC，而 `trials = min(50_000, 300×2) = 600` **低于** `minimum_mc_trials=2000` → `status=PARTIAL`，拿到一个采样不足的结果。
   - 所以 P3-7 应该是**实测 `exact_outcomes_per_ms` 这个常数**（它很可能过于保守），**而不是**强制切 exact。

> 注意：该工具的 capture 阶段是 no-op，用的是 `render_table` 合成帧，**不反映真实采集延迟**（真实采集卡实测 VFR，标称 30fps 实际 ~10fps ≈ 100ms/帧）。因此 §6.2 的预算必须把真实采集单独计入。

### 0.3 有三个东西**永远不该**实时化

| 产物 | 为什么不能实时化 | 正确做法 |
|---|---|---|
| 平台 ROI 几何 / slot layout / seat mapping | 依赖人工标注真值，实时算是循环论证 | 离线标注 → 版本化 JSON → 运行时只读 + 加载时校验 sha256 |
| 视觉置信度标定曲线 | 需要成百上千标注样本才能估准；实时只能用已标定的结果 | 离线批量标定（Wilson 下界）→ 只读；样本积累到阈值再重算 |
| 上游 GTO 范围表 / 翻后求解 | flop 单局实测 98s 量级，物理上不可能在决策窗口内出结果 | 离线预计算成资产（现在的做法是对的）→ 运行时查表；实时求解器只能跑**影子模式** |

**实时化的目标是"信号新鲜度"，不是"把求解器搬进决策回路"。** 把慢求解器塞进同步路径，是这个改造里最容易犯的致命错误。

### 0.4 分期

S0 观测埋点 → S1 事件驱动帧泵 → S2 事件日志 WAL + 快照 → S3 双轨一致性校验 → S4 断线重连与补齐 → S5 降级链与告警。

**先做 S0。** 没有延迟数据就做实时化改造，等于闭着眼睛调参。

---

## 1. "离线预计算"在本系统的具体含义

### 1.1 定义

> **离线预计算** = 在实盘会话之外，由人工标注、批量统计或外部求解器**提前**把「指标 / 参数 / 信号表」算好，固化成带版本号与校验和的只读文件；实盘运行时**不做**产生这些数值的计算，只做反序列化 + 查表 + 线性插值。

注意一个事实：**本系统目前没有任何 sqlite / jsonl 指标落盘**。所谓"落盘"实际是 5 类静态资产 + 2 个内存 LRU 缓存。

### 1.2 离线产物清单（实测）

| 资产 | 生成方式 | 更新频率 | 运行时角色 | 能否实时化 |
|---|---|---|---|---|
| `configs/vision/*/calibration.json` | 标注样本统计（Wilson 95% 下界，字段级） | 月级 | 识别置信度 → `ConfidenceGate` | ❌ 永久离线 |
| `configs/vision/*/{hero,board,dealer,empty}_slot_layout.json` | 人工标注 ROI | 平台变更时 | 裁剪区域 | ❌ 永久离线 |
| `configs/vision/wepoker_android_capture_card/card_heads.json` | 离线聚类出的牌面模板 | 模型升级时 | 模板匹配 | ❌ 永久离线 |
| `configs/platform/*.json` + `_seat_mapping.json` | 人工标注 slot→seat | 平台变更时 | 座位映射 | ❌ 永久离线 |
| `strategy/assets/preflopr-explicit-rfi-ranges.json`（11 KB） | 上游 GTO 范围表 + 本仓派生（`derived_ranges` 13 键） | 季度 | **翻前 RFI 信号本体** | ❌ 永久离线（求解延迟） |
| `configs/strategy/adaptive-equity-m1-pro-v1.json` | 离线拟合的引擎参数 | 季度 | `AdaptiveEquityPolicy` | ⚠️ 参数离线、**计算实时**（现状正确） |
| `EquityCache`（内存 LRU，256 条，key 含 `engine_version`） | 运行时填充 | 每次决策 | 权益结果复用 | ✅ 已是实时侧的缓存 |
| `StrategyCache`（内存 LRU，256 条，**TTL 300s**，key 含 `engine_version` + `provider_id`） | 运行时填充 | 每次决策 | 策略候选复用 | ✅ 已是实时侧的缓存 |

### 1.3 三个维度的差异

| 维度 | 离线预计算 | 实时计算 | 本系统的落点 |
|---|---|---|---|
| **数据延迟** | 分钟~季度级（取决于重算周期）。**优点**：延迟稳定、可预测、与机器负载无关 | 毫秒~秒级。**代价**：延迟是**分布**而非定值，受采集帧率、CPU 负载、GC、IO 影响 | 纯计算实测 p50 275ms / p95 283ms；但 **1.0s 固定轮询**把端到端拉到约 1.28s。权益有 300ms deadline 保护（余量仅 36ms），帧泵**没有任何**延迟保护 |
| **结果一致性** | 同一输入 → 同一输出，**天然可复现**（文件不变则结果不变） | 同一输入 → 输出**可能不同**：deadline 截断导致 MC 采样数浮动、并发顺序、浮点累积、缓存 STALE 交叉 | **这是最大风险点**，见 §9 |
| **可回测性** | 强：历史任意时刻可重放（只要保留了当时的资产版本） | 弱：不落事件日志就无法重放；且重放结果可能与当时不一致 | 目前**没有事件日志**，只有 `replay/capture_replay.py` 能重放**预先录制**的 artifact（带 sha256 完整性校验）——这是现成的回测底座，要复用 |

**一句话**：离线换来的是"确定性"，实时换来的是"新鲜度"。本系统里，**能离线的部分（标定 / 几何 / 范围表）继续离线，这是对的选择**；真正要实时化的是**感知-状态-权益-建议这条链路的调度与持久化**。

---

## 2. 目标架构

```
┌─ 采集进程 ────────────────────────────────────────┐
│ FramePump(事件驱动, 背压, 心跳, 单调 frame_seq)      │
│   └─ 断流检测 → GapMarker（不静默补帧）             │
└──────────────┬────────────────────────────────────┘
               │ 帧队列（有界，背压）
┌──────────────▼─ 计算进程 ─────────────────────────┐
│ VisionEngine → TemporalConsensus → HandBoundary    │
│      ↓ RawObservation                             │
│ Orchestrator → StateEngine(事件流, state_version)  │
│      ↓                    ↘ WAL(append-only jsonl) │
│ SnapshotStore(周期快照)    ↘ Snapshot(每 N 事件)    │
│      ↓ DecisionContext                            │
│ AdaptiveEquity(deadline-aware, 固定 trials)         │
│      ↓                                            │
│ StrategyRouter → Provider(s) → Advice/ABSTAIN      │
└──────────────┬────────────────────────────────────┘
               │ 建议帧（带 trace_id + 延迟分解）
┌──────────────▼─ UI 进程 ──────────────────────────┐
│ 渲染 + 降级提示 + GAP/STALE 标识                    │
└───────────────────────────────────────────────────┘

┌─ 影子（异步，绝不进同步路径）────────────────────────┐
│ ShadowRunner: 消费同一份 WAL → 全量重算 → 与实时结果 │
│ 比对 → 不一致率指标 + 逐条归因                       │
└───────────────────────────────────────────────────┘
```

**关键设计原则**

1. **单一事实来源是事件流（WAL），不是内存状态。** 内存状态是事件流的物化视图，随时可重建。
2. **影子计算与实时计算消费同一份事件流**，保证输入完全同源，差异只可能来自计算路径。
3. **慢的东西一律异步**：外部求解器、全量重算、标定重算都不进同步决策路径。
4. **降级优先于猜测**：任何环节超时/失败 → `ABSTAIN`/`PARTIAL`/`UNKNOWN` + 明确 reason，**绝不**用旧值冒充新值、绝不用单挑结果近似多人底池。

---

## 3. 指标分类：增量流式 / 定时批量 / 双轨 / 永久离线

### 3.1 判定规则

一个指标能否增量流式，依次问 4 个问题，**任一为否 → 不能纯增量**：

1. **可重放幂等**：给定相同事件序列，增量结果与全量重算结果是否一致？（一致性）
2. **误差可界**：增量累积的截断/浮点误差是否有可证明的上界？（有界性）
3. **状态有界**：增量算子的状态是否会随手数无界增长？（内存有界）
4. **无全局依赖**：计算当前值是否需要未来信息或全窗口数据？（无回溯依赖）

### 3.2 分类结果

#### A. 增量流式（实时主路径）

| 指标 / 计算 | 现状 | 增量算子 | 状态量 |
|---|---|---|---|
| 帧级字段确认 | 已有 `TemporalConsensus` | 连续 N 帧同值则提升，冲突则回退 | 每字段 pending 值 + 计数 |
| 手牌边界检测 | 已有 `HandBoundary` | 观察差分 | 上一帧 obs |
| 状态快照 | 已有 `action_reconstruction` | 事件追加 → 新 `state_version` | 事件列表 |
| 权益 | 已有 `adaptive_equity` | **改成"续跑式 MC"**：同 seed 继续追加 trials，不清零重跑 | samples 累计 + 矩累计 |
| 对手范围过滤 | 已有 `range_tracker` | 每动作一次贝叶斯式过滤 | combo 权重表（1326 上限，有界） |
| 玩家频率统计（VPIP/PFR/3bet/fold-to-cbet） | **缺失** | 计数 + 指数衰减（半衰期 N 手） | 固定维度计数器 |
| 底池 / 有效筹码 / SPR | 已有（状态派生） | 随事件更新 | 标量 |
| 延迟与健康指标 | **缺失** | 滑动分位数（t-digest 或固定桶直方图） | 固定桶（有界） |

#### B. 定时批量重算（周期性对账）

| 指标 | 周期 | 为什么不能纯增量 |
|---|---|---|
| 对手范围**联合分配归一化** | 每 50 手 / 每次街推进 | 连乘权重会数值下溢，增量截断误差无界 |
| 置信度标定曲线 | 样本 +200 或 30 天 | 需要标注真值集，统计性质 |
| 策略缓存预热 | 每日冷启动 | 纯性能，非正确性 |
| 聚合指标（小时/日级汇总） | 每小时 | 浮点累积误差，用全量重算清零 |
| `derived_ranges` 派生资产校验 | 每次资产加载 | 加载期一次性校验（现已有 `_validate_derived`） |

#### C. 双轨校验（实时 + 影子离线，持续比对）

| 对象 | 实时路径 | 影子路径 | 比对内容 |
|---|---|---|---|
| 权益 | MC（固定 trials，deadline 内） | Exact（无限时，后台） | 点估计偏差、区间覆盖 |
| 状态 | 增量事件重建 | 从头全量重放同一事件流 | 逐 `state_version` 规范化 diff |
| 策略建议 | 资产查表 / 启发式 | 外部求解器（异步，可能几十秒） | 动作一致率、EV 差 |
| 频率统计 | 增量衰减计数 | 全窗口精确计数 | 相对偏差 |

#### D. 永久离线（明确不做实时化）

见 §0.2。标定、ROI 几何、座位映射、上游范围表、翻后求解输出。

---

## 4. 状态管理

### 4.1 事件溯源 + 快照

- **WAL（append-only）**：每条记录一行 JSON，字段至少包含
  `seq`（进程内单调）、`hand_id`、`state_version`、`event_type`、`payload`、`ingested_at(UTC, aware)`、`source_frame_seq`、`schema_version`。
- **快照**：每 N=200 个事件或每次街推进写一份快照 `{hand_id, state_version, state_canonical_json, wal_offset, sha256}`。
- **恢复**：`load latest snapshot → 重放 offset 之后的 WAL`。重放必须幂等。
- **文件布局（本地即可）**：`{data_root}/sessions/{session_id}/wal.jsonl`、`snapshots/*.json`、`manifest.json`。

**为什么**：没有 WAL 就没有可回测性，也无法做 §8 的一致性验证。这是整个改造的地基，S2 必须做。

### 4.2 幂等与乱序

- 排序键：`(source_frame_seq)`，由帧泵在**采集侧**分配，严格单调。
- **不要用画面里的手机时钟或容器时间戳**：实测采集卡是 VFR（容器标称 30fps，实际 ~10fps），时间基不可信，用它排序必然乱序。
- 迟到事件：定义 `watermark = max(seq) - max_late(默认 2)`。迟于 watermark 的事件**不**回填历史状态，而是写入 `late_events` 并触发该手标记 `SUSPECT`。
- 重复事件：`(hand_id, source_frame_seq, event_type)` 唯一键，重复则丢弃并计数。

### 4.3 手牌边界与断流

- 断流期间可能已经换手。`HandBoundary` 的确认依赖连续帧，断流后**不能**直接沿用旧 `hand_id`。
- 规则：断流 > `hand_boundary_uncertainty_window`（默认 3s）→ 恢复后强制进入 `HAND_ID_UNKNOWN`，直到重新确认庄位 + 底牌；在此期间**禁止**输出策略建议，UI 显示 `UNKNOWN`。

---

## 5. 断线重连与历史补齐

### 5.1 分级处理

| 级别 | 场景 | 处理 | 是否可补齐 |
|---|---|---|---|
| L0 | 单帧丢弃（采集抖动） | 帧泵记录 `gap`，继续；consensus 的 pending 计数**不清零**（避免确认被重置） | ✅ 无需补 |
| L1 | 秒级断流（USB 重枚举、ADB 瞬断） | 重连后继续；`gap` 计入该手 `SUSPECT` | ⚠️ 部分可补（状态连续性靠下一帧差分校验） |
| L2 | 十秒级断流 | 重连 + 强制手牌边界重估；可能已漏掉整条街 | ❌ 不可补 → 标记 `GAP`，该手不产出训练结论 |
| L3 | 进程崩溃 / 重启 | 从 WAL + 快照恢复；重连采集 | ✅ 状态可补，画面不可补 |
| L4 | 平台/配置不匹配 | 直接 fail-closed，不猜 | ❌ |

### 5.2 补齐原则（红线）

1. **缺口绝不静默填补。** 任何 `GAP` 必须体现在：`hand.quality_flags`、`UI 的 STALE/UNKNOWN 标识`、影子比对的排除集。
2. **补齐只补"状态"，不补"信号"。** 可以从 WAL 重放恢复状态；但断流期间错过的决策点，**不回溯生成**"如果当时在会怎么建议"的假建议去污染统计。
3. **补齐后的第一帧必须重新确认**：底牌、庄位、街次、底池四项，任一未确认 → 该手 `SUSPECT`。
4. **重连退避**：指数退避 0.5s → 1s → 2s → 4s → 8s（上限 30s），带 ±20% 抖动；连续 5 次失败 → 停止重连并告警（避免无效重连烧 CPU 影响其他模块）。

---

## 6. 可靠性设计

### 6.1 无单点故障

| 现状风险 | 缓解 |
|---|---|
| 单进程内 `asyncio.to_thread(pipeline.step)` 承担采集+识别+状态+策略 | 拆 3 进程：采集 / 计算 / UI，用**有界队列**解耦。最小可行版先拆"采集"与"计算"两进程 |
| 任一异常 → `raise LiveCaptureError` 终止整条流 | 改成**分级**：采集失败可重试、识别失败降级为 `UNKNOWN`、策略失败降级为 `ABSTAIN`，只有"平台不可恢复"才终止 |
| 权益计算阻塞帧泵 | 权益有自己的 `deadline_ms`；帧泵**永不等待**策略结果，UI 消费最近一次完成的结果 + `stale_after` |
| 影子计算拖慢主路径 | 影子读 WAL 副本，独立进程，`nice` 降级，可被随时 kill 而不影响实盘 |

### 6.2 延迟预算（管线预算 + 端到端预算，两套不可混用）

预算分两套，**不要混用**：

**(a) 管线计算预算**（不含真实采集、不含策略 Provider）—— 沿用现有工具判据 `p50 < 500ms AND p95 < 500ms`：

| 阶段 | 实测 p50 | 实测 p95 | 目标 P95 | 说明 |
|---|---|---|---|---|
| vision | 11.6 ms | 13.3 ms | ≤ 30 ms | 余量充足 |
| state | 0.085 ms | 0.095 ms | ≤ 5 ms | 可忽略 |
| 权益（翻前/翻牌/转牌 MC） | 263.9 ms | 272.8 ms | ≤ 280 ms | **唯一瓶颈，余量仅 36ms** |
| 权益（河牌，改 exact 后） | 0.006 ms | 0.007 ms | ≤ 5 ms | 见 P3-7 |
| **管线合计** | **275.4 ms** | **282.5 ms** | **≤ 500 ms**（现有判据） | 实测已 PASS |

**(b) 端到端预算**（画面变化 → UI 出新建议，含真实采集与策略）：

| 阶段 | 目标 P50 | 目标 P95 | 硬上限 | 超时行为 |
|---|---|---|---|---|
| 真实帧采集（含背压等待） | 100 ms | 200 ms | 400 ms | 丢帧（计入 gap）。参考 VFR 实测 ~100ms/帧 |
| vision | 15 ms | 40 ms | 80 ms | 该帧字段置 UNKNOWN |
| 状态重建 | 1 ms | 10 ms | 30 ms | 保留上一 `state_version`，标 STALE |
| 权益 | 90 ms | 280 ms | 300 ms（= `default_deadline_ms`） | `status=PARTIAL` + 宽区间 |
| Provider 查询（资产查表） | 2 ms | 20 ms | 50 ms | 降级到下一 Provider |
| **端到端** | **400 ms** | **900 ms** | **1500 ms**（对齐 `strategy_live.deadline_ms`） | UI 显示 `DEGRADED` + 时间戳 |

**为什么端到端目标（900ms P95）比管线预算（500ms）宽**：端到端额外包含真实采集（合成帧测不到，实测约 100ms/帧）、策略 Provider、UI 渲染与序列化。**当前 1.0s 轮询下这个值约 1.28s，改造后应落在 400–500ms 区间。**

**验收方式**：每帧输出 `trace_id` + 各阶段耗时分解；跑满 30 分钟**真实采集**（不能用合成帧），统计 P50/P95/P99/max。

### 6.3 降级链（L0 → L4）

| 级别 | 触发 | 行为 | UI 呈现 |
|---|---|---|---|
| L0 正常 | — | 全链路实时 | 正常 |
| L1 弱计算 | 权益 PARTIAL | 仍出建议，但 `numerical_confidence` 下降、区间变宽 | 数值带 ±区间 |
| L2 无权益 | 权益超时/失败 | 出**不含 EV** 的建议（纯范围启发式），标注 `NO_EV` | 显示"仅范围建议" |
| L3 无策略 | Provider 全不匹配 | `ABSTAIN` + reason（如 `unsupported_player_count`） | 显示"无覆盖" |
| L4 无感知 | 识别置信度低于 gate / 断流 | `UNKNOWN`，**保留上一帧显示但明确标 STALE** | 灰化 + STALE 角标 |

**注意 L4 的坑**：现在的代码已经处理过一次这个问题（`pipeline.py:169-177` 的注释：置信度必须逐帧刷新，否则会永久显示过期牌面）。改造时**不能回退**这个行为。

### 6.4 告警清单

| 指标 | 阈值 | 动作 |
|---|---|---|
| 端到端 P95 延迟 | > 1200 ms 持续 2 min | WARN |
| 权益 `PARTIAL` 占比 | > 5% 持续 5 min | WARN（说明 deadline 或 trials 配置不合理） |
| 帧 gap 率 | > 2% 持续 1 min | WARN；> 10% → ERROR |
| `ABSTAIN` 占比 | > 30% 持续 10 min | WARN（可能是能力覆盖不足，非故障） |
| 影子不一致率 | 见 §8，超阈值 | **ERROR，停止对外产出建议**（fail-closed） |
| WAL 写入失败 | 任意一次 | **ERROR，立即停止会话**（宁可停，不可不可复现） |
| 重连连续失败 | 5 次 | ERROR，停止重连 |

---

## 7. 胜率保障：实时 vs 离线一致性验证方法

**核心命题**：实时化本身**不应该**改变信号质量。要证明这一点，需要把"实时路径"和"离线基准路径"喂**完全相同**的输入，然后比输出。

### 7.1 基线集（Golden Set）

- 用 `replay/capture_replay.py` 现成的框架（它已带 sha256 完整性校验、平台身份校验、期望值断言）。
- 构造 ≥ 3 类基线集：
  1. **真实采集基线**：已有的 `capture_card_calibration_*` 数据集（不进 Git）。
  2. **合成边界基线**：覆盖 6/7/8/9 人桌 × 各位置 × 街次 × 边界筹码量（含正好 100bb、99bb、101bb）。
  3. **对抗基线**：断帧、乱序、重复帧、识别冲突、街次跳变。
- 每类 ≥ 200 手，或全部可用样本。

### 7.2 五条判据（必须全部满足）

| # | 判据 | 计算方法 | 通过阈值 |
|---|---|---|---|
| 1 | **确定性哈希** | 同一事件流 + 同一 `engine_version`，跑两次，输出 canonical JSON 的 sha256 | **必须完全相同**。不同 = 有隐藏非确定性，直接阻塞发布 |
| 2 | **状态一致率** | 增量重建状态 vs 全量重放状态，逐 `state_version` 规范化 JSON diff | **100%**。任何差异必须逐条归因 |
| 3 | **权益偏差** | `abs(equity_rt − equity_ref)`，ref = 大样本 exact 或固定 trials 的高精度 MC | P95 ≤ **0.005**（0.5pp），max ≤ **0.02**（= `target_half_width`） |
| 4 | **建议一致率 AAR** | `(action, size_bucket)` 与基准一致的比例 | ≥ **99%**；任何不一致必须归类到 §9 的陷阱之一 |
| 5 | **翻转率 Flip Rate** | 因数值偏差导致**最终建议动作改变**的比例 | **0**。任何一次 flip 都要人工复核并写归因；连续出现 → 回滚 |

**说明**：判据 3 允许小偏差（MC 本质随机），判据 5 不允许偏差**转化为不同决策**。做法是把决策边界做成**带滞回**：当 equity 落在动作切换边界 ±ε（建议 ε = `target_half_width` = 0.02）内时，不翻转动作，而是标记 `BOUNDARY_UNCERTAIN` 并给出两个候选 + 理由。这是"胜率不下降"的关键工程手段。

### 7.3 持续验证（影子模式）

- 每次会话结束后，影子进程全量重跑 WAL，产出比对报告。
- 报告内容：逐手 `(hand_id, state_version, metric, rt_value, ref_value, delta, verdict)`。
- 每日汇总：AAR / 权益偏差 P95 / PARTIAL 占比 / flip 数。
- **趋势比绝对值重要**：AAR 从 99.8% 掉到 99.2% 就是信号，即使仍在阈值内。

### 7.4 胜率相关的特殊注意

- 本系统是**训练陪练**，不是自动下注。因此"胜率"应理解为**建议质量**：与基准策略的 EV 差、以及边界不确定时的诚实标注率。
- **绝不用"实时结果更好看"来证明实时化成功**。如果实时路径的 EV 系统性高于离线基准，第一怀疑是**前视偏差（look-ahead bias）**——实时路径可能用了当时还不可得的信息（例如把未来帧的识别结果提前并入了当前状态）。必须做**时间旅行检查**：把每个决策点的输入截断到该时刻之前，重算，确认结果不变。

---

## 8. 最易导致实时/离线不一致的陷阱与校验手段

按风险从高到低。**前 4 条是本系统当前代码中已经存在或高概率出现的问题。**

| # | 陷阱 | 具体表现（本系统） | 校验手段 |
|---|---|---|---|
| **1** | **MC 实际采样数随负载浮动**<br>🔴 **已实测为高风险** | `adaptive_equity.py:252-268`：`monte_carlo_*` 同时受 `trials`（计划值）和 `deadline_at=wall_deadline`（墙钟）双重约束。机器忙时 `result.samples < trials` → equity 值不同、`status` 在 `COMPLETE`/`PARTIAL` 之间翻转、`evidence` 字符串里 `trials=` 也不同 → **同一局面两次跑出不同结果**。<br>**余量实测只有 36ms**：MC p95 = 272.8ms，deadline = 300ms。任何负载抖动都会吃掉这点余量 | ① 增加 `benchmark_mode`：忽略墙钟，固定 `trials` 跑完；② 实时模式记录 `planned vs actual samples`，`actual < planned` 必须计入指标并对 `PARTIAL` 占比设告警；③ 判据 1 的确定性哈希（benchmark 模式下必须过）；④ **河牌直接走 exact（P3-7），从根上消除这一整条街的抖动** |
| **2** | **缓存 key 不含实际精度** | `EquityCacheQuery` 的 key 含 `trials`（**计划值**），不含 `result.samples`（**实际值**）。两个精度不同的结果会共享同一个缓存 key → 命中返回的是"先算出来的那个"，精度不可控 | 缓存写入时把 `result.samples` 一并入 key，或拒绝缓存 `actual < planned` 的结果 |
| **3** | **exact / MC 边界抖动** | `adaptive_equity.py:193`：`estimated_outcomes <= exact_budget` 决定是否走 exact。输入微小变化（多一个 combo、多一张公共牌）会让方法**跳变**，两种方法的数值天然有差 → 输出阶跃 | ① 给边界加**滞回带**（如 `[0.9×budget, 1.0×budget]`，在带内沿用上一次的方法）；② 基线集必须专门覆盖边界附近 case；③ 记录 method 切换次数 |
| **4** | **时间源混用** | 代码里同时存在 `utc_now()`（墙钟，用于 `expires_at`）和 `time.monotonic()`（用于 deadline）。墙钟会回拨/NTP 跳变；断线重连后 `expires_at` 可能瞬间过期或永不过期 → 权益缓存 STALE 判定错乱 | ① 所有**持续时间**一律用 `monotonic`；② `expires_at` 只在跨越进程边界时序列化；③ 检测墙钟回跳（`now < last_now`）→ 记 WARN 并让该帧缓存全部判 STALE（保守） |
| 5 | **增量 vs 全量漂移** | `range_tracker` 逐步过滤，连乘会截断/下溢；累积 100 手后与全量重算的分布可能不同 | 每 N=50 手全量重算一次做对账，偏差 > 1e-9 则重置为全量结果并告警 |
| 6 | **缓存 TTL 语义不一致** | `StrategyCache` 有 `ttl_seconds=300`，`EquityCache` **没有 TTL**（只有 `expires_at` 和 `engine_version`）。同一逻辑在两处语义不同 → 一个过期一个不过期 | 统一：所有缓存条目必须同时具备 `engine_version` + `source_version` + `asset_version` + `created_at` + `ttl`。缺一不可 |
| 7 | **版本漂移未进 key** | 策略资产有 `asset_version`、Provider 有 `source_version`，但缓存 key 只含 `engine_version`。换资产不换引擎 → 命中旧结果的缓存 | 把 `asset_version` / `source_version` 一并入 key；升级资产时版本号必须变（现 `derived_ranges` 已随资产走，需确认入 key） |
| 8 | **迟到确认 / 乱序帧** | `TemporalConsensus` 需要 N 帧确认；确认完成时街可能已推进，动作被记到错误的街 | 事件必须携带 `source_frame_seq`；写 WAL 时校验单调性；出现回退 → 标 `SUSPECT` 并进对抗基线 |
| 9 | **VFR 时间戳不可信** | 采集卡实测：容器标称 30fps，实际 ~10fps；cv2 索引 ≠ ffmpeg 索引。用时间戳推算"距上一帧多久"会系统性错误 | 帧间隔一律用**采集侧的 monotonic 到达时间**，不用容器时间戳。需要真实时间时用画面手机时钟（已有先例：真值看画面手机时钟） |
| 10 | **隐藏非确定性** | dict/set 迭代序、`hash()` 随机种子（Python `PYTHONHASHSEED`）、未播种随机、并行乱序、`Decimal` 上下文精度在线程间被改 | ① 固定 `PYTHONHASHSEED=0`；② 所有输出序列化前排序（现 `strategy_serialize` 需确认）；③ 判据 1 的确定性哈希在**多进程多次**都跑过 |
| 11 | **Decimal / float 混用** | 项目用 `Decimal` 表示筹码和概率，但 `confidence` 历史上踩过一次坑（传 `Decimal` 破坏了 6-max 判定）。混用会在比较/排序处产生微妙差异 | lint 规则：概率类一律 `Decimal`，耗时/计数一律 `int/float`，跨类型转换只允许在显式边界函数内 |
| 12 | **前视偏差** | 实时路径可能把"已经看到的下一帧"并入当前状态（例如 UI 为了流畅预取） | §7.4 的时间旅行检查：截断输入重算，结果必须不变 |

> **修复状态（2026-09-06，PLAN-MASTER Phase 1）**：
> - **#2 已修复**：`calculate_adaptive_equity` 只缓存完整跑完的结果（exact 或 `result.samples >= planned trials`），被墙钟截断的 MC 一律不入缓存 → 脏命中消除。钉死：`test_mc_run_cut_short_by_wall_deadline_is_not_cached`。
> - **#3 已修复**：双管齐下 —— ① exact/MC 选择加滞回带（`AdaptiveEquityPolicy.exact_method_hysteresis = 0.10`，常数带 0.5 安全系数，带内仍可在 ~55% deadline 内跑完）；② MC 路径先探测 exact 缓存键（exact 结果确定性与 deadline 无关），同决策点 deadline 收缩时复用 exact，不再退化成 MC PARTIAL。钉死：`test_exact_hysteresis_band_extends_exact_just_past_budget` / `test_beyond_hysteresis_band_still_uses_monte_carlo` / `test_exact_result_is_reused_when_shrinking_deadline_would_force_mc`。
> - **#6 已修复**：`EquityCache` 新增 `default_ttl_seconds=300.0`（与 `StrategyCache` 对齐，可传 `None` 关闭）；`expires_at=None` 的条目自动获得 `created_at + TTL`。钉死：`test_entry_without_explicit_expiry_expires_after_default_ttl` 等 3 个新用例。
> - **#1 部分缓解**：脏命中后果已被 #2 修复切断；`benchmark_mode` 与 planned/actual 指标计量仍未做（P3-1/P3-2/P3-8 待办）。
> - **#7 已确认**：`EquityCacheQuery.key` 的 `villain_ranges` 载荷本就含 `source` + `source_version`（`equity_cache.py` key payload），换资产不换引擎必然 MISS。

---

## 9. 关键实现要点清单（做什么 + 验证标准）

> 每条都可独立验收。**P0 未完成前，不要动其他层。**

### P0 — 观测与基线（没有数据就不要改造）

| # | 做什么 | 验证标准 |
|---|---|---|
| P0-1 | **复用**现有 `tools/benchmark_realtime_latency.py`（已能测 capture/vision/state/equity/total 的 p50/p95，判据 p50<500 且 p95<500）。**只补缺口**：① 增加真实采集后端（现在 capture 是 no-op）；② 增加策略 Provider 阶段；③ 输出 `trace_id` 与逐帧明细 | 现有判据仍 PASS；新增阶段的数据可导出；`tests/test_benchmark_metric.py` 仍绿 |
| P0-2 | 在 `PipelineStep` / `DesktopFrame` 上加 `trace_id`、`ingested_at`、`stage_timings`、`frame_seq`；延迟分位数用**固定桶**滑动直方图（有界内存，不随手数增长） | 跑 30 分钟**真实采集**（非合成帧）能导出每阶段 P50/P95/P99；指标内存 < 1 MB 且稳定 |
| P0-3 | 建黄金集：真实采集 + 合成边界 + 对抗（断帧/乱序/重复/冲突/跳街），各 ≥ 200 手，用 `capture_replay` 框架封装，带 sha256 | `load_capture_replay` 全部通过；基线集可被一条命令重跑 |
| P0-4 | 跑一次**当前系统的**基线：AAR / 权益偏差 / PARTIAL 占比，作为"离线基准" | 产出 `baseline-report.json`，作为后续所有对比的参照物 |

### P1 — 事件驱动帧泵（延迟可控）

| # | 做什么 | 验证标准 |
|---|---|---|
| P1-1 | 把 `live_analysis_stream` 的 `sleep(1.0)` 改为事件驱动：采集就绪即 `step()`，无帧则等待信号 | 端到端 P95 从 ≥1000ms 降到 ≤900ms；CPU 占用不高于改造前 |
| P1-2 | 帧队列**有界**（默认 8 帧）+ 背压：队列满则丢最旧帧并计 `gap` | 人为注入 10× 慢消费者，队列不无限增长；`gap` 计数正确 |
| P1-3 | 心跳 + 断流检测：> 3× 预期帧间隔无帧 → 触发 gap 流程 | 拔线 5s → gap 被正确记录，UI 显示 STALE；插回后自动恢复 |
| P1-4 | 采集与计算分离（至少两个进程/线程 + 队列） | 人为让权益计算卡 2s，帧泵**不**被阻塞，`gap` 计数增长 |

### P2 — 事件日志与快照（可复现 / 可回测）

| # | 做什么 | 验证标准 |
|---|---|---|
| P2-1 | WAL：`{data_root}/sessions/{sid}/wal.jsonl`，append-only，字段见 §4.1 | 写入失败 → 会话立即停止（fail-closed）；`fsync` 策略可配（默认每条 fsync，性能不足时改每 10 条） |
| P2-2 | 快照：每 200 事件或每次街推进，`{state_canonical_json, wal_offset, sha256}` | 恢复时间：1 万事件的会话 < 2s |
| P2-3 | 恢复：闪退（kill -9）后重启，从快照 + WAL 恢复 | **判据 2：恢复后状态 vs 崩溃前状态，逐 `state_version` 100% 一致** |
| P2-4 | 幂等重放：同一 WAL 重放两次，状态与输出完全相同 | **判据 1：canonical JSON 的 sha256 相同** |

### P3 — 增量与双轨（一致性）

| # | 做什么 | 验证标准 |
|---|---|---|
| P3-1 | 权益改**续跑式 MC**：同 seed 追加 trials 不清零，避免重跑抖动 | 同一局面分两次各跑 2000 trials = 一次跑 4000 trials（误差 ≤ 1e-9） |
| P3-2 | 增加 `benchmark_mode`：忽略墙钟 deadline，固定 trials 跑完 | 该模式下判据 1（确定性哈希）在 20 次独立运行中 100% 通过 |
| P3-3 ✅ 关键部分 2026-09-06 | 缓存语义补全：`EquityCache` 补 TTL（对齐 300s）；截断 MC 拒绝入缓存（等价于实际精度入 key 的效果）；`source_version` 确认已在 key 内。`asset_version` 独立字段入 key 待 P3 后续 | 构造"换资产不换引擎"的用例，缓存必须 MISS |
| P3-4 ✅ 已完成 2026-09-06 | exact/MC 选择加**滞回带**（0.10）+ MC 路径 exact 键优先探测 | 边界附近连续 100 帧，method 切换次数 = 0 |
| P3-5 | 影子进程：消费 WAL 副本，全量重算，输出逐手比对报告 | 每日报告自动生成；AAR ≥ 99%、flip = 0 |
| P3-6 | 决策边界**滞回**：equity 落在切换边界 ±0.02 内不翻转，而是标 `BOUNDARY_UNCERTAIN` 给双候选 | 对抗基线中 flip 数 = 0 |
| **P3-7** ✅ 已完成 2026-09-06 | ~~重新标定 `exact_outcomes_per_ms`~~ 已在本机（Intel Core Ultra 5 245KF）实测：exact 9.38 outcomes/ms、MC 5.662 trials/ms（min），按 0.5 安全系数 → **`exact_outcomes_per_ms` 3→4**、`mc_trials_per_ms` 维持 2，`engine_version` → `adaptive-equity-v3-core-ultra-5-245kf`。标定文件 `configs/strategy/adaptive-equity-core-ultra-5-245kf-v1.json`（工具哈希钉死，M1 Pro 旧文件留档） | ① 实测数据附测量命令 ✅；② exact 预算 900→1200 outcomes（加滞回带 1320），多人河牌落 `PARTIAL` 的范围收窄 ✅；③ 全量回归 2278 passed / 1 skipped ✅ |
| P3-8 | 翻前/翻牌/转牌的 MC：`trials` 按街固定（如 flop 2000 / turn 8000），**不随 deadline 浮动**；deadline 只作为"跑不完就标 PARTIAL"的兜底，不改变计划值 | 同一局面在 3 种不同 CPU 负载下跑，`planned trials` 完全相同；只有 `actual samples` 可能不同，且被单独计量 |

### P4 — 断线重连与补齐

| # | 做什么 | 验证标准 |
|---|---|---|
| P4-1 | 分级处理（§5.1 的 L0–L4）+ 指数退避重连 | 断线 1s/10s/60s 三档测试，每档行为符合表；连续 5 次失败后停止并告警 |
| P4-2 | 恢复后强制重确认：底牌 / 庄位 / 街次 / 底池 | 未全部确认前不产建议，UI 显示 `UNKNOWN`（不是 STALE） |
| P4-3 | `GAP` 标记贯穿：hand flag → UI → 影子排除集 | 含 GAP 的手不进入 AAR 统计；UI 有可见标识 |
| P4-4 | 补齐只补状态、不补信号 | 断流期间错过的决策点**不**生成回溯建议 |

### P5 — 降级与告警

| # | 做什么 | 验证标准 |
|---|---|---|
| P5-1 | 实现 L0–L4 降级链（§6.3） | 逐级别注入故障，行为符合表；**不回退**现有"置信度逐帧刷新"的行为 |
| P5-2 | 告警规则（§6.4）落地，含影子不一致超阈值 → 停止产建议 | 每条告警有对应测试用例；误报率 < 1 次/小时 |
| P5-3 | 健康端点：暴露延迟分位数 / gap 率 / ABSTAIN 率 / 影子不一致率 | 可被本地脚本轮询；UI 有健康指示灯 |

### P6 — 明确**不做**的事（红线）

1. **不做**任何自动点击 / 自动下注 / 客户端控制。人永远是唯一操作者。
2. **不把慢求解器塞进同步决策路径**（GTOpen 实测 7-max 92–164s、8-max 499s；flop 量级 98s）。只允许影子/离线。
3. **不用单挑结果近似 3+ 人底池**（多人翻后仍是行业空白）。
4. **不静默填补 GAP**，不用旧值冒充新值。
5. **不为了"实时结果更好看"而放松前视检查。**
6. 未标定的字段永远 `UNKNOWN`（`_uncalibrated()` floor=1.0），实时化**不豁免**这条。

---

## 10. 分期路线

| 阶段 | 内容 | 出口条件（做完才能进下一阶段） |
|---|---|---|
| **S0** | P0 全部 | 30 分钟**真实采集**的延迟分位数报告（含真实采集与策略阶段）+ 黄金集 + `baseline-report.json` |
| **S1** | P1 全部 | **端到端 P95 从实测的约 1.28s 降到 ≤ 900ms**；背压与断流检测有测试；管线预算（p50<500 / p95<500）仍 PASS |

### 10.1 已完成的阶段与实测结果（2026-09-06）

**S0（埋点）已完成** —— `RealtimePipeline.step()` 现在输出逐阶段耗时：

- 新增 `PipelineStep.timings`（capture / vision / consensus / boundary / change / advance / equity / total，毫秒）+ `timing(stage)` 访问器。
- `equity` **只在实际跑了的时候才记录**（change-gated，未变化的帧不重复算权益）。
- `monotonic_clock` 可注入 → 测试可确定性断言耗时。
- 契约：埋点是**纯观测**，不改变任何决策（有 `test_injected_clock_does_not_change_the_analysis` 钉死）。

**S1（事件驱动帧泵）已完成** —— `live_analysis_stream` 的 `interval_seconds` 从"固定 sleep"改为"最小周期"：

```python
remaining = interval_seconds - (time.monotonic() - started)   # 默认值 1.0 → 0.0
if remaining > 0:
    await asyncio.sleep(remaining)
```

新增 `tools/benchmark_stream_pacing.py` 实测（模拟真实采集开销，含 legacy 固定 sleep 对照）：

| 模拟采集开销 | 改造后帧率 | 帧间隔 p95 | 旧模型帧率 | 提升 |
|---|---|---|---|---|
| 33 ms（30fps 源） | **3.28 fps** | 307 ms | 0.786 fps | **4.17x** |
| 100 ms（~10fps 真实 VFR） | **2.68 fps** | 376 ms | 0.785 fps | **3.42x** |

**帧间隔从 1277ms 降到 307–376ms**，且能跟随真实采集速率自适应（不再是死板的 1 秒一刀切）。

**同时补上的可靠性**：设备级故障（`LiveCaptureError`，如 ADB 掉线 / USB 重枚举）现在按指数退避重试（默认 0.5s→8s，上限 5 次）并通过 `on_health` 回调上报；编程/配置类故障**不重试**立即抛出（重试只会掩盖 bug）。帧源耗尽时干净停止并通过 `exhausted` 标记上报。

**验证**：全量回归 **2266 passed / 0 failed / 1 skipped**，flake8 干净。新增 19 个测试：
`tests/realtime/test_pipeline_timings.py`（8）、`tests/desktop/test_live_stream.py`（11）。
其中 `test_zero_interval_adds_no_artificial_sleep` 用"记录 sleep 请求值"而非墙钟计时做确定
性断言——直接钉死"不再有无条件 sleep"这个语义。
| **S2** | P2 全部 | kill -9 恢复一致性 100%；重放幂等哈希一致 |
| **S3** | P3 全部 | 影子报告 AAR ≥ 99%、flip = 0、确定性哈希 20/20 通过 |
| **S4** | P4 全部 | 三档断线测试通过；GAP 贯穿 UI 与统计 |
| **S5** | P5 全部 | 降级链逐级别测试通过；告警误报率达标 |

**每完成一个阶段，跑一次全量测试套件**（当前基线：2248 passed / 0 failed / 1 skipped / ~35s；注意 `tests/strategy/test_local_resolver.py` 有已知的负载相关 flaky，先单独重跑确认再判断）。

---

## 11. 待拍板事项

1. **进程模型**：先做"两进程（采集 / 计算）"还是直接上"三进程（采集 / 计算 / UI）"？建议先两进程，UI 暂留主线程，等 S3 之后再拆。
2. **WAL 落盘位置**：默认 `{data_root}/sessions/`。`data_root` 需要你指定一个本地目录（**注意：中文路径有已知坑**——`cv2.imread` 和 binutils 都不认非 ASCII 路径，建议选一个纯 ASCII 路径）。
3. **影子比对频率**：每次会话结束后全量跑，还是每小时增量跑？建议前者（实现简单，且不影响实盘）。
4. **权益 `benchmark_mode` 的 trials 取值**：实测吞吐约 **7.6 trials/ms**（2000 trials = 264ms）。据此：
   - `benchmark_mode` 建议 **10000 trials ≈ 1.3 s/次**。若黄金集 600 手 × 3 个决策点 ≈ 1800 次 → 约 40 分钟，适合夜间影子跑。
   - 20000 trials ≈ 2.6 s/次 → 约 78 分钟，精度收益递减，除非有证据表明 10000 不够（判据 3 的偏差 P95 超 0.005 时再往上加）。
   - **先跑一次 10000 vs 20000 的差值分布**，如果两者 P95 差 < 0.001，就用 10000。
