# STRATEGY-001 失败复现与归因

任务：STRATEGY-001（Issue #23）· run_id `STRATEGY-001-20260915T233757Z-r2`
固定基线：`dc72a4176f81689e95a9238a49fb2d268dcd4a56`

本文件的每个数字都来自**本轮实跑**，不复制历史报告值。

---

## 1. 复现环境与命令（可复跑）

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONUTF8='1'
& $PYTHON tools/validate_threeway_models.py `
  --input   configs/strategy/examples/threeway-river-response-manual.json `
  --protocol configs/strategy/examples/threeway-validation-protocol-v1.json `
  --output  $PRIVATE_OUTPUT/validate-v1

& '...python.exe' tools/study_opponent_uncertainty.py `
  --input  configs/strategy/examples/threeway-river-response-manual.json `
  --output $PRIVATE_OUTPUT/uncertainty-v1
```

| 项 | 值 |
| --- | --- |
| repo HEAD | `dc72a4176f81689e95a9238a49fb2d268dcd4a56` |
| `tools/validate_threeway_models.py` sha256 前 16 | `9230cddb262ea7bb` |
| `src/.../threeway_policy_evaluation_v1.py` sha256 前 16 | `75b9af69582f4d29` |
| Python | 3.13.14（本机项目运行时，路径以占位符表示） |
| 依赖实况 | numpy **2.3.5** / opencv **4.10.0**（`pyproject.toml` pin：2.4.6 / 4.14.0.94 ⇒ **不一致**） |
| A 退出码 / 耗时 | **0** / **2 s** |
| B 退出码 / 耗时 | **2** / **5 s**（**设计内**：`tools/study_opponent_uncertainty.py:95` → `return 2 if any(... INSUFFICIENT_EVIDENCE)`，非崩溃） |

**A 复现结果**（与历史一致）：

```
world_cases=30  fixed_policy_evaluations=60  all_complete=true
fallback_cases=0            selected_id=calling_public_v1
screening_status=FAIL_STRESS_SCREEN
promotion_decision=NO_EMPIRICAL_PROMOTION
calibration_status=NOT_REAL_CALIBRATION
```

**B 复现结果**（与历史一致）：6 组全部保留，两组判定分列

| group | selected | status |
| --- | --- | --- |
| n6-facing_bet | `manual_reference` | `FAIL_DECLARED_WORLD_SCREEN` |
| n6-unopened | `null` | `INSUFFICIENT_EVIDENCE` |
| n7-facing_bet | `manual_reference` | `FAIL_DECLARED_WORLD_SCREEN` |
| n7-unopened | `null` | `INSUFFICIENT_EVIDENCE` |
| n8-facing_bet | `manual_reference` | `FAIL_DECLARED_WORLD_SCREEN` |
| n8-unopened | `null` | `INSUFFICIENT_EVIDENCE` |

**与历史基线的差异**：**无**。18/30 负比较、fallback=0、筛选状态全部一致。因此历史结论在本轮基线上成立，不需要版本/输入定位。

---

## 2. 逐场景条件 EV 与相对基线差（chips，净增量）

`selected` 指 log loss 选中的 `calling_public_v1` 策略本；`ref` 为原手工策略。完整 18 条：

| group | world | Δ vs ref | Δ vs check/fold | Δ vs check/call |
| --- | --- | ---: | ---: | ---: |
| n6-facing_bet | reference_control | −0.1607 | **+35.6915** | −0.1607 |
| n6-facing_bet | value_heavy | **−60** | −80 | **−60** |
| n6-facing_bet | rank_aware | −2.6244 | +26.8273 | −2.6244 |
| n6-unopened | value_heavy | 0 | −80 | −34.5222 |
| n6-unopened | rank_aware | 0 | +17.1458 | −1.9043 |
| n6-unopened | check_trap | 0 | +98.9676 | −4.9472 |
| n7-facing_bet | reference_control | −0.1607 | +39.5170 | −0.1607 |
| n7-facing_bet | value_heavy | −60 | −80 | −60 |
| n7-facing_bet | rank_aware | −2.5384 | +30.3003 | −2.5384 |
| n7-unopened | value_heavy | 0 | −80 | −34.5222 |
| n7-unopened | rank_aware | 0 | +20.0821 | −1.8131 |
| n7-unopened | check_trap | 0 | +106.7761 | −3.5498 |
| n8-facing_bet | reference_control | −0.1607 | +43.3424 | −0.1607 |
| n8-facing_bet | value_heavy | −60 | −80 | −60 |
| n8-facing_bet | rank_aware | −2.4524 | +33.7734 | −2.4524 |
| n8-unopened | value_heavy | 0 | −80 | −34.5222 |
| n8-unopened | rank_aware | 0 | +23.0183 | −1.7450 |
| n8-unopened | check_trap | 0 | +114.5846 | −1.9345 |

其它：`fallback_cases = 0`（**概率与次数均为 0**）；30 个世界全部 `complete`；无 `planning_errors`；
`conditional_river_EV only`，**不是**全手 bb/100，也**不**给统计置信区间。

---

## 3. 两个可在数据中直接观察到的结构性事实

### 事实 1：`ref` 与 `check/call` 在全部 9 个 facing_bet 世界中 EV **完全相同（精确分数相等）**

9 行 facing_bet 里 Δvs_ref 与 Δvs_check/call 逐位相同（例：n6 `-30444/189457` 两列一致）。
⇒ 在这些世界中，**三个比较对象实际只有两个是独立的**；「原手工策略」这一列不提供额外信息。

*可能原因（本轮未在代码中核实，故只列为假设）*：手写 reference 在 river 面对下注时恒为 call，因此在 EV 上与 check/call 基线重合。

### 事实 2：`ref` 与 `selected` 在全部 6 个 unopened 世界中 Δ=**0（精确相等）**

⇒ 未下注根上，log loss 选出的策略本与原手工策略本在本次评价中**没有产生差异**；该根的「新增挑战」并未真正区分两个候选。

**这两条事实的后果（已按 review 5217785775 更正，2026-09-16）**

> 原文此处曾推断「`18/30` 中有 9 行是同一比较的重复计数」。**该推断错误，现予撤回**，旧表述保留在此以备追溯。
> 实际统计路径是 `tools/validate_threeway_models.py` 的 `(group, world)` 双层循环：每个场景**至多追加一条**记录，
> 判定为 `delta < 0 or delta_vs_check_fold < 0 or delta_vs_check_call < 0`（三个比较列的 **or**）。
> 因此 `ref` 与 `check/call` 的 EV 相同**不能**推出重复计数，也就**不存在**「先修口径才能比较」这一步。

正确表述：上述两条事实只说明**比较对象在某些世界上退化** —— `ref` 列与 `check/call` 列给出同一个数、
未下注根上 `ref` 与选中策略无差异。这是**诊断/可读性**问题，**不改变**失败场景数 18，
也**不证明**两套策略等价。计数语义回归见 `tests/tools/test_validate_threeway_models_counting.py`。

**因此不存在「先修口径才能报数」这一步**：`ref` 与 `check/call` 数值相等只是让三列读数里实际只有两个独立比较对象，
既不加倍计数，也不改变 18 这个场景数，更不需要先修正任何统计口径（旧稿中「同时记了一次」「必须在下一轮修正口径后再报数」
两句与同段更正、生产计数和新回归测试相互矛盾，现一并撤回）。本文件 §2 的 18 条读数按当前口径即为有效读数；
下一步不是改口径，而是 B 阶段：用冻结策略本的可达公开历史给出**分支级**证据与精确收益对账。

---

## 4. 失败分类 A / B / C / D

| 类别 | 本轮判定 | 依据 |
| --- | --- | --- |
| **A 实现 / 结算 / 信息集错误** | **未发现** | 30 世界全部 `complete`，`planning_errors` 为空，`fallback_cases = 0`，精确分数自洽（同一比较两列逐位相等）；无异常退出（A exit 0）。既有反例（QQ/TT/JJ）已在历史轮次修复并保留为回归。 |
| **B 对手范围 / 响应模型错设** | **待检验假设**（原写作「主因」，按审查降级；当前**无分支级证据**） | ① `value_heavy` 世界 Δvs_check/fold = **−80**（两种根都是）：面对强价值范围时，不是最激进基线更好，而是**直接弃牌更优**，而所选策略没有充分弃牌。② `rank_aware` / `check_trap` 世界 Δvs_check/call 为 **−1.7 ~ −4.9**（check/fold 差值为大正数）：**假设「过度跟注」**（尚未用冻结 policy book 的可达公开历史给出分支级证据）。③ 选中候选由**合成 calling 生成器**产生 ⇒ 仅说明该候选家族的来源，**不等同于** Hero 的跟注频率。 |
| **C 动作网格 / 公开历史覆盖不足** | **本轮未触发** | `fallback_cases = 0`：没有任何世界因未覆盖历史而退化。零 fallback **不等于**能应对网格外动作（网格外下注仍不支持），但**不是本次 18 条的原因**。 |
| **D 桌规 / 字段 / 真实数据不足** | **长期缺口**（未作为本次归因假设） | `opponent_dataset_v1` 的严格准入下，真实可准入记录 = **0**；straddle 子类型、抽水、封顶保持 **UNKNOWN**（未确认为零）；`calibration_status=NOT_REAL_CALIBRATION`。这些限制本轮**未**直接造成 18 条负比较，但决定了本轮结论无法升级为真实对手证据。 |

**总判定（更正后）**：本轮**没有**实现/结算/信息集错误的证据，也**不能**宣布已排除全部实现问题；
C（动作网格/历史覆盖）在本轮未触发（fallback=0）；B 是**最值得检验的假设**，但尚无分支级证据；
D 为长期约束。事实 1/2 只影响**读数可读性**，不影响 18 这个场景级计数。

---

## 5. 模块能力地图与「决定复用」清单

| 模块 | 能力 | 本轮是否复用 | 结论 |
| --- | --- | --- | --- |
| `threeway_policy_evaluation_v1.py` | 冻结策略评价、fallback 记录、精确 Fraction EV | ✅ 实跑 | **复用**；B 阶段只加**可选终局路径 trace**（`evaluate_policy_book(..., trace=True)`），未重写 solver、未改策略选择/结算/基线 |
| `tools/threeway_path_diagnostics.py`（B 阶段新增） | 逐路径展开三套策略的终局路径、精确到达概率、条件终局 EV 与加权贡献，并做精确对账 | ✅ 实跑 | **新增工具**，只读复用同一内核；离线条件 EV，不是最优动作证明 |
| `response_model_calibration_v1.py` | 有限候选 log loss 选择、训练/验证隔离 | ✅ 间接（选择结果 `calling_public_v1`） | **复用**；不扩大模型族 |
| `robust_policy_selection_v1.py` | 最坏相对损失选择 | ✅ 间接 | **复用**；结论按 FAIL/INSUFFICIENT_EVIDENCE 表述 |
| `opponent_dataset_v1.py` | 真实数据准入闸门 | 未实跑 | **保持严格**；不用不足数据拟合 |
| `terminal_multiway_v1.py` | 终结 river all-in 条件 EV | 未实跑 | 保持边界，不与一般三人模块混淆 |
| `study_opponent_uncertainty.py`（工具） | 6 组多假设选择 | ✅ 实跑 | **复用**；exit 2 是设计信号需在文档中说明 |

**本轮没有新建任何 robust / 求解模块**，符合「不得再建一套同功能模块」。
