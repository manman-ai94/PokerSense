# AA8 下注显示空白与OCR未知的独立诊断

2026-09-09。新增`tools/aa8_wager_visibility.py`，未更改CandidateReader、
策略或现有下注数值。所有状态的`value`始终为None，不向资金层注入0。

接口：`AA8WagerVisibility(reference1500).read(image, scene_supported=True,
unobstructed=True)`。两个外部门控默认False，未确认场景或遮挡时只报UNKNOWN。
这四个开发检查点的外部门控来自人工核对，不声称已有自动全场景遮挡识别。

## 正向证据

- VISIBLE_COIN_CANDIDATE：匹配到币标（>=0.85），即使金额OCR失败也不能说空白。
- VISIBLE_EMPTY_CANDIDATE：ROI全部像素为明确绿色桌布、没有亮中性色文字、
  没有暗边界且币标未命中。一像素异常也保持UNKNOWN，没有容错比例补齐。
- UNKNOWN：其他情况，包括缺少场景/无遮挡门控、模糊文字、裁切、遮挡。

固定使用八座专用下注ROI；不读取中间底池数值来冒充某座下注。输出同时记录
桌布覆盖率、文字像素、暗像素、币标分数和边缘比例。

## 已执行源绑定检查

`G:/PokerSense_private/aa8_wager_visibility_v2/report.json`记录逐帧SHA256、
源清单哈希与实现哈希。共四帧32个ROI：21个空白候选、11个币标候选。

| 帧 | 有币标座位 | 正向空白座位 |
|---|---|---|
|1500|0/1/2/3/4|5/6/7|
|2400|4|0/1/2/3/5/6/7|
|2700|1/4/5|0/2/3/6/7|
|4755|0/3|1/2/4/5/6/7|

## 不能因此推导精确本轮价格

空白是“这个矩形当前显示桌布”的视觉证据，不等于该座本轮投入为0：筹码动画、
换街收筹、弃牌后的金额显示消失、前注和其他费用显示规则仍需跨帧验证。
此外八座几何和遮挡完整性仍非独立验收结果。因此`street_wager_zero_verified`
与`exact_street_price_verified`保持false；旧price_lower_bound逻辑不变。

10项契约测试通过、flake8通过；没有访问保留集、打开设备或额外扩展实验。
