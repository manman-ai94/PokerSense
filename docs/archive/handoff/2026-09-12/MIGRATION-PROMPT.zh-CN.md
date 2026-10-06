# 给新账号或新模型的启动提示

请复制下面整段作为第一条消息：

> 你接手本机PokerSense项目。唯一仓库是
> `C:\Users\Administrator\WorkBuddy\扑克\PokerSense`。
> 先完整阅读`handoff/2026-09-12/START-HERE.zh-CN.md`、
> `CURRENT-STATE.json`和`NEXT-TASK.zh-CN.md`，再运行
> `powershell -ExecutionPolicy Bypass -File handoff/2026-09-12/VERIFY.ps1 -Full`。
> 验证PASS且Git工作树干净前不要改代码。以仓库、Git、SHA256和实跑测试为
> 事实来源，不依赖旧聊天。不要读取300–600秒新保留数据，不启动采集、
> Provider、权益、Advice或任何游戏操作，不推远程。继续NEXT-TASK中的唯一
> 当前任务，不重复已完成的策略任务1–6；UNKNOWN/候选/合成结果不能算通过。

如果新工具无法访问本机终端、C盘和G盘，让它先明确报告`BLOCKED`，不要让它
根据粘贴的文档假装已经验证文件。
