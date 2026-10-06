# AA8 本轮下注初值：条件分区检查，尚未可用

新增独立`tools/aa8_street_baseline_v2.py`，未修改冻结V1。
`PartitionReader`复用AACenterAmountCandidate读取中央已收筹显示，复用现有
金额、币标、行动者与正向空白检测。`StreetBaselineCandidate.observe(frame,
observation, context)`只在两帧完全一致且全部条件满足时返回条件候选。

条件包括：新手/新街的因果上下文、此前无动作、当前行动者、场景无遮挡、
无收筹/模式切换、八座每处为正向金额/正向空白/明确NA，以及
`标题数值 = 中央数值 + 所有可见下注之和`。
只有这个条件初值中，正向空白才允许表示0；未知OCR绝不补0，明确NA仍是NA。
算术相等不证明AA房间的会计规则，canonical_verified始终false。

## 八帧实际结果：全部BASELINE_UNKNOWN

证据`G:/PokerSense_private/aa8_street_baseline_v2_dev_v2/report.json`。
使用明确的`aa8_reviewed_money_bank_v2_boundary/bank.npz`，哈希写入报告。

- 1320/1321自动读出标题23、中央14、行动者3；1号有明确币标但其金额OCR
  UNKNOWN，因此没有用23−14−其他下注反算成2。初值未通过。
- 2070/2071自动读出标题115、中央115、行动者1；Hero下注ROI存在60个亮像素，
  不能说是完整空白，没有为了让总和成立而填0。初值未通过。
- 1500/1501、2400/2401已经有本街动作，不能回头新建“此前无动作”的初值。

新街/无先行动作/无遮挡上下文在这次诊断中为人工检查注记，明确automated=false，
未声称已经自动接入V2历史。后续需解决1320的单座数字拒识、Hero空白ROI定义，
并由因果状态链提供上下文；未实现后续本轮投入追踪，也未开放策略使用。

本模块8项拒识/初值契约测试通过，与V2状态适配器合计19项通过，flake8通过。
没有读取保留集、300–600秒预留资料或重新录制。

后续显式可选下注几何V2修复了上述两处读数/ROI问题，8帧再测记录于
`aa8_street_baseline_v2_dev_v4`。1321、2071可形成条件基线，但上下文仍非自动。
旧v2拒识报告保留，原因及边界见`AA8-WAGER-GEOMETRY-V2.zh-CN.md`。
