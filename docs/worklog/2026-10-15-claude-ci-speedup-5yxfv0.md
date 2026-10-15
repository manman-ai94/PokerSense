### 2026-10-15 · `claude/ci-speedup-5yxfv0`（工作记录改成每个 PR 一个文件）
- 做了什么：新记录写进 `docs/worklog/<日期>-<分支名>.md`，不再直接改 `docs/WORKLOG.md`；新工具 `tools/worklog_rollup.py` 把这些文件按新到旧并进 WORKLOG“记录”最上面并删掉，每晚例行检查跑一次（单独一个 PR）。
- 起因：#58 加的 union 只对本地 git 管用，GitHub 网页照样报冲突、不跑检查（#58 合 main 三次，每次本地自动合并，GitHub 仍报冲突）；两个 PR 不碰同一个文件才不会冲突。
- 怎么验证的：roll-up 的单元测试（按日期、同一天按 git 加入时间排、空文件不动、试跑不改）；在仓库上 `--dry-run` 只认出这一条；flake8。
