# 策略层任务4：AA规则V2与规则绑定Provider门禁

2026-09-09。状态：规则合同及影子Provider门禁完成；没有真实策略资产或Advice。

## 为什么单独做V2

旧`GameConfig`可表示盲注、单一ante和抽水，但不能表达straddle位置、翻前
行动起点、最小加注重开，也不能把某份策略资产与完整房间规则绑定。直接修改
旧合同会破坏已冻结V1，因此本轮全部采用新增模块，原冻结280文件保持不变。

## 可配置规则

`AARuleProfileV2`精确使用Decimal，支持：

- 6/7/8人、8个物理座位；
- 小盲、大盲、最小筹码；
- 无前注或每位发牌玩家前注；
- 无straddle、UTG强制straddle、显式可选UTG straddle；
- 抽水百分比、BB封顶；
- 所有底池或见翻牌才抽水；
- 精确、按最小筹码向下/向上取整；
- 抽水按所有主/边池比例分配、主池优先或未确认；
- `simulation`和`live_verified`分离；未知抽水条件/取整不能标live_verified；
- 所有金额必须对齐最小筹码。

每一项进入规范JSON并生成SHA256规则指纹。改人数、盲注、前注、straddle、
抽水或取整都会改变指纹，旧策略资产不能静默命中新房间。

当前`configs/game/aa-shadow-rules-v2.json`是开发模拟：1/2、逐人前注2、
UTG straddle4、3%、2BB封顶、向下取整、按所有底池比例分配。数值来自已见画面标签和用户提供的
可配置抽水说明，但平台的完整结算方式没有验证，因此明确
`verification_status=simulation`，不能启用live策略。

## 强制投入计划和对账

根据已确认庄位和实际参与座位，自动派生BTN/SB/BB/UTG等位置，分别记录
ante、SB、BB、straddle组件、翻前第一行动者、当前强制下注额和最小加注到。
观察扣款必须提供8个物理座位的精确值，逐座与计划比较。

完全一致且规则live_verified时才可能`strategy_eligible=true`。任何额外或缺失
扣款只输出`UNALLOCATED_OPENING_DIFFERENCE`，不自动解释为抽水、保险、
蘑菇或暴击。

已有第一手7人开发扣款与该模拟规则比较：4号多2、7号多6，总计多8。
这和“累计投入减显示底池长期差6”是两个不同口径：其中2已经进入显示底池，
另外6没有。两者都不能仅靠算术命名。第二手开局6号余额缺失，不能伪造为0
完成逐座对账。

## 抽水估算

只有应用条件和取整方式都明确时才计算；见翻牌才抽水且是否见翻牌未知时返回
UNKNOWN。先按百分比计算、受BB封顶限制，再按最小筹码取整且不能超过封顶。
结果始终注明“来自配置”，不冒充平台实际扣款证据。

## 规则绑定影子Provider

`AARuleBoundShadowRouter`包在现有`StrategyRouter`外：

1. 规则必须live_verified；
2. 策略资产绑定指纹必须与当前规则完全一致；
3. 强制投入计划与规则指纹一致；
4. 观察开局逐座完全对账；
5. DecisionContext的盲注/前注/抽水与规则一致；
6. 当前仅允许preflop unopened；straddle后的最小加注必须正确；
7. 后续raise所需的最后完整加注增量尚未权威化，所以继续阻断；
8. 只返回`SHADOW_CANDIDATE`，永远`advice_emitted=false`、
   `strategy_eligible=false`。

测试中使用合成FakeProvider验证门禁连接；它不是产品策略资产。当前内置RFI
范围没有绑定这套ante/rake/straddle指纹，不会被调用。

## 验证与剩余工作

规则和Provider门禁24项聚焦测试通过，覆盖6/7/8人、真实开发差额、可选与
强制straddle、规则指纹、封顶/取整/no-flop-no-drop、模拟阻断、资产错绑、
开局不一致、错误最小加注及后续行动线阻断。

尚未连接用户设置页面；尚无经过验证的AA规则策略资产；尚未运行真实Provider、
权益或Advice。下一步是建立版本化多人策略资产/权益影子计算，而不是绕过规则
门禁复用无前注RFI表。

最终全仓3165项通过、1项跳过、2条依赖弃用警告；flake8为0（沿用已有
`aa_record_session.py`排除项）。V1冻结280个文件重新计算SHA256，0个变化。
