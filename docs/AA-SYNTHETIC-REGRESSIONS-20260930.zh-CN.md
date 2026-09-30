# 有限合成诊断的便携回归

本批只整理测试与证据说明。生产基线为 `511156ad`，生产 collector、编码和策略
没有修改。旧三轮实验与原始追踪保持不变；新回归不是旧实验重跑，也不能用旧结果
证明新源码通过。精确历史摘要见
[`aa_synthetic_diagnostic_evidence.json`](../tests/fixtures/aa_synthetic_diagnostic_evidence.json)。

新回归源码最初提交为 `8feea082`，恢复合同修订源码为 `5ed6ca6`。
固定83项检查不读取旧工作区、预算账本或追踪，
不依赖 `/workspace`、固定源码 SHA 或历史 RNG 指纹，不生成持久策略工件。
项目支持的 Python3.11–3.13 均可解析；实际跨平台执行结果另行记录，不能以解析
通过代替 Windows/macOS 验收。

| 测试模块 | 固定范围与断言 |
| --- | --- |
| `test_aa_synthetic_accounting.py` | 6组原有小树配置；1056分类轨迹=920正概率执行＋136零概率NOT_RUN。独立终端 Fraction 参考核对真实 `_walk` 的 regret 和 SIMPLE；visited、average-eligible、positive-average分别比较。 |
| `test_aa_synthetic_recall_limit.py` | 6条合法六人轨迹、108步、24编码：原始牌对、1个花色置换、1个隐藏完成变化。不同翻前类在固定翻牌/转牌碰撞、河牌重新区分，作为已知限制通过断言，不使用xfail。 |
| `test_aa_synthetic_shared_information.py` | 6组完美记忆16I小树；原始OWN质量14w，逐历史重复量44w，归一化可能掩盖错误。重复观察必须保持私有可见历史、自身动作、菜单、策略和reach一致，泄漏/遗忘冲突拒绝。 |
| `test_aa_synthetic_transactions.py` | seed17两次提交后的非空OWN/SIMPLE，collector第3进入和walk第7进入故障；完整checkpoint/RNG/旧量保留，2步×3臂续算，稀疏导出不补键，独立Fraction归一化与真实export接口。 |
| `test_aa_synthetic_status.py` | 50项状态/恢复检查：合同断言FAIL、基础设施ERROR、缺前提NOT_RUN、预算/用户中止INTERRUPTED；稳定id部分恢复保留未执行行与顺序，非法身份/结构拒绝，用户中止记录后传播。 |

两个参考模块只使用标准库和独立公式，不调用被测累加逻辑。两个 OWN 组件只在
`tests/strategy/` 内，生产算法保持 SIMPLE。候选守护/事务回归与实际接线尚有区别。

前轮第三次追踪有36个PASS对象残留初始 `NOT_REACHED` reason。此处只修复新
测试状态转换与恢复器，并验证真实事务/非法导出菜单异常走FAIL分类；旧追踪和hash
不改写。旧枚举中的零概率轨迹、守护后的未运行后缀也不从分母删除。

初版47项回归通过后，父任务发现 `overlay` 仍整段替换列表：只更新 `done` 会
删掉计划中的 `later`。旧检查给两份输入都提供了 `later`，因此没有发现此问题。
修订增加36项元数据边界回归；旧源码/PR head的测试与CI仅为历史证据。
修订恢复按每个列表内的非空字符串id合并，保持冻结顺序和遗漏行；嵌在字典或
行字典内的子计划同样处理，同名id可在不同列表中独立存在。重复/未知id、
新增计划列表（包括空列表）、容器类型替换、匿名/裸嵌套数组及非有限JSON形状
均明确拒绝。已有计划的空patch不删除行，PASS reason清理仍会应用。
该辅助器只恢复冻结计划证据，不用于任意checkpoint或数据数组。

在已安装项目现有测试依赖及 PokerKit0.7.5 的环境中，从仓库根目录重建：

```text
python -m pytest -q -rs tests/strategy/test_aa_synthetic_accounting.py tests/strategy/test_aa_synthetic_recall_limit.py tests/strategy/test_aa_synthetic_shared_information.py tests/strategy/test_aa_synthetic_status.py tests/strategy/test_aa_synthetic_transactions.py
python -m pytest -q -rs
python -m flake8 src tests tools
node tests/ui/test_aa_turn_runtime_ui.js
node tests/ui/test_aa_analysis_ui.js
node tests/ui/test_aa_table_settings_ui.mjs
python -m pytest -q -rs tests/tools/test_strategy_eval_independent_oracle_v1.py
```

需要单独计量时，可给pytest加 `-o junit_family=legacy --junitxml=result.xml`。
完整选择83项时，`synthetic_nodes`总计14,030（SIMPLE10,244、事务1,304、
记忆397、共享信息集2,085）。这里的节点是明确的参考项/遍历/API调用计数，
不是CPU指令数。各模块共享fixture成本归给第一个实际选中的检查，单独运行一个
检查也不会漏记已执行成本；后续只读断言不重复计量。

新CI风格回归开销单独记录，不加入历史研究账本。历史累计仍为58,455节点／
13.324054秒，上限200,000节点／180秒；没有追加研究样本。
本批相关/全量/JS/参考检查结果、平台skip与发布文件清单在合并报告中登记。

**生产集成门槛仍为HOLD。** 便携测试可用于审阅；未启用的独立组件需要单独草稿
与真实接线验证。直接替换SIMPLE仍欠质量、适用平均语义及规模预算证明；记忆编码
仍欠工件兼容、平均键来源与质量证明。前轮两案例质量方向混合，覆盖增加不能代表
策略更强；碰撞只能证明遗忘。合成计算时间不能代表捕获到显示的端到端延迟。
产品目标仍是允许辅助场景中的实时决策，本批不加入复盘、练习或教练功能。

发布候选内容只有11个新测试/辅助Python文件、上述小型公开合成JSON、本说明、
三轮合并报告与AGENTS状态记录。三份11.4MB/40.7MB/9.45MB完整追踪及执行日志
留本机；不发布私有策略、真实牌局、媒体、个人资料、凭据或环境文件。
