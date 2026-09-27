# AA 十秒方案：工程交付与验收清单

本增量以 `af67b4bb3ba56da2d4fdb70e0731583afc7aaf40` 为基线，版本
`0.2.0.dev1`。**工程预览，不是已验证的实时策略产品。** 目标仍是物理八座、
6/7/8 人四街策略，以及源画面到建议 p95≤1 秒／p99≤2 秒。没有通过验收的
功能不会因为设置了时间参数、生成了模型或测试通过而自动获得实战资格。

后续[V2策略验证已完成](AA-POLICY-READINESS-RESULTS-20260927.zh-CN.md)：评估链与可复现
学习信号通过，九个候选的新牌局可执行率仅4.44%–8.89%，翻后查询均未命中。
本轮已停止扩大训练；九份实际资产的本地影子接口通过不改变其NO_GO结论。

## 已实现

| 子系统 | 可使用的交付 | 当前证据边界 |
| --- | --- | --- |
| 十秒窗口 | 绝对截止、前两秒首结果、三秒操作余量、来源年龄、身份失效 | 合成时间证据；当前 reader 无可信现场起点／倒计时 |
| 本地影子执行 | 预加载进程、300ms 外部截止、超时终止、固定决策采样 | `AAFrozenShadowSession` 接通仿真观察到冻结资产；没有生产 Advice 注册 |
| AA 桌面 | 正确 AA 入口、版本、自检、离线启动、来源和拒答状态卡 | 默认不采集，私有模型外置；macOS 仍明确为 legacy 壳 |
| 全手环境 | PokerKit 0.7.5、6/7/8 人、四街、UTG straddle、边池／退款／抽水 | 配置模拟规则；分数筹码平分，不宣称 AA 真实零头规则 |
| 训练器 | external-sampling MCCFR、线性 SIMPLE 平均、预算、事务回滚、续训 | 多人经验算法；没有多人 Nash 收敛或强度保证 |
| 冻结策略 | 规则、人数、初始深度、编码器、摘要绑定；未见信息集拒答 | 所有资产固定 `research_only`；改摘要也不能开启 live |
| 配对评估 | 同牌换座、独立策略随机 salt、保留失败、按 seed 换座组 bootstrap | 合成对手结果；非随机策略平均胜率或真实盈利认证 |
| Jev 对照 | 固定 1.13.0 请求、严格 Choice 验证、原始回执、录制响应重放 | 无内置 HTTP／自动付费；需显式合成来源，无实战接线 |

旧 `BASELINE_V1` 及其冻结源文件不修改；新实验另有规则、协议与结果目录。
旧 dirty primary、PR35 失败研究及 PR36 历史结果不搬进本增量。

## 本地使用

桌面双击 `launch/aa/START-AA.cmd`。分发使用完整 `dist/PokerSense-AA` 文件夹，
不能只复制 EXE。默认只开放离线页面，`--self-check` 不启动设备或服务。

源码实验使用项目 Python 环境并安装 `[solver-tools]`，设置 `PYTHONPATH=src`、
`PYTHONUTF8=1`。以下命令不会开启采集、外部模型、云实例或自动晋升：

```powershell
python -m tools.aa_full_hand_lab smoke --players 8 --hands 3 --output outputs/arena-smoke
python -m tools.aa_full_hand_lab train --players 8 --seed 1103 --iterations 10 --seconds 30 --max-nodes 10000 --output outputs/train-n8
python -m tools.aa_full_hand_lab evaluate --players 8 --candidate outputs/train-n8/policy.json --blocks 2 --output outputs/eval-smoke
```

自动串联九个配置的工程批次使用：

```powershell
python tools/aa_self_play_study.py --smoke --output outputs/study-new --training-seconds 1 --iterations 1 --max-nodes 1000 --max-infosets 1000 --max-actions 100
```

它在首次训练前冻结全部计划、协议和代码摘要，随后训练、保存策略、重新加载评估、
保留全部结果。详细预算、分母、中断和源码漂移合同见
[单命令研究说明](AA-SELF-PLAY-STUDY.zh-CN.md)。

输出目录必须不存在，避免覆盖旧研究。训练每完成一个完整 sweep 原子更新
`latest-checkpoint.json`；`checkpoint.json` 是本次结束状态。续训使用新的输出目录
和 `--resume <旧checkpoint>`，规则、深度、协议、种子、编码器必须完全一致。
预算中止保留先前完整 sweep，但失败 sweep 的 regrets、平均策略与 RNG 均不提交。
`COMPLETE_RESEARCH_RUN` 只表示声明次数执行完毕，不表示策略强度达标。

评估省略 `--blocks` 才使用协议规定的每人数、每对手 2000 个配对块。
`--blocks 2` 只是工程检查，输出 `protocol_sample_complete=false`，不得当作验收。
未覆盖信息集不会自动弃牌，保留为 BLOCKED 并使该组 EV 和区间为空。

首轮编码器为翻前 169 类、翻后 64 个**牌型／高牌纹理桶**，不是已校准的潜在
牌力分布桶。其抽象、公开历史及筹码组合可能导致覆盖稀疏；这是当前实验的限制，
不得宣称已经压缩出高覆盖策略。SIMPLE 多人平均是近似，完整树无偏平均未实现。

## 验收协议与尚未完成

协议在 `configs/strategy/evaluation/aa-full-hand-protocol-v1.json`。训练发牌 seed
限制在 ≥2^62，评估／确认使用独立的低位区间；策略采样 salt 由独立随机源产生，
不把环境发牌 seed 发送给策略。规则中的 1/2、ante2、straddle4、3%／2BB 均为
既有明确模拟配置，不能解释真实 AA 费用。

- 全部 6/7/8 人、三个训练种子、固定对手池与样本量均须保留。CLI 支持逐配置与
  有界自动批次，不提供无人值守长期调参或自动晋升；不自动选择“最好种子”。
- 全套预定 2000 块评估、未见风格／针对性对手、混合桌、50/200BB／不等码压力测试、
  独立确认与 5BB/100 非劣门槛仍需完成。当前基础脚本对手不足以证明策略稳定。
- 不足额强制盲注／straddle 开局被拒绝，避免 PokerKit 低于名义盲注的语义偏差。
  正常支付强制下注后的短码全下受支持；真实零头派彩规则仍未验证。
- Jev 本轮没有真实请求、费用、吞吐或强度测量。录制响应适配器不能冒充真实 API
  验收；若另行授权调用，必须使用显式离线 transport 和费用限制。
- 真实回合起点／倒计时适配、完整合法状态、实战资格审批、生产动作显示仍未完成。
  当前真实 `/api/status` 始终拒答，不会将研究模型自动注册为实战 Provider。
- 主机时序、进程时间和合成测试不能证明物理端到端 p95/p99。需另行授权的至少三个
  会话、100 个 Hero 机会及足量故障／回放验证，所有 UNKNOWN 和超时均保留分母。
- 安装包 EXE 冒烟与安装器编译／实际安装分别记录。工程预览不建立 Release、不合并
  主线，不开启云训练或发布。

## 本轮有限实验结果

完成每个人数 3 手完整四街 smoke，另对 6/7/8 人各三个训练种子运行最多 10 sweeps、
每次 3 秒的本机工程探针。两组完成 10 sweeps，七组达到时间预算；所有九组均保留。
这些预算远小于正式研究预算，不能据此判断 MCCFR 长期学习效果。

勘误：八人 seed1103 的原 48 个配对机会全部在策略绑定时因
`independent_policy_salt_required` BLOCKED，尚未验证策略覆盖。旧报告原样保留。
该结果不产生 EV 或收益结论；不能用训练成功或 Kuhn 小游戏通过掩盖接口失败。

单命令 smoke 另执行九个配置，各完成一轮 sweep。原 378 个配对也全部因为上述
参数类型不匹配在绑定阶段失败，不能据此声称完整评估链通过或覆盖不足。
修复后用原资产、规则、种子、筹码和预算实际重跑，才得到 378 次信息集未命中，
且全部发生在首次 Hero 行动。九份资产的 592 条分布均匀，只有首轮工程更新，
不足以评判长期学习效果。正控 42/42 完成并与直接策略一致，详见
[评估链勘误](AA-EVALUATION-CORRECTION-V1.zh-CN.md)。批处理原 15 项聚焦测试通过，
独立复审修复了声明训练 seed 域与学习器实际域不一致的反例。

原 3 项独立 P1（续训绑定、嵌套隐藏信息、异常 checkpoint 部分更新）均已修复并
独立复验。详细运行和打包证据保留在实施目录的 `outputs/`，不包含真实媒体。

集成验证：完整本地 pytest **4701 passed / 2 skipped**，耗时 471.96 秒；完整
flake8 和 diff 检查通过。旧 30 场景基线摘要仍为
`c1a725f3f95a76261fb041af200e45bae02b6836202b36ec56578f0afd680aae`。
实际 JavaScript 检查 39 个原分析场景和 8 个新 TTL 场景通过；浏览器实际检查了
冻结 EXE 的观察页和拒答状态卡。冻结 EXE 在无源码工作目录／无 PYTHONPATH 下
通过自检、13 个端点及独立子进程计算，并拒绝默认采集请求。本机没有 Inno Setup，
安装器编译使用下述 GitHub 构建，而非本机编译。

初始工程 head `5ce06ca` 的 GitHub CI `36301773529`（Windows/macOS/hygiene）
与构建 `36301786735` 已通过，后者已编译 AA Windows 安装器并跳过 Release。
新增独立批处理工具之后的最新 head 另行核对 CI，不能继承旧提交绿灯。

该 CI 安装器已实际进行隔离安装、冻结 EXE 冒烟及卸载，功能检查通过且测试登记项
与目录恢复。但 `/NOICONS` 未生效，原 audit 保留失败状态。安装脚本已补
`AllowNoIcons=yes` 和回归断言；修复后的安装器须重新构建验证，最终结果记于 PR37。
