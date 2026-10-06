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

目标是“实时分析 v1”，按 [ROADMAP](docs/ROADMAP.md) 的里程碑推进。
已确定的方向：不自研全街策略，也不自研求解器；单挑翻后用现成开源求解器，
多人底池先给数学参考并明确标注。

## 开发环境（macOS Apple Silicon）

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev,desktop,solver-tools,perceptual]"

# 全量测试约 10 分钟；pyproject 里已默认 -q
PYTHONPATH=src:. .venv/bin/python -m pytest
.venv/bin/python -m flake8 src tests tools research/hu_root research/coverage_bridge
```

- 支持 Python 3.11–3.13，本机用 3.12。依赖版本在 `pyproject.toml` 里精确锁定，不要放宽。
- 已知问题：在 Mac 本机上，`tests/desktop/test_aa_hand_input_ui.py` 和
  `tests/perceptual/test_quartz_capture.py` 共 13 个测试失败（大扫除前就存在，GitHub CI 上通过）。
  没装 Node 时，JS 相关测试会自动跳过。
- 采集卡后端目前只支持 Windows 的 MSMF/DSHOW，macOS 支持待做（ROADMAP 里程碑 0）。

## 代码地图

| 位置 | 作用 |
|---|---|
| `src/poker_engine/perceptual/` | 画面采集后端（`capture/`）和视觉识别器（`vision/`：牌、公牌、底池、动作、金额等） |
| `src/poker_engine/realtime/` | 帧来源、变化检测、多帧共识、手牌边界、实时流水线 |
| `src/poker_engine/core/`、`state_engine/`、`memory/`、`confidence/` | 不可变数据合同、Decimal 金额、权威牌局状态、手牌记忆、置信度门槛 |
| `src/poker_engine/equity/` | 胜率计算：枚举、蒙特卡洛、范围对范围 |
| `src/poker_engine/strategy/` | 通用策略路由/Provider/建议；AA 规则、研究用 MCCFR；`frozen_postflop.py` 查询已保存的翻后求解结果 |
| `src/poker_engine/orchestrator/` | Fast/Slow 双路径编排，旧结果不覆盖新状态 |
| `src/poker_engine/desktop/` | AA 本地服务 `aa_server.py`（FastAPI）、会话、回合截止、分析和复查 |
| `ui/aa-live/` | AA 观察页前端（原生 HTML/JS，无构建步骤） |
| `research/` | `hu_root`（单挑已保存策略查询）、`coverage_bridge` |
| `tools/` | 离线命令行工具，其中不少是一次性研究脚本 |
| `configs/` | 识别标定、策略资产、规则配置 |
| `third_party/` | 只放第三方许可证和来源说明，不放源码或二进制 |

现有入口：`packaging/aa_live_entry.py` → `poker_engine.desktop.aa_server`
（Windows 上由 `launch/aa/START-AA.cmd` 启动）。Mac 上的启动方式还没验证。

子系统合同见 `docs/`：`core-contracts.md`、`state-engine.md`、`confidence-gate.md`、
`orchestrator.md`、`vision-engine.md`、`capture-replay.md`、`hand-memory.md`、`serialization.md`。

## 私有数据

- 录像、截图帧、标注和模型都在仓库外：`~/Projects/PokerSense_data/drive-G/`，
  目录结构对应原 Windows 的 `G:\PokerSense_archive` 和 `G:\PokerSense_private`。
- 旧代码和配置里写死的 `G:/...`、`C:/...` 路径需要改成可配置的，不能直接用。
- **仓库是公开的。**录像、截图、模型权重、第三方求解器源码或二进制、密钥、`.venv`
  一律不提交。

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
