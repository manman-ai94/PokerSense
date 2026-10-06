# 前期调研：dickreuter/Poker 与 PokerSense 的关系

调研日期：2026-08-21
目标项目：[dickreuter/Poker](https://github.com/dickreuter/Poker)

## 1. 项目是什么

`dickreuter/Poker` 是一个完整的自动扑克机器人，而不是单纯的胜率计算器或 HUD。项目 README 声称它可以支持 PartyPoker、PokerStars 和 GGPoker，通过屏幕图像识别读取牌桌，使用 Monte Carlo 计算牌力，并根据预设策略自动作出决定，甚至移动鼠标完成操作。

它的公开结构主要包括：

- `poker.scraper`：屏幕截图、桌面映射、牌桌元素识别和 GUI 标定。
- `poker.decisionmaker`：行动决策、Monte Carlo 胜率和策略参数。
- `poker.tests`：胜率计算和静态检查测试。
- `tessdata`：OCR 相关资源。
- `doc`、`notebooks`、`website`：文档、实验和网站资源。

上游仓库显示约 649 次提交，公开仓库许可证为 GPL-3.0。项目主页目前约有 2.4k stars 和 588 forks，但 GitHub 的受欢迎程度不能替代对当前代码质量和真实运行效果的验证。

来源：[GitHub 项目主页](https://github.com/dickreuter/Poker)

## 2. 它和 PokerSense 的关系

| 能力 | PokerSense 当前状态 | dickreuter/Poker | 对 PokerSense 的价值 |
|---|---|---|---|
| 屏幕捕获 | 有，macOS/Windows 后端 | 有，偏 Windows 桌面和固定布局 | 参考桌面标定流程 |
| 牌桌映射 | WePoker H5 已标定底牌区域 | 可通过 GUI 标定新牌桌 | 很有价值 |
| 牌面识别 | OpenCV 模板识别，底牌优先 | OpenCV 模板或神经网络 | 参考多平台适配方式 |
| OCR/数字识别 | 金额等字段尚未完整标定 | OCR 读取下注和桌面信息 | 参考 pot、bet、stack 输入设计 |
| 状态维护 | 有 hand_id、版本、事件和置信度 | 有实时桌面决策流程 | PokerSense 的状态设计更清晰、可测试 |
| 胜率 | Monte Carlo 随机对手范围 | Monte Carlo，支持一些范围输入 | 算法方向相近 |
| 策略建议 | 当前不提供 | 有基于阈值、曲线和历史行为的策略 | 可作为启发式策略参考 |
| 自动操作 | 明确不做 | 会移动鼠标并自动打牌 | 不建议引入；产品和合规边界不同 |
| 训练/分析 | 尚未形成完整分析器 | 有 strategy analyzer 和策略编辑器 | 可参考赛后分析设计 |

## 3. 最有帮助的部分

### 3.1 可视化牌桌标定工具

该项目允许用户截取牌桌，然后通过 GUI 标出：

- 牌桌边界
- 按钮区域
- 底牌区域
- 公共牌区域
- 行动按钮
- 金额和筹码区域
- 需要识别的模板

它还支持为每种牌桌皮肤准备模板，并根据固定的左上角参考点裁剪区域。

这对 PokerSense 很有帮助。PokerSense 当前使用测量后的配置文件，但未来可以考虑增加一个“标定工作流”：

```text
选择目标窗口
→ 截取一张参考画面
→ 用户标记牌桌边界和字段 ROI
→ 生成平台布局配置
→ 为每个字段绑定识别器和置信度校准
→ 用留出截图验证
```

不过 PokerSense 不应直接复制“固定像素坐标 + 依赖桌面不缩放”的限制，而应继续保留窗口尺寸、DPI、比例和置信度校验。

### 3.2 把策略做成可编辑参数

该项目的策略编辑器会同时考虑：

- 当前胜率
- 最低跟注/下注价值
- 前几轮行动
- 不同街道
- 策略参数曲线
- 历史结果

这提供了一个重要的产品思路：最终输出不一定一开始就需要完整 GTO Solver，可以先做透明的可解释策略层：

```text
输入：Hero equity、pot odds、位置、街道、行动历史
→ 规则/阈值计算
→ 输出：Fold / Call / Raise 及其理由
```

这种策略必须明确标记为 heuristic 或 exploitative estimate，不能包装成 GTO。

### 3.3 策略分析和结果回溯

README 提到它可以按翻牌前、翻牌、转牌、河牌分析策略表现，并查看具体牌局。这提示 PokerSense 后续可以增加：

- 每手牌的输入状态快照
- 当时显示的胜率和建议
- 实际选择的行动
- 最终结果
- 策略建议和实际行动的偏差
- 按街道统计 EV 或结果

但这需要在隐私和数据保留策略中单独定义。PokerSense 当前的设计是屏幕帧只在内存中处理，不保存截图；未来若保存牌局分析，应只保存结构化状态，并由用户明确开启。

## 4. 不建议直接复用的部分

### 4.1 自动移动鼠标和自动下注

该项目的目标是自动打牌，README 也明确描述了鼠标控制和长时间运行。PokerSense 当前的产品边界是“只观察和展示，不控制扑克客户端”。这两种产品的安全、合规、测试和责任边界完全不同。

因此本项目不应引入：

- 鼠标自动移动
- 自动点击下注按钮
- 自动提交行动
- 读取客户端内部内存
- 网络或协议注入

### 4.2 直接依赖其当前 Monte Carlo 实现

上游 README 明确说明 `montecarlo_numpy2.py` “not yet working correctly”，并且存在失败测试；Python 版本较慢但支持翻牌前范围。这个实现可以作为算法阅读材料，但不应直接替代 PokerSense 当前已经有测试和精确参考实现的 equity 层。

PokerSense 应继续采用：

```text
共享牌力 evaluator
→ 精确枚举作为参考实现
→ 固定种子的 Monte Carlo 作为实时实现
→ 收敛测试和回归测试
```

### 4.3 直接复制固定桌面假设

该项目的 README 要求牌桌大小、颜色、牌背、布局、DPI 和窗口可见性满足固定条件，并且部分功能只适用于六人桌。这种方法适合快速支持一个具体客户端，但会带来：

- 窗口缩放即失效
- DPI 变化即失效
- 牌桌皮肤变化即失效
- 不同浏览器和系统难以复用
- 识别错误难以被安全地阻断

PokerSense 应吸收它的“配置化标定”思想，但保留自身的置信度门控、未知值和可恢复错误设计。

## 5. 对最终架构的启发

这个项目强化了 PokerSense 之前的目标架构：

```text
Capture
  ↓
Vision / OCR / Table Mapping
  ↓
Raw Observation + Confidence
  ↓
Canonical Poker State
  ↓
Range Model
  ↓
Equity / Pot Odds / EV
  ↓
Heuristic or GTO Strategy
  ↓
Explainable Output
```

其中，`dickreuter/Poker` 最值得借鉴的是输入端和策略参数化；PokerSense 当前的 `core`、`state_engine`、`confidence` 和 `memory` 仍应作为规范化中间层，而不是让识别器直接驱动动作决策。

## 6. 对输入端的补充要求

如果 PokerSense 要从“底牌胜率显示”发展到“带理由的策略建议”，还需要可靠获取：

### 必需状态

- Hero cards
- Board cards
- Street
- Pot size
- Amount to call
- Current bet
- Effective stack
- Player count
- Hero position
- Dealer/button position

### 必需行动历史

- 谁先行动
- 谁 open、call、3-bet、4-bet
- 每次下注金额
- 当前轮是否已经发生下注
- Hero 是否面对下注

### 策略上下文

- 对手范围
- 盲注和 ante
- 现金桌或锦标赛
- 可用下注尺寸
- 抽水规则
- heads-up 或 multi-way

任何无法可靠识别的字段都必须保持 `UNKNOWN`，而不是用默认值继续生成确定性建议。

## 7. 对输出端的启发

最终输出可以分为四层：

```text
当前状态
→ Hero cards、board、street、position、pot、to call

数学结果
→ equity、pot odds、required equity、SPR、EV

策略结果
→ Fold / Check / Call / Bet / Raise 的推荐频率

解释和可信度
→ 使用的范围、策略来源、识别置信度、未知字段和限制
```

建议的最终显示形式：

```text
Hero: A♠ K♦
Board: A♥ 7♣ 2♠
Position: Button
Pot: 100 BB | To Call: 35 BB | SPR: 4.0

Equity: 58%
Opponent range: BB defend
Required equity: 26%

Recommendation:
Bet 33%      55%
Check        35%
Bet 75%      10%

EV:
Call         +0.42 BB
Raise        +0.31 BB
Fold          0.00 BB

Confidence: High
Strategy source: precomputed range lookup
```

在没有完整公共牌、底池、行动历史和位置之前，界面只能显示胜率和识别状态，不应显示正式的跟注/加注建议。

## 8. 许可证和使用边界

该仓库主页标记为 GPL-3.0。任何代码复制、链接、修改、分发或商业集成前，都需要单独审查许可证义务；本调研不把“可以参考算法”解释成“可以直接复制代码”。

此外，项目 README 本身讨论了账号冻结和使用虚拟机规避客户端干扰等风险。PokerSense 的后续设计应继续坚持被动读取和展示，并在实际目标平台上单独确认服务条款是否允许屏幕捕获、HUD 或实时辅助。

## 9. 结论

`dickreuter/Poker` 对 PokerSense 有帮助，但帮助主要集中在：

1. 可配置的牌桌标定和多桌面元素识别。
2. 将 pot、bet、stack、位置和行动历史纳入决策输入。
3. 将策略做成可编辑、可分析、可回溯的参数化层。
4. 用结构化牌局历史评估策略表现。

它不适合作为 PokerSense 的直接底层依赖，原因是：

1. 产品目标包含自动操作，而 PokerSense 明确保持被动观察边界。
2. 部分 Monte Carlo 实现和测试在 README 中仍被标记为不正确或过时。
3. 它依赖较强的固定桌面布局和 Windows 使用假设。
4. GPL-3.0 会影响直接集成和分发方式。

推荐的下一步不是直接移植该项目，而是先在 PokerSense 中完成一个独立的“输入契约 + 策略输出契约”，然后按阶段实现：

```text
可靠识别公共牌/底池/行动
→ Pot Odds 和 EV
→ 位置化对手范围
→ 预计算策略查表
→ 再评估是否需要接入独立 Solver
```
