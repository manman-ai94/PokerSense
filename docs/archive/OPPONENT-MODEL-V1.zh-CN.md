# 对手建模 V1：公开响应数据入口与范围不确定性比较

本轮提供可运行的公开决策校准入口和固定策略多假设比较。实际开发记录审计结论是 **NOT_READY_FOR_REAL_ALL_DECISION_CALIBRATION**，不能把现有候选日志称为真实模型训练集。工程完成与真实校准资格分开记录。

## 已有记录究竟能用到哪里

只审计项目文件明确引用的开发日志和动作标签，没有浏览录像、图片、保留区或启动设备。私有证据根为 `G:/PokerSense_private/opponent_model_v1_20260914_v1/`。

| 已核对资料 | 去重后的记录 | 本轮可直接准入校准 | 缺口 |
|---|---:|---:|---|
| AA8 已有两份最终开发日志 | 5897 帧、59 候选动作，其中对手 52、对手 river 4 | 0 | 完整合法菜单、经审阅的决策前状态和动作时点；三手来自同次录制 |
| AA8 人工动作窗口 | 38 | 0 | 与前两手自动候选重叠，不增加样本量；没有完整机会覆盖 |
| WPK 已审阅 AcQh 单手 | 13 动作，其中对手 10 | 0 | 选中的 all-in 参考手，非完整会话；没有 river 动作或保存的完整合法菜单 |

AA8 的 59 个动作都能在此前 12 帧内找到对应 actor 候选，但在字形确认帧及其前一帧均不匹配。因此不能把字形稳定确认的时点，直接当作动作前底池/跟注额的时间锚。仅 17+5 条在前一帧可构成数值跟注额候选，也不等于真值。

WPK 两份 reviewed/completed 产物是同一手，不能计算两遍；AA8 与 WPK 属于不同规则总体，不能直接作为训练/验证对。`data-readiness.json` 保存 13 个源文件的哈希、现有清单绑定和逐动作检查，`data-readiness.zh-CN.md` 为可读复核清单。这里的 0 只针对本轮明确审计的记录，不声称整个 G 盘没有可用素材。

## 数据入口与模型边界

`opponent_dataset_v1.py` 要求先声明所有决策机会，再逐项绑定观测记录。每条保存会话、手牌、对手身份、物理座位、位置、桌人数、争池人数、street、动作前底池和跟注额、完整合法动作菜单、实际动作、证据哈希及审阅/UNKNOWN 原因。机会缺记录或任何记录缺字段，整组 BLOCKED；不能挑剩下的完整记录拟合，以免产生选择偏差。

训练/验证在协议里按整个会话分开；同一手不能跨会话重标，座位号不能替代玩家身份。同一玩家跨会话换座可以保留原座位后归一到模型 actor 0，仍需显式声明同一对手。身份与全量覆盖声明没有因哈希存在而被认证。

候选 JSON 显式提供响应权重与价格分档，协议绑定其文件哈希；候选、数据集及每条记录还绑定 `platform_id` 和 `rule_fingerprint`，防止不同规则混池。价格比采用 Fraction 精确计算，避免高精度金额先做 Decimal 加法被舍入。当前只拟合公开合法动作菜单和价格条件下的有限候选；位置、桌人数等是保留的审核字段，不宣称已学到位置效应。范围模型保持 `None`，没有从局部摊牌倒推所有未摊牌手牌。仅接受 6–8 人桌、3 ACTIVE 的 river 决策，其他街或争池人数保留为不适用原因。

合成完整示例用于验证工具链，状态始终 `NOT_REAL_CALIBRATION`。真实模板名称含 `NOT-DATA`，字段保留 null 和待审原因，默认 BLOCKED。即使用户提交完整人工声明，仍为待审的模型评分，不自动获得实战资格。

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
python tools/calibrate_opponent_models.py --dataset configs/strategy/examples/opponent-dataset-synthetic-example-v1.json --candidates configs/strategy/examples/opponent-public-candidates-example-v1.json --output G:/PokerSense_private/opponent_model_v1_20260914_v1/my-new-calibration.json
python tools/study_opponent_uncertainty.py --input configs/strategy/examples/threeway-river-response-manual.json --output G:/PokerSense_private/opponent_model_v1_20260914_v1/my-new-uncertainty-run
```

校准 CLI 创建新 JSON 文件，多假设研究 CLI 创建新目录，已有输出均不覆盖。校准 CLI 的具体输入示例见 `configs/strategy/examples/opponent-*.json`。实际 `dataset-synthetic-v1` 返回 NOT_REAL_CALIBRATION；`dataset-template-v1` 返回 BLOCKED、selection/calibration 为空，两次运行均绑定 9 项源码/示例/依赖的前后哈希。

## 多假设下选择一套策略

`robust_policy_selection_v1.py` 在开发用范围/响应假设里，分别计算每本冻结策略相对 check/fold 和 check/call 中较强基线的 EV 差，然后最大化最差差值；并列按 policy_id 排序。另列最差与最好绝对 EV，不能把“比基线少亏”称为盈利。

选择完成后，验证仅执行唯一选中的策略。验证前重算原开发比较以核实回执，但不会用验证结果改选。训练/验证世界必须具有不同 ID 和定义哈希；改名不能去重。任何候选在开发世界不完整或出现未覆盖历史 fallback，整组证据不足，不能删除它后宣布其余候选获胜。未选出策略时仍保留所有验证世界，明确记录未执行原因。

最终实跑 `uncertainty-v2` 保留五种规划策略、六个公开场景组和五个旧开发世界，共 150 项开发比较（验证回执还会确定性重算原比较，不计为新样本）。三个面对下注组选择原手工策略，但在新增手工范围/响应挑战下仍未通过，最差条件净 EV 分别为 -12.7/-12.2/-11.7 chips；三个未下注组因候选出现 fallback，返回证据不足。12 条预定挑战世界记录全部保留，其中后六条明确未执行；`uncertainty-v1` 保留，最终 source receipt 绑定 11 项代码/输入/测试的运行前后哈希。新工具没有自动把这种结果接成真实动作建议。

旧五种世界已被开发者看过，继续作为回归；新增挑战也是手工开发假设，不能称独立真实对手验证。算法属于有限假设下的最坏相对损失比较，不是 GTO、范围学习、全手 bb/100、利润证明或统计置信区间。仍共用既有规则/结算内核，不支持任意网格外下注、all-in 边池跨越或更多活跃玩家。

## 下一次真实数据工作

首先需要同一规则总体、可确认身份的对手在至少两个完整开发会话中的决策机会清单。先锁定会话划分，再逐项审阅动作前状态、完整合法菜单、实际动作和缺失机会。仅 4 个候选 river 对手动作不足以代表对手；不能把大量视频帧当独立决策样本扩大统计量。

在数据补齐前，可以运行手工假设分析和回归，但不能称已完成真实响应校准。数据补齐后先固定候选与训练/验证划分，运行入口，保留错误和零似然结果，再决定是否扩大模型表达能力。本轮没有改变识别阈值、读取保留录像、处理 MC deadline、提交、打 Tag 或推送。

## 最终工程验收

新增 46 项聚焦测试通过；全仓 **3815 passed、1 skipped、2 项依赖弃用警告（69.38s）**。全仓 lint 0（沿用 recorder 排除）、资产生成器 `--check` 与 `git diff --check` 通过。独立审查验证了数据缺口、身份和规则混池、LJ 位置、精确价格、最坏基线差目标、验证不重选及失败世界保留。

初始 955 文件在最终 AGENTS 状态注记前全未变；最终只给该文件追加本轮状态。V1 冻结 280 项、旧私有证据 9 项、数据审计源 13 项哈希均一致。本轮新增 12 个文件，最终工作区/源码副本/私有证据绑定在 `final-manifest.json`。

最终结论：**工程 PASS；真实对手校准 BLOCKED（已审计数据不满足准入）；手工策略挑战 FAIL/INSUFFICIENT_EVIDENCE**。成果待人工审阅，未放行真实采集或策略执行。
