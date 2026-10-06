# USABLE-001 · 第一次人工离线试用准备（启动入口 / 版本 / 真实样本缺口）

run_id `USABLE-001-FIRST-TRIAL-20260917T0330Z` · 版本对应 **`c9936329f35002ca9b30175200a9f720df118ed0`**
（U2 `PASS_WITH_SCOPE`，审查 `pullrequestreview-5227367145`）· 分支 `codex/usable-001-hand-review` · Draft PR #28。
本轮**只做试用准备**：U2 功能冻结、不扩功能、不重做 U2、不合并发布；真实样本 `REAL_HAND_ACCEPTANCE_PENDING`
与策略强度 `NOT_ASSESSED` 保持。

## 0. 一句话结论

独立启动入口是 `launch/u2-trial/START-TRIAL.cmd`（版本 **`aa-trial-u2.0`**，记录实现 **`aa-analysis-record-v1`**，
`c993632` 的代码），双击即可，**不碰你已有的程序、配置和记录**；
授权的结构化材料里**没有**一手满足当前内核前提的真实牌局（沿用已有选样结论，本轮未重搜），
需要你亲自确认的只是下面 §4 那一份清单。

## 1. 启动入口（对应 `c993632`）

| 项 | 值 |
| --- | --- |
| 双击入口 | `G:\PokerSense_worktrees\usable-001-hand-review\launch\u2-trial\START-TRIAL.cmd` |
| 命令行入口 | `python launch\u2-trial\trial_launcher.py`（在 `G:\PokerSense_worktrees\usable-001-hand-review` 下执行） |
| 试用版本 | **`aa-trial-u2.0`** |
| 记录实现版本 | **`aa-analysis-record-v1`** |
| 代码版本 | 该 worktree 的 `HEAD` = `c9936329f35002ca9b30175200a9f720df118ed0`（工作树干净） |
| 首选端口 | **8791**（被占用时报告并改用明确空闲端口，**不结束任何进程**） |
| 页面地址 | 启动后自动打开 `http://127.0.0.1:8791/` |
| 试用状态目录 | `G:\PokerSense_worktrees\usable-001-hand-review\launch\u2-trial\state\`（配置、桌规、已保存分析都在这里） |

**与你既有程序的关系**：主仓库 `C:\Users\Administrator\WorkBuddy\扑克\PokerSense\` 里**没有** `launch\` 目录，
本入口只存在于试用 worktree；它用项目已在本机使用的 Python，不装依赖、不改全局环境或代理、
**不读取也不覆盖** `%LOCALAPPDATA%` 里的程序、桌面快捷方式和你自己的规则/记录。

### 1.1 本轮实跑确认（不是照抄文档）

| 检查 | 结果 |
| --- | --- |
| `trial_launcher.py --version` | `aa-trial-u2.0 (aa-analysis-record-v1)` |
| `trial_launcher.py --self-check` | `missing_resources: []`、`preferred_port: 8791`、`port: 8791`、`port_note: null`、`capture_enabled: false` |
| 实跑启动（`--no-browser` + 就绪文件） | 就绪文件写出 `base=http://127.0.0.1:8791/`，`version=aa-trial-u2.0` |
| `GET /` | **200**，17,473 字节；页面含「本桌规则」「录入一手已结束牌局」「多人河牌条件分析」「保存本次分析并重开」「手工假设 · 非实时建议」 |
| `GET /api/status` | **200**；`strategy_scope=AA8_OBSERVATION_ONLY_NO_ADVICE`；`table_rules.conditional_analysis_ready=false`（新试用目录还没有桌规） |
| `GET /api/analysis/records`、`/api/hand-input/template` | 均 **200** |
| 启动横幅 | 打印版本、地址、试用状态目录、以及**逐条未验收项** |

### 1.2 页面版本怎么认

页面**没有**屏幕上的版本徽标（本轮不新增功能）。可核对的版本标识有四处，任取其一即可对上：

1. 启动时窗口里的横幅第一行：`=== PokerSense 离线试用 aa-trial-u2.0（记录实现 aa-analysis-record-v1）===`；
2. 页面里四条面板标题齐全，且分析面板带 `手工假设 · 非实时建议` 标签；
3. 每条已保存分析在详情里标注自己的**记录实现版本**（当前为 `aa-analysis-record-v1`）；
4. 启动横幅里的试用状态目录路径（上面的 §1 表格第 7 行）。

> 如果你希望页面上直接显示「版本 + 提交号」，那是一次小的界面改动，本轮按范围**没有**做，可在下一次明确授权后单独加。

## 2. 你在电脑上最简单的打开方式

1. 打开资源管理器，进入 `G:\PokerSense_worktrees\usable-001-hand-review\launch\u2-trial\`；
2. **双击 `START-TRIAL.cmd`**（一个黑窗口会打印版本与未验收项，然后自动打开浏览器）；
3. 浏览器里就是试用页面：`http://127.0.0.1:8791/`；
4. **第一次必须先做**：在「设置与分析 → 本桌规则」填齐并**保存**桌规（新试用目录里桌规是空的，
   页面上的 `conditional_analysis_ready` 此刻为 false，录入区会因此拒绝核对）；
5. 之后按页面从上到下走：保存桌规 → 录入一手已结束牌局 → 核对输入 → 计算条件收益 → 保存本次分析；
6. 关掉那个黑窗口（或按 Ctrl+C）即退出；记录留在 `launch\u2-trial\state\records\`，下次启动仍在。

排障：黑窗口出现「Local Python not found」时，说明脚本里的本机 Python 路径变了——把 `PYTHON_BIN`
设成你项目在用的解释器再双击即可；它**不会**去装任何东西，也不会改动别的东西。

## 3. 真实样本核对结论（沿用已有选样，本轮不重搜）

依据：`docs/research/usable-001-u1-sample-selection.zh-CN.md`（只读已授权的结构化产物 JSONL/JSON，
未打开媒体、未扫描整盘）。该清单已核对 10 个决策点，覆盖：development replay 的 9 手注册手牌（13,415 帧）、
同一手 `observed_deal_17` 的两份观测（各 2,060 帧）、以及 `configs/reproduction/` 的 36 条已审阅动作标签。

**结论：没有一手真实牌局满足当前内核前提，`REAL_HAND_ACCEPTANCE_PENDING` 仍然成立。** 具体原因（旧证据，未重搜）：

- 全部 9 手注册手牌的 `hand_ledger_v2.status = HAND_COMMITMENTS_UNKNOWN`、`hand_commitments = null`，
  且明确标注 `opening_post_vector_incomplete` ⇒ **每座本手投入未知**；
- 河牌帧里 `participants` **最多只有 2 名 active**，而内核要求河牌开始**恰好 3 名 ACTIVE** —— 这不是补字段能解决的，
  是这手牌本身的事实；
- `configs/reproduction/*.json` 的 36 条标签只有 `actor_slot/actual_action/amount/street/review_status`，
  没有 Hero 手牌、公牌、底池、投入。

因此**没有**「待人工确认的输入」可以整理出来：能整理的部分（牌面、行动顺序候选、显示底池、座位筹码）
构不成一手可算牌局，而缺的部分无法在不猜值的前提下补上。本轮**不**把合成示例冒充真实牌局。

## 4. 需要你亲自确认的最少事项（一次列清）

### 4.1 先确认一件事

- [ ] **是否同意**：授权材料里没有符合内核前提的真实牌局（我已按已有清单核对过，本轮不重搜），
      本次试用先用**明确标记的合成输入**走通「保存 → 关掉程序 → 重开」的流程；真实第一手牌局由你另给。

### 4.2 如果你要给我一手真实牌局，请给这些（不能猜的事实）

内核会逐一核对，缺任何一项都会拒绝计算；**不要猜、不要补零**：

1. Hero 的**座位号**与**两张手牌**；
2. **5 张公牌**（必须是完整河牌）；
3. 河牌开始时**仍争池的座位号**——**恰好 3 个**；
4. **每个争池座位的本手已投入筹码**（单底池要求三名相等）；
5. **当前最高下注额**；
6. **Hero 的跟注应付额**；
7. 三家的**河牌行动顺序**；
8. **河牌公开历史**：每个动作的座位号、动作类型、以及下注/加注**到的本街累计额**（跟注/过牌/弃牌无尺寸）；
9. **显示的底池**（会与「各座已投入 + 本街历史」对账）；
10. **额外费用**：明确「本手没有」——内核目前只接受 0 且来源已确认，非零会被拒绝；
11. **桌规**：该手的盲注、前注、抽水（百分比与封顶大盲倍数）、最小筹码单位；或者你愿意用「本桌规则」里存的那套。

### 4.3 这些可以是你给的「假设」，不必是事实

页面上会明确标成假设，换一个数字结果就会变：

- [ ] 每个对手的**具体组合 + 相对权重**（例如 `JhJd` 权重 1、`TcTd` 权重 3）；
- [ ] 每个对手对 `check / fold / call / bet / raise` 的**响应权重**（两类节点都要有权重，否则内核拒绝）；
- [ ] **加注尺寸网格**（例如 `20,40,80`）与**加注次数上限**。

### 4.4 我不会替你做的事

不把 `HAND_COMMITMENTS_UNKNOWN` 当 0、不摊平底池、不虚构弃牌者投入、不用摊牌结果回填决策时的未知信息、
不把合成局面称为真实牌局、不为凑够 3 名活跃而补造玩家。

## 5. 本轮未做（范围）

未扫描新的私有媒体、未打开采集设备、未回放媒体、未调用视觉 API；未改策略、未改计算上限或容量；
未新增自动化/Agent/MCP/Git 流程；未重做 U1/U2 或扩功能；未合并、未发布、未覆盖旧程序；
未重搜旧选样材料（只引用已存在的结论）。顺带更正了 `usable-001-u2-r2-...` §3.2 里「封顶 8 < 130×5%=6.5」
的不等号笔误（正确为 `8 > 6.5`，且只说明**本例这个底池**不触发封顶）。

## 6. 可选后续（需你明确授权后才做）

1. 在页面上加一个「版本 + 提交号」徽标，让试用版本一眼可核（小改动）。
2. 你把 §4.2 的事实给我之后，我把这手牌整理成待你确认的输入并跑通第一手真实牌局。
