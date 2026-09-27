# PokerSense

当前增量为 **AA 工程预览 0.2.0.dev1**：Windows 打包已统一到 AA 专用入口，
双击 `launch/aa/START-AA.cmd` 可打开本地离线页面。新增十秒行动窗口与过期拒答、
可终止的本地影子策略进程，以及 6/7/8 人全手仿真、有限 MCCFR 训练和配对评估。
**尚未开放实时动作建议**：当前没有经过验证的回合计时来源或合格策略资产，
真实端到端 p95/p99 和策略强度仍待验收。默认不采集、不调用模型 API，私有模型外置。
使用方法、原批次接口失败的勘误与修复后覆盖诊断见
[十秒方案实施清单](docs/AA-TEN-SECOND-IMPLEMENTATION.zh-CN.md)。
原 378 次失败首先由采样参数类型不匹配引起，不能直接归因于策略覆盖。
修复后实际重跑才确认了信息集缺失；见[评估链勘误](docs/AA-EVALUATION-CORRECTION-V1.zh-CN.md)。
需要固定批次的训练→冻结→评估，可使用[单命令离线研究工具](docs/AA-SELF-PLAY-STUDY.zh-CN.md)；
它保留九个配置及所有失败，不自动调参、选最好种子或晋升实战策略。

关键公牌、参与状态、ALL-IN 与河牌首位行动者候选现在携带来源和时序证据。
快照预填遇到缺失、过期或冲突的关键证据会拒绝带入；缺少因果证据的旧缓存也拒绝带入。
旧记录保留原候选，但可能需要
人工补录。当前未预处理牌面也必须支持跨帧公牌候选。这些检查不代表视觉准确率或
真实手牌已经验收，详见[五字段专项验证合同](docs/AA-CRITICAL-PERCEPTION-VERIFICATION.zh-CN.md)。
仅验证感知时显式关闭河牌分析旁路。

[TARGET-S 确认合同](docs/AA-REAL-HAND-CONFIRMATION-V1.zh-CN.md)使用独立的证据绑定确认历史，
旧确认记录不会自动升级。事实确认及当前有效 receipt 不代表 PHH 就绪、策略资格、
独立视觉验收或盈利成立。

**简体中文** | [English](README.md)

## AA 八座开发工具

新增 [V5 离线复查与河牌条件核算](docs/AA-STRATEGY-ENTRY-V5.zh-CN.md)：带出保存画面的牌面、底池和跟注额候选，用普通表单进行并保存保守收益边界计算。无需API密钥；费用未知时不输出净收益保证。补了开局/投入衔接与跟注价格，但尚未形成全街强策略或盈利验证。

已保存画面可生成带来源标识的手工河牌策略输入草稿，缺失范围/费用/投入保留待填；不会自动给当前牌局建议。观察页状态轮询缩短至250ms，端到端时延仍需实测。

新增[简洁观察台与 DeepSeek 视觉复查](docs/AA-REVIEW-DESK-AND-VISION-API.zh-CN.md)：观察、复查记录、设置分开；一键保存固定画面，人工纠正留历史。明确勾选并提交时才把该截图和对应字段发给DeepSeek。密钥仅存本机服务内存，重启需重填；有每日调用次数限制。AI结果为复查候选，不会自动训练或生成实战策略。

明确授权某一现场轮次后，也可运行有限自动抽查：最短30秒一次、最多20次，停止观察或换来源即结束；该轮次的截图及对应字段会发往DeepSeek。定时抽查记录与人工确认分开，不自动续期。

源画面预览按竖屏比例放大，支持“大图预览”与滚动查看细节；大图实时更新，关闭不停止回放。人工复查方法见[第一手复核](docs/AA8-FIRST-HAND-REVIEW-20260915.zh-CN.md#人工复查操作)。

已增加[动作语义与结算候选阶段](docs/AA8-ACTION-SEMANTICS-AND-SETTLEMENT.zh-CN.md)：基于扣款前价格区分下注/加注/跟注与all-in，清台后将历史账本与当前差额分开；未知和未解释款项继续保留，不放开自动策略资格。

当前增量支持[手动桌规、连续观察、问题记录与多人河牌条件分析](docs/AA-TABLE-VALIDATION-V2.zh-CN.md)，可使用[便携私有资源包](docs/AA-RUNTIME-BUNDLE.zh-CN.md)。条件分析通过独立进程运行，示例与当前观察分开；真实视觉资格和高盈利策略尚未成立。

新增独立的 AA 八座观察入口：支持本机模型预检、明确开始/停止、设备编号选择、开发帧回放、八座字段与预览、异常和过期清空。运行与打包见 [AA 观察工具](docs/AA-LIVE-MONITOR-V1.zh-CN.md)。当前已验证源码开发回放与浏览器操作；采集卡实机、完整合法状态和强多人策略尚未验收。私有模型外置，不包含在公开仓库或安装包中。

当前执行路线：[AA视觉优先工作计划](PLAN-AA-vision-first.zh-CN.md)；[WPK视频计划](PLAN-WPK-video-first.zh-CN.md)保留为回归；规则与案例：[德州规则底稿](docs/WPK-RULEBOOK.zh-CN.md)。先使用本地录像推进，最后做采集卡真机验收。

当前采集卡时序保护已推进到v9，正式路径仍保持拒答；离线候选诊断与实际源视频对照可继续运行。旧静态精度不代表新版本已验收。
本地开发版本在帧源故障后清空临时识别证据，并在重试前发送不可用、无建议快照，保留历史牌局。
掉帧、时间异常和ROI变化的受控测试已通过，真实设备及浏览器端到端恢复仍待验收，见[连续性检查报告](docs/WPK-V8-CONTINUITY-REVIEW.zh-CN.md)。
当前牌面与融合历史矛盾时会拒答并重新积累；相似牌受控切换及其准确性/拒答代价见[v9报告](docs/WPK-V9-HANDOFF-REVIEW.zh-CN.md)。
重复像素仅作诊断：既不能把静止牌桌直接判为冻结，也不能凭主机帧号证明来源正在更新。

PokerSense 是德州扑克实时训练伴随工具。当前本地开发主线为 **手机 + 采集卡、AA扑克8个物理座位、6–8人参与**，WPK保留回归。
已接入按在局人数计算的随机范围摊牌胜率和可调整的牌桌规则页面。采集卡动态识别、完整行动重建与翻后策略仍在开发；
参数完整或模拟页面能显示结果，不代表已经支持相应策略，也不代表盈利已验证。

启动、工具及最新证据见 [WPK 本地进展](docs/wpk-progress-2026-09-08.md)。模拟默认值和真实规则明确区分；
盲注、前注、3% 等抽水比例、封顶和 straddle 可以在设置页修改。产品只允许真机采集卡入口；AA扑克和微扑克都会限制模拟器登录，因此 ADB/雷电不再是可选项。

PokerSense 不是自动打牌机器人：不会点击、输入、下注或控制扑克客户端，真人始终是唯一执行者。目标
场景是朋友自建牌局、对练、教学和刻意训练。

## 历史 ADB 证据（不可选择）

下表只记录以前独立标定的 **Windows 雷电模拟器 WePoker Android 竖屏** 证据，用于解释历史回归；不能作为部署路径，也不能当作采集卡已通过。

| 功能 | 状态 |
|---|---|
| Windows 雷电模拟器 ADB 采集 | 仅保留历史回归；产品 CLI 会拒绝 `--source adb` |
| WePoker Android 1440×2560 竖屏底牌识别 | 已标定 |
| WePoker Android 公共牌和街道 | 已标定；发牌/翻牌过渡帧会拒绝写入 |
| WePoker Android 总底池 | 已标定；文字标签、菜单和遮罩会拒识 |
| WePoker Android 逐槽位筹码 | 已标定 8 个固定视觉槽位；空座和遮挡会拒识 |
| WePoker Android 座位占用和位置 | 已标定 8 个槽位；通过版本化 Android mapping 形成规范 seat 和位置 |
| WePoker Android Dealer 标记 | 已标定为视觉槽位；只通过版本化 Android mapping 转换为规范 seat |
| Hero 行动方和已完成动作 | Hero 当前行动回合及 fold/check/call/bet/raise/all-in 已标定；对手当前计时圈仍拒识 |
| 胜率计算 | 可用；按已识别的可见牌对随机范围计算 |
| 中英文界面 | 可用；语言选择会在重启后保留 |
| 规范行动历史和金额 | 动作标签经过去重和 seat mapping；只有筹码差额与底池证据一致时才接受金额 |
| 可解释建议、范围追踪和训练反馈 | 合同和 UI 已实现；没有合格的多人策略 Provider 时仍拒绝显示动作 |
| 自动打牌或控制客户端 | 永不提供 |

当连续帧确认到一对不同的底牌时，PokerSense 会自动开始新的一手。发牌动画中的单帧变化不会直接写入状态。

Android 标定现由原有 66 张去重 ADB 帧、234 张全分辨率牌桌帧和一段 88 分钟时序录像共同支持。
每个字段使用独立证据：座位占用在 272 个稳定槽位状态上复核；Hero actor 在 33 个行动帧命中并对其余
201 帧拒识；Dealer、筹码和动作都通过版本化 Android mapping 绑定。私有原图和录像不进入 GitHub 或安装包。

## 安装状态

正式仓库尚无已验收的新 Release。历史 v0.1.11 通用入口不能代表当前 AA 产品。
0.2.0.dev1 的 Windows 工程包使用 AA 入口，必须分发完整 `PokerSense-AA` 文件夹；
安装器、硬件、真实时延和策略资格分别验收，不能把离线 EXE 检查当作实战已上线。

## 模拟器入口已关闭

两个桌面入口都会拒绝 `--source adb`。ADB 后端只作为历史离线回归依赖保留，不能重新接回用户可选采集源。当前开发使用 G 盘既有 AA 真机采集卡录像，之后的硬件验收也必须使用实体手机与 UVC 采集卡。这不授权实时建议或控制客户端。

## AA 被动实战采集

新增的 AA 采集入库工具只支持一次性人工授权后的实体手机＋UVC 采集卡
video-only 录制。它固定关闭识别、策略、Advice、自动操作、网络、音频、模拟器和
ADB；没有授权、授权过期、nonce 重复、输出目录已存在或任一禁止能力被打开时，
都会在启动 FFmpeg 前拒绝。每次新录制先进入私有隔离区，按 60 秒分段并生成哈希
收据；成功录制仍不是校准或策略证据。操作合同和硬件演练顺序见
[AA 被动采集入库 V1](docs/AA-PASSIVE-CAPTURE-INTAKE-V1.zh-CN.md)。

## 隐私与本地数据

普通桌面识别的采集卡帧只在内存中处理并丢弃，不保存截图、视频或帧历史。只有用户
针对一个 session 明确授权 AA 被动采集时，独立 intake 工具才会把原始 video-only
分段写入 `G:/PokerSense_private`；这些分段、昵称和私有身份映射不能进入 GitHub、
PR 或安装包。真实标定原图同样属于私有离线数据，只保留必要的脱敏回归样本。

界面语言与牌桌规则分别保存。语言设置位置：

- macOS：`~/Library/Application Support/PokerSense/settings.json`
- Windows：`%APPDATA%\\PokerSense\\settings.json`

该文件只保存 `auto`、`en` 或 `zh`。`auto` 会使用系统语言。牌桌参数保存在同目录的
`table-rules.json`，切换语言不会覆盖规则。诊断回放工具仅读取你指定的本地归档视频。

## 开发

支持 Python 3.11–3.13。

```bash
# 安装开发依赖
pip install -e ".[dev,desktop,perceptual]"

# 运行检查
make test
make lint

# 启动桌面应用
make run-desktop

# 仅启动本地服务
make run-desktop-server

# 构建本地应用包
pip install -e ".[dev,desktop,packaging]"
make package
```

桌面应用组装代码位于 `src/poker_engine/desktop/`，实时更新链路位于 `src/poker_engine/realtime/`，平台标定
位于 `configs/`。

## 识别与标定

PokerSense 使用 OpenCV 角标模板匹配和按平台配置的布局映射。Android 底牌几何和置信度已用真实 ADB 帧
验证；标定数据和说明见：

- [`configs/platform/wepoker_android__ldplayer_portrait_1440x2560.json`](configs/platform/wepoker_android__ldplayer_portrait_1440x2560.json)
- [`configs/vision/wepoker_android/calibration.json`](configs/vision/wepoker_android/calibration.json)
- [`docs/vision-engine.md`](docs/vision-engine.md)

没有独立标定的数据项会显示为不可用，不会猜测结果。

## 目标架构

![PokerSense v0.3 目标架构](docs/realtime-training-assistant.drawio.svg)

这个 SVG 内嵌了 draw.io 源数据，可以直接用 draw.io 打开。第一份结果来自确定性的本地 Fast Path；
缓存未命中或 EV 很接近时可异步启动本地 resolver，但过期结果会被丢弃。关键状态不确定时输出
`ABSTAIN`，绝不猜测。

```text
授权牌桌 → Capture → Vision → Temporal Consensus → Confidence Gate
  → State/Event Engine v2 → DecisionContext
  → Range + Equity + Strategy Router → Decision Fusion → Advice → Live Coach UI
  → 真人动作 → Hand Memory → 复盘 / 训练题 → 改善后续牌局先验
```

完整的数据契约、延迟预算、算法说明和里程碑退出标准见 [`architecture.md`](architecture.md)。

## 项目结构

| 模块 | 位置 |
|---|---|
| 领域类型与状态转换 | `src/poker_engine/core/`、`src/poker_engine/state_engine/` |
| 截图与视觉识别 | `src/poker_engine/perceptual/` |
| 胜率与实时链路 | `src/poker_engine/equity/`、`src/poker_engine/realtime/` |
| 桌面应用 | `src/poker_engine/desktop/`、`ui/` |
| 测试 | `tests/` |
| 平台标定 | `configs/` |

更详细的子系统说明见 [`docs/`](docs/)。

## 后续计划

1. **M1 — 可信的 Android 完整状态：** 标定公共牌、底池、筹码、座位、庄位、行动方和动作；加入多帧共识、下注
   合法性、hand boundary 和筹码守恒。
2. **M2 — 可解释的基础建议：** 落地 `DecisionContext`、组合范围贝叶斯更新、preflop DB、range
   equity、action EV，并把真实 Fast Path 首次建议 p95 控制在 300ms 内。
3. **M3 — 预解库与训练闭环：** canonical solution bundle、EV loss 复盘、漏点分类和训练题；实时与
   局后分析共用同一套接口。
4. **M4 — 鲁棒对手调整：** 小样本向总体先验收缩，用 KL 正则约束剥削偏移，并限制最坏损失。
5. **M5 — 异步局部精算：** 先做 river subgame，设置计算预算并丢弃过期结果。

详细交付物与退出标准见 [`architecture.md` 第 9 节](architecture.md#9-最优实施路线)。
# AA 冻结结果离线查看

新增独立的只读回放界面：在仓库根目录运行 `python -m tools.aa_replay_viewer --observations <冻结日志路径>`，
然后打开 `http://127.0.0.1:8766`。仅接受已固定SHA的0–1800回放，不启动采集或策略。
未实现字段、未知值和日志未记录的置信度均明确显示；[打开方法与边界](docs/AA-REPLAY-VIEWER-V1.zh-CN.md)。
