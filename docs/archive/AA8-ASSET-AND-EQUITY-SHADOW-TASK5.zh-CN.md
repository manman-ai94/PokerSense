# 策略层任务5：版本化策略资产与权益影子计算

2026-09-10。状态：资产绑定、规则感知权益和WAL记录能力完成；没有真实AA策略
资产，没有对真实录像执行权益或Advice。

## 版本化策略资产绑定

新增`AAStrategyAssetBindingV2`及严格JSON Schema。绑定文件独立于策略节点，
必须固定：

- 策略资产SHA256；
- Provider capability SHA256；
- 完整AA规则指纹；
- Provider ID和source version；
- 6/7/8玩家数及preflop/flop/turn/river街道范围；
- 来源URL、revision、SPDX/自定义许可证和限制说明；
- `test_only`、`shadow_reviewed`或`live_approved`状态。

绑定本身也有规范SHA256。Provider实际文件、能力、玩家数或街道与绑定不一致
都会拒绝；`test_only`不能进入影子路由。`AARuleBoundShadowRouter.from_binding`
只接受已shadow reviewed的绑定，并再次执行规则/开局/straddle加注门禁。

当前没有提交任何伪造的产品策略节点。测试使用合成FakeProvider，仅证明版本化
连接和错误绑定拒绝正常，不是AA策略质量证据。

Schema：`configs/strategy/aa-asset-binding-v2.schema.json`。

## 规则感知权益影子

`evaluate_aa_equity_shadow`复用现有AdaptiveEquity exact/MC和多人逐池权益：

- 规则、DecisionContext和强制投入计划必须匹配；
- 开局逐座对账必须完全一致；
- Hero牌、公共牌、所有底池eligible seats和对手具体组合范围必须齐全；
- simulation必须调用者显式开启，结果状态仍为SIMULATION；
- 规则已验证时返回COMPLETE/PARTIAL；输入、范围、期限或规则有问题时BLOCKED；
- 同时保存毛期望筹码、配置抽水和配置后净期望筹码；
- 抽水支持按所有主/边池比例分配或主池优先；分配方式未知时不计算净值；
- 结果只供后台，不生成行动概率、推荐尺寸或Advice。

抽水分配方式已经加入AA规则指纹。修改分配规则会使绑定资产失效。

## 6–8人合成连通验证

当前私有报告：`G:/PokerSense_private/aa_equity_shadow_synthetic_v3/report.json`。

固定河牌、3名仍可争夺玩家、150底池，配置3%且封顶2BB后抽水为4：

| 桌型 | 方法 | 毛期望筹码 | 配置后净期望 | Advice |
| --- | --- | ---: | ---: | --- |
| 6人 | exact | 150 | 146 | 无 |
| 7人 | exact | 150 | 146 | 无 |
| 8人 | exact | 150 | 146 | 无 |

三例Hero固定必胜只用于让毛/净扣款关系可直接核算；这不是胜率准确率或盈利证明。
代码分别绑定规则指纹，耗时约0.29–0.43ms，仅为单一河牌exact小样本。

## WAL升级与真实日志

影子WAL现在允许记录Provider/权益是否执行、方法、毛/净期望、抽水、区间、
数值置信度、规则指纹、资产绑定ID及拒绝原因；白名单明确禁止
`preferred_action`、推荐尺寸和其他未知/可执行字段。Follower和离线分析器会
累计Provider/权益执行次数及影子结果状态。

当前最终真实日志会话：
`G:/PokerSense_private/aa8_shadow_sessions/aa8-dev-v8-shadow-20260910-v2`。

- 3839条记录；3732 ABSTAIN、107 DEFERRED；
- Provider执行0、权益执行0、Advice 0；
- WAL SHA256：`8939b345308dea033edf39ba9e169657f073c605c2bbaad353a25a255e3e47bc`；
- 哈希链、receipt及当前实现哈希全部一致；
- 输入门禁P50约0.0127ms、P95约0.0181ms；不是端到端性能。

真实权益仍为0次是正确结果：视觉输入没有独立权威化，现有开局与模拟强制投入
也未完全对账，且没有与AA规则指纹绑定的真实对手范围或策略资产。

## 尚未完成

- 获取、生成或求解真正适用于6–8人、前注、3%、straddle的版本化策略节点；
- 建立每个位置/行动线的具体组合范围先验及动作更新似然；
- 用权威完整手牌将视觉状态送入权益影子；
- 翻后Provider和长期实时/影子一致性验收；
- 用户设置页面尚未切换到AA规则V2；
- 任何live approval、建议展示或盈利结论。

本任务完成的是可以安全承载未来真实资产和胜率计算的轨道，不是用合成策略
填满空白。

本任务当时全仓3192项通过、1项跳过、2条依赖弃用警告；flake8为0（沿用已有
`aa_record_session.py`排除项）。V1冻结280文件0变化；最终真实WAL共3839条，
哈希链及receipt一致，Provider/权益/Advice仍均为0。
