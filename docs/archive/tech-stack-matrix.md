# 技术选型矩阵 (Tech Stack Matrix)

> 选型铁律：**凡有成熟开源工具覆盖的通用能力，优先接入而非自研；自研精力只投向「正确性约束 + 扑克领域逻辑 + 可回放/可观测」。**
> 本文是选型的唯一对照表。新 Task 开工前先查这张表，决定「接/候选/后期/不接（红线）」。

## 一、结论速览（按「是否影响当前架构」排序）

| 组件 | 用途 | 许可证 | 状态 | 决策 |
|---|---|---|---|---|
| **OpenCV** | 视觉处理（Vision Engine 基础） | Apache 2.0 | ✅ 已用 | 继续用 |
| **NumPy** | 数值计算 | BSD | ✅ 已用 | 继续用 |
| **pytest / flake8** | 工程 | MIT | ✅ 已用 | 继续用 |
| **PaddleOCR** | 金额/文字 OCR | Apache 2.0（可商用） | ⚠️ 候选，已定首选 | **做 Task 8 金额识别时接入** |
| **PokerKit**（uoftcprg/pokerkit） | 扑克规则库 + hand evaluator | MIT | 🔵 候选 | 评估是否接管规则正确性 |
| **Treys**（ihendley/treys） | 牌力评估（查表法） | MIT | 🔵 候选 | 对比自研 evaluator，看性能/覆盖 |
| **TexasSolver**（bupticybee） | GTO 求解 | **AGPL v3 + 商业授权** | 🔴 后期/谨慎 | **不可随意集成**（见下方红线说明） |
| **dickreuter/Poker** | 全链路 bot 参考 | **GPL-3.0** | 📖 参考 | 只研究架构思路，禁止抄代码（copyleft），且它做真金自动下注/ToS 违规，与我们「分析助手不自动操作」的定位相反 |
| **neuron_poker / OpenSpiel / rlcard / PokerRL** | 博弈/RL 训练环境 | 需核实 | 🔴 定位红线外 | **训练自动打牌 agent，不接** |
| Tesseract | OCR 备用 | Apache 2.0 | ⚪ 未用 | 已被 PaddleOCR 取代，不选 |
| mss | 截屏后端 | MIT | ⚠️ 声明未真跑 | 主用 FakeBackend |
| YOLO / PyTorch | 视觉检测/模型训练 | — | 🔵 后期 | 若替换模板识别再评估 |
| FastAPI / Docker | 服务化/部署 | MIT / Apache | 🔵 后期 | 出口层 |

## 二、关键许可证红线（务必先看）

1. **TexasSolver = AGPL v3**。AGPL 是「传染性」协议：如果你的软件集成它的代码、或通过网络提供服务，**你有义务开源你的整个项目源码**。作者明确说明：把求解器**二进制**集成到你的软件允许，但把**代码**集成进自己的软件或提供网络服务，**需联系作者购买商业授权**。
   - **决策**：TexasSolver 不能当作「随时可接的开源依赖」。它只能「后期单独授权」或「作为独立进程二进制调用（不碰其源码）」，做 Task 10 GTO 前需重新评估。且按我们「GTO 后置」战略，可用「蒙特卡洛 equity + 参数策略」先跑通，TexasSolver 非前置。
2. **neuron_poker / OpenSpiel / rlcard / PokerRL**：这些是**训练自动打牌 agent**的 RL 博弈环境。接它们 = 把项目往「自动打牌 bot」方向带，与我们「分析/教学/可解释决策建议、不做自动下注」的定位红线冲突。
   - **决策**：仅作研究参考，**不接入**。若未来要「可解释的策略建议」，走我们自研的 equity + 规则策略，不走 RL 自博弈。

## 三、分类明细

### 🟢 已用（继续）
- OpenCV：模板匹配 + 图像预处理，Vision Engine 底座。
- NumPy：图像数组 + 数值。
- pytest / flake8：测试与规范。

### ⚠️ 已定首选、待接入（近期 Task 触发）
- **PaddleOCR**：金额/文字 OCR。选它而非 tesseract 的理由：Apache 2.0 可商用、轻量模型（最小 1.5M）、99% 场景对数字/金额识别精度高、支持 ONNX 导出（避免强依赖 PaddlePaddle 运行时）。tesseract 中文/数字精度弱、需切语言包，不适合牌桌金额。**Task 8 做金额识别时接入。**

### 🔵 候选（评估后决定「接 or 继续自研」）
- **PokerKit**：MIT、纯 Python、99% 覆盖、支持大量扑克变体 + 灵活状态控制。用途候选：**接管「扑克规则正确性」**（下注合法性、底池分配、手牌比较）。
- **Treys**：MIT、查表法、5/6/7 张评估、250k eval/s。用途候选：**牌力评估**（对比我们 Task 9 自研 evaluator）。
  - **评估判据**：我们自研 evaluator 已通过「枚举法 vs 蒙特卡洛」自证。换 PokerKit/Treys 的唯一合理动机是「性能极大规模」或「覆盖多变体」，否则继续自研（它们不带来「正确性约束」这层我们独有的价值）。

### 📖 参考（不依赖）
- **dickreuter/Poker**：GPL-3.0，2.4k star，活跃维护（近期仍有更新），在 PartyPoker/PokerStars/GGPoker 上做视觉识别 + 蒙特卡洛 equity + 遗传算法策略 + **自动下注**。
  - 可以借鉴的：OpenCV 模板/GUI 标定截屏区域的思路、蒙特卡洛 equity 的工程实现方式。
  - **不能做的**：①直接抄它的代码——GPL-3.0 是强 copyleft，抄了代码等于整个项目也要开源；②照搬它「自动下注」这条路径——这正是我们架构里明确排除的红线（我们是分析助手，不做自动操作），而且在真实平台上做自动操作大概率违反平台 ToS，有账号/法律风险。

### 🔴 后期/红线外（先不动）
- **TexasSolver**：GTO 求解，后期 + 授权门槛（见红线）。
- **neuron_poker / OpenSpiel / rlcard / PokerRL**：RL 训练环境，定位红线外。
- **YOLO / PyTorch**：若将来「自研专用识别模型替换模板匹配」再评估。
- **FastAPI / Docker**：出口层，最后才接。

## 四、给未来开发的「开工前查表」动作

新 Task 涉及通用能力时，先问自己三句：
1. 表里有没有成熟开源候选？→ 有，就用（PaddleOCR / PokerKit / Treys 按候选接入）。
2. 它有没有许可证/定位红线？→ TexasSolver(AGPL)、RL环境(bot 倾向) 先跳过。
3. 它是不是「正确性约束」这一层？→ 是，就自研（这是护城河，开源给不了）。

## 附：调研要点来源（2026-08-19 实时核实）

- PokerKit 正确仓库 = `uoftcprg/pokerkit`（多伦多大学，MIT，纯 Python，99% 覆盖，多扑克变体 + 灵活状态控制 + 1M eval/s）。
- Treys 正确仓库 = `ihendley/treys`（MIT，Deuces 的 Python3 移植，查表法，5/6/7 张，250k eval/s）。
- TexasSolver = `bupticybee/TexasSolver`（C++ QT，AGPL v3，作者要求集成需商业授权；有 GPU 版更快）。
- neuron_poker = `dickreuter/neuron_poker`（OpenAI Gym + keras-rl DQN 自博弈，训练自动打牌 agent）。
- OpenSpiel = `google-deepmind/open_spiel`（C++ 核心 + Python 绑定，博弈/RL 研究框架，含 CFR/MCCFR）。
- PaddleOCR = `PaddlePaddle/PaddleOCR`（Apache 2.0，PP-OCRv6 轻量 1.5M~34.5M，ONNX/OpenVINO 导出）。

---

# 附：AGPL/RL 组件的「使用边界」与 Solver Adapter 隔离护栏（2026-08-20 用户定调）

> 用户定调（重要，长期遵守）：软件**第一阶段纯自用、不对外分发**；将来对外时再获取相应授权。训练目的是「让整体决策模型/算法更强、提高胜率」，**主语是人**——系统是「军师」，不是「代替人自动下注的枪手」。这一定位与「分析/教学/可解释决策建议」一致，不冲突。

## 一、TexasSolver（AGPL v3）—— 可用，但必须走「隔离适配器」

**结论**：纯自用阶段，AGPL 的传染条款不触发（它约束的是「分发/对外提供服务」这个动作）；可以拉代码、本地跑、研究、甚至自用集成。但**工程上必须隔离**，防止未来对外时污染核心。

**护栏（务必遵守）**：
1. **绝不把 TexasSolver 的源码编译进 `poker_engine.core` 或任何核心包**。它只能通过架构里预留的 **Solver Adapter** 层作为「外部进程 / 独立二进制」调用。
2. Solver Adapter 的职责：进程边界 + 序列化输入输出（把自己的状态转成求解器格式、把求解结果转回来）。核心包只依赖「Extome 接口」，从不 import TexasSolver。
3. 将来要对外分发/提供服务时，二选一：① 单独买商业授权；② 继续走「独立进程调用」，不把 AGPL 代码编进去。→ 到那时这一层单独决策，不污染其余。

## 二、neuron_poker / OpenSpiel / rlcard / PokerRL —— 借鉴算法思想，不接 RL 训练去造 bot

**结论**：这些是「自博弈训练 agent」的 RL 环境。我们要的是「提高胜率的决策建议」，不是「自动打牌 agent」。

**用法（吸收而非接入）**：
1. **借鉴算法思想**：CFR（反事实后悔最小化）、MCCFR（蒙特卡洛 CFR）、深度 CFR——这些是「让策略更接近 GTO」的正路，可以**学思路、必要时自研实现**（我们自研的 CFR 是我们自己的代码，不受它们的 RL 框架/许可证约束）。
2. **不接它们的 RL 训练框架**去自博弈出一个「自动下注 agent」——那会越过定位红线。
3. 落地到我们架构 = Strategy 层用「蒙特卡洛 equity + CFR/参数策略」，产出「给人看的决策建议 + 胜率/赔率/范围」，不产出「自动执行的动作」。

## 三、一句话边界（记死）

> **「借鉴算法、隔离引用」—— 开源算法思想可以吸收（CFR/MCCFR/evaluator），但 AGPL 组件走独立进程隔离、RL 训练框架不接入。系统永远是「军师」不是「枪手」。**

