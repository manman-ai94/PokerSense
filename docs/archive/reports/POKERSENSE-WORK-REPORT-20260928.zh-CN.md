# PokerSense 工作总汇报与 ChatGPT 审核入口

**快照日期：2026-09-28。** 这是已有工作的去重汇报，不是一次新训练、策略晋升或发布。
范围包括正式仓库的历史演进、本轮 PR #37–#42、旁支失败研究，以及仍未同步的本地历史工作。
同一能力按最终状态归并一次；中间版本、重跑和勘误只作为追溯证据，不重复计成果。

**当前判断：离线观察、手工复盘、规则配置和可复现策略实验的工程基础已具备；
6–8人完整四街强策略、真实十秒窗口验收和盈利能力仍未成立。**
ChatGPT 的独立审核尚未执行；本文件提供审核入口，不要求审核者接受这里的结论。

## 1. 当前项目到底处于什么状态

| 项目 | 已核对事实 | 不能据此推导的结论 |
|---|---|---|
| 正式仓库 | [xiaoyangpeng1994-create/PokerSense](https://github.com/xiaoyangpeng1994-create/PokerSense)，PUBLIC，默认分支main | 公开仓库不等于已发布产品 |
| 当前main | `af67b4bb3ba56da2d4fdb70e0731583afc7aaf40`，最近合并的是[#34][pr34] | main尚不包含后续六项Draft交付 |
| 最新集成快照 | `f05d804ba701e8041552327867e4ac9e2d6420fd`，位于[#42][pr42]的依赖链；版本`0.2.0.dev1` | 上传分支、通过CI不等于合并、上线或策略可用 |
| PR盘点 | 本汇报PR创建前共37个PR：26已合并、7开放Draft、4关闭未合并；编号间隙属于Issue等，不是漏记 | 不把关闭研究算作生产功能 |
| 发布 | 正式Releases为0；有工程构建工件 | 不称正式Release或已完成用户设备验收 |
| 可以使用 | AA离线入口、本桌设置、已保存资料复查、明确条件下的手工河牌分析；仿真、训练、冻结、评估和审计CLI | 条件分析依赖人工范围／响应假设，不是现场自动建议 |
| 当前实战路径 | 缺少合格策略、完整可信现场状态与计时来源，生产动作建议仍关闭 | 不能声称现在能边打牌边稳定提高胜率 |

GitHub状态来自本次实时API核查。历史实验数值依据固定提交的文档和已有产物，**本次没有重跑实验或读取录像**。
机器可读的[证据索引](POKERSENSE-WORK-REPORT-20260928.evidence.json)记录37个PR的唯一归属、完整SHA、最新检查及脱敏聚合结果。

## 2. 去重后的成果账

表中“已实现”描述代码能力；右栏限定它实际证明了什么。测试次数、开发帧数和研究样本不累加成一个“项目准确率”。

| 编号／工作域 | 归并后的实际交付 | 当前边界与来源 |
|---|---|---|
| W0 早期基础与AA影子桥接 | 保留牌力、状态、合法动作、主／边池、范围、权益、路由与拒答基础；AA任务1–6增加8座输入桥、影子日志、规则指纹、资产绑定、范围跟踪与权益隔离。WPK／ADB历史用于回归，当前主线为AA实体手机＋采集卡 | 没有合格AA范围与完整现场输入就不能转成实时策略；Task7本地未提交增量另列W14。[桥接](../AA8-STRATEGY-BRIDGE-TASK1.zh-CN.md)、[规则门禁](../AA8-RULES-AND-PROVIDER-GATE-TASK4.zh-CN.md)、[范围资产](../AA8-RANGE-ASSET-TRACKER-TASK6.zh-CN.md) |
| W1 仓库、CI与同步 | 建立正式仓库、中文PR工作流、分支保护、Windows/macOS检查；修复Git凭据助手／退出码／SHA核对和节拍测试。仓库审查保留为历史意见 | [#1][pr1]、[#13][pr13]、[#26][pr26]已合并；[#30][pr30]关闭未合并。历史PR正文可能保留旧状态，当前合并状态以API快照为准 |
| W2 授权采集与设备入口 | 一次性授权的被动采集入库、UGREEN视频接口选择、设备锁清理、dry-run及开发媒体审查 | [#7][pr7]–[#12][pr12]。有历史开发采集不等于端到端延迟和长时可靠性验收；本次不启动采集 |
| W3 AA识别、状态候选与观察工具 | 关闭模拟器产品入口；AA8会话登记、字形去重／盖牌与弃牌区分、浅色ALL-IN、金额与动作候选、完整机会合同、actor episode、开发回放、观察页、开局／账本／动作和终结语义 | [#2][pr2]–[#6][pr6]、[#14][pr14]–[#18][pr18]、[#20][pr20]。其中[#17][pr17]是关闭的留出资格审计。稀疏人工匹配、已曝光录像回归不当作完整视觉准确率；UNKNOWN与未解释现金差保留。[集成边界](../AA8-V2-INTEGRATED-STATUS.zh-CN.md) |
| W4 人工复查与事实治理 | 来源绑定字段标注、追加修订、不可逆曝光历史；TARGET-S人工事实确认与回执；五个关键感知字段的来源／时序校验；候选、标注、事实、gold和训练资格分离 | [#19][pr19]关闭，部分能力经[#31][pr31]选择性迁移；[#32][pr32]、[#33][pr33]已合并。不是两套重复成果；TARGET-S不等于完整PHH或策略准入。[标注](../AA-FIELD-ANNOTATIONS-V1.zh-CN.md)、[确认](../AA-REAL-HAND-CONFIRMATION-V1.zh-CN.md)、[感知](../AA-CRITICAL-PERCEPTION-VERIFICATION.zh-CN.md) |
| W5 多人条件分析与复盘 | Hero唯一仍可行动时的多人河牌call/fold终结核算；恰好3ACTIVE时的有限河牌行动树；范围敏感性、固定策略压力筛选；手工输入、记录和独立分析进程。另有人工触发的视觉API候选复查入口 | [#24][pr24]、[#28][pr28]，沿用此前接通的AA工具。边池／退款／抽水可核算，不等于范围假设真实；三人行动树不支持任意all-in／边池跨越；手工分析最多约10秒，不进入实时关键路径。[终结研究](../AA-MULTIWAY-STRATEGY-RESEARCH-20260913.zh-CN.md)、[三人验证](../THREEWAY-MODEL-VALIDATION-V1.zh-CN.md)、[早期对手／不确定性研究](../OPPONENT-MODEL-V1.zh-CN.md)、[视觉复查](../AA-REVIEW-DESK-AND-VISION-API.zh-CN.md) |
| W6 开源与技术路线调研 | 比较PokerKit、OpenSpiel、多人研究与HU求解器；区分状态机、手牌历史、求解器和已训练策略的职责 | [#29][pr29]及[技术矩阵](../STRATEGY-EVALUATION-FOUNDATION-V1.zh-CN.md)。选PokerKit作环境／机械参考，保留MCCFR；没有把Pluribus论文或HU程序当作现成AA多人策略 |
| W7 冻结河牌基线与独立参考 | 固定公开历史策略书、30个已曝光合成条件世界、独立牌力与结算参考；同一公开条件跨世界固定同一策略；防止按隐藏世界重新选动作 | [#34][pr34]。独立参考核对终结机械，不证明人工范围、响应概率或所有行动树EV正确；数值结论在第3节集中列示 |
| W8 对手建模研究 | 固定范围后验候选、历史全行动机会审计、合成行动似然控制；保留失败与风格漂移结果 | [#35][pr35]拒绝并关闭未合并，分支／挑战／结果保留；[#36][pr36]独立Draft，未进入后续依赖链。真实可准入行动机会仍不足；详见第3节 |
| W9 十秒窗口与全手实验底座 | 单调时钟绝对截止、源画面年龄、身份／状态失效、浏览器TTL、固定决策采样、预加载可终止影子进程；PokerKit全四街6/7/8人仿真、MCCFR、事务checkpoint、同牌换座评估、九配置编排；修复salt合同与失败归因 | [#37][pr37]。Windows入口和打包改为AA；Jev只实现显式合成／录制响应适配，没有实调或强度背书。[实施清单](../AA-TEN-SECOND-IMPLEMENTATION.zh-CN.md)、[运行合同](../AA-TEN-SECOND-RUNTIME.zh-CN.md) |
| W10 V2状态表示与学习诊断 | 分离精确身份和有损学习特征；保留本人／公牌花色关系、逐街路径、精确金额；全局花色规范化；版本拒配、学习／不更新对照、续训数值修复、九份资产影子接口验证 | [#38][pr38]。没有抹去金额或用默认动作补洞；学习信号通过，未见牌局覆盖不通过。数字集中在第3节 |
| W11 本桌设置表单 | 观察页摘要＋编辑；人数、盲注、前注、straddle、百分比抽水、BB封顶、可选常见筹码区间；更多规则折叠；本机保存、取消回读、换桌清空、版本冲突及旧请求兼容 | [#39][pr39]。未知留空，0有明确含义；筹码范围只是元数据，不改规则指纹或逐手筹码。保存／清空停止观察并失效旧分析，不自动恢复采集或开放建议。[表单合同](../AA-TABLE-VALIDATION-V2.zh-CN.md) |
| W12 外部本地模型研究 | 固定两个Mapika候选的权重／许可／运行时，公开状态到合法菜单适配、加载／时延筛查；随后增加可严格判定的决策检查与完整牌局限时对战 | [#40][pr40]、[#41][pr41]合并计为一条候选验证链。两模型均NO_GO，未部署；独立GPU研究环境未进入桌面依赖。完整结果在第3节 |
| W13 有限翻前支持集审计 | 固定6/7/8人×每已占座位×169牌类×3前缀，真实loader与原checkpoint逐项核对；区分未访问、全零／非零regret无平均、命中和不成立决策；报告重核来源而不信自报HIT | [#42][pr42]。一次限时审计，无训练、补动作或策略修改；未发现可据此直接认定的MCCFR实现bug。数字在第3节 |
| W14 本地历史保留项 | 旧主目录仍保存Task7模拟范围基线／隔离改动及历史交接材料等未提交工作，本次git状态为8项已跟踪修改、143个未跟踪文件 | 不把文件数当功能数；未整体导入、推送、删除或重新验收。当前集成分支不含`aa_simulation_baseline_v1.py`，不能把旧本地Task7称作已进入本轮GitHub代码 |

上述37个PR在机器索引中各归属一个工作域。W0/W14是起始底座和本地保留项，不伪造新的PR数量。
旧文档继续保留作证据；本汇报没有删除历史失败、复制实现或新建第二套策略框架。

## 3. 策略与评估结论：每项实验只计一次

| 实验／核查 | 有效结论与完整分母 | 对项目的含义 |
|---|---|---|
| 早期条件策略与冻结BASELINE V1 | 人工范围／响应校准只在合成控制中恢复生成模型；早期30世界压力筛选18项不利。随后固定V1的30世界回归中12项输给至少一个简单对照，30/30自比较相等。旧世界反复用于回归，不能累加成独立样本 | 数学核算／回归基础可用，不能把条件EV、精确Fraction或小游戏正确性当强策略。[早期验证](../THREEWAY-MODEL-VALIDATION-V1.zh-CN.md)、[V1基线](../STRATEGY-EVALUATION-FOUNDATION-V1.zh-CN.md) |
| RANGE_POSTERIOR_V1 | 54/54固定合成世界：7改善、14退化、33相等；平均条件差−5.6824筹码，log loss 0.6167→0.7282，Brier 0.4245→0.4996 | REJECT；[#35][pr35]关闭未合并。[固定提交报告](https://github.com/xiaoyangpeng1994-create/PokerSense/blob/cd2502ad3f67c2060e45569df6d8e00603348508/docs/RANGE-POSTERIOR-V1.zh-CN.md)与公开逐项JSON可复核；不是全手BB/100 |
| 行动似然与真实数据资格 | 已复核动作、actor episode、帧各有统计，但真实合格训练／验证机会为0/0。384个合成机会按整session分192/96/96；玩家模型稳定集log loss 0.7510优于汇总0.9038，漂移集1.2959劣于汇总0.8200 | INSUFFICIENT_DATA；不能以稳定子集改善升级真实模型。[#36][pr36]、[固定数据审计](https://github.com/xiaoyangpeng1994-create/PokerSense/blob/136aa06938466e519dcb78e8bd0e4b6316d7d616/docs/OPPONENT-ACTION-LIKELIHOOD-DATA-AUDIT-V1.zh-CN.md) |
| 真实冻结策略评估接线修复 | 6/7/8人真实资产正控42/42与直接执行一致。原48探针及378配对首先因salt字符串／整数合同不匹配失败；修复后用原资产再跑才确认378次未命中。原592条均匀记录只有首轮更新 | 接线可信；两种失败不能混为同一种。旧结果保留，首轮均匀不证明长期不能学习。[勘误](../AA-EVALUATION-CORRECTION-V1.zh-CN.md) |
| V1/V2有预算学习与新牌局 | 99任务全部执行；V1/V2各九配置有非均匀学习变化，18个不更新对照均匀。V2完整345/5670（6.08%），V1为350/5670；总11340=695完成+10645阻断，EV空。另3150查询中，三个翻后街各0/630命中 | 学习信号PASS，未见完整牌局NO_GO；不继续扩大原训练。查询与配对不混成一个分母。[九配置结果](../AA-POLICY-READINESS-RESULTS-20260927.zh-CN.md) |
| 两个本地模型：筛查→决策→全手 | 初始各24个固定四街查询只证明可加载和合法输出。之后基本决策0.8B正确6/9、2B正确3/9；2B三个本人皇家同花顺案例全弃牌。全手计划3780=3297完成+3批次边界阻断+480未执行；及时完整1901/3780 | 两模型NO_GO；多个完整合成对战组退化。0.8B虽1890/1890完成，却只有1次转牌、0次河牌实际决策；2B完成1407/1890。保留未执行分母，不从成功子集推整体盈利。[筛查](../AA-LOCAL-CANDIDATE-SCREEN-20260927.zh-CN.md)、[最终诊断](../AA-LOCAL-FULLHAND-20260928.zh-CN.md) |
| 原九份V2的有限翻前审计 | 10647支持槽位／31941资产行全部处理：HIT2833、UNVISITED23204、全零regret无平均1990、非零regret无平均872、不适用3042。可构造2833/28899=9.80%；按资产内键去重2229/27378=8.14% | 支持仍严重稀疏。指定“先跟注再面对一次最小加注”前缀的9126可构造行全部未访问；不能扩称所有第二次行动。没有新训练，也不是从6.08%提升到9.80%。[完整审计](../AA-PREFLOP-SUPPORT-AUDIT-20260928.zh-CN.md) |

后两轮预算实际为：本地模型基本检查约31.048秒；全手两批2382.376／2387.223秒；翻前审计一批107.621秒。
各批在预声明上限内结束，没有按结果追加第三批全手实验或第二批支持集审计。
基本决策检查是有意构造的公开信息算例，包含50%人工费用压力；它不是AA真实费率，
6/9或3/9也不是现场准确率。两个固定候选的失败不扩展成对所有语言模型的结论。

重要解释：regret表存在只说明表行存在；全零不等于从未访问，非零也不等于平均策略已导出。
现有SIMPLE next-player平均方式并不对每次遍历都累计平均。旧记录缺少逐次traverser角色，
不能事后编造某个键为什么没被平均；本次审计也没有证明仅修改平均器就能补上未访问状态。

## 4. 十秒窗口、表单和安装包的真实可用边界

**十秒设计目标**仍是源画面出现Hero行动后p95≤1秒／p99≤2秒，2秒内给有效建议或明确无法建议，
剩余不足3秒不新增或替换动作。截止必须来自可信起点或倒计时，不能靠重试再获得十秒。
这些合同和合成故障检查已实现；真实源时间、完整状态、合格策略及至少三会话／100个Hero机会的硬件验收尚未完成。

| 已有时延证据 | 正确用途 |
|---|---|
| V2查表调用p95约0.426–0.485ms，已命中样本的影子进程调用约0.396–0.641ms | 局部软件调用；不能忽略大部分未命中，不能称采集到显示时延 |
| 两本地模型全手诊断首次调用p95约416.051／647.165ms | 包含输入准备、调用前日志和工作进程；未达到本轮300ms目标。评分段另记，缓存重读不算新推理 |
| 截止／源年龄／浏览器TTL／工作进程终止测试 | 工程防护证据；不代替真实设备延迟分布或策略强度 |

**本桌设置**已在本地入口交付；没有要求用户每手先填行动历史。字段未知留空，手动完整配置也不升级为视觉确认或实战资格。
观察与复盘功能、手工条件分析和研究策略保持各自边界；没有接入自动下注。

**安装包事实需要按版本区分：**

- AA Windows安装器／便携目录来自[#37][pr37]的工程版本；`b796cce96426d37cb0c4f4746d0dd8998bc6c86d`的[构建36302657746](https://github.com/xiaoyangpeng1994-create/PokerSense/actions/runs/36302657746)成功，Release跳过。本次核查Windows／legacy macOS工件均未过期。
- 既有记录显示最终Windows安装器完成隔离安装→离线功能／13端点／冻结计算→卸载，`/NOICONS`已修复；安装器未签名。本次只是核对记录和构建状态，没有重新安装。
- 该二进制不代表后续PR #38–#42；尤其本桌表单增强没有另做新安装包。后续策略结果不能借旧包测试取得交付资格。
- 用户曾明确反馈的是“点击聊天里的链接打不开”，不能误记为已经复现EXE崩溃。正式Release仍未建立；本地源码启动入口为[START-AA.cmd](../../launch/aa/START-AA.cmd)，便携运行需要完整目录。

## 5. 给审核者的固定版本与PR依赖

依赖链为 `main → #37 → #38 → #39 → #40 → #41 → #42`；[#36][pr36]是main上的独立研究旁支，
[#35][pr35]是关闭保留的失败研究。不要将依赖PR内已有文件再次计算成后续PR的新成果。

| PR | 本次核对的head（均Draft，未合并） | 对应最新CI（三项SUCCESS） | 实验源码与说明 |
|---|---|---|---|
| [#37][pr37] | `674a63bab226702d1183eadc36122ea0c15459b2` | [36306458260](https://github.com/xiaoyangpeng1994-create/PokerSense/actions/runs/36306458260) | 含评估接线修复；旧包源码另列于第4节 |
| [#38][pr38] | `4e7ceae02e19116f62576442f61a1bdc906d500a` | [36311817446](https://github.com/xiaoyangpeng1994-create/PokerSense/actions/runs/36311817446) | 实验`40a42f5ad4dac88585ff7138a1a3856677fd0280` |
| [#39][pr39] | `15d5895d1a0721a0ddb603a69deb9acaab29930c` | [36318114836](https://github.com/xiaoyangpeng1994-create/PokerSense/actions/runs/36318114836) | 本桌设置表单；不重打包 |
| [#40][pr40] | `adfc1efb7f5f93a0d2ec7a37f086336225c37698` | [36330453585](https://github.com/xiaoyangpeng1994-create/PokerSense/actions/runs/36330453585) | 筛查源码`9663038fb9c95a7992908933f34c123b2902f179` |
| [#41][pr41] | `d3f70522c38014ea280b38af5127bc50ad5070d3` | [36339070865](https://github.com/xiaoyangpeng1994-create/PokerSense/actions/runs/36339070865) | 实验`2dfe5a57c4f274f5401319c7a6170fac1b1182ec` |
| [#42][pr42] | `f05d804ba701e8041552327867e4ac9e2d6420fd` | [36408605036](https://github.com/xiaoyangpeng1994-create/PokerSense/actions/runs/36408605036) | 实验`4ca7bc093140ddd3eaa822897b11e880e9c71c82` |

PR事件的CI通常checkout服务器生成的合并候选，不是直接checkout原head。
已核对#41实际测试`22d8e0d2891fb824777977a767b289aa666974b2`，#42实际测试`d44e91e4b6398f20f0d92c5e2fa5de200029d91d`。
更早运行可通过Actions checkout日志确认；不能把某个旧绿灯套给新的head。

工程验证各有范围：#37初始全套4701通过／2跳过；#39表单57项聚焦与浏览器合成流程；
#40筛查125项聚焦；#41新增73项；#42新增30项及84项既有回归。**这些有重叠，不能相加成独立测试总数。**
本次汇报仅做资料、版本、数字、链接与隐私核对，没有借汇报重做这些实验。

## 6. 什么证据能让ChatGPT独立核对

| 证据层 | 可访问范围 | 审核时应如何使用 |
|---|---|---|
| GitHub状态与代码 | PR、固定提交、代码、测试、协议、CI日志可公开读取 | 先核head和base，再检查实现与反例；不要只读本汇报或PR正文 |
| 已公开实验数据 | 例如[#35固定结果JSON](https://github.com/xiaoyangpeng1994-create/PokerSense/blob/cd2502ad3f67c2060e45569df6d8e00603348508/configs/strategy/evaluation/range-posterior-v1-results.json)、[#36合成结果JSON](https://github.com/xiaoyangpeng1994-create/PokerSense/blob/136aa06938466e519dcb78e8bd0e4b6316d7d616/configs/strategy/evaluation/action-likelihood-synthetic-results-v1.json)、冻结V1公开工件 | 可重新核算公开数据；仍然只是各自声明的合成条件 |
| 本报告的脱敏索引 | [evidence.json](POKERSENSE-WORK-REPORT-20260928.evidence.json)从现有报告白名单提取：18个V1/V2配置、18组模型对战、九个支持审计配置、原报告哈希和PR快照 | 可核对加总、去重、缺失分母和版本；这是**派生汇总，不是原始实验重现**，不把自报digest当独立证明 |
| 仅本机原始证据 | 完整训练checkpoint、模型权重、逐步原始日志、媒体／玩家资料、本机安装验证、部分独立复核回执 | 没有随本报告上传。ChatGPT无法访问时必须写“依赖本机证据／未独立核验”，不能说已重放全部实验 |

公开汇报不含原始媒体、真实玩家身份、凭据、模型大文件或私有原始日志。
本报告以本机原始报告SHA绑定派生数据，方便以后在本机比对；哈希不证明内容正确、时间真实或历史数据独立。

## 7. 尚未完成的门槛与唯一建议

| 待完成项 | 当前缺口 |
|---|---|
| 真实规则与完整牌局状态 | 用户真实桌规、精确逐手筹码／投入／合法菜单、完整因果行动序列与可信计时仍须实际验收；表单填满不等于完成 |
| 可部署全街策略 | 九份V2支持不足，两外部候选NO_GO；没有达到完整牌局覆盖和质量要求的资产 |
| 独立策略强度 | 每人数／候选预定2000配对块、独立新对手／反制、5BB/100退化界限、50/200BB／不等码／非网格压力、独立确认尚未完成 |
| 真实十秒可靠性 | 三个受控会话、至少100个Hero机会、源画面到显示p95/p99、故障／失焦恢复、及时有效建议覆盖≥80%及零过期／跨回合／非法输出尚未验收 |
| 持续优化闭环 | 已有有界研究编排、冻结和报告；没有无人值守长期自优化、自动晋升或在线改权重；回退／晋升须有新证据与受控确认 |
| 用户交付与财务 | 正式签名／Release／当前整套功能安装包仍待交付验收。首月2000元是此前预算上限，不是已支出；本次不付费。Jev无真实调用，较早视觉API费用本次未核账 |

**建议下一步只做“可完全枚举的小型对局中的采样覆盖与平均权重验证”。**
先固定应估计的平均量、各状态的到达概率和对照，再决定是否改采样／收集机制。
该建议来自未访问占主要部分且存在平均缺口的事实；没有证明现有SIMPLE实现有bug，也不保证单改平均器能解决全部覆盖。
本汇报不启动这个新实验，不延长旧训练，不更换第三个模型，不把失败研究重新命名为通过。
“8个AI自行打牌”可作为局外模拟的长期方向，当前仍需要以上质量和部署门槛；真人行动时不进行重训练或云决策。

## 8. 可直接交给ChatGPT的审核任务

下面的审核要求针对固定快照；审核者应报告自己实际读取了什么、哪些证据不可访问。

建议先看这些代码入口，再按问题追到对应测试；不要把逐个PR重复通读当成独立证据次数。

| 审核重点 | 直接入口 |
|---|---|
| 候选／人工事实边界 | [确认与回执](../../src/poker_engine/desktop/aa_real_hand_confirmation.py)、[标注／曝光](../../tools/aa_annotation_records.py) |
| 截止、身份与隔离 | [回合合同](../../src/poker_engine/desktop/aa_turn_runtime.py)、[影子进程](../../src/poker_engine/desktop/aa_frozen_shadow.py) |
| 表示、学习与平均导出 | [V2编码](../../src/poker_engine/strategy/aa_policy_encoding_v2.py)、[MCCFR](../../src/poker_engine/strategy/aa_mccfr.py)、[冻结策略](../../src/poker_engine/strategy/aa_frozen_policy_v2.py) |
| 全手与完整分母 | [配对评估](../../src/poker_engine/strategy/aa_arena_evaluation.py)、[V1/V2编排](../../tools/aa_policy_readiness_study.py) |
| 候选诊断和支持审计 | [本地模型全手工具](../../tools/evaluate_aa_local_fullhands.py)、[翻前支持审计](../../tools/audit_aa_preflop_support.py) |
| 当前配置与旧包区别 | [规则保存](../../src/poker_engine/desktop/table_rules.py)、[Windows打包](../../packaging/pokersense.spec)、[安装器](../../packaging/pokersense.iss) |

```text
请独立审核这份PokerSense工作汇报，不要只复述或信任作者结论。
先读汇报、同目录evidence.json、main与PR #37–#42的固定SHA；
失败研究另看#35、#36的固定分支，不能把它们当已合并代码。

请回答：
1. 有无重复计算同一能力、同一状态、重跑样本、依赖PR或测试数量？
2. 是否混淆合并/上传/打包/安装/实战验收，以及工程PASS/学习变化/覆盖/收益？
3. 原378次失败的两阶段归因、V2全部配置和查询分母是否正确？
4. 本地模型的基本错误、3297+3+480完整分母、批次边界超时及四街范围是否说清？
5. 翻前审计31941分类、28899可构造与27378去重分母，能否从索引核算？
   是否存在把全零regret称为学会、把非零regret当平均策略、或把未访问靠补动作掩盖的问题？
6. 10秒预算哪些已通过软件验证，哪些缺真实输入/硬件/强策略证据？
7. 现有证据是否足以支持“下一步先验证采样覆盖与平均权重”？请给一个优先目标、
   明确退出条件和停止条件；不要自动扩成多个算法或追加云预算。

输出：逐项PASS/PARTIAL/FAIL/无法核验；问题严重级别；对应文件、SHA或数据行；
必要的最小复现；最后给项目成熟度判断和唯一下一步。
对仅本机原始证据请标记“未独立核验”，不得凭公开汇总或哈希假装已经复现。
这次只审核，不合并、发布、启动采集、付费或训练，也不要把后来的底牌标签用于决策时输入。
```

[pr1]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/1
[pr2]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/2
[pr3]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/3
[pr4]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/4
[pr5]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/5
[pr6]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/6
[pr7]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/7
[pr8]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/8
[pr9]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/9
[pr10]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/10
[pr11]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/11
[pr12]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/12
[pr13]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/13
[pr14]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/14
[pr15]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/15
[pr16]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/16
[pr17]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/17
[pr18]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/18
[pr19]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/19
[pr20]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/20
[pr24]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/24
[pr26]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/26
[pr28]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/28
[pr29]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/29
[pr30]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/30
[pr31]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/31
[pr32]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/32
[pr33]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/33
[pr34]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/34
[pr35]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/35
[pr36]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/36
[pr37]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/37
[pr38]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/38
[pr39]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/39
[pr40]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/40
[pr41]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/41
[pr42]: https://github.com/xiaoyangpeng1994-create/PokerSense/pull/42
