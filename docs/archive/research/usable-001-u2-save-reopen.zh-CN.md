# USABLE-001 U2 · 保存本次计算 → 关闭程序 → 重新启动 → 校验重开

> **部分被取代（U2-R1）**：本文档关于「两类重算只载入 / 只要求重新核对」「记录标记
> `rubric=synthetic_input_labelled`」「重算→保存尚未走通」的表述已由
> `docs/research/usable-001-u2-r1-recompute-binding.zh-CN.md` 取代。保存所有权、幂等、只读重开、
> 启动器与真实样本状态的结论仍然有效（但记录现在另带内容封存摘要与显式 `source_kind`）。

run_id `USABLE-001-U2-20260916T2225Z` · 基线 `44cb006597264107421698135a816e0b1ea34eb4`（U1-R3 验收 head）
分支 `codex/usable-001-hand-review` · 同一个 Draft PR #28 · 依据执行单 `issuecomment-5698965857`（U1-R3 `PASS_WITH_SCOPE`）
**本轮只做 U2**；不重做 U1/R1/R2/R3、不扩算法/人数/街道/上限、不新增 Git/MCP/自动化、不合并、不覆盖用户旧程序。

## 0. 一句话结论

本次实际计算可以**冻结成记录**（事实与来源、对手假设、核对时的桌规版本、规范输入、服务端实际完成报告与各类身份），
关掉服务再启动后**同一条记录仍能被读回并展示相同数值**，而重开**不调用内核、不改当前桌规**。
另提供一个**独立目录、带版本、非破坏性**的离线试用入口（自带状态目录，不覆盖既有程序/配置/记录）。
真实样本仍为 `REAL_HAND_ACCEPTANCE_PENDING`，策略强度 `NOT_ASSESSED`。

## 1. 执行单五节 → 落地对照

| 执行单要求 | 落地 |
| --- | --- |
| **1 保存的是本次计算** | 新增 `src/poker_engine/desktop/aa_analysis_records.py`（最薄适配，未改 `aa_study_records.py` 的固定合成注册表）：一次保存冻结事实（含 `provenance`/原候选）、假设、有效规则与核对时修订、**经同一可信路径重建**的规范输入、服务端实际 COMPLETE 报告、`input/facts/assumptions/rules` 身份、`job_id`、实现版本、保存时间、来源关联（无则 null）。**服务端从自己内存里的已完成 job 取结果**，客户端只能给 `job_id` + 自己核对过的输入摘要；RUNNING/ERROR/CANCELLED/TIMED_OUT/被替换的任务一律拒绝；保存重试按 `(job_id, input_sha256, source_issue_id)` 幂等，不重复新增；两个不同人工来源即使数值相同也各自成记录 |
| **2 重开与重算分开** | 重开只解析落盘记录并**从冻结值重新推导整个视图**：schema、记录类型、身份块（输入/事实/假设/有效规则四类摘要）、`input↔job` 关联、每个 `{exact, decimal}` 的**小数由精确值重算**（改动 display 会被检出）、动作字段一致性（`check/call/fold` 目标额必须为 0、`bet/raise` 必须为正、`call` 的追加金额必须等于核对时的应付额、根动作不重复）。当桌规修订或实现版本变化时，记录仍作为**原输入·原假设·原实现版本下的历史结果**可看（自洽校验通过为前提），并明确标注；**不照搬**固定 C 源文件必须仍在原位置。`reopen` 绝不调用内核、绝不用当前桌规覆盖记录。「按保存条件重算」载入保存时的输入与规则（`rules_source=document`）并**不改全局桌规**；「用当前桌规重算」把保存的事实载回表单，必须重新核对后再算 |
| **3 界面与试用启动** | 新增 `ui/aa-live/analysis_records.js` + `index.html` 一个 `<section>`：保存本次分析、已保存列表、打开已保存分析，展示牌面/局面、事实与假设（含来源与原候选标记）、规则情景、各动作追加金额与条件净 EV、容量/阻碍、公开历史标签与历史版本说明；只用现有 design token 与安全文本节点，不要求改 JSON |
| **4 独立离线试用入口** | 新增独立目录 `launch/u2-trial/`（`trial_launcher.py` + `START-TRIAL.cmd` + `README.zh-CN.md`，版本 `aa-trial-u2.0`）：复用本机既有 Python，无新依赖；启动打印版本、实现版本与未验收项；**先校验资源存在**；端口被占用时**报告并改用明确空闲端口、不结束任何进程**；**服务就绪后才打开浏览器**；自带 `state/` 目录（配置/桌规/记录都在里面，`.gitignore` 排除），不读取、不覆盖用户既有程序与记录；**不打开采集设备、不回放媒体** |
| **5 真实样本** | 选样清单沿用，未重扫那 10 条记录；本轮演示全部用**明确标记的合成输入**（记录里 `rubric=synthetic_input_labelled`，与真实记录标签分开）；未补造第三名玩家、未分摊未知投入、未用摊牌答案替代对手假设 |

## 2. 验证（本轮实跑）

| 项 | 上一轮 head `44cb006` | 本轮 |
| --- | --- | --- |
| `tests/desktop/test_aa_analysis_records.py`（18 例，新增） | **2 collection errors**（`aa_analysis_records` 不存在） | **18 passed** |
| `tests/desktop/test_trial_launcher.py`（8 例，新增） | **collection error**（`trial_launcher` 不存在） | **8 passed** |
| `tests/desktop/test_aa_analysis_records_ui.py`（2 例，含**真实重启**） | 未运行（前置收集失败） | **2 passed** |
| `tests/js/hand_records_flow_test.mjs`（26 项检查，两阶段） | 链路不存在 | **phase1 26/26 + phase2 5/5** |
| 全量 `pytest` | 4048 passed / 1 skipped（U1-R3） | **4076 passed / 1 skipped / 2 warnings，226.35s** |
| `flake8 src tests tools launch` | — | **0 项**（本机对 `launch` 也跑；CI 的 lint 目标**未改动**，原因见 §7） |

### 2.1 真实重启证据（两阶段 harness + 两个真实服务进程）

`tests/desktop/test_aa_analysis_records_ui.py` 起**两个独立服务进程共享同一记录目录**：

- **phase 1**（服务 A）：经 `controls.js` 保存桌规 → 合成输入一（`Qs Qd`）核对+计算→保存 → 合成输入二（`2h 3d`）核对+计算→保存 →
  重复保存返回同一记录 → 改输入后保存旧任务被拒 → 再算一次并改桌规（确认旧记录不被改写）→ 打开旧记录得到**历史规则版本**说明 →
  「按保存条件重算」载入保存规则且**全局桌规未变** → 「用当前桌规重算」把事实载回表单要求重新核对 →
  改写某条记录的 display 值后经**真实 get/list 路径**得到 `INVALID`/`display_permitted=false`/`view=null`，UI 拒绝展示数值 → 还原后重新可读。
- 停掉服务 A（并确认端口确实拒绝连接）后，**phase 2**（新的服务进程 B）读同一目录：
  两条记录仍在、各自自洽校验通过、分别打开后牌面与数值与 phase 1 **完全一致**，且**没有发出任何 `/api/analysis` 请求**（重开未跑内核）。

### 2.2 反例清单（都在真实路径上验证）

| 反例 | 结果 |
| --- | --- |
| 保存一个还没算完的任务 | 400「只有已完成的分析可以保存」 |
| 保存一个已被新输入替换的旧 job | 400「已被新的输入替换，保存被拒绝」 |
| 客户端自报的输入摘要与服务端不一致 | 400「不是同一份」 |
| 事实/假设重建不出服务端实际用的输入 | 400「重建的规范输入与…不一致」 |
| 重复保存同一 job | 返回同一条记录 + `duplicate_of_existing`，目录仍只有 1 个 |
| 两个不同来源数值相同 | 两条独立记录 |
| 改动保存记录的 display 小数 | `INVALID`，不展示数值，文件保持原样 |
| 改动精确值 / 有效规则 / 规范输入 / 身份摘要 | 同上，各自命中对应检查 |
| 动作字段不一致（`call` 目标额非 0） | `INVALID` |
| 落盘 JSON 损坏 | get 明确拒绝、list 标 `INVALID`、**文件未被改写或删除** |
| 把损坏记录当重算输入 | 拒绝并说明原因 |

## 3. 页面操作步骤

1. 「设置与分析 → 本桌规则」保存完整桌规。
2. 「录入一手已结束牌局」填完 → **核对输入** → **计算条件收益**（得到本次输入的条件净 EV）。
3. 展开「保存本次分析并重开」→ 填记录名称 → **保存本次分析**（结果只针对这次输入与这次规则）。
4. 关掉程序，重新运行（试用入口见下）→ **刷新记录** → 选一条 → **打开已保存分析**（只读历史，不重算）。
5. 需要重算时二选一：**按保存条件重算**（用保存时的输入与规则）或 **用当前桌规重算**（事实载回表单、必须重新核对）。

## 4. 离线试用入口

```
launch\u2-trial\START-TRIAL.cmd              # 双击；首选端口 8791
python launch\u2-trial\trial_launcher.py --self-check   # 只报告版本/资源/端口/目录
```
启动即打印：版本 `aa-trial-u2.0`、实现版本 `aa-analysis-record-v1`、实际地址、试用状态目录、以及**逐条未验收项**。
状态与记录都在 `launch/u2-trial/state/`；**不覆盖**既有程序、配置与记录，也不结束任何进程、不占用采集设备。

## 5. 当前可用范围与剩余阻碍

- **可用**：河牌、恰好三名活跃玩家、单底池、人工录入或从结构化快照带入的已结束牌局；本次输入的条件净 EV；
  本次分析的保存、列表、只读重开、两类显式重算；以及隔离的离线试用入口。
- **不可用**：边池/全下跨越、翻牌与转牌、非三人活跃场景、超过 128 联合组合的宽范围、未支持特殊机制；
  不做范围编辑器、不做对手模型、不给实战提示、不自动点击。
- **真实样本**：`REAL_HAND_ACCEPTANCE_PENDING` **独立保留、状态未变**；本轮的合成记录只用于工程与反例验证，
  记录里带 `synthetic_input_labelled` 标记，与真实记录始终分开。
- **策略强度**：`NOT_ASSESSED`。

## 6. 本轮明确不做

不启动下一检查点；不重做 A/B/C/D 与冻结的 C 协议数据；不换模型；不扩 solver/容量/上限；不改 #24/#20；
不新增 Git/MCP/Agent/自动循环；不读新私有媒体、不开采集或视觉 API；不合并、不发布、不覆盖用户旧程序。
## 7. 一处未做（如实列出）

CI 的 flake8 目标仍是 `src tests tools`，**没有**把新目录 `launch/` 加进去。
原因：本机推送用的是 `gh` 的 OAuth 令牌，**缺少 `workflow` 权限**，修改 `.github/workflows/*` 会被远端直接拒绝
（`refusing to allow an OAuth App to create or update workflow ... without workflow scope`）。
没有为此改写推送方式或新增 Git 工具（本轮明确不开发 Git/自动化）；`launch/u2-trial/trial_launcher.py` 已在**本机**
通过同一套 flake8 配置（`max-line-length=88`、`extend-ignore=E203,W503`）检查，0 项。
如需让 CI 覆盖它，请由所有者在 `gh auth refresh -s workflow` 之后再加一行 lint 目标；本轮未擅自改动 CI 配置。
