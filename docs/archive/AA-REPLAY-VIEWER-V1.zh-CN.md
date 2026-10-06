# AA 冻结回放界面

界面只读取SHA为
`7f86f4cd631dfae997b2fe7dc8ce42fda819f6b52d8b0127f56e6173e18161bc`
的observations.jsonl，严格要求连续0–1800共1801帧。不是采集入口，不执行
识别器或策略。依赖项目desktop开发环境的FastAPI、uvicorn。

在本分支仓库根目录使用PowerShell启动（把路径替换为该已授权冻结日志）：

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
python -m tools.aa_replay_viewer --observations '<冻结observations.jsonl完整路径>' --port 8766
```

浏览器打开 `http://127.0.0.1:8766`。支持上一帧、下一帧、左右键、时间滑块、
输入帧号后点击跳转、播放/暂停（每秒10帧）。终端Ctrl+C停止服务。
仅绑定127.0.0.1；不读取原视频，也不提供任意文件下载或实时采集路由。

每帧显示画面来源SHA、冻结结果SHA、源帧号与时间、hero/公共牌、9槽筹码及
部分可见动作字样。这里是早期九槽回放，不套用后来的八槽配置。
pot、seat_presence、current_actor、full_actions及special_modes明确标记
“未实现”，不可把局部动作字样当成完整动作。参与状态沿用日志，UNKNOWN显示
“未实现（源值UNKNOWN）”；源gap_reset或不支持场景有明确失效说明。

该冻结日志没有数值置信度及细分拒识原因。界面如实显示“未记录”，不凭空生成
百分比或推断具体识别失败原因。切帧请求开始即清空字段，失败时保持清空；
乱序返回通过请求序号丢弃。输出始终strategy_eligible=false，不代表实战可用。

验证：已实际打开页面，帧152显示Jc/9h，帧1261清空hero；0和1800可访问。
focused测试覆盖未实现强制标记、未知清空、错误SHA拒绝、边界路由及输入不变。
