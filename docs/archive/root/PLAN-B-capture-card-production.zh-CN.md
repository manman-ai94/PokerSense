# 板块 B · 采集卡路径可用化

> 让采集卡路径从「仅 `card` 可用」变成 9 字段全标定，从而也能产出建议。
> 可与板块 A **并行**推进，无代码重叠。
> 状态：待开工 · 编制 2026-09-06

---

## 1. 目标

补齐采集卡平台（`wepoker_android_capture_card`）缺失的识别器、生产资产、ROI 与标定量，使：

1. 实跑 `load_measured_calibrations()` 返回 **9 个字段**（现在只有 `['card']`）
2. 五个必需字段（`hero_cards` / `street` / `pot` / `stacks` / `action`）全部可达 `valid`
3. 采集卡路径端到端产出 `READY` 建议

**不在本板块范围内**：Provider 注册与行动线（板块 A）、7/8 人与翻后策略能力（板块 C）、服务端开关（板块 D）。

---

## 2. 现状：瓶颈是「生产资产断层」，不是标注

### 2.1 字段级现状（实跑）

| 字段 | 离线识别器 | 生产接线 | 备注 |
|---|---|---|---|
| `card` | 融合 MLP | ✅ 已标定 | `card_fused` 178/178，零假 VALID |
| `stack` | `stack_auto.py` + `stack_transcribe.py` | ❌ | 离线已验证 |
| `occupancy` | `seat_reader.py` | ❌ | 离线 893 对 / 0 错 |
| `dealer` | `seat_reader.py` | ❌ | 离线 576/576 |
| `action` | `action_reader.py` | ❌ | 离线已验证 |
| **`amount` (pot)** | **无** | ❌ | **缺识别器** |
| **`actor`** | **无** | ❌ | **缺识别器** |
| **`street`** | 无（应由 board 派生，`live.py:550`） | ❌ | **缺派生逻辑** |

### 2.2 三个真正的断层

1. **生产模板资产全部缺失。** `configs/vision/wepoker_android_capture_card/` 只有 `board_slot_layout` / `hero_slot_layout` / `card_heads.*`。`_load_templates`（`live.py:443/458/480/490/502`）在无模板时直接退化为 `None` → 字段恒 UNKNOWN。缺：`digit/` `stack_digit/` `action_glyph/` `dealer/` `marker.png` `empty_slot/` `plus.png`
2. **ROI 缺失。** platform rois 有 20 个，但**无 dealer / occupancy / street ROI**（stack / action / pot / hero / board / actor 有）
3. **缺标定落地工具。** `card_fused` 那块是手工写进 `calibration.json` 的，没有「离线评测 → 自动生成字段块」的工具

### 2.3 数据基础是够的

- `capture_card_calibration_20260903/labels/frames.jsonl`：**367 帧**、2936 条槽位标注
- 覆盖 hero_cards 100、board 74、pot 100、street 101、occupancy 957、dealer 576、stack 349、action 94、actor 55
- 实跑 `coverage --root <数据集>` → **stage G met**

**结论：不缺标注，缺的是把标注转成生产资产与标定的工具链。**

---

## 3. 改动清单

### B1 · 补 `pot` 识别器

新建 `tools/capture_card_calibration/pot_reader.py`，从 pot ROI 做数字 OCR。需与 `stack_auto.py` 共享数字识别基础能力，避免两套实现。

### B2 · 补 `actor` 识别器

从已有的轮次证据（蓝圆「N 跟注」= 激活决策，记忆中有实测词表）判定当前行动者。注意与 `viewpoint.py`（视角判定）区分开。

### B3 · 补 `street` 派生

在 live 路径接入 `live.py:550` 的 board → street 派生逻辑，并单独测试（空 board=preflop / 3 张=flop / 4 张=turn / 5 张=river）。

### B4 · 生成生产模板资产

从私有数据集切图生成：`digit/` `stack_digit/` `action_glyph/` `dealer/` `marker.png` `empty_slot/` `plus.png`，落到 `configs/vision/wepoker_android_capture_card/`。

⚠️ **平台隔离红线**：不得复用 LDPlayer 平台的模板。新平台的几何与阈值证据必须独立生成。

### B5 · 补 ROI 与布局配置

在 platform 配置补 `dealer` / `occupancy` / `street` ROI，并补 `dealer_slot_layout.json` / `empty_slot_layout.json`。

### B6 · 建标定落地工具（关键复用件）

新建工具：读标注 → 跑识别器 → 按 hand 隔离的 splits 算 `samples` / `correct` / `floor` / `ceiling` → **自动生成 `calibration.json` 字段块**。

`MeasuredCalibration` 格式要求（`perceptual/vision/calibration.py:132-181`）：

```json
"stack": {
  "samples": 80, "correct": 80,
  "readable_score_floor": 0.83,
  "unreadable_score_ceiling": 0.381,
  "source": "测量过程描述（非空）"
}
```

- 约束 `0 <= ceiling < floor <= 1`
- confidence 是 **Wilson 95% 单侧下界**，不是 correct/samples（62/62 只支持 95.8%，178/178 才得 0.985）
- `floor` = 最低正确样本 raw 分；`ceiling` = 最高被拒负样本 raw 分

> 这个工具做完，后续新平台（如 AA）标定可直接复用。

---

## 4. 验收标准

- 实跑 `load_measured_calibrations()` 返回 9 个字段，每个都有 Wilson 下界且满足 `0 <= ceiling < floor <= 1`
- 新增 `tests/vision/` 用例覆盖 pot / actor / street 识别器，含失败关闭路径
- 采集卡路径端到端产出 `READY` 建议（需板块 A 已完成）
- 回归基线不下降：`2148 passed / 2 skipped`

---

## 5. 与其他板块的边界

| 板块 | 关系 | 约定 |
|---|---|---|
| A 策略接线 | **无代码重叠，可并行** | B 只改 `tools/capture_card_calibration/` + `configs/vision/` + `configs/platform/`；A 改 `live.py` 策略装配段 + `action_line.py` |
| C 能力扩张 | 无重叠 | C 改 `src/poker_engine/strategy/` |
| D 服务端 | B 完成后 D 的 `--source` 才有意义 | D 只改 `server.py` |

⚠️ **唯一潜在冲突点**：若 B 需要调整 `live.py` 的 `load_calibration` / ROI 装配段，需与 A 的改动（策略装配段 733-741）分在不同函数，避免同一文件同一区域并发修改。

---

## 6. 工作量与风险

粗略分配：**模板/布局资产生成 40% · 人工复核标注与跑出可辩护阈值 35% · 接线与回归 25%**

| 风险 | 说明 | 应对 |
|---|---|---|
| 阈值辩护不足 | Wilson 下界对样本量敏感，小样本字段（actor 仅 55 条）可能拿不到高置信 | 先补标注到可辩护量级，或如实接受低阈值并让门更保守 |
| 模板切图质量 | 从视频切图受 VFR / letterbox 影响 | 复用已验证的归一化流程，切图后人工抽检 |
| 平台隔离违规 | 复用旧平台模板会让标定失去意义 | B4 明确禁止，Code Review 检查项 |
| 依赖私有数据集 | 数据集不进 Git | 工具产出物（模板、标定 JSON）进仓库，脚本与数据集留在本地 |

---

## 7. 明确不做

- ❌ 不复用 LDPlayer/ADB 平台的任何 ROI、坐标、阈值、模板（架构红线）
- ❌ 不改动 Provider 与策略能力（属板块 C）
- ❌ 不做 AA 平台（本板块只做 wepoker 采集卡；AA 是独立平台，需独立走一遍）
