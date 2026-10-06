# AA 全手离线实验台与同牌配对评估 v1

这是 10 秒行动窗口方案的**离线训练与验证基础设施**。此实验台不连接真实
采集、不调用云模型、不向实时界面发出建议，也不将规则标记升级为实战资格。
`strategy_eligible=false`、`empirical_status=NOT_ASSESSED` 始终保留。

## 规则与环境接口

`AAFullHandArena(rules, starting_stacks=None, occupied_seats=None,
dealer_seat=None, optional_straddler=None)` 接收现有 `AARuleProfileV2`。
默认物理座位为 `0..N-1`，其余座位空置，最大已占座位为 BTN；允许明确指定
6/7/8 个物理座位及按钮。默认每人 100BB，支持最小筹码单位对齐的不等码。
未知抽水应用、舍入或分配方式均拒绝；模拟规则始终仍是模拟规则。

- `reset(seed)` 使用本地 RNG 固定完整发牌；`clone()` 返回独立的深复制状态。
- `observe(seat)` 仅返回该座位底牌、已公开公共牌、公开下注历史、筹码、桌规
  身份与合法菜单。不会返回种子、其他底牌或未来牌。策略调用方只收到该字典，
  不应把 simulator 对象或私有字段交给不受信任的策略。
- `actor` 是物理座位；`terminal` 表示已结算；`legal_actions()` 返回不可变
  `ArenaAction` 元组，`step(action)` 接收动作对象或稳定的字符串动作 ID。
- 菜单包含 fold、check/call、最小加注、半池、整池及最大合法下注，去重且
  按金额排序。raise_to 始终表示本街累计投入总额，不是增量。半池下注按最小
  筹码向下取整，短码全下由规则引擎判断。合法的非网格 raise_to 仍可输入。
- `terminal_returns()` 返回各座位的净筹码 `Fraction`；`terminal_result()`
  返回 JSON 安全的精确分子／分母、退款、各层底池与抽水。终局观察的 stack
  字符串可为分数字符串；非终局行动输入金额始终是精确十进制。

PokerKit 固定为 0.7.5，负责四街行动顺序、全下、最小加注、短加注重开及结算。
UTG straddle 的最小完整加注仅在翻前改成 straddle 金额，翻后恢复 BB；不能
直接把引擎的所有街 min_bet 都改成 straddle。可选 straddle 必须显式指出
合法 UTG 座位，或显式采用本手没有 straddle 的默认值。短码不足以支付自己的完整
前注加盲注／straddle 的情况拒绝；PokerKit 对不足额 BB 的默认跟注价会低于
声明的 BB，因此此类开局等待专门适配。完整强制下注之后的短码全下继续支持。

终局另从完整投入重建分层底池、未跟注退款和资格，再与 PokerKit 的无抽水
净额比较；不一致即报错。抽水按总可争池计算一次总 cap，再按配置比例或
main-first 分配到各层。不对未跟注退款收费，不逐边池重复应用 cap。
平分与比例抽水采用精确分数：这是**合成的分数筹码模型**，不是实际 AA 的
最小筹码／奇数筹码分配验收。手工确定牌力及筹码算例可验证结算数学；同一个
PokerKit 引擎的自洽比较不能宣称独立规则 oracle。

## 配对评估

`evaluate_paired(rules, candidate, baseline, opponents, *, seeds,
candidate_id, baseline_id, starting_stacks=None, bootstrap_samples=1000,
bootstrap_seed=0, max_actions=1000, policy_seed=7719)` 接收纯确定性
`observation -> action ID`
策略及具名对手映射，每个对手组使用相同发牌比较候选／基线，并让 Hero 轮换
每个已占座位。候选、基线及对手实现应在调用前冻结；在线学习、用评估结果
重新选择策略和即时付费调用不属于此函数。

混合策略可以提供 `for_game(opaque_salt)` 返回纯的逐决策采样函数。实验台用
与发牌 RNG 独立的 `policy_seed` 产生每个 trial、每个物理座位的新 salt，
配对两边复用相同座位的 salt，不能被先前候选分支的随机调用数扰动。策略只
得到 salt，得不到发牌 seed；策略应以 salt、策略身份、信息集身份固定该次
决策，刷新不重复抽样，同信息集在不同对局仍可混合。普通纯函数保持原行为。
协议记录 policy_seed 与采样方式；错误的 factory 结果保留为 BLOCKED 行。

每个 seed 的全部 Hero 换座形成一个 bootstrap cluster，避免把高度相关的
重复牌局误当独立样本。每个人数、对手组分别报告净 BB/100 差及双侧 95%
percentile bootstrap 区间。一个 seed 不产生置信区间。预定 seeds 不允许
重复，预算与 seeds 写进 protocol hash。

候选拒绝、非法动作、超出行动预算或异常，保留该 pair 两边的记录；受影响组
整体统计置空，不做 complete-case 筛选，也不把拒答改成弃牌。原始 rows
保留 exact returns 与错误，完整和失败的分母同时报告。该协议 hash 不是
策略源码完整性证明；调用方需要另外绑定代码与冻结策略资产。重复观察探针
只能发现一部分不确定性，不能证明策略无副作用。

提供 check/call、免费过牌否则弃牌、最小加注和菜单中最大非全下加注脚本，
仅为实验台对照。赢这些脚本、区间为正或报告 COMPLETE，都不自动晋升策略。
正式的固定对手池、每人数 2000 个配对块、未见评估与真实操作验收仍由上层
训练／晋升协议安排。

## 验证

新增测试覆盖 6/7/8 人全部四街、同 seed 与 clone 重现、替换对手底牌及未来牌
时当前观察不变、观察字典不能修改内部状态、非法动作原子拒绝、合法非网格
加注、短全下不重开、straddle 与物理座位、手算多边池／未跟注退款／整手 cap、
no-flop-no-drop、抽水舍入、失败分母和按完整换座组 bootstrap。
另用 300 个确定种子的随机合法行动、不等码、前注和 straddle 合成牌局检查
完整结算与筹码守恒。这些是工程与合成规则验证，不是实际桌规或策略强度验证。
