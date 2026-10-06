# AA8 动作解释与结算阶段

2026-09-15，承接第一手复核。新增桌面解释层，不修改既有识别器、模板、阈值、金额账本或canonical策略门禁。

## 动作解释

`AAObservationSemantics` 保存有界的前态窗口。对于有金额动作，取现金首次变化之前一帧的完整本轮投入向量和价格；要求同来源、同epoch、同街道、没有跨遮挡，以及前后余额与支出一致。缺失、冲突或越过历史窗口返回UNKNOWN，不从确认帧的后态回填之前价格。

新增动作副本保存原kind/glyph/amount，另添`semantic_kind`、`semantic_street`、`all_in`、`target_total`、调用前价格和来源帧证据：

- 原价格4、本人本轮0、支出20：raise-to20。
- 原价格0、支出58：bet58。
- 原价格0、余额214→0：bet214且all-in。
- 面对214、本人本轮0、余额120→0：call120且short all-in，不是raise。

加注是否足额、是否重开、整手历史是否完整以及真实规则仍未验证，不能把这层直接作为合法StateEvent。零支出的check/fold可保留字样类型；若确认时处于转街动画，`semantic_street=None`，不填造街道。第一手3023正属此情况。

原`observed_actions_v2`与`action_history_candidate`不改，新增`interpreted_actions`/`interpreted_action_history`；源确认帧通过已保存的逐帧映射获得，不以固定offset猜测采集卡丢帧后的编号。页面明确“来源确认帧”和“处理序号”。

## 结算候选阶段

本轮只覆盖已观察到完整河牌、开局参与集合已知、参与者均为folded/all-in且至少两名all-in、无待确认动作或当前行动者的终局候选。随后出现同epoch正向现金回流，才记`SETTLEMENT_CANDIDATE`。

再观察到连续两帧底池0、底牌与公共牌清空、没有新发牌正证据，进入`WAITING_NEXT_HAND_CANDIDATE`；第一帧为`POT_CLEAR_PENDING`。这不是仅凭底池0认定结算，也不支持把任意补码当成赢池。

新`hand_phase.current_ledger`在清台阶段为空；`historical_ledger`保留清台前629投入、623显示底池、6待解释差额和正向现金事实。原`hand_ledger_v2`字节语义未变，不能删除历史或擅自把6/13解释成费用。转来源、断帧、新epoch、遮挡或行动状态矛盾会清理／暂停解释依据。

普通非all-in摊牌、弃牌直接获胜、费用分配与资金规则的通用结算尚未实现。所有`canonical_verified`、`legal_action_verified`、`strategy_eligible`继续为false；页面使用“候选”说明。

## 验证

- 新增28个聚焦测试，覆盖四类价格解释、short-call/short-raise区别、前态缺失／未知／错误余额／标签冲突、跨来源／遮挡／街道、底池零但没有终局依据、现金回流、清台稳定、新手重置及历史保全。
- 当前完整第一手重新运行2060帧（3前滚＋2057牌局），原字段对照零变化；21个动作类型与参考对应。3023的check保留，但确认街道仍未知。3300/3319进入等待下一手候选，当前账本为空、历史629及差6保留。
- 全仓3786 passed / 7 skipped / 1依赖警告（52.58s）；18项真实JS状态／动作显示测试通过。
- 私有证据：`G:/PokerSense_private/aa-semantic-stage-20260915-v1/runtime-v1/comparison.json`。本轮没有读取保留区、打开设备、训练模型或生成实战建议。

这些结果证明这一层在开发样本和反例上的工程行为；不是独立视觉、完整合法状态或强策略验收。
