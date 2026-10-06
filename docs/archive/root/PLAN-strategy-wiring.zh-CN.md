# PokerSense 开发计划索引

> 编制 2026-09-06 · 纯本地推进，不触碰远程
> 本文件是**索引与契约**，具体执行细节见 A/B/C/D 四份分册。

---

## 1. 四板块总览

| 板块 | 主题 | 目标一句话 | 改动范围 | 依赖 |
|---|---|---|---|---|
| **[A](PLAN-A-strategy-wiring.zh-CN.md)** | 策略层接线打通 | 让系统第一次产出真实建议 | `live.py` 策略装配段 + 新 `action_line.py` + `tests/integration/` | — |
| **[B](PLAN-B-capture-card-production.zh-CN.md)** | 采集卡路径可用化 | 9 字段全标定，采集卡也能出建议 | `tools/capture_card_calibration/` + `configs/vision/` + `configs/platform/` | — |
| **[C](PLAN-C-strategy-capability.zh-CN.md)** | 策略能力扩张 | 补 7/8 人桌与翻后 | `src/poker_engine/strategy/` | A |
| **[D](PLAN-D-delivery-readiness.zh-CN.md)** | 服务端与发布就绪 | 暴露开关、补测试、收尾 UI、对齐发布门槛 | `server.py` / `app.py` + 依赖 + UI + 发布流程 | — |

---

## 2. 核心诊断（三句话）

1. **ABSTAIN 是按设计，不是 bug。** `architecture.md:66` 明写"缺合格 Provider 时只输出 ABSTAIN"——管道按设计接好了，缺的是可发布的策略资产。
2. **但「该放开的没放开」。** `live.py:734` 是 `StrategyOrchestrator(StrategyRouter())` 空参，连**已验证可用**的 Heuristic Provider 都没注册。
3. **还藏了一个阻塞。** `LiveStrategySession` 没传 `action_line_resolver`，而 `provider.py:288` 硬性要求 `action_line is not None` → **光注册 Provider 不够**，必须先实现行动线解析器。这是本轮新发现。

---

## 3. 关键现状数据（均为实跑，非推断）

| 项 | 数值 | 位置 |
|---|---|---|
| 回归基线 | **2148 passed / 0 failed / 2 skipped / ~24s** | ⚠️ 需加 `-v` 才看得到统计行 |
| 必需字段 | `("hero_cards","street","pot","stacks","action")` + 翻后 `board_cards` | `strategy_live.py:38` |
| ADB 标定字段 | 9 个（action, actor, amount, board, card, dealer, occupancy, stack, street） | 实跑 |
| 采集卡标定字段 | **仅 `card`** | 实跑 |
| Provider 覆盖 | heuristic `{6,9}` / blueprint `{2}` / gtopen `2–9` | 见分册 C |
| 翻后策略 | **零** | 全库搜无一命中策略层 |
| 端到端测试 | **零** | 同时 import 感知与策略的测试文件零命中 |

---

## 4. 冲突边界契约（四板块并行时的约定）

| 边界 | 约定 |
|---|---|
| **A ↔ C** | C 只修改 A 建立的 `build_strategy_router()` **函数体**（往元组追加 Provider），**不改函数签名、不改调用方、不另设注册点** |
| **A ↔ B** | 无重叠。若 B 需动 `live.py`，只能动标定加载段，**不得碰策略装配段 733-741** |
| **A ↔ D** | 无重叠。D 改 `server.py` / `app.py` CLI，A 不碰 server |
| **B ↔ C** | 完全无重叠 |
| **B ↔ D** | D1 的 `--source` 开关要等 B 完成才有真机意义，但代码不冲突 |
| **C ↔ D** | 完全无重叠 |
| **基线数字** | D2 会更新回归基线（2148 → 2154）。**由 D 统一维护**，A/B/C 引用时以 D2 更新后的数字为准 |

---

## 5. 执行顺序建议

```
阶段 1（并行）
  ├── A 策略接线打通 ──────► 系统第一次出建议（6 人翻前 unopened）
  └── B 采集卡可用化 ──────► 采集卡 9 字段全标定

阶段 2
  ├── C1 GTOpen 接入 ──────► 补 7/8 人桌（依赖 A）
  └── D1/D2 服务端开关 + 测试基建（可与阶段 1 并行）

阶段 3
  ├── C2 翻后策略（C2.1 → C2.2 → C2.3，每期独立验收）
  └── D3/D4 UI 收尾 + 真机验证

阶段 4
  └── D5 发布门槛 R0–R6
```

**推荐先做 A + B**：完成后你能**在真实设备上第一次看到建议**；C2（翻后）是最大的能力建设，建议单独评估后再启动。

---

## 6. 全项目红线（四板块共同遵守）

- ❌ **不做任何自动点击、下注或控制客户端** —— 人永远是唯一操作者
- ❌ **不把 6/9 heuristic 宣称为多人 GTO** —— `architecture.md:64` 硬性禁止；GTOpen 输出也必须标 `HEURISTIC`
- ❌ **不复用旧平台的 ROI / 坐标 / 阈值 / 模板** —— 新平台证据必须独立生成
- ❌ **不为拿绿灯而删断言、扩容差、跳场景** —— 发布门槛 11.1 明令禁止
- ❌ **不接 GitHub / CI / 远程服务** —— 当前阶段全部本地完成
- ✅ **失败即关闭** —— 证据缺失返回 None/UNKNOWN，绝不猜

---

## 7. 待你确认后即可开工

计划已完备。确认后我按 **A → B → C1 → D** 的顺序推进，A 板块可立即开工（改动明确、风险最低、收益最直接）。
