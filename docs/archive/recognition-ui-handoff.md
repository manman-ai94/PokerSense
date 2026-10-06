# WPK 识别与 Live Coach UI 开发交接

> 面向：负责 `h5.wpk.com` 牌桌识别和 Live Coach UI 的开发伙伴
> 协作分支：`codex/multiplayer-strategy-system`
> 策略基线：`7b573e4` 及其后续提交
> 文档日期：2026-08-23

## 1. 先看结论

策略、状态、多人 Equity、Router、Advice 和大部分自动化测试已经存在。你不需要实现
Solver，也不需要在识别层决定 Fold/Call/Raise。竖屏雷电 Android 现已能稳定提供
Hero、board、street、总底池、8 槽 occupancy/stack、Dealer、Hero 当前行动回合和完成动作；
版本化 mapping 已能推导 canonical seat/position，完成动作也能在 stack/pot 守恒时进入 history。
当前真正阻断发布闭环的是授权 raw-frame Replay、对手当前 actor 和复杂 all-in/side-pot/漏帧边界，
以及缺少匹配实际人数的合格策略 Provider；UI 还需用真实 `DesktopFrame` 验收四种 Advice 状态。

双方约定的边界是：

```text
你的识别模块
  → RawObservation（候选事实 + 每字段置信度/证据）
已有状态/策略模块
  → PokerState + StateEvent[] + DecisionContext + Advice
你的 UI 模块
  → 只渲染 DesktopFrame，不自行推断状态或策略
```

## 2. 当前已经有什么

| 模块 | 当前能力 | 主要位置 | 你是否需要修改 |
|---|---|---|---|
| Capture | macOS/Windows 窗口捕获、显式 window index、帧序号 | `src/poker_engine/perceptual/capture/` | 只在 WPK 窗口身份或布局选择需要时修改 |
| Hero cards | WPK Hero 两张底牌真实识别、两帧确认 | `src/poker_engine/perceptual/`、`configs/vision/wepoker/` | 继续补 Replay，不要降低已有门槛 |
| Android Board/Street | 5 个独立牌位、占位/牌面双信号、街道推导 | `configs/vision/wepoker_android/`、`desktop/live.py` | 补 raw-frame Replay；过渡帧不得降阈值 |
| Android Pot | 固定总底池 ROI、深色底白字 OCR、负样本拒识 | 同上 | 补边池/动画 Replay；不与 stack 共用证据 |
| Android Occupancy/Stack | 8 个固定 visual slot、独立 plus-marker/字模校准、空座/覆盖层拒识 | 同上 | 补 raw Replay；不得借其他字段置信度 |
| Android Dealer | 8 个独立搜索窗、唯一 marker visual slot、隐藏态拒识 | 同上 | 已通过版本化 mapping 转 canonical seat |
| Android Actor/Action | Hero 当前蓝色操作区；8 槽完成动作字形 fold/check/call/bet/raise/all-in | 同上 | 对手当前计时圈与复杂金额边界补 raw Replay |
| Observation contract | 每字段 value/confidence/source/evidence/timestamp/status | `src/poker_engine/core/observation.py` | 按合同输出，不要直接写状态 |
| Temporal Consensus | 所有字段和 slot 的连续帧确认、冲突/漏帧处理 | `src/poker_engine/realtime/temporal_consensus.py` | 通常无需修改；提供稳定候选即可 |
| Slot→Seat mapping | 版本化 platform/layout、occupancy/stack/action/actor/dealer slot 映射 | `src/poker_engine/state_engine/platform_mapping.py` | Android 8 槽实测 config 已接入；未知布局拒答 |
| State/Event Engine | 2–9 人状态、行动重建、合法动作、主池/边池、原子版本 | `src/poker_engine/state_engine/` | 不在 Vision 中复制这些逻辑 |
| DecisionContext | 位置、筹码、底池、行动历史、合法动作和质量门 | `src/poker_engine/strategy/state.py` | 由已有代码构建 |
| Equity | HU/multiway exact、Monte Carlo、CI、cache、side-pot share | `src/poker_engine/strategy/` | 不在 UI 重算 |
| Strategy | Provider、Router、Fast/Slow、GTOpen 研究 Adapter、拒答 | `src/poker_engine/strategy/` | 不属于识别/UI任务 |
| Live binding | State/quality/history 绑定到 Advice；旧结果丢弃 | `src/poker_engine/desktop/strategy_live.py` | 联调时接入真实输入 |
| UI wire | 原子 `DesktopFrame`，包含 analysis 和可选 Advice | `src/poker_engine/desktop/serialize.py` | UI 必须只消费该合同 |
| Advice view | READY 才暴露动作；其他状态隐藏动作 | `src/poker_engine/desktop/advice_view.py` | 按字段渲染，不改策略语义 |
| Mock/Regression | 298 个策略 Mock；2–9 人、异常、拒答和过期测试 | `tests/fixtures/strategy/`、`tests/strategy/` | 新真实场景不得只用 Mock 替代 |
| Raw-frame Replay | hash、校准、授权、隐私和质量报告合同 | `src/poker_engine/replay/`、`docs/capture-replay.md` | 必须提交真实 WPK Replay 证据 |

当前正式发布版仍只保证 Hero cards 和翻牌前随机范围 Equity。上表中的策略能力位于开发
分支，尚未等同于发布能力。

## 3. 你需要完成什么

### 3.1 识别侧任务

按以下顺序做；P0 没完成前，不要把 UI 显示出策略动作作为完成标准。

| 优先级 | 任务 | 必须输出 | 关键验收 |
|---:|---|---|---|
| P0 | WPK 窗口和布局身份 | `platform_id`、`layout_id`、mapping/calibration version | 同标题窗口必须显式选择；布局不匹配时拒绝识别 |
| P0 | 2–9 座位几何 | 每个 visual `slot_id` 的稳定 ROI 和 seat mapping 配置 | 空座、入座、离桌、不同人数不串 seat |
| 已标定 | 座位占用 | `slot_occupancies: tuple[SlotObservation[bool], ...]` | 34 个稳定状态、272/272 槽位正确；过渡/覆盖保持 UNKNOWN |
| 已标定 | Dealer/Button | `dealer_pos: ObservationField[int]`，value 是 visual slot | 40/40 复核正确；mapping 已接入，raw Replay 待补 |
| 已标定 | 逐座位筹码 | `slot_stacks: tuple[SlotObservation[ChipAmount], ...]` | 80/80 复核正确；mapping 已接入，raw Replay 待补 |
| 部分标定 | Actor | `actor: ObservationField[int]`，Android 只表示当前轮到 Hero | 33/33 正样本命中、201 其他帧拒识；对手当前计时圈保持 UNKNOWN；完成动作 actor 由 glyph slot 决定 |
| 已标定 | 动作标签 | `slot_actions[]`，使用规范 `ActionType` | 45/45 人工复核正确；Hero 操作按钮和覆盖层拒识；持久 fold 由时序层去重 |
| 部分标定 | 行动金额 | actor stack delta + pot delta evidence | 两者守恒时才构造本次增量和 total-street amount；漏帧/side-pot 不猜 |
| 已标定 | Android Pot | `pot: ObservationField[ChipAmount]` | 总底池数值与负样本已测；side-pot 仍需 Replay |
| 已标定 | Android Street/Board | `street`、`board_cards` | flop/turn/river 张数一致；发牌动画不提前确认；仍需 raw Replay 发布证据 |
| P0 | 每字段质量 | confidence、source、evidence、timestamp、status | 每个字段独立；低置信度不能借 Hero 置信度升级 |
| P0 | 真实 Replay | 原始帧、配置、校准、逐帧 expected 状态和 hash | 通过 `docs/capture-replay.md` 的 raw-frame release gate |
| P1 | 多布局/缩放 | 分辨率、浏览器缩放、窗口尺寸对应的 layout profiles | 未知布局 fail closed，不套用最接近布局 |

### 3.2 UI 侧任务

| 优先级 | 任务 | 使用的输入 | 验收结果 |
|---:|---|---|---|
| P0 | 原子帧渲染 | 同一个 `DesktopFrame.analysis + advice` | 不组合两个不同 state version 的数据 |
| P0 | 四状态显示 | `READY/PARTIAL/ABSTAIN/STALE` | 只有 READY 显示动作；其余立即清空旧动作 |
| P0 | 动作建议 | `advice.actions[]` | 显示动作概率、推荐尺度、preferred；按概率排序 |
| P0 | EV 可用性 | 每个 action 的 `ev` 和 `ev_gap` | `null` 显示“未提供”，不能显示 0 |
| P0 | 来源和质量 | source/version、match kind/score、confidence | Exact、近似、Heuristic、人工输入视觉上可区分 |
| P0 | 限制和拒答 | assumptions、missing inputs、gate/rejection reasons | 用户能知道为什么没有建议 |
| P0 | Fast→Slow 更新 | 相同 hand/state/request 的后续 Advice | 原位升级；旧 request、换手和过期结果不闪回 |
| P0 | 断连和重连 | WebSocket 生命周期 | 断连立即隐藏动作；重连等待新原子帧 |
| P0 | 双语 | 已有中英文标签体系 | 新状态和错误原因不得只加一种语言 |
| P1 | 真实窗口验收 | 实际 WPK + Live Coach | 截图/录屏证明信息清楚、不遮挡牌桌、无状态闪烁 |

## 4. 识别输出合同

每帧必须构造一个完整 `RawObservation`。识别不到的字段也不能消失，应使用 `value=None`
和正确状态。示意结构如下，具体类型以源码为准：

```python
RawObservation(
    frame_seq=frame_seq,
    timestamp=aware_timestamp,
    hero_cards=ObservationField(...),
    board_cards=ObservationField(...),
    pot=ObservationField(...),
    stacks=ObservationField(...),          # 兼容字段
    bet_size=ObservationField(...),
    action=ObservationField(...),
    street=ObservationField(...),
    dealer_pos=ObservationField(...),      # visual slot
    actor=ObservationField(...),           # Android: current Hero actor
    slot_occupancies=(SlotObservation(...), ...),
    slot_stacks=(SlotObservation(...), ...),
    slot_actions=(SlotObservation(...), ...),
)
```

每个 `ObservationField` 至少应包含：

| 字段 | 规则 |
|---|---|
| `value` | 类型正确的候选值；不确定时为 `None` |
| `confidence` | 该字段独立的 0–1 实测质量，不是整帧统一分数 |
| `source` | recognizer/profile 的稳定名称和版本 |
| `evidence` | ROI、候选分数、frame/revision、必要的 OCR 原始证据 |
| `timestamp` | 带时区，并与帧一致 |
| `validation_status` | `VALID/LOW_CONFIDENCE/UNKNOWN/CONFLICT` |

注意：visual `slot_id` 不是玩家 seat，也不是 position。转换只能通过版本化
`PlatformSeatMapping` 完成。`slot_occupancies` 已进入 `RawObservation`、serialization、temporal、
mapping 和 Replay 合同；未知/冲突值不得用 stack 是否可读来静默替代。

## 5. UI 输入合同

UI 接收的顶层对象是：

```text
DesktopFrame
├── frame_seq
├── state: hand_id/state_version/street/hero_cards/board_cards/pot
├── equity: win_rate/tie_rate
├── confidence: overall_confidence/field_status
└── advice（可选）
    ├── status/show_actions/actions
    ├── strategy_source/strategy_version
    ├── match_kind/state_match_score/match_dimensions
    ├── confidence/ev_gap
    ├── rejection_reasons/gate_results/missing_inputs
    ├── assumptions/evidence/input_provenance
    ├── evidence_chain_id/evidence_complete/missing_evidence
    ├── expires_at
    └── identity: hand_id/state_version/request_id/player counts
```

必须执行的 UI 规则：

| 条件 | UI 行为 |
|---|---|
| `advice.show_actions == true` | 才能渲染动作 |
| `show_actions == false` | 清空所有旧动作和尺度 |
| `ev == null` | 显示未提供，不显示 0 |
| Advice identity 与 state 不同 | 视为 STALE；前端不得尝试修复 |
| `expires_at` 已过期 | 隐藏动作，即使最后一帧曾是 READY |
| 只有 Equity | 单独显示 Equity，不生成 Fold/Call/Raise |

当前 wire contract 只给每个动作的总频率和推荐尺度列表，还没有给每个尺度各自的频率。
这是策略输出合同的 Gap，由策略侧扩展；UI 不得平均分配或猜测。

## 6. 不要做什么

| 不要做 | 原因 |
|---|---|
| Vision 直接修改 `PokerState` | 会绕过 temporal、冲突检测和筹码守恒 |
| Vision 推导 position、合法动作或策略 | 这些属于状态/策略层 |
| UI 根据 Equity 阈值生成建议 | Equity 不是动作频率或 GTO |
| UI 保留上一帧 READY 动作 | 新状态可能已经发生，存在误导风险 |
| 对 UNKNOWN 使用上一帧值补齐 | 会把过期事实伪装成当前事实 |
| 同标题窗口自动选第一个 | 用户有两个同名 WPK 窗口，必须显式 index |
| 用 Synthetic 数据声明真实识别完成 | 发布需要授权 raw-frame Replay |
| 在未审查许可前打包 GTOpen | 当前只允许本地研究 Adapter |

## 7. 建议的开发与联调顺序

| 阶段 | 识别侧 | UI 侧 | 联调输出 |
|---:|---|---|---|
| 1 | 固定一个 WPK layout 和 slot mapping | 用现有 Mock DesktopFrame 完成四状态 | mapping 配置 + UI snapshots |
| 2 | dealer、stack、actor、action/amount | 显示 missing/gate reasons | RawObservation sequence |
| 3 | pot、street、board 和动画抑制 | 完成 Fast→Slow/STALE 顺序 | Synthetic E2E |
| 4 | 注册授权 raw-frame Replay | 用真实 WebSocket sequence | Replay quality report |
| 5 | 策略侧启用实际桌型和 Provider | 真实窗口视觉验收 | WPK→Advice→UI 录屏和机器报告 |
| 6 | 扩展 3–9 人布局 | 多人位置/side-pot/来源显示 | 按人数发布能力矩阵 |

## 8. 提交前验收清单

### 识别改动

- [ ] 新字段进入 `RawObservation`，并有类型、序列化和 UNKNOWN/CONFLICT 测试。
- [ ] slot mapping 有 platform/layout/version，未映射 slot 必须拒绝。
- [ ] 每个字段有独立 confidence 和 evidence。
- [ ] 动画、漏帧、重复帧、换手、空座和 OCR 异常有用例。
- [ ] 使用真实 raw-frame Replay；没有 Replay 时明确标记 experimental。
- [ ] 不改变未校准字段的生产声明。

### UI 改动

- [ ] READY、PARTIAL、ABSTAIN、STALE 都有 snapshot/序列测试。
- [ ] 非 READY、过期、换手、断连时清空动作。
- [ ] EV `null`、拒答原因、来源、版本、match、confidence 可见。
- [ ] 相同状态 Fast→Slow 原位更新；旧 Slow 不闪回。
- [ ] 中英文标签同步。
- [ ] 用真实 DesktopFrame sequence 验收，不只使用前端手写对象。

### 共同 E2E

- [ ] 固定代码 commit、WPK layout、calibration hash、Replay hash、Provider/version、UI build。
- [ ] `frame_seq + hand_id + state_version + request_id` 全链一致。
- [ ] 保存机器可读结果、截图/录屏和 p50/p95/p99 延迟。
- [ ] macOS Screen Recording 权限和窗口 index 已记录。
- [ ] 干净安装验收与本机开发运行分开记录。

## 9. 本地验证命令

使用 Python 3.11–3.13：

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m flake8 src tests
./.venv/bin/python tools/generate_strategy_mock_fixtures.py --check
node --check ui/app.js
git diff --check
```

macOS Quartz 测试依赖运行该 Python 可执行文件的 Screen Recording 权限。权限失败必须单独
记录，不能把对应测试描述成通过。

## 10. 相关文档

| 文档 | 用途 |
|---|---|
| `architecture.md` | 整体模块和数据流 |
| `docs/product-requirements.md` | 产品边界、输入输出和双方责任 |
| `docs/strategy-requirements-matrix.md` | 策略功能和字段需求 |
| `docs/strategy-regression-test-matrix.md` | 测试层级、E2E 和发布门槛 |
| `docs/capture-replay.md` | 真实 WPK Replay 的格式和证据要求 |
| `docs/core-contracts.md` | 不可变核心数据合同 |
| `docs/state-engine.md` | 状态转换边界和拒答规则 |

如果识别结果无法放入 `RawObservation`，或者 UI 需要的数据不在 `DesktopFrame`，应先提出
合同变更，而不是在两个模块之间增加未经测试的临时 JSON。
