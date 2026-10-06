# STRATEGY-DIAG D 阶段：现有离线复盘的最小接入

任务：STRATEGY-DIAG（Issue #23）· 检查点来源 = 评论 5693166971 + C 审查 `pullrequestreview-5219296503`
run_id：`STRATEGY-DIAG-D-20260916T0645Z`
**范围：只有 D。A/B/C 未重做、未改协议参数、未删历史。** 未改视觉规范、未开采集、未新增算法或自动化。

## 1. 页面入口与点击步骤（非程序员可直接照做）

| 步骤 | 操作 |
| --- | --- |
| 1 | 启动本机 AA 观察台（`python -m poker_engine.desktop.aa_server --profile <识别资源> --records-dir <记录目录>`），浏览器打开 `http://127.0.0.1:8771/` |
| 2 | 顶部导航点 **「设置与分析」** |
| 3 | 页面下半部展开 **「研究结果示例与已保存记录（合成 · 非本桌）」** |
| 4 | 在「研究示例」下拉里选 **对手范围敏感性对照（合成研究示例）**，点 **「载入示例（只读预览）」** |
| 5 | 查看：来源与适用范围、固定策略本、唯一变化对象、三组条件净 EV 与相对基线差、可展开的精确分数与主要终局路径 |
| 6 | 点 **「保存为独立研究记录」** → 记录编号出现在提示里，记录下拉多一条（状态「已保存 · 当前版本」） |
| 7 | 在「已保存的研究记录」下拉切到**另一条**记录，点 **「重开结果」** |
| 8 | 需要核对原始字段时展开 **「完整来源、身份与原始字段（只读）」** |

真实截图（本机实测，未提交仓库以免与「不提交媒体」规则冲突）：

| 文件 | 内容 | 大小 / sha256 前 16 |
| --- | --- | --- |
| `d-preview.png` | 示例只读预览：合成标签、来源、固定策略本、变化对象、EV 对照表 | 71,543 B / `491248be112d2c59` |
| `d-saved.png` | 保存后的独立记录：编号、状态「已保存 · 当前版本」、记录下拉「共 3 条」 | 74,578 B / `a7f1f4f2afdc1082` |
| `d-details.png` | 精确分数表（`737057752/20650813` 等）与主要终局路径贡献差（5 条非零） | 40,453 B / `80419f97e0453ae5` |

## 2. 最小接入做了什么

| 层 | 文件 | 内容 |
| --- | --- | --- |
| 后端 | `src/poker_engine/desktop/aa_study_records.py`（新） | 受控示例注册表 + 报告校验 + 视图模型 + 独立记录存储 |
| 后端 | `src/poker_engine/desktop/aa_server.py` | 5 条只读/受控路由 + 服务 `/study.js`（沿用既有同源与 `X-AA-Live` 中间件） |
| 前端 | `ui/aa-live/study.js`（新） | 仅用 `createElement`/`textContent` 的安全渲染、token 迟到响应保护、错误态 |
| 前端 | `ui/aa-live/index.html` | 在「设置与分析」里加一个 `<details>` 面板 + 一条 script |

**五条路由**：`GET /api/study/examples`、`GET /api/study/examples/{id}/view`（只读预览，不落盘）、
`POST /api/study/records`（保存）、`GET /api/study/records`（列表）、`GET /api/study/records/{record_id}`（重开）。

## 3. 合成示例与真实牌局的隔离（硬约束）

- 示例只经**固定注册表**载入：`example_id → 仓内固定文件名 + 期望 sha256`；
  报告里的 `protocol.path` / `input.path` 字符串**只做一致性比对，绝不用来打开文件**（有专门回归测试证明）。
- 保存的记录是**独立 sidecar**：`records_dir/study-records/<record_id>/record.json`，
  与「复查记录」的 issue 命名空间分离；记录里 `bound_record_id = null` 并写明不绑定任何观测牌局。
- 视图模型显式标注 `source_type = SYNTHETIC_STUDY_EXAMPLE` 与「合成研究示例 · 非本桌 · 非真实对局」，
  并给出 4 条**缺失项**（未绑定真实牌局、未观测范围、真实抽水/封顶/摊牌 UNKNOWN、未评估跨世界总体优劣），
  界面不允许用示例参数补齐真实牌局。
- `strategy_eligible` / `advice_emitted` / `live_advice` 恒为 `false`；产品流程不调用视觉 API、不开采集设备、
  不做任何牌桌操作（有 `RecordingSession` 回归：整个流程只触发应用关闭时的 `stop`）。

## 4. 数值展示与校验

- EV 以 **chips** 为单位给出易读小数（4 位，仅展示）+ **可展开的精确分数**；
  对账只用精确 Fraction，`0.1607` 这类小数不参与任何比较。
- 保存与打开时都会**重算**：每套策略概率和 = 1、贡献和 = 该策略 EV、终局路径贡献和 = 台账贡献和、
  同本对账 `Σ(逐路径差) = 报告 EV 差`、跨本对账 `Σ(逐路径差) = selected − manual_reference`、
  逐因子读数与策略指标一致、`Σ 后验 = 1`。任何一项不符即拒绝。
- **`policy_unchanged` 不接受「两个空字段相等」**：要求策略本哈希是完整 64 位十六进制、
  世界内 `policy_hash_before == policy_hash_after == book_sha256`、`unchanged_across_worlds is True`
  且与冻结策略本台账一一对应；空值或缺失直接判无效。
- 拒绝清单（都返回 400 且界面不渲染结果）：基准未复现（`matches_original_reading != true`）、
  世界 BLOCKED、未知 schema / 多余字段、路径贡献或概率被篡改、不可达路径带条件 EV、
  控制台行数/路径数与计数不自洽、空身份、非法路径、示例源文件哈希不符、未登记示例、
  外部记录编号、超大小记录文件、重复键 JSON。
- **输入修订变更后旧结果标历史**：登记文件在保存后被替换时，重开该记录返回
  `content_status = SUPERSEDED_SOURCE`（界面显示「历史记录 · 源文件已变更」），内容与标签仍按保存时原样展示，
  不再作为当前结果。
- 迟到响应：`studyToken` 单调令牌 + `studyAcceptance()`，旧响应到达时既不渲染也不改动 `#study-content`。

## 5. 实际验证（本轮实跑）

| 检查 | 命令 / 方式 | 结果 |
| --- | --- | --- |
| 后端与 API 回归 | `pytest tests/desktop/test_aa_study_records.py` | **24 passed** |
| 真实 JS 交互（无浏览器） | `pytest tests/desktop/test_aa_study_ui.py`（起真 uvicorn + 跑 node 驱动**原样 study.js**） | **2 passed / 26 项检查全绿** |
| 页面交互与布局 | agent-browser（Chromium）打开 `http://localhost:8791/` 并按步骤点击 | **BROWSER_VISUAL_RUN**：3 张真实截图（见 §1） |
| 全部 JS 检查 | `node tests/js/study_flow_dom_stub_test.mjs <base>` | `verdict ok=true, passed=26, failed=0, requests=13` |
| 全仓回归 / lint | `pytest -v` / `flake8 src tests tools` | 见 PR 正文的当轮实测行 |

JS 交互测试覆盖：示例列表与 SYNTHETIC 标记、只读预览的数值/路径/缺失项/固定说明、保存为独立记录、
记录列表、重开内容与身份一致、**迟到响应不覆盖新记录**、未知示例与外部记录编号被拒、
无 `innerHTML` 写入、全部请求只落在 `/api/study/*`。

**浏览器限制（如实记录）**：agent-browser 的页面会话在**单条命令内**稳定，跨命令会丢失页面
（表现为快照 `(empty page)`、ref 失效）；因此点击流程都放在同一条命令链里完成，
`http://127.0.0.1:8791/` 渲染空白而 `http://localhost:8791/` 正常。截图与自动化断言分开表述。

## 6. 未完成项与边界

- 列表上限 30 条、单记录/报告上限 2 MB；不做导出、不做图表、不做多示例并列（本轮明确不做美化）。
- 未接入真实牌局：示例与观测记录**没有**任何自动关联路径，也不打算有。
- 未改视觉规范（复用既有 `panel` / `footnote` / `tag` / `review-picker` / `analysis-table` 样式）。
- 未新增常驻服务、队列或通用导入平台；未改观察、人工复查与 AI 候选数据。

---

## 7. D-R1 补修（2026-09-16，按审查 `pullrequestreview-5220426669`）

审查判定 `IMPLEMENTATION_PRESENT / D_NOT_ACCEPTED_YET`，三项补修均已按「先补失败用例、再最小修复」完成。

### 7.1 P1：重开记录时真正重算，不再信任记录自称

**缺陷（修复前实测，`dr1-probe-before.txt`）**：

| 落盘改动 | 修复前 | 修复后 |
| --- | --- | --- |
| 未改动 | `CURRENT`，返回 view，display `-0.1607` | `CURRENT`，返回 view，`display_permitted=true` |
| 只改 `display` 为 `999999.0000`（exact/hash 不变） | **`CURRENT` 且原样返回错值** | `INVALID`，**不返回 view**，`display_permitted=false` |
| 改 `bound_record_id` / `source_type` / 策略身份 | **`CURRENT`** | `INVALID`，不返回 view |
| `example_id` 改为未登记 | `INVALID` 但**仍返回完整 view** | `INVALID`，不返回 view |

**最小修复**：`_verify()` 在 `get`/`recent` 时从**已验证的登记源**重新推导 `identity` 与 `view`，
逐项与落盘内容比较；`identity` 缺失/非 64 位十六进制、`bound_record_id` 非空、嵌套 `decision` 非 false、
`table_context` 非合成来源等一律判无效。源文件被替换或不可用时不再用「源 hash 正常」冒充，
而是 `HISTORICAL_UNVERIFIED` + `display_permitted=false`（文件保留、不删除、不改写 Git 历史）。
`INVALID` 与历史记录都**不返回 view**，前端也不渲染数值、不写成功反馈。

### 7.2 P2：选择变化 / 关闭面板 / 迟到响应 / 无效结果

**缺陷（修复前）**：token 只在 Load/Save/Open 开始时增加，选择变化与关闭面板不失效；
`INVALID` 仍被渲染并给出「与保存时一致」的成功反馈。

**最小修复**：新增 `invalidateStudy()`（自增 token、清空内容、隐藏、禁用保存、复位标签），
在**新请求开始前**以及 `study-example` / `study-record-select` 的 `change`、`study-tools` 的 `toggle`（关闭）时调用；
`renderStudy(record, token, expectedTarget)` 除 token 外还核对**目标身份**（`studyAcceptsTarget`）
与 `display_permitted`，不满足时不渲染数值。

### 7.3 P2：面板补最小实验局面

`build_view()` 新增 `table_context`（来自已核对身份的登记输入与已验证报告）：
Hero 手牌 `Qs Qd`、公牌 `2c 4d 7h 9s Jc`、公开历史「座位1 bet 20 → 座位2 call」、
底池 130（各座已投入 90 + 本街历史投入 40）**chips**、决策点需跟注 20，
以及两套固定策略的根动作：**手工参考策略 = 跟注（本街追加 20）**、**训练选中策略 = 加注到 80（本街追加 80）**，
并显式标注「合成假设，不是实战指令」。底池由声明数值相加得出（`definition` 字段写明未调用引擎），
根动作从已验证报告的**可达终局路径**唯一确定——不为展示重新规划策略。重开后逐字一致（同一字段参与 `view` 比较）。

### 7.4 先红后绿

| 阶段 | 结果 |
| --- | --- |
| 先写失败用例（后端 15 例 + JS 6 项检查） | `pytest tests/desktop/test_aa_study_records.py`：**15 failed**（其余既有 24 例通过） |
| 最小修复后同批 | 该文件 **39 passed**；`tests/desktop/test_aa_study_ui.py` 的 JS 检查 **34/34 passed**（修复前 32 passed / 2 failed） |
| 全仓 | **3999 passed / 1 skipped / 2 warnings，61.54 s**（D 基线 3984 = +15 例） |
| Lint | `flake8 src tests tools` 0 项 |

### 7.5 实际界面检查（本机 Chromium）

| 文件 | 内容 | 大小 / sha256 前 16 |
| --- | --- | --- |
| `dr1-context.png` | 新实验局面区块：手牌/公牌/公开历史/底池 130/需跟注 20 + 两套根动作表（跟注 20 vs 加注到 80） | 56,203 B / `675e763d9db1411a` |
| `dr1-invalid.png` | 落盘被改写后的记录：标签「无效记录 · 不可作为结果」+ 拒绝理由 + 身份行，**不显示任何数值**、保存按钮禁用 | 66,760 B / `00aace07eb1a0639` |

浏览器限制同 §5：会话只在单条命令内保持，`127.0.0.1` 空白而 `localhost` 正常。

### 7.6 本轮边界

未改冻结协议与 C 数据；未新增算法、自动化、Git 工具或平台；未接触视觉/实时/采集链路；
未删除任何记录文件；`strategy_eligible` / `advice_emitted` / `live_advice` 恒为 `false`。
