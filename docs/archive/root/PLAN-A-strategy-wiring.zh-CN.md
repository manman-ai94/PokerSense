# 板块 A · 策略层接线打通

> 让桌面端**第一次产出非 ABSTAIN 的真实建议**。
> 优先级：**最高**，其余三个板块都依赖它。
> 状态：待开工 · 编制 2026-09-06

---

## 1. 目标

注册已验证可用的策略 Provider，补齐缺失的接线，使 ADB 路径下 **6 人桌翻前无人入池（unopened）** 场景产出 `AdviceStatus.READY` 的具体建议。

**不在本板块范围内**：采集卡路径（板块 B）、7/8 人桌与翻后能力（板块 C）、服务端开关与发布（板块 D）。

---

## 2. 现状：三个真实阻塞（均已核实，非推断）

### 阻塞 1 · 零 Provider 注册

`live.py:734`：

```python
StrategyOrchestrator(StrategyRouter())   # 空参 → providers = ()
```

空 providers → `router.py:152-159` 直接 `return RouteResult(LookupState.NO_STRATEGY, None, (), ("no_strategy",))`。

### 阻塞 2 · `action_line_resolver` 缺失（隐藏阻塞，本轮新发现）

`live.py:736-741` 构造 `LiveStrategySession` 时**没有传 `action_line_resolver`**，而它默认是 `None`（`strategy_live.py:48`）→ `action_line = None`（`strategy_live.py:171-173`）。

而 `ProviderCapability.match` 是硬性要求（`provider.py:288-291`）：

```python
if context.action_line is None:
    reasons.append("missing_action_line")
elif context.action_line not in self.action_lines:
    reasons.append("unsupported_action_line")
```

**也就是说，光注册 Provider 不够，必须先实现行动线解析器。** `ActionLineResolver` 目前只是一个类型别名（`strategy_live.py:32`），仓库内**没有生产实现**。

### 阻塞 3 · 五个必需字段必须 valid

`strategy_live.py:38`：

```python
_REQUIRED_LIVE_FIELDS = ("hero_cards", "street", "pot", "stacks", "action")
```

翻后额外加 `board_cards`（`strategy_live.py:151-152`）。任一字段 `status != "valid"` → `live_input_not_valid:<field>` 进 `hard_failures` → ABSTAIN。

ADB 路径这 5 个字段**均已标定**（`card` / `street` / `amount` / `stack` / `action`），门阈值 0.89–0.94，可达标，本板块无需处理。采集卡路径不满足，由板块 B 解决。

### 已澄清的一点（修正上一版判断）

人数**不是硬编码**：`strategy_live.py:163-170` 已经从 `state.players` 动态推导：

```python
dealt_count = sum(p.status is not PlayerStatus.SITTING_OUT for p in state.players)
if 2 <= dealt_count <= game_config.max_seats:
    game_config = replace(game_config, dealt_player_count=dealt_count)
```

`GameConfig` 是 frozen dataclass，用 `dataclasses.replace` 派生，改法正确。

⚠️ 但注意兜底风险：`_seed_state`（`live.py:598-612`）把 8 个玩家全部 seed 成 `SITTING_OUT`。若 occupancy 识别不工作，`dealt_count = 0` → 兜底 `dealt_player_count=8` → **8 人桌恰好无任何 Provider 覆盖** → ABSTAIN。ADB 路径 occupancy 已标定，不受影响；采集卡路径由板块 B 解决。

---

## 3. 改动清单

### A1 · 抽出 Provider 注册工厂

在 `live.py` 新增：

```python
def build_strategy_router() -> StrategyRouter:
    """Register every release-eligible provider. 板块 C 只往这里加，不改调用方。"""
    return StrategyRouter((PreflopRfiHeuristicProvider.from_builtin(),))
```

`live.py:734` 改为 `StrategyOrchestrator(build_strategy_router())`。

> **这是给板块 C 预留的唯一扩展点。** C 板块新增 Provider 时只改这个函数体，不碰 `live_analysis_stream`。

### A2 · 实现行动线解析器

新建 `src/poker_engine/desktop/action_line.py`，导出 `resolve_action_line(state, history) -> str | None`。

- 从 `state` + `action_history` 推导动作线标签，至少覆盖 `unopened`（heuristic 唯一支持的标签）
- **识别不出时返回 `None`**（失败关闭），绝不猜
- 参照 `blueprint_provider.py:433` 的 `_history_action_line` 语义，但独立实现并单独测试

`live.py` 传入 `action_line_resolver=resolve_action_line`。

### A3 · 端到端测试（补当前最大测试空白）

现状：全库**没有任何端到端测试**——同时 import vision/capture 与 strategy 的测试文件零命中。

新建 `tests/integration/test_live_strategy_wiring.py`：

| 用例 | 构造 | 断言 |
|---|---|---|
| 6 人翻前 unopened、合法 hero 手牌 | `context()` 基建 + 真实 Provider | `READY`，`preferred_action ∈ {FOLD, RAISE}`，`strategy_source` 正确 |
| 3/4/5/7/8 人参数化 | 同上 | `ABSTAIN` + `unsupported_player_count`（对齐 `E2E-002`） |
| 翻后场景 | street=FLOP | `ABSTAIN` + `unsupported_street`（承认当前能力边界） |
| `action_line=None` | resolver 返回 None | `ABSTAIN` + `missing_action_line` |
| 必需字段 UNKNOWN | 注入 hard_failures | `ABSTAIN` + `live_input_not_valid:<field>` |
| 资产 hash 错误 | 篡改 | Provider unavailable，系统不崩溃（对齐 `E2E-010`） |

造数据复用 `tests/strategy/helpers.py:76` 的 `context()`，注册写法参考 `tests/strategy/test_heuristic_provider.py:194-215`。

### A4 · 修正过时注释

`live.py:729-731` 的注释称"No released multiplayer Provider is bundled"，注册后不再准确，改为如实描述当前覆盖范围与限制。

---

## 4. 验收标准

- 新增测试全绿，且**回归基线不下降**：`2148 passed / 2 skipped`
  （⚠️ pytest 9.1.1 + `addopts = "-q"` 会吞统计行，复现加 `-v`）
- 6 人翻前 unopened 场景实跑产出 `READY` 建议
- 界面如实标注 assumptions（`no_raise_size_or_ev`），**不宣称 GTO**
- flake8 干净（max-line-length=88，extend-ignore=E203,W503）

---

## 5. 与其他板块的边界

| 板块 | 关系 | 约定 |
|---|---|---|
| B 采集卡 | **无代码重叠** | B 改 `tools/` + `configs/`；A 改 `live.py` 策略装配段 + 新文件 `action_line.py` |
| C 能力扩张 | **依赖 A** | C 只修改 `build_strategy_router()` 函数体，不改调用方，不另设注册点 |
| D 服务端 | **无代码重叠** | D 改 `server.py`；A 不碰 server |

---

## 6. 风险

| 风险 | 说明 | 应对 |
|---|---|---|
| action_line 推导错 | 误判 unopened 会导致错误建议 | 识别不出返回 `None`；单测覆盖 multi-limp / raise / 3bet 等分支 |
| 建议质量低 | heuristic 只有 FOLD/RAISE 二选一，conf 0.4，**无 EV、无加注尺寸** | 界面必须显示 assumptions；`architecture.md:64` 明令禁止宣称为多人 GTO |
| hand_id/state_version 不匹配 | `strategy_live.py:91-92` 会 raise ValueError | 沿用现有传参，端到端测试覆盖 |

---

## 7. 明确不做

- ❌ 不做自动操作（项目硬红线）
- ❌ 不扩大 Provider 覆盖范围（属板块 C）
- ❌ 不改后端识别逻辑（属板块 B）
- ❌ 不宣称 GTO，不补齐 EV/加注尺寸（需新资产，属板块 C）
