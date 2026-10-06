# AA8 基础视觉预声明验收合同

只针对用户当前同意的基础视觉范围；特殊机制具体规则和资金语义延后。
本工具不修改V1原13字段全功能门禁，不把旧失败改成成功，不运行采集或预测。

新增 `tools/aa8_base_acceptance_v2.py` 及17项聚焦测试；测试通过，lint通过。

## 结果名称及边界

基础10字段：actor、street_wagers、actions、pot、stacks、street、hand、
participation、hero_cards、board_cards。基础通过时仅输出BASE_VISUAL_PASS，
仍然full_visual_acceptance=false和strategy_eligible=false。缺任一必要证据
输出BASE_VISUAL_PARTIAL；合成测试的PASS不构成真实基础视觉验收。

## 必须预先声明

`--template`打印declaration空模板，需填UTC声明时间、scope配置SHA和硬件
测试最短时长。声明必须早于保留集源画面审核及预测，并与scope配置、门禁
实现一起包含在候选冻结中。全部登记完整手/全部拥有帧不得按预测表现删除。

完整证据manifest的每个条目都包含path和sha256：scope、declaration、freeze、
registry、pool、gold、predictions、prediction_report、hardware。模型冻结
实际文件、预测报告及JSONL哈希、源池与登记清单、gold源池身份、硬件冻结
身份必须匹配。预测报告必须明确没有使用labels，开始时间与gold收据一致。

```powershell
python -m tools.aa8_base_acceptance_v2 --template
python -m tools.aa8_base_acceptance_v2 --manifest <已冻结并绑定的基础验收证据清单.json>
```

本轮没有创建新的冻结或验收证据清单，没有读取300–600秒新保留画面。

## 真值、保护与恢复

每个拥有帧必须有完整10字段status/value记录。普通支持场景需要独立源画面
审核scene=supported，UNKNOWN场景不能当普通；每手需完整人工行动机会帧
登记。每字段至少有一个required帧，required全部自动正确；已知行动时点不
允许掩盖成无行动。模型仍canonical_verified=false的动作/因果投入或非权威
手牌身份不能因为本期范围缩小就自动KNOWN。

特殊阶段仍在原手和原帧中保留。gold必须明确源审核、对应源SHA及哪种模式，
模型必须确实输出相应guard，而不是只返回未知。相关下注字段安全拒识；
字段豁免需要同帧源证据与special_ui/transition/occluded/no_action理由，不是
运行时收据自动豁免。任何optional帧KNOWN预测仍须匹配KNOWN真值。未知资金
必须UNALLOCATED，不能改成抽水/盈利。

特殊阶段之后恢复普通状态时，收据需resume_evidence，其中
fresh_context_verified=true，source_frames均在最后特殊帧之后且不晚于当前帧。
这是必须提供的恢复证据接口，不表示当前candidate已实现或证明了它；没有
证据时门禁失败，不能直接沿用旧投入状态。

硬件仍需明确授权、目标设备、端到端运行、新鲜度、延迟预算、断连/恢复及
零未解释间隔/未发现陈旧帧/崩溃的真实报告；未知不能写0。时长由预声明配置，
没有擅自设置一个固定时长来增加门槛或削减要求。

当前没有完整独立10字段真值、对应冻结预测与实际硬件证据，因此本合同
准备完成不等于基础视觉已经通过，更不等于全功能或实战策略可用。
