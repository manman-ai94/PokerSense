# PokerSense

德州扑克**实时策略分析**工具：用采集卡读取 AA 扑克手机画面，识别牌局，实时计算并显示策略参考。
用途是跟 AI 学打牌，不涉及资金。软件只显示分析结果，绝不自动点击或下注，人始终是唯一操作者。

*A real-time Texas Hold'em strategy-analysis tool for study: it reads the table from a capture card,
reconstructs the hand state and shows strategy references. It never clicks, bets or controls the poker
client.*

## 当前状态

开发中，还没有可用的发布版。方向和里程碑见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 快速开始（macOS）

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev,desktop,solver-tools,perceptual]"
PYTHONPATH=src:. .venv/bin/python -m pytest

# 打开观察页并回放录像帧（需要仓库外的私有数据，见 AGENTS.md）
launch/mac/start-aa-replay.command
```

## 文档

- [AGENTS.md](AGENTS.md)：项目说明、代码地图、开发和 Git 规则（人和 AI 协作者都从这里开始）
- [docs/ROADMAP.md](docs/ROADMAP.md)：方向、里程碑、待决问题
- [docs/](docs/)：各子系统的合同文档
- [docs/archive/](docs/archive/)：2026-10-06 之前的全部历史资料

## 隐私

录像、截图、标注和模型都放在仓库外，不提交到 GitHub。
