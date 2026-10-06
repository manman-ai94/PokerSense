# 策略层任务6：AA具体组合范围资产与逐手跟踪器

2026-09-10。状态：范围资产格式、动作似然更新、逐手跟踪和权益门禁完成；
没有提交真实AA范围数据，没有对真实录像计算权益或建议。

## 具体组合资产

新增`AAConcreteRangeAssetV2`和严格Schema。每份资产必须绑定AA规则指纹并记录：

- asset ID/version/status和文件SHA256；
- 来源URL、revision、许可证和限制；
- 精确玩家数、位置、有效筹码BB、行动线；
- concrete combo及Decimal先验权重；
- fold/check/call/aggressive/all-in逐组合动作似然；
- 置信度、有效样本数和证据引用。

资产只允许`AcKc`这类具体两张牌，不能输入`AKs`抽象标签。相同实体手牌使用
`AcKc`和`KcAc`反向重复会拒绝；combo必须排序且先验精确和为1。动作似然
必须在0–1且只能引用该先验已有组合。规则、资产文件或节点维度不匹配均无
fallback。

状态分`test_only`、`shadow_reviewed`、`live_approved`。test_only不能进入影子
范围；当前没有产品级shadow reviewed/live approved节点。

Schema：`configs/strategy/aa-range-asset-v2.schema.json`。

## 查询、阻断牌和动作更新

`AARangeQueryV2`按规则资产中的玩家数/位置/筹码/行动线做精确节点查询。
Hero及公共牌阻断调用既有`filter_blocked_combos`，移除碰牌后精确归一。

动作更新复用`bayesian_action_update`：

- P(action|combo)与先验相乘再归一；
- 保存似然覆盖率、缺失组合、entropy、ESS、confidence和source version；
- 部分似然按先验质量覆盖率降低置信度；
- 没有该动作似然时不修改范围，但明确`applied=false`和coverage0；
- prior必须来自同一规则指纹、同一资产和同一seat，不能注入其他范围。

## 逐手影子跟踪器

`AARangeShadowTrackerV2`按seat建立范围并严格消费单调动作帧：

- 默认最低动作似然覆盖0.80；
- 未建范围的玩家行动、阻断后无组合、未知动作或范围更新异常都会记录事件；
- coverage不足或无似然会污染本手范围快照；
- 失败事件也递增版本并保留，不静默丢失；
- snapshot再次检查所有底池eligible opponent正好各有一份范围；
- 不允许多余座位范围，因为它会错误占用牌堆并影响runout；
- 所有范围source version必须含当前AA规则指纹；
- 默认最低范围confidence0.25；不满足时`equity_permitted=false`；
- snapshot永远不产生Advice或策略资格。

## 权益链的新门禁

`evaluate_aa_equity_shadow`现在默认要求同一个`AARangeShadowSnapshotV2`：

- snapshot必须允许权益且没有范围更新blocker；
- snapshot distributions必须与DecisionContext villain_ranges逐项一致；
- 规则指纹、底池资格座位及最低置信度再次核对。

只有显式`allow_untracked_ranges=true`的测试工具可以绕过tracker，并在结果中
写入`untracked_ranges_explicit_test_only`。产品影子路径默认不能绕过。

## 现有开源范围的边界

仓库已有MIT preflopR只包含6/9人、100BB、无前注、无抽水、first-in open
范围；7/8人策略还是从9人同名位置派生。它没有straddle行动树，也没有完整
fold/call/raise likelihood，因此没有被重新标记成当前AA规则资产。

## 验证与剩余工作

范围资产/跟踪器23项聚焦测试通过，覆盖哈希/规则绑定、重复JSON键、反向重复、权重、
似然、阻断、节点缺失、6–8查询、范围seat/规则/confidence门禁、完整/部分/
缺失动作更新、乱序和未建范围玩家。规则感知权益及合成工具11项测试继续通过。

尚缺真正的AA组合先验和动作似然数据。下一步应生成第一批“simulation only”
完整组合基线及对抗测试，或者接入经来源审计的求解数据；在此之前真实WAL的
Provider/权益仍应保持0，而不是把preflopR或随机范围包装成高质量策略。

当前合成权益报告更新为
`G:/PokerSense_private/aa_equity_shadow_synthetic_v3/report.json`，明确使用
`allow_untracked_ranges`测试披露；产品默认路径仍要求tracker snapshot。

最终全仓3216项通过、1项跳过、2条依赖弃用警告；flake8为0（沿用已有
`aa_record_session.py`排除项）。V1冻结280个文件重新计算SHA256，0个变化。
