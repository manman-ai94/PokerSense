### 2026-10-15 · `claude/nightly-automation-60jgce`（改动三道关的 --out 写相对路径就坏）
- 做了什么：`tools/flywheel_gates.py` 的 `--out` 以前照原样传给两个版本的工具，而工具在各自的代码目录里跑：写相对路径时，上一版的结果写进了临时工作区（跑完就删），这一道关就报“重放失败”或“模拟失败”。现在先把 `--out` 换成绝对路径，两个版本都写到同一个地方。
- 怎么做的：`main` 里 `args.out = args.out.resolve()`，在建临时工作区之前；`--frames` 本来就换成了绝对路径。边池那个线程报的问题。
- 怎么验证的：先加测试复现（在临时目录里用相对的 `--out`，旧代码传给工具的是相对路径、重放失败），改后 `tests/tools/test_flywheel_gates.py` 全过，flake8 干净。
- 还剩什么：无。
