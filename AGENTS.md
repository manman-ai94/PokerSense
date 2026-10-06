# PokerSense 项目说明（给所有 AI 协作者）

开始任何工作前先读完本文件，再读 [docs/ROADMAP.md](docs/ROADMAP.md)。
本文件只写**现状和规则**，保持在 200 行以内；过程记录写进 PR 描述，不要追加到这里。

## 这是什么

PokerSense 是一个德州扑克**实时策略分析**工具：用采集卡读取 AA 扑克手机画面 →
识别牌局 → 实时计算并显示策略参考。用途是跟 AI 学打牌，不涉及资金。

底线（任何改动都不能违反）：

- 软件只显示分析结果，**绝不**自动点击、下注或控制扑克客户端；人始终是唯一操作者。
- 识别或状态不确定时输出 `UNKNOWN` / `ABSTAIN`，不猜、不补默认值。
- 合成数据、开发集和单元测试的结果，不能当作真实牌局验收结论。

## 当前阶段

总目标：做一个胜率高的扑克 AI，人通过它的实时分析学习。按 [ROADMAP](docs/ROADMAP.md)
的里程碑推进，当前顺序是：识别补缺 → 策略记分牌 → 翻前范围表 → 单挑翻后求解 → 多人底池 → 界面重做。
已确定的方向：
- 不自研全街策略，也不自研求解器；单挑翻后用现成开源求解器，多人底池先给数学参考并明确标注。
- 每项策略改进都必须在“策略记分牌”（模拟牌桌上的 bb/100）上看到提升，不能凭感觉。

## 开发环境（macOS Apple Silicon）

```bash
export PATH="/opt/homebrew/bin:$PATH"   # Homebrew（gh、node）不在默认 PATH 里
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev,desktop,solver-tools,perceptual]"

# 全量测试约 10 分钟；pyproject 里已默认 -q
PYTHONPATH=src:. .venv/bin/python -m pytest
.venv/bin/python -m flake8 src tests tools research/hu_root research/coverage_bridge
```

- 支持 Python 3.11–3.13，本机用 3.12。依赖版本在 `pyproject.toml` 里精确锁定，不要放宽。
- 前端 JS 测试需要 Node.js（`brew install node`），没装时会自动跳过。
- 2026-10-06 在 M1 Pro 上跑过全量测试：5593 个通过，8 个跳过（都是只能在 Windows 上跑的），0 个失败。
- 采集卡在 macOS 上走 AVFoundation，这是默认接口；Windows 上仍是 MSMF。
  2026-10-06 真机验证通过：UGREEN 25854 采集卡（AVFoundation 设备 0），1920×1080、30 帧，
  手机画面位置和 Windows 录像一致（裁切第 711–1208 列），实时识别正常。
- 采集卡注意事项：
  - macOS 的摄像头权限给的是 Mac 自带的“终端”应用。要用 `launch/mac/*.command` 启动，
    它们会在“终端”里运行；从 Claude 的命令行直接读采集卡会被系统拒绝。
  - 三星手机接 HDMI 后要切换到“屏幕镜像”，不能用 DeX 桌面模式。

## 在 Mac 上运行

```bash
launch/mac/start-aa-capture.command           # 接采集卡实时识别（观察页里选“实体采集卡”）
launch/mac/record-aa-capture.command 20 标签   # 录采集卡画面 20 分钟，存到 PokerSense_private/aa-mac-recordings/
launch/mac/start-aa-video.command             # 录像实时回放：按录像节奏送画面，模拟采集卡
launch/mac/start-aa-replay.command            # 逐帧回放第一手牌的帧（不按真实速度）

# 测量实时链路：延迟、丢帧、字段覆盖率、和人工标注的对比
PYTHONPATH=src:. .venv/bin/python tools/measure_aa_realtime.py --video <录像> --out <目录> \
    [--exclude 300-820] [--gold tests/fixtures/aa_reference_hands/eight_dev_checkpoint_gold_v1.json]

# 核对 8 个座位的在局状态：覆盖率，以及和人工逐座位标注的对比
PYTHONPATH=src:. .venv/bin/python tools/check_aa_seat_states.py --video <录像> [--labels <标注.json>]
# 核对轮到你时的按钮（跟注额 / 让牌 / All in）和标注是否一致
PYTHONPATH=src:. .venv/bin/python tools/check_aa_call_button.py --video <录像> \
    --labels tests/fixtures/aa_reference_hands/hero_call_button_labels_v1.json
```

浏览器会自动打开观察页，点“开始观察”。详见 [launch/mac/README.md](launch/mac/README.md)。

## 代码地图

| 位置 | 作用 |
|---|---|
| `src/poker_engine/perceptual/` | 画面采集后端（`capture/`）和视觉识别器（`vision/`：牌、公牌、底池、动作、金额等） |
| `src/poker_engine/realtime/` | 帧来源、变化检测、多帧共识、手牌边界、实时流水线 |
| `src/poker_engine/core/`、`state_engine/`、`memory/`、`confidence/` | 不可变数据合同、Decimal 金额、权威牌局状态、手牌记忆、置信度门槛 |
| `src/poker_engine/equity/` | 胜率计算：枚举、蒙特卡洛、范围对范围 |
| `src/poker_engine/strategy/` | 通用策略路由/Provider/建议；AA 规则、研究用 MCCFR；`frozen_postflop.py` 查询已保存的翻后求解结果 |
| `src/poker_engine/orchestrator/` | Fast/Slow 双路径编排，旧结果不覆盖新状态 |
| `src/poker_engine/desktop/` | AA 本地服务 `aa_server.py`（FastAPI）、会话 `aa_session.py`、画面来源 `aa_sources.py` / `aa_video_source.py`（录像当采集卡）、8 个座位的在局状态 `aa_seat_states.py`、轮到你时的按钮和跟注额 `aa_hero_controls.py`、按公共牌张数判断的街道 `aa_street.py`、牌桌数学 `aa_math.py`（胜率、底池赔率、SPR）、回合截止、分析和复查 |
| `ui/aa-live/` | AA 观察页前端（原生 HTML/JS，无构建步骤） |
| `research/` | `hu_root`（单挑已保存策略查询）、`coverage_bridge` |
| `tools/` | 离线命令行工具，其中不少是一次性研究脚本 |
| `configs/` | 识别标定、策略资产、规则配置 |
| `third_party/` | 只放第三方许可证和来源说明，不放源码或二进制 |

入口：`packaging/aa_live_entry.py` → `poker_engine.desktop.aa_server`。
Windows 上由 `launch/aa/START-AA.cmd` 启动，Mac 上由 `launch/mac/start-aa-replay.command` 启动。
私有数据位置统一由 `src/poker_engine/data_paths.py` 决定。

子系统合同见 `docs/`：`core-contracts.md`、`state-engine.md`、`confidence-gate.md`、
`orchestrator.md`、`vision-engine.md`、`capture-replay.md`、`hand-memory.md`、`serialization.md`。

## 私有数据

- 录像、截图帧、标注和模型都在仓库外的数据目录里，默认是 `~/Projects/PokerSense_data`，
  可以用环境变量 `POKERSENSE_DATA_ROOT` 改；Windows 上默认仍是 `G:/`。
  数据目录下面是 `PokerSense_private/` 和 `PokerSense_archive/`，对应原 Windows 的 `G:\` 结构。
- 旧配置里写的 `G:/...` 和旧仓库路径 `C:/Users/Administrator/WorkBuddy/扑克/PokerSense/...`，
  会被 `data_paths.resolve_legacy_path` 自动映射到本机。新代码请直接用 `data_paths`，不要再写死路径。
- **仓库是公开的。**录像、截图、模型权重、第三方求解器源码或二进制、密钥、`.venv`
  一律不提交。测量产生的逐帧日志也放在数据目录里，报告只写汇总数字。
- **保留区间不能碰**：9 月 9 日 AA 录像（`aa_phone_record_20260909_031030_54322c62`）的
  300–600 秒从未被看过，留作独立验收；600–820 秒以前评估时用过。开发、调参、测量时
  一律跳过 300–820 秒（`--exclude 300-820`）。9 月 4 日的 `session_001` 是 9 座布局，
  和现在的 8 座识别不匹配。

## Git 与 GitHub 规则

- `main` 是唯一的长期分支，并且受保护：不能直接推送或强推；只能通过 PR 合并，
  并且三项检查 `review-hygiene`、`test (macos-latest)`、`test (windows-latest)`
  必须通过，分支还要先和 main 同步。
- 固定流程：从最新 `main` 开短分支 → 提交 → 推送 → 开 PR → CI 通过 →
  用 merge commit 合并 → 删除分支（仓库已设置合并后自动删除）。
- 分支命名：`feat/`、`fix/`、`docs/`、`chore/`、`research/` 加简短英文描述。
- 一个 PR 只做一件事；main 必须随时能跑。PR 描述用中文写清：做了什么、怎么验证的、还剩什么。
- 修改 `.github/workflows/` 需要 `gh` 带 `workflow` 权限。
- 2026-10-06 大扫除前的所有分支，都保存为 `archive/<原分支名>` 标签；旧 Draft PR 已关闭。

## 文档规则

- `AGENTS.md`（本文件）：现状和规则，保持简短。`CLAUDE.md` 只是引用它。
- `docs/ROADMAP.md`：方向、里程碑、待决问题。阶段完成时更新它。
- `docs/*.md`：子系统合同。改了接口就更新对应文件。
- `docs/archive/`：历史资料，只读，不再更新，里面的链接可能失效。
  旧版 342KB 工作日志在 `docs/archive/AGENTS-legacy-20261006.md`；
  旧代码注释里写的“见 AGENTS.md”，指的就是这份旧日志。
