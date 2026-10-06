# PokerSense 架构设计文档 v0.3

> 单桌德州扑克实时训练助手：可信感知 → 权威状态 → 范围与策略 → 可解释建议 → 训练闭环
> 目标环境：自建牌局、朋友对练、教学演示
> 最高原则：**状态正确性 > 建议可靠性 > 可观测性 > 实时性 > 功能数量**

## 0. 文档地位

本文是 PokerSense 当前唯一的目标架构。v0.2.1 中已经落地的不可变数据契约、
`ConfidenceGate`、纯 `StateEngine`、`HandMemory`、`RequestContext` 和 Fast/Slow
思想继续保留；未实现的目录草图、固定 Python 3.11、LLM 参与决策等旧规划不再作为目标。

产品范围、Multi-Scenario / Multi-Player 能力矩阵、输入输出要求和分阶段验收标准见
[`docs/product-requirements.md`](docs/product-requirements.md)。Heads-Up 是第一阶段交付范围，
不是公共领域模型和 Strategy Router 的最终边界。

识别完成后的功能拆分、Strategy Router 输入输出矩阵和验收规则见
[`docs/strategy-requirements-matrix.md`](docs/strategy-requirements-matrix.md)；自动化回归套件、测试数据和发布门槛见
[`docs/strategy-regression-test-matrix.md`](docs/strategy-regression-test-matrix.md)。

修订记录：

| 版本 | 变更 |
|---|---|
| v0.3 | 面向授权对练的实时建议；加入 Temporal Consensus、State/Event Engine v2、Range Tracker、Decision Context、Strategy Router、Decision Fusion、Advice、训练闭环和五阶段最优路线 |
| v0.2.1 | 深层不可变、Decimal 金额、置信度门控、事件记忆、异步结果版本保护 |

## 1. 我们要优化的到底是什么

PokerSense 的目标不是“接入最强 solver”，而是在有限行动时间和不完整信息下，最大化建议质量：

```text
maximize   Expected decision quality
subject to canonical state is trustworthy
           p95 first-advice latency ≤ 300ms
           every result is versioned and auditable
           uncertain inputs can produce ABSTAIN
           the human remains the only executor
```

“最优”分为四层：

1. **状态最优**：牌、底池、筹码、行动方和行动线正确；错误时拒答。
2. **数值最优**：基于具体组合范围比较各合法动作 EV，不用单一 equity 阈值代替策略。
3. **策略最优**：以 GTO/blueprint 为基准，根据可信对手证据做受约束的剥削调整。
4. **系统最优**：Fast Path 先给可靠结果，Slow Path 异步提高精度，旧结果永不污染新状态。

目标层的 `StrategyOrchestrator` 已实现这一条合同：Fast Advice 同步返回；只有 capability
匹配且 Fast 结果不是 exact 时才提交 Slow Future；collect 时重新验证
`hand_id + state_version + request_id + deadline + provider version`，并且只接受质量等级更高的结果。

## 2. 当前事实与目标差距

| 能力 | 当前 `main` | v0.3 目标 |
|---|---|---|
| Capture | ADB 直读雷电 Android framebuffer；多实例必须显式 serial | 设备重连、真实 ADB capture 延迟与掉线恢复测量 |
| Hero cards | Android 1440×2560：58/58 可见帧正确，8/8 非手牌帧 abstain；23 个不同手牌 | 扩充独立设备、主题、分辨率与真实失败样本 |
| Board / street | Android 1440×2560 已独立标定；27/27 个人工复核稳定状态正确，动画/非法占位 fail closed | 扩充独立设备与授权 raw-frame Replay |
| Pot | Android 总底池 ROI/OCR 已标定；22/22 个不同数值正确，25 个文字/遮罩/过渡负样本拒识 | 扩充桌型、边池标签与授权 Replay |
| Seats / stacks / dealer | Android 8 槽 occupancy、筹码和 Dealer 已独立实测；版本化 mapping 把 visual slot 映射为 canonical seat 并按 Dealer 推导 2–8 人位置 | 补授权 raw Replay、独立设备和离桌/重入边界样本 |
| Actor / actions / amounts | Hero 当前行动回合和逐槽 fold/check/call/bet/raise/all-in 已标定；完成动作按 glyph slot 确定 actor、持久字形去重，并只在 stack delta + pot 守恒时生成金额事件 | 对手当前计时圈、漏帧多动作、all-in/side-pot 用授权 Replay 验收 |
| State | 权威更新 hero/board/street/pot/occupancy/stacks/dealer/positions，并把可证明的完成动作写入 canonical history；hand-boundary、legal-action、side-pot、slot→seat mapping 和 hash-pinned Replay 合同均已接入 | 用授权真实原始帧执行 release-eligible Replay；策略源不匹配时 live 保持 ABSTAIN |
| Equity | 枚举、Monte Carlo、range equity、pot odds；目标层已有加权多人 pot-share、seeded MC/CI、canonical TTL/LRU cache 和 operation-budget 路由 | 大范围直接采样、真实 deadline 吞吐校准和持久化 cache |
| Strategy | 多人 DecisionContext、Provider capability、Router、Advice、状态派生和 FakeProvider 回归闭环；未发布目标层新增可选 HU preflop Blueprint Adapter，以及固定来源/hash、仅覆盖明确 6/9 人 unopened 牌表的低置信度 Heuristic RFI Provider | 扩大 HU Golden 节点覆盖；接入人数精确匹配的 3–9 人 preflop DB、预解缓存、轻量策略、异步 resolver；不得把 6/9 heuristic 宣称为多人 GTO |
| Opponent | `OpponentProfile` 契约；目标层已有受限 6/9 人 RFI 资产→concrete-combo 初始范围、blocker、贝叶斯更新、小样本收缩和多人联合组合枚举；不适用时返回 UNKNOWN 而非 random range | 扩展到逐一验证的 3–9 人位置/行动/stack 先验资产、实时事件接入和受约束模型 |
| Output | 生产 live 已接入 canonical action history → `LiveStrategySession → StrategyOrchestrator → DesktopFrame`，支持 Advice/UI/WebSocket 的频率、尺度、EV、来源、证据和过期防闪回；缺合格 Provider 时只输出 ABSTAIN | 接入匹配且可发布的多人策略资产，使声明场景可 READY |
| Learning | 无 | 实际动作 → EV loss → 漏点 → 训练题 |

### 2.1 并行开发的集成边界

识别和 UI 可以与策略侧并行开发，但必须在冻结合同处汇合：识别侧止于带逐字段质量和
证据的 `RawObservation`，策略侧负责从 observation 形成 canonical state、事件、Context 和
Advice，UI 侧只渲染原子的 `DesktopFrame`，不推断牌局事实或策略。

```text
伙伴：Capture / Vision
  → RawObservation + PlatformSeatMapping evidence
本分支：Temporal / State / Context / Strategy
  → DesktopFrame { analysis, advice }
伙伴：Live Coach UI
  → 只渲染，不自行生成动作
```

当前接口和责任 Gap 的权威表见
[`docs/product-requirements.md` 2.3](docs/product-requirements.md#23-策略识别与-ui-的协作边界)。
伙伴可直接执行的任务和验收清单见
[`docs/recognition-ui-handoff.md`](docs/recognition-ui-handoff.md)。
真实联调前必须冻结 `platform_id + layout_id + mapping version`、Replay hash、Provider/version
和 UI build；否则不同团队各自通过测试仍不能证明同一条产品链路成立。

## 3. 目标架构图

下图是目标模块关系；SVG 内嵌 draw.io XML，可直接用 draw.io 打开继续编辑。

![PokerSense v0.3 target architecture](docs/realtime-training-assistant.drawio.svg)

架构图源文件：[docs/realtime-training-assistant.drawio.svg](docs/realtime-training-assistant.drawio.svg)

## 4. 端到端数据流

### 4.1 可信感知

```text
Capture Adapter
  → Vision Engine
  → Temporal Consensus
  → Confidence Gate
  → StableObservation
```

- `Capture Adapter` 绑定窗口身份、帧序号、时间戳和坐标。
- `Vision Engine` 只输出候选值、raw score 和证据，不直接修改状态。
- `Temporal Consensus` 通过连续帧确认、动画抑制和冲突检测形成稳定观察。
- `Confidence Gate` 将达不到独立测量阈值的字段降级为 `UNKNOWN`。

### 4.2 权威状态

```text
Previous PokerState + StableObservation + StateContext
  → State/Event Engine v2
  → New PokerState + StateEvent[] + ValidationResult
```

State/Event Engine v2 负责：

- 新手牌和街道边界；Hero 换牌或多信号 reset 可确认切手，冲突/弱证据保持不切手，dealer/stack 信号只接受显式 slot→seat 映射。
- actor、stack、street committed、hand committed、pot、current bet、to-call。
- fold/check/call/bet/raise/all-in 的事件语义。
- 最小加注、合法动作和筹码守恒。
- 重复帧、漏帧、回退值、冲突观察的确定性处理。

它保持纯函数，不访问 Vision、数据库、solver、LLM 或 UI。

### 4.3 决策上下文

`DecisionContext` 只能从 canonical state、事件流和已版本化画像构造：

```python
@dataclass(frozen=True)
class DecisionContext:
    hand_id: str
    state_version: int
    hero_seat: int
    actor_seat: int
    legal_actions: tuple[ActionType, ...]
    pot: ChipAmount
    to_call: ChipAmount
    effective_stack: ChipAmount
    spr: float
    action_history: tuple[StateEvent, ...]
    hero_range: RangeDistribution
    villain_ranges: tuple[RangeDistribution, ...]
    quality: ContextQuality
```

未经门控的 OCR 值不得绕过 State Engine 进入 `DecisionContext`。

### 4.4 Fast Path

```text
DecisionContext
  ├→ Preflop DB / Canonical Cache / Presolved Strategy
  ├→ Range Equity + Pot Odds
  └→ Decision Fusion
       → Advice
       → WebSocket / Live Coach UI
```

Fast Path 无网络依赖，不调用 LLM，不等待重型 solver。目标 p95：

| 阶段 | 预算 |
|---|---:|
| 真实窗口 capture | 25ms |
| Vision + temporal consensus | 25ms |
| State + derived metrics | 10ms |
| Range update + strategy lookup | 25ms |
| Equity | 190ms |
| Fusion + transport + render | 25ms |
| **总计** | **≤300ms** |

当前合成基准的总链路 p95 约 191ms，其中 equity p95 约 183ms；capture 是 no-op，
所以必须用真实窗口重新测端到端预算。

### 4.5 Slow Path

cache miss、节点匹配低、非标准下注尺度或 EV gap 很小时，Strategy Router 可异步请求
本地 resolver：

```text
RequestContext(hand_id, state_version, request_id)
  → Local Resolver
  → StrategyCandidate
  → stale check
      ├→ same version: update Advice
      └→ changed version: discard
```

Solver 使用独立进程和硬预算，不能阻塞 Fast Advice。第一版从 river subgame 开始，
flop/turn 未按时收敛时只用于局后分析。

多人翻牌前的本地研究路径可选用 `GTOpenPreflopProvider`。它不复制上游 Rust 代码，而是访问
`127.0.0.1` 上单独运行的 GTOpen JSON API；把 2–9 人位置、等起始筹码、blind/ante/rake 和
权威行动事件构造成 Preflop Lab tree，等待 model gap 达标后，按 Hero 具体 169-class 索引读取
逐尺度策略。由于上游每个服务只有一个可变 preflop session，Provider 必须串行；超时、行动
路径不精确、返回非法动作或不等起始筹码时拒答。多人 terminal value 使用近似模型，因此输出
固定为 `HEURISTIC`，不能作为发布版完整多人 GTO 声明。

## 5. 范围、Equity 与决策算法

### 5.1 组合范围更新

初始范围来自位置、stack 和 preflop action。观察到动作 `a` 后，对具体组合 `h` 更新：

```text
P(h | a, s) ∝ P(a | h, s, profile) × P(h | s)
```

每次更新必须：

1. 移除与 hero/board 冲突的 blockers。
2. 使用策略源给出的 combo-action frequency 更新权重。
3. 对小样本 opponent profile 做 Beta/Dirichlet 或层级收缩。
4. 重新归一化，并保存 posterior entropy、有效样本量和版本。

### 5.2 Equity 与 pot odds

对后验范围 `R`：

```text
Equity(hero, R, board)
  = Σ_h P(h | history) × E_runout[pot_share(hero, h, runout)]
```

跟注成本为 `C`、当前底池为 `P` 时：

```text
break_even_equity = C / (P + C)
EV(call) = q × (P + C) - C
```

Pot odds 是证据，不是完整策略；flop/turn 仍需考虑未来行动和 equity realization。

### 5.3 Bet/Raise EV

对候选尺度 `B`，设对手 fold/call/raise 概率为 `f/c/r`：

```text
EV(bet B)
  = f × P
  + c × [q_called × (P + 2B) - B]
  + r × EV(vs raise branch)
```

Fast Path 只使用少量经验证的标准尺度和预计算 continuation value；Slow Path 才展开复杂 raise 分支。

### 5.4 GTO 与剥削融合

设基准策略为 `π₀(a|s)`，对手 posterior 下动作价值为 `Q(a)`。使用 KL 正则化限制
剥削偏移：

```text
π*(a|s) = argmax_π Σ_a π(a)Q(a) - λ KL(π || π₀)

π*(a|s) ∝ π₀(a|s) × exp(Q(a) / λ)
```

- 样本少、画像不稳定：增大 `λ`，接近 GTO。
- 样本充分、倾向稳定：减小 `λ`，增加针对性。
- 必须设置最大 exploit weight，限制画像误判时的最坏损失。

### 5.5 Decision Fusion 与拒答

Decision Fusion 只消费结构化结果，不让 LLM 参与动作或 EV 计算。硬门任一失败就输出
`ABSTAIN`：

- hero/board/street 不完整或冲突。
- actor、pot、to-call、effective stack 无法构造合法动作。
- 行动线不能解释当前状态或筹码不守恒。
- 没有适用策略节点且 resolver 超时。
- 结果的 `state_version` 已过期。

软置信度采用保守聚合：

```text
confidence = min(
  perception_lower_bound,
  temporal_consistency,
  state_consistency,
  strategy_match_score,
  range_confidence,
  numerical_confidence,
)
```

## 6. Advice：系统唯一输出

```python
@dataclass(frozen=True)
class Advice:
    hand_id: str
    state_version: int
    request_id: str
    action_probabilities: Mapping[ActionType, Decimal]
    action_options: tuple[ActionOption, ...]  # 每个动作/尺度的独立频率
    recommended_sizes: tuple[BetSize, ...]
    action_ev: Mapping[ActionType, ChipDelta]
    ev_gap: ChipDelta
    confidence: float
    status: AdviceStatus  # READY / PARTIAL / ABSTAIN / STALE
    evidence: tuple[EvidenceRef, ...]
    key_factors: tuple[str, ...]
    expires_at: datetime
```

UI 默认显示动作频率，而不是把混合策略压成单个按钮。授权对练模式可以提供可重放 RNG，
seed 由 `session_id + hand_id + state_version` 派生。人类玩家是唯一执行者。

解释层只把 `Advice` 翻译成人话；可先使用确定性模板，未来的 LLM adapter 不能修改数值或动作。

## 7. 策略源层级

| 层级 | 来源 | 典型延迟 | 适用场景 |
|---|---|---:|---|
| L0 | legality / safety | <1ms | 合法动作、状态拒答 |
| L1 | Preflop DB | <5ms | 标准 HU preflop 节点 |
| L2 | Canonical presolved cache | 5–20ms | 标准 postflop 节点 |
| L3 | Lightweight policy/value model | 10–80ms | cache miss 的近似策略 |
| L4 | Local resolver / CFR backend | 0.5–5s+ | 小 EV gap、异常尺度、局后精算 |

Adaptive Equity 的默认预算不是理论常量。当前 `adaptive-equity-v2-m1-pro` 使用目标机
MacBookPro18,3 的版本化实测：exact 3 outcomes/ms、MC 2 trials/ms，约为最慢 p95 吞吐的
50%。更换硬件、Python 或 evaluator 实现时必须重新运行 benchmark、生成新 calibration 版本，
并更换 engine version，防止旧 cache 与新性能假设混用。

Fast Path 使用 `TieredStrategyRouter` 固定查询 L0/L1 对应的 Cache、Preflop DB、Presolved 和
Model 层。每层内部仍由 capability-safe `StrategyRouter` 选出最佳 candidate；一旦某层命中，
更低层不得执行。Cache 是 lookup-only source，DB/Presolved/Model 可使用 write-through wrapper
回填；全部层 miss/rejected/not-applicable 时保留完整 lookup 轨迹并返回 NO_STRATEGY，不构造
伪 candidate。具体多人或 postflop 资产是否可用仍由各 Provider capability 和 Golden 证据决定。

多人 preflop 与 presolved postflop 使用同一个只读 `JsonStrategyAssetProvider` 接入合同。资产在
Provider 注册前必须通过文件 SHA-256、schema、Provider/version/source/license 元数据、
capability ID 和完整 capability digest 校验；运行时仅以 canonical context digest 查节点。
缺节点返回 NOT_FOUND，节点结构或概率错误返回 REJECTED，未披露差异维度的 interpolated 节点
无效。Synthetic asset 只验证 Adapter，不能作为真实多人 GTO 或发布 Golden 证据。

缓存键至少包含游戏类型、人数、位置、有效筹码、盲注/ante/rake、行动序列、board canonical
form、允许尺度和策略版本。位置和行动线必须精确匹配；stack、pot 与最近一次主动下注尺度只有在
Provider 明确声明 bucket 和最大距离时才允许插值。节点近似匹配必须同时输出保守的
`state_match_score` 和结构化 `match_dimensions[]`，并在缓存、融合、Advice 与 UI 中保持，不能
假装精确命中。

Decision Fusion 在输出前统一生成 freshness、confidence、context、strategy source 和 legal
actions 五个内置硬门，并接受 range、equity/numerical 或后续模块提供的具名外部门。门结果使用
PASS/FAIL/SKIPPED 合同写入 Advice；任一 FAIL 都会清空动作并转为 ABSTAIN，过期请求则优先
转为 STALE。外部模块不能覆盖内置门名，也不能只返回失败而不提供稳定 reason code。

## 8. 训练闭环

```text
Advice → 玩家实际动作 → Hand Memory
  → Hand Debrief
  → EV loss / 错误分类 / 同类训练题
  → Learner Profile + Opponent Profile
  → 更新下一手范围先验和训练计划
```

Live Coach 与 Hand Debrief 必须消费同一状态、事件和策略接口，确保同一节点的实时建议与局后
评估不矛盾。

## 9. 最优实施路线

### M1 — 完整、可信的 heads-up 状态

- 采集真实 flop/turn/river、pot、stack、action、actor 标注帧。
- 完成各字段独立 calibration 和 Temporal Consensus。
- 实现 State/Event Engine v2、hand boundary、下注合法性和筹码守恒。
- UI 先展示 SPR、pot odds、有效筹码和行动历史。

退出标准：不依赖人工 seed 重建完整对练手牌；关键字段错误时可靠拒答。

### M2 — 可解释的基础建议

- 落地 `DecisionContext`、`RangeDistribution` 和 `Advice`。
- 加入 HU preflop DB、Bayesian Range Tracker、range equity 和 action EV。
- 输出动作频率、尺度、EV gap、来源与置信度。

退出标准：200–500 个 golden spots 通过人工/基准解校验；真实 p95 首次建议 ≤300ms。

### M3 — 预解库与训练闭环

- 离线生成标准 HU solution bundle 和 canonical index。
- 记录玩家动作，计算 EV loss，分类漏点并生成训练题。
- 对同一节点验证 Live Advice 与 Debrief 一致。

### M4 — 鲁棒对手建模

- 位置、街道、pot type 分桶的后验画像。
- KL-regularized exploit fusion。
- 在 nit、calling station、maniac 模拟对手上评估平均收益和最坏损失。

### M5 — 异步局部精算

- 先接 river resolver，再逐步扩展 turn/flop。
- 独立进程、计算预算、stale filter 和数值误差报告。
- 未及时收敛的结果进入局后分析，不阻塞实时建议。

## 10. 测试与发布门槛

### 感知

- accuracy、coverage、unknown rate、negative false-positive rate。
- 真实平台独立样本；按主题、DPI、窗口尺寸和动画阶段分层。
- 使用 Wilson lower bound，不把小样本全对直接宣称为 100% 可靠。

### 状态

- 完整 hand replay 与 ground-truth event sequence 一致。
- 重复帧、漏帧、street regression、all-in、split pot、hand boundary 属性测试。
- 所有金额使用 Decimal 值对象并验证筹码守恒。

### 数值与策略

- Monte Carlo 与可枚举 exact spot 交叉验证。
- range 单一 holding 时退化为 known-hand exact equity。
- action probabilities 归一化，非法动作概率为零。
- 固定 solver 版本的 golden spots：频率距离、EV capture、数值误差。
- profile 误判压力测试和 worst-case EV。

### 系统

- 真实 capture 的 p50/p95/p99。
- stale result drop rate、cache hit rate、Advice abstain rate。
- 每个 Advice 可追踪到 observation evidence、state、range 和 strategy source version。

发布前必须通过 `pytest`、flake8、draw.io XML/渲染检查和真实牌局回放验收。

## 11. 模块边界

建议按里程碑逐步创建，而不是一次生成空目录：

```text
src/poker_engine/
├── state_engine/       # v2 reconciliation + betting rules
├── metrics/            # DecisionContext / SPR / effective stack
├── ranges/             # combo distribution / blockers / Bayesian update
├── strategy/           # router / preflop DB / solution store / solver adapter
├── decision/           # action EV / robust fusion / advice confidence
├── training/           # evaluator / leak classifier / drill generator
├── explanation/        # deterministic templates; optional LLM adapter
└── realtime/           # fast path / slow path / stale filter
```

依赖规则：

- Core 和 State 不依赖 Vision、solver、LLM、UI 或持久化实现。
- Strategy source 不直接输出 UI 数据，只输出版本化 `StrategyCandidate`。
- Decision Fusion 是唯一生成 `Advice` 的出口。
- Explanation 不得反向修改 Advice。
- 仓库中不存在自动点击、键盘下注或客户端注入模块。

已有模块的详细契约继续见：

- [Core contracts](docs/core-contracts.md)
- [Capture and table mapping](docs/capture-and-table-mapping.md)
- [Vision engine](docs/vision-engine.md)
- [Confidence gate](docs/confidence-gate.md)
- [State engine](docs/state-engine.md)
- [Hand memory](docs/hand-memory.md)
- [Orchestrator](docs/orchestrator.md)
