# PokerSense 策略回归测试矩阵

> 状态：目标自动化测试与发布验收基线

当前开发分支的一次 commit-bound 功能和目标硬件性能执行结果见
[`test-report-2026-08-23.md`](archive/test-report-2026-08-23.md)。该报告不是 R6 发布验收替代品。
> 更新日期：2026-08-22
> 当前实现说明：本文件定义目标回归体系，不表示列出的测试均已实现

## 1. 目的与适用范围

本文件回答三个问题：

1. 功能完成后，怎样证明输入被正确处理并产生正确输出？
2. 修改状态、范围、Equity、Provider、Router、UI 任一模块后，需要重跑哪些测试？
3. 什么证据足以允许合并、打包或宣称支持一个新场景？

测试范围覆盖：

```text
StableObservation / Manual Input
→ State and Events
→ DecisionContext
→ Metrics / Ranges / Equity
→ Provider / Router / Fusion
→ Advice / Serialization / UI
```

图像识别模型本身的精度评测独立管理，但真实识别输出进入上述链路的 replay 和端到端测试属于本文件范围。

## 2. 测试原则

- 确定性优先：单元、状态重放、Provider Golden 和序列化测试必须可重复。
- 多人按实际人数验证：3、4、5、6、7、8、9 人分别测试，不能用 6-max 代表全部多人场景。
- 状态与策略分开验收：能够维护多人状态，不代表存在对应多人策略。
- Equity 与 Strategy 分开验收：计算出胜率，不代表能输出动作频率。
- 正向和拒答同等重要：每个 READY 场景至少有对应的 missing、conflict、unsupported 或 stale 场景。
- 旧结果零容忍：任何旧 hand/state/request 的结果都不能覆盖当前 Advice。
- Golden 数据版本化：策略资产、fixture schema、预期输出和容差变更必须经过评审。

## 3. 回归运行层级

| Suite | 触发时机 | 最大建议时长 | 内容 | 阻断条件 |
|---|---|---:|---|---|
| `R0 Contract` | 本地开发、每次提交 | 1 分钟 | 数据对象、枚举、序列化、reason codes、Provider capability | 任一失败阻断 |
| `R1 Core` | 每次提交、PR | 5 分钟 | State、rules、metrics、range blockers、exact equity、router/fusion | 任一失败阻断 |
| `R2 Integration` | PR、合并 main | 15 分钟 | State→Advice、Fast/Slow、cache、WebSocket、UI contract | 任一失败阻断 |
| `R3 Scenario` | PR、每日 | 30 分钟 | 2–9 人参数化、preflop/postflop、all-in/side-pot、拒答场景 | 声明能力内任一失败阻断 |
| `R4 Statistical` | 每日、算法变更 | 60 分钟 | Monte Carlo 收敛、CI 覆盖、range sampling、随机属性测试 | 超出统计门槛阻断 |
| `R5 Performance` | 每日、发布候选 | 环境固定 | p50/p95/p99、内存、cache、resolver budget | 超出已批准预算阻断发布 |
| `R6 Release E2E` | 发布候选 | 手工+自动 | 真实 capture replay、本地包、UI、权限/平台、干净安装记录 | 缺少目标平台证据阻断发布 |

目标测试标记：

```text
contract, core, integration, scenario, statistical, performance, release_e2e
```

建议命令契约；在测试实现后写入 CI：

```bash
pytest -q -m "contract or core"
pytest -q -m integration
pytest -q -m scenario
pytest -q -m statistical
pytest -q -m performance
pytest -q -m release_e2e
```

## 4. 标准测试数据契约

每个 fixture 都必须是自包含、不可变、可版本化的数据对象，至少包含：

```text
fixture_schema_version
fixture_id
requirements[] / function_ids[] / test_ids[]
game_config
hand_id / state_version / request_id
observations[] or canonical_state
seat map / dealt_player_count / active_player_count / positions
hero cards / board
stacks / commitments / main and side pots
actor / legal actions / action history
hero and villain ranges
input provenance / quality / assumptions
provider capability / provider version / asset hash
expected state / events / context
expected advice status / source / match kind
expected actions / math / reason codes
numeric and timing tolerances
```

fixture 分四类：

| 类型 | 数据来源 | 用途 | 是否允许手工填写策略频率 |
|---|---|---|---|
| `Synthetic` | 手工构造合法或非法状态 | 边界、属性、拒答和错误处理 | 只允许 FakeProvider 的确定性结果 |
| `Golden` | 固定版本 Provider/策略资产直接导出 | Adapter parity、动作频率和 EV | 不允许手工杜撰 |
| `Replay` | 经授权并脱敏的真实帧/观察/事件序列 | 感知到状态、动画、漏帧、换桌 | 不适用或引用固定 Provider |
| `Benchmark` | 固定规模和硬件条件的数据集 | 性能、统计和资源使用 | 不适用 |

所有 Golden fixture 必须记录生成工具版本和策略资产 hash；资产变化时不得静默覆盖旧预期结果。

### 4.1 已建立的 Mock 数据基线

目标架构的确定性 Mock 数据位于
[`../tests/fixtures/strategy/README.md`](../tests/fixtures/strategy/README.md)，由
[`../tools/generate_strategy_mock_fixtures.py`](../tools/generate_strategy_mock_fixtures.py)
生成。目前包含 297 条 Synthetic/Benchmark fixture，并由自动测试保证：

- 17 个 `REQ-*` 全部有 Mock 覆盖。
- 本文和需求矩阵中列出的 `T-*`、`E2E-*`、`P-*`、`PERF-*` 均至少关联一条 fixture。
- 2–9 人和九类 preflop 行动线逐项覆盖。
- Flop/turn/river 的 active player count 2–9 逐项覆盖。
- 所有关键输入字段分别覆盖 UNKNOWN、LOW_CONFIDENCE 和 CONFLICT。
- 23 条 `MOCK-PLATFORM-MAPPING-*` 覆盖 check/fold/bet/call/raise/all-in、
  slot 行动定位、no-op、缺失/冲突 actor、未映射 slot、dealer 冲突、多人筹码变化、
  缺 stack/pot、筹码不守恒、行动与换街/发牌混帧以及强制盲注拒绝。
- READY、PARTIAL、ABSTAIN 和 STALE 均有契约样例。
- 生成结果可重放，manifest 保存数量、覆盖摘要和 JSONL SHA-256。

运行方式：

```bash
python3 tools/generate_strategy_mock_fixtures.py --check
pytest -q tests/strategy/test_mock_fixture_dataset.py
```

Mock 数据只证明合同和处理逻辑；不能替代真实 Provider Golden、真实平台 Replay、目标硬件性能结果或干净安装验收。

### 4.2 已建立的真实 HU Provider Golden

`tests/fixtures/strategy/provider/hu_preflop_blueprint_golden.json` 不是手工策略频率。它由固定的
`amaster97/poker_solver` commit `f78f1b2bc338dd8cbb5226ecb8398bbdb3635676`
及其哈希校验分片直接查询，记录 package、license、manifest、asset 和 shard 版本证据。
当前覆盖 100BB/no-ante root 的全部 169 手牌类，以及 11 个跨 `c`、`b200/b300/b500`、
`b300r700/b300r900`、20/100BB 和 0/0.5/1BB ante 的节点，共 180 次 lookup。
Adapter 测试还验证 `c`、`b/r`、`A` token、任意绝对盲注到 BB 的 ante/金额标准化、
真实 stack×ante pair capability、逐尺度频率保留、1e-26 精确概率分配和非法尺度重归一化。

常规 CI 以该 Golden 驱动 Adapter、Router 和 Advice 的确定性 parity 测试；显式上游审计使用：

```bash
PYTHONPATH=src:<upstream-checkout> python \
  tools/verify_hu_blueprint_golden.py <upstream-checkout>
```

当前 Golden 证明完整 169-class root 和列出的 11 个 HU preflop 节点，但不等于枚举了
27 个分片的完整动作树。它也不证明多人策略、postflop 策略、目标硬件延迟或上游
exploitability。

### 4.3 已建立的 6/9 人 RFI Heuristic 资产审计

`preflopr-explicit-rfi-ranges.json` 由固定的 `bmorrow10/preflopR` commit
`aed511d0451aea33a14f7e9204595fc2211f233f` 生成。资产 v2 复制上游源码明确写出的
6/9 人 unopened 牌表；7/8 人通过解析上游 `get_positions()` 的位置表，逐位置映射到
**同名** 9 人键（`7_UTG → 9_UTG`），BB 仍排除；上游的 `9_BTN` last-resort 兜底被显式
禁用并由加载时校验钉死（指向非同名键会直接 `ValueError`）。生成/校验命令：

```bash
python tools/import_preflopr_open_ranges.py \
  <preflopR-checkout>/preflopR.r \
  src/poker_engine/strategy/assets/preflopr-explicit-rfi-ranges.json \
  --revision aed511d0451aea33a14f7e9204595fc2211f233f --check
```

`test_heuristic_provider.py` 遍历 13 个显式位置牌表 + 13 个派生位置牌表的全部 169 手牌类别，并验证能力边界、来源/hash/限制、资产损坏、无 size/EV、Exact 优先、所有禁止 fallback，以及 derived 指向必须同名。7/8 人派生建议 confidence=0.3，evidence 标注
`derived_range:{7|8}_X<-9_X:{hand}`，assumptions 增补「tighter than true table size」声明。
该证据只支持 `PRV-006` 的 heuristic fallback，不支持 `PRV-003` 的 3–9 人精确策略。

### 4.4 当前可执行的策略核心覆盖

`tests/strategy/` 当前已实现合同、Router、Advice、Mock 执行以及状态派生测试。其中
`test_orchestration.py` 使用可控 Future 和真实线程池适配验证 Fast 不等待、同版本升级、
pending 不闪回、旧 state/request 取消、deadline/candidate expiry、resolver 异常隔离、
provider identity、capability 和“Slow 必须更优”门槛。
`test_local_resolver.py` 通过真实本地子进程验证无 shell JSON 协议、成功 candidate/EV/尺度、
配置 timeout 与 request deadline、输出上限、退出码、坏 JSON、身份/版本/概率错误、
no-strategy/not-converged、exploitability 门槛，并经 ThreadedSlowResolver 完成 Advice 升级。
`test_gtopen_provider.py` 验证 loopback-only/fixed-revision 配置、3 人位置和 blind 映射、
Hero 169-class index、精确 actor/kind/raise-to 路径、多个 raise size 聚合、等起始筹码限制、
model-gap 门、transport/非法动作/timeout fail-closed、best-effort stop，以及
ThreadedSlowResolver→READY Advice。真实上游 E2E 还必须固定 checkout revision，记录 CPU-only
build/test、树节点/内存、iteration/gap 和返回尺度；这些结果只算本地模型 Adapter 证据，不算
许可策略资产 Golden。
`test_training.py` 验证实际动作必须绑定同一 Advice identity、动作/尺度偏差、EV 完整与缺失门、
非 READY 不做策略评判，以及中英文确定性解释 snapshot。
`test_hand_review.py` 验证整手多决策按 actual 时间排序和精确 state/request 配对、已知 EV
求和、最大漏损点、完整/partial 标志、动作/尺度偏差计数，以及 missing/orphan/duplicate/
same-state retry/cross-hand 均不做猜测性关联。
`test_ev.py` 验证 Call 即时 EV 的 Decimal 锚点、Bet/Raise 分支树、缺 continuation value
拒绝、分支概率守恒，以及只有全部合法动作 EV 完整时才计算 best/second gap。
`test_context_factory.py` 验证 provenance 唯一性、required-field 最低值聚合、全部质量状态和
一致性硬门，以及 Request ID 的 deadline、时区、重复重试/回滚和并发唯一性。
`test_input_provenance.py` 验证 Observation、人工、配置、派生和推断输入的自动来源标记，
同值多源共识、异值或显式冲突不被静默覆盖，null/低置信度、稳定 value digest、确定性字段顺序，
并通过 `DecisionContext` 质量门执行拒答；`MOCK-PROVENANCE-*` 8 组语料直接执行同一 collector。
`test_confidence.py` 验证 perception/state/match/range/numerical 具名因子取最小值、并列限制项、
非法值、显式缺失因子导致 ABSTAIN，以及 approximate match score 对 Advice confidence 的上限。
`test_exploit_fusion.py` 验证 Q 值指数倾斜受 sample/quality/weight/logit/KL 四重门控制，
KL 预算单调、零 baseline 支持保持、尺度条件频率保持、极端 Q 数值稳定，且弱证据或缺失 Q
时返回同一 baseline；任何已调整结果必须标为 HEURISTIC。
`test_fusion.py` 验证 Router 的单一 baseline 不被跨 abstraction 混合；无画像保持原候选，
可信画像经过同一融合链生成 HEURISTIC Advice，弱画像保持 Exact，无策略时保持 equity-only，
并验证 StrategyOrchestrator 的 Fast Advice 已实际使用该融合链。
`test_evidence.py` 验证 input→canonical state→逐 seat range→Provider 四阶段结构化引用、
顺序无关 SHA-256 chain ID、state/provider 变化敏感、动态 required input、缺 range/provider
具名结果、断链 confidence≤0.49、Advice round-trip 和旧 schema-v1 additive 兼容。
`test_strategy_cache.py` 验证 canonical context 等价、request/player identity 排除、行动 payload
纳入、Provider/version/asset/engine 逐维 miss、安全 Candidate 重绑定、TTL/STALE、LRU、并发和
Cache→Provider 查询次数。
`test_heuristic_provider.py` 验证固定 6/9 人 RFI 资产的 13×169 完整映射、Heuristic 标签、
来源和 hash、无虚构 size/EV、3–5/7–8 与 BB fail-closed，以及 Exact 路由优先级。
`test_advice_view.py` 验证 READY 动作按频率排序并携带尺度、EV、来源、匹配和证据，
PARTIAL/ABSTAIN/STALE 均不向 UI 暴露动作；还覆盖发送时到期强制转 STALE、JSON wire 嵌入和
逐字段 Vision/manual/config/derived/inferred 来源徽标、UI 所需元素/无动态 HTML 注入约束。
Advice schema-v1 对新增 provenance 采用 additive default，旧 payload 仍可读取。
`test_live_strategy.py` 验证生产 live 绑定在输入不足时输出无动作 ABSTAIN、注入匹配 Provider
后可输出 READY、同 state/version/request 复用、到期或新版本换 request，以及同一 state 下
感知质量下降会立即换 request 并撤销 READY，不能沿用旧动作。
`realtime` 的轻量合同与可选 OpenCV 捕获栈现已延迟解耦，
因此该输出回归可在无视觉依赖环境执行。真实 FastAPI WebSocket 顺序测试覆盖同状态
Fast→Slow 升级和 state_version 变化后旧 Advice 强制 STALE/动作清空；断线后的当前状态恢复
仍由 `E2E-011` 单独验收。

`test_state_derivation.py` 直接验证：

- 合法 check/bet、fold/call/raise、短码 all-in 和金额语义；
- 相等 all-in、两级/三级边池、folded contributor、unmatched-chip return；
- 每个池的金额、eligible seats 与总筹码守恒；
- `PokerState → DecisionContext` 请求绑定、缺失字段、质量硬门；
- preflop 按 dealt player count、postflop 按 active player count；
- 多人 pairwise effective stacks。

`test_action_reconstruction.py` 从相邻 canonical states 验证 fold/check/call/bet/raise、
短码 all-in-call/all-in-raise 的多义性、可选识别标签消歧、additional/total-street payload，
以及 hand/version/street/cards/player identity/status/chip/current-bet 不一致时无事件、阻断策略。
8 组 `MOCK-ACTION-RECONSTRUCTION-*` 数据直接执行同一重建器。

`test_temporal_consensus.py` 验证所有基础识别字段和逐 `slot_id` 字段的连续帧确认、值变化重启、
UNKNOWN 中断、CONFLICT 保留、帧序号缺口、slot 消失、阈值 1、非法配置和非递增帧拒绝。
真实 `RealtimePipeline` 集成测试证明 pending pot 在确认前不会进入 canonical state。
8 组 `MOCK-TEMPORAL-*` 序列由生成器维护，并直接执行 production consensus；Mock 总数为 245。

`test_hand_boundary.py` 验证 Hero 换牌、postflop→preflop 的 street/board/pot reset、
显式 dealer/stack slot→seat 映射、弱证据、冲突证据和未映射视觉 slot 的 fail-closed 行为；
RealtimePipeline 集成测试还验证确认边界后创建新 `hand_id`，并在旧手牌写入带同一边界时间的
`HAND_END`。6 组 `MOCK-HAND-BOUNDARY-*` 数据直接执行 production detector；Mock 总数为 251。

`test_memory_atomic.py` 与 `test_hand_memory.py` 验证 state+events 批量提交及旧手完成+successor
创建的原子性、幂等性和失败回滚。错误 event hand/version、非 HAND_END、已有 successor 均不得
改变 state/event/history/active identity。4 组 `MOCK-MEMORY-*` 数据直接执行 production store；
Mock 总数为 255。

`test_router.py`、`test_local_resolver.py`、`test_strategy_cache.py` 和
`test_exploit_fusion.py` 验证 position 精确匹配、stack/pot/last-aggressive-size 有界插值、组合维度
最小分数、阈值外拒答，以及 Local Resolver、缓存、融合、Advice 序列化和 UI 全链路保留
`match_dimensions[]`。4 组 `MOCK-ABSTRACTION-*` 数据直接执行 production capability/router；
Mock 总数为 259。任何 `INTERPOLATED` Candidate 缺少差异维度，或上报分数高于维度/Capability
允许值，均必须拒绝。

`test_safety_gates.py` 验证 freshness、confidence、context、strategy source、legal actions 五个
内置硬门，以及 range/numerical 等外部模块门的唯一命名、保留名、PASS/FAIL/SKIPPED 合同、
Fusion/Orchestrator 透传、序列化、STALE 保留和 `READY` 构造不变量。4 组
`MOCK-HARD-GATE-*` 数据直接执行 production Advice builder；Mock 总数为 263。

`test_tiered_router.py` 和 `test_strategy_cache.py` 验证 Cache → Preflop DB → Presolved → Model
固定顺序、命中即停止、miss/rejected 继续、全部失败 reason 聚合、lookup-only cache 的
miss/hit/stale、write-through 回填后下一请求由 Cache 命中，以及 Production Orchestrator 接受
分层 Router。5 组 `MOCK-FAST-FALLBACK-*` 数据直接执行 production tier router；Mock 总数为
268。

`test_asset_provider.py` 验证 strategy asset 文件 SHA-256、完整 Provider 元数据、license、
capability ID 与完整 capability digest，及 canonical context node lookup。覆盖 3 人 preflop、
3-way flop、4-way turn、逐尺度频率/EV、Router→Advice、缺节点、损坏节点、未知 schema、错误 hash、
错误 capability 和缺失许可。6 组 `MOCK-STRATEGY-ASSET-*` 数据执行 production Adapter；Mock
总数为 274。所有这些资产均标记 synthetic-only，不能替代 PRV-003~005 的真实许可资产 Golden。

`test_platform_mapping.py` 验证版本化、不可变且一一对应的视觉 slot→seat contract，把稳定
actor/action/stack/pot/dealer 证据构造成 candidate state，再交给 production action reconciler。
覆盖 3 人状态下六类行动、global/slot 双来源一致性、未映射与冲突输入、缺字段、筹码守恒、
换街/发牌混帧、低置信字段、StateEngine fallback 和 Orchestrator 原子写入。23 组
`MOCK-PLATFORM-MAPPING-*` 直接执行同一路径；Mock 总数为 297。这些是 Synthetic Replay，
不构成 WePoker 真实 ROI、slot calibration 或 capture Replay 证据。

`test_capture_replay.py` 验证 Capture Replay v1 注册和执行合同：artifact、平台配置、逐字段校准、
原始帧全部 hash-pinned；相对路径不得逃逸 asset root；平台/layout/字段/sample count 必须由引用
文件内部再次声明；raw-frame recognizer 输出必须绑定 frame SHA-256、revision、sequence 和 timestamp。
执行器逐帧比较 mapping status、state version、event types 和 reasons，并输出 JSON-safe quality
report。32 个测试覆盖真实/合成 stage 边界、授权、隐私、缺失/空校准、篡改、顺序、未知字段、
错误 recognizer 类型/身份及预期漂移。仓库没有真实 WePoker 原始帧，因此这里只完成 R6 执行合同，
没有将 R6 标记通过。

`test_range_tracker.py` 直接验证 concrete-combo blocker、手算 Bayesian
posterior、缺失 likelihood 降级、小样本收缩、多人 joint assignment 的跨玩家
碰牌排除、known-card blocker、无解和组合预算边界。
`test_range_prior.py` 验证 13 个明确 6/9 人 RFI 位置、AA/AKs/AKo 的 6/4/12 concrete
combo 展开、均匀归一、known-card blocker、资产/version evidence、全阻断 UNKNOWN，
以及其他人数、BB、stack 和 action line 不适用时绝不继承或退回 random range。

`test_multiway_equity.py` 直接验证三人 tie 只在实际赢家间分池、Hero 不具备
side-pot 资格时不得获得该池、联合范围权重、turn runout exact 枚举、缺失 holding、
碰牌和 `max_outcomes` 预算门。

`test_metrics.py` 直接验证多人 pairwise SPR、zero-pot `UNKNOWN`、Decimal exact
pot odds、no-call-cost，以及 additional/total 金额语义下的 BB、pot fraction 和
raise multiplier。

`test_equity_cache.py` 直接验证 canonical 等价 key、cards/ranges/version/pots/
method/trials/seed 的逐维 miss、TTL `STALE`、LRU 和结果身份；
`test_adaptive_equity.py` 验证 exact/MC 预算路由、seed 重放、95% CI、低 trials
`PARTIAL`、足够精度 `COMPLETE`、缓存元数据、过期请求拒绝，以及超过 joint
materialization 上限后直接进入 range rejection sampling；多人 Equity 测试另验证
跨玩家碰牌只能重采样、无合法联合发牌时明确失败，并用可控 monotonic clock
验证 wall deadline 到达后返回实际完成的样本数而不是伪报 planned trials。

`tools/benchmark_adaptive_equity.py` 在声明的目标机 MacBookPro18,3（Apple M1 Pro 10-core、
32GB）上分别测量 HU exact、HU MC 和 3-way MC。五次 measured run 固化在
`configs/strategy/adaptive-equity-m1-pro-v1.json`，包含 OS/Python、p50/p95/max、工具 SHA-256、
命令和源 revision。`test_adaptive_equity_calibration.py` 锁定工具 hash、环境、默认 policy 和
至少 50% 的 p95 安全余量，并验证默认 300ms flop 预算只计划 600 trials、如实返回 PARTIAL。

这些是 `ST-006`、`ST-007`、`CTX-001`、`MET-001~004`、`RNG-002~005`
和 `EQ-003~006`
的当前自动化证据；
真实状态 Replay、Provider Golden、随机属性生成与 UI 测试仍按后续层级补齐。

## 5. 场景覆盖矩阵

### 5.1 玩家人数与街道

| 场景族 | 参数 | 必测结果 |
|---|---|---|
| Preflop HU | `dealt_player_count=2` | HU Provider 可命中；多人 Provider 不误匹配 |
| Preflop multi-player | `dealt_player_count=3..9` 分别运行 | 只匹配对应人数 Provider；只有 HU Provider 时 ABSTAIN |
| Postflop HU | `active_player_count=2`，原始发牌人数可为 2..9 | 使用 HU postflop 分支，但范围保留原始多人行动历史 |
| Postflop 3-way | `active_player_count=3` | 联合三人范围/equity；无 3-way Provider 时 PARTIAL/ABSTAIN |
| Postflop 4-way+ | `active_player_count=4..9` | 不拆成多个 HU；按 active count 匹配能力 |

### 5.2 行动、筹码和底池

| 维度 | 必测等价类 | 关键断言 |
|---|---|---|
| Preflop line | unopened、limp、multi-limp、raise、3-bet、4-bet、squeeze、iso、all-in | actor、金额、to-call、legal actions 和 Provider key 正确 |
| Postflop line | check-through、c-bet、donk、probe、bet/raise/re-raise/all-in | street event 顺序和下注树可达 |
| Stack | 10/20/30/40/60/80/100/150/200BB、覆盖内插值边界 | exact/approx/not-applicable 状态正确 |
| Pot | single pot、multiway pot、一个/多个 side pot | 金额守恒、eligible players 和 pot share 正确 |
| Rules | ante/no-ante、cash/tournament、rake/cap | Provider capability 不匹配时不命中 |
| Input quality | VALID、UNKNOWN、LOW_CONFIDENCE、CONFLICT、manual | READY 门槛、badge、assumption 和 reason code 正确 |

不要求对维度做不可维护的全笛卡尔积。每个受支持 Provider 必须覆盖其全部人数；其余维度采用边界值和 pairwise 组合，并为高风险组合单独增加 Golden/Replay。

## 6. 功能回归矩阵

| Test group | Requirement / Function | 核心测试 | 自动断言 | Suite |
|---|---|---|---|---|
| `TG-IN` | REQ-IN-001、REQ-IN-002、ST-001、CTX-002/003 | 多帧稳定、抖动、冲突、manual+vision 混合 | 不稳定输入不更新 state；来源不丢失 | R0/R2/R3 |
| `TG-STATE` | REQ-ST-001、REQ-ST-002、ST-002~007 | no-op、合法行动、非法行动、hand/street boundary、side pot | 确定性、版本、筹码守恒、合法动作 | R1/R3 |
| `TG-CONTEXT` | REQ-CTX-001、CTX-001~004 | 完整、缺 position、缺 stack、deadline、多人 seats | missing_fields、quality、ID 和人数一致 | R0/R1 |
| `TG-METRIC` | REQ-MET-001、MET-001~004 | effective stack、SPR、pot odds、size normalization | 与独立公式/枚举结果一致 | R1 |
| `TG-RANGE` | REQ-RNG-001、RNG-001~005 | prior、action update、blocker、shrinkage、multiway collision | 权重归一、冲突组合为零、版本可追踪 | R1/R4 |
| `TG-EQUITY` | REQ-EQ-001、EQ-001~006 | exact、range、MC、adaptive、multiway、cache | exact parity、seed replay、CI/容差、cache key | R1/R4/R5 |
| `TG-PROVIDER` | REQ-PRV-001、PRV-001~007 | capability schema、asset hash、Golden lookup、timeout | adapter parity；损坏/不支持时拒绝注册或返回明确状态 | R0/R2/R3 |
| `TG-ROUTER` | REQ-RTR-001、RTR-001~008 | 2–9 人、exact/approx、fallback、stale、cache | 候选集合、优先级、查找状态和最终降级正确 | R1/R2/R3 |
| `TG-FUSION` | REQ-FUS-001、EV/FUS-* | 非法动作、概率归一、EV、低置信、多个 candidates | 非法动作=0；概率和=1±容差；硬门失败非 READY | R1/R2 |
| `TG-ADVICE` | REQ-OUT-001、REQ-OUT-002、ADV/EXP/SER-* | 四种状态、evidence、expiry、语言、round-trip | 必填字段、reason code、数值不被解释层修改 | R0/R2 |
| `TG-UI` | REQ-UI-001、UI-001~003 | READY/PARTIAL/ABSTAIN/STALE、Fast→Slow、重连 | 频率/尺度/来源正确；旧动作隐藏且不闪回 | R2/R6 |
| `TG-AUDIT` | REQ-AUD-001、ADV-003 | observation→state→range→provider→advice | 每条 READY evidence chain 完整 | R0/R2 |
| `TG-TRAIN` | REQ-TRN-001、TRN-001/002 | 实际动作匹配、无法确认动作、EV 完整/缺失 | 不推断未知动作；不伪造 EV loss | R2/R3 |

## 7. 关键端到端回归用例

| Test ID | 输入 | 处理路径 | 预期输出 |
|---|---|---|---|
| `E2E-001` | HU、完整人工上下文、Golden AA root | State→Context→HU Provider→Advice | READY/exact；频率、版本和 Golden 一致 |
| `E2E-002` | 3..9 人参数化、只有 HU Provider | Context→Capability Filter | ABSTAIN/unsupported_player_count，无动作频率 |
| `E2E-003` | 3..9 人参数化、对应人数 Fake/Golden Provider | Router→Fusion→Advice | 只命中相同人数 Provider，READY/source/version 正确 |
| `E2E-004` | 6 人开局、flop 剩 2 人 | Range history→HU postflop Provider | active=2；preflop range history 仍来自 6 人行动线 |
| `E2E-005` | 三人 flop、两个 villain ranges | Joint range→multiway equity | PARTIAL/equity_only 或对应 3-way Strategy，不出现 HU 拼接 |
| `E2E-006` | 四人 all-in、主池+多个边池 | State→pots→equity/pot share | 每个池金额和 eligible players 正确，筹码守恒 |
| `E2E-007` | Position UNKNOWN，其余完整 | Quality/Rejection Gate | ABSTAIN/missing_position，数学安全字段可选显示 |
| `E2E-008` | 无 Provider、Equity 输入完整 | Equity fallback→Advice | PARTIAL/equity_only，不显示 GTO/动作频率 |
| `E2E-009` | Fast Advice 后 state_version 更新，旧 slow result 到达 | Stale Filter→UI | 旧结果丢弃，当前 UI 不闪回 |
| `E2E-010` | Provider asset hash 错误 | Registry/Router | Provider unavailable；明确 integrity reason；系统不崩溃 |
| `E2E-011` | WebSocket 断开重连 | Advice store→serialization→UI | 只恢复当前未过期 Advice |
| `E2E-012` | 完整手牌 replay + 实际动作 | State/Advice history→Debrief | 动作绑定正确版本；仅完整 EV 时显示 EV loss |

## 8. 数值和属性测试门槛

| 对象 | 测试方法 | 通过门槛 |
|---|---|---|
| Chip accounting | 随机合法行动序列属性测试 | 初始筹码 = stacks + commitments + awarded chips，Decimal 精确相等 |
| Legal actions | 规则边界和随机状态 | 所有输出动作可执行；min/max raise 满足规则 |
| Probabilities | 所有 StrategyCandidate/Advice | 每项 `[0,1]`；合法项总和 `1±1e-9`；非法项为 0 |
| Exact equity | 独立枚举器或已知小场景 | 在浮点容差内完全一致 |
| Monte Carlo | 固定 seeds + exact reference | 偏差落在预先定义的统计容差；失败可重放 |
| Multiway assignment | 随机联合范围 | 任意样本无重复牌，权重归一 |
| Match score | abstraction 边界两侧 | 阈值内为 approximate；阈值外 NOT_FOUND |
| Stale protection | hand/state/request/deadline 单独变更 | 任一变化都拒绝旧 candidate |

统计容差和 trial 数必须由 benchmark fixture 指定，不允许在测试失败后临时放宽全局阈值。

## 9. 性能与稳定性门槛

| Metric | 起点→终点 | 发布目标 | 说明 |
|---|---|---:|---|
| `PERF-CTX` | Stable state→DecisionContext | p95 ≤ 10ms | 不含感知稳定等待 |
| `PERF-LOOKUP` | Context→热 preflop lookup | p95 ≤ 10ms | 冷/热分开报告 |
| `PERF-FIRST` | Stable state→first Advice | p95 ≤ 300ms | Fast Path 用户指标 |
| `PERF-UI` | WebSocket receive→UI paint | p95 ≤ 25ms | 在固定测试环境测量 |
| `PERF-STABILITY` | 长 session | 无 Advice 闪回、无持续内存增长 | 报告峰值 RSS、cache hit/eviction |
| `PERF-SLOW` | Resolver request→result | 报告分布和 timeout rate | 不以牺牲 Fast Path 为代价 |

性能回归必须记录硬件、OS、Python、策略资产版本、数据集版本和冷/热状态；环境不同的结果不能直接比较。

## 10. 变更影响与最小回归集

| 修改范围 | 最少必须运行 |
|---|---|
| State/Event/Rules | R0、R1 全部；R3 的所有人数、行动、all-in/side-pot |
| DecisionContext/schema | R0、R1、R2 全部；序列化兼容测试 |
| Range/Equity | TG-RANGE、TG-EQUITY、R4；相关 E2E-004/005/006/008 |
| Provider/策略资产 | TG-PROVIDER、TG-ROUTER、全部受支持人数 Golden、资产完整性测试 |
| Router/Fusion | R1、R2、全部 E2E-001..010 |
| Advice/serialization/UI | R0 Advice contract、R2、E2E-009/011、UI snapshot |
| Capture/recognition/calibration | 真实 Replay、TG-IN、状态 E2E、目标平台 R6 |
| Packaging/dependencies | 全量自动测试、包构建、资源/hash 检查、目标平台 R6 |

## 11. 合并与发布门槛

### 11.1 Pull Request

- `R0 + R1 + R2` 全部通过。
- 受影响场景的 `R3` 通过。
- 新需求有 Requirement ID、Function ID、Test ID 和 fixture。
- 新 Provider 有 capability contract、Golden parity、source version 和 asset hash。
- 不得通过删除断言、扩大容差或跳过失败场景获得绿灯，除非有书面技术决策。

### 11.2 发布候选

- `R0–R5` 全部通过，并保存机器可读结果和性能报告。
- `R6` 在目标系统完成；本地打包成功不等于干净安装成功。
- 能力清单只包含有 Golden/Replay、延迟和已知限制证据的场景。
- README、PRD、需求矩阵、Provider 版本和 UI 声明一致。
- 当前发布不具备的目标能力必须继续明确标记为 planned。

### 11.3 识别/UI 并行工作流合并门槛

| 交付方 | 合并前最低证据 | 不允许替代的证据 |
|---|---|---|
| WPK 识别 | 版本化 platform/layout mapping；授权 raw-frame Replay；Hero/board/street/pot/dealer/actor/slot stacks/actions 的逐字段报告；UNKNOWN/CONFLICT、动画和漏帧用例 | Synthetic Observation、静态截图或单一总置信度不能替代 raw-frame Replay |
| 策略/状态 | 同一 Replay 生成确定性 state/events/context；对应人数 Provider capability/Golden；READY 和拒答路径；过期 Slow 丢弃 | Mock Provider 不能替代真实 Provider Golden；Equity 不能替代策略 |
| Live Coach UI | 四种 Advice 状态 snapshot；同状态 Fast→Slow；换手、换 state、过期、断连后不闪回；来源/版本/假设/证据可见 | 单独构造的前端假数据不能替代真实 `DesktopFrame` sequence |
| 共同 R6 | 固定 commit、calibration hash、Replay hash、Provider/version 和 UI build 跑通 `capture→Advice→render`；保存机器结果、截图/录屏、延迟和权限记录 | 各模块独立绿灯不能替代同版本产品 E2E |

伙伴提交的识别或 UI 改动应按影响范围触发 `TG-IN/TG-STATE` 或 `TG-UI`，并至少运行
`E2E-007/009/011`；若改动影响 seat mapping、actor、stack 或 action amount，还必须运行
`E2E-004/006/012`。缺少目标 WPK Replay 时可以合并为 planned/experimental，但不得在能力
清单中标记为 supported。

## 12. 需求到回归证据追踪

| Requirement | Test groups | 必要 E2E | 发布证据 |
|---|---|---|---|
| REQ-IN-001、REQ-IN-002 | TG-IN | E2E-007 | hash-pinned raw-frame Replay quality report；Synthetic/stable-observation 不合格 |
| REQ-ST-001、REQ-ST-002 | TG-STATE | E2E-004/006/012 | State/property report |
| REQ-CTX-001 | TG-CONTEXT | E2E-001/003/007 | Contract report |
| REQ-MET-001 | TG-METRIC | E2E-005/006/008 | Numeric report |
| REQ-RNG-001 | TG-RANGE | E2E-004/005 | Range statistical report |
| REQ-EQ-001 | TG-EQUITY | E2E-005/006/008 | Exact/MC benchmark |
| REQ-PRV-001 | TG-PROVIDER | E2E-001/002/003/010 | Golden parity + asset manifest |
| REQ-RTR-001 | TG-ROUTER | E2E-002/003/004/008/009 | Scenario routing report |
| REQ-FUS-001 | TG-FUSION | E2E-001/008/009 | Candidate legality/stale report |
| REQ-OUT-001、REQ-OUT-002 | TG-ADVICE | E2E-001/007/008/009 | Advice contract snapshots |
| REQ-UI-001 | TG-UI | E2E-009/011 | UI sequence/snapshot evidence |
| REQ-PERF-001 | TG-CONTEXT、TG-ROUTER、TG-UI | E2E-009/011 + R5 | Versioned performance report |
| REQ-AUD-001 | TG-AUDIT | E2E-001/003/012 | Evidence-chain audit |
| REQ-TRN-001 | TG-TRAIN | E2E-012 | Debrief parity report |

一个需求只有在对应单元/属性测试、必要 E2E 和发布证据同时存在时，才允许从 `planned` 标记为 `supported`。

## 13. 回归结果记录格式

每次发布候选应生成一份机器可读结果和一份人类摘要，至少记录：

```text
release/version/commit
test_timestamp
OS/hardware/Python
fixture_schema_version and dataset hashes
provider IDs/versions/asset hashes
suite totals: passed/failed/skipped/xfailed
failed test IDs and links to artifacts
scenario coverage by player_count/street/status
performance p50/p95/p99
known limitations and approved exceptions
```

可用性以需求和场景覆盖为核心，不以单一代码行覆盖率代替。要求：

- 所有 `P0` Requirement ID 必须映射到自动测试和发布证据。
- 所有已声明 `supported` 的人数、street 和 Provider capability 必须至少有一个正向 Golden，以及一个拒答/降级用例。
- 任何 `skip/xfail` 都必须有原因、负责人或跟踪项和到期条件；发布报告中单独列出。
- 测试执行中没有收集到的场景视为“未验证”，不能视为“通过”。
