# Vision Engine（Task 7B）

感知层核心：`Frame + TableMap + Vision 配置 → RawObservation`。

## 架构

- `VisionEngine` 只编排，不实现识别算法，不泄漏 OpenCV/Paddle 到 Core。
- 可替换 detector/adapter Protocols：`CardRecognizer` / `AmountRecognizer` / `ActionRecognizer` / `BoardSlotDetector` / `StreetDetector` / `ConfidenceCalibrator`，以及 Android 专用的 slot marker / Hero turn recognizer。

## 模块

| 文件 | 职责 |
|---|---|
| `protocols.py` | Protocols + 不可变识别结果 dataclass |
| `card_layout.py` | `BoardSlotLayout`(5) / `HeroSlotLayout`(2)，归一化子 ROI |
| `asset_manifest.py` | `VisionAssetManifest`（版本绑定，JSON round-trip） |
| `calibration.py` | monotonic empirical bins + per-detector `abstain_floor` |
| `trace.py` | `RecognitionTrace`（memory-only） |
| `corner_glyph_recognizer.py` | 牌面识别（`CardRecognizer` 实现）：只读角标 rank/suit glyph，不做整牌模板匹配 |
| `amount_recognizer.py` | 数字模板（ChipAmount，禁 float） |
| `action_recognizer.py` | per-seat action 识别 |
| `slot_marker_recognizer.py` | Dealer 与空座 plus marker 的逐槽识别 |
| `hero_turn_recognizer.py` | Hero 蓝色操作区检测，只表达当前轮到 Hero |
| `board_slot_detector.py` | 5 board slot CARD/EMPTY/UNKNOWN |
| `street_detector.py` | street 派生（精确 UNKNOWN/CONFLICT 规则）+ raw_score |
| `engine.py` | `VisionEngine` 编排 |

## 关键边界

- **平台隔离**：Android 与 H5 的 TableMap、slot layout 和校准证据完全分开。相同 WePoker 牌面美术可通过 `template_source` 复用 rank/suit 模板，但不得据此复用 ROI 或置信度。
- **当前 Android 证据**：234 张 1440×2560 ADB 帧已用于 board/street/pot/stack/dealer/action/occupancy/actor 的逐字段标定。occupancy 在 34 个稳定状态的 272 个槽位上全部正确；Hero actor 在 33 个明确操作帧命中，并对其余 201 帧拒识。stack、Dealer、action 和 occupancy 都保留 visual-slot 语义，随后由版本化 mapping 转换。88 分钟 H.264 录像只提供时序/压缩验证，不替代 raw ADB 阈值证据。
- **Hero 定位**：优先使用 Android 固定 ROI；弹窗、结果动画等导致牌面上移时，使用仅限画面下部中央的双白牌动态定位。仍要求两帧确认后才写入新手牌。

- **Street**：5 视觉 board slot 位置派生（EEEEE/CCCEE/CCCCE/CCCCC），非标准模式 → CONFLICT，任一 UNKNOWN → UNKNOWN；与 board_cards 交叉校验。
- **Bet Size**：scalar `bet_size` 仅当恰好一个全局 BET_SIZE ROI（Task 6 契约已结构性保证：BET_SIZE 强制 slot_id=None + 唯一键）。
- **Confidence**：raw score ≠ confidence；per-detector 校准 → `[0,1]`；`abstain_floor` 非 Task 5 阈值。
- **Action / actor**：seat-rendered action glyph 表示已经完成的动作；Hero 蓝色操作区表示当前轮到 Hero。二者语义不同，状态层以 action glyph 的 slot 作为完成动作 actor，并对持久 glyph 去重。对手当前计时圈尚无独立校准时保持 UNKNOWN。
- **确定性**：模板一次初始化；合成 fixture 确定性。

## 不进入

Equity / Strategy / Solver / Decision / LLM / State mutation / player identity 映射。
