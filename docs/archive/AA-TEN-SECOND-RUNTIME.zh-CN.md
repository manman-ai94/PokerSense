# AA 十秒行动窗口：运行时基础

本阶段实现**离线／影子计时基础和观察端拒答合同**，没有开放实战建议。
`/api/status.realtime` 始终为 `OBSERVATION_ONLY`，`strategy_eligible=false`、
`advice_emitted=false`、`advice=null`。当前 AA reader 没有经过验证的回合起点／
倒计时生产者，也没有通过实战资格验收的本地策略，不能把第一次识别到 Hero
行动当成新的十秒。现有手工条件分析继续独立运行，不进入实时路径。

## 时间与身份合同

- `AATurnWindow` 只接受显式 `TurnIdentity(instance_id, generation, hand_id,
  turn_id)` 和 `TurnEvidence`。这是供未来经验证的源适配器使用的 Python 接口，
  浏览器不能提交这些对象；现有 reader payload 中类似字段不被信任。
- 证据必须是已验证起点或已校正舍入误差的倒计时下界，使用主机单调时钟。
  同一回合后续证据只能收紧截止时间。中途接入剩余六秒，不重新获得首两秒预算。
- 第一结果期限是回合绝对截止时间减八秒；计算预算是剩余期限与 300ms 的较小值；
  剩余三秒进入操作余量区，拒绝新增或替换结果。换手、换实例、换 generation、
  换回合及单调时钟倒退会使旧窗口失效。
- 结果发送前重新检查来源年龄、身份、合法菜单、状态、剩余预算。
  源年龄上限一秒；不把非法输出替换为弃牌或其他动作。

## 已接入的观察链

采集来源在 `backend.capture()` 前后分别记录 `host_source_started_at` 和
`host_source_received_at`。会话另外记录源读取起止、识别起止、处理耗时、发布时刻。
两者都是主机端计时，不能代表采集卡之前的源画面时间；
`physical_source_timestamp`、`physical_source_age_ms`、`end_to_end_latency_ms`
保持未知。开发回放 PTS 不冒充现场单调时钟。

会话的旧帧清除从已知来源调用起点计时，避免识别完成将旧帧刷新为新帧，
包括第一帧识别已经过期的情况。源时间缺失时仍可观察，但实时合同明确拒答。
停止、错误、来源变更会清除对应时序数据。

`/api/status` 在其他状态读取完成后重新计算实时拒答，绑定实例、generation、
sequence 和桌规 revision。接口列出 10,000/2,000/300/3,000ms 时间要求；
目标不是已测性能成绩。页面显示“本次无法建议”和具体缺项，不输出动作。
独立 50ms watchdog 为实时状态执行 500ms TTL，并扣除整个 HTTP 往返时间；
慢请求不续命，页面失焦／重新聚焦、源切换和连接中断都清除状态。
浏览器调度暂停不能由 JavaScript 保证硬实时，因此恢复时必须重新获取状态。

## 预加载影子策略进程

`AAIsolatedPolicyWorker` 在回合前通过 spawn 子进程预加载冻结概率表。
信息键、完整状态键、规则指纹、策略摘要、合法动作和回合身份共同构成请求身份。
同一身份使用一次确定性混合采样，重试及重启不能重复抽签寻找喜欢的动作。
查询没有等待队列；占用时拒答。已派发查询在等待或接收检查时超过窗口剩余
预算或 300ms 就终止子进程；后续状态回调迟到也拒答。不依赖 `Future.cancel()`，
也不在同一回合自动重新预加载。

这里的 300ms 从 `AAIsolatedPolicyWorker.lookup` 取得锁后进入 `_lookup`
的首次单调时钟取样开始，包含绑定计算、IPC 等待和结果校验。它不是整个
`AAFrozenShadowSession.lookup` 的硬截止；父层编码期间仍消耗同一来源 TTL、
首结果期限和操作余量。例如来源起点为 100s、窗口起点也为 100s，父层处理
400ms 后仍可分配最多 300ms；处理 950ms 后只剩来源 TTL 的 50ms。
产品中的稳定状态到建议 p95 目标不等同于这个影子接口的阶段预算。

影子适配器在编码前、编码后检查原绝对窗口；V1/V2 每次查询从同一次验证取得
信息键和分布，不跨请求缓存，也不接受调用者提供的预计算键。scope、菜单、
概率和编码验证沿用各版本原顺序；已经过期的输入先按时间合同拒答，命中与
缺键均不能绕过过期检查。完整状态哈希及菜单求值后，worker 入口再次检查窗口。
worker 冻结一次绝对计算截止，在绑定计算后、发送前复核窗口和计算截止；
新证据只能进一步收紧该截止，不能恢复已经消耗的额度。
尚未发送便过期时不发送请求。接收结果及状态复核后，用同一时钟取样比较
计算截止并记录首结果；恰好到期也拒答，不在记录时再次取样改变接受时刻。

调用者必须提供快速、非阻塞的 `is_current(binding)` 回调，在进程返回后重新读取
当前状态；不得仅比较请求自己的副本。回调返回后再次检查预算。映射查询本身不
读取环境暗牌、网络、Jev 或运行 Monte Carlo。返回是 `SHADOW_RESULT`，
仍然没有实战资格；父层负责规则／筹码深度覆盖、状态编码、资格审核和最后显示检查。
生产 AA 会话未调用此影子执行器，待可信时间证据与合格策略同时可用后另行接入。

## 验证与未完成事项

合成测试覆盖中途接入、重试不续命、延迟首结果、倒计时收紧、源过期、非法动作、
身份切换、状态变化、进程实际阻塞／终止、确定性混合采样与浏览器 TTL。
使用真正 spawn 子进程，但输入是合成的；不是现场延迟或扑克强度验证。

固定合成时钟还验证一次编码、0/400/950/1050ms 前处理、超时绑定不派发、
迟到结果／状态回调、恰好到期及重复身份。同步编码、哈希、IPC send 和调用者
回调不能被这些事后检查抢占；测试证明的是派发／接受时刻的拒答合同，不能
保证 Python 函数在硬截止前返回，也不代表摄像头到显示的端到端成绩。

首轮本地候选 `b171c7e` 以 `511156ad` 为固定基线；63 项新增固定回归和 164 项
相关既有回归全部通过，0 失败／错误／跳过／未执行。旧源码和证据保留。
`65a5a5b1` 上的 `9323c0dc` 本地验收为历史证据：分母5,337，5,329 passed、
8 skipped；pytest629.86s、命令632.496s。其第一版独立JS/reference/lint记录和
首次可选 `/usr/bin/time` 包装缺失的启动ERROR（0执行/5,337未执行）独立保留。
2026-10-01 新独立分支安全衔接 `3629953c`，包含已合并PR47的range/snapshot身份
保护；shadow生产代码与63项测试保持原候选字节一致。新基线执行源码`10380993`：
相关277/277通过，完整分母5,376，5,368 passed、8平台skipped，失败/错误/中断/
未执行均0；pytest621.92s、命令623.962615s。全仓lint、57项JS及11项独立参考
在新基线重新执行并通过；63项shadow及50项身份相关用例全部通过。
新分母相对旧计划新增40身份、移除1个由两个边界参数替代的旧expired_request身份，
净增39；完整身份和跳过原因逐项核对。775个源码/测试/tool文件哈希与冻结执行保持
一致；1,138个tracked文件快照属于执行提交，后续只更新AGENTS与本说明两份文档。
Python3.12.14、Node24.19.0，既有CPU/依赖、workspace独立basetemp，最低空间
28.7926GiB。8项跳过为4项Windows cmd、3项WinDLL DPI、1项Quartz；本地记录
不代表Windows/macOS或安装包通过，跨平台CI与远端SHA在PR证据中单列。
完整日志125项警告保留，包括Starlette/PokerKit与JUnit record_property/xunit2；
没有过滤警告或放宽门槛。公开提交严格限原7个工程代码/合成测试/说明路径；
独立玩具质量实验保留本地，不随本候选发布，策略或实时资格没有因此提升。
新增用例是合成 clock/IPC，既有 worker/session 测试另覆盖真实 spawn 和超时终止。
复现相关检查：

```bash
PYTHONPATH=src:. UV_CACHE_DIR=/workspace/.uv-cache python -m pytest -q \
  --basetemp=/workspace/pytest-shadow-boundaries \
  tests/desktop/test_aa_shadow_boundaries.py \
  tests/desktop/test_aa_frozen_shadow.py tests/desktop/test_aa_policy_worker.py \
  tests/desktop/test_aa_turn_runtime.py tests/strategy/test_aa_frozen_policy.py \
  tests/strategy/test_aa_frozen_policy_v2.py \
  tests/strategy/test_aa_policy_encoding_v2.py \
  tests/strategy/test_aa_probability_contract.py \
  tests/strategy/test_aa_equity_shadow_v2.py \
  tests/tools/test_run_aa_equity_shadow_synthetic.py
python -m flake8 src tests tools
```

新基线的完整pytest、JS、独立参考和lint均按新的命令冻结执行。以下命令供复现：
`python -m pytest -q --basetemp=/workspace/pytest-shadow-full`，
`node tests/ui/test_aa_turn_runtime_ui.js`、
`node tests/ui/test_aa_analysis_ui.js`、`node tests/ui/test_aa_table_settings_ui.mjs`、
`python -m pytest -q tests/tools/test_strategy_eval_independent_oracle_v1.py`。
真实采集、平台接入、端到端速度与策略强度均不在本次本地验收范围内。

仍需实现并独立验收源事件时间标记／倒计时读取、完整合法状态、通过评估的冻结
策略、真实部署桥接及最终显示动作通道。尚未测量物理采集到页面的 p95/p99，
未开展真实采集／实战，没有据此声称一秒建议、80% 覆盖或稳定盈利。
