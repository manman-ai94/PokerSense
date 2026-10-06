# PokerSense 开源架构基准（OPEN_SOURCE_ARCH_BENCHMARK）

- **run_id**：`oss-arch-benchmark-20260917-1745`
- **日期**：2026-09-17
- **产品基线**：`xiaoyangpeng1994-create/PokerSense` PR #28 head `fbda7c52bd40c460bdca919b4e1a43547606de0d`（Draft，base `codex/strategy-001-research`）
- **本轮性质**：**研究轮，零产品代码改动**。没有改任何生产文件、没有给产品加任何依赖、没有改求解器常量、没有重训视觉。
- **报告去向**：Issue #27；ACK 见 `issuecomment-5712314341`。
- **后续修订（2026-09-18，PHASE 5）**：本报告里「因 license / 无明确 license / AGPL 直接淘汰技术候选」的那部分结论，**已被 owner 决策 supersede**，见 §1.1 末尾的 **OWNER OVERRIDE（许可证不作为技术筛选门槛）**。
  本次修订**只改结论口径**：原始实验数据、PokerKit PoC、PHH roundtrip、强制投入 `17`、边池、UNKNOWN 风险、所有 upstream metadata、原报告日期 `2026-09-17` 与 `run_id`、原研究上下文**一律未改动**。

> **证据分级**（全文遵循，不混用）：
> 【实测】本轮在本机真实运行得到的输出；【读码】直接读上游源码文件得到的结论（给路径+符号）；【规范】上游规范原文（给文件+行）；【仓库既有】本仓库既有文档（`docs/`、`AGENTS.md`）已记录的事实；【推断】无直接证据的推断。
> 凡标【推断】的都不作为决策的唯一依据。

---

## 0. 一句话结论

**H1 成立、H2 成立，但有一个决定性的安全边界。**

1. **PHH + PokerKit 应当成为 PokerSense 的「已确认手牌」规范表示与规则/结算 oracle**——前提是**只喂已确认事实**。本轮用真实库跑通了：AA 桌强制投入结构能**逐字节复现**录像里观测到的开局底池 **17**；边池、派彩、PHH 往返全部与上游一致。
2. **但 PokerKit 对「未知信息」的裁决是静默错的**：未知牌会被判成「不能赢」、手牌评估直接抛 `KeyError(Rank.UNKNOWN)`；PHH 能**存**未知（`??`、`inf`），PokerKit 不能**判**未知。⇒ **不确定性/溯因层必须留在 PokerSense 手里**，这不是可选项，是这套方案能安全落地的前提。
3. **求解器侧维持「验证而非替代」**：不存在开源多人翻后求解器（本轮复核成立，且既有调研已记录一行被本轮点名的清单里漏掉的首选：`b-inary/postflop-solver`）。近期唯一能落地的独立参照是**河牌单挑子博弈**。

---

## 1. 方法与上游核对结果

### 1.1 上游版本与许可（【实测】`gh api repos/<r>` 逐仓库读取）

| 仓库 | SPDX | 语言 | 最近推送 | ★ | 归档 | 与本项目的关系 |
| --- | --- | --- | --- | --- | --- | --- |
| `uoftcprg/pokerkit` | **MIT** | Python | 2026-08-22 | 498 | 否 | **采用**（格式 + 规则 oracle） |
| `uoftcprg/phh-std` | **MIT** | Python(Sphinx) | 2025-05-08 | 19 | 否 | **采用**（规范文本） |
| `google-deepmind/open_spiel` | **Apache-2.0** | C++ | 2026-08-31 | 5490 | 否 | 参照/评估框架（后期） |
| `MatthewPDingle/GTOpen` | **无许可** | Rust | 2026-09-17 | 14 | 否 | **技术研究 / PoC / oracle 候选**：仓库无明确 license，**直接复制或分发代码时需单独评估，但不因许可状态淘汰其技术价值**（OWNER OVERRIDE，见本节末尾） |
| `bupticybee/TexasSolver` | **AGPL-3.0** | C++ | 2026-08-26 | 2550 | 否 | **技术参考 / oracle 候选**（离线独立进程）；AGPL 继续记录为**直接代码复用与分发边界**，单独处理，**不因 AGPL 自动判为技术不可用** |
| `bupticybee/TexasHoldemSolverJava` | **MIT** | Java | 2026-07-01 | 913 | 否 | 备选参照（需 JRE11，慢） |
| `EricSteinberger/PokerRL` | **MIT** | Python | 2023-03-31 | 542 | 否 | 仅方法论 |
| `EricSteinberger/Deep-CFR` | **MIT** | Python | 2020-05-06 | 332 | 否 | 仅方法论 |
| `datamllab/rlcard` | **MIT** | Python | 2024-06-26 | 3548 | 否 | 无增量价值 |
| `b-inary/postflop-solver` | **AGPL-3.0** | Rust | 2024-07-09 | 370 | 否 | **既有调研首选，本轮复核仍在**；同上，AGPL 只界定**直接代码复用与分发边界**，不构成技术淘汰 |

许可结论（三条硬事实）：
- **PokerKit / PHH-std / OpenSpiel / PokerRL / Deep-CFR / rlcard 的许可都不阻塞自用集成**；PokerKit 是 MIT + 纯 Python，可以进产品依赖（本轮**没有**加，见 §10）。
- **GTOpen 至今没有 LICENSE 文件**（【实测】`gh api …/license` 为空；本地 `.upstream/GTOpen/` 里也 `find` 不到 LICENSE）。这既有文档结论一致，**该事实在任何修订中都保留不变**；被撤回的只是「所以它技术上不可用」这一推论（见下方 OWNER OVERRIDE）。
- **AGPL 组件的既有边界继续有效**（`docs/tech-stack-matrix.md` 附节）：源码/二进制不进仓库、只走独立进程、不静态链接。本轮未新增任何 AGPL 代码或资产。

#### OWNER OVERRIDE · 后续项目决策（2026-09-18，Issue #27 `issuecomment-5712960433`）

> **本小节 supersede 本报告中任何「因 license 直接淘汰技术候选」的旧结论。** 上述三条**事实**（含「GTOpen 当时确实没有 LICENSE 文件」）**全部保留**；被撤回的只是从中推出的**技术筛选结论**。

**owner 决策原文要点**：PokerSense 当前为**非商用、本地研究/自用项目**，因此
「**许可证不再作为技术候选的淘汰条件**」；仍记录 license / no-license，仅作为**事实备注与未来用途提醒**；
技术上有价值的项目（含无明确 license、AGPL 等）都可进入**学习、架构借鉴、隔离 PoC、对照验证、接口复用候选**；
调研结论不得再用「无许可 / AGPL」直接判定「技术不可用」，应改写为「**技术价值 + 集成方式 + 运行边界**」。

**统一口径（全文适用）**：

> **license status 是事实字段和「直接复用 / 分发」的边界，
> 但不是本项目当前的技术候选淘汰条件。**

**三类用法必须分开写**（owner 决策原文）：

| 类别 | 用法 | license 是否构成阻塞 |
| --- | --- | --- |
| ① 借鉴算法 / 架构 | 读源码、学结构、抄思路，不搬运代码 | **否**，无阻塞 |
| ② 本地隔离运行 | 独立进程 / 离线 PoC / oracle / cross-check | **否**，无阻塞（AGPL 走独立进程即可） |
| ③ 直接复制或嵌入大量源码 | 把上游源码/二进制并进产品、静态链接 | **是**——这是**复用与分发边界**，需单独评估；若未来项目用途改变，再单独复核 |

**据此被修订的具体条目**：

| 项目 | 旧分类（已 supersede） | 新分类 |
| --- | --- | --- |
| `MatthewPDingle/GTOpen` | ~~不可用（无许可文件）~~ | **技术研究 / PoC / oracle 候选**；尤其 solver workflow、Rust engine、preflop lab、reports、player model/evidence 设计。无明确 license 只影响 ③ 类直接复制/分发，需单独评估 |
| `bupticybee/TexasSolver` | ~~AGPL ⇒ 排除~~ | **技术参考 / oracle 候选 / 源码学习候选**；AGPL 继续记录为 ③ 类复用边界（不进产品、不静态链接），**不据 AGPL 判为技术不可用** |
| `b-inary/postflop-solver` | （首选，但带 AGPL 顾虑） | **仍是首选**；AGPL 同上只界定 ③ 类边界，离线独立进程使用无阻塞 |

**后续 GitHub 调研的第一筛选标准**（owner 决策）：**是否能减少 PokerSense 自研弯路、是否能提供可验证能力**，而非许可状态。
本轮**不需要**重做整份调研，只修正 license gating 造成的排序偏差。

### 1.2 本轮亲自跑过的 PoC（这是本轮唯一的「新证据」）

环境：隔离 venv `C:\Users\Administrator\.workbuddy\tmp-oss\venv-oss`，`pip install pokerkit` → **0.7.5**（PyPI，2026-08-22 发布，纯 Python，`python_requires>=3.11`）。**未安装进产品环境**（产品 `pyproject.toml` 仍是 `requires-python>=3.11,<3.14` + numpy/opencv 三件套）。

脚本与输出（临时目录，不进仓库）：

| 文件 | sha256 | 说明 |
| --- | --- | --- |
| `poc_h1_table.py` | `8b13b12c8bacc7c78f4f64136b2e7974a5d298791d6c16a8c5e11ef8fb6837f3` | 强制投入 / 边池 / PHH 往返 / 未知牌 |
| `poc_h1_partial.py` | （见 §1.4）| PHH 承载不完整与未知信息 |

**A. AA 桌强制投入结构——被逐字节复现（【实测】）**

录像事实（【仓库既有】`docs/research/usable-001-opening-boundary-and-ordinary-river-close.zh-CN.md:48-62`）：三手牌开局底池**各自恰好 17**（帧 8647 / 9814 / 11130），成因写作 `5 座 × ante 2 + SB 1 + BB 2 + UTG straddle 4`。
把同一结构喂给 PokerKit：

```
antes           = {0:2, 1:2, 2:2, 3:2, 4:2}   # 只给 5 个已发牌座位
blinds_or_straddles = (1, 2, 4, 0, 0)         # SB 1 / BB 2 / UTG straddle 4
create_state(..., starting_stacks=(200,)*5, player_count=5)
→ total_pot_amount = 17        stacks = [197, 196, 194, 198, 198]
→ actor_index = 3（straddle 之后由 index 3 先行动）
```

⇒ **开局底池 17 不是识别误差，而是该桌强制投入结构的必然结果**，且 PokerKit 能原样表达它（含「按已发牌座位下 ante」与「强制 straddle」两件本桌特有的事）。这条把 ⑳/㉔ 的推断升级为**可执行验证**。

**B. 边池与派彩（【实测】）**

3 人、栈 `(100, 40, 20)`、短栈全下 20、深栈加到 40：

```
SIDE POTS: [(60, 0, (1, 2)), (40, 0, (1,))]    # 主池 60 归 {p2,p3}；边池 40 归 {p2}
settlement: final stacks = [60, 40, 60]        # 合计 160 == 起始总额（守恒）
tail ops: ChipsPushing ×2, ChipsPulling ×2      # 两个池各推送一次
```

⇒ 边池（`Pot.player_indices`）与派彩方向都由上游给定，守恒精确成立。

**C. PHH 往返（【实测】）**

`HandHistory.from_game_state(GAME, state)` → `dumps()` 得 310 字符 TOML，内容含 `variant='NT'`、`antes`、`blinds_or_straddles`、`min_bet`、`starting_stacks`、`actions`；`HandHistory.loads()` 后逐 action 重放 **13 步，最终栈 `[60,40,60]` 与原始完全一致**。动作记号实测形状：`d dh p1 9c3h`（发底牌）、`p3 cbr 20`（加到 20）、`p2 cc`（跟注/过牌）、`p1 sm 9c3h`（亮牌/埋牌）、`d db 2c2sKh`（发公共牌）。

**D. 未知信息的裁决——关键失败（【实测】）**

```
StandardHighHand.from_game('??Ad', 'AhKhQh2s3d')  ->  RAISED KeyError: <Rank.UNKNOWN: '?'>
StandardHighHand.from_game('AcKd', 'QhJhTh2s3d')  ->  AcKdQhJhTh   （已知则正常）
```

并在 PHH 载入后探测状态：

```
can_win_now(0)  ->  False          # 手里是 ?? 的玩家被判为「现在不能赢」，不是 UNKNOWN
hole_cards      ->  UNKNOWN OF UNKNOWNS (??)
```

⇒ **上游把「未知」当「输」处理**。这是本轮最重要的发现：它决定了 PokerSense 的架构分工（见 §4）。

### 1.3 PHH 规范关于「不完整 / 未知」的原文（【规范】`phh-std/required.rst`）

- `starting_stacks`：「Unknown stack values can be denoted as `inf`」（:149）⇒ 未知筹码可表达，实测载入后为 `Decimal('Infinity')`。
- 底牌：「some or all of which may be unknown」（:210）；未知牌写作 `??`（:279）。
- 动作数组：「The actions may represent a complete history of the hand or **a partial history that does not reach the terminal state**」（:178）⇒ **规范明确允许不完整手牌**，实测 `loads()` 通过（9 步）。
- 亮牌/埋牌：现金局允许 `??Ad` 这种半亮（:240）。
- `winnings`：「If rakes are applied the winnings should denote the post-rake values」（`optional.rst:170`）⇒ **规范没有独立抽水字段**，抽水只能体现在 `winnings` 里。

### 1.4 「PHH 能承载我们的不确定性」——成立的只有一半

| 问题 | 结论 | 证据 |
| --- | --- | --- |
| 能否记录部分已知的一手？ | **能** | 【规范】`required.rst:178` + 【实测】`loads()` 通过 |
| 能否记录未知底牌/未知筹码？ | **能** | 【规范】`??` / `inf`；【实测】`Decimal('Infinity')` |
| 能否记录「这个字段是人工核对的 / 是识别推断的」？ | **不能直接记录** | 只有 `author` / `event` / `venue` / `url` / `hand` 这类自由文本（`optional.rst`），以及动作尾部的 `# commentary` 通道（`required.rst:190-196`）。**没有结构化的 provenance 字段。** |
| 能否记录抽水参数？ | **不能** | 上游无 rake 字段（§1.3） |
| 记录后能否被上游**裁决**？ | **不能（危险）** | §1.2-D：未知被判「不能赢」/ 抛 `KeyError` |

---

## 2. 决策矩阵（17 行，每行**恰好一个**建议）

> **五种建议的判定口径（本轮统一定义，避免歧义）**
> - `KEEP_POKERSENSE`：该行继续自研，上游无可用替代或不适用。
> - `WRAP_EXTERNAL`：该行能力**由上游客观实现**，我们只保留薄适配层（上游成为事实实现）。
> - `USE_AS_ORACLE`：**保留自研为主**，但每个已确认样本都必须与上游**对照**，不一致即 fail-closed。
> - `REPLACE_INTERNAL`：**删掉自研的规则实现**，由上游接管；我们的代码降级为证据/适配。
> - `DEFER`：本轮不决定，并写明触发条件。

| # | 能力 | 建议 |
| --- | --- | --- |
| 1 | capture / frame ingestion | `KEEP_POKERSENSE` |
| 2 | visual recognition | `KEEP_POKERSENSE` |
| 3 | temporal smoothing | `KEEP_POKERSENSE` |
| 4 | seat / dealer / actor tracking | `KEEP_POKERSENSE` |
| 5 | forced-bet / opening reconstruction | `USE_AS_ORACLE` |
| 6 | action legality / betting state | `REPLACE_INTERNAL` |
| 7 | pot + contribution ledger | `KEEP_POKERSENSE` |
| 8 | side-pot handling | `USE_AS_ORACLE` |
| 9 | hand terminal detection | `KEEP_POKERSENSE` |
| 10 | settlement / payout semantics | `WRAP_EXTERNAL` |
| 11 | hand-history serialization | `WRAP_EXTERNAL` |
| 12 | replay / deterministic reproduction | `WRAP_EXTERNAL`（仅手牌层） |
| 13 | range representation | `KEEP_POKERSENSE` |
| 14 | postflop tree building | `DEFER` |
| 15 | CFR / CFR+ / DCFR / Deep CFR | `DEFER` |
| 16 | exploitability / BR / LBR / H2H validation | `USE_AS_ORACLE` |
| 17 | local browser UI / session persistence / reports | `KEEP_POKERSENSE` |

### 1. capture / frame ingestion —— `KEEP_POKERSENSE`

- **现状**：`src/poker_engine/desktop/aa_sources.py::AACaptureSource`（:18）+ `aa_device_lock.py::AACaptureDeviceLock`（:19，设备互斥）+ 主仓库 `tools/aa_record_session.py::main()`；`read()` 2 秒超时，输出 `{image(498×1080 BGR), source_frame, pts_seconds, source_kind}`。
- **上游依据**：无。PokerKit 的输入是**牌面字面量与动作调用**（【读码】`README.rst:69` `state.deal_hole('JsTh')`），OpenSpiel 的输入是游戏参数与动作索引；两者都不接视频。
- **判断**：上游**结构性**不覆盖，且这块正是产品差异化的入口（采集卡/手机投屏归一化）。
- **缺口**：单一采集卡路径；`read()` 超时即抛错无重试（冷启动首帧可达 10.78s，【仓库既有】）。

### 2. visual recognition —— `KEEP_POKERSENSE`

- **现状**：`src/poker_engine/perceptual/vision/*`（card_layout / fused_card_recognizer / gray_amount_recognizer / hero_turn_recognizer / street_detector / action_recognizer …）+ `tools/aa8_candidate_v2.py`；输出 `hero_cards / board_slots / stacks(8 槽) / pot / wagers / actor / dealer_seat / participation / special_modes`。
- **上游依据**：无。所有上游都以「已知牌面」为前提。
- **判断**：这是 PokerSense 的 IP（§4）。
- **注意**：视觉输出被强制盖戳 `candidate_only=True, strategy_eligible=False`（【读码】`aa_reader.py:234-238`）——这个「永不自称合法完整状态」的约束在上游是**不存在**的，别在上游方案里丢掉。

### 3. temporal smoothing —— `KEEP_POKERSENSE`

- **现状**：三层——`realtime/temporal_consensus.py::TemporalConsensus`（N 帧一致才确认）、`desktop/aa_reader.py::AA8Reader.read`（帧号必须 +1、PTS 递增且间隔 ≤1.0s，否则整棵 reset）、`tools/aa8_state_adapter_v2.py::AA8StateAdapterV2`（`pair_window=12` 的前后对窗比较）。
- **上游依据**：PokerKit 的 `Automation`（【读码】`pokerkit/state.py:330`）是**自动化自己的动作**，不是从噪声观测量里做时序确认，名字像但语义完全不同（【推断】不会有人误用，但值得写明）。
- **判断**：上游不适用。

### 4. seat / dealer / actor tracking —— `KEEP_POKERSENSE`

- **现状**：`tools/aa8_dealer_v2.py::AA8DealerReader`、`tools/aa8_actor_ring_v2.py`、`tools/aa8_participation_v2.py::ParticipationReaderV2`、`aa_reader.py::_Tracker`；输出 `dealer_seat`（`dealer_seat_canonical_verified=False`）、`actor`、participation 槽。
- **上游依据（可用于核对「规则」而非「数据」）**：PokerKit 的 `Opening.POSITION`（`state.py:94`）、`Street(...)`（`state.py:189`）、`turn_index`（`:1605`）、`actor_index`；实测中 straddle 之后 `actor_index=3`（§1.2-A）。
- **判断**：**数据**归属视频侧（上游拿不到）；**行动顺序规则**（谁先行动、straddle 如何影响顺序）可以用上游当 oracle 校核我们的 `actor_ring`/`_Tracker` 结论。这一行的建议仍是 `KEEP_POKERSENSE`，因为在校核之前它没有客观实现可换。

### 5. forced-bet / opening reconstruction —— `USE_AS_ORACLE`

- **现状**：`tools/aa8_state_adapter_v2.py::posting_comparison()`，门卫在 **67-68 行 `if len(debits) < 3: return None`**；消费方 `tools/aa8_strategy_state_v2.py::AA8HandLedgerCandidate._reset()`（**77 行类、87 行方法**；105-107 行要求 `status == "MULTI_POST_DEAL_CANDIDATE"` 且 `len(debits) >= 3`）。
- **上游依据**：`AntePosting`（`state.py:510`）、`BlindOrStraddlePosting`（`:540`）、`ante_trimming_status`、`raw_antes` 支持 `{-1: 600}` 形式（`README.rst:56`）、`get_effective_ante`（`:2941`）、`verify_ante_posting`（`:3017`）。**本地实测复现开局底池 17**（§1.2-A）。
- **判断**：**观测**必须自研（上游看不见筹码），但「这个强制投入结构应该产生哪几个座位、各扣多少、总额应是多少」必须由上游**算出来**再和观测对账。本轮已经把该桌的期望向量算出来了（5 座 × 2 + 1 + 2 + 4 = 17）。
- **会触动的模块**：`aa8_state_adapter_v2.py`（新增「期望强制投入向量」对照）、`aa8_strategy_state_v2.py`（把 `>=3 座` 从「唯一通过条件」改为「与期望向量对齐的检查项」）。
- **硬约束**：**不要**为了通过而放宽 `>=3`（【仓库既有】㉔：AA 桌本来就 5 座同时扣款）。真正缺的是**扣款在识别筹码上不可见**——那是观测问题，不是门槛问题。

### 6. action legality / betting state —— `REPLACE_INTERNAL`

- **现状**：**我们真的自己写了一整套**。`src/poker_engine/strategy/state.py::calculate_legal_actions()`（:138-227，含最小加注/全下/跟注语义）、`contracts.py::DecisionContext.legal_action_types`（426 行）、`state_engine/action_reconstruction.py::reconstruct_action_event`（违规返回 INVALID；**92-95 行显式拒绝强制投入** `forced_action_not_supported`）。视觉侧根本没有接通：`desktop/aa_semantics.py` 的 `_interpret`（:50）只给 `PRICE_DERIVED_CANDIDATE`（:151），`legal_action_verified=False`（:59）、`reason="full_history_raise_reopening_and_rules_not_verified"`（:153）。
- **上游依据**：每个操作都有 `can_*` / `verify_*` 一对——`verify_ante_posting`（:3017）/`can_post_ante`（:3039）、`verify_bet_collection`（:3179）/`can_collect_bets`（:3191）等；加注语义 `completion_betting_or_raising_to(amount)`（`README.rst:60-77` 实战示例）；`BettingStructure`（:36）；最小加注规则在 0.7.4 修正（【读码】`CHANGELOG.rst`：*"Min bet/raise amount no longer considers the effective stack"*）。
- **判断**：**这是「停止自研」收益最大的一行。** 我们的规则实现是**第二套**（canonical 一套、视觉侧旁路一套），维护成本双份、且与上游无对照。目标状态：规则事实由 PokerKit 提供，我们的代码只做「把已确认事实翻译成上游调用 + 把上游的拒绝翻译成我们的 UNKNOWN/ABSTAIN」。
- **为什么现在标 `REPLACE_INTERNAL` 而不是立刻动**：本轮**不改**（研究轮红线）。落地顺序见 §5 Phase A，先做差分测试证明等价，再删我们的规则分支。
- **风险**：金额语义差异（我们用 `ActionAmountSemantics.ADDITIONAL|TOTAL_STREET` 两种口径，上游 `cbr amount` 是「加注到」）必须在适配层显式换算，不能隐式。

### 7. pot + contribution ledger —— `KEEP_POKERSENSE`

- **现状**：`tools/aa8_strategy_state_v2.py::AA8HandLedgerCandidate`，状态令牌只有 `HAND_COMMITMENTS_UNKNOWN` / `HAND_COMMITMENTS_SUSPENDED` / `OBSERVED_HAND_COMMITMENTS_CANDIDATE`；逐动作累加 debit 到 8 槽，与读到的 pot 做差并显式标注「差额不等于抽水或费用」（`unallocated_difference`）。
- **上游依据**：PokerKit 有 `total_pot_amount` / `pot_amounts` / `bets`，但**没有等价物**：它的账本是「我知道全部投入，所以我能算」，我们的账本是「我只看到一部分，所以我必须记住哪些看不到」。**上游没有 taint、没有 epoch、没有 SUSPENDED 这类状态**。
- **判断**：这是不确定性账本，不是金额账本（§4）。
- **注意**：这行的产物永远是 `complete_and_canonical_verified=False`，不要把上游的「精确」误当成我们的「精确」。

### 8. side-pot handling —— `USE_AS_ORACLE`

- **现状（纠正一个常见误解）**：**生产代码确实有** —— `src/poker_engine/strategy/state.py::calculate_side_pots()`（55-133 行：分层 tranche、uncalled return、provisional pot、`pot_id="main"/"side-N"`），被 `terminal_multiway_v1.py` 与 `threeway_river_v1.py` 调用。**但** `threeway_river_v1._validate`（第 188 行）**拒绝**存在边池或未跟注款项的输入（`existing_sidepot_or_uncalled_money_unsupported`），且视觉观测层**没有任何边池识别**。
- **上游依据**：`Pot(raked_amount, unraked_amount, player_indices)`（`state.py:438`）、`State.pots`（`:2759`）、`pot_amounts`（`:2509`）；本轮实测 3 人短栈场景得到 `[(60, {p2,p3}), (40, {p2})]` 且守恒精确（§1.2-B）。
- **判断**：保留自研（它是研究内核的一部分，且由不确定输入驱动），但每个已确认的多方手牌都必须与 `State.pots` 对账。**毕业判据**：若差分测试在枚举场景上零分歧，Phase A 可把它降级为上游调用（`REPLACE_INTERNAL`）。

### 9. hand terminal detection —— `KEEP_POKERSENSE`

- **现状**：`desktop/aa_semantics.py::AAObservationSemantics._phase()`（`aa_semantics.py:161` 起）。`closed`（:220-231）= ≥2 家参与且全为 all_in/folded、其中 ≥2 家 all_in、`pending_actions==0`、`current_actor is None`；`terminal`（:232）= closed + 5 张完整合法 river；`ORDINARY_RIVER_CLOSED`（:177-187）= 普通河牌局 + **正的余额增加**结算证据 + 必须等到**下一个 hand epoch 边界**才发一次性事件。
- **上游依据**：上游**不需要检测终局**——它自己驱动整手，`status` 自然变 False（本轮实测：结算后 `status=False`）。所以这一行在语义上不可搬运。
- **判断**：检测必须自研（它是从证据里推断）；但「终局的定义」应当与上游对齐（例如上游在结算后 `pots` 为空、`ChipsPushing/Pulling` 出现两次——这可以作为我们 C2「正结算证据」的对照模板）。
- **代码自述**：`"ORDINARY_RIVER_CLOSED_ONLY; preflop/flop/turn fold-out endings are NOT covered"`（`aa_semantics.py:201-203`）⇒ **真实录像里绝大多数手牌结束在河牌之前，现在一律检测不到**。这是产品侧最高优先级的缺口（§5 T2）。

### 10. settlement / payout semantics —— `WRAP_EXTERNAL`

- **现状**：**没有**生产代码真正计算「谁赢多少」。现有的是：`aa_semantics.py` 里「可见余额增加」的弱证据（`unallocated_positive_cash` :243/:258，语义 `UNALLOCATED_NOT_RAKE_OR_PROFIT` :301，从不分配到人）、离线工具 `tools/verify_aa8_settlement.py::reconcile()`（七人现金对账，非生产路径）、策略侧 `terminal_multiway_v1` 的条件 EV 份额（不是派彩）。
- **上游依据**：`ChipsPushing`（`state.py:654`）、`ChipsPulling`（`:688`）、`HandKilling`（`:646`）、`HoleCardsShowingOrMucking`（`:636`）以及 `push_chips`/`pull_chips`；本轮实测派彩守恒精确（起始 160 → 结束 160，§1.2-B）；PHH 侧可写 `winnings`/`finishing_stacks`（`optional.rst`）。
- **判断**：我们**没有**可替换的实现，上游有通用且正确的实现 ⇒ **直接用上游**，我们只做「把已确认的贡献与亮牌喂进去」。
- **前置条件（硬）**：上游用未知牌会错判（§1.2-D）⇒ 只有在**参与者的牌都已知**（或明确把未知者排除在收益资格之外、并把这个决定记为我们的策略而非上游结论）时才允许调用。

### 11. hand-history serialization —— `WRAP_EXTERNAL`

- **现状**：我们**没有**手牌历史格式。有的是：`desktop/serialize.py::analysis_to_dict/desktop_frame_to_dict`（UI 载荷）与 `desktop/aa_analysis_records.py` 的记录格式 **`aa-analysis-record-v1`**（`record_kind=manual_hypothesis_analysis`，字段 `input/facts/assumptions/support/amounts/report/content_seal`，存 `records/<record_id>/record.json`）——那是**单次河牌分析的冻结快照**，不含动作序列与公共牌时间线。
- **上游依据**：PHH（TOML）规范字段完备（`required.rst`：`variant`/`antes`/`blinds_or_straddles`/`starting_stacks`/`actions`；`optional.rst`：`winnings`/`finishing_stacks`/`seats`/`seat_count`/`players`/`currency`…），PokerKit 提供 `HandHistory.load/loads/dump/dumps/from_game_state/create_state`（【读码】`pokerkit/notation.py:73`），本轮实测往返成功（§1.2-C）。
- **判断**：**采用 PHH 作为「已确认手牌」的规范持久化格式**（这是 H1 的核心回答）。
- **具体缺口与对策**：PHH 装不下我们的 provenance 与抽水参数 ⇒ **PHH 主文件 + 一个 sidecar**（例如 `*.poker-sense.json`：逐字段来源、确认帧、epoch、taint、抽水参数、`input_sha256`）。sidecar 是 PokerSense IP，PHH 是交换层。**不要把 provenance 塞进 `# commentary` 假装结构化**（规范允许注释，但注释不是可校验字段）。
- **会触动的模块**：新增 `aa_hand_input` → PHH 的发射/解析适配（Phase A）；`aa-analysis-record-v1` **保持不变**（它是分析信封，不是手牌格式）。

### 12. replay / deterministic reproduction —— `WRAP_EXTERNAL`（仅手牌层）

- **现状**：**视频/帧层自研且做得好**：`replay/capture_replay.py::CaptureReplay`（逐帧 sha256 + 期望状态断言）、`desktop/aa_sources.py::AADevelopmentSequenceSource`（:160，playlist 全链 sha256 绑定）。
- **上游依据**：PHH → `list(HandHistory)` 逐 action 重放；本轮实测 13 步重放后最终栈与原始**完全相等**（§1.2-C）。
- **判断**：这一行**拆两半**：视频重放 `KEEP_POKERSENSE`（上游给不了）；**手牌级确定性重放走 PHH**（这就是建议标 `WRAP_EXTERNAL` 的范围，写明「仅手牌层」）。
- **为什么这样切**：手牌级重放是我们目前**缺**的能力（我们只能重放帧），而它恰好是「用上游当 oracle」的入口：同一个 PHH 在两边重放，逐街栈/池必须一致。

### 13. range representation —— `KEEP_POKERSENSE`

- **现状**：**不是 169 格**。`src/poker_engine/strategy/aa_range_assets_v2.py::AAConcreteRangeAssetV2` + `configs/strategy/aa-range-asset-v2.schema.json` 用的是**具体组合权重表**：`combo` 正则 `^[2-9TJQKA][cdhs][2-9TJQKA][cdhs]$`（1326 个组合），权重是十进制字符串；节点字段 `node_id/player_count∈{6,7,8}/position/stack_bb/action_line/prior/action_likelihoods{fold,check,call,aggressive,all_in}/confidence/effective_sample_size/evidence`；资产级 `asset_status∈{test_only,simulation_only,shadow_reviewed,live_approved}`、`rule_fingerprint`、`source{url,revision,license_spdx}`、`limitations[]`。
- **上游依据**：PokerKit **没有范围模型**；OpenSpiel 的 `universal_poker` 也不含范围（它是完整信息状态游戏）；GTOpen 线上协议用 **169 向量**（这正是 `gtopen_provider.py:432` 要检查 `len == strategy × 169` 的原因）。
- **判断**：我们的组合级、带置信与证据链的范围**就是 IP**（§4），继续自研；对外的**互操作**需要转换器（169 视图 ↔ 1326 视图），不要为了迁就外部把内部模型降维成 169。

### 14. postflop tree building —— `DEFER`

- **现状**：只有**河牌一棵手工小树**：`strategy/threeway_river_v1.py`（`RiverAction`、`aggression_targets`、`max_aggressions∈[1,3]`，288/293 行递归到 `nodes/terminal_nodes`）。**flop/turn 树不存在**；下注尺度是**人工声明**的网格，不是自动生成的 bet-size grid。
- **上游依据**：TexasSolver（AGPL，C++，CLI/`console_solver`）、`b-inary/postflop-solver`（AGPL，Rust，`TreeConfig{starting_pot, effective_stack, flop/turn/river_bet_sizes}`，**有 bunching effect，官方称支持 6-max**）、GTOpen（**无许可**，README 明示 "postflop solving is heads-up only"）。**三者都是单挑翻后**（【仓库既有】`docs/research-open-source-solvers.md:15-17` 已三路取证）。
- **判断**：`DEFER`。理由：① 没有多人翻后求解器，任何外部树都用不上我们的 3+ 人场景；② 我们的产品路径当前只需要河牌那棵树，且它已存在；③ 引入任何一个外部树都要先确定**集成方式与运行边界**（离线独立进程 / 只借鉴其树构建思路）。**许可状态只界定「能否直接复制或分发源码」（③ 类复用边界），不再作为技术淘汰条件**（OWNER OVERRIDE，§1.1）。
  - ⚠️ 本条理由 ③ 的**旧写法**是「都要先过许可（AGPL 独立进程 / 无许可不可用）」，该写法已被 owner 决策 supersede，**已更正为上面的口径**。
- **触发条件（写死，避免无限 DEFER）**：当出现一个**已确认的**、**单挑**的 flop/turn 决策需求时，先用 `b-inary/postflop-solver` 的 `TreeConfig` 做**离线**参照（独立进程、不进仓库），再决定是否自研通用树。

### 15. CFR / CFR+ / DCFR / Deep CFR —— `DEFER`

- **现状**：**仓库内零 CFR 实现**（grep 只命中 `SyntheticFrameSource` 的子串误报）。`strategy/gtopen_provider.py::GTOpenPreflopProvider` **不是求解器**，是一个 fail-closed 的 loopback HTTP 客户端（`_validate_local_base_url` → `/api/preflop/spot` → 轮询 → 取 169 向量 → 裁成 `StrategyCandidate`，confidence 封顶 0.60）。
- **上游依据**：OpenSpiel 有 CFR/MCCFR 家族与 `universal_poker`（Apache-2.0、C++ 核心、活跃）；PokerRL/Deep-CFR 的评估与训练代码里**多处硬断言只支持 2 人**（5 处 `Only HU supported!` 类断言），且依赖 `torch 0.4.1` / `gym 0.10.9` / `pycrayon`（需 Docker）/ 仅 Linux / PyPI 停留在 2019；PokerRL 只发 `.dll/.so` 无 C++ 源码。
- **判断**：`DEFER`。理由：① 我们的场景是多人；② 现有研究框架的多人支持与依赖形态都不适合桌面产品；③ 求解器常量本轮禁止改动，策略层也没有需要 CFR 才能做的决策。
- **触发条件**：Phase C 启动「策略扩张」时，先评估**自研小规模 DCFR**（仅用于我们自己的抽象博弈）而不是引入外部训练框架；论文层面的算法参考优先 OpenSpiel（Apache-2.0、可读、可审计）。

### 16. exploitability / BR / LBR / H2H validation —— `USE_AS_ORACLE`

- **现状**：**没有任何策略评估器**。最接近的是：`strategy/ev.py::calculate_call_ev/calculate_aggressive_ev`（输出 `ActionEvEstimate{status, ev, components, missing_inputs, assumptions}`，明确标注 `immediate_call_ev_no_future_actions`）、`exploit_fusion.py`（KL 有界的对手调整，**不是**可利用度）、`local_resolver.py`（只**校验**外部上报的 `exploitability_bb100` 阈值）、`threeway_policy_evaluation_v1` 等（冻结策略 × 人工世界网格的确定性评估，自称 "never empirical approval"）。
- **上游依据**：PokerRL 给出了**可零依赖提取的 BR 递归**（`game/_/tree/_/ValueFiller.py:21-101`：机会节点求和 → 对手节点按 σ 加权（:87）→ 自己节点 `np.max`（:91）→ `epsilon = ev_br_weighted − ev_weighted`（:100）→ `exploitability = Σ_h epsilon`（:101），约 40 行，仅依赖 numpy）；OpenSpiel 提供现成的 `exploitability` 实现（Apache-2.0）可用来**校准我们自己的实现**。
- **判断**：**方法论抄上游、实现自己写、用上游校准**。河牌没有后续街，infoset 只需（自己两张牌、公共牌、行动序列），showdown 可精确枚举 ⇒ 河牌 3 人的 BR 上界是可算的，**不需要 CFR 遍历器**。
- **落地方式**：① 用 OpenSpiel 在一个**完全同构的极小游戏**（Kuhn/Leduc，以及一个 HU 河牌玩具）上跑 `exploitability`，把我们 40 行实现的结果对齐到它；② 对齐后才允许用它评估我们的河牌子博弈。**不允许**直接把 PokerRL 的 `LocalBRMaster` 当产品依赖（HU 断言 + Linux + 二进制扩展）。

### 17. local browser UI / session persistence / reports —— `KEEP_POKERSENSE`

- **现状**：`ui/aa-live/{index.html,app.js,controls.js,analysis.js,review.js,study.js,hand_input.js,analysis_records.js}` + `ui/aa-replay/`；服务端 `desktop/aa_server.py::create_app`（FastAPI，30+ 路由，含 `/api/hand-input/*`、`/api/analysis/records*`、`/api/review/*`）；状态目录 `launch/u2-trial/state/`（`profile.json` + `records/`）。
- **上游依据**：GTOpen 有自己的 HTTP 服务（:3737）与 session/report 模型，但它是**求解器 UI**；PHH/PokerKit 无 UI。
- **判断**：产品 UX 是 IP。**可借鉴的只是文件/结构层面的具体做法**（例如 GTOpen 的 session 单例 + 报告快照的组织方式）——这属于 **① 类架构借鉴，无阻塞**。GTOpen 无明确 license 这一**事实不变**，但它界定的是 **③ 类「直接复制源码进产品」的边界**（当前不做；若未来项目用途改变再单独复核），**不是**「能否借鉴其组织方式」。

---

## 3. Stop Building These Ourselves

> 判据：**上游已有、且正确性比我们更容易被证明**的东西。

1. **NLHE 下注合法性规则（最小加注、短全下重开、跟注额、全下边界）** —— 现在 `strategy/state.py::calculate_legal_actions`（138-227 行）与视觉侧旁路是两套。改用 PokerKit 的 `can_*`/`verify_*`（`state.py:3017+` 每个 Operation 一对），我们的代码只保留「已确认事实 → 上游调用」的翻译与 fail-closed 映射。
2. **强制投入的会计（谁下盲注、谁下 ante、谁 straddle、总额应为多少）** —— 现在这一层被并进「≥3 座现金下降」的观测判断里。改为由 PokerKit 算出**期望向量**（本轮已算出本桌 = 5×2+1+2+4 = 17），观测只负责核对「哪几座看不到」。
3. **边池切分与派彩** —— `strategy/state.py::calculate_side_pots`（55-133 行）可以保留到差分测试通过为止，但**新的派彩计算不要再写第三套**：用 `State.pots` + `push_chips`/`pull_chips`。
4. **手牌历史格式** —— 不要再设计自己的手牌 JSON。PHH 是可交换、可校验、有引用的标准（`required.rst`/`optional.rst`），PokerKit 已经实现了双向读写。
5. **手牌级确定性重放** —— 不要再写「用我们的记录格式回放动作序列」的第二种实现；`list(HandHistory)` 就是。
6. **牌型比较/摊牌胜负（在牌都已知时）** —— `StandardHighHand.from_game(hole, board)` / `analysis.py`。**但注意**：牌有未知时**绝不许**调用（§1.2-D 会静默判负）。
7. **BR / exploitability 的算法定义** —— 不要凭想象设计一套评估口径；直接用 PokerRL `ValueFiller.py:21-101` 的定义并拿 OpenSpiel 校准。

**明确「不要接」的**（尽管名字听起来很对口）：

| 项目 | 为什么不要接 |
| --- | --- |
| `datamllab/rlcard` | 相对 OpenSpiel/PokerKit **没有增量价值**：它是 RL 训练脚手架 + 自己的牌型评估，我们要的规则/序列化/评估三件事它都不比 OpenSpiel/PokerKit 强，且（【推断】）维护节奏落后于两者。 |
| `EricSteinberger/PokerRL` | 评估/BR/H2H **全部硬断言 2 人**（5 处），依赖 `gym==0.10.9`/`pycrayon`(Docker)/`ray 0.6.1`，仅 Linux，PyPI 停在 2019，且**只发 `.dll/.so` 无 C++ 源码**（不可审计不可重建）。 |
| `EricSteinberger/Deep-CFR` | 同上：是 PokerRL 的插件而非独立库，官方仅支持 Linux；H2H 脚本自述单次导出 ~15GB，需 24 核；明确定位 "designed for Researchers"。 |
| ~~`MatthewPDingle/GTOpen`~~ | ⚠️ **本行已被 OWNER OVERRIDE 修订（§1.1），不再是「不要接」。** 重新分类为**重点研究 / 本地复用候选**（solver workflow、Rust engine、preflop lab、reports、player model/evidence 设计）。**保留的事实边界**：仓库无明确 license（③ 类直接复制源码需单独评估）、翻后仅单挑、多人翻前 solver 本机 7/8 人实测 92-499 秒且未收敛（【仓库既有】）——**这些是范围与复用边界，不是技术淘汰**。 |
| `bupticybee/TexasSolver`（作为代码依赖） | AGPL：可以当**独立进程**参照，但**不能**把源码/二进制并进产品，不能静态链接。既有边界继续有效。**OWNER OVERRIDE**：AGPL 只界定 **③ 类「源码/二进制能否进产品、能否静态链接」** 的复用与分发边界，**不再**据此判定「技术上不可用」；作为**离线独立进程 oracle / 源码学习候选**是允许的。 |
| 已归档/烂尾候选（`DEEPFOLD-SOLVER` 之类） | 既有调研已淘汰（"All rights reserved" 伪装开源），本轮不重开。 |

---

## 4. Keep as PokerSense IP

**这一节是本轮最重要的产出**：它划定了「即使采用 PHH/PokerKit，也永远不能被上游替代」的部分。

1. **不确定性域（uncertainty domain）** —— 我们的账本里有 `UNKNOWN` / `SUSPENDED` / `taint_reasons`，我们的相位里有 `OBSERVING` / `WAITING_OPENING` / `POT_CLEAR_PENDING`；上游**没有**这个概念，而且会把未知**当成已知处理**（§1.2-D）。这就是为什么 H1 只能「喂已确认事实」。
2. **溯源与确认身份（provenance）** —— 逐字段来源、确认帧、「这个数字是人工核对的还是识别推断的」。PHH 装不下（§1.4），注释通道不是可校验字段。
3. **`input_sha256` 身份守恒** —— `aa_hand_input.facts_hashes()["input_sha256"] == report.input_sha256` 逐字节相等；再加上 `aa-analysis-record-v1` 的 `content_seal`。这是「结果绑定到人工核对过的输入」的唯一凭据，上游没有类似物。
4. **视觉层与采集归一化** —— 模板/字形/采集卡/手机投屏，以及「永不自称完整合法状态」的盖戳纪律（`candidate_only=True, strategy_eligible=False`）。
5. **时序证据融合** —— 连续帧确认、帧号/PTS 连续性门、丢帧即整棵 reset、前后对窗比对。上游的 `Automation` 不是这件事。
6. **从证据推断终局** —— `ORDINARY_RIVER_CLOSED` 的三条件（河牌完成 + **正**结算证据 + 新 epoch 确认）。上游不需要检测终局，因此永远不会提供这个能力。
7. **组合级范围 + 证据链范围资产** —— 1326 组合权重、置信、样本量、`asset_status` 阶梯、`rule_fingerprint`。
8. **产品 UX 与「军师不代打」定位** —— 只给建议、绝不自动操作；离线研究面板与「不可用于实时建议」的显式声明。
9. **可回放的证据链** —— 逐帧 sha256 钉死 + playlist/audit 哈希 + `replay_id`。

---

## 5. 90 天架构建议（三阶段）

### Phase A（第 0-4 周）· 规范的真实手牌表示 + 重放/校验

**目标**：把「一手已确认的真实牌局」变成可交换、可重放、可被独立裁判的资产。

- **A1**：新增 **PHH 适配**（发射 + 解析），只接受**已确认事实**；每字段的来源/帧号写 sidecar。产物：`<hand>.phh` + `<hand>.poker-sense.json`。
- **A2**：**PokerKit oracle 校验闸**（fail-closed）：把 A1 的 PHH 喂给 PokerKit，逐街核验 ① 动作合法性（`can_*`/`verify_*`）② 每街栈与池的守恒 ③ 强制投入向量 == 期望向量（本桌 17）④ 终局与派彩（`pots`/`push`/`pull`）与我们记录的结算证据是否一致。**任何一条不一致 ⇒ 该手标记 INVALID，不得进入策略路径。**
- **A3**：差分测试：`calculate_legal_actions` / `calculate_side_pots` vs PokerKit，枚举足够多的局面（含短全下、多头、uncalled 退还）。**零分歧**才允许进入 A4。
- **A4**（可选，需鹏哥批）：把规则分支从我们的 canonical 层删掉，改为调用上游；我们的代码正式降级为 adapter/evidence。

**Phase A 的验收物**：第一手**真实牌局**的 PHH + sidecar + 双方重放一致报告 + 差分测试结果。这也是 `REAL_HAND_ACCEPTANCE_PENDING` 转正的唯一路径。

### Phase B（第 5-8 周）· 策略 oracle 交叉校验

- **B1**：实现（自研，~40 行级别）河牌子博弈的 **BR 上界**；先用 OpenSpiel 在 Kuhn/Leduc + 一个 HU 河牌同构玩具上校准到一致。
- **B2**：在**最小可比子博弈**上做三方对照：我们 `threeway_river_v1` 的 EV/动作频率 vs 外部求解器（`b-inary/postflop-solver` 或 TexasSolver，独立进程、离线）。**明确列出无效比较的情形**（见 §7 H2）。
- **B3**：把「对手 σ 的来源」写清楚——没有外部对手策略输入时，BR/exploitability 只是自洽性检查，不是可利用度（PokerRL `ValueFiller.fill_with_agent_policy` 的教训）。

### Phase C（第 9-12 周）· 策略扩张（仅在 A/B 有结论后启动）

- **C1**：把覆盖从「河牌 3 人」扩到**转牌**（先做离线预计算资产，沿用 `aa-range-assets-v2` 的资产阶梯与 `rule_fingerprint`）。
- **C2**：评估**自研小规模 DCFR**（仅用于我们自己的抽象）vs 引入 OpenSpiel 的取舍；论文/算法参考走 OpenSpiel，不引入 PokerRL 训练栈。
- **C3**：终局覆盖补齐（翻前/翻牌/转牌弃牌结束）——这其实是我们自己的缺口，不是开源问题（见 T2）。

---

## 6. 迁移风险表

| 维度 | PokerKit / PHH | 评估 | 缓解 |
| --- | --- | --- | --- |
| **许可** | MIT（两个项目） | 🟢 无阻塞 | 仍需在 `docs/` 记录 SPDX + 版本 |
| **语言边界** | 纯 Python（`python_requires>=3.11`，无运行时依赖） | 🟢 与产品同栈 | 产品 `requires-python>=3.11,<3.14`，本机运行时 3.13.14 已验证兼容（【实测】PoC 在 3.13 上跑通） |
| **性能** | 状态推进是纯 Python；oracle 只用于**每手一次**的校验，不进实时帧循环 | 🟢 可接受 | 明确：**禁止**把上游调用放进逐帧路径（`AA8Reader.read` 链路） |
| **Windows 支持** | 纯 Python，无平台特定代码 | 🟢 未发现障碍 | 【推断】无 CI Windows 证据；本地 PoC 已在 Windows 3.13 跑通，落地时补一条 Windows 回归 |
| **维护活跃度** | PokerKit 2026-08-22 推送、0.7.5、99% 覆盖率（自述）；PHH-std 最近 2025-05-08 但规范已冻结 | 🟢 活跃 | 固定版本；PHH 是规范不是库，冻结反而是优点 |
| **多人限制** | PokerKit 无人数上限（`player_count<2` 才报错）；实测 3/5 人正常 | 🟢 | 仍需测 8 人 + straddle 的完整组合（本轮只测了 5 座） |
| **Schema 不匹配** | PHH **无抽水字段**、**无 provenance 字段**、无「每座位已发牌」概念 | 🔴 真实缺口 | sidecar 承载；抽水只体现在 `winnings`（post-rake） |
| **未知信息语义** | 上游**静默误判**未知（判负 / `KeyError`） | 🔴 **最高风险** | 架构上禁止把未知喂给上游；oracle 闸口只接受「已确认」输入，未知走我们的 UNKNOWN 路径 |
| **测试策略** | 需要三套新测试：PHH 往返、差分（我们的规则 vs 上游）、oracle 闸的 fail-closed | 🟡 工作量 | 全部用**已有**的帧级夹具（`opening_rows_1260_1290_v1.json` 这类「adapter 之前」的行），CI 不依赖 `G:` |

**其他项目的风险（用于「集成方式与运行边界」决策，不再用于技术淘汰；OWNER OVERRIDE，§1.1）**：OpenSpiel = C++ 核心 + 需构建（Apache-2.0，活跃）⇒ 只作为**后期**评估框架；TexasSolver = AGPL ⇒ **离线独立进程 oracle / 源码学习候选**（AGPL 只限 ③ 类复用）；GTOpen = **无明确 license** ⇒ **技术研究 / PoC / oracle 候选**，直接复制或分发源码需单独评估（**不是**「不可用」）；PokerRL/Deep-CFR = Linux + 老旧依赖 + 二进制不可审计 ⇒ 方法论。**第一筛选标准已改为「能否减少自研弯路 / 能否提供可验证能力」，不再是许可状态。**

---

## 7. 两个假设的裁定

### H1 —— PokerKit/PHH 应当成为参考规则层 + 手牌历史层？**成立，但带一个硬前置。**

**成立的部分（证据）**：
- 强制投入结构可**逐字节复现**录像事实 17，且能表达「按已发牌座位下 ante」与「强制 straddle」（§1.2-A）。
- 边池是**一等公民**（`Pot.player_indices`），派彩守恒精确（§1.2-B）。
- PHH 是可双向读写的标准，且**规范明确允许不完整手牌**与未知牌/未知筹码（§1.3）。
- 纯 Python、MIT、无人数上限、0.7.5 在 Python 3.13 上跑通（§1.2）。

**前置（不可协商）**：
- **不确定的视觉候选永远不得变更 canonical 状态，也不得喂给上游做裁决。** 因为上游对未知的处理是静默错的：`can_win_now` 返回 `False`、`StandardHighHand.from_game('??Ad', …)` 抛 `KeyError(Rank.UNKNOWN)`（§1.2-D）。
- 因此 H1 的正确形态是：**「已确认事实 → PHH/PokerKit」+「未确认事实 → 我们的 UNKNOWN 域」**，两者在接口上分离，而不是把候选塞进一个「差不多完整」的状态里。

**哪些现有状态机代码会从「规则代码」降级为「适配/证据代码」**：
`strategy/state.py::calculate_legal_actions`（规则）、`strategy/state.py::calculate_side_pots`（结算规则）、`state_engine/action_reconstruction.py::reconstruct_action_event`（事后合法性重建）、`tools/aa8_state_adapter_v2.py::posting_comparison`（强制投入会计）。它们的**证据职能保留**（谁看到的、哪一帧看到的、缺什么），**规则职能交出**。

### H2 —— 外部求解器应当「验证」而不是「替代」我们的近期路径？**成立，且只有很小的可比窗口。**

- **可比较的唯一窗口**：**河牌、单挑（或可降为单挑的两方残局）、离散下注尺度、无抽水差异**。此时双方都在完全信息子树上求解，EV 与动作频率才可对照。
- **明确列出的无效比较**（任何一条成立就不许比）：
  1. **人数**：我们 ≥3 活跃 vs 外部只有单挑（GTOpen 明示 postflop HU only；postflop-solver/TexasSolver 亦然）。3 人以上的"对照"是把不同博弈的均衡混在一起，无效。
  2. **范围模型**：我们的范围是**具体组合权重 + 人工响应权重**（`aa-range-asset-v2`，`manual_river_start_ranges_and_response_weights_not_observed_or_GTO`），外部是自洽的初始范围假设。范围不同 ⇒ 频率差异不能归因于求解质量。
  3. **抽水**：我们有 `rake_percent` + `cap_bb`（且 `rake_cap_bb=0` 会吃掉整段抽水，【仓库既有】⑱）；外部求解器多数不建模抽水，或口径不同。
  4. **下注抽象**：我们的 `aggression_targets` 是**人工声明**的网格（`threeway_river_v1` 189-194 行）；外部是自动生成的抽象树。抽象不同 ⇒ 均衡不同。
  5. **博弈树范围**：我们只解河牌；外部若解到 flop，树包含后续街 ⇒ 对方的"河牌策略"是子博弈完美策略，我们的不是。
  6. **全下与边池**：`threeway_river_v1` 明确拒绝全下与边池输入（195-197 行）⇒ 这两类局面没有可对照的自研输出。
- **结论**：外部求解器在本项目里的角色是**「在我们能力范围内的最小区间上做定点抽检」**，不是策略来源。**不要**用它的多人翻前输出去改我们的翻前资产（GTOpen 本机实测在 7/8 人桌未收敛且两个 realization 结论互相矛盾）。

---

## 8. 验收问题逐条回答

**Q1. PokerSense 应当采用 PHH 作为 canonical 持久化手牌格式吗？为什么？**
**应当**，但**只手牌**，且必须带 sidecar。【规范】PHH 明确支持不完整手牌（`required.rst:178`）与未知牌/筹码（`??`/`inf`）；【实测】PokerKit 往返重放后栈完全一致。理由：① 我们**没有**手牌格式（现有的是单次分析快照 `aa-analysis-record-v1`）；② PHH 有规范、有参考实现、有校验工具；③ 未知信息有官方写法，不必自创。**为什么不能只有 PHH**：它没有 provenance、没有抽水字段 ⇒ sidecar 承载「来源/确认帧/taint/抽水参数/`input_sha256`」。

**Q2. PokerKit 应当成为规则/状态 oracle 吗？具体承担哪些职责？**
**应当**，职责限定为四项：① 每一个 Operation 的**合法性**（`can_*`/`verify_*`）；② **强制投入的期望向量**（ante/blind/straddle 的会计）；③ **底池与边池的切分**（`pots`）；④ **结算与派彩**（`push_chips`/`pull_chips`/`winnings`）。**不承担**：视觉识别、时序确认、不确定性账本、终局检测、溯源。**入口约束**：只在「已确认事实」上调用，且只在每手一次的校验路径上调用（不进逐帧路径）。

**Q3. 哪些现有状态机代码会从「规则代码」变成「适配/证据代码」？**
`strategy/state.py::calculate_legal_actions`（138-227 行）、`strategy/state.py::calculate_side_pots`（55-133 行）、`state_engine/action_reconstruction.py::reconstruct_action_event`、`tools/aa8_state_adapter_v2.py::posting_comparison`、`tools/aa8_strategy_state_v2.py::AA8HandLedgerCandidate._reset` 的「≥3 座」判据。它们保留「我看到了什么/缺什么」的证据职能，交出「什么合法/该谁付多少」的规则职能。

**Q4. 第一个独立参照，用于单挑河牌/转牌验证的求解器该选谁？**
**`b-inary/postflop-solver`（Rust，AGPL-3.0）**，理由是它是**唯一实现 bunching effect** 的（官方称支持到 6-max 的折叠影响），河牌级性能足够；作为**离线独立进程**使用（AGPL 边界）。**次选** `bupticybee/TexasSolver`（预编译 Windows 二进制 + CLI 最省事，AGPL，同样单挑翻后）。**注意**：这一条是既有调研的结论（`docs/research-open-source-solvers.md`），本轮把它**重新带回**——因为下一轮任务清单里点名了 TexasSolver/GTOpen 却漏掉了这个当前首选。转牌在 `b-inary/postflop-solver` 上需实测（【推断】可接受但未测）。

**Q5. 后期做 exploitability/BR 式评估该用什么框架？**
**方法论来自 PokerRL（MIT）的 `ValueFiller.py:21-101`，校准来自 OpenSpiel（Apache-2.0）的 `exploitability`**，实现自己写（河牌无后续街 ⇒ 不需要 CFR 遍历器）。**不用** PokerRL 作为依赖（5 处 HU 硬断言、Linux-only、仅二进制扩展、PyPI 停在 2019）。

**Q6. 哪些开源项目虽然听起来相关但**不**合适？**
`PokerRL` / `Deep-CFR`（**技术原因**：HU-only 硬断言 + Linux-only + 老依赖 + 无 C++ 源码；研究代码自述 "INEFFICIENT and SLOW"——**不是**许可原因）、`rlcard`（**技术原因**：相对 OpenSpiel/PokerKit 无增量）、以及既有已淘汰的 `DEEPFOLD-SOLVER`（"All rights reserved" 伪装开源）之类。
**以下两项按 OWNER OVERRIDE（§1.1）重新分类，不再是「不合适」**：
- **`MatthewPDingle/GTOpen`** → **技术研究 / 本地复用候选**（solver workflow、Rust engine、preflop lab、reports、player model/evidence 设计）。保留事实边界：无明确 license（③ 类直接复制/分发需单独评估）、翻后仅 HU、本机多人实测未收敛（7/8 人 92-499 秒且两个 realization 相互矛盾）。
- **`bupticybee/TexasSolver`** → **技术参考 / oracle 候选**（离线独立进程）。AGPL 只界定 ③ 类「源码/二进制不进产品、不静态链接」的复用边界；**不因 AGPL 判为技术不可用**。

**Q7. 本轮之后优先级最高的 3 个工程任务？**
见 §9。

---

## 9. 本轮之后的 3 个工程任务（优先级序）

**T1 · PHH ↔ PokerSense 双向适配 + PokerKit oracle 闸（fail-closed）**
把「已确认手牌」发射成 PHH + provenance sidecar，并在读回时用 PokerKit 核验合法性/守恒/强制投入向量/派彩；不一致即 INVALID。这是 Phase A 的全部内容，也是把 `REAL_HAND_ACCEPTANCE_PENDING` 转正的**唯一路径**。
*交付判据*：第一手**真实牌局**通过闸门，且「我方的记录」与「PHH 重放」逐街栈池一致。

**T2 · 补齐终局覆盖：翻前 / 翻牌 / 转牌弃牌结束**
`aa_semantics.py:216-218` 自己声明不覆盖。真实录像里**绝大多数**手牌不走到河牌 ⇒ 现在即使把 ⑳/㉔ 的观测问题解决了，能确认的手牌也寥寥无几。这是**产品侧**最高价值的缺口，且与开源无关（上游不提供终局检测）。
*交付判据*：在已有录像上能确认出「翻前结束」与「转牌结束」两类手牌，且各自的结算证据与 PokerKit 的对应终局语义一致。

**T3 · 把强制投入从「观测阈值」改成「期望向量 + 缺失清单」**
用 PokerKit 算出本桌的期望强制投入向量（本轮已验证 = 5×2+1+2+4 = 17，且 `actor_index=3` 与观测一致），让 `posting_comparison` 输出「哪几座能看到、哪几座看不到」，而不是在 `len(debits)<3` 时整体返回 `None`。
*交付判据*：本录像的三个开局窗口都能产出结构化的「缺失座位清单」，且**不放松** `UNKNOWN`、**不降低** `>=3` 门槛（门槛在 AA 桌本来就满足，缺的是可见性）。

> 备注（不排进前三）：把 `calculate_legal_actions` / `calculate_side_pots` 换成上游调用（A3/A4 差分测试之后）；以及 Phase B 的 BR 校准。

---

## 10. 未完成、边界与待裁决

**本轮明确没做的事**：
- **没有改任何产品代码**（`git status` 干净；唯一新增文件是本文件）。
- **没有给产品加依赖**（PokerKit 只装在隔离 venv `C:\Users\Administrator\.workbuddy\tmp-oss\venv-oss`）。
- **没有**改求解器常量、没有重训视觉、没有改 PR #28 行为、没有合并、没有强推。
- **没有**改 `REAL_HAND_ACCEPTANCE_PENDING` 与 `NOT_ASSESSED` 的取值。

**验证盲区（诚实列出）**：
1. PoC 只覆盖 3 人与 5 人；**8 人 + straddle + 部分座位 ante** 的完整组合**未测**。
2. PHH 对**抽水**的表达只有 `winnings`（post-rake）；我们的 `rake_percent`/`cap_bb` 如何落到 PHH 未验证（sidecar 方案是【推断】可行）。
3. 上游在 Windows 的 CI 证据未找到（PoC 跑通不等于有回归保障）。
4. `b-inary/postflop-solver` 的转牌性能**未实测**（既有调研只有河牌结论）。
5. OpenSpiel 的 `universal_poker` 是否能承载我们的**抽象**下注网格，本轮**未实测**（只读了参数与评测代码结构）。
6. 既有调研提到的 `docs/research-amaster97-poker-solver.md`（HU 蓝图）与 `blueprint_provider` 的实际资产存在性未核。

**需要鹏哥裁决的三项**（沿用上一轮未决项，本轮不擅自决定）：
1. **历史 bundle 对照**：是否允许把昨天的 bundle/profile 与今天逐字节对照以定位识别差异？
2. **比较锚点与窗口**：开局比较的锚点帧与窗口宽度是否改（现为 dealer 前移帧 + 4 帧补救窗口）？
3. **是否新增并列普通终局条件**：除 `ORDINARY_RIVER_CLOSED` 之外，是否补「翻前/翻牌/转牌弃牌结束」（即 T2 是否立项）？

**另外一项新的待裁决**：是否允许 Phase A 之后**删除**我们自己的规则实现（`calculate_legal_actions` / `calculate_side_pots`），把它们彻底交给 PokerKit？本轮只给建议（`REPLACE_INTERNAL`），**未动代码**。

---

## 附录 A · 本轮实际读过/运行过的上游文件

**本地浅克隆（只读，临时目录，不进仓库）**
- `C:\Users\Administrator\.workbuddy\tmp-oss\pokerkit`（`uoftcprg/pokerkit`）：`LICENSE`、`README.rst`、`CHANGELOG.rst`、`setup.py`、`requirements.txt`、`pokerkit/{state,notation,games,hands,analysis,lookups,utilities}.py`
- `C:\Users\Administrator\.workbuddy\tmp-oss\phh-std`（`uoftcprg/phh-std`）：`LICENSE`、`required.rst`、`optional.rst`、`spec.rst`、`validation.rst`、`tooling.rst`
- `C:\Users\Administrator\.workbuddy\tmp-oss\{GTOpen,TexasSolver,rlcard,PokerRL,Deep-CFR}`（浅克隆/按需抓取）

**逐项关键符号（已在本文件正文中引用）**
- PokerKit：`pokerkit/state.py` 的 `BettingStructure:36`、`Opening:94`、`Street:189`、`Automation:330`、`Mode:414`、`Pot:438`、`Operation:497`、`AntePosting:510`、`BlindOrStraddlePosting:540`、`ChipsPushing:654`、`ChipsPulling:688`、`HoleCardsShowingOrMucking:636`、`HandKilling:646`、`State:705`、`turn_index:1605`、`pot_amounts:2509`、`pots:2759`、`get_effective_ante:2941`、`verify_ante_posting:3017`、`can_post_ante:3039`、`verify_bet_collection:3179`、`can_collect_bets:3191`；`pokerkit/notation.py` 的 `HandHistory:73`、`PokerStarsParser:2464`、`ACPCProtocolParser:2564`；`HandHistory.{load,loads,dump,dumps,from_game_state,create_state}`
- PHH 规范：`required.rst:149,178,210,240,266,276,279`；`optional.rst:34,165,170,185`
- 元数据：`gh api repos/<r>`（许可/语言/推送/星标/归档）逐仓库核对（§1.1 表）

**PoC（临时，未进仓库）**
- `poc_h1_table.py` sha256 `8b13b12c8bacc7c78f4f64136b2e7974a5d298791d6c16a8c5e11ef8fb6837f3`
- `poc_h1_output.txt` sha256 `392cd5e6db9917fe8246e110983259c58e784e0426833fb8a3110099f9805832`
- `pokerkit==0.7.5`（PyPI），Python 3.13.14

## 附录 B · 与既有调研的关系（避免重复与冲突）

| 既有文档 | 既有结论 | 本轮的关系 |
| --- | --- | --- |
| `docs/tech-stack-matrix.md`（2026-08-19） | PokerKit 列为**候选**（MIT、纯 Python、99% 覆盖），用途候选「接管规则正确性」 | **本轮把候选变成结论**：给出可执行的接管路径、差分测试要求与风险（未知信息误判）。 |
| `docs/research-open-source-solvers.md`（2026-09-06） | 不存在开源多人翻后求解器；首选 `b-inary/postflop-solver`（AGPL、有 bunching）；AGPL 隔离边界 | **本轮复核成立**，并把「被下一轮任务清单漏掉的首选」重新带回（Q4）。 |
| `docs/research-multiplayer-preflop-assets.md`（2026-09-06） | GTOpen：**无 LICENSE**、Windows 可构建、7/8 人翻前实测 92-499s 且未收敛、翻后仅 HU | **本轮复核不变**（`gh api …/license` 仍为空）——该**事实继续保留**；但自 2026-09-18 OWNER OVERRIDE（§1.1）起**不再**据此把它判为技术不可用：§3 中该行已改为「重点研究 / 本地复用候选」，H2 的无效比较清单（HU-only、多人翻前未收敛）**仍然成立**（那是范围边界，不是许可淘汰）。 |
| `docs/AA-MULTIWAY-STRATEGY-RESEARCH-20260913.zh-CN.md` | 多人 GTO 的可行性与边界；「研究、数学模块与条件分析入口已交付，多人 GTO/学习后范围/一般下注策略/盈利验收没有被宣称完成」 | 本轮的 §5 Phase B/C 与该结论一致：**不宣称**任何多人 GTO 能力。 |

**本轮新增（既有文档没有的）**：PHH/PHH-std 的评估与「采用为 canonical 手牌格式」的结论；PokerKit 对**未知信息的静默误判**这一硬风险；AA 桌强制投入结构在 PokerKit 上的**可执行复现**（17）。
