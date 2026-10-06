# PokerSense 产品需求文档

> 状态：目标需求基线
> 更新日期：2026-08-23
> 适用场景：授权自建牌局、朋友对练和教学演示

## 1. 产品目标与边界

PokerSense 将可见牌桌画面转换为可信、版本化的牌局状态，并在输入充分且策略源适用时，向真人玩家提供实时、可解释、可拒答的训练建议。

系统不是自动扑克机器人：

- 不点击、输入、下注或控制扑克客户端。
- 不读取客户端内存，不注入客户端，不拦截网络协议。
- 真人玩家始终是唯一执行者。
- 关键输入不足、冲突或没有适用策略时，必须输出 `ABSTAIN`，不得猜测。

当前发布能力仍是 WePoker H5 2-max Hero 底牌识别和翻牌前随机范围胜率。本文描述目标需求，不表示这些能力已经实现。

## 2. 核心目标：Multi-Scenario / Multi-Player Strategy System

PokerSense 的最终策略系统不得被设计成只能处理 Heads-Up。Heads-Up Preflop Blueprint 只允许作为第一个可验证 Strategy Provider 和 Demo，不是最终产品边界。

目标系统必须根据玩家人数、位置、筹码深度、牌局配置、行动历史和街道选择适用策略源，并明确区分精确命中、近似匹配、启发式结果、仅 Equity 和拒答。

```text
可信牌桌状态
  + 玩家人数与座位
  + 位置
  + 筹码和牌局配置
  + 完整行动历史
  + Hero / Villain ranges
  → Strategy Router
  → 适用的 HU / multi-player / preflop / postflop Provider
  → 版本化 Advice
```

### 2.1 可验收的系统需求

下表是实现、评审和回归测试使用的需求主索引。`P0` 是形成安全闭环的必要能力；`P1` 是策略质量和多人覆盖；`P2` 是增强能力。

| Requirement ID | 优先级 | 系统必须做到 | 可观察验收结果 |
|---|---:|---|---|
| `REQ-IN-001` | P0 | 接收并区分观察、配置、人工输入和推断值 | 每个输入均有 value、quality、provenance 和 timestamp/version |
| `REQ-IN-002` | P0 | 对关键字段执行多帧确认、冲突检测和置信度门控 | 不稳定值不进入权威状态，输出 UNKNOWN/CONFLICT；真实 raw-frame Replay 可生成机器可读质量报告 |
| `REQ-ST-001` | P0 | 从稳定输入维护不可变、版本化、筹码守恒的牌局状态 | 相同输入可重放得到相同 state/events；非法变更不覆盖旧状态 |
| `REQ-ST-002` | P0 | 支持 2–9 个座位、动态 active players、合法行动和主/边池 | 参数化状态测试覆盖 2–9 人和 all-in/side-pot |
| `REQ-CTX-001` | P0 | 构建与 hand/state/request 绑定的多人 `DecisionContext` | 缺失字段、来源、假设和 deadline 可机器读取 |
| `REQ-MET-001` | P0 | 计算 legal actions、to-call、effective stack、SPR 和 pot odds | 与独立手算/枚举结果在规定容差内一致 |
| `REQ-RNG-001` | P1 | 按人数、位置和行动历史维护每名对手的范围 | Blocker、组合冲突和范围版本可验证，不把推断当事实 |
| `REQ-EQ-001` | P0 | 计算 HU 和 multiway equity/pot share，并报告方法和数值质量 | Exact 小场景一致；MC 可重放并满足统计容差 |
| `REQ-PRV-001` | P0 | Provider 声明人数、street、stack、rake、action tree 和版本能力 | 不匹配 Provider 永不进入候选集合 |
| `REQ-RTR-001` | P0 | 按当前上下文选择 exact、approximate、model、resolver 或 equity-only | 路由结果、查找状态和降级路径可追踪 |
| `REQ-FUS-001` | P0 | 只融合合法、未过期、来源一致的候选结果 | 非法动作概率为零；旧 request 结果被丢弃 |
| `REQ-OUT-001` | P0 | 只通过版本化 `Advice` 向 UI 输出策略 | READY/PARTIAL/ABSTAIN/STALE 字段契约稳定 |
| `REQ-OUT-002` | P0 | 明确区分 Strategy、Equity、近似、假设和拒答 | Equity-only 不显示 GTO 频率；拒答给机器码和用户说明 |
| `REQ-UI-001` | P0 | 实时展示动作频率、尺度、数学信息、来源、置信度和限制 | 状态变化或过期后旧动作立即隐藏且不闪回 |
| `REQ-PERF-001` | P1 | 稳定状态到首个 Fast Advice 的 p95 不超过 300ms | 固定性能数据集报告 p50/p95/p99，感知稳定时间单列 |
| `REQ-AUD-001` | P0 | Advice 可追溯到 observation、state、ranges 和 provider asset | 任一证据断链时不得输出高置信 READY |
| `REQ-TRN-001` | P2 | 将实际动作与当时 Advice 绑定并生成可信局后训练信息 | 无完整 counterfactual EV 时不显示 EV loss |

### 2.2 统一处理和输出规则

每次决策必须经过同一条管线，任何模块不得绕过质量门直接向 UI 输出：

```text
Observed/Input Values
→ Temporal + Confidence Gate
→ Canonical State and Events
→ DecisionContext + Derived Metrics + Ranges
→ Provider Capability Filter + Equity/Strategy Execution
→ Legality/Stale/Rejection Gate
→ Advice
→ UI
```

系统允许“少输出”，不允许“伪造完整输出”：

| 条件 | 唯一允许的结果 |
|---|---|
| 输入完整、状态可信、策略精确适用 | `READY/exact` |
| 输入完整、近似边界明确且在阈值内 | `READY` 或 `PARTIAL/approximate`，必须列出差异 |
| 无适用策略，但 Equity 输入充分 | `PARTIAL/equity_only` |
| 关键输入缺失、冲突、行动线歧义或人数不支持 | `ABSTAIN` |
| hand/state/request 已变化或 Advice 到期 | `STALE`，不得显示动作建议 |

### 2.3 策略、识别与 UI 的协作边界

当前开发分成两个并行工作流：本仓库的策略/状态工作流，以及伙伴负责的 WPK
识别和 UI 工作流。模块完成不能只以各自单元测试判断；只有下表的生产接口、真实
Replay 和 UI 验收同时完成，才算产品端到端闭环。

| 工作流 | 当前已经提供 | 仍由该工作流完成 | 交给下游的稳定边界 | 完成证据 |
|---|---|---|---|---|
| 策略与状态（本分支） | 2–9 人状态、事件、Context、Equity、Provider/Router、Fast/Slow、Advice、拒答和训练合同；live 已按 occupancy 选择实际桌型并传入 canonical history | 注册获准 Provider；把逐尺度频率加入 UI wire contract；补齐真实输入后的生产编排 | `RawObservation → PokerState/StateEvent[] → DecisionContext → DesktopFrame(advice)` | 策略回归、Provider Golden、真实 WPK E2E、版本化性能报告 |
| WPK 识别（伙伴工作流） | Android hero/board/street/pot、8 槽 occupancy/stack/dealer/action、Hero 当前 actor、版本化 mapping 和守恒动作重建 | 补授权 raw Replay、对手当前 actor、all-in/side-pot/漏帧多动作边界；不得直接推导策略 | 每帧一个类型正确的 `RawObservation`；视觉 slot 只用 `slot_id`，由版本化 `PlatformSeatMapping` 映射到 seat | 授权 raw-frame Replay、逐字段 precision/recall、动画/漏帧/换手用例、layout/calibration hash |
| Live Coach UI（伙伴工作流） | 当前页面可消费 `DesktopFrame` 和基础 Advice view | 原子消费 analysis+Advice；只在 READY 展示动作；显示频率、尺度、EV 可用性、来源、版本、match、confidence、assumptions、evidence 和拒答原因；状态变化/过期立即隐藏旧动作 | WebSocket `DesktopFrame` JSON；不得从 Equity 自行生成动作，不得在前端重新解释策略 | READY/ABSTAIN/PARTIAL/STALE snapshot、Fast→Slow 顺序测试、过期/换手无闪回、真实窗口视觉验收 |
| 联调（共同） | Synthetic/Mock 合同和无 OpenCV 测试已经存在 | 固定同一 WPK layout、calibration、Replay、Provider 和 UI build，跑通画面到建议；保存每层 identity 和时间戳 | `frame_seq + hand_id + state_version + request_id` 全链一致 | R6 报告、录屏/截图、机器可读输出、干净安装和权限记录 |

识别工作流必须交付以下最小输入矩阵。`value=None` 时仍必须产生字段，并明确标记
`UNKNOWN/LOW_CONFIDENCE/CONFLICT`，不得省略或用上一次值填充。

| 输入域 | 必需输出 | 类型/语义 | 策略侧使用方式 | 当前 Gap |
|---|---|---|---|---|
| 帧与布局 | `frame_seq`、带时区 timestamp、window/layout identity | 单调帧号；窗口和布局版本可追溯 | temporal gap、Replay、mapping 选择 | layout identity 尚未进入完整 live 证据链 |
| Hero/board | `hero_cards`、`board_cards` | `ObservationField[tuple[Card,...]]` | blocker、street/state、Equity | Android Hero/board 已真实标定；发布级 raw Replay 待补 |
| 街道与底池 | `street`、`pot` | `ObservationField[Street/ChipAmount]` | hand/street transition、pot odds、SPR | Android street/pot 已标定；发布级 raw Replay 待补 |
| 座位与位置 | `slot_occupancies[]`、`dealer_pos` visual slot | 2–9 座位；视觉 slot 必须经版本化 mapping | 位置、行动顺序、player count | Android occupancy 272/272 稳定槽位正确；8 槽 mapping 已接入，授权 raw Replay 待补 |
| 筹码 | `slot_stacks[]` | 每个 visual slot 的 `ChipAmount` | effective stack、to-call、事件金额和边池 | Android 8 槽 OCR 已标定并映射为 seat stack；遮挡/空座拒识 |
| 行动 | `actor`、`slot_actions[]`、筹码/底池差额 | Android actor 表示当前轮到 Hero；完成动作 actor 来自 glyph slot；动作使用规范枚举 | 重建 fold/check/call/bet/raise/all-in 和 canonical history | Hero actor 33/33 且其余 201 帧拒识；glyph 已标定并去重，金额仅在 stack/pot 守恒时写入；对手当前 actor 与边界 Replay 待补 |
| 字段质量 | confidence、source、evidence、timestamp、validation status | 每个字段独立，不使用单一总置信度代替 | provenance、硬拒答门、审计 | 需要真实阈值和冲突样本 |

UI 工作流必须遵守以下显示矩阵；这是安全边界，不是样式建议。

| Advice 状态 | 动作/尺度 | Equity | 来源与限制 | 必须行为 |
|---|---|---|---|---|
| `READY` | 显示，并按概率排序；逐尺度频率只有 wire contract 提供后才显示 | 可显示 | 显示 source/version、match、confidence、assumptions/evidence | hand/state/request 必须与同一帧一致 |
| `PARTIAL` | 隐藏策略动作 | 只显示明确可用部分 | 显示 missing inputs 和降级原因 | 不得把 equity-only 包装成策略 |
| `ABSTAIN` | 隐藏 | 可用时单独显示 | 显示 gate/rejection reasons | 不保留上一帧 READY 动作 |
| `STALE` | 隐藏 | 可显示当前帧自身数据 | 显示过期或 identity mismatch | 旧 Slow 结果不得闪回 |

当前最关键的跨工作流 Gap 是：Router 尚未注册可发布且与实际人数匹配的策略 Provider；Android
识别/映射链仍需授权 raw-frame Replay 覆盖对手当前 actor、all-in/side-pot 和漏帧多动作；UI wire
contract 目前只输出动作总频率和尺度列表，尚未输出每个尺度各自的频率。这些分别由策略、识别验收和
策略输出合同负责，不能把其中任何一项作为 UI 层猜测逻辑实现。

伙伴的可执行任务顺序、源码入口、字段示例和提交前清单见
[`recognition-ui-handoff.md`](recognition-ui-handoff.md)。

## 3. 场景覆盖要求

### 3.1 玩家人数

领域模型、`DecisionContext`、策略路由和 Advice 契约必须支持可配置的 2–9 个座位，不得在公共接口中硬编码两名玩家。

| 场景 | 交付定位 | 说明 |
|---|---|---|
| 2-max / Heads-Up | 第一阶段 | 当前 WePoker H5 标定和首个策略 Demo |
| 3–5 人 / short-handed | 多人能力范围 | 每个实际人数分别验证位置、范围、行动历史和策略源 |
| 6-max | 首批多人策略资产优先级 | 常见 UTG/HJ/CO/BTN/SB/BB；不是系统多人上限 |
| 7–9 人 / full-ring | 多人能力范围 | 每个实际人数分别验证完整位置序列和更紧的前位范围 |
| 临时少人状态 | 必须建模 | 空座、离桌、sit-out、已弃牌和 all-in 后人数变化 |

未配置相应策略源时，系统仍可维护牌局状态和计算可支持的数值，但不得将 Heads-Up 策略用于多人场景。

### 3.2 位置

系统必须根据 dealer button、座位占用和玩家人数推导规范位置，包括：

```text
BTN / Dealer
SB
BB
UTG
UTG+1
HJ
CO
```

要求：

- 保留 `seat_id` 与规范位置的映射。
- 位置随新手牌重新计算。
- Heads-Up 中正确处理 BTN 同时为 SB 的特例。
- 空座、sit-out 和中途离桌不得破坏位置计算。
- 位置无法唯一确定时，依赖位置的策略必须 `ABSTAIN`。

### 3.3 Preflop 行动线

至少需要表达：

```text
unopened pot
limped pot
single-raised pot
3-bet pot
4-bet pot
5-bet / all-in
squeeze
iso-raise
multi-limp
```

行动历史必须记录：

- Actor seat 和规范位置。
- Fold/check/call/bet/raise/all-in。
- 原始金额、增量金额和以 BB 表示的规范尺度。
- 每街投入、整手投入、当前最大下注和需要跟注金额。
- 事件顺序、时间戳、来源证据和状态版本。

系统不能只根据最终底池大小猜测唯一行动线；存在多个合法解释时必须保留歧义，并阻断依赖该行动线的策略。

### 3.4 Postflop 场景

目标支持：

```text
single-raised / 3-bet / 4-bet / limped pot
heads-up / multiway pot
in-position / out-of-position
flop / turn / river
check-through / c-bet / donk / probe / delayed c-bet
bet / raise / re-raise / all-in
```

多人 postflop 不能退化为多个独立 Heads-Up 计算，必须显式考虑：

- 多个 Villain range。
- Card removal 和组合冲突。
- 多人 Equity / pot share。
- 主池和边池。
- 不同玩家的有效筹码。
- 行动顺序和已经 all-in 的玩家。

### 3.5 筹码与牌局配置

目标至少覆盖常见有效筹码深度，并允许 Provider 声明自身支持的 bucket：

```text
10 / 20 / 30 / 40 / 60 / 80 / 100 / 150 / 200 BB
```

决策上下文还必须包含：

- Small blind / big blind。
- Ante 或 no-ante。
- Cash / tournament 配置。
- Rake 及 cap（策略源依赖时）。
- 每名玩家的起始筹码、剩余筹码和有效筹码关系。
- 允许的 bet/raise sizes。

策略源不支持当前筹码、rake、ante 或尺度树时，必须返回不支持或近似匹配，不能假装精确命中。

## 4. 输入端需求

### 4.1 牌桌级输入

- 游戏类型和牌桌配置。
- 目标窗口身份、窗口尺寸、DPI、帧序号和时间戳。
- 座位数量、座位坐标和 dealer button。
- Blinds、ante、rake 配置。
- 当前 street、board 和 pot。

### 4.2 玩家级输入

每个座位至少需要：

```text
seat_id
occupied / empty / sit-out
is_hero
player_identity（可选、带置信度）
stack
street_committed
hand_committed
folded
all_in
current_actor
last_observed_action
```

### 4.3 识别质量与来源

每个输入字段必须携带：

- 候选值。
- Raw score / calibrated confidence。
- `VALID / UNKNOWN / LOW_CONFIDENCE / CONFLICT` 状态。
- Observation timestamp 和 frame sequence。
- ROI、模板或识别器证据引用。
- 来源：视觉识别、用户输入、平台配置或推断。

人工输入可以用于 Demo，但 UI 和 Advice 必须明确标记，不能显示为自动识别结果。

### 4.4 测量矩阵

感知识别必须按场景分层测量，而不是只报告一个总体准确率：

| 维度 | 示例 |
|---|---|
| 玩家人数 | 2、3、4、5、6、7、8、9 人分别统计 |
| 位置 | UTG/HJ/CO/BTN/SB/BB |
| 街道 | preflop/flop/turn/river |
| 底池 | unopened/limped/SRP/3-bet/4-bet/multiway |
| 筹码状态 | normal/short/deep/all-in/side pot |
| 客户端状态 | 发牌动画、结果覆盖层、断线、窗口遮挡 |
| 显示环境 | DPI、分辨率、缩放、主题、牌面皮肤 |

每个关键字段至少报告：

```text
accuracy
coverage
unknown rate
false-positive rate
conflict rate
temporal confirmation latency
Wilson lower bound
```

## 5. 权威状态需求

State/Event Engine 必须维持不可变、版本化的 canonical state，并验证：

- 合法行动顺序和 actor 轮转。
- 最小下注和最小加注。
- Pot、stack 和 committed amount 的筹码守恒。
- Fold、all-in、street transition 和 hand boundary。
- 主池和边池。
- 重复帧、漏帧、回退值和冲突观察。

State Engine 保持纯函数，不访问 Vision、数据库、Strategy Provider、Solver、LLM 或 UI。Hand Memory 的写入由 Application Orchestrator 负责。

## 6. 通用 DecisionContext

公共决策接口不得使用只适合 Heads-Up 的字段结构。目标契约至少包含：

```python
@dataclass(frozen=True)
class DecisionContext:
    hand_id: str
    state_version: int
    request_id: str
    game_config: GameConfig
    seats: tuple[DecisionSeat, ...]
    hero_seat: int
    actor_seat: int
    active_seats: tuple[int, ...]
    board_cards: tuple[Card, ...]
    street: Street
    pots: tuple[PotState, ...]
    legal_actions: tuple[LegalAction, ...]
    action_history: tuple[StateEvent, ...]
    effective_stacks: tuple[EffectiveStack, ...]
    hero_range: RangeDistribution
    villain_ranges: tuple[RangeDistribution, ...]
    input_quality: ContextQuality
    input_provenance: tuple[InputProvenance, ...]
    missing_fields: tuple[str, ...]
```

Provider 可以只支持该上下文的子集，但必须通过 capability 声明和适用性检查选择，不能要求上游退化成 Heads-Up 模型。

## 7. Strategy Router 与 Provider 需求

### 7.1 Provider 能力声明

每个 Strategy Provider 必须声明：

```text
supported_game_types
supported_player_counts
supported_streets
supported_positions
supported_stack_buckets
supported_ante/rake
supported_action_histories
supported_bet_sizes
exact / interpolated / heuristic
source_version
```

### 7.2 路由层级

目标路由可以包含：

```text
Legality / Safety Gate
HU Preflop Blueprint
3–9 人 Preflop Providers（按实际人数声明 capability）
Canonical Postflop Presolved Cache
3-way / 4-way+ Postflop Providers
Lightweight Policy / Value Model
Local Solver / CFR Resolver
Equity-only Service
ABSTAIN
```

当前目标层代码已有一个严格受限的 6/9 人 PreflopR RFI Heuristic Provider：只覆盖
100BB、no-ante/no-rake、unopened 的显式位置牌表，输出 raise/fold 且不提供 size/EV。
它用于回退和链路验证，不满足 3–9 人精确策略要求，也不改变当前发布版桌面能力。

目标层还提供一个可选的本地 GTOpen Preflop Adapter：通过 loopback JSON API 把 2–9 人
位置、等起始筹码、blind/ante/rake、行动历史和尺度树转换为 GTOpen session，并按 Hero
具体 169 手牌类读取逐尺度频率。它必须在 Slow Path 串行运行，保存 iteration、model gap、
tree size、realization 和固定上游 revision 证据；多人结果固定标记 `HEURISTIC`，并披露
product-equity/realization model、非唯一多人均衡和服务 revision 未远程证明等假设。上游许可、
独立 Golden 或输入映射不完整时，该 Adapter 只用于本地研究，不得注册为发布能力或打包资产。

规则：

- HU Provider 不得匹配 `player_count > 2`。
- Postflop HU Provider 不得匹配 multiway active pot。
- Equity-only 结果不得包装成 GTO 策略。
- 近似匹配必须输出匹配维度、距离和 `state_match_score`。
- Resolver 超时、未收敛或结果过期时必须丢弃。
- GTOpen 的单 preflop session 必须串行访问；超时应尽力停止上游 solve。
- GTOpen v1 遇到不等起始筹码、非精确行动路径或非法返回动作时必须拒答。
- 所有结果必须绑定 `hand_id + state_version + request_id`。

### 7.3 范围需求

Range Tracker 属于推断层，不是权威牌局事实。每个范围必须携带：

```text
player/seat
combo weights
source and source version
updated_from_action
posterior entropy
effective sample size
confidence
```

范围更新必须移除与 Hero、board 和其他确定牌冲突的组合。多人范围计算必须处理不同玩家组合之间的 card collision。

## 8. 输出端需求

Advice 是系统唯一面向 UI 的策略输出，至少包括：

```text
hand_id / state_version / request_id
player_count / active_player_count
action probabilities
recommended sizes
per-action EV（策略源真实提供时）
EV gap
preferred action（可选）
strategy source and version
exact / interpolated / heuristic / equity-only
state_match_score
confidence
evidence and key factors
assumptions and missing inputs
READY / PARTIAL / ABSTAIN / STALE
expires_at
```

UI 必须明确区分：

- 精确预计算策略。
- 近似或插值策略。
- 启发式策略。
- 对手画像调整后的 exploitative 策略。
- 仅 Equity，无策略建议。
- 输入不足或无适用 Provider 的拒答。

## 9. 非功能需求

### 9.1 正确性与可审计性

- 每个 Advice 可追溯到 observation、canonical state、ranges 和 strategy source version。
- 非法动作概率必须为零，动作概率在容差内归一化。
- 多人 Equity 与可枚举小场景交叉验证。
- 固定策略版本建立按人数、位置和行动线分层的 golden spots。

### 9.2 实时性

性能指标必须分开测量：

```text
per-frame processing latency
temporal stabilization latency
stable-state-to-first-advice latency
slow-result refinement latency
end-to-end user-visible latency
```

Fast Advice 的目标仍为稳定状态形成后 p95 ≤ 300ms。多帧确认等待时间单独报告，不能隐藏在单帧处理预算中。

### 9.3 安全与拒答

- 关键输入冲突或未知时拒答。
- 不得使用不匹配玩家人数的策略。
- 不得把范围推断显示为已观察事实。
- 不得把 Monte Carlo Equity 显示为 GTO 动作频率。
- 不得让旧版本或超时结果覆盖当前 Advice。

## 10. 分阶段交付

### Phase 1：通用接口 + Heads-Up Demo

- `DecisionContext` 和 Provider capability 从第一天支持多人结构。
- 使用当前真实 Hero 底牌识别。
- Position、stack、ante 和 preflop action history 暂由用户明确输入。
- 接入 HU Preflop Blueprint，验证路由、Advice、版本和 UI。
- UI 标记人工输入和策略适用范围。

退出标准：HU Demo 可用，但代码中不存在把系统整体限定为两人的公共接口。

### Phase 2：自动化 Heads-Up 完整输入

- 识别 dealer button、位置、stack、blind、preflop action 和 bet size。
- 完成 Heads-Up preflop 全链路和可信拒答。
- 开始 board、pot 和 postflop action 标定。

### Phase 3：3–9 人 Preflop Strategy Framework

- 完成 3–9 人座位占用、位置和行动顺序的统一模型。
- Provider capability 必须按实际 `player_count` 声明，不允许用 6-max 资产代替其他人数。
- 以 6-max 作为首批多人策略数据集，但交付矩阵必须逐步覆盖 3、4、5、6、7、8、9 人。
- 接入有明确来源和版本、且人数匹配的 Preflop Provider。
- 覆盖 unopened、limp、raise、3-bet、4-bet 和 squeeze。
- 对每个宣称支持的人数，按位置和行动线建立独立 golden spots。

### Phase 4：Multiway State / Equity

- 完成多人 pot、all-in、main/side pot 和有效筹码模型。
- 支持多个 Villain ranges 和 multiway equity。
- 没有可靠 multiway strategy 时允许 Equity-only 或 `ABSTAIN`。

### Phase 5：Multi-Scenario Postflop Strategy

- 接入版本化 presolved cache 和适用的 Provider。
- 先从 river、标准尺度和有限人数场景开始。
- Turn/flop 或复杂 multiway 场景超出实时预算时进入异步或局后分析。

### Phase 6：多人覆盖补齐与扩展场景

- 补齐 Phase 3 尚未覆盖的 3–9 人位置、范围和策略数据；9-max 是其中之一。
- 支持锦标赛、ante、short-stack 和更多下注树配置。
- 按真实需求和独立验证结果扩大场景矩阵。

## 11. 验收原则

每个宣称支持的场景必须有明确的能力矩阵和证据：

```text
player_count
positions
street
pot type
stack bucket
action history
strategy source/version
sample or golden-test evidence
latency evidence
known limitations
```

“支持 Heads-Up”不能表述为“支持多人”；“可以计算 Equity”不能表述为“可以给出 GTO 建议”；“近似匹配”不能表述为“精确求解”。

识别后策略模块的功能 ID、输入输出矩阵和路由真值表见
[`strategy-requirements-matrix.md`](strategy-requirements-matrix.md)。自动化回归范围、数据集、运行层级和发布门槛见
[`strategy-regression-test-matrix.md`](strategy-regression-test-matrix.md)。
