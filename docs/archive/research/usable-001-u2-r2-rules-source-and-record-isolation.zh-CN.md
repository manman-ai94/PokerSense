# USABLE-001 U2-R2 · 规则来源控件与实际模式一致、坏形状记录逐条隔离

run_id `USABLE-001-U2-R2-20260916T1804Z` · 增量基线 `d9212c8690251ac3482715921e1aca70c6f6868f`（U2-R1 head）
分支 `codex/usable-001-hand-review` · 同一个 Draft PR #28 · 依据审查 `pullrequestreview-5226343574`
与执行单 `issuecomment-5702073701`。
**本轮只补 A（规则来源控件）与 B（坏形状记录隔离）**；不重做 U1/U2-R1、不重写启动器、不升级环境/权限/模型、
不扩算法/容量、不新增 Git/MCP/自动化、不合并、不覆盖用户旧程序。

## 0. 一句话结论

「使用本桌已保存规则」这个控件现在**真的会切换模式**（勾选即退出保存条件情景，保留牌局、对手假设与重算父记录），
并且规则来源不一致时构建请求会 fail-closed 地拒绝；
`record.json` 是合法 JSON 但不是对象（`[]` / `null` / 字符串）时，**该条记录自己按 `INVALID` 拒绝，其余记录照常读取**，
列表/单条/重算三个入口都不再抛未处理异常、不挂住连接、不改不删文件。
真实样本仍为 `REAL_HAND_ACCEPTANCE_PENDING`，策略强度 `NOT_ASSESSED`，两者独立保留、状态未变。

## 1. A / P1：规则来源控件与实际计算模式一致

### 旧缺陷（实测）

保存条件模式（`handScenario` = 该记录的规则，checkbox 关闭）下，用户勾选「使用本桌已保存规则」时，
change 处理器只调 `handCareful`（清回执），**不退出 `handScenario`**；`handVerify` 只看 `handScenario` 非空就用它，
于是请求仍是 `rules_source=document` + 旧 `table_rules`，而界面显示的是「本桌规则」。
上一 head 的隔离探针（本轮 harness 实测）：

```
ticking_the_real_rule_source_control_leaves_the_saved_scenario
  scenario=[object Object]  status=输入已变更，请重新核对后再计算。   # 情景仍在
the_switched_verify_asks_the_server_for_the_TABLE_rules
  sent=document  doc_rake=0                                        # 仍发旧 document 规则
the_switched_rules_actually_changed_the_numbers
  A call=64.375 -> switched call=64.375                            # 数值完全没变
```

### 修法

| 落点 | 改动 |
| --- | --- |
| `hand_input.js::handUseTableRulesFromControl`（新） | 规则来源控件改为**自己的 change 处理器**：勾选本桌规则时 `handScenario = null`、checkbox 置真、`handInvalidate(...)` 明确说明「记录 X 的保存条件模式已退出（牌局、对手假设与重算来源保留）」；已在 table 模式时退化为原有的 `handCareful`（只作废回执） |
| `hand_input.js::handVerify`（新守卫） | 若 `handScenario` 非空而 checkbox 为真（控件与场景不一致），**fail-closed 拒绝**并说明，不再替用户猜规则来源 |
| `handLoadRecordScenario` | 保存条件模式下把「要改用本桌规则就勾选该控件」写进阻碍清单，让可用的切换操作在界面上可见 |
| `analysis_records.js::recordsRecompute` | 保存条件模式的面板反馈补上同一句提示 |

规则来源因此只有**一个明确生效的状态**；反向切换（本桌 → 记录保存条件）仍走已验证记录的显式入口
（重新打开该记录 → 点「按保存条件重算」），不新增页面、不改全局桌规、不凭空补规则。

## 2. B / P2：坏形状记录逐条隔离

### 旧缺陷（同一探针脚本，同一目录）

| 文件内容 | 旧 head | 本轮 |
| --- | --- | --- |
| `[]` | 列表**HTTP 500 且响应体不结束**（读体超时） | 200，该条 `INVALID` / `display_permitted=false` |
| `null` | 请求**超时** | 200，同上 |
| `"not-an-object"` | 请求**超时** | 200，同上 |
| `get` / `scenario` | 超时 | **400**「分析记录格式不受支持」 |
| 健康记录 | 一起读不出来（`0/3` 列表请求里四条健康记录全部消失） | 四条全部照常 `display_permitted=true` |
| 文件 | — | **字节未变**（`[]`/`null`/字符串原样保留） |

（同一脚本 `probe_shape.py` 分别在两个 head 的独立只读 worktree 上跑，未操作所有者目录。）

### 修法（共享边界先核对形状，再访问字段）

| 落点 | 改动 |
| --- | --- |
| `aa_analysis_records.py::_verify` | **第一条**检查就是 `isinstance(document, dict)`；不是对象 → `(note, None, INVALID)`，任何字段都不再被 `.get` |
| `aa_analysis_records.py::_verify` | 字段读取段的 `except` 增补 `(AttributeError, TypeError, KeyError, IndexError, ValueError)` → 记为**该条自己的**「记录结构不受支持，读取字段时失败：<类型>: <消息>」，既不是成功也不是跳过 |
| `aa_analysis_records.py::_present` | 信封字段改为从 `fields = document if isinstance(document, dict) else {}` 读取，记录号仍按**目录号**报告 |
| `aa_analysis_records.py::recent` | 每条一个 `try`（解析 + `_present`），可预期的解析/结构失败 → 该条 `INVALID` 行并**继续处理下一条**；不是吞掉整个列表返回空列表，也不自动改写/删除坏文件 |
| `_invalid_row`（新） | 统一「无法读取」行的形状，避免各处手写不一致 |

`_load` 的顶层字典检查保持（单条 `get` 继续 400）；旧格式 `UNVERIFIED_FORMAT`、内容封存、幂等、
重开不跑 solver 的合同一律不动。

## 3. 验证（本轮实跑）

| 项 | 上一 head `d9212c8`（独立只读 worktree，仅换新测试） | 本轮 |
| --- | --- | --- |
| `tests/desktop/test_aa_analysis_records.py` | **7 failed / 44 passed** | **51 passed / 0 failed** |
| 三阶段 harness（三个真实服务进程） | run1 **9 项命名失败**（A 6 项 + B 3 项） | run1 + run2 + run3 全绿 |
| `flake8 src tests tools` | 0 项 | **0 项** |
| 全量 `pytest -v` | 4092 passed / 1 skipped（U2-R1） | **4109 passed / 1 skipped / 2 warnings，462.32s** |

### 3.1 上一 head 的 RED（逐项命名，非崩溃）

A：`ticking_the_real_rule_source_control_leaves_the_saved_scenario`（`scenario=[object Object]`）、
`the_switched_verify_asks_the_server_for_the_TABLE_rules`（`sent=document doc_rake=0`）、
`the_switched_record_uses_THIS_table_rules_and_keeps_its_parent`（记录规则 `rake_cap_bb=0` vs 本桌 `2`）、
`the_switched_rules_actually_changed_the_numbers`（数值完全相同）、
`switching_the_rule_source_during_an_in_flight_verify_discards_the_answer`、
`the_two_current_rules_entries_reach_the_same_rules_by_different_controls`。
B：`a_wrong_shaped_file_is_listed_as_invalid_and_does_not_hide_the_others`（`0/3 served`，四条健康记录全部读不出来）、
`get_and_scenario_answer_a_wrong_shaped_file_with_a_refusal_not_a_crash`（`0/3 answered 400`）、
`the_records_panel_still_reads_the_healthy_records_after_a_bad_shape`（面板空白）。

服务端 7 项：`[]`/`null`/`"not-an-object"`/`123`/`true`/`[]\n` 六种非对象文件 + 「两条健康记录夹一条坏文件」，
旧实现都抛 `AttributeError: 'NoneType' object has no attribute 'get'`；本轮同样输入下全部按条 `INVALID`。

### 3.2 一个被量测出来的真陷阱：抽水封顶为 0 会把差异抹掉

审查提到「避免封顶为 0 掩盖差异」，本轮实测确认它在**上一轮的 harness 里就是真的**：

| 桌规 | 根动作 EV（同一手牌/假设） |
| --- | --- |
| `rake_percent=0, rake_cap_bb=0` | call `64.375` · raise40 `83.03125` · raise80 `108.90625` |
| `rake_percent=0.05, rake_cap_bb=0` | call `64.375` · raise40 `83.03125` · raise80 `108.90625`（**完全相同**） |
| `rake_percent=0.05, rake_cap_bb=2` | call `60.15625` · raise40 `78.23125` · raise80 `104.10625`（明确不同） |

`rake_cap_bb=0` ⇒ 封顶 `0 × 大盲 = 0` ⇒ 抽水被整段吃掉，于是「按当前规则重算」与「按保存条件重算」
在数值上无法区分，上一轮那一步的 EV 断言是**空的**。本轮 R2 改为 `rake_cap_bb=2`（封顶 `2 × 大盲 4 = 8` 筹码，
大于本例 130 底池的 `130 × 5% = 6.5`，因此本例不触发封顶，抽水照常计入），差异因此可测。
（更正：本文件早先写成「8 < 6.5」，不等号写反了；正确关系是 `8 > 6.5`。这里只能说明**本例这个底池**不触发封顶，
不代表所有终局都不触发——更大的底池仍会撞到封顶。）

## 4. 真实控件「保存条件 → 切本桌规则 → 重新核对 → 真实计算 → 保存 → 重开」

三阶段 harness（真实 DOM 替身、真实 HTTP、真实内核、三个真实服务进程共享一个记录目录）：

- 打开记录 A → 「按保存条件重算」→ 表单进入 A 的规则情景（`handScenario.rules.rake_percent="0"`，控件关闭）→
  **先核对一次**，确认此时确实是 `rules_source=document`、document 的 `rake_percent=0`；
- **通过真实控件**勾选「使用本桌已保存规则」（置 checkbox 后派发真实 change）→
  情景退出、回执/已构建文档/已接受 job 全部归零、控件为真；**牌局、对手假设、加注尺寸与重算父记录全部保留**；
- 重新核对 → 构建请求实测 `rules_source="table"`，文档 `rake_percent=0.05`；
- 真实内核计算 → 保存为**新记录 E**：`parent=A`、`source_kind=recomputed_from_analysis_record`、
  `effective_rules` 与本桌当前 `simulation_rules` **逐字段一致**、job 与 A 不同、A 未被改动；
  且 E 的 EV 与 A 的**不同**（规则真的生效）；
- 「本桌当前规则」入口（记录 C）与「保存条件」入口（重启后记录 D）仍然各自可用，三条重算记录的规则情景分别是
  `0.05`（E、C）与 `0`（D），互不覆盖；
- **直接内核交叉核对**：把 E 自己的规范输入直接 POST 给 `/api/analysis`（`rules_source=table`），
  返回的根动作 EV 与 E 里冻结的 EV 逐项相同、`input_sha256` 与 E 的身份相同；
- 重启（第二个进程）与再重启（第三个进程）后，五条记录逐字段不变、各自自洽通过、**零分析请求**。

## 5. 边界（未变）

未改内核/求解器/容量/上限/启动器/CI 配置；未换模型；未新增 Git/MCP/Agent/自动化；未读新私有媒体、未开采集或视觉 API；
未合并、未发布、未覆盖旧程序。`REAL_HAND_ACCEPTANCE_PENDING` 与 `NOT_ASSESSED` 独立保留。
真实样本仍缺「3 个争池座位号 / 每座已投入 / 当前最高下注 / Hero 应付额」四项，本轮未补造。

## 6. 与既有文档的关系

本文档补充（不取代）`docs/research/usable-001-u2-r1-recompute-binding.zh-CN.md`：
U2-R1 的两类重算、请求身份、内容封存与三进程重启结论全部仍然有效；
本轮在其之上补齐「规则来源控件必须与发送的模式一致」与「坏形状记录逐条隔离」。
