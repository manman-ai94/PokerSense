# PokerSense 策略需求矩阵

> 状态：功能、输入、处理和输出的详细验收基线
> 更新日期：2026-08-22
> 上游输入：经过 Temporal Consensus 和 Confidence Gate 的 `StableObservation`
> 下游输出：版本化、可解释、可拒答的 `Advice`

## 1. 文档目的

本文将 [`realtime-training-assistant.drawio.svg`](archive/realtime-training-assistant.drawio.svg) 中“识别完成之后”的链路拆成可开发、可测试、可验收的细粒度需求。产品级需求由 [`product-requirements.md`](archive/product-requirements.md) 定义；自动化运行方式和完整回归门槛由 [`strategy-regression-test-matrix.md`](strategy-regression-test-matrix.md) 定义。

范围从 canonical state 构建开始，到 Live Coach UI 收到 Advice 为止：

```text
StableObservation
→ Application Orchestrator
→ State/Event Engine + Hand Memory
→ DecisionContext Builder
→ Derived Metrics + Range Tracker
→ Equity Service + Strategy Router
→ Fast Sources / Slow Resolver
→ Decision Fusion + Rejection Gate
→ Advice Contract
→ Serialization / WebSocket / Live Coach UI
```

本文不重复定义图像识别算法，但定义策略层接受识别结果必须满足的字段、质量和来源要求。

### 1.1 使用方法与追踪规则

- 产品需求使用 `REQ-*`，模块功能使用 `ST/CTX/MET/RNG/EQ/PRV/RTR/EV/FUS/ADV/UI/TRN-*`，测试使用 `T-*`。
- 每个代码变更必须指出影响的功能 ID；每个功能 ID 至少有一个自动测试 ID。
- 每个宣称支持的场景必须在输入矩阵中满足所有 `R` 字段，并在输出矩阵中满足对应状态契约。
- 本文中的细粒度测试是需求的最低验收例；CI 套件和发布回归以回归测试矩阵为准。

### 1.2 产品需求到模块的覆盖关系

| 产品需求 | 主要模块功能 | 关键输出 |
|---|---|---|
| `REQ-IN-001`、`REQ-IN-002` | ST-001、CTX-002/003 | Provenance、quality、UNKNOWN/CONFLICT |
| `REQ-ST-001`、`REQ-ST-002` | ST-002~007、MEM-001 | PokerState、StateEvent、legal actions、pots |
| `REQ-CTX-001` | CTX-001~004 | DecisionContext、missing fields、deadline |
| `REQ-MET-001` | MET-001~004 | Effective stack、SPR、pot odds、normalized size |
| `REQ-RNG-001` | RNG-001~005 | Versioned per-player ranges、entropy/confidence |
| `REQ-EQ-001` | EQ-001~006 | MathReport、method、CI、multiway pot share |
| `REQ-PRV-001`、`REQ-RTR-001` | PRV-001~007、RTR-001~008 | Candidate、lookup state、source/version/match |
| `REQ-FUS-001` | EV-001~003、FUS-001~005 | Legalized candidate、EV、final status |
| `REQ-OUT-001`、`REQ-OUT-002` | ADV-001~003、EXP-001、SER-001 | Versioned Advice、reason codes、evidence |
| `REQ-UI-001` | UI-001~003 | Live READY/PARTIAL/ABSTAIN/STALE display |
| `REQ-PERF-001` | CTX-004、RTR-005~008、UI-003 | First-advice latency、deadline、Fast/Slow timing |
| `REQ-AUD-001` | CTX-002、ADV-003、SER-001 | End-to-end evidence chain |
| `REQ-TRN-001` | TRN-001/002 | Actual action、debrief、qualified EV loss |

## 2. 状态说明与术语

| 标记 | 含义 |
|---|---|
| `C` | 当前代码已有，可直接复用或小幅扩展 |
| `P` | 当前只有部分契约或基础算法，需要补齐 |
| `N` | 需要新建 |
| `R` | 该场景策略所需输入 |
| `O` | 可选输入；缺失时降低能力或置信度 |
| `—` | 该场景不适用 |
| `ABSTAIN` | 不给出动作策略，并说明缺失或冲突原因 |
| `PARTIAL` | 只能提供部分数学结果或有限建议，不能包装成完整 GTO |

## 3. 识别后完整功能表

### 3.1 权威状态与决策上下文

| ID | 状态 | 功能 | 输入 | 确定输出 | 失败/拒答行为 | 主要验证 |
|---|---|---|---|---|---|---|
| ST-001 | C | Observation 编排 | `StableObservation`、previous state | 调用状态转换并决定是否持久化 | Observation 类型或版本错误时拒绝写入 | 通用 `TemporalConsensus` 已在 StateEngine 前接入实时 Pipeline；逐字段/逐 slot 连续帧、序号缺口、UNKNOWN/CONFLICT、状态写入和 8 组可执行 Mock 已验证 |
| ST-002 | P | State/Event Engine v2 | Previous state、observation、rules、版本化平台 slot→seat contract、hash-pinned Capture Replay | `PokerState`、`StateEvent[]`、`ValidationResult`、Replay quality report | 未映射/冲突 slot、混合发牌与行动、非法行动或筹码不守恒时保持旧状态且不生成事件；Stable/Synthetic Replay 永不提升为真实发布证据 | 通用 temporal gate、显式 `PlatformSeatMapping`、2–9 人 candidate-state、行动重建、原子持久化，以及 artifact/config/calibration/frame hash、授权/隐私、frame/revision evidence、逐帧预期和机器可读报告的 `raw_frame` Replay runner 已完成；平台映射 38 个、Replay 合同 32 个聚焦测试和 23 组 Synthetic Replay 已验证。WePoker stack/action/actor/dealer 的实测 ROI/slot calibration 与授权原始帧仍缺，因此保持 P |
| ST-003 | C | 状态版本管理 | `hand_id`、previous version | Material change 时版本 `+1` | No-op 不增加版本 | 单元测试 |
| ST-004 | C | Hand boundary | Hero cards、dealer/button、street/board/pot/stack reset 证据 | 新 `hand_id`、旧手牌 `HAND_END` 事件 | 冲突证据返回 `AMBIGUOUS`；弱证据不切手；dealer/stack 仅在显式 slot→seat 映射后使用 | 确定性 detector、RealtimePipeline 切手、HandMemory 旧手完成事件和 6 组可执行 Mock 已验证；真实平台映射与 Replay 仍属于 ST-002 |
| ST-005 | C | 行动事件重建 | 相邻 canonical states、Actor、可选 action label、stack/commitment/pot/current-bet delta | 规范 fold/check/call/bet/raise/all-in `StateEvent`，同时记录 additional/total-street 金额语义 | 筹码、身份或状态不一致返回 `INVALID`；多个合法解释返回 `AMBIGUOUS` 且不生成事件、阻断策略 | 29 个 delta/状态/金额/歧义测试和 8 组可执行 Mock 已实现；ST-002 的通用平台映射现已调用同一 production 重建器，真实平台校准仍单独验收 |
| ST-006 | C | 合法动作计算 | State、actor、规则、stack | `LegalAction[]`，含 min/max size 和金额语义 | Actor/金额不完整时无策略 | check/bet、fold/call/raise、short all-in 和异常边界测试已实现 |
| ST-007 | C | 主池/边池计算 | Player commitments、fold/all-in、betting-open/closed | `PotState[]` + settled unmatched-chip returns | 进行中的领先投入保留在 provisional pot；关闭后才退回；不守恒时硬门失败 | 四组 all-in/折叠 fixture、开放盲注、eligible seats 和筹码守恒已实现 |
| MEM-001 | C | 状态和事件存储 | Valid state/events、hand-boundary successor | 可按 hand/version 查询的历史；原子 state+events 与 old-hand+successor 提交 | 全部预验证后才修改内存；任一事件、版本、hand 或 successor 冲突时状态、事件、history、active hand 均不变 | `record_transition`、`replace_active_hand`、Orchestrator 接入、回滚/幂等/边界集成测试及 4 组可执行 `MOCK-MEMORY-*` 已验证 |
| CTX-001 | C | DecisionContext 构建 | Canonical state、events、profile versions | 不可变 `DecisionContext` | 必需字段缺失则记录 `missing_fields` | State→Context Builder、请求绑定、人数切换和缺失字段测试已实现 |
| CTX-002 | C | 输入来源汇总 | Observation evidence、用户输入、配置、派生和推断 | 唯一字段的 `InputProvenance[]` + 可审计 candidates | 空值转 `UNKNOWN`；不同可用值转 `CONFLICT`，不得静默按优先级覆盖或进入 Advice | 四类外部来源自动标记、派生来源、同值共识、冲突、稳定 value digest、确定性排序、Context Builder 和 8 组可执行 Mock 已实现 |
| CTX-003 | C | 上下文质量计算 | 各字段 confidence、state consistency | `ContextQuality` | 硬门失败时标记不可决策 | required-field 最低置信度、阈值、missing/UNKNOWN/CONFLICT/LOW_CONFIDENCE、一致性失败及 Builder fail-closed 测试已实现 |
| CTX-004 | C | RequestContext 创建 | Hand/version、clock、deadline | `request_id`、requested/expires time | ID 不唯一或时间无时区时失败 | 线程安全工厂、显式 clock、期限、重复 ID 重试/失败/回滚和时区测试已实现 |

### 3.2 Derived Metrics、范围与 Equity

| ID | 状态 | 功能 | 输入 | 确定输出 | 失败/降级行为 | 主要验证 |
|---|---|---|---|---|---|---|
| MET-001 | C | Effective stack | Hero 与每个 active villain stack | Pairwise `EffectiveStack[]` 和最短 effective stack BB | 必要 stack 无法进入 canonical state 时 Context 不可构建 | 多人不同筹码示例测试已实现 |
| MET-002 | C | SPR | Pots 和 postflop pairwise effective stacks | 每个相关对手的 Decimal SPR | Pot=0 时值为 `UNKNOWN`，不伪装成 0 | 多对手、主/边池和 zero-pot 边界测试已实现 |
| MET-003 | C | Pot odds | Pot、to-call | Decimal break-even equity | `to_call=0` 明确标记 no-call-cost | `P=100,C=25` 和 zero-call exact 测试已实现 |
| MET-004 | C | 下注尺度规范化 | Additional/total amount、pot、BB、current bet | BB、pot fraction、raise multiplier | 基数为 0 时对应比例为 `None`；金额语义冲突拒绝 | exact 数值与异常边界测试已实现 |
| RNG-001 | C | 初始范围选择 | Player count、position、stack、preflop history | 版本化 concrete-combo prior distribution | 无适用来源时 `NOT_APPLICABLE/UNKNOWN`，不使用 random range 冒充策略范围 | 已实现显式 6/9 人、100BB、first-in open-raise 资产到均匀 concrete-combo prior；13 位置、169 类展开、blocker、无 fallback 共 41 个测试 |
| RNG-002 | C | Blocker 过滤 | Concrete combo ranges、Hero cards、board | 无冲突且精确归一的 combo distribution | 所有权重被移除时 `range_card_collision` | Hero/board blocker、全冲突和抽象标签拒绝测试已实现 |
| RNG-003 | C | 行动贝叶斯更新 | Prior、combo-action likelihood、observed action | Posterior、entropy、ESS、likelihood coverage | Likelihood 缺失时保留 prior mass 并降低 confidence；全零时冲突 | 手算 posterior、部分/全部缺失和非法 likelihood 测试已实现 |
| RNG-004 | C | 小样本收缩 | Opponent likelihood、population prior、sample size | Shrunk combo-action likelihood | 样本不足时接近总体先验 | sample size 0/小/大边界测试已实现 |
| RNG-005 | C | 多人组合兼容性 | 多个 concrete villain ranges、已知牌 | 精确归一的联合 assignments | Card collision 必须排除；组合数超预算拒绝枚举 | 跨玩家碰牌、known blocker、无解和预算测试已实现 |
| EQ-001 | C | Known-hand exact equity | Hero、known villains、board | Win/tie/loss/equity/samples | 重复牌或非法 board 抛出领域错误 | 单元测试 |
| EQ-002 | C | Range exact equity | Hero、villain ranges、board | 加权 exact result | 空范围或全部冲突时明确失败 | 单元 + differential |
| EQ-003 | C | Monte Carlo equity | 同上、trials、seed | 可重放估计 + standard error/95% CI | Trials 不足时降低 numerical confidence | 已有 known/range MC；新增多人联合范围 seeded 重放、exact anchor 与 CI 测试 |
| EQ-004 | C | Adaptive equity budget | Street、concrete ranges、deadline、cache | Method、planned/actual trials、confidence interval、COMPLETE/PARTIAL | MC 达到 wall deadline返回已完成样本的 PARTIAL；过期请求拒绝；预算不得高于目标硬件保守校准 | 小范围 exact、超限范围 rejection-sampling MC、CI/cache/wall-stop 已实现；Apple M1 Pro 10-core/32GB、Python 3.12.2 五次复测给出 exact p95=7.186 outcomes/ms、最慢 MC p95=4.757 trials/ms，默认采用约 50% 安全预算 3/2 并由版本化 JSON/hash 测试锁定 |
| EQ-005 | C | Multiway pot-share equity | Hero、多个 concrete joint assignments、board/pots | 每个主池/边池 win/tie/loss、expected share/chips 和总 pot equity | 按 eligible seats 联合比较；碰牌、缺 holding 或超预算明确失败 | 加权范围、三人 tie、边池资格、turn 枚举和预算测试已实现 |
| EQ-006 | C | Equity cache | Canonical cards/ranges/version/method/trials/seed | Cache hit result + CI + provenance | Key 任一维度变化 `NOT_FOUND`；过期 `STALE`；LRU 淘汰 | canonical 等价、逐维 miss、TTL、LRU、结果身份测试已实现 |

### 3.3 Strategy Provider 与路由

| ID | 状态 | 功能 | 输入 | 确定输出 | 失败/拒答行为 | 主要验证 |
|---|---|---|---|---|---|---|
| PRV-001 | C | Provider capability 声明 | Provider metadata | 支持的人数、street、Hero position、stack、ante/rake、action tree，以及可选 pot/aggressive-size abstraction | 声明不完整时不注册；位置、人数、street、配置或行动线不匹配时不查询 Provider | 合同、注册冲突、2–9 人参数化、内置 Provider 位置声明及 abstraction 边界测试已实现 |
| PRV-002 | C | HU Preflop Blueprint Adapter | 2-max preflop context | 动作标签、逐尺度频率、source/version | 非 HU、history 或明确 stack/ante pair 不匹配时返回 `NOT_APPLICABLE/NOT_FOUND` | 已接入 `amaster97/poker_solver` 1.11.0；ante/动作尺度按任意 BB 归一；capability 保存真实 stack×ante pairs；完整 169 root + 11 个跨 action/stack/ante 节点共 180 次固定 Golden parity，含 commit/manifest/shard 证据 |
| PRV-003 | P | Multi-player Preflop Provider | 3–9 人 preflop context | 按实际人数、位置、筹码和行动线的动作频率 | 只允许匹配 Provider 明确覆盖的人数；来源、许可、版本、asset/capability hash 不清楚时不得注册或发布 | 通用 hash-pinned JSON Strategy Asset Adapter、3 人 synthetic 节点和完整拒答链已实现；GTOpen 本地研究 Adapter 已能调用 2–9 人 API，但固定标为模型型 HEURISTIC，不能冒充完整 GTO 或发布资产。真实许可资产与 3–9 人分层 Golden spots 尚缺 |
| PRV-004 | P | Multiway Postflop Provider | 3-way、4-way+ postflop context | 多人动作频率、尺度和可用 EV | 不得调用 HU provider 或把多个 HU 策略拼接成多人策略 | 通用 Adapter 已验证 3-way flop 与 4-way turn synthetic 节点；真实多人 postflop 资产与 Golden spots 尚缺 |
| PRV-005 | P | Presolved postflop Adapter | Canonical context digest（board、ranges、pot/stack/tree）、版本化资产 | Strategy candidate、逐尺度频率、可用 EV、hash/license/node evidence | Asset 与 capability SHA 不符时注册失败；节点缺失 `NOT_FOUND`；节点损坏 `REJECTED`；插值无 dimensions 非法 | `JsonStrategyAssetProvider`、schema/hash/capability/license/version 校验、Router/Advice 接入、21 个测试和 6 组可执行 Mock 已完成；真实 presolved 导出 schema parity 与 Golden 尚缺 |
| PRV-006 | C | Lightweight policy/value Adapter | 完整 context、model/asset version | Approximate strategy/value | 必须标记 heuristic/model，不得标为 exact GTO | 已实现固定 MIT 来源和 hash 的 6/9 人、100BB、unopened RFI heuristic；7/8 人走**同名 9 人键派生**（仍禁 9_BTN last-resort 与 BB fallback、3-5 人相邻 fallback）；31 个 contract/169-class Golden/拒答/路由测试 + 13 个 derived 键 169-class Golden + derived 指向校验 |
| PRV-007 | C | Local Resolver Adapter | Context、ranges、tree、budget | Versioned candidate、iterations/exploitability metadata | 无 shell 子进程；timeout/未收敛/超阈值/崩溃/坏输出/身份或版本错误均 `REJECTED/NOT_FOUND` | JSON stdin/stdout protocol、双重 deadline、输出上限及 Async Slow Path 集成共 20 个真实进程测试 |
| PRV-008 | C | GTOpen local Preflop model Adapter | 2–9 人 preflop context、loopback API、固定 revision、求解预算 | Hero 169-class 的动作/逐尺度频率、iteration、model gap、tree/realization evidence | 仅 loopback；单 session 串行；非 preflop/不等起始筹码/位置、action-line 或行动路径不精确/超时/未收敛/非法动作均拒答；多人固定 HEURISTIC，不远程证明 server revision，不复制或发布无许可源码/资产 | `GTOpenPreflopProvider`、真实 M1 Pro API E2E、21 个 2–9 人/context/路径/尺度/收敛/故障/Slow Advice 测试；上游许可与独立 Golden 仍由 PRV-003 发布门控制 |
| RTR-001 | C | Provider 注册表 | Provider instances | 唯一 provider IDs 和版本 | ID/version 冲突时启动失败 | 已实现并测试 |
| RTR-002 | C | Capability filter | DecisionContext、capabilities | 适用 provider 列表 | HU provider 永不匹配 `player_count > 2` | 2–9 人和 postflop active-count 测试已实现 |
| RTR-003 | C | 精确路由 | Exact state/provider match | 最高优先级 candidate | 不允许被低等级 heuristic 覆盖 | Exact 优先级已实现并测试 |
| RTR-004 | C | 近似匹配 | State 与 Provider 明确声明的位置、stack、pot、last-aggressive-size/action-line abstraction | Candidate/Advice/UI 的结构化 `match_dimensions[]`（requested、matched、distance、maximum）+ 保守 `state_match_score` | 任一精确维度不匹配或距离超过阈值即 `NOT_APPLICABLE`；`INTERPOLATED` 缺少维度即非法；Provider 不得上报高于 dimension/capability 的 score，也不得把插值声称为 exact | position/stack/pot/aggressive-size/action-line、组合最小 score、阈值两侧、本地 Resolver、缓存、融合、序列化、UI 和 4 组可执行 Mock 已验证 |
| RTR-005 | C | Fast source fallback | Cache → Preflop DB → Presolved → Model | 固定顺序中第一层可用 candidate；保留所有已查询结果 | 命中后不得查询更低层；miss/not-applicable/rejected 才继续；全部失败时无虚假 candidate，只能 Equity 时返回 `equity_only` | `TieredStrategyRouter`、lookup-only Cache Provider、write-through 回填、同一 Provider 跨层身份、Orchestrator 接入、all-miss reason 聚合和 5 组可执行 Mock 已验证；真实 DB/Presolved/Model 资产适用性分别由 PRV-002~006 管理 |
| RTR-006 | C | Slow resolver 调度 | Cache `NOT_FOUND`、EV gap、deadline | Async request handle | Fast Advice 不等待 resolver | `StrategyOrchestrator` 立即返回 Fast Advice，只在无 exact Fast 且 capability 匹配时提交 Future；同步 Provider 的线程适配和并发测试已实现 |
| RTR-007 | C | Stale filter | Candidate request context、current state | Accept/discard | Hand/version/request/deadline 任一不符即丢弃 | 异步 collect 对 hand/state/request、request/candidate expiry、provider identity 和质量提升做 fail-closed 验证；旧 Future 取消/丢弃测试已实现 |
| RTR-008 | C | 结果缓存 | Candidate + canonical key | Versioned cache entry | Solver/provider/version 变化必须 cache `NOT_FOUND` 并重新查询 | Canonical context、provider/version/asset/engine key、identity-free template、新 request 重绑定、TTL/STALE、LRU、并发、Cache→Provider 和错误存储门已实现 |

### 3.4 动作 EV、融合、Advice 与 UI

| ID | 状态 | 功能 | 输入 | 确定输出 | 失败/拒答行为 | 主要验证 |
|---|---|---|---|---|---|---|
| EV-001 | C | Call EV | Equity、pot、to-call | `EV(call)` | 未来行动未建模时标记 immediate EV | 精确公式 `share*(pot+call)-call`、0/1、split、微额/大底池和非法概率测试已实现 |
| EV-002 | C | Bet/Raise EV | Fold/call/raise likelihood、sizes、continuation values | Per-action EV | 缺 continuation value 时不得伪造完整 EV | 分支概率严格求和；fold 赢当前 pot；正概率 call/raise 分支缺净 continuation EV 时返回 UNKNOWN |
| EV-003 | C | EV gap | Legal action EV map | Best/second-best gap | EV 不完整时 gap unknown | 所有合法动作完整性、best/second、tie 和 Advice 集成测试已实现 |
| FUS-001 | C | Candidate 合法化 | Candidate、legal actions | 非法动作归零并重新归一化 | 全部非法则 ABSTAIN | 动作和尺度合法化已实现并测试 |
| FUS-002 | C | GTO baseline 选择 | 多个 candidates、source priority | 单一 Baseline candidate | 不混合不同 abstraction 后继续声称 exact | Router 按 exact/interpolated/heuristic、match score、priority 选择唯一 baseline；DecisionFusion 保留该 baseline，只允许一次可审计 KL 调整并降级为 HEURISTIC，已接入 Fast/Slow Advice |
| FUS-003 | C | 鲁棒对手调整 | Baseline、Q values、profile quality、KL budget | Exploitative candidate + adjustment metadata | 样本不足、画像低质、Q 不完整或预算为零时原样退回 baseline | 已实现 profile/sample/weight/logit/KL 四重约束的指数倾斜；零支持保持、尺度条件频率、极端 Q、单调预算和 fail-safe 共 27 个测试 |
| FUS-004 | C | 硬拒答门 | Context、state、strategy、stale flags、模块化 `GateResult[]` | READY/PARTIAL/ABSTAIN/STALE + 可审计 PASS/FAIL/SKIPPED 门结果 | 过期优先转 STALE；任一内置或外部硬门失败不得 READY；失败门必须给出 reason，外部门不得覆盖保留门名 | freshness/confidence/context/strategy/legal 五个内置门、可扩展 range/numerical 等外部门、Fusion/Orchestrator/Advice/序列化/UI 全链路及 4 组可执行 Mock 已验证 |
| FUS-005 | C | 置信度聚合 | Perception/state/match/range/numerical quality | 保守 confidence | 缺一项时不得用平均值掩盖低值 | 具名因子最小值聚合已接入 Advice；input/provider/state-match 由 Builder 自动提供，range/numerical 可显式注入；声明但缺失时 confidence=0、ABSTAIN 并记录缺失因子 |
| ADV-001 | C | Advice 构建 | Context、math report、strategy/fusion result | 完整 Advice | 字段和来源不一致时构建失败 | 四状态合同、字段门槛和构建器已实现 |
| ADV-002 | C | Advice 有效期 | Clock、state/action deadline | `expires_at` | 到期后 UI 必须显示 STALE/隐藏策略 | Request/candidate expiry 和 mark-stale 已实现 |
| ADV-003 | C | Evidence chain | Observation/state/range/provider refs | SHA-256 chain ID、结构化 refs、完整度和缺失段 | 断链时 confidence 上限 0.49，并披露具体 missing evidence；旧 schema v1 仍可读取 | 动态 required input、canonical state、Hero/逐对手 range、Provider 证据审计已接入 Advice；完整/断链/digest/序列化共 19 个测试 |
| EXP-001 | C | 确定性解释 | Advice、模板、语言 | 人类可读 key factors | 不得修改数值或动作 | 中英文确定性模板保留原始 Decimal 频率/尺度/来源/匹配/置信度，READY/ABSTAIN snapshot 已实现 |
| SER-001 | C | 序列化 | Advice/DecisionContext/现有 reports | JSON-safe payload | Round-trip 字段不得丢失 | Strategy schema v1 与旧 RequestContext 兼容测试已实现 |
| UI-001 | C | Live Advice 渲染 | Serialized Advice | 频率、尺度、EV、来源、置信度 | 非 READY 不显示行动建议 | `advice_to_view`、Live Coach renderer 和生产 `live_analysis_stream → LiveStrategySession → StrategyOrchestrator → DesktopFrame` 已接通；Advice 绑定 hand/state/request 和感知质量指纹，READY 排序展示，PARTIAL/ABSTAIN/STALE 清空动作；当前真实 WePoker 输入不足且无内置 HU 策略资产，因此生产流按合同 ABSTAIN |
| UI-002 | C | 来源和假设标识 | Provenance、match kind、manual inputs | Exact/approx/heuristic/manual badges | 人工值不得显示成视觉识别 | Advice 结构化保留逐字段 Vision/manual/config/derived/inferred 来源和质量；UI 显示 match 与来源徽标，人工输入独立高亮，并显示来源/版本、假设和 evidence；旧 Advice 无新增字段可兼容读取 |
| UI-003 | C | Advice 更新策略 | Fast Advice、slow refinement、state updates | 原位更新或过期移除 | Slow 旧结果不得闪回 | 原子 `DesktopFrame(analysis, Advice?)` 支持同状态 Fast→Slow 原位升级；发送前核对 hand/state identity 和 expiry，版本不符或到期均转 STALE 并清空动作；真实 WebSocket 顺序测试已实现 |
| TRN-001 | C | 实际动作记录 | Human action observation、Advice ref | Versioned chosen-action event | 无法确认动作时不推断选择 | `ActualActionRecord` 强制 hand/state/request、动作/尺度、时间和 evidence；identity mismatch 测试已实现 |
| TRN-002 | C | Hand Debrief | 一手内 Advice、actual actions、counterfactual EV | 决策明细、已知总 EV loss、完整度、最大漏损点、偏差和训练标签 | 没有可信 counterfactual EV 时只汇总已知部分并标记 partial；缺失/孤立/重复动作不猜测配对 | 单点及整手聚合、时间排序、identity、缺 EV、missing/orphan/duplicate/cross-hand 共 22 个测试；真实 Replay 仍是发布验收证据而非算法完成条件 |

## 4. 策略输入矩阵

### 4.1 决策输入字段

| 输入字段 | 权威来源 | HU Preflop | HU Postflop | 3–9 人 Preflop | 3-way/4-way+ Postflop | 质量门与缺失行为 |
|---|---|---:|---:|---:|---:|---|
| `hand_id` | Hand Memory | R | R | R | R | 缺失即停止 |
| `state_version` | State Engine | R | R | R | R | 与结果不匹配即 STALE |
| `request_id/deadline` | Orchestrator | R | R | R | R | 慢路径必须具备 |
| Game type | Platform config | R | R | R | R | Provider 必须精确支持 |
| Seat count | Table map/state | R | R | R | R | HU Provider 仅允许 2 |
| Occupied/active seats | State Engine | R | R | R | R | 冲突则 ABSTAIN |
| Hero seat/cards | Vision → State | R | R | R | R | 两张牌且通过门控 |
| Dealer button | Vision → State | R | R | R | R | 用于位置；未知则策略拒答 |
| Hero/villain positions | Derived from seats/button | R | R | R | R | 必须可唯一推导 |
| Street | Vision/State | R | R | R | R | 与 board count 一致 |
| Board cards | Vision → State | — | R | — | R | 3/4/5 张、无冲突 |
| Blinds | Config/recognition | R | R | R | R | 金额必须为 Decimal |
| Ante | Config/recognition | R | R | R | R | Provider capability 必须匹配 |
| Rake/cap | Config | O | R | O | R | 依赖策略源时必须具备 |
| Player stacks | Vision → State | R | R | R | R | 关键 stack 未知则拒答 |
| Street commitments | Vision/events | O | R | O | R | 用于行动和边池守恒 |
| Pot/main/side pots | State Engine | O | R | O | R | Postflop 必需 |
| Current bet/to-call | State Engine | R | R | R | R | 与 legal actions 一致 |
| Actor seat | State Engine | R | R | R | R | 非 Hero actor 时通常不输出 Hero Advice |
| Legal actions/sizes | Rules engine | R | R | R | R | Strategy 输出必须是其子集 |
| Preflop action history | Event stream | R | R | R | R | 不可达/歧义节点拒答 |
| Postflop action history | Event stream | — | R | — | R | 必须包含尺度和 actor |
| Effective stacks | Derived | R | R | R | R | 多人按 pair/pot 表达 |
| SPR | Derived | — | R | — | R | 未知时部分 postflop provider 不匹配 |
| Hero range | Strategy prior | O | R | O | R | 具体 Hero cards 可用于展示；求解需要 range |
| Villain ranges | Range Tracker | O | R | O | R | Equity-only random range必须显式标记 |
| Opponent profile | Profile store | O | O | O | O | 仅用于受约束调整，不是权威事实 |
| Input provenance | Context Builder | R | R | R | R | 人工/识别/配置/推断必须区分 |
| Context quality | Context Builder | R | R | R | R | 硬门失败即 ABSTAIN |

### 4.2 最小输入组合

| 场景 | 最小可输出结果 | 必需输入 | 缺失时输出 |
|---|---|---|---|
| Hero cards only | 随机范围 preflop equity | Hero cards、player count 假设标记 | 无 Strategy，`PARTIAL/equity_only` |
| HU Preflop Demo | Blueprint action frequencies | Hero cards、HU position、stack BB、ante、action history、legal actions | `ABSTAIN` 或只显示 equity |
| HU Postflop equity | Hero-vs-range equity/pot odds | Hero/board、pot、to-call、villain range | 缺范围可用 random range，但必须标记假设 |
| HU Postflop strategy | Strategy/EV | 完整 state、双方 ranges、tree/provider match | 无 provider 时 `PARTIAL` 或 `ABSTAIN` |
| 3–9 人 Preflop | 按实际人数、位置和行动线的 frequencies | Seat occupancy、button、所有位置、stack、完整 history、覆盖该人数的 Provider | 禁止使用 HU Provider；无适用多人 Provider 时 `ABSTAIN` |
| 3-way Postflop | 三人 Equity 或三人策略 | 两个 villain ranges、pot/side pots、actor/history、3-way Provider | 无策略源时只给可信 3-way Equity |
| 4-way+ Postflop | 多人 Equity 或多人策略 | 所有 active ranges、主/边池、pairwise effective stacks、行动线、覆盖该人数的 Provider | 不得拆成多个 HU 结果；无策略源时 Equity-only 或 `ABSTAIN` |

## 5. 策略输出矩阵

| 输出字段 | READY | PARTIAL | ABSTAIN | STALE | 验证规则 |
|---|---:|---:|---:|---:|---|
| `hand_id/state_version/request_id` | R | R | R | R | 必须与产生结果的上下文一致 |
| `status` | READY | PARTIAL | ABSTAIN | STALE | 枚举值 |
| `action_probabilities` | R | O | 空 | 空 | 合法动作；总和≈1；非法动作=0 |
| `action_options` | O/R | O | 空 | 空 | 每个动作/total-street 尺度保留独立频率；过滤非法尺度后重新归一化 |
| `recommended_sizes` | O/R | O | 空 | 空 | 每个尺度属于 legal sizing |
| `action_ev` | O | O | 空 | 空 | 只有真实计算/策略源提供时显示 |
| `ev_gap` | O | O | 空 | 空 | 至少两个可比动作 EV 才允许输出 |
| `preferred_action` | O | O | 空 | 空 | 混合策略默认仍显示完整频率 |
| `math_report` | O | R/O | O | O | Equity/pot odds 与 Strategy 分开标识 |
| `strategy_source/version` | R | O | O | R | READY 不允许未知来源 |
| `match_kind` | R | O | O | R | exact/interpolated/heuristic/equity_only |
| `state_match_score` | R | O | O | R | Exact=1；近似必须列出差异维度 |
| `match_dimensions[]` | 近似时 R | O | 空 | 保留 | 每项含 dimension、requested、matched、distance、maximum_distance；UI 必须可见 |
| `confidence` | R | R | R | R | 保守聚合，范围 `[0,1]` |
| `evidence` | R | R | R | R | 可追踪到 observation/state/provider |
| `assumptions` | O | R | R | O | 所有人工和默认输入必须列出 |
| `missing_inputs` | 空/O | R | R | O | READY 不得缺决定性字段 |
| `rejection_reasons` | 空 | O | R | R | 机器可读代码 + 用户文本 |
| `gate_results[]` | R | R | R | 保留 | 内置及外部门的 PASS/FAIL/SKIPPED；FAIL 必须有 reason，READY 不得含 FAIL |
| `expires_at` | R | R | R | R | 到期后不可继续显示 READY |

## 6. Strategy Router 决策矩阵

### 6.1 内部查找状态与用户输出

`NOT_FOUND` 只是某一个数据源没有找到当前节点，Router 必须继续检查下一个适用来源；它不是最终失败，也不能直接显示给用户。

| 内部状态 | 含义 | Router 动作 | 是否直接成为 Advice |
|---|---|---|---|
| `NOT_CHECKED` | 尚未检查该来源 | 按优先级继续 | 否 |
| `HIT_EXACT` | 找到精确节点 | 进入合法化和融合 | 可以形成 READY |
| `HIT_APPROXIMATE` | 找到明确可解释的插值/近似节点 | 记录差异和 match score 后进入融合 | READY 或 PARTIAL |
| `NOT_FOUND` | 适用来源中没有当前节点 | 继续检查下一来源 | 否 |
| `NOT_APPLICABLE` | 玩家人数、street、rake、stack 或行动树不适用 | 跳过该来源 | 否 |
| `REJECTED` | 资产损坏、输出非法、过期或未收敛 | 记录原因并尝试安全降级 | 否 |
| `NO_STRATEGY` | 所有适用策略来源均无结果 | 只允许 Equity-only 或 ABSTAIN | PARTIAL/ABSTAIN |

### 6.2 多人路由矩阵

| 当前场景 | 精确策略来源 | 近似来源 | Equity | Slow Resolver | 最终允许状态 |
|---|---|---|---|---|---|
| 2 人 preflop | HU Preflop Provider | HU stack/action interpolation | HU range equity | 可选，不作为首个 Demo | READY/PARTIAL/ABSTAIN |
| 3 人 preflop | 3-player Preflop Provider | 仅可使用声明支持 3 人的 model | 3-player equity | 仅支持 3 人时启动 | READY/PARTIAL/ABSTAIN |
| 4 人 preflop | 4-player Preflop Provider | 仅可使用声明支持 4 人的 model | 4-player equity | 仅支持 4 人时启动 | READY/PARTIAL/ABSTAIN |
| 5 人 preflop | 5-player Preflop Provider | 仅可使用声明支持 5 人的 model | 5-player equity | 仅支持 5 人时启动 | READY/PARTIAL/ABSTAIN |
| 6 人 preflop | 6-max Preflop Provider | 仅可使用声明支持 6 人的 model | 6-player equity | 仅支持 6 人时启动 | READY/PARTIAL/ABSTAIN |
| 7 人 preflop | 7-player Preflop Provider | 仅可使用声明支持 7 人的 model | 7-player equity | 仅支持 7 人时启动 | READY/PARTIAL/ABSTAIN |
| 8 人 preflop | 8-player Preflop Provider | 仅可使用声明支持 8 人的 model | 8-player equity | 仅支持 8 人时启动 | READY/PARTIAL/ABSTAIN |
| 9 人 preflop | 9-max Preflop Provider | 仅可使用声明支持 9 人的 model | 9-player equity | 仅支持 9 人时启动 | READY/PARTIAL/ABSTAIN |
| Postflop 剩余 2 人 | HU postflop presolved/model | HU abstraction match | HU range equity | HU subgame resolver | READY/PARTIAL/ABSTAIN |
| Postflop 3-way | 3-way postflop Provider | 仅支持 3-way 的 model | Joint 3-way equity | 仅支持 3-way 时启动 | READY/PARTIAL/ABSTAIN |
| Postflop 4-way+ | 对应 active-player-count Provider | 仅支持该人数的 model | Joint multiway equity | 仅支持该人数时启动 | READY/PARTIAL/ABSTAIN |

表中的“人数”有两个不同字段：

- `dealt_player_count`：本手开始时实际发牌人数，决定 preflop 位置和基础范围。
- `active_player_count`：当前仍未弃牌、仍参与底池的人数，决定 postflop 是 HU、3-way 还是 4-way+。

不得因为 preflop 是 6-max、flop 只剩两人，就继续使用 6-way postflop 模型；此时 postflop 策略分支是 HU，但双方范围必须由此前 6-max 行动历史推导。

### 6.3 来源执行矩阵

| 条件 | Cache | 对应人数 Preflop Provider | 对应人数 Postflop Provider | Model | Resolver | Equity | 最终状态 |
|---|---|---|---|---|---|---|---|
| Preflop exact key | 先查 | `HIT_EXACT` | `NOT_APPLICABLE` | 不用 | 不用 | 可并行 | READY/exact |
| Preflop stack 可插值 | 先查 | `HIT_APPROXIMATE` | `NOT_APPLICABLE` | 可选 | 不用 | 可并行 | READY 或 PARTIAL/interpolated |
| 3–9 人 preflop，只有 HU Provider | `NOT_FOUND` | HU=`NOT_APPLICABLE` | `NOT_APPLICABLE` | 仅对应人数 model 可用 | 仅对应人数 resolver 可用 | Joint multi-player equity | ABSTAIN 或 equity_only |
| Postflop exact presolved | 先查 | `NOT_APPLICABLE` | `HIT_EXACT` | 不用 | 不用 | 可并行 | READY/exact |
| Postflop cache 未找到、输入完整 | `NOT_FOUND` | `NOT_APPLICABLE` | `NOT_FOUND` | 对应人数 Fast approximate | 对应人数异步 resolver | Fast math | PARTIAL → 可升级 READY |
| Flop/turn resolver 超预算 | `NOT_FOUND` | `NOT_APPLICABLE` | `NOT_FOUND` | 可选 | `REJECTED/timeout` | Fast math | PARTIAL，不等待 |
| Multiway postflop 无对应人数 Provider | `NOT_FOUND` | `NOT_APPLICABLE` | `NOT_FOUND` | 无适用 model | 不启动 HU resolver | Joint multiway equity | PARTIAL/equity_only |
| 关键状态 UNKNOWN/CONFLICT | 不查 | 不查 | 不查 | 不查 | 不启动 | 仅安全字段可显示 | ABSTAIN |
| Slow result 版本过期 | — | — | — | — | `REJECTED/stale` | — | 保持当前 Advice |
| Provider 输出非法动作 | — | — | `REJECTED` | `REJECTED` | `REJECTED` | — | 合法化后为空则 ABSTAIN |

## 7. 测试数据与夹具规范

### 7.1 Canonical fixture

每个策略测试夹具必须固定：

```text
fixture_id
game_config
hand_id/state_version
seat map / positions
hero cards / board
stacks / commitments / pots
actor / legal actions
action history
hero and villain ranges
input provenance / quality
strategy provider/version
expected status
expected source/match kind
expected actions or rejection reasons
numeric tolerances
```

### 7.2 最小场景集

| Fixture ID | 场景 | 用途 |
|---|---|---|
| FX-HU-PF-ROOT-AA | HU、100BB、no ante、SB root、AA | Exact blueprint adapter |
| FX-HU-PF-ROOT-AKS | HU、100BB、SB root、AKs | Suited hand-class mapping |
| FX-HU-PF-VS-R-AKO | HU、BB facing raise、AKo | Action-history mapping |
| FX-HU-PF-NOT-FOUND | HU、unsupported stack/history | Provider 未找到节点后的降级或拒答 |
| FX-MP-PF-{3..9}-ROOT | 分别为 3、4、5、6、7、8、9 人的 unopened spot | 参数化验证人数、位置和 Provider 精确路由 |
| FX-MP-PF-{3..9}-ACTION | 分别为 3–9 人的 limp/raise/3-bet/squeeze spot | 参数化验证多 actor 行动线和范围更新 |
| FX-HU-FLOP-SRP | HU single-raised flop | Pot odds、SPR、range equity |
| FX-HU-RIVER-CACHE | HU river exact presolved node | Postflop exact source |
| FX-HU-RIVER-STALE | Resolver 返回时 state 已变化 | Stale discard |
| FX-3W-FLOP | 三人 flop、两个 villain ranges | 3-way blockers/equity/provider routing |
| FX-4W-FLOP | 四人 flop、三个 villain ranges | 4-way blockers/equity/provider routing |
| FX-SIDE-POT | 三人 all-in、主池+边池 | Pot allocation |
| FX-CONFLICT-ACTOR | Actor 与动作证据冲突 | State/Advice ABSTAIN |
| FX-MISSING-POS | Hero position unknown | Context rejection |
| FX-EXPIRED | Advice 超过 deadline | UI STALE |

真实 Provider 的动作频率不能手工杜撰。Golden 值必须从固定版本的策略资产生成，记录资产 hash，并由独立 Adapter 直接查询结果冻结。

## 8. 细粒度可验证测试规划

### 8.1 单元与属性测试

| Test ID | 对应功能 | 输入/动作 | 可验证预期 |
|---|---|---|---|
| T-ST-001 | ST-003 | No-op observation | State version 不变，无持久化 |
| T-ST-002 | ST-002 | Pot/stack 不守恒 | Transition invalid，旧 state 保留 |
| T-ST-003 | ST-005 | 同一 delta 有两个合法解释 | Action history 标记 ambiguity，策略被阻断 |
| T-ST-004 | ST-006 | 随机合法 betting states | 生成动作均合法，min/max raise 满足规则 |
| T-ST-005 | ST-007 | 三人不同 all-in 金额 | 主池/边池金额和参与者精确匹配 |
| T-ST-006 | ST-005 | Fold/check/call/bet/raise、短码 all-in、label 冲突及筹码异常 | Exact 才生成事件；Ambiguous/Invalid 无事件并阻断策略 |
| T-CTX-001 | CTX-001 | 完整 HU context | `missing_fields=()`，可决策 |
| T-CTX-002 | CTX-001/003 | Position UNKNOWN | Context 构建成功但不可策略，原因明确 |
| T-CTX-003 | CTX-002 | 人工 stack + 视觉 cards | Provenance 分别为 manual/vision |
| T-CTX-004 | CTX-002/003 | Vision/manual/config/derived/inferred 单源、同值共识、异值冲突、null/low-confidence | 每字段仅一条 provenance；来源准确；冲突和未知触发质量硬门 |
| T-MET-001 | MET-001 | 多人不同筹码 | Pairwise effective stacks 正确 |
| T-MET-002 | MET-003 | `P=100,C=25` | Break-even equity=`0.2` |
| T-RNG-001 | RNG-002 | Hero/board blockers | 冲突 combos 权重为零并归一化 |
| T-RNG-002 | RNG-003 | 已知 likelihood | Posterior 与手算 Bayes 结果一致 |
| T-RNG-003 | RNG-004 | Sample size→0/∞ | 小样本接近 prior，大样本接近观察值 |
| T-RNG-004 | RNG-005 | 两 villain 持相同牌 | 联合 assignment 被排除 |
| T-RNG-005 | RNG-001/002 | 6/9 人显式 RFI 位置、AA/AKs/AKo、known blockers、其他人数/stack/action/BB | 只在明确能力内返回归一 concrete prior；冲突牌为零；不适用时无 distribution 且不使用 random fallback |
| T-EQ-001 | EQ-002 | Singleton range | Range exact 等于 known-hand exact |
| T-EQ-002 | EQ-003 | 固定 seed/trials | 结果可重放 |
| T-EQ-003 | EQ-003 | 多组 exact spots | MC 误差在统计容差内 |
| T-EQ-004 | EQ-005 | 可枚举三人 river | Multiway pot share 与手工枚举一致 |
| T-PRV-001 | PRV-001 | Capability 缺 player counts | Provider 注册失败 |
| T-PRV-002 | PRV-002 | 169 root hands + 11 个 c/b/r、20/100BB、0/0.5/1BB ante Golden 节点 | Adapter 与固定上游 180 次 lookup 一致；不同绝对盲注仍命中同一 BB 场景；不存在的 stack×ante 组合拒绝 |
| T-PRV-003 | PRV-006 | 6/9 人全部显式位置 × 169 手牌类 | 与固定 PreflopR 源生成资产一致；只输出 HEURISTIC raise/fold；无 size/EV |
| T-PRV-004 | PRV-003/006 | 3–5 人和 BB unopened；7/8 人 derived 指向非同名 9 人键或 9_BTN | Heuristic Provider 对 3–5 人仍 `NOT_APPLICABLE`；BB 仍拒答；7/8 人 derived 必须只能指向同名 9 人键，资产校验在加载时直接拒绝任何指向 9_BTN 或其他位置的派生项（运行时红线回归） |
| T-PRV-005 | PRV-007/RTR-006/007 | 本地子进程 converged/no-strategy/not-converged/timeout/crash/bad JSON/identity/version/convergence threshold | 成功结果带版本和收敛证据并可异步升级；所有失败可恢复且不污染当前 Advice |
| T-PRV-006 | PRV-003/008/RTR-006/007 | GTOpen 3 人 root、精确 raise 路径、多个 raise size、等/不等 stack、gap 阈值、timeout、transport/非法动作、Slow Advice | 只从精确 actor/kind/to 路径和 Hero 169-class 读取频率；尺度完整保留；失败拒答并尽力 stop；成功固定 HEURISTIC 且带模型限制/iteration/gap/tree/revision evidence |
| T-RTR-001 | RTR-002 | 参数化 3–9 人 context + HU provider | HU Provider 对每个人数均不进入候选列表 |
| T-RTR-002 | RTR-003 | Exact + heuristic 同时可用 | Exact provider 被选为 baseline |
| T-RTR-003 | RTR-004 | Match score 阈值两侧 | 阈值内 `HIT_APPROXIMATE`，阈值外 `NOT_FOUND` |
| T-RTR-004 | RTR-007 | Version/request/deadline 各自变化 | 每一种都独立触发 discard |
| T-RTR-005 | RTR-002/003 | 参数化 3–9 人 context + 对应人数 Provider | 每个人数只选择 capability 精确匹配的 Provider |
| T-EV-001 | EV-001 | 已知 q/P/C | Call EV 与公式一致 |
| T-EV-002 | EV-002 | 已知 f/c/r 分支 | Bet EV 与手算树一致 |
| T-FUS-001 | FUS-001 | Candidate 含非法 raise | 非法概率归零并重新归一化 |
| T-FUS-002 | FUS-004 | 每个硬门分别失败 | 均输出对应 ABSTAIN reason code |
| T-FUS-003 | FUS-005 | 一项 confidence 很低 | 最终 confidence 不高于该项 |
| T-FUS-004 | FUS-003 | Baseline、三动作 Q、不同 profile/sample/KL budget | 高 Q 动作单调增加；KL 不超预算；弱证据返回同一 baseline；调整结果标记 HEURISTIC |
| T-FUS-005 | FUS-002/003 | Routed baseline→DecisionFusion→Advice/Orchestrator | 无画像保持唯一 baseline；可信画像生成 HEURISTIC Advice；弱画像保持 Exact；无策略仍为 equity-only/ABSTAIN |
| T-ADV-001 | ADV-001 | READY Advice | 来源、版本、actions、expiry 全部必填 |
| T-ADV-002 | ADV-002 | Fake clock 越过 expiry | READY 转 STALE，动作不再展示 |
| T-ADV-003 | ADV-003 | 完整链、缺 input/range/provider、顺序变化、state/provider 变化 | 完整链四阶段齐全且 digest 稳定；断链具名并把 READY confidence 限制到 0.49；schema v1 向后兼容 |
| T-TRN-001 | TRN-001/002 | 多决策整手、乱序 actual、完整/缺失 EV、missing/orphan/duplicate/cross-hand | 精确 identity 配对；已知 EV 可复算；完整度和最大漏损点正确；未知动作/EV 不推断 |
| T-SER-001 | SER-001 | 所有 Advice status round-trip | 序列化前后相等 |

### 8.2 集成与端到端测试

| Test ID | 链路 | 场景 | 通过条件 |
|---|---|---|---|
| T-INT-001 | State→Context→HU Adapter→Advice | FX-HU-PF-ROOT-AA | READY；与固定蓝图一致；来源/版本完整 |
| T-INT-002 | Vision provenance→Context→UI | Hero cards 自动、其他字段人工 | UI 明确显示不同来源 |
| T-INT-003 | Router→Equity-only→Advice | 无适用策略但 equity 输入完整 | PARTIAL；不出现 GTO 动作频率 |
| T-INT-004 | 3–9 人 context→Router | FX-MP-PF-{3..9}-ROOT，只有 HU Provider | 每个场景均 ABSTAIN/unsupported_player_count |
| T-INT-005 | Fast Advice→Slow refinement | HU river cache `NOT_FOUND` | Fast 不等待；同版本 slow 可更新 |
| T-INT-006 | Fast Advice→State update→Slow result | FX-HU-RIVER-STALE | 旧结果丢弃，UI 无闪回 |
| T-INT-007 | Multiway ranges→Equity→Advice | FX-3W-FLOP、FX-4W-FLOP | 3-way/4-way equity；无对应 Provider 时 PARTIAL |
| T-INT-008 | Full hand replay→Debrief | 固定 action/EV fixture | 实际动作绑定正确 Advice；EV loss 可复算 |
| T-INT-009 | WebSocket reconnect | 最新 Advice + 已过期 Advice | 只恢复当前有效状态，不恢复 stale 动作 |
| T-INT-010 | Process failure | Resolver crash/timeout | 主进程正常；Fast Advice 保留；错误可观测 |
| T-INT-011 | 3–9 人 Context→对应 Provider→Advice | FX-MP-PF-{3..9}-ROOT | 每个人数均命中对应 Provider；来源、人数和版本一致 |
| T-INT-012 | 6/9 人 unopened→Heuristic Provider→Router | 显式位置/100BB/no-ante/no-rake | HIT_APPROXIMATE；来源/hash/限制完整；并存 Exact 时选择 Exact |

### 8.3 性能测试

| Metric ID | 起点 → 终点 | 数据集 | 目标/报告方式 |
|---|---|---|---|
| P-001 | Stable state → DecisionContext | 分层 fixtures | p50/p95/p99，目标 p95≤10ms |
| P-002 | Context → preflop lookup | 冷/热 cache | 分开报告；热查询目标 p95≤10ms |
| P-003 | Context → equity | preflop/flop/turn/river、HU/multiway | 按方法和 trials 分层 |
| P-004 | Context → first Advice | 真实 Fast Path | p95≤300ms |
| P-005 | Frame → stable state | 真实 capture + temporal consensus | 单独报告，不计入纯计算延迟 |
| P-006 | Slow resolver | River/turn/flop | 收敛时间、超时率、误差，不设统一假目标 |
| P-007 | UI transport/render | WebSocket→paint | p50/p95/p99，目标 p95≤25ms |
| P-008 | Memory/cache | 长 session、多 provider assets | 峰值 RSS、cache hit、eviction、包体积 |

### 8.4 故障注入与稳健性测试

| Test ID | 故障 | 预期行为 |
|---|---|---|
| T-FAIL-001 | 策略资产 hash 不匹配 | Provider unavailable；明确 asset-integrity error |
| T-FAIL-002 | Provider schema/version 不支持 | 启动或加载失败，不读旧格式 |
| T-FAIL-003 | Equity trials 超时 | 返回 PARTIAL/低 numerical confidence，不阻塞 UI |
| T-FAIL-004 | Resolver 子进程崩溃 | Fast Path 不受影响；错误计数和日志可追踪 |
| T-FAIL-005 | Observation confidence 抖动 | Temporal/quality gate 阻断 Advice 频繁闪烁 |
| T-FAIL-006 | Action event 漏帧 | State ambiguity；不得自行补造唯一行动线 |
| T-FAIL-007 | Window 切换到同标题另一桌 | Window identity mismatch；停止当前 Advice |
| T-FAIL-008 | Profile 数据损坏 | 回退 population prior，不影响 canonical state |
| T-FAIL-009 | Cache 中旧 solver 版本 | Cache `NOT_FOUND`/rebuild，不返回旧 candidate |
| T-FAIL-010 | 系统时间跳变 | 使用 monotonic deadline 判断运行时过期 |

## 9. 分阶段验收门槛

| 阶段 | 必须实现的功能 ID | 必须通过的测试 | 可对外声明 |
|---|---|---|---|
| S1 通用策略骨架 | CTX-001~004、PRV-001、RTR-001/002/007、ADV-001/002、SER-001 | T-CTX、T-PRV、T-RTR-001/004、T-ADV、T-SER | 有多人兼容 Strategy API，无真实策略声明 |
| S2 HU Preflop Demo | PRV-002、RTR-003/005、FUS-001/004、UI-001/002 | T-PRV-002、T-INT-001/002、P-002/004 | 授权 HU preflop、限定 blueprint 版本的实时建议 |
| S3 自动 HU Preflop | ST-004~006、MET-001/004、完整 provenance | Replay、T-ST、T-INT-001，真实识别数据门槛 | HU preflop 自动输入建议 |
| S4 HU Postflop Math | MET-002/003、RNG-001~003、EQ-002~004、EV-001 | T-RNG、T-EQ、T-EV-001、T-INT-003 | HU range equity/pot odds；不自动声称 GTO |
| S5 3–9 人 Preflop | PRV-003、多人位置/行动状态 | FX-MP-PF-{3..9} goldens、T-RTR-001/005、T-INT-004/011 | 仅对逐个人数、位置和行动线均已验证的 preflop 场景给建议 |
| S6 Multiway Math | ST-007、RNG-005、EQ-005 | T-ST-005、T-RNG-004、T-EQ-004、T-INT-007 | 已验证场景的 multiway equity/side pots |
| S7 Postflop Strategy | PRV-005、EV-002/003、FUS-002/003（PRV-006 的 preflop heuristic 已独立完成） | Provider goldens、T-EV-002、T-FUS、P-004 | 限定 abstraction 的策略和 EV；现有 RFI heuristic 不代表 postflop 能力 |
| S8 Slow Resolver | PRV-007、RTR-006~008 | T-INT-005/006/010、P-006、T-FAIL-004 | 异步局部精算，不保证每次实时返回 |
| S9 Training Loop | TRN-001/002 | T-INT-008 + live/debrief parity | 有可信 counterfactual EV 的局后训练 |

任何阶段只能声明通过能力矩阵覆盖的场景。通过 HU 测试不能声明支持 6-max；通过 Equity 测试不能声明支持 Strategy；通过启发式模型测试不能声明 exact GTO。

## 10. 需求—功能—测试—输出追踪表

| 需求 | 功能实现 | 最低测试证据 | 用户可见输出 |
|---|---|---|---|
| 不使用错误玩家人数策略 | PRV-001、RTR-002 | T-RTR-001、T-INT-004 | ABSTAIN/unsupported_player_count |
| 3–9 人策略按人数精确路由 | PRV-003、RTR-002/003 | T-RTR-005、T-INT-011 | 对应人数的 frequencies/source/version |
| 输入不足时拒答 | CTX-003、FUS-004 | T-CTX-002、T-FUS-002 | missing inputs + ABSTAIN |
| 可信 HU preflop 建议 | PRV-002、RTR-003、ADV-001 | T-PRV-002、T-INT-001 | Frequencies/source/version |
| 区分 Equity 与 Strategy | EQ-*、RTR-005、ADV-001 | T-INT-003 | PARTIAL/equity_only |
| 多人 Equity 正确 | RNG-005、EQ-005、ST-007 | T-RNG-004、T-EQ-004、T-ST-005 | Multiway pot share/pots |
| 旧结果不污染新状态 | RTR-007、ADV-002、UI-003 | T-RTR-004、T-INT-006 | 保持当前 Advice，旧结果不显示 |
| 近似匹配透明 | RTR-004、UI-002 | T-RTR-003 | Match score + differing dimensions |
| 可审计建议 | ADV-003、SER-001 | T-ADV-001/003、T-SER-001 | Chain ID、完整度、missing evidence、source/assumptions |
| 实时首答 | RTR-005、UI-003 | P-001~004、P-007 | Stable-state 后 p95≤300ms |
| 可信 EV loss | TRN-002、EV-003 | T-INT-008 | 仅在 counterfactual EV 完整时显示 |

## 11. 当前代码到目标功能的映射

| 当前实现 | 可复用内容 | 目标改动 |
|---|---|---|
| `core/state.py` | Immutable PokerState、version、cards、players、pot | 扩展 commitments、pots、规则配置或增加 v2 对象 |
| `state_engine/engine.py` | 纯 transition、确定性更新 | 增加 actor/action/betting legality/side pots |
| `orchestrator/app.py` | State 与 Hand Memory 编排 | 增加 Context、Strategy 调度和 stale filter |
| `memory/hand_memory.py` | 状态/事件历史和 active hand | 增加 Advice/actual-action 关联或独立训练存储 |
| `equity/*` | Evaluator、exact、MC、range、pot odds | Adaptive budget、CI、multiway joint ranges/cache |
| `core/request_context.py` | Hand/version/request 绑定 | 增加 deadline/monotonic expiry 或配套 runtime metadata |
| `core/reports.py` | Equity/Strategy/Decision 基础契约 | 迁移到新的 MathReport/StrategyCandidate/Advice，不破坏旧序列化 |
| `realtime/pipeline.py` | Material-change 驱动、连续 Hero 确认 | 通用 temporal consensus、Fast/Slow strategy path |
| `desktop/serialize.py` + `ui/` | WebSocket payload 和现有 equity UI | Advice 状态、频率、来源、假设和过期更新 |

## 12. 建议的首个实现切片

首个代码切片应验证通用接口，而不是立即实现整套 Solver：

```text
DecisionContext（多人兼容）
→ StrategyProvider Protocol + Capability
→ FakeProvider（确定性测试）
→ StrategyRouter
→ Advice + serialization
→ UI 显示 READY/PARTIAL/ABSTAIN/STALE
```

第二个切片再接入真实 HU Preflop Blueprint Adapter。这样可以先证明输入、路由、输出、拒答和过期保护正确，再把外部策略资产引入打包链路。
