# PokerSense 三轮合成诊断与回归整理

三轮有限验证已确认两类限制：当前SIMPLE平均策略收集可能漏掉已访问的信息集；
现有跨街抽象可能忘记翻前私有牌类。在冻结的小树中没有复现与独立SIMPLE语义
不一致的记账错误。测试专用OWN候选满足自身reach合同，但不能据此替换生产算法。

第一轮精确枚举1584条分类轨迹，其中1512条正概率执行、72条零概率NOT_RUN。
真实遗憾和SIMPLE平均量均符合不复用生产累加器的独立有理数参考。一个零概率
对手前缀案例中，30个信息集都被访问，但只有20个具备正SIMPLE平均量。合法六人
引擎下，KsJs与KsTs的翻前类不同，在相同公共历史和2c4d8h翻牌上合并为同一
抽象键；花色置换与隐藏牌完成变化没有消除这一碰撞。

第二轮在共同基线511156ad比较SIMPLE和测试专用自身reach收集器，计划2112条
轨迹，1704条执行、408条零概率NOT_RUN。候选增加了指定案例的平均键覆盖，并
保留遗憾、RNG与合法动作合同；两token记忆表示在固定语料中将6个键拆为8个，
每原键最多拆2。质量指标的方向却混合：一个有限树案例改善约0.03488，另一个
恶化约0.03569。因此没有建立统一决策质量提升，更不能推断真实扑克胜率。

第三轮补齐多历史共享同一信息集和已有非空提交量后的故障恢复。16个信息集
按自身reach只记一次，原始总量是14×权重；逐历史重复累加会变成44×权重，
归一化策略却可能几乎相同。已有OWN质量66、SIMPLE质量18时，两种故障均回滚
完整checkpoint与RNG，四组共12个继续臂与未中断及JSON恢复参考一致。完整物理
分母保留为3844：3347PASS、6个预期拒绝FAIL、491个守护后的NOT_RUN。

已确认的是这些冻结合成案例中的数学记账、覆盖限制、表示遗忘和事务不变式。
尚未证明的是真实策略更强、遗忘造成实际质量损失、候选在六人扑克规模下可用，
以及实际设备端到端实时决策延迟。覆盖、决策质量、端到端延迟、拒答正确性仍需
分别验收。没有真实扑克训练、平台接入、实盘或生产策略/编码改动。

本批从511156ad单独整理47项可移植回归，不依赖旧工作区或原始追踪。它保留
公开小树、固定策略、合法合成牌组、独立参考和简明历史摘要，修复新输出的PASS
残留reason及P3异常分类。旧三轮追踪/hash保持原样；新回归结果单独登记，不能
把旧实验PASS称为新代码已经通过。研究累计预算仍为58,455节点／13.324秒，
低于200,000／180秒；新CI回归计量与研究账本分开。

下一步门槛明确：便携回归可以进入独立审阅；隔离且未启用的守护/事务组件只能
进入另一个有实际接线验证的草稿。生产OWN替换继续HOLD，直到平均语义、质量
和规模复杂度有充分证据；翻前记忆编码也继续HOLD，直到工件兼容、平均键来源
与质量证明补齐。产品方向保持允许辅助场景中的实时对战决策，不增加复盘、
练习或教练功能，不承诺胜率或实战资格。

本报告及小型合成摘要可公开；完整追踪和执行日志留本机。当前批次只包含测试
和说明文档，任何合并仍须用户另行确认。

新回归验证记录（与前三轮独立实验分开）：执行源码提交为
`8feea0823d093b2e838fe45e1936032ef0501606`，11个模块执行前后SHA256一致。
Python3.12.14、Node24.19.0、PokerKit0.7.5，使用既有CPU与依赖。
相关检查158PASS（其中47项新增），全量5230PASS＋8平台SKIP、0FAIL/ERROR，
全量进程墙钟634.762秒、最大RSS810744KiB。8项跳过分别为4项Windows cmd、
3项Windows ctypes.WinDLL、1项macOS Quartz；新增合成检查没有跳过。
全量lint、57项JS（8实时TTL、39分析UI、10设置UI）、11项独立参考检查通过。
两个实际pytest选择各计量14,030次调用；相关检查整个进程3.401秒、RSS87200KiB。
这些是合成回归/完整CI风格检查开销，不是研究新增预算或硬件端到端速度。
跨平台运行仍须以此批Draft PR对应CI为准，解析Python3.11语法不算执行证据。

发布候选精确15文件清单如下，原始追踪、执行日志和运行环境记录不在其中：

```text
AGENTS.md
docs/AA-SYNTHETIC-REGRESSIONS-20260930.zh-CN.md
docs/reports/POKERSENSE-THREE-ROUND-SYNTHETIC-SUMMARY-20260930.zh-CN.md
tests/fixtures/aa_synthetic_diagnostic_evidence.json
tests/strategy/aa_regression_own_component.py
tests/strategy/aa_synthetic_exact_reference.py
tests/strategy/aa_synthetic_regression_support.py
tests/strategy/aa_synthetic_shared_component.py
tests/strategy/aa_synthetic_shared_reference.py
tests/strategy/aa_synthetic_status.py
tests/strategy/test_aa_synthetic_accounting.py
tests/strategy/test_aa_synthetic_recall_limit.py
tests/strategy/test_aa_synthetic_shared_information.py
tests/strategy/test_aa_synthetic_status.py
tests/strategy/test_aa_synthetic_transactions.py
```

内容核验仅涉及本批文件及其提交范围：公开固定合成牌组/小树、数学参考、测试
组件和汇总计数/hash。没有私有策略、真实牌局素材、个人资料、凭据或环境文件。
文件名守护仅检查Git索引，不能代替上述内容与完整提交范围审阅。
