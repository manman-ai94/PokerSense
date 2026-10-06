# WPK 动作与金额字段实测 v1

日期：2026-09-08。测量工具与来源绑定完成；自动识别接入状态链仍为PARTIAL。
本轮没有放宽任何生产门槛，也没有把候选动作变成真实行动事件。

## 实际结果

新增 `tools/probe_wpk_observation_fields.py`，直接使用生产配置下的
`VisionEngine.process`。对两个已归档窗口读取96个独特来源帧（重叠帧先核对像素及PTS），
在8个独立于模型输出、由agent目检标注的检查点评分。这里的“独立”仅指标签不由识别器
生成；素材属于反复使用的同一手开发录像及下一手前注，不是独立牌局留出验收。

| 字段 | 可读正样本 | 正确接受 | 错误接受 | 拒答 | 负样本正确拒绝 / 总数 |
|---|---:|---:|---:|---:|---:|
| 顶部底池数字 | 5 | 3 | 0 | 2 | 3 / 3 |
| 8座位可见余额 | 63 | 21 | 0 | 42 | 1 / 1 |
| 已显示动作文字 | 35 | 0 | 0 | 35 | 29 / 29 |

合计136项字段检查。可读筹码覆盖率仅33.3%，动作覆盖率0%；不能以“未发现错误接受”
宣称系统识别已好用。96帧只是在该工具中处理的样本数，不等于96帧全部完成真值核验。
采样之间有间隔，不声明已重建连续动作，也不计算真实采集卡时延。

## 已定位缺口

1. 生产 `calibration.json` 无动作字段独立标定；原始字形候选不得越过门槛直接用。
2. 当前 ACTION ROI 只有座位0–5，座位6、7缺失。本手关键对手位于座位6。
3. 动作模板只有bet/call/check/raise，缺fold/all_in。弃牌/全押还可能显示在头像内，
   与普通行动徽标的位置不同，不能只复制同一个小识别框。
4. 筹码低覆盖不仅是边界分数：例如若干座位分数低于0.1，需检查识别区域、字形分割
   和亮暗状态。未证明这些都是同一根因，本轮不降阈值或补数字。

原始候选、最终字段状态、分数和缺失ROI原因均保存在报告中。动作文字可能持续多帧，
也不是“当前轮到谁”的证据；不会每看到一次文字就记一次下注。

## 重要勘误：逻辑池不等于同帧显示值

重新查看原始f8560：Hero余额64、桌前跟注62，顶部显示156，下方池显示94。
旧审阅夹具按跟注完成阶段写了逻辑池218，但字段名为`raw_total_pot`，容易被误当成
截图直接读数。新画面真值明确写156，逻辑参考218另存，并标注不能作原子状态一致性验收。
画面中存在不同字段未同步变化的现象；其服务端时点或具体动画延迟尚未测量。

未改写旧夹具、旧报告或证据。`verify_reviewed_checkpoints`文档及新生成账本报告明确
说明检查的是逻辑阶段目标，不是同帧OCR一致性；两份前序报告均已添加勘误。
这不改变最后总额584、退回238、可争夺346及Hero净余额324的结算核验。

同时保留负样本：“总底池”文字不是数字0、被“高牌”遮挡的余额不是可观测238、
8836下一手前注不是上一手费用。

## 来源、复现与验证

真值：`tests/fixtures/wpk_reference_hands/aq_observation_v1.json`。
测试：`tests/tools/test_wpk_observation_fields.py`。
私有输出：`G:/PokerSense_archive/wpk_video_first_20260908/observation_fields/aq_measured_v1/`。

先验证窗口既有SHA256清单，再校验每个PNG文件哈希及像素哈希；绑定来源视频哈希与
容器PTS，冻结真值、源码/配置和输入清单。推理后再次核验输入及源码未变化。
这里复用已解码且来源绑定的PNG，不伪称本轮重新解码或重算了12GB原视频的哈希。
旧输出不覆盖，初次工具发现缺失ROI时的未完成目录也保留，不计作成功结果。

复现时用独立解释器：
`C:/Users/Administrator/.codex/runtimes/pokersense-v6-clean-20260908/Scripts/python.exe`，
设置 `PYTHONPATH=src`、`PYTHONUTF8=1`、`PYTHONNOUSERSITE=1`，执行：

```powershell
python -m tools.probe_wpk_observation_fields `
  --review tests/fixtures/wpk_reference_hands/aq_observation_v1.json `
  --hand-window G:/PokerSense_archive/wpk_video_first_20260908/hands/aq_allin_8240_8900 `
  --cash-window G:/PokerSense_archive/wpk_video_first_20260908/settlement/credit_8780_8845 `
  --output G:/PokerSense_archive/wpk_video_first_20260908/observation_fields/aq_recheck
```

`python`需指向上述解释器；输出必须为新目录。检查点评分在推理完成后进行，
不向识别器提供审阅动作、后续底牌、逻辑余额或保险金额。

新增15项测试覆盖：零/空值分离、候选拒答、金额精确比较、画面与账本差异、缺失ROI、
错误真值结构、图片篡改、不同视频/缺帧和禁止覆盖旧报告。完整回归2487通过、
1项Quartz平台跳过、2项依赖弃用警告；Flake8与差异检查通过。相同输入与源码重复运行，
96帧报告逐字节一致（第二份为`aq_measured_repeat_v1`）。

## 下一轮工作

先补齐离线候选的8座位动作区域、弃牌/全押字形和正负样本覆盖，同时针对筹码低分
读数定位分割/区域问题。调参与验收按牌局分开，不把本批开发数据重复当作留出集。
达到字段覆盖门槛后再处理同帧不同步、重复徽标及漏多步动作，接入状态事件层。
未过这些门槛前，生产`requires_revalidation=true`不变，不发出行动建议或盈利结论。
