# V2 独立预测与真值接口

2026-09-09。仅准备工程接口；没有启动V2冻结，没有读取300–600秒新保留画面，
也没有执行新保留预测。本轮仍为PARTIAL，不能宣布用户的三项验收已完成。

新增文件：`aa8_holdout_predict_v2.py`、`aa8_gold_registry_v2.py`及各自测试。
没有修改V1冻结代码、模型或预测。20项聚焦测试通过，新增文件flake8通过。

## 预测入口

调用`tools.aa8_candidate_v2.create_candidate(spec)`，不复制CandidateStateV2
识别逻辑，不修改参数。factory.json必须恰好包含source/context_source/
late_source/bank_path/profile_path/heads_path/audit/bomb_pool/reservations，
不得混入gold或目标标签。构造前检查冻结清单、开发输入清单、模型、参数、
factory spec、预测入口源码和候选模块源码哈希。执行前后重新核对，失败保留
部分输出但不生成完成报告；输出目录不可覆盖。

run manifest是在候选冻结、边界登记和目标帧提取之后、预测之前另外冻结的
执行清单。必需字段：frozen_at_utc、freeze_sha256、registry_sha256、
target_manifest_sha256、factory_spec_sha256、harness_sha256、split_path。
命令还要外部提供该run manifest的SHA256，防止无声替换。

以下命令仅在开发门槛确实满足、隔离边界登记和执行清单准备完成后使用。
这里路径表示未来工件，本文没有创建这些冻结/目标目录：

```powershell
$python = 'C:/Users/Administrator/.codex/runtimes/pokersense-v6-clean-20260908/Scripts/python.exe'
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
& $python -m tools.aa8_holdout_predict_v2 --freeze G:/PokerSense_private/aa8_candidate_freeze_v2/freeze.json --run G:/PokerSense_private/aa8_evaluation_run_v2/run.json --run-sha256 <已外部核验的run清单SHA256> --registry G:/PokerSense_private/aa8_holdout_boundary_registry_v2/registry.json --target G:/PokerSense_private/aa8_holdout_whole_frames_v2 --spec configs/reproduction/aa8_candidate_v2/factory.json --output G:/PokerSense_private/aa8_holdout_predictions_v2
```

## 冻结输入清单

现有`aa8_freeze_candidate`的`--repo`会覆盖所有src/tools的Python源码，包含
两个新V2入口、候选factory及依赖。另须显式提供以下数据输入；本轮不运行：

- `--training G:/PokerSense_private/aa8_first_hand_full_v1/samples.json`
- `--training G:/PokerSense_private/aa8_second_hand_window_v1/samples.json`
- `--training G:/PokerSense_private/aa8_late_dev_special_search_v1/samples.json`
- `--training G:/PokerSense_archive/aa_video_first_20260908/mode_mining_1s_v1/samples.json`
- `--model G:/PokerSense_private/aa8_reviewed_money_bank_v2_center/bank.npz`
- `--model configs/vision/wepoker_android_capture_card/card_heads.npz`
- `--parameters configs/vision/aa_android_capture_card/layout.8seat.candidate.json`
- `--parameters configs/reproduction/aa8_candidate_v2/factory.json`
- `--parameters configs/reproduction/aa8_candidate_v2/aa8_recording_split_plan_20260909.json`
- `--parameters configs/reproduction/aa_holdout_reservations_v1.json`
- `--parameters G:/PokerSense_private/aa8_geometry_reference_v1/normalization.candidate.json`

模板PNG由各开发samples.json绑定，加载时仍校验每个实际PNG哈希。若根任务
增加模型、配置或训练源，冻结清单必须同步增加，不能只照抄本批文件列表。
原V1冻结及600–820秒已评估数据不重命名为新holdout。

## 13字段的保守归一化

输出actor/street_wagers/actions/pot/stacks/street/hand/participation/
hero_cards/board_cards/insurance/mushroom/bomb，每字段明确KNOWN或UNKNOWN。
UNKNOWN不自动变成0、NONE、关闭模式或上一帧已知值。当前等待正证据可以
支持余额NA，但等待历史不能补当前未知。正向暴击标题可作为模式可见证据，
同时阻断过期下注字段。保险可见时下注actor、街道、动作等不输出KNOWN；
当前直接可见的底池/余额/Hero牌可以继续保留。

observed_epoch不是权威手牌身份；canonical_verified=false的因果下注和动作
也不会自动成为完整合法状态。因此现有V2不能凭该入口获得完整验收。不要
为了生成一个通过报告而消费唯一尚未见过的新保留集。

## 独立完整真值登记

gold.json格式为role=holdout、source_manifest_sha256、labels数组。每行需
frame、hand、source_sha256、source_reviewed、reviewer、decision_opportunity
和13字段status/value。字段required=false必须有source-reviewed豁免理由
transition/occluded/no_action和同帧source_sha256，行动时点不能豁免。
registry每手还需独立审核的action_opportunity_frames与opportunities_reviewed。

```powershell
& $python -m tools.aa8_gold_registry_v2 --registry G:/PokerSense_private/aa8_holdout_boundary_registry_v2/registry.json --pool G:/PokerSense_private/aa8_holdout_whole_frames_v2 --gold G:/PokerSense_private/aa8_holdout_gold_v2/gold.json --output G:/PokerSense_private/aa8_holdout_gold_v2/registration.json
```

登记器检查源文件哈希、逐帧覆盖、每手归属和行动机会；稀疏真值或全UNKNOWN
库存一律PARTIAL。即使完整登记通过也仅为GOLD_READY_NOT_PASS，因为尚未
与独立预测比较，更没有真实采集链路证据。

尚缺：可独立归因的无字动作/保险现金、全部特殊模式正负证据、完整连续
行动机会/13字段真值、冻结后未调参的完整手比对，以及用户明确授权后的
实际采集长期运行/新鲜度/恢复验收。原始104事件安全拒答不得通过改gold消除。
