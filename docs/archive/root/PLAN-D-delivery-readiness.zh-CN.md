# 板块 D · 服务端与发布就绪

> 把已打通的能力**暴露到服务端**、补测试基建、收尾 UI 遗留、对齐发布门槛。
> 可与板块 A/B **并行**推进。
> 状态：待开工 · 编制 2026-09-06

---

## 1. 目标

1. 采集卡路径在服务端层可选（现在根本没暴露）
2. 测试基建补齐，`tests/desktop` 那 6 个阻塞测试纳入回归
3. UI 遗留项收尾
4. 真机验证 + 对齐 `R0–R6` 发布门槛

**不在本板块范围内**：策略注册与行动线（板块 A）、标定与识别器（板块 B）、策略能力（板块 C）。

---

## 2. 现状

### 2.1 采集卡路径在服务端层未暴露

`live_analysis_stream` 的签名**已经支持** `source`：

```python
async def live_analysis_stream(
    device_serial=DEFAULT_DEVICE_SERIAL,
    interval_seconds: float = 1.0,
    source: str = "adb",
    *, device_index: int = 0, api: str = "MSMF", normalization=None,
)
```

但 `server.py:135-143` 的 CLI **只有两个参数**：

```python
parser.add_argument("--device-serial", default=DEFAULT_DEVICE_SERIAL, ...)
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()
run(port=args.port, device_serial=args.device_serial)
```

`app.py:77-81` 同样只有 `--device-serial`。**后端能力已就绪，只是没有开关。**

### 2.2 测试基建缺口

| 项 | 现状 |
|---|---|
| `tests/desktop` | 缺 `fastapi`，阻塞 2 个文件 / **6 个测试** |
| `test_advice_view.py:345` | 2 个 skip 之一，**也是缺 fastapi** |
| 端到端测试 | 全库零命中（板块 A 补） |
| 回归基线 | **2148 passed / 0 failed / 2 skipped / ~24s** |

⚠️ 复现基线注意：pytest 9.1.1 + `addopts = "-q"` 会吞掉统计行，需加 `-v` 才看得到。

### 2.3 UI 遗留项（来自 2026-09-05 视觉改造）

1. 断线后无「立即重试」按钮，只能等自动重连
2. `waiting` 相位时 advice 面板隐藏，无「等待中…」占位
3. EV 数值对比展示：三个 action 的 EV 都是 `null`（正确遵守"未提供不显示 0"），但与"有 EV 的行"对比不明显
4. 真实键盘 `Tab` 焦点环未验证（headless 截不到，`states.html` 用 class 模拟）
5. AA 平台布局未覆盖（与板块 B 相关，但采集卡 AA 尚未启动）

---

## 3. 改动清单

### D1 · 服务端暴露采集源开关

`server.py` 与 `app.py` 的 CLI 增加透传参数（后端签名已支持，无需改逻辑）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--source` | `adb` | `adb` / `capture-card` |
| `--device-index` | `0` | UVC 设备索引 |
| `--api` | `MSMF` | 采集后端 API（⚠️ 采集卡必须 `MSMF`，DSHOW 实测全黑） |

注意 `build_pipeline` 的平台校验规则：
- `source="capture-card"` 且 platform/layout 为默认 → 自动切到 `CAPTURE_CARD_PLATFORM`
- `source="capture-card"` 但 platform 不是采集卡配置 → `LiveCaptureError`
- `source="adb"` 但 platform 是采集卡配置 → `LiveCaptureError`

### D2 · 补测试基建

1. 安装 `fastapi`（`pyproject.toml` 的 `desktop` extra），解阻塞 6 个测试
2. 回归基线更新为 `2154 passed / 0 skipped`（2148 + 6，并消除 1 个 fastapi 相关 skip）
3. 记录新基线，作为后续所有板块的回归门槛

### D3 · UI 遗留收尾

按优先级：

1. **断线重试按钮**（用户可见的功能缺口，优先）
2. **`waiting` 相位 advice 面板占位**
3. EV 对比展示优化：让 preferred action 的 EV 有值、其余 `null`，以体现对照
4. 真实键盘焦点环：起 agent-browser 做真实 `Tab` 遍历验证（headless 截图做不到）

⚠️ 约束：UI 改动必须通过契约测试 `test_ui_contains_all_advice_contract_targets_and_no_inline_html_sink`（8 个 advice id、禁止 `renderAdvice` 后用 `innerHTML`、token 化样式、双语文案）。

### D4 · 真机端到端验证

- 干净安装验证（**本地打包成功 ≠ 干净安装成功**，`strategy-regression-test-matrix.md` 11.2 明确要求）
- 30 分钟连续运行
- 拔插恢复
- 采集卡真机（需板块 B 完成）

### D5 · 发布门槛对齐

`docs/strategy-regression-test-matrix.md` 第 11 节现成要求：

**PR 门槛（11.1）**
- `R0 + R1 + R2` 全部通过，受影响场景的 `R3` 通过
- 新需求有 Requirement ID / Function ID / Test ID / fixture
- 新 Provider 有 capability contract、Golden parity、source version、asset hash
- **不得通过删除断言、扩大容差或跳过失败场景获得绿灯**

**发布候选（11.2）**
- `R0–R5` 全通过 + 机器可读结果 + 性能报告
- `R6` 在目标系统完成
- 能力清单只包含有 Golden/Replay、延迟和已知限制证据的场景
- **当前发布不具备的目标能力必须继续明确标记为 planned**

**识别/UI 合并门槛（11.3）**
- 需版本化 platform/layout mapping、授权 raw-frame Replay、逐字段报告
- **Synthetic Observation、静态截图或单一总置信度不能替代 raw-frame Replay**

---

## 4. 验收标准

- `--source capture-card` 可正常启动并选中 UVC 后端（需板块 B 完成后真机验证）
- `tests/desktop` 6 个测试纳入回归，新基线稳定
- UI 遗留项 1–3 完成，契约测试与双语检查通过
- 发布门槛清单逐项勾选，有机器可读结果

---

## 5. 与其他板块的边界

| 板块 | 关系 | 约定 |
|---|---|---|
| A 策略接线 | 无代码重叠 | D 改 `server.py` / `app.py` CLI；A 改 `live.py` 策略装配段 |
| B 采集卡 | D1 的开关要等 B 完成才有真机意义 | B 改 `tools/` + `configs/`；D 改 CLI 透传 |
| C 能力扩张 | 无重叠 | C 改 `src/poker_engine/strategy/` |

⚠️ **唯一潜在冲突点**：D2 改回归基线数字，A/B/C 的验收标准都引用了基线。约定由 **D 统一维护基线数字**，其他板块引用时以 D2 更新后的数字为准。

---

## 6. 风险

| 风险 | 说明 | 应对 |
|---|---|---|
| fastapi 引入传递依赖 | 可能与其他包冲突 | 装在隔离 venv，验证后记录版本 |
| 干净安装失败 | 打包遗漏资源（模板、标定 JSON、card_heads.npz） | D4 必须在**目标系统**验证，不能只看本地 |
| raw-frame Replay 涉及隐私 | 11.3 门槛要求原始帧 Replay | 需隐私审查流程，属前置条件 |
| UI 改动破坏契约测试 | 契约测试硬约束 5 条 | 改前先读 `tests/strategy/test_advice_view.py` |

---

## 7. 明确不做

- ❌ 不做 CI/CD、不接 GitHub、不配远程仓库（按当前阶段要求，全部本地）
- ❌ 不为拿绿灯而删除断言、扩大容差或跳过失败场景（11.1 明令禁止）
- ❌ 不把未具备的能力写进能力清单（必须标记 planned）
