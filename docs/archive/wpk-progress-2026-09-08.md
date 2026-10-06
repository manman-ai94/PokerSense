# WPK 本地接管与第一批实现（2026-09-08）

最新视频推进：已建立第一手AcQh的来源绑定对照，独立规则与项目数学一致，并修复动态卡面融合的输入改写/对齐方向/无界缓存问题。
v4卡面算法处于独立重新标定阶段，生产路径暂不接受卡面候选；旧v3精度数字仅作历史记录。
保险发现与边界见 [保险机制核查](WPK-INSURANCE-NOTES.zh-CN.md)，当前总计划见根目录视频优先计划。

随后第二批12个冻结检查点未通过：在局底牌要求6/6通过，但灰暗底牌3张、公共牌红色6两张仍误读。
一处K♦/K♥目检笔误已经留痕更正，首次预测未改写。对比度静态原型改善灰暗牌，尚未进入生产；需要新数据验证后再放行。

## 当前范围

手机通过采集卡连接电脑；WPK（WePoker）6–8 人桌。AA 放到第二阶段。开源优先，全部本地工作。
用户要求级别、前注、抽水、straddle 可在软件中调整。2/4、3% 是常用实例；前注 2、抽水封顶 2BB、straddle 8 是当前**模拟默认值**，不是已证实的固定规则。

## 本次实现

- 修复不足两名有效玩家时策略 Context 抛异常；输出等待原因并丢弃旧 Advice/异步结果。
- 补 actor、dealer、slot stack/action/occupancy 的独立变化检测，避免单独槽位变动被跳过。
- 将实时 equity 改为实际 ACTIVE/ALL_IN 对手人数；排除弃牌/离桌；输出对手数、样本量、摊牌份额与标准误差；明确为随机范围基线。
- 当前牌面与状态不一致、公共牌失去可信度或座位未识别完整时，不显示貌似精确的胜率。
- 新增 PH Evaluator 可选开源加速；保留直接牌力评估 fallback，并与原穷举实现交叉验证。
- 新增独立 PokerKit 规则校验工具。标准模拟 2/4、每人 ante=2、UTG straddle=8、最小加注增量=8 时，6/7/8 人初始底池为 26/28/30；首行动者索引 3，跟注 8，最小加到 16。该结果不证明实际 WPK 暴击或特殊 straddle 规则已接通。
- 新增 `/table-rules` API、独立原子保存、规则版本标识和中英文设置表单。规则修改立即清除旧动作，前端拒绝旧规则版本的在途结果。
- 设置可填写人数、小盲/大盲、每人前注、最小筹码、抽水百分比/封顶、straddle 模式/金额和额外规则说明。未知暴击只记录说明，不伪造收益算法。
- 修复 UI 将原始筹码错误标成 bb；新增随机范围/对手数提示及等待占位。
- 将归档中已测得的采集卡裁剪配置放入生产资源并自动加载：1920×1080，crop [711,0,1209,1080]，输出 498×1080。原本默认 normalization=None 无法匹配竖屏标定。
- 原生桌面壳补齐采集源、设备索引和 API 参数，默认 capture-card。提供 PowerShell 启动器和独立模拟页面。
- 修复四个导致 GBK 解码失败的测试读取点；修复延迟基准 exact 场景重复 7H 导致未实际计算的问题。

## 新工具

| 工具 | 用途 |
|---|---|
| `tools/start_wpk.ps1` | 启动真实采集卡服务或 `-Demo` 模拟服务，选择已安装的可选开源运行库 |
| `tools/wpk_demo.py` | 不碰采集设备的页面/多人随机范围演示，始终标记模拟且不输出策略动作 |
| `tools/wpk_readiness.py` | 重复检查字段、默认策略覆盖、规则状态及训练/评测同手泄漏 |
| `tools/replay_wpk_video.py` | 原始归档视频经生产归一化、视觉、多帧确认、状态、equity 门控；输出可用率诊断 |
| `tools/benchmark_wpk_equity.py` | 6/7/8 人 × 四街，区分冷计算和缓存，不冒充全链路延迟 |
| `tools/verify_pokerkit_rules.py` | 独立开源规则引擎校验 ante/straddle 示例 |

可选开源依赖固定为 `pokerkit==0.7.5`、`phevaluator==0.6.0`，见 `pyproject.toml` 的 `solver-tools` extra。
本机验证安装在独立目录 `C:\Users\Administrator\.codex\runtimes\pokersense-oss-20260908`，未更改 WorkBuddy 全局环境。
`tools/start_wpk.ps1` 能加载该目录；其他机器可以在自己的虚拟环境安装 `.[solver-tools]`。

## 运行

在仓库根目录打开 PowerShell：

```powershell
.\tools\start_wpk.ps1 -Demo -Port 8876
# 模拟页面：http://127.0.0.1:8876

.\tools\start_wpk.ps1 -DeviceIndex 0 -Api MSMF -Port 8765
# 真实采集卡页面：http://127.0.0.1:8765
```

也可使用已配置依赖的 Python：

```powershell
$env:PYTHONPATH='src'
$env:PYTHONUTF8='1'
python -m poker_engine.desktop.app --source capture-card --device-index 0 --api MSMF
```

语言和牌桌参数分别保存至用户配置目录的 `settings.json`、`table-rules.json`。测试/临时预览可用
`POKERSENSE_SETTINGS_PATH`、`POKERSENSE_TABLE_RULES_PATH` 指向独立目录。原始画面与手牌数据不会因调整规则被上传。

## 验证证据与剩余问题

后续视频优先工作已推进到v5候选：灰暗底牌归一化完成，连续开发回放底牌错误3→0，
公共牌红6仍有2次误读，生产仍不放行。最新完整回归2364 passed / 1 skipped。
细节、适用范围及后续训练链工作见[WPK v5识别报告](WPK-V5-RECOGNITION-REVIEW.zh-CN.md)。
以下为最初本机接入轮次的证据，保留作历史对照。

再后续v6已完成可复现离线点数训练，第三批8个新检查点首测通过卡面候选门槛：
底牌15正确/1拒答/0错、公共牌20正确/0错；生产仍关闭。最新回归2378 passed / 1 skipped。
共享环境OpenCV重叠及全模型数据独立性尚未解决，详见
[v6训练与验证报告](WPK-V6-RANK-TRAINING.zh-CN.md)。

- 初始接入轮完整回归：在开源可选运行库可用时 **2327 passed / 1 skipped / 21.56s**。唯一跳过为 macOS Quartz。
- Python 直接评估器：4500 个随机牌型 + 特殊牌型对照穷举。PH Evaluator：3000 对随机手牌比较胜负/平局；多人平分与 HU exact 交叉检查通过。
- PH Evaluator 后端 2000 次采样，6–8 人、四街示例，三次冷运行中位数约 **30–56ms**。仅计算模块，未包含真实采集、视觉、策略与 UI。
- 浏览器实际修改模拟规则至 5/10、2.5% 后保存，刷新重新打开仍保留；未修改用户真实偏好文件。设置界面已检查可见状态与布局。
- 原始 `session_002.mkv` 三个位置各连续处理 90 帧，共 270 帧，工具未崩溃；但公共牌多为 CONFLICT/UNKNOWN，stacks/action 均未形成有效完整结果，尚无可用真实策略闭环。这些是诊断窗口，不是带真值的验收数据集。
- `wpk_readiness` 仍报 `board/action` 缺标定、模拟规则、翻后策略缺失、同手跨 train/eval 等阻塞。严格禁止把此阶段写成 100% 完成或高盈利已验证。

下一主线：修复并独立验证动态视觉与完整状态；引入 PokerKit 作为真实规则适配的交叉基准；对 6–8 人翻前行动线和翻后剩两人/仍有三人以上分别建立策略覆盖。TexasSolver/其他翻后求解器仍需要输入范围、动作尺度、收敛与 Golden 验证，尚未接入生产。

参考来源：

- <https://github.com/uoftcprg/pokerkit>
- <https://github.com/HenryRLee/PokerHandEvaluator>
- <https://github.com/b-inary/postflop-solver>
- <https://github.com/bupticybee/TexasSolver>
