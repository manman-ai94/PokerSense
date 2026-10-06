# STRATEGY-001 证据矩阵与来源核查

任务：STRATEGY-001（Issue #23）· run_id `STRATEGY-001-20260915T233757Z-r2`
固定基线：`dc72a4176f81689e95a9238a49fb2d268dcd4a56`（PR #20 head / 分支 `codex/aa-live-recognition-v1`）

本文件回答 Issue 指定的四个问题，并把每个来源按**本轮实际核查深度**标注来源等级。等级定义：

| 等级 | 含义 |
| --- | --- |
| `VERIFIED_THIS_RUN` | 本轮由本机实际抓取一手页面/摘要并逐条记录 |
| `VERIFIED_PRIOR_PROJECT` | 由本项目既往研究文档记录，含 commit 固定链接或 DOI；本轮**未**重新抓取 |
| `NOT_RE_VERIFIED_THIS_RUN` | Issue 列出但本轮未独立抓取；**不得**据本文件宣称已读全文 |
| `UNKNOWN` | 未知项，禁止猜测填充 |

> **本批最大缺口（如实记录）**：受本次执行的实际时间/上下文预算限制，`VERIFIED_THIS_RUN` 只有 2 项。
> 其余来源沿用项目既往已固定 commit/DOI 的记录，或标注为未复核。不将未复核项写成已读。

---

## 1. 四个问题的取证

### Q1 多人不完全信息决策：哪些思想可借鉴，哪些定理只适用于两人零和

| 来源 | 等级 | 与本项目直接相关的结论 |
| --- | --- | --- |
| Zinkevich, Johanson, Bowling, Piccione, *Regret Minimization in Games with Incomplete Information*, NIPS 2007 | `VERIFIED_THIS_RUN`（仅摘要） | 提出 **counterfactual regret**；「minimizing counterfactual regret minimizes overall regret, and therefore in self-play can be used to compute a Nash equilibrium」。**注意**：抓取到的摘要文字**未**限定两人零和；该限制来自正文/后续文献，本轮**未**在正文中核实。 |
| Brown, Bakhtin, Lerer, Gong, *Combining Deep RL and Search for Imperfect-Information Games*（ReBeL），arXiv:2007.13544v2 | `VERIFIED_THIS_RUN` | 摘要原文：**"provably converges to a Nash equilibrium in any two-player zero-sum game"**；实证为 **heads-up** no-limit hold'em。这是本项目「不把 heads-up 理论保证冒充多人保证」的直接文献依据。 |
| Brown & Sandholm, *Superhuman AI for multiplayer poker*, Science 2019 | `VERIFIED_PRIOR_PROJECT` | 项目既往记录：CFR 平均策略收敛到 Nash 的保证**适用于双人零和，多人不保证**；Pluribus 六人 NLHE 击败职业玩家是「自博弈+搜索能产生强多人策略」的实证，不是「多人均衡必不亏」。 |
| 项目结论（本项目自身判断） | — | 多人无抽水扑克玩家总转移仍可为零和，但「多于两人」本身不满足双人 minimax/CFR 的前提；不能靠加一个被动玩家恢复双人性质。 |

**可借鉴**：反事实遗憾与自我博弈的**训练范式**、抽象/蓝图的工程分层、搜索与学习的组合（ReBeL 的框架思路）。
**不可移植**：任何「收敛到 Nash ⇒ 不亏」的安全保证。本项目 6–8 人桌必须继续按**有限假设下的最坏相对损失**比较来表述结论，而不是均衡保证。

### Q2 范围/响应模型错设时如何评估固定策略（不借助未来信息或对手真实底牌）

| 来源 | 等级 | 结论 |
| --- | --- | --- |
| 本项目 `threeway_policy_evaluation_v1.py` | `VERIFIED_THIS_RUN`（实跑） | 规划阶段冻结公开条件、规划场景哈希与策略哈希；**评价阶段只执行冻结映射**，不重新优化 Hero。世界可改对手范围/响应参数，公开牌、Hero 手牌、费用规则、历史与动作网格必须一致。 |
| 本项目 `response_model_calibration_v1.py` | `VERIFIED_PRIOR_PROJECT` | 冻结有限候选，用训练集 log loss 选一个，再**仅验证该候选**；训练/验证按 session 与 hand 同时隔离；验证不得改选。 |
| 本轮实跑 | `VERIFIED_THIS_RUN` | 选中的是 `calling_public_v1`，验证集平均 log loss 0.8328…（历史值，本轮未重算该标量）。 |

**关键点**：固定策略评价只在**给定世界**下给条件期望——不产生统计置信区间，也不构成对手建模能力。反例（QQ vs 弱 TT 得 CALL/EV 160，换强 JJ 仍 CALL 但 EV −100）说明**输入假设错了，精确计算只会精确地错**。

### Q3 下注尺寸抽象、未覆盖公开历史、all-in/边池、前注/straddle/抽水如何限制可用范围

| 限制 | 等级 | 本项目现状 |
| --- | --- | --- |
| 未覆盖公开历史 | `VERIFIED_THIS_RUN` | 存在**预声明的 fallback 规则**（未覆盖历史按声明规则免费 check，否则 fold），并分别记录 fallback 概率与次数；本轮 30 个世界 **fallback = 0**，即本轮失败**不是**由 fallback 引起。 |
| 动作网格外下注 | `VERIFIED_PRIOR_PROJECT` | 不支持；零 fallback 并**不**证明能应对网格外动作。 |
| all-in / 边池跨越 | `VERIFIED_PRIOR_PROJECT` | 一般三人非 all-in 模块与终结 call/边池模块**不得混淆**；`terminal_multiway_v1.py` 只覆盖 river 上「Hero 唯一 ACTIVE、其余 ALL_IN」的终结条件 EV。 |
| 前注 / straddle / 抽水 | `VERIFIED_PRIOR_PROJECT` | 实际 2/4/8、ante=4 仅按已确认记录表达；straddle 子类型、抽水、封顶**未确认即保留 UNKNOWN**；不默认为零。 |
| 桌上人数 ≠ 活跃人数 | `VERIFIED_THIS_RUN` | 6/7/8 人桌全程仍只有 **3 个 ACTIVE**；不得据桌人数宣称多人能力。 |

### Q4 本机可运行的最小实验与资源成本（实测而非猜测）

| 项 | 实测值（本轮） |
| --- | --- |
| 机器 | Core Ultra 5 245KF，14 核 / 14 线程，约 31.6 GiB RAM |
| `validate_threeway_models.py` | exit 0，**wall 2 s**；30 world_cases / 60 fixed_policy_evaluations / fallback 0 |
| `study_opponent_uncertainty.py` | exit **2**（设计内信号），**wall 5 s**；6 组判定 |
| Python / 依赖 | Python 3.13.14；numpy **2.3.5**、opencv **4.10.0** |
| 与 `pyproject.toml` pin 的差异 | pin 为 numpy **2.4.6** / opencv **4.14.0.94** ⇒ **环境与 pin 不一致**。策略工具为纯 Python 路径，本轮结果未受影响，但这是复现性风险，需单独处理。 |

结论：当前失败复现**不需要**云算力、不需要重新训练、不需要第三方 solver；全流程秒级。真正的瓶颈不是算力，而是**输入假设质量与数据可准入性**。

---

## 2. 开源实现核查

| 项目 | 等级 | 已核实的关键事实 | 本项目用途 |
| --- | --- | --- | --- |
| [google-deepmind/open_spiel](https://github.com/google-deepmind/open_spiel) | `VERIFIED_PRIOR_PROJECT`（commit `4840189`） | `universal_poker` 声明 2–10 玩家，有 6 人 NLHE 配置与多人测试；Apache-2.0 | **自博弈/算法实验/独立对照环境**；不是训练好的强策略 |
| [uoftcprg/pokerkit](https://github.com/uoftcprg/pokerkit) | `VERIFIED_PRIOR_PROJECT`（commit `54571dd`） | 真实多人规则/结算库，6 人、ante、straddle 示例，支持自定义 rake；MIT | **规则/结算交叉校验**；不是决策策略 |
| [MatthewPDingle/GTOpen](https://github.com/MatthewPDingle/GTOpen) | `VERIFIED_PRIOR_PROJECT`（commit `92c86ed`） | README 明确 **Postflop is heads-up only**；多人 preflop 为 continuation approximation；3+ 人叶子 latent-strength 样本不是联合发出的真实底牌/公共牌 | 已有适配器 ≠ AA 多人策略可用；**不得称完整多人全街求解器** |
| [EricSteinberger/Deep-CFR](https://github.com/EricSteinberger/Deep-CFR) | `NOT_RE_VERIFIED_THIS_RUN` | 本轮未抓取 | 待评估：Deep CFR 参考实现 |
| [EricSteinberger/PokerRL](https://github.com/EricSteinberger/PokerRL) | `NOT_RE_VERIFIED_THIS_RUN` | 本轮未抓取 | 待评估：环境/算法对照 |
| [datamllab/rlcard](https://github.com/datamllab/rlcard) | `NOT_RE_VERIFIED_THIS_RUN` | 本轮未抓取 | 环境/评估对照，非必须新增依赖 |
| [bupticybee/TexasSolver](https://github.com/bupticybee/TexasSolver) | `VERIFIED_PRIOR_PROJECT`（commit `d12197b`） | 源码 `player_number=2`，后续 `oppo = 1 - player`；**AGPL-3.0** | 仅 HU 参考后端；不能承担 3+ 活跃玩家求解 |
| [b-inary/postflop-solver](https://github.com/b-inary/postflop-solver) | `VERIFIED_PRIOR_PROJECT`（commit `9d1509f`） | 双人数组；README 的 6-max 是**最多 4 名已弃牌者**的 bunching，不是 6 人仍争池；**AGPL-3.0** | HU 参考与比对工具 |
| [c-heidt/pluribus-opponent-exploitation](https://github.com/c-heidt/pluribus-opponent-exploitation) | `VERIFIED_PRIOR_PROJECT`（commit `dd422bb`） | 真有多人 external-sampling MCCFR 路径与 3 人边池测试；**KIT 硕士研究实现，非官方 Pluribus**；文档描述约 420 GB 磁盘 / 约 150 GB 蓝图 RAM，有 Linux/HPC 依赖 | 值得**隔离评估**，不能直接实战；本机不建议按 150 GB 常驻方案部署 |

**许可提醒**：`NOT_RE_VERIFIED_THIS_RUN` 的项目其 LICENSE 一律视为 **UNKNOWN**。非商用不等于无许可条件；
不得因为「公开仓库」就假定可复制或再分发。本轮**未**安装、运行或训练任何第三方 solver，也未执行其安装脚本。

---

## 3. 技术决策记录（立即复用 / 仅作参考 / 暂不采用）

### 立即复用（已有本机依赖，零新增）

1. **既有四人模块链路**：`threeway_policy_evaluation_v1` + `response_model_calibration_v1` + `robust_policy_selection_v1` + `opponent_dataset_v1`。
   理由：本轮已实跑，秒级、可复现、含预声明 fallback 与预算失败保留。对应缺口：**输入假设质量**，不是计算能力。
2. **冻结式评价协议**（先冻结候选与策略哈希，再跑世界；验证不重选）。
   理由：这是本项目唯一能避免「看结果后调参再称独立验证」的机制。对应缺口：缺少真实对手池。
3. **合成/手工世界的回归地位**：五个旧世界作为回归保留，不反复针对其调参。

### 仅作参考（不引入依赖）

4. **OpenSpiel / PokerKit**：作为**独立环境与结算对照**的参考实现。
   理由：Apache-2.0 / MIT 清晰，但引入即新增依赖且不解决当前瓶颈（输入假设与数据）。
   对应缺口：本项目结算内核与第三方的一致性校验目前仍是空白。
5. **ReBeL / Deep CFR / DeepStack / DDCFR 的方法框架**：只借鉴「搜索+学习组合」「价值网络替代子博弈求解」的思路。
   理由：ReBeL 的保证**明确限定两人零和**，直接移植到 6–8 人桌没有理论依据。
6. **Pluribus 论文的实证口径**：只作为「多人强策略存在实证可行性」的论据，作为**性能数字不可外推**（六人、每手重置 100BB、无 AA 前注/straddle/抽水）。

### 暂不采用（并说明原因）

7. **任何 HU 求解器充当多人引擎**：TexasSolver / postflop-solver 的 `player_number=2` 是硬事实。
8. **GTOpen 作为多人全街求解器**：README 自述 postflop 仅 heads-up，多人 preflop 是近似 continuation。
9. **重训大模型 / 长时间自博弈 / 租云算力**：本批边界禁止；且当前瓶颈不是算力（复现全流程秒级）。
10. **LLM 作为策略数值内核**：自然语言模型只用于研究与编码，不替代数值决策内核。

---

## 4. 与本仓库具体模块/缺口的对应表

| 模块 | 现状（本轮核实） | 缺口 | 对应上面的决策 |
| --- | --- | --- | --- |
| `strategy/threeway_policy_evaluation_v1.py` | 冻结策略评价 + fallback 计数；本轮 fallback=0 | 评价世界是**手写压力世界**，不是对手池；比较对象存在结构性退化（见 findings 文档） | 立即复用；先修可测量性问题 |
| `strategy/response_model_calibration_v1.py` | 有限候选 log loss 选择；训练/验证隔离 | 候选族有限；`policy_source` 为合成 | 立即复用，不扩大模型族 |
| `strategy/opponent_dataset_v1.py` | 严格准入：机会清单 + 逐项字段绑定 | **真实可准入记录 = 0**（既有开发日志不满足完整合法菜单/时点要求） | 保持严格，不用不足数据拟合 |
| `strategy/robust_policy_selection_v1.py` | 最坏相对损失（对 check/fold、check/call 取较强基线） | 未使用验证结果改选（正确）；但选出的策略在压力世界仍失败 | 立即复用；结论表述为 FAIL/INSUFFICIENT_EVIDENCE |
| `strategy/terminal_multiway_v1.py` | 终结 river（Hero 唯一 ACTIVE、其余 ALL_IN）条件 EV | 不覆盖一般三人非 all-in；不支持网格外下注/边池跨越 | 保持边界，不与一般模块混淆 |
| `tests/`（策略相关） | 既有聚焦测试与全仓回归 | 本次未新增 | Phase 5 |

---

## 5. 本文件明确**不**主张的内容

- 不主张已完整阅读任何未标 `VERIFIED_THIS_RUN` 的论文全文或仓库源码。
- 不主张多人 GTO 已可用、不主张任何盈利或实战资格。
- 不把 Pluribus 论文结果当作任意同名 GitHub 实现的能力证明。
- 不把合成恢复（log loss）当作学到真实对手。
- 不把局部 river 条件 EV 换算成全手 bb/100。
