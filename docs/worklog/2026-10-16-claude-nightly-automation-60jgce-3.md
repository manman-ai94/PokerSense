### 2026-10-16 · `claude/nightly-automation-60jgce`（只改第二台电脑安装说明的 PR 也跑测试）
- 做了什么：CI 把只改 `docs/` 里说明文字的 PR 当成“只改文字”，跳过 Windows 和 macOS 测试；可 `test_setup_texassolver.py` 会读 `docs/second-seat-windows.md`，核对里面的安装命令。只改这份说明的 PR（比如开着的 #51）以前不跑这个测试，说明写错了也看不出来。
- 怎么做的：把它加进 `tools/ci_changes.py` 的“测试会读的文件”名单。
- 怎么验证的：新测试用例在 main 上失败、改后通过；`test_ci_changes`、`test_setup_texassolver` 和 flake8 通过。
- 还剩什么：无。
