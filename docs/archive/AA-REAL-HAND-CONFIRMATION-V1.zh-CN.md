# AA 真实手牌确认 V2（TARGET-S）

本文件保留原 V1 路径，现描述 `aa-real-hand-confirmation-v2`。V1 是未合并
PR #32 的旧合同；V2 修复 Issue #27 `5762748242` 的六组 P0。真实事实的唯一
验收路径仍是 `aa_real_hand_confirmation` 中的人工确认 + 绑定证据 + append-only
修订。此文档不声明真实手牌已验收、策略已验证或可实战使用。

## 1. 权威与范围

| 层 | owner | 与真实手牌验收的关系 |
| --- | --- | --- |
| 机器观测/候选 | `aa_semantics` | `UNKNOWN`、`VISIBLE_LABEL_CANDIDATE`、`PRICE_DERIVED_CANDIDATE` 不自动变成事实 |
| 开发标注/曝光 | `tools.aa_annotation_records`（#31） | annotation row 不是确认记录，不作为本模块事实源 |
| 人工真实手牌确认 | `aa_real_hand_confirmation` | 唯一 TARGET-S acceptance authority |
| holdout gold/训练 | 独立 freeze 治理 | 无自动 C→gold 路径；freeze adapter 未接入 |

`AAHandInput` / `aa_analysis_records` 保留原行为及
`MANUAL_HYPOTHESIS_OFFLINE_NOT_LIVE_ADVICE` scope；其 `human_confirmed`
表单值、AAReviewDesk note/verdict 均不能生成真实验收 receipt。
`DO_NOT_MUTATE_MACHINE_CANDIDATE` 保留：人工复核可以与机器候选不同，但不能
改写候选的原值或 provenance，也不能将开发标注直接升级为 confirmed fact。

TARGET-S 当前只接受：6–8 个完整 dealt seats、恰好三名 ACTIVE、Hero 为 river
first actor、所有 ALL_IN 为空、无既存边池、本街投入为零、无未完成动作，且牌局已结束。
逐条 river action 确认、Hero 后手、ALL_IN/一般边池、PHH 全手、策略优化均不在此合同内。

TARGET-P/PHH 需要 forced bets 和 preflop 起的完整 action 序列；stack delta
只给聚合 commitment，不能拆成 ante/SB/BB/straddle/逐街 action。
`TARGET_S_REAL_HAND_CONFIRMED` 不表示 `TARGET_P_PHH_READY`。

## 2. V2 证据 descriptor 与公共接口

`confirm_fact(store, *, hand_id, observed_epoch, capture_session_id, source_ref,
marker, source_frame, evidence_digest, evidence_descriptor, fact_key, value,
reviewer, snapshot_digest=None, supersedes=None, audit_note=None, recorded_at=None)`
写入一条确认。identity/marker/frame 必须与 descriptor 相符；不从机器输出补字段。

Descriptor 的**精确 schema**如下；不得增加未知键或省略键：

```json
{
  "schema_version": "aa-real-hand-evidence-v2",
  "hand_id": "synthetic-hand-1",
  "observed_epoch": "synthetic-epoch-1",
  "capture_session_id": "synthetic-session-1",
  "source_ref": {"recording_id": "synthetic-recording-1"},
  "marker": "RIVER_START",
  "window_start_frame": 200,
  "window_end_frame": 202,
  "frames": [
    {"source_frame": 200, "content_sha256": "<64 lowercase hex>"},
    {"source_frame": 201, "content_sha256": "<64 lowercase hex>"},
    {"source_frame": 202, "content_sha256": "<64 lowercase hex>"}
  ],
  "stable": true,
  "boundary_continuity": true
}
```

- `source_ref` 只允许 `media_sha256` 和 `recording_id`，至少一项存在；存在的项
  必须有效。`media_sha256` 为 64 位 lowercase hex，`recording_id` 为非空字符串。
- frame 均为非负整数；frames 按 frame 严格升序、无重复、位于窗口内且含首尾。
  每项 `content_sha256` 标识实际审阅的本地 frame/evidence 内容；单帧窗口也合法。
- `evidence_digest = digest(evidence_descriptor)`，使用模块 canonical JSON SHA256。
  row 的 `snapshot_digest` 必须为同一 descriptor seal；省略时由 writer 赋该值。
  `source_frame` 必须出现在 descriptor 的 frames 中。
- `stable`、`boundary_continuity` 都必须明确为 `true`。这是人的证据与边界连续
  attestation，不能由 JSON 字段、机器候选或图片文件名推断。
- descriptor 绑定 hand/epoch/session/source/marker/window/content。复制旧 descriptor
  到新 identity、只粘贴一个 hash、改变 descriptor 后复用旧 hash 均拒绝。
- 本地无密钥 checksum 证明内容与绑定的一致性，不证明操作人说了真话，也不是对任意
  磁盘攻击者的认证。本模块不读取图片、调用视觉模型或自动判定 frame 内容。

每条 immutable row 另存 confirmation ID、source digest、结构化 value、reviewer、
带时区 timestamp、revision、supersedes、`provenance=human_confirmed` 和 audit_note。
自由文本只允许在 audit_note 中；它永远不是事实值。
JSONL 只按物理换行分隔记录；审计字符串内合法的 U+2028、U+2029、U+0085
会原样保存、参与摘要并可继续修订，不被当成额外记录。空白物理记录仍拒绝。

## 3. Marker 角色、时间和 stack-delta 区间

| Marker | 绑定的事实 | 时点 |
| --- | --- | --- |
| HAND_START | opening_stacks、seat_set、dealer_button_seat、table_rules | 本手第一笔 forced-bet 借记前的最后稳定窗口 |
| RIVER_START | Hero 座位/手牌、board、ACTIVE/FOLDED/ALL_IN、action_order、river_start_stacks、pot_display、hero_is_first_river_actor、street_wagers_zero、no_side_pot、no_pending_action、straddle_posted_this_hand、stack_delta_assertions | 第五张公共牌稳定，任何 river action 尚未发生 |
| PAYOUT | ended_hand_confirmed、other_fees | 手已结束、结算稳定；不替代 river 起点证据 |

同一 marker 的有效事实必须绑定**同一个稳定窗口 descriptor**；不要求每个事实
选同一张物理帧。严格时序为 `HAND_START.end < RIVER_START.start` 且
`RIVER_START.end < PAYOUT.start`。marker 错角色在写入/恢复拒绝；窗口不相容或
时序矛盾时 view 阻止 commitment/history 派生，不能只在最终 receipt 降级。

HAND_START 可以是上一手结算后、下一手强制下注前的 inter-hand 窗口。
Descriptor 的 hand/epoch 指被人工确认的**目标手**，不是从画面推断来的旧机器 epoch。
必须审阅跨界连续性；换座、补码、离桌/重新入座、遮挡或无法证明连续时不确认。
本手 optional straddle 是否实际发生是逐手观测；RIVER_START attestation 表示
复核了该手的 posting，不表示 river 时才发生，也不能从桌规金额自动推得。

`stack_delta_assertions` 必须包含下列全部布尔键，且每项都为 true：

```text
hand_start_marker_valid, river_start_marker_valid, seat_identity_continuous,
no_rebuy_or_topup, no_chip_return, no_payout_before_river,
no_jackpot_or_cashout, no_insurance, no_chip_side_fee_or_rake,
same_integer_precision
```

还必须包含 `hand_start_evidence_digest` 和 `river_start_evidence_digest`，分别
等于当前有效 HAND_START 与 RIVER_START descriptor seals。区间断言覆盖这两个
明确窗口之间的证据；任一边界改变后，旧区间断言失效，必须明确重新确认。
未知键、false、缺失保险断言或缺失/不匹配区间 seal 均拒绝，不静默丢弃。

公开数值函数 `derive_hand_committed_by_stack_delta(...,
opening_evidence_digest=..., river_evidence_digest=...)` 也校验相同断言 schema 和
区间 seals；缺失时返回 UNCONFIRMED。它不是单独的 acceptance authority：时间、
source 和 marker 的完整校验在确认 view 中进行。

C1–C8 的其余要求继续生效：座位身份完整一致，无筹码侧 rebuy/topup/退还/提前派彩/
jackpot/cashout/保险/rake/fee；两窗口筹码非负整数、同一精度；逐座 delta 非负；
`sum(opening_stack - river_stack) == independently confirmed pot_display.value`。
禁止平摊、补零、用底池反推逐座投入。派生 provenance 为
`derived_from_confirmed_observations`，不是 `human_confirmed`。失败的派生没有
accepted digest，不能进入 confirmed commitment。

## 4. 状态、金额和桌规

所有 dealt seats 必须恰好属于 ACTIVE/FOLDED/ALL_IN 的一个集合；并集等于完整
seat_set，数量等于明确的 table_rules.table_size（6/7/8）。folded_seats 是必需
事实，任何修订与冲突都会影响 view/receipt。所有 ACTIVE 的剩余筹码严格为正；
Hero 必须 ACTIVE，不能同时 folded/all-in。ALL_IN 集合非空一律超出当前 TARGET-S
支持域，即使是短码、等额或 `no_side_pot=true` 也拒绝。

恰好三名 ACTIVE，action_order 是其唯一排列且第一项为 Hero，dealer 在 seat_set。
固定 AA8 物理座位按 0…7 顺时针编号；action_order 必须与 dealer 后首个 ACTIVE 起的
顺时针顺序一致（跳过非 ACTIVE，dealer 自己最后），不能只接受任意排列。
只有这些结构、稳定 marker、明确 Hero-first、街投入零和 no_pending_action 都成立，
才能派生合法 `history=[]`。board 恰好五张合法互异牌，Hero 两张合法互异牌并与 board
不重叠。逐座 opening/river maps 必须覆盖同一个完整 seat_set。

金额 map 只接受 int 0–7 或 canonical string `"0"`…`"7"` 的 seat key；先验证后
转为 string。`1`/`"1"` 混合重号、`"01"`、float、bool 均拒绝；JSON 重复对象键
在解析时拒绝。金额只允许非负整数；不容许浮点/缩写/不可读值或 last-wins。

三名 ACTIVE 的 commitment 必须相同，其他座位不得超过该水平；保留独立
no_side_pot attestation。不得因勾选框而忽略数值或资格冲突。

桌规精确键为 table_size/small_blind/big_blind/ante/ante_mode/straddle_amount/
straddle_mode/revision；blinds 正数且 small≤big；none ante/straddle 金额为零；
非 none straddle 大于 big blind。none posting 必须 false，mandatory_utg 必须
true，optional_explicit_utg 必须明确逐手 true/false。禁止独立 min_bet 真值源。
other_fees 必须明确 `{value: 非负整数, confirmed: true}`；未知不默认零。

## 5. Append-only 恢复与 V1 兼容

同一个 immutable-record validator 用于 writer 和 reader，逐行检查完整 schema、
身份、value、provenance、timestamp、source 重新计算及 evidence binding，包括
已经被 supersede 的历史行。文件仍为 confirmations.jsonl + best-effort lock +
逐行 record_digest/prev_digest，flush/fsync，不引入数据库。

每手每事实的历史必须是：唯一 revision-1 root、parent 属于同手同事实、child=parent+1、
parent 在文件中先出现、无分叉/环/孤点、遍历覆盖全部 rows。孤立 cycle 不能藏在有效
head 后，不能按最新 timestamp/最大 revision 丢掉坏历史。写入前也验证已有 store。

Reader 对非法 UTF-8、malformed row/history 抛 StoreIntegrityError；confirmed_view 将它转为
NOT_READY 与明确 blocking/conflicts，不返回部分可信事实；target_s_acceptance
返回 TARGET_S_NOT_READY。损坏历史禁止继续 append。修复不能原地重写旧证据链。

V1 rows/receipts 不自动升级，不补 descriptor/区间，不改旧 seals。旧文件保留，
新 reader 拒绝旧 schema；缺乏新绑定的记录不能继承真实验收资格。需要重新审阅并
明确确认后写入新的 V2 store。缺失历史不是可静默迁移的数据。

## 6. Facts package、receipt 和消费检查

事实包由 `confirmed_view(store, hand_id)` 的完整结果和当时的
`target_s_acceptance(store, hand_id)` receipt 组成。view 包括确认事实、派生、缺失、
冲突、blocking、checks、逐事实 evidence refs（含当前 row seal 和全部祖先 seals）。
Bundle digest 覆盖整个 view，包括 schema/implementation、values 和来源/修订。
Receipt 的 river_start_snapshot_digest 绑定实际 RIVER_START descriptor，不能只 hash
牌面值冒充证据。Receipt digest 覆盖全部 receipt 字段。

`validate_target_s_receipt(store, hand_id, receipt) -> bool` 从当前有效 history
重新产生完整 receipt 并严格比较；只对当前 ACCEPTED 返回 true。相同值的 evidence/
frame/reviewer/revision/祖先/table-rule 修订也使旧 receipt 失效；改 flag、旧 schema
或坏 store 均返回 false。校验是调用时刻的检查，消费时必须重新校验，不能缓存
某次 true 或只验证 receipt 自己的 checksum。

事实就绪与现有 kernel 的可运行性分开：本模块不调用 solver，也不把真实规则改成
simulation。现有 threeway kernel 仍需要声明的 opponent ranges/response models、
action grid/预算、特定 simulation profile、已知零额外费用，以及 stacks 高于 action
grid 等支持条件。一个真实但非零的已确认 fee 不能被改写成零来适配 kernel。
本阶段的 facts package 不构成 solver adapter 或实际建议。

始终保留 `phh_ready=false`、`target_p_phh_ready=false`、`strategy_assessed=false`。
没有人工真实证据签收时 `REAL_HAND_ACCEPTANCE_PENDING=YES`；策略为 `NOT_ASSESSED`。
工程测试、receipt schema 和代码合并不会提升到真实验收、训练 gold、实战或盈利资格。

## 7. 验证与后续受控证据

六组 P0 以 public confirm/view/acceptance/receipt-currentness 及 checksum-valid
malformed recovery 回归验证；包括正常 6/7/8 座、合法多帧窗口、inter-hand opening、
正常修订的正控。测试仅 synthetic metadata，临时 store 在仓库外；不读取历史媒体。
独立审查不导入此测试文件的 fixture builder。还应运行 manual/semantics/#31 隔离
回归及仓库完整 checks，并将 review/CI 绑定最终 SHA。

后续真实验证需要独立授权和实际本地视觉审阅。最小目标仍是一手完整的 HAND_START、
RIVER_START、PAYOUT：全座位筹码和牌面可读，UI 尺寸/缩放稳定，无遮挡，完整手边界
与板面过渡可见；三名 ACTIVE、Hero 首先行动且无 ALL_IN/边池。缺少合格真实样本可以
报告工程 PASS、真实验收 BLOCKED/PENDING，不能为完成任务放宽条件或反推未知。
