# AA8 完整决策机会审计 V1

本轮建立独立于对手模型的全机会数据合同。它解决的问题是：已经识别出一个动作，
不等于已经保存了该玩家作决定时的完整公开状态，更不等于没有漏掉其他决策机会。

## 当前真实结论

当前最终 AA8 晚期开发回放有 36 条人工复核候选，其中 30 条可见动作 MATCH、
6 条误报。30 条 MATCH 包括 25 条对手动作和 5 条 Hero 动作，按街道为：

| 街道 | 数量 |
|---|---:|
| preflop | 7 |
| flop | 19 |
| turn | 2 |
| river | 2 |

动作类型为 11 check、10 fold、6 call、2 bet、1 all-in。这些记录全部进入当前
审查队列，没有挑选“字段比较完整”的行。但它们来自已出现的动作字形，不是对
完整时间线中每次轮到玩家行动的独立枚举，因此当前仍不能声明 all-opportunities
覆盖。

当前 30 行的共同缺口包括：

- 没有跨手、跨会话稳定的匿名玩家身份，物理座位不能替代身份；
- 没有严格早于动作开始的 actor、菜单和状态证据；
- 动作确认帧只能证明动作结果，不能回填动作前 pot、to-call 或 stack；
- 完整合法动作菜单为 0；
- active/争池玩家、位置和未来行动玩家不完整；
- 真实 AA 房间的盲注、ante、straddle、rake 与特殊模式规则没有审阅指纹；
- 只有一个真实牌局录制会话，不能拆成训练与验证；
- `aa8_late_dev_hand_005` 开局含特殊 bomb 底池，不能自动当普通模式。

因此最终实际输出为 `data_readiness=BLOCKED`、
`eligible_target_count=0`、`model_fit_executed=false`。30 条候选是下一轮人工
补证队列，不是可校准数据。

## 数据合同

`decision_opportunities_v1.py` 要求顶层同时保存：

- 数据范围、平台和真实规则 profile；
- 完整 session 清单及原录像 group，防止拆段、复制或改名后跨 split；
- 稳定匿名 participant 身份及私有证据哈希；
- 连续窗口内的完整手和显式 censored 边缘；
- 最小机会总账 `opportunity_ledger`；
- 与总账同序的完整 `opportunities` 记录。

机会总账列出完整会话中每个玩家的每次决策，包括 Hero。模型范围只能在预注册
的 `target_player_ids`、street 和 active-count 上取用，不能通过不登记困难行来
制造完整样本。详细记录缺失时，审计结果会按总账原位置补回
`decision_detail_missing`，不会丢弃或移到末尾。

每条完整机会必须包含：

1. session、hand、物理 seat、稳定 player、顺序、位置、street、争池玩家、
   当前及后续待行动座位和规则指纹；
2. 严格早于 action onset 的 actor/menu/state frame、PTS 和 SHA-256；
3. 动作前 stack、已投入、current bet、pot、to-call、最小加注和公开行动历史；
4. 完整合法菜单及每个动作的 min/max 和金额语义；
5. 属于菜单且满足金额范围的实际动作；
6. 根据 `Fraction(Decimal(to_call)) / (Fraction(Decimal(pot)) +
   Fraction(Decimal(to_call)))` 重算并规范约分的价格；
7. insurance、mushroom、bomb、buy-in overlay 的明确状态和证据；
8. 作者与独立复审状态，以及每个 UNKNOWN 的稳定原因码。

fold/check 金额语义为 `none`；call 与 all-in 为 `additional`；bet/raise 为
`total_street`。菜单缺失、实际动作不在菜单、call 金额不同于 to-call、价格
不是精确约分、动作前证据晚于 onset、规则混池或特殊模式未排除，都会保留原行
并阻断整组，不运行 complete-case 拟合。

审计器从规则强制投入初始化 pot、current bet 和每座投入，随后按 observed action
更新 street/hand commitment 和筹码；街道只能在上一行动轮关闭后前进。它还按
桌上顺序验证首个行动者、加注后的重新行动队列、fold 后的争池资格和 all-in 后
的待行动状态。一手结束前如果仍有未行动玩家，或既没有单人胜出、all-in 终局，
也没有完成河牌行动轮，整手会被阻断。

当前工程合同采用常见 no-limit 规则：一次完整 bet/raise 才重新开放已经行动玩家
的 raise 权，单次不足最小增量的 short all-in 不重开。如果以后确认 AA 房间采用
累计 short all-in 或其他 reopen 规则，必须先把该维度加入 `AARuleProfileV2`
及其指纹；当前真实规则未知，所以实际 AA 队列仍然 BLOCKED。

## 数据结果

- `BLOCKED`：缺机会、缺字段、身份不稳、session split 缺失、规则或特殊模式
  未知等；
- `NOT_REAL_DATA`：合成合同完整，但永远不是现实证据；
- `DECLARED_COMPLETE_NEEDS_ARTIFACT_VERIFICATION`：JSON 内部声明彼此一致，
  仍必须由单独的文件级验证器解引用 source、manifest、timeline、identity 和
  review bundle 后才能讨论离线校准。

普通 JSON 中的 reviewer 名称或 64 位字符串不能自行产生
`ELIGIBLE_FOR_OFFLINE_CALIBRATION`。即使声明完整，输出仍固定
`selection=null`、`calibration=null`、`range_model=null`、
`model_fit_executed=false`、`strategy_eligible=false`、
`advice_emitted=false` 和 `live_use=false`。模型拟合与实战放行属于后续独立
验收。

## 现有物理会话审计

元数据审计没有找到第二个可确认同规则的 AA8 真实牌局会话：

- `aa_phone_record_20260909_031030_54322c62` 是当前 8 座主来源，五个完整时间
  边界候选仍属于同一次录制；
- `aa_phone_test_20260909_0245` 是独立物理录制，但当时只到 AA 大厅，没有牌局；
- 2026-09-04 的 `session_001` 是旧 9 座/混合桌人数来源，规则、抽水和完整手未
  验证，不能与当前 AA8 混成同一总体。

这些判断只使用已有 JSON、JSONL、日志和文件元数据，没有打开 PNG/MKV，也没有
读取 300–820 秒校准/保留区内容。

## 工具与证据

通用审计：

```powershell
$env:PYTHONPATH='src;.'
python tools/audit_decision_opportunities.py `
  --dataset configs/strategy/examples/decision-opportunities-synthetic-example-v1.json `
  --output G:/PokerSense_private/my-decision-opportunity-audit.json
```

实际当前队列由 `build_aa8_decision_readiness.py` 读取哈希固定的 hand registry、
动作复核、V2 report 和 observations JSONL 生成。协议为
`configs/reproduction/aa8_decision_opportunity_readiness_v1.json`。最终私有输出
位于 `G:/PokerSense_private/aa8_decision_opportunities_v1_20260914_v10/`；前九次
输出保留为被后续合同加固取代的中间产物。

最终输出 SHA-256：

- `readiness.json`：`e10be9812b7beb24cd8da4792166fbc94903493831192f2ddc799a2f474cec10`；
- `synthetic-audit.json`：`9391257b19e7c42e69047e5b98ee0c9c0abd17fbbd81fef983047b55aefb5a6d`；
- `template-audit.json`：`cf7a902bdf91370fb5aadbb6af097288e2034ba985747f2ae1bc4ea073fe20fd`。

公开仓库同时提供一个完整合成合同样例和一个
`reviewed-template-NOT-DATA`，便于下一次真实会话按相同字段填写。模板中的
`REPLACE_ME`、null 和 UNKNOWN 都会保持 BLOCKED，不能因文件可解析而升级。

## 下一步真实数据工作

先在已有 G 盘来源中继续登记主 AA8 会话的全部 actor episode，包含没有匹配
动作字形的 episode，并逐项补动作前因果证据和完整菜单。与此同时寻找或以后
录制第二个同规则物理会话；在两个 session 和真实规则指纹齐全之前，不迁移或
启动对手校准器。本轮不处理 MC deadline、all-in/边池扩展或 live Advice。

本轮 53 项聚焦测试通过；全仓 3327 passed、1 skipped、2 项依赖弃用警告；
全仓 flake8 为 0；策略夹具生成器 299 项无漂移；Git index 私有文件名检查
854 个路径、0 命中；`git diff --check` 通过。
三路独立代码、证据和范围复审在五轮对抗反例修复后均为 PASS。
