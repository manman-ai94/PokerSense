# PokerSense 当前交接入口

状态日期：2026-09-12。此目录是换ChatGPT账号、Codex任务或其他本地编码Agent
时的唯一当前入口。旧`HANDOFF-CODEX-GPT6.md`只保留历史背景。

## 第一件事

不要立即改代码。按顺序执行：

1. 确认唯一仓库：`C:\Users\Administrator\WorkBuddy\扑克\PokerSense`。
2. 阅读本文件、`CURRENT-STATE.json`、`NEXT-TASK.zh-CN.md`。
3. 只读查看`AGENTS.md`开头的Current state；不要先加载整个16万字节历史日志。
4. 在PowerShell运行：
   `powershell -ExecutionPolicy Bypass -File handoff/2026-09-12/VERIFY.ps1 -Full`
5. 只有结果PASS且Git工作树干净，才能开始下一项任务。

如果只有网页聊天、不能访问本机终端、C盘仓库和G盘证据，则不要声称接管成功。

## 不可改变的事实边界

- 当前主线是AA扑克；WPK只保留回归。
- AA布局为8个物理座位，Hero=4，顶部0开始顺时针；策略人数参数化6/7/8。
- 手机+采集卡是认可路径；模拟器不是当前AA实战采集路径。
- 保险、种蘑菇、暴击的具体资金语义延后；正证据必须暂停普通策略。
- UNKNOWN、候选、开发回归、合成结果和单元测试不能称为独立验收通过。
- 300–600秒是V2唯一未消费的新保留区间；不得在冻结前查看或用于调参。
- 600–820秒已经被V1评估，不能重新命名为未见数据。
- 未知资金差额不得归为抽水、费用、保险、盈利或奖励。
- 不自动点击、下注或控制扑克客户端；人始终是唯一执行者。
- 不启动采集、录制、Provider、权益或Advice，除非当前用户明确要求。
- 不推送GitHub，不创建PR，不发布安装包。

## 当前工程结论

视觉和策略都还是PARTIAL。开发回归能识别大量字段，但没有独立完整手牌和
实际链路验收。策略任务1–6已建立：AA8输入桥、影子WAL、庄位/整手投入/
行动线候选、规则V2、规则绑定资产、规则感知权益、具体组合范围资产和逐手
范围跟踪器。没有真实AA范围/动作似然/策略节点；真实WAL中Provider=0、
equity=0、Advice=0。

最后已知全仓基线：3216 passed、1 skipped、2 warnings；flake8为0，排除已有
`aa_record_session.py`。以`VERIFY.ps1 -Full`当前实跑为准，不要只信这段文字。

## Git规则

- 本交接点只在本地，不推远程。
- 当前路径含中文。禁止自行执行`git checkout -b`、`stash`、`rebase`、`gc`、
  `prune`或破坏性reset。
- 不要删除旧录像、失败报告、旧冻结或历史交接。
- 新工作前检查`git status`；完成后更新`AGENTS.md`顶部Current state。
- 当前检查点使用本地tag：`handoff-2026-09-12-aa-strategy-task6`。

## 推荐读取顺序

1. `docs/AA8-RANGE-ASSET-TRACKER-TASK6.zh-CN.md`
2. `docs/AA8-ASSET-AND-EQUITY-SHADOW-TASK5.zh-CN.md`
3. `docs/AA8-RULES-AND-PROVIDER-GATE-TASK4.zh-CN.md`
4. `docs/AA8-DEALER-LEDGER-ACTIONLINE-TASK3.zh-CN.md`
5. `docs/AA8-SHADOW-LOG-BACKEND-TASK2.zh-CN.md`
6. `docs/AA8-STRATEGY-BRIDGE-TASK1.zh-CN.md`
7. 需要视觉细节时再读`docs/AA8-BASE-VISUAL-ITERATION-V5.zh-CN.md`。

不要从旧聊天推断完成度；仓库、Git、SHA256和当前测试输出才是事实来源。
