# AA8 独立验收证据合同

2026-09-09。状态：验收工具已实现，真实视觉验收仍为 PARTIAL。

## 当前真实证据边界

核对仓库 Current state、AA8 split plan 及投保误报修复报告：首手 2057 帧的
21 个可见动作和次手窗口 1782 帧的 17 个可见动作均为开发回归；次手在修复
投保误报时已经参与开发，不能重新命名为 holdout。四帧金额核对有人工上下文。
split plan 的 verified_independent_hands 为 0；候选时间范围不是完整手牌。
本次没有读取 calibration/holdout 的图片或视频，也没有启动采集设备。

995.366 秒原始录制的完整解码、帧数和时间戳检查支持文件/时间线完整性，
不独立证明源画面没有卡住，也不证明连续视觉引擎在设备上稳定运行。

## 工具及输出

`tools/aa8_acceptance.py --template` 输出空 manifest。
`tools/aa8_acceptance.py --manifest <manifest.json>` 验证证据并输出 JSON；
PASS 返回 0，PARTIAL 返回 2。工具不打开视频、不采集、不生成策略。

manifest 必须绑定 implementation、model、parameters、dataset、labels、
predictions、hardware 文件 SHA256；绑定失效不能通过。dataset JSON 数组
须与 manifest 的 hands 完全一致。完整 holdout 手必须有边界、session、
人工审核标记、无调参暴露声明，并与开发帧区间不重叠。

标签与预测采用 JSON 数组，每项含 hand、frame、fields。每一帧、每一字段
均计算 total/known_gold/automatic_known/matched；不允许只以已识别部分为
分母。字段包含 actor、street_wagers、actions、pot、stacks、street、hand、
participation、insurance、mushroom、bomb。所有值必须标记 KNOWN 并有合法
类型；预测 origin 必须 automatic，人工上下文/UNKNOWN 不算匹配。
不存在行动者用明确 NONE，而非 UNKNOWN；模式未开启用 active=false。
保险、蘑菇、暴击均需要正负样本，另需换街、换手、等待入桌、无标记动作。

目前采用严格全帧匹配合同，尚未擅自引入容错百分比。字段一致只是必要条件，
不能替代人工核实标注真实性、特殊模式金额语义和场景标签。SHA256 保证文件
没有变化，不证明文件内容真实，也不证明 frozen_before_predictions 声明诚实。
只有实际冻结清单、保存原始预测、再审核标签的执行流程才能补足这条审计链。

## 设备验证与可配置要求

hardware 证据要求目标设备、端到端运行、源画面新鲜度、断连及恢复、延迟预算、
异常间隔和崩溃计数；未知不能写 0。测试仅采集/识别，不涉及策略或游戏动作。
hardware_min_seconds 是显式配置，无任意写死的 30 分钟硬门槛；未配置不能
声称长时验收已通过。已有录像可支持实际被测环节，但不能覆盖未测的端到端
或重连环节。独立 hardware session 是推荐扩展项，可通过
require_independent_hardware_session 配置为要求；结果始终单独报告真实独立性。
同一录制的 holdout 不能称为独立设备或独立 session。

当前录制已停止；缺少设备证据不授权自动启动新的录制。

## 验证

新增 26 项合成合同测试，覆盖空证据、哈希改变、缺帧、重复帧、UNKNOWN、
人工预测、调参暴露、开发区间重叠、非完整手、设备未知/短时/会话混用等。
合成 PASS 仅验证门禁实现，不构成真实 AA8 验收。

下一步是将真实连续识别输出接到此格式，冻结后按事先声明的完整手选择规则
建立 holdout 真值。没有完整独立真值和真实预测，不能用单元测试通过替代。

## 冻结与仅边界审核工作流

新增 `aa8_holdout_plan.py`，只读 JSON 元数据，不解码媒体。冻结清单必须有
UTC 时间、按解析后绝对路径排序且唯一的文件 SHA256，以及 implementation、
model、parameters、training 四类工件。训练/模板选择/调参来源必须登记为
development 或 calibration，holdout 和未知来源会被拒绝。人工边界审核素材
不得回流给调参者。验收时重新校验冻结清单及所有文件，预测开始时间必须晚于
冻结时间，验收所用实现/模型/参数还必须与冻结清单完全对应。

600–820 秒仅是候选范围。冻结成功后，独立边界审核者按时间顺序采样、逐帧
收敛首个发帖/下一手发帖边界，绑定前后相邻帧见证及图片哈希。记录范围内
每一个候选手，保留所有完全落在范围内的手；跨界排除必须写原因，禁止按
识别分数选容易的手。边界元数据可共享，画面/真值不得交给调参 Agent。
本工具只产生 READY_FOR_BOUNDARY_REVIEW_ONLY，不授予预测运行或视觉通过。

验收和冻结共 39 项聚焦测试通过。现有 split plan 元数据回归确认没有独立手；
该断言将来应随真正的登记工件更新，不能为消除失败而改写历史计划。

补充：空座/等待座金额允许显式 `{ "status": "NOT_APPLICABLE" }`，但须在
同帧 participation 的 KNOWN 值明确为 empty/waiting；活跃座不能借 NA 回避
识别，UNKNOWN 不能冒充 NA。也不要求每一帧都有行动者；无行动者应由真值和
识别独立提供明确 NONE，不允许把检测不到倒计时直接改为 NONE。

后续加入参与者候选工具及 NA 回归后，本分支聚焦测试合计 56 项通过。

新增 hero_cards / board_cards 的真实牌面身份要求，不能用公共牌数量替代。
检验牌码、重复牌及手牌与公共牌冲突、街道与公共牌数量一致；Hero弃牌/空座/
等待或idle允许有上下文的显式NA。固定8座/Hero4/从顶部顺时针映射必须匹配。
后续包含自动换手候选测试后，本分支四工具合计70项聚焦测试通过。

## 源画面确实不可观测时的安全拒答合同修正

这属于工程合同修正，不是改变真实数据来宣布通过。发牌/动画/遮挡时并非
所有字段都物理可见，因此不再要求这种帧“猜一个值”。完整每帧13字段记录
仍必需，但gold字段可显式required=false，且须给出transition/occluded/no_action
之一的原因、人工审核者、source_reviewed=true和实际源文件路径/SHA256。
文件哈希不匹配、理由含糊或缺审核不能豁免。该机制不设宽松准确率阈值。

每手必须有审核过且哈希绑定到dataset的action_opportunity_frames清单；每帧
gold必须明确decision_opportunity真/假，并与清单一致。所有已审核行动时点
必须13字段required，禁止豁免；已知真实行动者或非空动作却标记无行动也会拒绝。
每个字段至少存在一个required帧，required帧仍必须全部自动正确；全optional
绕过不会通过。真实动作机会清单是否遗漏，还需要独立标注审核保证，程序不能
仅凭JSON声明证明人工审核没有漏看。

optional帧自动UNKNOWN属于exempt_abstained，不算matched，也不算required正确。
如果系统在optional帧输出KNOWN，仍必须是自动来源、有效字段且与KNOWN真值
一致；真值UNKNOWN但系统猜出KNOWN也不能静默算通过。缺字段记录不能用豁免
规避。计数同时显示total、required_total、required_matched、exempt_total、
exempt_abstained、known_gold、automatic_known和matched，原始全帧分母不丢失。

本次新增防全豁免、动作时点豁免、源证据缺失、无真值却猜测KNOWN等测试，
验收模块41项聚焦测试通过。没有修改开发真值、预测或实际接受标准百分比，
也没有把本合同的合成测试PASS当作真实AA8通过。
