### 2026-10-15 · `claude/nightly-automation-60jgce`（装新版前复查：“街道”这一项奖励了留着上一手的旧街道）
- 做了什么：识别覆盖率里的“街道”以前只看读没读出，两手之间（公共牌清空、底池 0）一直留着上一手翻牌/转牌/河牌的旧版本反而得分高（10/15 杜的录像：旧版 98.4%，正确清掉的新版 96.0%，复查没过）。现在两手之间显示“不知道”或翻前算对，显示翻后街道算错；公共牌没了、底池也没读出却还是翻后街道，同样算错。
- 怎么做的：`tools/p30_acceptance.py` 新函数 `street_right`，`field_coverage` 的 street 改用它；复查工具、同事复盘、P30 验收都用这一个函数。底池读到筹码时（摊牌公共牌闪一下）留着的街道照旧算对；其余门槛一个没动。
- 怎么验证的：先用合成帧加测试复现（留旧街道的版本 100%、清掉的 20%），改后反过来（20% 和 100%）；`test_p30_acceptance.py`、`test_release_check.py`、`test_tester_review.py` 全过，flake8 干净。
- 还剩什么：`configs/acceptance/second_seat_baseline_v1.json` 的街道基准是按旧算法量的，下次在 Mac 上用同样的日志重跑 `p30_acceptance.py baseline` 更新。
