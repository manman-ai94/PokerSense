### 2026-10-15 · `claude/sim-fidelity-plac0g`（保护裁判：一个 PR 不能既改策略又改裁判）
- 做了什么：review-hygiene 里加一道检查：PR 同时改了策略文件和裁判文件（模拟对手和牌桌、统计数字、拟合、三道关、验收线、检查本身）就失败，要拆成两个 PR。两份清单放在 `configs/evaluator-protection.json`。
- 怎么做的：`tools/ci_changes.py` 本来就按 PR 的改动判断要不要跑测试，现在顺带对照清单（只在 PR 上查，推到 main 不查）；没改工作流文件。
- 怎么验证的：测试：清单里每一项都对得上仓库里的文件、没有文件两边都算；同时改两边的 PR 失败，只改一边、文档、共用文件（bots.py）不拦；推送不拦。拿最近 40 个合并的 PR 回放：#48（改了工作流和求解器）会被拦，其余都过。flake8。
- 还剩：共用的文件（bots.py、strength.py、spots.py、replay.py）两边都不算，夜间代码体检留意。
