# WPK 八座动作与筹码离线候选 v1

日期：2026-09-08。离线候选实现及对照检查完成；识别覆盖仍为PARTIAL，生产不放行。

## 本轮实际改变

- `tools/wpk_field_candidate.py`：八座双区域动作候选。下注、跟注、加注、过牌读
  头像上方徽标；弃牌和全押读头像内部。六类模板齐备，包含缺失的座位6、7区域。
- `field_candidate_v1.json`：明确498×1080画布、8座区域及模板来源，位于测试夹具目录。
  拒绝未审阅画布，不自动缩放套用。工程门槛0.85、第一/第二候选差0.10，未视为校准概率。
- `tools/probe_wpk_field_candidate.py`：来源、配置、代码及模板冻结，完整保留候选分数，
  输出原/新筹码裁剪与字形分割形状供核验。
- `tools/check_wpk_field_candidate.py`：不调参检查冻结候选在后续已目检画面上的表现。

没有改生产配置或权重，没有把候选识别结果写入实时事件存储。动作是画面文字，
不是“发生了一个新动作”或“轮到该玩家”的结论。

## 开发检查结果

复用前轮96个独特缓存帧，在原8个目检点比较：

| 字段 | 原正确接受 | 候选正确接受 | 候选拒答 | 候选错误接受 | 负样本正确拒绝 |
|---|---:|---:|---:|---:|---:|
| 动作文字（35个可读） | 0 | 20 | 15 | 0 | 29/29 |
| 筹码数字（63个可读） | 21 | 33 | 30 | 0 | 1/1 |

动作候选与生产口径不同：候选门槛仅用于离线诊断，生产仍因缺独立标定而保持UNKNOWN。
筹码比较只改变裁剪区域，使用同一个生产识别器与原置信门槛；本批没有原正确接受变错
或变拒答的检查点。底池未修改，也没有宣称全字段完整状态覆盖已提高到可发布程度。

fold模板来自f8500顶部座位，all_in模板来自f8700 Hero。两张来源帧上的16个动作槽：
9正确/6拒答/1负样本拒绝；其余同手48槽：11正确/9拒答/28负样本拒绝。
必须把模板来源帧与其余开发帧分开，不能把整体20次正确当作独立测试成功。

## 筹码低分的具体证据

`stack-geometry-review.png`显示旧座位2、5的裁剪切掉数字顶部；座位7的区域混入
底池胶囊边缘。f8500诊断如下，原始候选串均未被低分门槛接受：

| 座位 | 旧裁剪分割/原始候选 | 新裁剪原始候选 | 新结果 |
|---|---|---|---|
| 2 | 25×69粘连单块，候选4 | 220，分数约0.755 | 继续拒答，不因看似正确而放宽 |
| 5 | 顶部被截，候选220，分数约0.040 | 726，分数约0.726 | 继续拒答 |
| 7 | 30×52粘连单块，候选8 | 197，分数约0.846 | 通过原门槛 |

因此裁剪问题确实存在，但不解释所有低覆盖；修好几何后仍有字形/分割/亮暗适应问题。
当前60像素宽的实验筹码区域仅在已列数字上测量，长金额、小数、布局变化未验收。

## 不调参的后续画面检查

先目检并冻结f10400、11000、11340，再使用相同候选进行检查。这些画面来自后续牌局，
但曾用于卡牌开发，不是整个项目从未接触的留出集。

- 动作：7个正样本中4正确、3拒答；17个负样本均拒绝。3次拒答均为弃牌字形。
- 筹码：23个可见数字中，旧区域5正确，新区域12正确、11拒答；1个空座负样本拒绝。
- 未发现错误接受，不表示未标注帧或其他牌局均正确。
- f11340等待审核/正在带入座位的0，只验证屏幕数字；不是可用筹码、已入局或入座成功的证明。

开发集仍未接受对手座位6的全押动画；Hero模板不能直接等价覆盖不同特效背景。
这些失败保留，未通过增加专用映射或降低阈值把它们“刷成通过”。

## 验证与产物

新增11项测试覆盖双候选冲突、低分拒答、错误画布、缺座位、越界区域、非有限阈值、
模板退化、输入副本隔离及只修改离线筹码区域。完整2498通过、1项Quartz平台跳过、
2项依赖弃用警告；Flake8通过。生产权重哈希与requires_revalidation=true保持。

私有目录：`G:/PokerSense_archive/wpk_video_first_20260908/field_candidates/`。
主产物为`v1_final/report.json`、`v1_final/stack-geometry-review.png`、
`followup_verified/report.json`；旧版本和先前检查均保留。每个目录有SHA256清单。

代码和配置由主实验冻结；后续检查要求冻结依赖哈希与当前实现一致。新模板只以
二值字形保存到私有实验目录，不把玩家截图写入仓库或替换生产模板。

使用独立解释器及既定PYTHONPATH/PYTHONUTF8/PYTHONNOUSERSITE环境，执行：

```powershell
python -m tools.probe_wpk_field_candidate `
  --baseline G:/PokerSense_archive/wpk_video_first_20260908/observation_fields/aq_measured_v1 `
  --profile tests/fixtures/wpk_reference_hands/field_candidate_v1.json `
  --output G:/PokerSense_archive/wpk_video_first_20260908/field_candidates/new_candidate

python -m tools.check_wpk_field_candidate `
  --candidate G:/PokerSense_archive/wpk_video_first_20260908/field_candidates/new_candidate `
  --window G:/PokerSense_archive/wpk_video_first_20260908/transitions/scene_10400_11500 `
  --review tests/fixtures/wpk_reference_hands/field_followup_v1.json `
  --output G:/PokerSense_archive/wpk_video_first_20260908/field_candidates/new_check
```

输出必须是新目录。下一步针对暗色弃牌、全押特效和数字分割补充可复核的字形样本，
分离开发/独立牌局校准，再接连续动作去重和状态事件；仍无需新增实战录像。
