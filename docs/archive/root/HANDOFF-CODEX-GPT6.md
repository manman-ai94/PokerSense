# PokerSense 项目交接 — 交给 Codex GPT-6 全权接手

> **历史文件，已于2026-09-12过期。** 这里保留当时背景，不再代表当前主线。
> 新账号或新模型必须从
> `handoff/2026-09-12/START-HERE.zh-CN.md` 开始，不要按本文件的
> “WPK主线、AA第二阶段”继续。

> 给 **Codex GPT-6** 的项目交接。只给最必要的事实和方向，**现状由你自检**，怎么推、先推哪，由你用能力判断。
> 直接整份复制给 Codex 即可。

---

## 一、两个基本事实

### 1. 原始视频素材在哪

全部归档在 **G 盘**：`G:\PokerSense_archive\`

| 平台 | 目录 | 原始视频 |
|---|---|---|
| wepoker（主） | `capture_card_calibration_20260903\` | `source\raw\` 下 `session_001.mkv`(6.7G)、`session_002.mkv`(12G)，以及两个 `_UNFINALIZED` 残卷（停录未 finalize，与同名 .mkv 重复，解一份即可） |
| AA（独立起步） | `capture_card_calibration_aa_20260904\` | `source\raw\session_001.mkv`(24G) |

每个平台目录下还有已加工产物：`normalized\frames\`（归一化 PNG 帧）、`normalized\manifest.json`、`labels\frames.jsonl`（真值标签）、`splits\`、`reports\`、`_mining\`（目检拼版）、若干 `_act_*.py`/`_debug_*.py` 探索脚本（可参考，不必全读）。

### 2. 项目唯一地址在哪

**唯一主仓库（本地，不推远程）：`C:\Users\Administrator\WorkBuddy\扑克\PokerSense`**

- 本地自用项目。GitHub 上 `github.com/windgeek/PokerSense` 只是**技术路线参考源**，owner 定调：全部本地运行，不推远程、不做 CI/CD。
- 同级 `PokerSense-交付\` 是只读交付副本。

---

## 二、项目是什么

**PokerSense** = 德州扑克**「训练陪练」桌面工具**。桌面端用 UVC 采集卡 / ADB 抓取真实牌桌画面，走完整链路：

```
视频/画面捕获 → 视觉识别(牌面/筹码/座位/动作/街) → 状态重建 → 策略建议 → UI 出牌理建议
```

**它是陪练，不是外挂**：绝不自动点击/下注/控制客户端，人永远是唯一操作者。这是它的本质前提，不是限制。

技术栈：Python（OpenCV + numpy）、原生 HTML/CSS/JS 单页 + WebSocket（无框架无构建）、pytest。
顶层路线文件：`PLAN-MASTER-四象限总计划.zh-CN.md`（四象限 = 快速 / 稳定 / 可盈利 / 自我进化）。

---

## 三、两个必须提前知道的坑（中文路径）

项目路径含中文「扑克」，是本机一系列诡异 bug 的根因，三条铁律：

1. `cv2.imread("/中文路径/...")` 返回 `None` → 一律 `cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), flags)` 读、`cv2.imencode`+`.write_bytes` 写。
2. C/C++/Rust/Binutils 构建**必须在纯 ASCII 路径编译，再复制回来**（中文路径会炸 `dlltool`，曾两次摧毁 .git）。
3. ⛔ 中文路径仓库**禁止 `git checkout -b` / `stash` / `rebase` / `gc` / `prune`**。提交只用 `git add -A` + `git commit`。

环境：Python venv `C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`；跑测试带 `PYTHONPATH=src`；flake8 `max-line-length=88`、`extend-ignore=E203,W503`、排除 `aa_record_session.py`。

---

## 四、现状由你自检

我不写"已经做到哪"。请你**先自己把项目现状摸一遍**：

1. 跑一次完整回归，拿到真实的通过/失败基线：`PYTHONPATH=src <venv-python> -m pytest tests/ -q`
2. 读 `PLAN-MASTER-四象限总计划.zh-CN.md`，对照四象限看缺口在哪。
3. 自己判断：视觉层的 9 个字段标定到哪了、翻前策略覆盖到哪、翻后策略有没有、UI 通不通。
4. 需要时翻 `HANDOFF-2026-09-06.zh-CN.md`（上一版的坑清单）和 `docs/`、`PLAN-*.md`。

自检结论**以实跑代码为准**，不要读注释/文档猜。

---

## 五、最该往哪推（我的判断，供你校准，不是约束）

按这个项目的症结，**最应该推的是「可盈利」这条线——翻后策略**。理由：

- 这是一个扑克训练/陪练工具，价值核心是**翻后能不能给出有 EV 依据的建议**。翻前再稳、识别再准，翻后一片空白，用户拿到手也"不好用"。
- 翻前（PREFLOP）和视觉识别相对已经比较成熟；翻后是当前最薄、也最能拉开"能盈利 vs 不能盈利"的一环。
- 求解器路线：`bupticybee/TexasSolver`（AGPL-3.0，自用不商用范围已放开；独立进程、不进仓库）。river 可实时、turn 较慢、flop 需离线预解——这是一个有明确工程纵深、能发挥你能力的硬骨头的方向。

具体怎么落（先 river 还是先整体架构、用哪个求解器、怎么接独立进程），**由你设计**。方向我给了，方案归你。

---

## 六、交付风格

- 中文，条目/表格化，明确结论与盲区，不写"最优/完美"。
- 关键结论给实测数字 + 命令输出。

---

**开始吧：先自检现状，然后朝着「翻后策略」这条主线把它推起来。**
