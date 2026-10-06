# Strategy Evaluation Foundation V1

## 判定与边界

基线源码固定在公开 `main` 的
`d98084aba96eac6ff3bc0cf07dad99b00e36ff31`。本阶段在改变任何策略行为前，
冻结了当前 **AA 人工条件三人河牌规划器** 的六份公开历史策略表，并建立可重复的
离线测量、容量拒绝探针和独立结算参考。

| 判定 | 值 | 准确含义 |
| --- | --- | --- |
| `STRATEGY_EVALUATION_READY` | `YES` | 可在固定的人工河牌场景和对手假设下重复测量策略条件 EV、对照差、模型敏感性、回退和容量。 |
| `BASELINE_V1_FROZEN` | `YES` | 六份策略表、原始源码哈希、输入/协议哈希和结果摘要已固定；对手世界不会重新生成基线动作。 |
| `REAL_HAND_ACCEPTANCE_PENDING` | `YES` | 当前没有经签收的真实完整决策状态、真实对手范围或实时策略资格。 |
| 真实策略质量/盈利 | `NOT_ASSESSED` | 本轮的合成条件 EV 不能转换成实战 bb/100、胜率、GTO 距离或盈利结论。 |

这些状态可以同时成立。`STRATEGY_EVALUATION_READY` 只描述评估基础设施，
不提升机器感知候选、人工假设或 TARGET-S 确认的事实等级。

## 当前代码架构（按调用链核对）

- 通用桌面 session 在 `src/poker_engine/desktop/live.py` 构造
  `StrategyOrchestrator(build_strategy_router())`。内置 `heuristic_provider.py`
  只提供 6/7/8/9 人、100bb、无 ante/抽水、未开池翻牌前 RFI 的 raise/fold
  启发式；7/8 人从九人同名位置资产派生，置信度 0.3/0.4 不是 EV 或实测正确率。
  它不代表 AA 当前多人河牌策略。可选 GTOpen 注册入口目前有可重现实现错误：
  `registry.py` 构造 `GTOpenConfig` 时漏了必需的 `source_revision`，启用参数后
  在联网前抛 `TypeError`。本阶段记录错误，未改变生产策略行为。
- AA 手工离线分析由 `desktop/aa_hand_input.py` 进入 `desktop/aa_analysis.py`，
  再分别调用 `terminal_multiway_v1.analyze_terminal_multiway` 或
  `threeway_river_v1.analyze_threeway_river`。前者是 Hero 唯一 ACTIVE、对手已
  all-in 的河牌 call/fold 条件结算；后者是河牌起点恰好三名 ACTIVE 的有限动作树。
  两者均要求人工范围和已声明规则，结果不能授权 live Advice。
- 三人河牌要求 6–8 个发牌座位、五张已知公牌、恰好两份人工对手范围与响应模型、
  已知行动顺序、相容的河牌起点投入和正好为零的额外费用。只允许普通单底池，
  活跃筹码须高于最大下注目标；不支持跨越 all-in 或边池。响应概率由自身手牌
  类别、公开合法动作及价格比率的人工权重归一化；Hero 在一个信息集内对整体
  后验取最优，而非看见隐藏牌后逐手重选。默认联合范围乘积上限 128、树节点
  上限 20,000。预算耗尽返回 `BLOCKED`，没有局部 EV。桌面进程另有 10 秒
  等待上限，本轮没有用这些小场景证明该端到端时限。
- `threeway_policy_evaluation_v1.compile_policy_book` 将规划所得公开历史动作、
  规划输入哈希、公开条件和整个策略表哈希冻结。`evaluate_policy_book` 在新世界
  只查表，未知公开历史按已声明的 check-if-free-else-fold 回退，比较固定策略与
  check-fold/check-call；它不会为新世界重新优化 Hero。它与规划器共享转移、
  牌力和结算内核，因此它的自洽检查 **不是** 独立数学 oracle。

## 可重复基线

文件：

- `configs/strategy/evaluation/baseline-v1.json`：六个策略表的完整动作、源码与
  公开输入/协议 SHA256、上限和真实性边界。冻结命令只接受上述精确 `main`。
- `configs/strategy/evaluation/baseline-v1-results.json`：30 个逐项结果、精确有理数
  EV、对照差、联合假设数、节点数和运行环境。`deterministic_sha256` 排除计时，
  本轮为 `c1a725f3f95a76261fb041af200e45bae02b6836202b36ec56578f0afd680aae`。
- `configs/strategy/evaluation/oracle-v1-result.json`：独立参考的逐字段差分结果。

从仓库根目录运行：

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
python tools/strategy_evaluation_v1.py check
python tools/strategy_evaluation_v1.py run --output <new-result-path.json>
python tools/compare_strategy_evaluation_v1.py --candidate configs/strategy/evaluation/baseline-v1-results.json
python -m pytest -q tests/tools/test_strategy_evaluation_v1.py
```

首次冻结是在策略源码未修改、HEAD 精确为 `d98084a` 时执行
`python tools/strategy_evaluation_v1.py freeze`。后续评估只读取已保存动作；
列明的源码依赖、输入、协议、策略表任一变化都拒绝冒名为 V1。冻结/结果文件
只能新建，普通运行不能覆盖已存在文件。新的候选策略须与这一基线
在同一组预先声明的世界和独立挑战上配对比较，不能覆盖 V1 文件。
`tools/compare_strategy_evaluation_v1.py` 已提供只读配对接口：候选报告必须
保留同一 case ID、世界哈希与联合范围条件；候选超时/拒绝留在分母，
不会被筛掉。比较器先核对规范 V1 产物、当前评估内核源码、输入和协议，
再核对报告正文与逐项统计。每个公开条件组的五个世界（含拒绝行）必须使用
同一份候选策略表，不能按世界重编译。不同于 V1 的候选必须另外提供完整
六份冻结策略表：`--candidate-books <books.json>`，内容为 group 到
`book_data` 的 JSON 映射。比较器验证表哈希，并在固定 V1 世界与内核上
重新评估，要求提交的 EV、对照、条件历史概率和回退指标与实际计算一致。
只提交自行重算摘要的报告不能证明数值可信。拒绝行不得夹带部分 EV。
以 V1 自身作候选时 30/30 精确相等；
本任务没有创建优化候选，`COMPARABLE_SYNTHETIC` 也不授予经验提升。
将来候选生成器及未曝光挑战集仍须由后续独立任务建立。

V1 文件的规范字节 SHA256 为
`3b9983b46c054a40499286467164c68e2e1ea7039df0a5c2470859ebd702eab4`。
`freeze` 和 `run` 都固定这一身份；有效但不同的策略表不能重新命名为 V1。
比较器的重算证明报告与提交的冻结策略一致，不能证明策略开发者从未看过
这些公开世界。它们始终是已曝光的开发回归集；未来的提升结论还需要预先
登记、未用于选模/调参的新挑战及独立审查。

协议沿用现有公开人工场景：6/7/8 发牌人数 × facing-bet/unopened 两种根节点 ×
五个声明的世界（原始控制、强价值范围、弱牌跟注者、秩敏感响应、过牌后陷阱）。
发牌人数变化主要增减已弃牌座位，**30 行不是 30 手独立真实牌局**；每行仅
1–4 个合法联合假设。这里没有训练/验证样本、置信区间或经验泛化保证。

## 本轮实测

- **30/30** 固定策略评估完成；**12/30** 在至少一个 check-fold/check-call
  对照下出现负差值；回退概率均为 0。数值是同一人工模型下的条件 EV。
- 6 人 facing-bet 的原始控制世界：基线 call 的精确 EV 为
  `543196/15151` ≈ 35.852 筹码；规划器的 raise-to-40 与 raise-to-80
  分别为 `823961056/23499201` 和 `737057752/20650813`。冻结表对原始
  世界重算一致。
- 仅换成强价值范围后，6/7/8 人的 facing-bet 固定 call 相对 fold 都为
  **−20 筹码**；同一世界若事先知道新模型，根动作会改为 fold。unopened
  固定 bet 相对 check-fold 为 **−80 筹码**，已知模型的根动作是 check。
  这证明对假设变化敏感，不是实战中已经损失了这些筹码。
- 弱牌跟注者世界中，6 人 facing-bet 固定 call 的 EV 为 126 筹码；
  同一内核提前知道该世界并重规划可比它高 `184320/2023` ≈ 91.11 筹码，
  根动作改为 raise。该“模型知识差”是上界式诊断，**不是 GTO regret**。
  秩敏感及过牌陷阱世界使用了规划器表达不了的响应覆盖，故不计算假装精确的
  世界最优差，只给固定策略与简单对照的差值。
- 独立的既有单因素范围探针
  `python tools/threeway_range_experiment.py --check` 保持同一冻结手册策略和
  响应模型，只把行动对手的一组强牌组合相对权重改为 0.5/1/2；策略条件 EV
  分别为 `77437/1417`、`543196/15151`、`390596/22781`，随权重上升
  从约 54.65 降到 17.15 筹码。该旧探针有单独的固定协议，不把它误计为
  30 个新独立样本。
- 本机 Python 3.12.10、Windows 11 上，这 30 个小世界的固定策略评估
  使用 6–244 节点，单项墙钟上限约 20 ms；不是大范围或生产端到端时延保证。
  显式节点预算 1、联合预算 1、默认 128 对 12×12 范围、未知费用、四人
  ACTIVE、混入 ALL_IN 的六个探针全部 `BLOCKED`，动作为空、策略资格及
  Advice 均为 false。

## 独立参考与错误归因

`tools/strategy_eval_independent_oracle_v1.py` 使用固定的开源
[PokerKit 0.7.5](https://github.com/uoftcprg/pokerkit/tree/54571ddda38a7da9b8c527d54c16c788ac14dac7)
独立判定摊牌牌力，并在独立代码中枚举人工联合手牌、分层底池、退款、抽水及
条件 EV，与现有 `terminal_multiway_v1` 逐字段差分。这不是调用同一个
`calculate_side_pots` 或 PokerSense 的手牌评估器。公开 6 人示例为 `MATCH`：
底池 110/130/80、抽水 11/8、13/8、1，call 净条件 EV 256、fold 0。
另外 11 个定向测试涵盖短筹码退款、加权范围与阻牌、公共皇家同花顺平分、
7/8 人桌、抽水取整/分配、零胜率、注入错误可检出及依赖缺失/未知费用拒绝；
本机安装 0.7.5 时 **11 passed**。CI 在原测试后单独安装这一固定免费依赖，
并在 Windows/macOS 明确再次运行实质差分测试，避免把 skip 当成通过。

这个参考确实校验了当前条件结算的多个算例；它没有验证人工范围和响应概率，
没有模拟完整行动树或真实桌规，也不能证明三人河牌每个行动 EV 无实现错误。
当前独立参考的判定是 `MECHANICAL_REFERENCE_VALID_WITH_LIMITS`。
可复现的实现错误另有可选 GTOpen 初始化缺参；与本次固定 AA 河牌表分离，
且不应为了得到绿灯偷偷启用 GTOpen。

## 外部技术路线：角色、证据与取舍

| 技术 | 本阶段可承担角色 | 当前判定与依据 |
| --- | --- | --- |
| PokerKit 0.7.5 | 独立牌力/结算参考 | **USE**，上面的差分已实际执行；它不是策略 policy。 |
| [OpenSpiel](https://openspiel.readthedocs.io/en/latest/games.html) / CFR、MCCFR、DCFR | 极小游戏的算法参考、未来 critic 校准 | **DEFER**。Hold'em 依赖可选 ACPC；[其 exploitability 实现](https://github.com/google-deepmind/open_spiel/blob/master/open_spiel/python/algorithms/exploitability.py) 限于双人常和；不能把 HU 指标直接贴给 AA 多人。 |
| [TexasSolver](https://github.com/bupticybee/TexasSolver)、[b-inary](https://github.com/b-inary/postflop-solver)、GTOpen | 声明边界内的 HU 对照 | **DEFER**。范围/人数与当前 AA 普通三人河牌不等价；GTOpen 当前注册入口还有上述实现错误。无需为本阶段引入 AGPL 或不明许可的发布依赖。 |
| [Pluribus](https://www.science.org/doi/10.1126/science.aay2400) 与多人 CFR 家族 | 研究多人可行性 | **REFERENCE ONLY**。六人实证不是可用模型权重，也不给当前有限树通用多人均衡保证。 |
| [Deep CFR](https://arxiv.org/abs/1811.00164)、[NFSP](https://arxiv.org/abs/1603.01121)、[ReBeL](https://arxiv.org/abs/2007.13544) | 将来学习 policy/value 或快速近似的候选方法 | **DEFER**。主要扑克证据偏 HU，缺同构多人规则、可信训练数据和配对评测；不能用“深度学习”替代这些条件。 |
| 对手范围/响应建模 | 条件策略的输入模型、误差来源与不确定性检测 | **EVALUATE NEXT**。只有在同房间、逐决策完整且可审计的数据上，才能做按 session/opponent 切分的 held-out log loss、Brier、校准及条件 EV 敏感性；现有人工权重未获此验证。 |
| [ToolPoker/LLM 工具辅助研究](https://proceedings.iclr.cc/paper_files/paper/2026/file/03e0712bf85ebe7cec4f1a7fc53216c9-Paper-Conference.pdf) | 解释、提问或离线错误归类的候选 router/critic | **DEFER**。文本推理和动作说明不能替代已知合法状态、精确算术和结算参考。 |
| 快速近似/缓存 | 将来有足量代表性输入和精确误差上界后压缩运行时 | **DEFER**。本轮只有 1–4 个合法联合假设，无法从 20ms 推出大范围瓶颈或批准近似。 |

### Jev / System One Models

[TypeSafe 官方文档](https://docs.typesafe.ai/llms-full.txt)描述 Jev 为托管的、
文本输入的结构化选择/评分模型：Choice 的数值是在提供的标签之间归一化的
选择分布，Score 是指定评分级别上的分布，Noul 是 yes 的概率；Choice/Score
`confidence` 是这些输出分布导出的统计量。文档的“校准”是群体层面的，
不保证单个扑克判断正确。这些数值没有下注效用、对手行动频率或均衡频率语义。
[官方介绍](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
标明早期访问和付费 API；本任务没有授权付费/专有依赖，因此 **未调用**。
一篇[独立 HU 单牌面探针](https://backnotprop.com/blog/jev-poker/)只报告了
行动首选一致率（150 个位置总体 63%，55 个争议位置 38%），没有 EV 损失，
不能转移到 AA 多人局面。

**Jev 总判定：`SHADOW_TEST`，以将来获得访问授权为前提；目前实际运行
状态 `DEFER`。** 它只能在公开/合成纯文本状态上尝试狭窄的非权威语义判断，
与确定性规则和独立标签比较 Brier、log loss、校准、选择性准确率、延时和
费用；记录固定版本、原始输出及拒绝率。对策略 policy、EV/牌力 oracle、
GTO 频率和真实手牌事实升级，判定为 **REJECT**。Jev 输出不得接 Advice。

## 唯一下一优化目标（本阶段不执行）

`FIRST_OPTIMIZATION_TARGET = OPPONENT_RIVER_RANGE_POSTERIOR_CALIBRATION`。

原因是同一已冻结动作只改变人工强牌范围便出现 −20/−80 筹码的简单对照差，
单因素强牌权重 0.5→2 又使条件 EV 从约 54.65 降至 17.15；对手范围先验、
阻牌和公开行动后的后验是最直接、可量化的策略输入不确定性。响应假设也敏感，
但本次强价值范围实验单独就足以使基线动作逆转。优先建立可信、逐决策的范围
证据与校准，再考虑改变动作搜索、扩玩家数、训练深度 policy 或近似加速。

下一任务必须另行启动，并先冻结未用于选择该目标的挑战集及对照口径；
本 PR 没有改范围参数、响应权重、策略动作或生产范围。缺真实可审计样本时，
优化仍只能处于合成研究，不能以该目标名义提升实战策略等级。
