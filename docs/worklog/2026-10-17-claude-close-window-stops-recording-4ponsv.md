### 2026-10-17 · claude/close-window-stops-recording-4ponsv（关掉黑色窗口等同于点“停止”）
- 做了什么：主人 10-16 21:09 那场关掉终端窗口时，程序被系统当场结束：录像没收尾、没有 `recording.json`，体检单、场次包和上传都没做。现在关掉终端 / 控制台窗口、注销关机、新窗口顶掉旧窗口、Ctrl-C，都和点“停止”一样：录像存好，体检单和场次包在后台做完，没传完的录像由一个后台进程接着传。
- 怎么做的：`aa_live_entry.on_close`（Mac/Linux 接 SIGHUP、SIGTERM；Windows 用 SetConsoleCtrlHandler 接关窗口、注销、关机）→ `close_window`（`aa_session.stop` 后 `aa_after_session.after_close`）；场次包进程在 Windows 上不再挂在窗口的控制台上，做的时候留 `flywheel/building`，任何上传都等它做完；一台电脑同一时间只一个上传（`upload/upload.lock`，进程结束就放开）；关窗口时结束窗口自己起的 rclone，后台 `python -m poker_engine.desktop.aa_upload` 传一遍就退出。顺手修夜间代码体检的上传线程被状态查询打断（`_check` 一次赋值、上传里只读一次、一轮出错只记日志再试）。
- 怎么验证：新测试：真发 SIGHUP / SIGTERM 能收尾；窗口进程被杀后场次包照样做完；上传到一半关窗口，云盘里没有半个文件、没有 upload.json，接手的上传补完；场次包没做完不上传；锁随进程放开；体检的复现测试在 main 上失败、在这里通过。desktop 测试和 flake8 全过。
- 还剩什么：Windows 真关控制台窗口只在杜的电脑上装了以后才看得到（CI 只测得到接口）；20261016-210927 那场的场次包由 Mac 那边补做。
