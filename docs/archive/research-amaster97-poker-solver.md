# `amaster97/poker_solver` HU Blueprint 接入调研

## 结论

PokerSense 可以把该项目作为**可选、隔离、带版本证明的 HU 翻牌前策略源**，但不能把它扩张解释为多人策略，也不能仅凭仓库使用了 CFR/DCFR 就宣称输出已经达到可证明的 GTO 精度。

本次核验基于：

- 仓库：<https://github.com/amaster97/poker_solver>
- commit：`f78f1b2bc338dd8cbb5226ecb8398bbdb3635676`
- Python package：`1.11.0`
- license：MIT
- Blueprint schema：`v1.0`
- Premium-A asset version：`v1`
- manifest SHA-256：`a2caeb1ba9d20a970445dde102f85958d7ba330b6ffb3a8aef465ff0bddf1666`

## 已核实能力

资产目录实际包含 27 个 gzip 分片：9 个有效筹码深度（20、30、40、60、80、100、150、175、200BB）乘以 3 个 ante 档（0、0.5、1BB）。每个分片在 manifest 中记录内容 SHA-256、迭代次数和生成耗时；加载器默认在首次读取分片时校验内容哈希。

查询键包括有效筹码、ante、169 手牌类别和动作历史。根节点动作标签不是单纯的 Fold/Call/Raise，而是 Fold、Call、多个 `open_to_N` 尺度和 All-in。PokerSense Adapter 会：

1. 将两张具体手牌转换为 `AA`、`AKs`、`AKo` 等 169 类标签；
2. 保留源分片、manifest、commit 和版本证据；
3. 将多个 raise 尺度汇总到标准 `RAISE`，同时通过 `ActionOption` 保留每个 total-street 尺度的独立频率；
4. 从明确含 seat、action 和 total-street amount 的 `StateEvent` 构造 `c/x/f/A/bN/rN`，并验证 HU 座位轮转与粗粒度 action line 一致；
5. 对非 HU、非 preflop、非精确 stack/ante/rake 或无法构造权威 history 的上下文明确拒绝匹配；
6. 对缺失节点、损坏分片、未知动作标签或异常概率分别返回 `NOT_FOUND` 或 `REJECTED`，不让异常穿透 Router。

## 当前限制与风险

- 当前接入支持可由权威 `StateEvent` 精确表达的 HU preflop 节点；Golden 已锁定完整 169-class root 和 11 个跨 action/stack/ante 节点，但尚未枚举 27 个分片的完整动作树。
- ante 和动作金额均按 big blind 标准化；capability 额外保存实际存在的 stack×ante pairs，不会把两个独立列表错误扩展成不存在的组合。
- 上游 manifest 的 `final_exploitability_bb100` 为 `null`。因此输出可称为“精确命中该版本 Blueprint”，不能称为“已验证 exploitability 的 GTO”。
- 169 类会把具体花色组合抽象为同一手牌类别；它不是逐 combo 独立求解。
- 该资产是 Heads-Up，不适用于 3–9 人；多人请求必须由多人 Provider 处理或拒答。
- PokerSense 没有复制上游代码或 27 个资产分片。仓库中只保存少量可审计 Golden 查询结果及来源元数据；运行时资产仍是可选外部依赖。

## 回归与更新规则

`tests/fixtures/strategy/provider/hu_preflop_blueprint_golden.json` 固定完整 169 手牌类根节点和 11 个代表动作/stack/ante 节点，共 180 次真实查询。常规测试使用 Loader test double 验证 Adapter 映射，避免 CI 隐式下载外部资产。生成和复核命令为：

```bash
PYTHONPATH=<upstream-checkout> python \
  tools/generate_hu_blueprint_golden.py <upstream-checkout> --check
PYTHONPATH=src:<upstream-checkout> python \
  tools/verify_hu_blueprint_golden.py <upstream-checkout>
```

只有 commit、manifest 哈希、分片哈希、动作标签和概率全部一致，Golden parity 才通过。任何升级都应生成新 fixture version，并重新审阅许可、动作树和数值质量。
