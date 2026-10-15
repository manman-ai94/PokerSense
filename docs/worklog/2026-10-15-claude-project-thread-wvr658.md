### 2026-10-15 · `claude/project-thread-wvr658`（杜每天上传的录像自动复盘）
- 做了什么：新工具 `tools/tester_review.py`：`run` 读同事上传的录像文件夹（窗口日志 `frames.jsonl`、`recording.json`、`upload.json`，不看视频），只列出问题：电脑读帧太慢、各项识别低于三星基准的 90%、轮到他没给建议的次数和原因、重放不下去和读错的手比 Mac 多一倍以上、级别没读出、能统计对手的手太少；写复盘单（只有汇总）和给总控的三行；`population` 把这些手（他自己的座位除外）加进 AA 真人统计。
- 怎么做的：复用 `p30_acceptance.field_coverage/compare`、`aa_session_report`、`aa_population_stats`；状态（复盘过哪些、对手的手）放私有数据目录 `PokerSense_private/tester-review/`，同一场不复盘第二次，下一场写“和上次比”。
- 怎么验证的：7 个单元测试；杜 10/14 那场 18 分钟录像：每秒读 2.3 帧（Mac 7.8）、识别一帧 360 毫秒（Mac 83）、底池 0%、轮到他 36 次 9 次没建议、24 手 15 手重放不下去、能统计对手的 12/24；AA 真人统计 401 → 414 手，和手工 `aa_population_stats build` 结果逐项一样。
- 还剩：每天早上由排好的任务跑一次（云端读 Mac 上的云盘文件夹）；真人统计只放私有目录，要不要换进包里的 `aa_real_stats` 由策略那边定。
