# 冻结策略评估链修复与旧结果勘误

原 PR37 `b796cce96426d37cb0c4f4746d0dd8998bc6c86d` 的评估器给策略
`for_game` 传入 64 位十六进制字符串，但实际 `FrozenResearchPolicy` 只接受整数。
原 48 配对探针和九配置 378 配对 smoke 首先失败在绑定阶段；此前把这些失败直接
称作策略覆盖不足是不准确的。旧 JSON、策略、manifest 和历史结果均保留。

## 修复与合同

- `for_game` 统一接受 64 位小写十六进制字符串；不接受整数、bool、错误长度或非
  十六进制字符。策略 salt 独立于发牌 seed，配对两边复用对应的 per-seat salt。
- `inspect_lookup` 输出策略 digest、编码器版本、实际 key、公开特征摘要及
  HIT/UNKNOWN_INFORMATION_SET/SCOPE_MISMATCH/INVALID_MENU/ADAPTER_ERROR。
- `evaluate_paired(record_diagnostics=True)` 记录绑定成功、失败阶段、实际 actor、
  是否 Hero、零起始行动序号和每个已观察 Hero 机会。确定性重复调用不双计机会。
- 按街命中率只覆盖实际观察前缀；首次拒答后的行动机会数量未知，不补零或推算。
  局部策略调用耗时不包含采集、界面、额外诊断或重复调用，不能当作物理端到端延迟。

## 本轮实际验证

预先声明的种子4441/4442，分别在6/7/8人构造明确的 check/call 接线测试资产，
使用真实序列化加载、真实冻结策略和真实评估器：12/14/16 配对，共 **42/42 完成**。
所有候选的逐步 trace、终局和收益与直接 check/call 一致，四街每局各一个 Hero
机会。该资产是测试正控，不是学习候选，也不是未见牌局验证。

原九份资产按原协议的规则、起始筹码、种子、对手、bootstrap 和行动预算重跑，
绑定全部成功；随后 **378/378 UNKNOWN_INFORMATION_SET**，均在首次 Hero 决策。
每个失败和完整分母保留，受影响组 EV 为 null。原57个JSON前后 SHA256 完全一致。

九份首轮策略共有592条记录，全部为合法动作均匀分布。首 sweep 从零 regret
开始，整 sweep 后才提交，因此这些短产物尚不足以证明学习偏好或策略强度。

独立审查另验证了无效 salt、规则／深度、错误菜单、空表、预算、非法动作、
对手绑定错误；失败 actor 不被误记为 Hero，机会不双计，输出不得位于原数据目录。

## 复现

```powershell
$env:PYTHONPATH='src'; $env:PYTHONUTF8='1'
python -m tools.diagnose_aa_frozen_evaluation --source <原九配置目录> --output <全新报告目录>
python -m pytest tests/strategy/test_aa_real_frozen_evaluation.py tests/strategy/test_aa_arena_evaluation.py
```

本机追加报告位于 `G:/PokerSense_private/aa-policy-readiness-20260927-v1/stage1-correction`。
该阶段通过只表示评估接线可信；不代表 V1 表示正确、策略已学习、未知牌局可执行或
真实十秒窗口已经验收。随后 V2 使用新编码器与新产物，禁止覆盖 V1。
