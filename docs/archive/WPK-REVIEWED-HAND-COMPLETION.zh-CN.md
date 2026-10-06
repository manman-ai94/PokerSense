# WPK 审阅手牌结算 v1

日期：2026-09-08。审阅输入的河牌—摊牌—毛派奖—现金观测重放 **PASS**；
费用拆分 **PARTIAL**，自动 OCR→状态与策略效果尚未验收。该结果不是实战发布许可。

后续像素核验勘误：f8560顶部显示156，而跟注后逻辑池为218；此前账本的
`raw_total_pot=218`不能当作该帧直接OCR真值。此差异不改变最终346毛派奖、324余额
及22未归因差额，但削弱“金额检查点即同帧画面一致”的表述。见
[字段实测报告](WPK-OBSERVATION-FIELDS.zh-CN.md)。旧夹具及历史产物保留，新增独立画面真值。

## 本轮完成了什么

新组件 `src/poker_engine/state_engine/reviewed_completion.py` 在同一 PokerKit
下注会话上继续重放，保留原有下注 API 和19个下注状态，增加11个结算节点，合计30个。
项目独立的五张牌评估器及主/边池计算对获胜者、派奖金额进行交叉核验，要求与
PokerKit 一致。全部状态均通过项目 Core 序列化往返校验。

这是已审阅输入的离线账本，不是自动视觉事件。没有添加 Frozen Core 事件枚举，
也没有接入实时事件存储、自动操作客户端或改变生产识别阈值。

## 真实录像核验结果

来源：原 session_002 的 AcQh 参考手牌，主窗口8240–8900；新增顺序解码
8780–8845共66帧，用于审阅结算余额。原录像、原手牌夹具和旧输出保留。

| 来源帧/阶段 | 证据或规则结果 | 解释边界 |
|---|---|---|
| 最后跟注及退款 | 总额584，退回对手238，可争夺池346 | 规则退款不等于该帧已显示到账 |
| 8700 | Hero AcQh、对手 KcAh，公共牌 Jh5sQs9s | 摊牌后信息不回灌较早决策 |
| 8720 | “已投保12”提示 | 不是已确认扣款交易 |
| 8760 | 河牌8c；Hero获胜，毛派奖346 | 派奖节点表示规则应得金额，不表示现金到账时点 |
| 8760 | “未击中保险，结算时将扣除保费” | 宣布扣费，不足以确定实际账户及完整费用拆分 |
| 8793 | 本次连续核验区间中首次可见Hero余额324 | 8780–8792仍显示0；不换算成服务端结算延迟 |
| 8833–8835 | 对手座位6余额238直接可见 | 此前被“高牌”文字遮挡，无须再依赖跨手反推 |
| 8835 | 全部8个座位余额可见 | 完成本手逐座位现金观测覆盖 |
| 8836 | 下一手前注开始，Hero322、座位6为236 | 明确排除出本手费用 |

8835的源座位0–7余额依次为：324、358、220、365、194、726、238、197。
Hero毛派奖346与可见净余额324相差22；其抽水、保险或其他费用构成仍为UNKNOWN，
不按3%或提示12硬凑。保险信息独立保留，重复余额观测不重复扣账。

每个节点检查：玩家余额总和 + 尚在池中金额 + 未归因净流出 = 起始筹码2644。
原跟注前条件投影仍为补64、可争夺346、退回238、无费用门槛32/173，
不使用后来的对手底牌、河牌或净余额。

## 产物与复现

- 新补充夹具：`tests/fixtures/wpk_reference_hands/aq_completion_v1.json`。
- 新测试：`tests/state_engine/test_reviewed_completion.py`。
- 现金帧目检工具：`tools/review_wpk_cash_frames.py`。
- 扩展重放入口：`tools/replay_wpk_reviewed_hand.py`，原下注模式保持可用。
- 私有报告：`G:/PokerSense_archive/wpk_video_first_20260908/state_replay/completed_aq_v1/report.json`。
- 现金证据及拼图：`G:/PokerSense_archive/wpk_video_first_20260908/settlement/credit_8780_8845/`。

原21项证据引用，加9项补充引用，重叠3帧，合计27个独特引用帧。
入口核验引用文件/像素哈希及两窗口的来源视频哈希一致性，保留源码快照和产物清单。
逻辑时间只表示证据已知顺序，不冒充动作精确时刻或实际到账时刻。

使用独立环境 `C:/Users/Administrator/.codex/runtimes/pokersense-v6-clean-20260908/Scripts/python.exe`，
设置 `PYTHONPATH=src`、`PYTHONUTF8=1`、`PYTHONNOUSERSITE=1`，在仓库内运行：

```powershell
python -m tools.replay_wpk_reviewed_hand `
  --window G:/PokerSense_archive/wpk_video_first_20260908/hands/aq_allin_8240_8900 `
  --completion-review tests/fixtures/wpk_reference_hands/aq_completion_v1.json `
  --cash-window G:/PokerSense_archive/wpk_video_first_20260908/settlement/credit_8780_8845 `
  --output G:/PokerSense_archive/wpk_video_first_20260908/state_replay/completed_aq_recheck
```

上述 `python` 应解析到指定独立解释器；输出目录必须不存在，不覆盖已存报告。

## 验证与能力边界

新增12项测试：真实参考手牌、输入不可变、下注前缀不变、守恒、重复现金观测、
保险不自动扣账、部分座位覆盖、未来牌泄漏、下一手前注、无凭据外部收入、重复牌、
多板及缺牌拒绝，以及合成主/边池异主、精确平分和不支持的零头分配拒绝。
这些类别部分合并或参数化为测试；多人异主和平分是合成测试，不是新增真实牌局。

完整回归2472通过、1项Quartz平台跳过、2项依赖弃用警告；Flake8和差异空白检查通过。
最终回归XML：`settlement/pytest-completion-final.xml`；前次回归记录保留。

当前仅支持明确审阅的单板、已知争夺者底牌的摊牌。零头派奖、多板、保险赔付/外部
入账等未支持场景拒绝推断。`chip_unit=1`仅为此案例的记账网格，不代表所有WPK房间。
起始筹码/动作仍含人工审阅逻辑重建，不能称为逐帧自动识别真值已全部完成。

生产权重和原始标注哈希不变，`requires_revalidation=true`保持。
下一步是现有录像的动作/筹码OCR实测接入，与此审阅链逐节点比较；缺多步动作时
保持UNKNOWN或拒答，不补造行动线。之后仍需独立牌局覆盖、策略验证及最终采集卡验收。
