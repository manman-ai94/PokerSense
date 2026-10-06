# AA 6–8人桌：多人策略路线与首个决策模块

日期：2026-09-13。用户确认策略模块优先，并明确必须覆盖多人底池。本文中的“人数”分为桌上人数、当前仍争池人数、每个边池的资格人数，不能混用。

**结论：多人强策略有实证可行性，但当前没有已核实、可直接装上本机就能在AA6–8人桌高胜率运行的开源成品。多人GTO不提供双人零和那样的安全保证。** 本轮已交付真正多方参与的终结决策条件EV模块与可运行JSON入口；它不是完整多人GTO，也没有盈利验收。

## 1. 多人GTO可行性与稳定性

Brown和Sandholm的[Science最终论文](https://www.science.org/doi/10.1126/science.aay2400)明确指出：CFR平均策略收敛到Nash的保证适用于双人零和，多人不保证。其Pluribus在六人NLHE中击败职业玩家，是**自博弈加搜索能够产生强多人策略**的实证，不是“多人均衡必不亏”的证明。

[Meta官方说明](https://ai.meta.com/blog/pluribus-first-ai-to-beat-pros-in-6-player-poker/)也明确：超过两人时，即使使用精确Nash策略也可能亏损。

[补充材料](https://noambrown.com/papers/19-Science-Superhuman_Supp.pdf)中的5人+1AI实验有10,000手，均值47.7 mbb/game，即4.77 bb/100，标准误2.50 bb/100，单侧p=.028，并使用AIVAT方差缩减。**不是47.7%的赢手率。** 官方博客p=.021与最终论文不一致，本报告采用最终论文。该实验是六人、每手重置100BB；不能直接外推7/8人、AA的前注/straddle/抽水及特殊资金规则。

论文报告蓝图训练约8天、64核、12,400核小时、内存小于512GB；线上使用两颗CPU封装而非“两核”，搜索约1–33秒。历史云端spot费用不代表今日复现全项目成本。官方因商业扑克影响未公布完整代码，只给主要组件伪代码；本次未找到官方公开训练权重的依据。

数学上的区别：无抽水多人扑克的玩家总转移仍可为零和，但“多于两人”本身已经不满足双人minimax/CFR的保证前提。结果相关抽水通常又使玩家总收益依赖终局。不能通过给庄家加一个被动玩家来恢复双人性质。

稳定性需要分别检查：模型内求解是否收敛、软件是否及时正确返回、对不同对手组合是否仍有净收益。这三者不能用同一个“GTO”标签代替。

## 2. GitHub实际支持边界

以下为2026-09-13只读查询及源码检查。未执行第三方solver，也未复现其作者胜率。commit固定链接优先于会变化的默认分支。

| 项目 | 核实内容 | 本项目用途 |
| --- | --- | --- |
| [TexasSolver](https://github.com/bupticybee/TexasSolver/blob/d12197b6d409a10474a7138ec2fb662b02588c09/src/solver/PCfrSolver.cpp#L31) | 源码明确player_number=2，后续oppo=1-player；AGPL-3.0 | HU参考后端，不能担当3+活跃玩家求解 |
| [b-inary/postflop-solver](https://github.com/b-inary/postflop-solver/blob/9d1509fe5077d019825f833eed04b16d342dfda1/src/game/mod.rs#L47) | 双人数组；README的6-max是最多4名已弃牌者的bunching，不是6人仍争池；支持抽水配置；AGPL-3.0 | HU参考和比对工具；desktop-postflop也未改变双人内核 |
| [GTOpen](https://github.com/MatthewPDingle/GTOpen/blob/92c86ed73aa0856df8479b5c7635e1469f48f1e8/README.md) | Postflop is heads-up only；多人preflop使用continuation approximation | 已有适配器不代表真实AA多人策略已可用 |
| [GTOpen技术说明](https://github.com/MatthewPDingle/GTOpen/blob/92c86ed73aa0856df8479b5c7635e1469f48f1e8/docs/technical_reference.md#L77) | 3+人叶子的latent-strength样本不是联合发出的真实底牌/公共牌；模型内gap小不证明真实牌局准确 | 不用该近似结果签收完整多人求解 |
| [c-heidt/pluribus-opponent-exploitation](https://github.com/c-heidt/pluribus-opponent-exploitation/blob/dd422bb5aee40cde03e22e26f5c597ee2bb691c0/poker_ai/search/solver.py#L91) | 真有多人external-sampling MCCFR路径、3人边池测试；KIT硕士研究实现，非官方Pluribus | 值得进入隔离评估候选，尚不能直接实战 |
| [OpenSpiel](https://github.com/google-deepmind/open_spiel/blob/48401890ee9857e611678302371378175a8e4c6b/open_spiel/games/universal_poker/universal_poker_test.cc#L88) | universal_poker声明2–10玩家，源码有6人NLHE配置及多人测试；Apache-2.0 | 自博弈、算法实验、独立对照环境，不是训练好的强策略 |
| [PokerKit](https://github.com/uoftcprg/pokerkit/blob/54571ddda38a7da9b8c527d54c16c788ac14dac7/README.rst) | 真实多人规则/结算库，有6人、前注和straddle示例；[文档](https://pokerkit.readthedocs.io/en/stable/simulation.html)支持自定义rake；MIT | 规则/结算交叉校验，不是决策策略 |

`c-heidt`的完整52张牌路线文档描述约420GB磁盘、约150GB蓝图RAM，并有Linux/HPC依赖；quickstart是20张牌LUT，不能冒充完整NLHE。没有核实可直接使用的强蓝图或独立真人盈利记录。文档“What it prints”中的收益数字是输出示例，不当作实测证据。

本机实查为Core Ultra 5 245KF、14核/14线程、约31.6GiB RAM，不能直接按上述150GB常驻蓝图方案部署。先做有界模块和小规模独立实验，不因仓库名称含Pluribus就宣布复现。

另查到的`fedden/poker_ai`为归档研究脚手架，所查short-deck实现使用固定增量，不能直接当成任意下注尺寸的完整NLHE；其他Pluribus重实现证据不足，不优先接入。

非商用不等于没有许可条件。本轮仅记录必要出处与许可，未复制或运行许可不明项目的实现；部分新研究仓库未找到LICENSE，应在真正接入前解决。许可审查不替代技术推进。

## 3. 本轮实际实现

新增 `src/poker_engine/strategy/terminal_multiway_v1.py`：

- 6/7/8名已入局玩家，Hero之外实际2–7名all-in对手，即至少3人争池。
- river已知5张公共牌；Hero是当前actor且唯一ACTIVE，其他争池者均ALL_IN、stack0且确有投入。存在后续可行动玩家则拒绝。
- 人工范围和配置假设独立标识，不伪装simulation资产为live，不修改现有生产门禁。
- 分别投影call和fold，重建最终主池、边池和未匹配返还。已弃牌投入保留死钱，Hero无资格边池不分收益。
- 按配置分配抽水；总现金、下注一致性、筹码单位、额外费用、非法最高下注、未退前街超额等均检查。
- 精确联合底牌枚举、blockers和`Fraction`分配，支持精确三等分/七等分比较；默认4096联合组合、最大10000，超限拒绝。不声称硬墙钟时限。
- 输出CALL/FOLD/INDIFFERENT、两个动作EV、逐池份额/费用、返还和投入向量。**结果为COMPLETE_CONDITIONAL，不是生产Advice**。

经济口径：call EV是最终预期净分配加Hero返还减本次call成本；已投筹码是沉没成本，不重复扣除。fold EV保留可能返还，不能直接写死零。无法支持的未结清前街退款情形明确BLOCK。

明确限制：范围按独立权重乘积再对碰撞条件化；没有学习真实对手范围。平分采用fractional_equal_split，未实现物理奇数筹码分配。完整下注历史可达性未验证，不是ICM/风险偏好模型。未知额外费用、非river、bet/raise、多次发牌及超预算不支持。

独立数学审查发现并修复了“已弃牌者制造最高下注”及“未退前街唯一最高投入”的反例，未触碰被冻结的底池、范围或牌力内核。

## 4. 可运行入口

示例文件：`configs/strategy/examples/terminal-multiway-river-manual.json`。
这是6人桌、Hero加3名all-in对手、另2人已弃牌的人工假设案例，不是真实AA录像或已观察对手底牌。

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
$env:PYTHONNOUSERSITE='1'
& 'C:/Users/Administrator/.codex/runtimes/pokersense-v6-clean-20260908/Scripts/python.exe' tools/analyze_terminal_multiway.py --input configs/strategy/examples/terminal-multiway-river-manual.json
```

示例call成本60，最终池110/130/80；在该特定底牌假设下Hero赢得所有池，gross EV260，配置抽水封顶4后net EV256。它仅证明计算，不是“能赚256”的实战预测。

同一牌局只改变一名对手的范围，结果会改变：

| 对手假设 | 跟注净EV | 条件比较 |
| --- | ---: | --- |
| 仅KhKd | 256 | CALL |
| KhKd权重1、JhJd权重2 | 136/3 | CALL |
| KhKd权重1、JhJd权重9 | -142/5 | FOLD |

这也是下一阶段必须建立对手范围与动作响应模型的原因：精确计算无法替代准确的输入假设。

## 5. 以高收益为目标的开发顺序

1. 固定当前多人决策输入和结算口径，用独立可核算案例验证；不再等待视觉层全自动完成才开发策略。
2. 扩展可验证的范围资产、范围敏感性和更宽范围的数值方法；每项都标明真实数据、手工模型或模拟来源。
3. 普通下注与加注必须加入其他玩家响应及后续街策略。优先有限动作树、3名活跃玩家的可核查基线，再扩展更多争池者；桌人数仍保持6/7/8分别建模。固定响应模型的rollout属于模型策略，不冒称GTO。
4. 在隔离环境评估多人MCCFR/blueprint/search候选；成熟HU内核只进入HU分支。OpenSpiel/PokerKit用于环境和结算校验，不当成已训练策略。
5. 最后将通过强度与运行验证的模块接到人工确认／视觉输入。当前不启动真实采集或建议。

“胜率很高”的验收目标采用**扣费净bb/100、候选相对冻结基线的收益差、置信区间与鲁棒性**。使用重复牌局/座位轮换、多随机种子、独立对手池及6/7/8分别统计，避免只打随机弱bot或只看自博弈。记录回撤、超时、拒绝率和支持覆盖。

可以预先声明晋级条件为收益差95%置信区间下界大于0、受保护对手池无重大退化；这只能支持对应评估条件，不保证未来实战盈利。赢手比例不是优化目标，也不能用固定手数自动认定足够证据。

## 6. 研究证据边界

GitHub README/源码/测试为只读静态核对；本轮未安装、运行或训练第三方solver。论文论据来自Exa对原始论文/官方页面的实质文本抽取，Jina全文请求超时，不声称完整重新阅读全文PDF。来源冲突和未验证的作者性能声明均保留。

原始抓取及简报原存系统临时目录，最终副本与本轮测试、示例、范围敏感性结果保存于 `G:/PokerSense_private/multiway_strategy_start_20260913_v1/`。最终版本/哈希见本轮交付文件。

## 7. 本轮最终验证

44项新增聚焦测试通过；全仓3635 passed、1 skipped、2条依赖弃用警告（59.68s），全仓flake8为0（沿用aa_record_session.py排除项），任务7资产生成检查无漂移，V1冻结280文件哈希不变。原935个Git可见文件在写本轮AGENTS追加说明前全部字节未变。研究、数学模块和条件分析入口已交付；多人GTO、学习后的真实范围、一般下注加注策略与盈利验收没有被宣称完成。
