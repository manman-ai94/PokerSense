# 板块 C · 策略能力扩张（人数覆盖与翻后）

> 补齐 7/8 人桌与翻后策略。**本板块工作量最大，必须分期。**
> 依赖板块 A 的注册扩展点。
> 状态：待开工（C1 可先做，C2 需单独评估） · 编制 2026-09-06

---

## 1. 目标

把策略覆盖从「6/9 人翻前 unopened 单一场景」扩张到：

1. **C1**：3–9 人翻前（补齐 7/8 人桌这个主流缺口）
2. **C2**：flop / turn / river 翻后决策
3. **C3**：路由架构对齐 `architecture.md` 的 L0–L4 分层

**不在本板块范围内**：Provider 注册与行动线接线（板块 A）、采集卡标定量（板块 B）、发布流程（板块 D）。

---

## 2. 现状：两个覆盖缺口

### 2.1 7/8 人桌几乎无覆盖

| Provider | `player_counts` | 位置 |
|---|---|---|
| `PreflopRfiHeuristicProvider` | `{6, 9}` | `heuristic_provider.py:76` |
| `HuPreflopBlueprintProvider` | `{2}` | `blueprint_provider.py:108` |
| **`GTOpenPreflopProvider`** | **`range(2,10)` = 2–9** | **`gtopen_provider.py:285`** |
| `JsonStrategyAssetProvider` | 取决于外部资产 | — |

⚠️ 你定调过 **90% 牌局是 6–8 人桌**，而 **7、8 人恰好是当前唯一有资产的 Provider 覆盖不到的**。这是必须优先补的缺口。

### 2.2 翻后是零

全 `src/` 搜 `Street.FLOP|TURN|RIVER|postflop`，命中的 5 个文件**全是识别/状态层，没有一个是策略**：

- `contracts.py:357`（校验公共牌张数）
- `state_engine/engine.py`
- `realtime/hand_boundary.py`
- `perceptual/vision/engine.py`
- `perceptual/vision/street_detector.py:50-54`

四个 Provider 的 `capability.streets` **全是 `{PREFLOP}`**。实测翻后请求 → `ABSTAIN / ('unsupported_street',)`。

**即：能识别翻后状态，但完全没有翻后策略。**

### 2.3 现有蓝图（不用重新设计）

`architecture.md` 第 7 节已定义分层，且 `TieredStrategyRouter` **已实现**（`router.py:287`），只是 live.py 没用：

| 层级 | 来源 | 延迟 | 适用 |
|---|---|---|---|
| L0 | legality / safety | <1ms | 合法动作、状态拒答 |
| L1 | Preflop DB | <5ms | 标准 HU preflop |
| L2 | Canonical presolved cache | 5–20ms | 标准翻后节点 |
| L3 | Lightweight policy/value model | 10–80ms | cache miss 近似 |
| L4 | Local resolver / CFR | 0.5–5s+ | 小 EV gap、异常尺度 |

---

## 3. 改动清单

### C1 · 接入 GTOpen（补 7/8 人桌）

依据 `architecture.md:201-208` 的设计：

- 访问 `127.0.0.1` 上单独运行的 GTOpen JSON API（默认端口 3737），**不复制上游 Rust 代码**
- 把 2–9 人位置、等起始筹码、blind/ante/rake 和权威行动事件构造成 Preflop Lab tree
- 按 Hero 的 169-class 索引读取逐尺度策略

**硬性约束（文档明确规定）**：
- 上游每个服务只有一个可变 preflop session → **Provider 必须串行**
- 超时、行动路径不精确、返回非法动作、不等起始筹码 → **拒答**
- 多人 terminal value 用近似模型 → 输出**固定为 `HEURISTIC`，不能作为发布版完整多人 GTO 声明**

**前置依赖**：需要部署 GTOpen 本地服务。这是外部依赖，若暂不部署，C1 只能以「服务不可用时优雅拒答」的方式接线。

### C2 · 翻后策略（分三期，每期独立验收）

| 期 | 内容 | 依据 |
|---|---|---|
| **C2.1** | L2 canonical presolved cache：标准翻后节点查表 | `architecture.md` L2 |
| **C2.2** | L3 轻量 policy/value model：cache miss 近似 | `architecture.md` L3 |
| **C2.3** | L4 local resolver：从 **river subgame** 开始 | `architecture.md:199-200` 明说第一版从 river 开始，flop/turn 未按时收敛时只用于局后分析 |

Solver 必须用独立进程和硬预算，**不能阻塞 Fast Advice**。

### C3 · 路由架构对齐

把 `build_strategy_router()`（板块 A 建的函数）内部从 `StrategyRouter` 升级为 `TieredStrategyRouter`，按 L0→L4 固定顺序查询，一旦某层命中，更低层不得执行。

`architecture.md` 规定：全部层 miss/rejected/not-applicable 时**保留完整 lookup 轨迹并返回 NO_STRATEGY，不构造伪 candidate**。

---

## 4. 验收标准

对齐 `docs/strategy-regression-test-matrix.md` 的现成用例表：

| 用例 | 场景 | 预期 |
|---|---|---|
| `E2E-002` | 3..9 人参数化、只有 HU Provider | `ABSTAIN/unsupported_player_count` |
| `E2E-003` | 3..9 人参数化、对应人数 Provider | 只命中相同人数 Provider，READY/source/version 正确 |
| `E2E-004` | 6 人开局、flop 剩 2 人 | `active=2`；preflop range history 仍来自 6 人行动线 |
| `E2E-005` | 三人 flop、两个 villain ranges | 联合三人范围/equity，**不出现 HU 拼接** |
| `E2E-010` | Provider asset hash 错误 | Provider unavailable，明确 integrity reason，系统不崩溃 |

人数与街道矩阵（`strategy-regression-test-matrix.md` 5.1）：Preflop HU / Preflop 3..9 / Postflop HU / Postflop 3-way / Postflop 4-way+，每个受支持 Provider 必须覆盖其全部人数。

---

## 5. 与其他板块的边界

| 板块 | 关系 | 约定 |
|---|---|---|
| A 策略接线 | **C 依赖 A** | C 只修改 A 建立的 `build_strategy_router()` 函数体，**不改调用方、不另设注册点** |
| B 采集卡 | 无重叠 | B 改 `tools/` + `configs/`；C 改 `src/poker_engine/strategy/` |
| D 服务端 | 无重叠 | — |

⚠️ **唯一潜在冲突点**：A 与 C 都要动 `build_strategy_router()`。约定 A 先建好函数骨架（只含 heuristic），C 后续只往元组里追加 Provider，**不重构函数签名**。

---

## 6. 风险

| 风险 | 等级 | 说明 |
|---|---|---|
| GTOpen 外部服务依赖 | 中 | 需部署与运维本地服务；上游 session 可变导致必须串行，吞吐受限 |
| 翻后是能力建设不是接线 | **高** | C2 从零开始，工作量远大于 A/B，建议单独评估立项 |
| 误宣称为 GTO | **高** | `architecture.md:64` 明令禁止把 6/9 heuristic 宣称为多人 GTO；GTOpen 输出也必须标 `HEURISTIC` |
| 资产来源 | 中 | 若不想依赖 GTOpen，扩展 Heuristic 资产到 7/8 人需要新的资产来源与审计（现有 NOTICE 明确说 3–5/7–8 是刻意排除的） |
| 延迟预算 | 中 | L4 resolver 0.5–5s+，必须异步且不阻塞 Fast Advice |

---

## 7. 明确不做

- ❌ 不把任何启发式输出宣称为 GTO（`architecture.md:64` 硬性禁止）
- ❌ 不复制上游 Rust solver 代码（只通过 JSON API 访问）
- ❌ 不阻塞 Fast Advice 等待慢速 resolver
- ❌ 不在证据不足时构造伪 candidate（全部层 miss 必须返回 NO_STRATEGY）
