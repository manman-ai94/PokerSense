# AA 单命令离线自博弈研究 v1

`tools/aa_self_play_study.py` 把既有学习器、冻结策略、全手仿真和配对评估连接
成一个有预算的本地研究批次。它不修改学习算法，不自动调参，不选最好种子，
不调用 Jev／云算力，不连接真实采集，也不将任何结果晋升为实时策略。

## 最短工程检查

在仓库根目录、已安装项目依赖和 PokerKit 0.7.5 的 Python 环境执行：

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONUTF8 = "1"
python tools/aa_self_play_study.py --smoke --output G:/PokerSense_private/study-smoke-new --training-seconds 1 --iterations 1 --max-nodes 1000 --max-infosets 1000 --max-actions 100
```

输出目录必须不存在。所有预算必须显式提供；不会复用、覆盖或自动追加旧结果。
`--smoke` 保留 6/7/8 人 × 协议的三个训练种子，总共 **9 个配置**，但每个对手
只运行 2 个配对换座块，bootstrap 为 100 次。每组训练最多使用请求预算与
2 秒、1 次完整 sweep、2000 nodes／infosets 中较小的限制。评估每手 action
上限同样显式限定，smoke 最多为 200。该模式始终标注 `ENGINEERING_SMOKE_ONLY`。

去掉 `--smoke` 后，每个配置、每个对手固定运行协议的 **2000 个配对块**；
三个对手为 check/call、最小加注和菜单中最大非全下加注，基线为免费过牌否则
弃牌。完整批次共 **378000 个配对比较**，不得把它当成便宜的启动检查。
训练预算为每个配置整个训练阶段的预算，不是每次迭代重置预算；九组总预算
记录在 manifest。初始化、序列化及评估耗时另计，因此该数字不是完整命令的
硬墙钟截止承诺。不要为得到正结果自动增加迭代或测试样本。

## 冻结与证据顺序

开始训练前先保存只写一次的 `frozen-manifest.json` 和 `protocol.json`。
manifest 列出全部 9 个计划配置、规则身份、训练与评估预算、固定基线与对手、
参与执行的项目源码文件哈希、Python／PokerKit 版本及协议哈希。种子域校验
绑定学习器实际使用的 `[2**62, 2**63)` 训练域；评估和确认的完整 2000 种子
区间必须互不重叠且在训练域之前。

每个 `nN-seedS/` 目录依次写入：

1. 规则与可恢复的 `latest-checkpoint.json`。
2. `training-report.json`、最终 `checkpoint.json` 和冻结 `policy.json`。
3. 重新从已保存的策略读取并验证，再运行 `evaluation-report.json`。

每次开始拟合、完成拟合和完成评估都检查源码哈希。代码中途变化时，相关及
后续配置保留 ERROR，不会把新代码重新标成原冻结版本。源码哈希和库版本是
可复核标识，不是对实验环境真实性的密码学认证。

## 失败处理与读报告

`study-report.json` 在首次训练前就含全部 9 行；每个阶段更新，最后保留所有
成功、预算不足、拒答、异常和未启动配置。Ctrl+C 会保留当前 checkpoint，
当前配置标注 INTERRUPTED，剩余配置标注 NOT_RUN_INTERRUPTED。

- `actual_runs=9` 表示报告保留了九个配置，不表示九组都执行成功；必须一起看
  `started_runs`、`complete_runs`、各行阶段状态。
- 全部配对分母为 `complete_pairs + blocked_pairs + unreported_pairs`。
  unreported 表示没有可报告的完整结果，不能称为已执行、成功或失败样本。
- 预算耗尽时保存已有完整 sweep 的 checkpoint 与策略，并继续评估该冻结
  候选；该配置仍标注 BLOCKED，摘要指标置空，不冒充完整训练成功。
- 评估有拒答、非法动作、超预算或异常时保留记录，相关汇总指标置空。
- 各组 artifacts 字段给出已保存 JSON 的 SHA256；顶层绑定原始 manifest、
  协议与源码哈希。不会自动重试失败配置或只展示最好种子。

顶层 `strategy_quality=NOT_ASSESSED`、`strategy_eligible=false`，晋升始终
被阻断。即使九组都完成，也仅表示研究批次执行完整；固定脚本对手成绩不能
替代未见对手、风格漂移、压力测试、独立确认或实际 10 秒窗口验收。
