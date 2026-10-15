### 2026-10-15 · `claude/nightly-automation-60jgce`（记分牌里一个求解超时，整场模拟就停了）
- 做了什么：记分牌里的求解器策略（solver_turn、solver_flop 等）遇到一次求解超过 300 秒，以前整场模拟报错退出（#48 加了超时强杀，记分牌这边没接住）；现在这一步改照翻前/基础策略打，记成“solver_timeout”，模拟继续。
- 怎么做的：`solver_bot.py` 的 `decide` 接住 `SolverTimeout`，和算不了的局面一样交给基础策略；实时窗口那条路本来就接住了，不变。夜间代码体检复查 #48 时发现。
- 怎么验证的：先加测试复现（假求解器每次超时，旧代码整场报错），改后 `tests/scoreboard/test_solver_bot.py`、`tests/desktop/test_aa_solver_advice.py` 全过，flake8 干净。
- 还剩什么：超时次数多时，这一场的成绩会受机器快慢影响，看记分牌里的 solver_timeout 计数。
