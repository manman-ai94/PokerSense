# 调研：德州扑克怎么才打得好，打得好的人和 AI 怎么打（2026-10-07）

目的：弄清楚“打得好”靠什么，落实到 PokerSense 的 AI 和翻牌前范围表（里程碑 4）上。
有出处的写出处；没有核实的标“未核实”。

## 结论

1. **打得好 = 先打得“难被占便宜”，再针对对手的毛病多赢。** 顶级玩家和顶级 AI 都是这个顺序：
   先用接近博弈论最优（GTO）的打法打底，保证谁都很难针对你；再根据对手群体的固定毛病偏离，去多赢钱。
2. **我们现在的路线和顶级 AI 的结构一致**：Libratus、Pluribus 都是“提前算好的粗略打法（蓝图）+ 牌局中实时细算”。
   对应到我们：翻牌前范围表 = 蓝图；翻牌后求解器 = 实时细算；记分牌 = 衡量强弱。里程碑 4 正好补上蓝图。
3. **AA 的规则让打法明显不同于普通牌桌**：
   - 每人前注 2 = 1 个大盲，桌上死钱很多，翻牌前整体应该打得更宽；
   - 强制跨注让跨注位置像“大大盲”，其余位置反而要收紧，按钮位收紧得最多；
   - 暴击局所有人随机牌入池，要按牌面打；
   - 保险按牌桌的赔率买，期望值明显为负，原则上不买。
4. **普通玩家群体的常见毛病**：翻牌前跟注太多，翻牌后面对加注弃牌太多，河牌诈唬太少。
   对策：价值下注更薄更多；面对河牌大注、过牌加注时少抓诈唬。
5. **里程碑 4 的数据来源**：能直接算“8 人、前注、强制跨注”翻牌前范围的只有商业工具（GTO Wizard Ultra，每月 279 美元起），
   没有合适的开源工具。建议先不花钱：从公开的近似范围出发，按 AA 规则调整，用记分牌筛选；
   要不要买商业工具做对照，由你决定。

## 一、打得好的基本功

- **按范围想，不按单手牌想**：判断对手时想的是“他这样打，手里可能是哪些牌的组合”，自己的打法也要让每种动作背后都有好牌和差牌。
- **位置**：后行动的人信息更多，同样的牌在后位能玩得更宽。
- **底池赔率和最少防守比例**：对手下注 b、底池 p，跟注至少要有 b/(p+2b) 的胜率才不亏；
  为了不让对手拿任何牌诈唬都赚，自己至少要继续 1 − b/(p+b) 的范围（半池下注时约 67%）。[MDF 说明][mdf]
- **下注尺度**：小注施压对手的整个范围，用“强牌 + 中等牌 + 听牌”混合下注；
  大注两极化，只用“很强的牌 + 诈唬”下注。[MDF 说明][mdf]
- **筹码与底池比（SPR）**：后手越浅，越容易“打光”，中等牌的价值越高；后手越深，越看重位置和潜力。
- **混合策略**：同一手牌有时下注、有时过牌，让对手猜不透。职业玩家说 Pluribus 最大的优势就是能做到“完全随机地混合”，
  人很难做到。[CMU 新闻][cmu]

## 二、顶级扑克 AI 怎么做到的

| AI | 年份 | 场景 | 做法 | 成绩 |
|---|---|---|---|---|
| Libratus | 2017 | 单挑无限注 | 提前算好的蓝图（简化后的完整游戏）+ 牌局中逐步细算的子博弈求解 + 根据对手常用的下注尺度自我补强 | 12 万手赢 4 位顶级职业，每手约 0.147 个大盲 [IJCAI][libratus] |
| DeepStack | 2017 | 单挑无限注 | 每一步重新求解，用神经网络估计“往后的价值” | 战胜职业玩家 [说明][libratus-news] |
| Pluribus | 2019 | 6 人无限注 | 自我对弈得到蓝图（翻牌后很粗）+ 往前看几步的实时搜索；看不到的部分，假设每个对手只在 4 种风格里选 | 1 万手赢 5 位职业同桌；训练只用 12,400 核时，实战 28 个核 [CMU 新闻][cmu]、[综述][pluribus] |

**对我们的启示**：

- 结构照搬：蓝图（翻牌前表）+ 实时细算（翻牌后求解）。多人底池目前没有开源求解器，Pluribus 的“有限深度搜索”说明多人也能做，但工作量大，按路线图放在里程碑 6。
- Pluribus 比人更常“领先下注”（上一街跟注的人这一街先下注），也更常用很大的下注尺度。我们的求解树目前只有少数几个尺度，以后可以扩展。
- 这些 AI 都不是“背一张表”，而是边打边算。我们翻牌后已经是边打边算，翻牌前用表就够了，因为翻牌前的局面数量有限。

## 三、针对普通玩家群体

- 小级别常见的群体倾向：翻牌前跟注太多，翻牌后面对加注弃牌太多；对后位的再加注弃牌常超过 70%。[DeucesCracked][dc-pop]
- 河牌普遍诈唬不足，尤其是河牌超池下注、过牌加注、领先下注，这些情况下拿边缘牌抓诈唬长期是亏的。
  反过来，普通玩家转牌过牌、河牌突然大注时，诈唬比例反而偏高。[DeucesCracked][dc-pop]
- 做法：先找出 GTO 的打法，再看这个群体实际诈唬多还是少：诈唬少就多弃牌，诈唬多就多跟注。[DeucesCracked][dc-pop]
- 我们已有的基础：记分牌里的“真人人群”机器人就是按公开牌谱统计出来的群体打法。
  以后积累到足够多 AA 牌局，可以换成 AA 真实对手的统计，用来做剥削层。

## 四、AA 规则对打法的影响

规则细节见 [AA 牌桌规则整理](aa-table-rules.zh-CN.md)。

- **前注很大**：每人前注 2 = 1 个大盲，8 人桌开局底池 23，是普通 1/2 牌桌（3）的近 8 倍。
  死钱越多，开池和防守都越宽。[前注与跨注][antes]
- **强制跨注**：跨注相当于在按钮后面多了一个“盲注位”，翻牌前最后行动的变成跨注位。
  一项求解对比显示，加了跨注后，非跨注位置都要收紧，按钮位收紧最多（约 9.6 个百分点）。[前注与跨注][antes]
  AA 两者都有，方向相反，最终谁占上风要用求解或记分牌算，不能凭感觉。
- **暴击局**：所有人随机牌直接看翻牌，大家的范围都很宽、也不“封顶”，胜负主要看牌面配合程度。[暴击策略][bomb]
- **保险**：牌桌赔率明显低于公平赔率，按两种可能的计算方式，抽成在约 18% 到 50% 以上，期望值为负。
  除非特别想减小波动，否则不买；以后观察页可以直接算出“这次保险亏多少”。
- **抽水**：录像初步反推约 5%，大底池有封顶（约 13），待俱乐部确认。抽水越重，小底池里的边缘跟注越不划算。

## 五、落到我们的 AI 上

1. **里程碑 4：翻牌前范围表**。数据来源三选一：
   - A. **买商业工具**：GTO Wizard Ultra 支持最多 9 人、前注、跨注的多人翻牌前求解，
     现在每月 279 美元（按年 229），10 月 15 日后每月 359 美元（按年 289）。[价格][gtow-price]、[功能][gtow-mw]
     要逐个局面手工查询再整理成表，花钱需要你同意；
   - B. **开源工具**：没有合适的。现有开源工具只做翻牌后、单挑，或短筹码“全下或弃牌”。[开源工具][oss]、另见 [多人翻牌前资产调研](research-multiplayer-preflop-assets.md)；
   - C. **不花钱的做法（推荐先做）**：从公开的近似范围（已接入的 6/9 人开池表）出发，按 AA 结构（前注放宽、跨注收紧）
     做成每个位置的开池、跟注、再加注范围，用记分牌对“真人人群”和风格机器人两种对手池筛选，只保留能涨分的版本。
2. **翻牌前和翻牌后保持一致**：翻牌后的范围由“实际用的翻牌前打法”重放推出，换了翻牌前表，翻牌后自动跟着用。
3. **剥削层**：先用“真人人群”的统计，以后换成 AA 真实对手的统计；每一项调整都要在记分牌上涨分才保留。
4. **保险计算**：全下后显示“这次保险的期望亏损”，帮你建立“保险基本不该买”的直觉。

## 未核实

- 前注与跨注对范围的具体百分比，来自单一来源的求解对比，AA 前注 = 1BB、跨注 = 2BB 的组合没有直接数据。
- 群体倾向的数字来自英文网络牌局的总结，是否适用于 AA 的玩家要用以后的 AA 牌局验证。
- 保险“赔率”的确切含义（买中时是否退回保费）待用实际牌局核对。

## 来源

- [mdf]: https://www.pokerskill.com/poker-glossary/topics/ranges-gto-and-strategy/ （MDF、两极化与混合范围）
- [cmu]: https://www.cmu.edu/news/stories/archives/2019/july/cmu-facebook-ai-beats-poker-pros.html （Pluribus：对局手数、训练与实战算力、打法特点）
- [pluribus]: https://www.scientificamerican.com/article/ai-conquers-six-player-poker （Pluribus 有限深度搜索、4 种风格简化）
- [libratus]: https://www.ijcai.org/Proceedings/2017/772 （Libratus 三个模块）
- [libratus-news]: https://www.sciencedaily.com/releases/2017/12/171218091001.htm （Libratus 成绩、与 DeepStack 的关系）
- [dc-pop]: https://www.deucescracked.com/blog/gto-vs-exploitative-small-stakes-online-poker-2026 （小级别群体倾向与剥削）
- [antes]: https://internals.quintace.ai/articles/antes-vs-straddles/ （前注与跨注对翻牌前范围的影响）
- [bomb]: https://www.deucescracked.com/blog/bomb-pot-poker-strategy-live-cash-games （暴击局策略）
- [gtow-price]: https://www.pokernews.com/news/2026/03/gto-wizard-subscription-plans-new-features-pricing-50908.htm （GTO Wizard 价格）
- [gtow-mw]: https://www.vegasslotsonline.com/news/2026/02/06/what-are-the-consequences-of-gto-wizards-new-multi-way-pre-flop-solver/ （多人翻牌前求解：最多 9 人、前注、跨注）
- [oss]: https://github.com/topics/dcfr （开源求解器现状之一）

[mdf]: https://www.pokerskill.com/poker-glossary/topics/ranges-gto-and-strategy/
[cmu]: https://www.cmu.edu/news/stories/archives/2019/july/cmu-facebook-ai-beats-poker-pros.html
[pluribus]: https://www.scientificamerican.com/article/ai-conquers-six-player-poker
[libratus]: https://www.ijcai.org/Proceedings/2017/772
[libratus-news]: https://www.sciencedaily.com/releases/2017/12/171218091001.htm
[dc-pop]: https://www.deucescracked.com/blog/gto-vs-exploitative-small-stakes-online-poker-2026
[antes]: https://internals.quintace.ai/articles/antes-vs-straddles/
[bomb]: https://www.deucescracked.com/blog/bomb-pot-poker-strategy-live-cash-games
[gtow-price]: https://www.pokernews.com/news/2026/03/gto-wizard-subscription-plans-new-features-pricing-50908.htm
[gtow-mw]: https://www.vegasslotsonline.com/news/2026/02/06/what-are-the-consequences-of-gto-wizards-new-multi-way-pre-flop-solver/
[oss]: https://github.com/topics/dcfr
