# AA-FIELD-ANNOTATIONS-V1 · 来源绑定的开发字段标注与不可逆曝光历史

> 状态：**P0 已实现（PR pending review）**。本模块是 #19 的**选择性迁移**结果，不是 #19 的原样合并。
> 依据：Issue #27 `issuecomment-5724976158` · `PR19_FINAL_ARCHITECTURE_DECISION_READY`（裁决 `MIGRATE_SELECTED_THEN_CLOSE`）。
> 实现：`tools/aa_annotation_records.py`；测试：`tests/tools/test_aa_annotation_records.py`。

---

## 0. 正向消费许可在本 P0 是关闭的（重要）

当前 main **不存在**受审的 consumer registry，也不存在全局 store inventory。本模块**不自行发明第二套 policy authority**，因此：

- `assess_use` 恒定返回 `BLOCKED`（`usable_scope = ANNOTATION_ONLY`），并携带 `trusted_consumer_registry_unavailable` 与 `global_history_inventory_unavailable`；
- `history_coverage` 恒为 `UNKNOWN`，空事件集**永不**被表述为 `NO_EXPOSURE_RECORDED_UNDER_DECLARED_COVERAGE`；
- `reserve=True` 不会产出 receipt。

这是**保守闸门，不是设计缺陷**：本 P0 的价值是「标注修订历史 + 曝光历史」，不是给训练系统发通行证。宁可 false-negative，不能错误 ALLOWED。未来接入受审 consumer adapter 后，这两个常量是唯一需要打开的位置。

---

## 1. 这是什么，不是什么

**是**：AA 视觉开发的**数据治理记录**——把「某来源帧的某个字段，人工标注成什么、改过几次、被训练消费过哪一版」做成可追溯的事实。

**不是**：

- 不是truth source。标注 ≠ holdout gold、confirmed poker facts、合法行动历史、PHH confirmed actions、策略资格、验收结论。
- 不是训练平台。不训练、不导出训练样本、不生成 crop、不调用模型、不发 HTTP、不做 UI。
- 不是第二套准入体系。用途资格**只读派生**；reservation 权威只来自当前 main 既有受审工件（`aa_holdout_reservations_v1.json`），**客户端传入的字典从不构成权威**。
- 不是 P1。金额/glyph 导出、UI 字段编辑区、更多字段词汇、历史标签导入均**未迁**。

---

## 2. P0 保留的三类价值

| 类别 | 内容 |
| --- | --- |
| **A. 来源绑定的逐字段开发标注** | 同一 `(source identity, field_id, seat)` 上的 KNOWN / UNKNOWN / NOT_APPLICABLE 标注 |
| **B. append-only 修订历史** | 更正只能追加新 revision，`supersedes` 指向旧值，`expected_revision` 不匹配即拒；旧 revision 永久可读；恢复时**整图校验**（见 §5） |
| **C. 不可逆 training exposure history** | 来源级使用事件单调累积；修订、改名、换 replay/目录/模型、撤回标签、re-audit、媒体别名、crop 重建、新建 store 都**不能**把它变回 untouched holdout |

已**明确不迁**（见 §9）：逐事件 hash chain、旧 9 槽/1801 帧 UI 与 HTTP、`zone==development` 旧分区布尔、`strategy_ready`/`strategy_eligible`、训练标签导出。

---

## 3. 首批支持的字段

| field_id | 含义 | 值类型 | unit | 备注 |
| --- | --- | --- | --- | --- |
| `pot_display` | 显示的底池数额 | `int`（>=0，KNOWN 时必须给值） | 必填，现仅 `chips` | 只表示**显示底池**；`current_street_wager` / `call_price` / `cumulative_commitment` 等 amount role 一律拒绝 |
| `visible_action_glyph` | 可见的动作字样 | `str` ∈ {fold, check, call, bet, raise, all_in, muck, none} | 不允许 | 只表示**可见字样**；携带 `full_actions` 一律拒绝 |

**未知 `field_id` 一律 fail closed**：

- `seat_presence` / `current_bet` / `street_wager` / `actor` / `special_mode` → `UnsupportedFieldError`（P1 候选，需先定义可见语义与 UNKNOWN 规则）
- `full_actions` / `acceptance` / `strategy_eligible` / `canonical_verified` / `confirmed_facts` / `holdout_gold` / `phh_confirmed_actions` / `strategy_ready` → `ForbiddenTruthFieldError`（**永不开放**：标注不是这些事实的归属）

---

## 4. Source identity：证据身份 ≠ 长期曝光身份

`source_ref` 必须携带，且**拒绝** `path` / `current_path` / `replay_name` / `replay_file` / `ui_index` / `display_index` 等可变定位与 UI 行号作为身份。

| 字段 | 含义 |
| --- | --- |
| `source_audit_ref` + `source_audit_sha256` | 来源/审计/清单引用（**provenance evidence**） |
| `media_id` + `media_sha256` | 媒体身份（**provenance evidence** + content root） |
| `frame_index` + `frame_sha256` | 帧身份（content root） |
| `layout_id` / `slot_count` / `slot_mapping` | 布局与槽位映射；**只支持 8 物理槽位**，不做 9→8 猜映射 |
| `observation_snapshot_digest` | observation / replay 快照摘要（不进长期曝光身份） |
| `implementation_revision`（可选） | 实现 / 模型版本（对照物，不参与任何身份键） |
| `parent_frame_ref`（可选） | 派生 crop 的父帧身份；**只允许一层**（见下） |

所有 SHA-256 字符串在参与任何身份键之前**统一规范化为 lowercase**，因此同一 digest 的大小写写法不能分裂成两个身份。

### 4.1 两个身份

| 键 | 绑定内容 | 用途 |
| --- | --- | --- |
| `source_key` | `source_audit_ref` + `source_audit_sha256` + `media_id` + `media_sha256` + `frame_index` + `frame_sha256` | **证据身份**：标注修订分组，标识「这次标注是针对这份审计做的」 |
| `exposure_root_key` | 规范 `media_sha256` + `frame_index` + `frame_sha256`（**仅此三项**） | **长期内容/曝光身份**：re-audit、清单重建、media 别名都不得重置曝光 |

推论：

- 同内容 re-audit / 换 `media_id` / 重建清单 ⇒ `source_key` 变、`exposure_root_key` **不变** ⇒ 历史 `ACTUALLY_CONSUMED` 仍能找到；
- 真实 `media_sha256` 不同 ⇒ `exposure_root_key` 不同 ⇒ **不串**；
- layout / slot mapping / observation snapshot / 模型版本不进 `exposure_root_key` ⇒ 重新识别不会重置历史。

### 4.2 身份等级

- `COMPLETE` — 全部就位、槽位映射是 0..7 双射、**且父帧（若有）完整合法** ⇒ 才可能进入后续用途判定
- `INCOMPLETE` — 核心身份在，但布局/摘要/槽位/父帧不全 ⇒ **只能 `ANNOTATION_ONLY`**
- `UNBOUND` — 核心身份缺失 ⇒ 连稳定身份键都算不出来，不可记录 exposure

### 4.3 Parent lineage（只允许一层）

`parent_frame_ref` 必须在**计算 identity_class 之前**完整校验：

- 空 / 非映射 / 键未知 / SHA 非法 / `frame_index` 非法 ⇒ 记为 gap，父键为 `None`，identity 降级 ⇒ BLOCKED；
- **父帧自身还带 `parent_frame_ref` ⇒ `nested_parent_not_supported`，直接 BLOCKED**（P0 不支持任意嵌套 DAG，也不静默只查一跳）；
- `assess_use` 同时校验 **child 与 parent/root** 的 reservation / policy；父帧 reserved ⇒ child BLOCKED；
- exposure 查询同时覆盖 child 与 parent 的 `source_key` / `exposure_root_key`，保留**最高**污染状态。

---

## 5. 标注记录 schema（append-only JSONL）

每条 revision 含：`schema_version` / `event_id` / `revision_id` / `recorded_at` / `actor` /
`source_key` / `exposure_root_key` / `parent_source_key` / `parent_exposure_root_key` /
`identity_class` / `identity_gaps` / `source_ref` /
`field_id` / `seat` / `status` / `value` / `unit` / `reason` / `supersedes` / `expected_revision` /
`model_output` / `model_reason` / `model_output_seen` / `implementation_revision` / `observation_snapshot_digest`。

**UNKNOWN 是一等状态**：

- `status=UNKNOWN` ⇒ `value` 必须为 `None` 且必须有 `reason`；**绝不**折叠成 0 / false / none
- `status=KNOWN` 且 `value=0` 是合法标注，与 UNKNOWN 严格区分
- `status=KNOWN` 且 `value="none"`（可见字样为无）与 UNKNOWN 严格区分
- `status=NOT_APPLICABLE` ⇒ 必须有 `reason`（上下文依据），且不得携带值
- **写入与磁盘恢复复用同一套 KNOWN / UNKNOWN / NOT_APPLICABLE 校验器**；磁盘上的 `KNOWN + null` 一律拒绝

`model_output` / `model_reason` / `model_output_seen`（YES / NO / UNKNOWN）是**对照材料**：
绑定当时的 observation 快照与实现版本，不随新模型或新 replay 回填；human value 不因模型输出而改变。
看过模型预测的标注保留 `model_output_seen=YES`，未被策略显式允许（`allow_model_assisted_labels`）时不能进 Independent 用途。

**当前值只按 `supersedes` / revision 折叠，不按时间戳猜赢家**。

### 5.1 修订图全量校验（读取即校验）

`AnnotationStore.read_annotations()` 在返回前对**整个 store** 做语义校验，任何一项不通过即 `StoreIntegrityError`（不静默修复、不部分信任）：

- `revision_id` **全局唯一**；
- 从存储的 `source_ref` **重算** `source_key` 与 `group_key` 并比对 ⇒ 禁止磁盘伪造 group key / source key；
- 每行重新执行字段与标签校验器（含 `KNOWN + null` 拒绝）；
- `supersedes` 必须存在（禁止 orphan）、必须属于**同一 source + field + seat**（禁止 cross-source / cross-field / cross-seat）、必须与 `expected_revision` 一致；
- 禁止环（cycle）；每个 revision group 必须恰有 **一个 root** 与 **一个 head**；
- **坏图不能靠 `append_annotation(expected_revision=None)` 另开 root「修复」**：追加前先校验既有 store。

---

## 6. Exposure invariant（长期不变量）

> 一旦某来源帧或其派生样本进入 **training / tuning / template_selection**，任何后续修订、撤回标签、replay 重建、改名换目录、crop 重建、模型变化、re-audit / media alias、新建 store，**都不能把这次使用从历史中抹掉，也不能据此恢复成 untouched holdout**。

- exposure event 记：`purpose` / `evidence_kind` / `annotation_revision_ids` / `annotation_revision_refs` / `source_key` / `exposure_root_key` / `parent_source_key` / `parent_exposure_root_key` / `consumer` / `run_or_manifest_ref` / `artifact_ref` / `role` / `policy_ref` / `policy_violation` / `binding_status` / `binding_reasons` / `contamination_keys`
- `evidence_kind` 四态严格区分：`RESERVED` / `RELEASED` / `POSSIBLY_USED` / `ACTUALLY_CONSUMED`
- **状态单调**：`RESERVED → RELEASED` 仍是 `EXPOSED_POSSIBLY_USED`；出现过 `ACTUALLY_CONSUMED` 则永久 `EXPOSED_ACTUALLY_CONSUMED`
- **没有记录 ≠ never_trained**：历史覆盖无法证明时状态为 `EXPOSURE_UNKNOWN` 且 **BLOCKED**
- **违规事实必须记录**：`policy_violation=True` 的事件照常落盘并保留；错绑的历史事件保留但标为 `UNRESOLVED`，永不成为可信消费事实
- 训练过的**开发数据**依策略可以再次训练（`allow_reuse_of_exposed_development`）；永久禁止的是把它**伪装成独立 holdout**
- 记录持久化失败 ⇒ 消费者**拿不到** receipt（`consumption_record_not_durable` + BLOCKED）

### 6.1 Multi-store history coverage 规则

`assess_use` 与 `exposure_projection` 使用**同一个**历史读取器：

1. 读取**全部** declared store（含 own store 未声明时补读自身），不再各自为政；
2. 合并后**再按目标 canonical `source_key` / `exposure_root_key`（含 parent）过滤** ⇒ unrelated source 的曝光既不污染目标，也不会被漏掉；
3. 跨 store **同 `event_id` + 同内容 ⇒ 显式去重**；**同 `event_id` + 内容冲突 ⇒ 报 `cross_store_event_id_conflict` 并 BLOCKED**；
4. **空目录不能证明 coverage COMPLETE**；**仅 caller 自报 `declared_store_paths=[B]` 不能证明 A 不存在**；
5. 当前无受审全局 inventory ⇒ `history_coverage` 恒为 `UNKNOWN`；declared store 缺失/损坏 ⇒ 追加 reason 且状态 UNKNOWN/BLOCKED。

### 6.2 消费 revision / source 绑定

`record_exposure` 逐条解析被消费的 revision，全部满足才落盘 `binding_status="BOUND"`：

- revision 存在；
- 属于目标 source lineage（`source_key` ∈ {target, parent}）且 `exposure_root_key` 匹配 ⇒ **禁止 source A 事件引用 source B 的 revision**；
- `(field_id, seat)` 精确命中 consumer 的 `required_targets`；
- `ACTUALLY_CONSUMED` 时该 revision 必须是 `KNOWN` ⇒ **UNKNOWN 不得当成已消费标签**；
- consumer 声明的每个 target 都必须被实际消费 ⇒ 不允许「某 seat 有一个 KNOWN 就算整组满足」；
- receipt 只记录这个**精确集合**，不会把其它 seat 的 UNKNOWN revision 顺带写进去；
- `run_or_manifest_ref` 必须是非空映射且带稳定 `kind` + `digest`/`sha256`/`ref`；空 dict 拒绝。

### 6.3 统一 binding validator：持久化 `binding_status` 不是权威

**一条 exposure 行上的 `binding_status` 只是写它的人在当时的声明，从不是权威。**
新写入路径（`record_exposure`）与全部历史恢复路径（`assess_use` / `exposure_projection`）
共用**同一个**内部校验器 `_evaluate_exposure_binding`，从同一批输入重新派生有效绑定：

- 事件自己的 `source_ref`；
- 它引用的每个 annotation revision 重新解析出的 `source_key` / `exposure_root_key`；
- 该 revision 的 **canonical parent exposure identity**（长期 root 身份，不是 provenance 显示名）；
- revision 的 `field_id` / `seat` / `status` / `identity_class`；
- consumer 的 `required_targets` 与 `run_or_manifest_ref`。

派生结果 = `effective_binding_status`：`BOUND` 仅当**全部**条件满足，否则 `UNRESOLVED`。
存储的 `BOUND`、存储的 `UNRESOLVED`、`binding_status` 缺失（旧格式）三者走**同一条**重新派生路径：
只要底层事实不满足契约，三者都得到 `UNRESOLVED`。存储值只在派生结果里保留为
`claimed_binding_status`（历史声明），不参与判定。

**R1 — 新事件不得 re-parent 已标注的 revision。** caller 不能在 `record_exposure` 里
把一个 `parent_frame_ref = A` 的 crop revision 用 `parent_frame_ref = B` / 删除 parent /
`parent_frame_ref={}` 的方式消费后仍然得到可信 `BOUND`：

1. revision parent=A，caller parent=B ⇒ **非 BOUND**；
2. revision parent=A，caller 删除 parent ⇒ **非 BOUND**；
3. revision parent=A，caller parent={} ⇒ **非 BOUND**；
4. revision 自身 parent lineage **INCOMPLETE** ⇒ **非 BOUND**（可保留历史事实，但
   trusted binding=NO、`freeze_bindable`=NO、independent clean claim=NO）；
5. **合法 provenance 别名**（re-audit / manifest rebuild / media_id 改名，canonical parent
   exposure root 未变）⇒ 绑定正常，不因改名误拒、也不因改名清除污染。

错绑的新事件**不写成可信 BOUND**：它照常落盘（历史事实不删除），但为
`binding_status="UNRESOLVED"` + `policy_violation=True` + `binding_reasons`，
并把 **revision 已知 lineage ∪ caller 声明 lineage** 一起写进 `contamination_keys`——
不会因为调用方说 B 就丢掉 revision 已知的 A。

**R2 — 历史恢复必须重新验证。** `_read_declared_stores` 在合并事件后建立
annotation revision 索引，逐条解析 `annotation_revision_ids`，再派生出每个事件的
`effective_binding_status` 与 **effective contamination keys**（事件声明的 lineage ∪
被引用 revision 能证明的 lineage）。
`_filter_events` / `assess_use` / `exposure_projection` 一律使用这套 effective keys：

- 错误历史**保留、不删除**；
- event 自报 A、revision 实际属于 B ⇒ **A 与 B 都至少保守污染**，B 不会被洗白；
- 无法解析的 revision ⇒ 不猜 clean，保持 `UNRESOLVED` / 非可信；
- 历史 consumer targets / field / seat / revision 列表 / `run_or_manifest_ref` 任一不再满足
  真实 binding 契约 ⇒ 有效绑定降级；
- 跨 store 同名 revision 派生产物不一致 ⇒ `binding_revision_ambiguous:*`，永不 BOUND。

#### 6.3.1 同名 revision 的多候选：`revision_id` → **全部**候选 lineage

索引不是 `revision_id → 单个 lineage`，而是 `revision_id → 全部候选 lineage`
（`_add_revision_candidate` / `_revision_candidates`）。判定规则：

- **候选去重**：两个 store 里同一 `revision_id` 的**完整派生产物完全相同**
  （source/root/parent/identity_class/parent_gaps/field/seat/status/group_key 全等）
  ⇒ 视为同一事实的副本（备份 / 复制的 store），**去重为一个候选，不报冲突、
  不降级**；
- **真歧义**：同一 `revision_id` 的派生产物**任一环不同** ⇒ 全部候选**并列保留**，
  有效绑定 `UNRESOLVED`，**不挑选任何一方成为可信事实**；
- **污染并集**：`contamination_keys` = 事件声明的 lineage ∪ **每一个**候选的
  child source / child exposure root / parent source / parent exposure root。
  无法确定错误事件到底消费了哪个候选时，**全部保守污染**；
- **顺序无关**：declared store 的读取顺序只影响候选进入索引的先后，污染并集、
  `binding_reasons`（`sorted(set(...))`）与有效绑定都是集合运算 ⇒
  `[E, A, B]` 与 `[E, B, A]` 的结果**完全一致**。不得出现「先读到的一方才被污染、
  后读到的一方从曝光查询里消失」；
- **无关来源隔离**：与事件及各候选都没有证据关系的来源（D / PD）**不被污染**，
  仍为 `EXPOSURE_UNKNOWN` + `no_exposure_history_evidence`。

`binding_reasons` 前缀：`binding_event_identity_not_complete` ·
`binding_revision_unresolvable:*` · `binding_revision_ambiguous:*` ·
`binding_revision_lineage_mismatch:*` · `binding_revision_identity_not_complete:*` ·
`binding_revision_parent_incomplete:*` · `binding_parent_lineage_mismatch:*` ·
`binding_revision_target_mismatch:*` · `binding_revision_not_known:*` ·
`binding_consumed_revision_set_missing` · `binding_consumer_target_not_covered:*` ·
`binding_consumer_targets_unreadable` · `binding_consumer_identity_missing` ·
`binding_consumer_identity_invalid:*` · `binding_run_ref_invalid:*`。
在 `exposure_projection` 行里以 `binding_reason:<token>` 出现在 `unresolved`，并使
`freeze_bindable=False`。

---

## 7. 最小 API

| 函数 | 职责 |
| --- | --- |
| `append_annotation(store, source_ref, field_id, seat, label, expected_revision, actor, ...)` | 追加一个明确修订，返回 `revision_id`；追加前校验既有 store 图完整性 |
| `get_annotations(store, source_ref, include_history=False)` | 只读当前标注与历史；按 `supersedes` 折叠；store 语义损坏则抛错 |
| `assess_use(store, source_ref, purpose, policy_bundle, *, reserve=False)` | 只读派生用途结论；客户端不能提交 `training_eligible`，也不能提交权威 |
| `record_exposure(store, source_ref, annotation_revision_ids, purpose, run_or_manifest_ref, evidence_kind, *, consumer=..., ...)` | 追加绑定到具体 revision/consumer 的使用/释放/消费/违规事实 |
| `exposure_projection(store, scope)` | **供未来受控 freeze adapter 使用的只读行视图**（见 §8） |
| `validate_annotation_rows(rows)` | 修订图全量语义校验，供外部复核 |

### 7.1 `assess_use` 的权威来源（客户端字典不是权威）

| 判据 | 权威来源 |
| --- | --- |
| reserved 区间 | 仓库受审工件 `configs/reproduction/aa_holdout_reservations_v1.json`，经 `validate_reservations` 校验 |
| caller 另传 `reservations` | 只做**比对**；不一致即 `caller_reservations_do_not_match_canonical_artifact`，**不覆盖** |
| development role | 帧必须落在工件的 `known_development_inclusive_intervals` 内，且不在 reserved、不在 exploration |
| `development_evidence_ref` | **纯 provenance，零权威**。任意字符串（含 `"anything"`）都不产生授权 |
| `policy_ref` / `role` | 纯元数据，不产生授权 |
| 正向消费许可 | 需要受审 consumer registry —— **当前不存在**，故恒 BLOCKED |

### 7.2 `assess_use` fail-closed 清单

以下任一命中即为 `BLOCKED`（`usable_scope = ANNOTATION_ONLY`）：

`policy_bundle_missing` · `policy_ref_missing` · `purpose_unsupported` · `source_identity_incomplete:*` ·
`trusted_reservation_artifact_missing:*` · `trusted_reservation_artifact_unreadable:*` ·
`trusted_reservation_artifact_invalid:*` · `trusted_reservations_unavailable` ·
`caller_reservations_not_authoritative` · `caller_reservations_do_not_match_canonical_artifact` ·
`reservation_artifact_sha_mismatch` · `frame_reserved_or_invalid:child|parent` ·
`frame_not_in_trusted_development_intervals:child|parent` ·
`exploration_frame_is_not_development_authority:child|parent` ·
`role_unknown:*` · `calibration_role_has_no_trusted_interval_authority` ·
`required_annotation_missing:*` · `required_annotation_not_known:*` · `required_field_unsupported:*` ·
`annotation_history_conflict` · `annotation_store_integrity_error:*` ·
`model_assisted_label_without_policy` · `consumer_identity_missing` · `consumer_identity_malformed` ·
`trusted_consumer_registry_unavailable` ·
`exposure_history_coverage_undeclared` · `declared_store_missing:*` · `declared_store_unreadable:*` ·
`own_store_not_declared_in_history_coverage` · `global_history_inventory_unavailable` ·
`cross_store_event_id_conflict:*` · `history_event_without_id` ·
`exposure_history_unknown` · `possibly_used_reuse_not_declared` ·
`exposed_development_reuse_not_declared` · `known_policy_violation_exposure` ·
`holdout_training_history_cannot_be_redeveloped` · `exposure_event_not_bound:*` ·
`consumption_record_not_durable` · `consumption_reservation_refused:*`

**「不在 reserved」绝不等于「自动可训练」**：仅 `assert_training_frames` 通过而缺少 development 区间证明、consumer 绑定、完整历史覆盖时仍然 BLOCKED。

---

## 8. 与现有体系的关系（桥接方向）

| 现有对象 | 本 P0 的关系 |
| --- | --- |
| `aa_data_separation` / `aa_holdout_reservations_v1.json` | **只读复用**：`validate_reservations` + `assert_training_frames`；reserved 权威只来自该工件。**未修改、未放宽**任何旧门禁 |
| `freeze.exposures` | **行视图，未接通**：`exposure_projection()` 返回带 `rows` 的 envelope，行的 `used_for` / `role` / `artifact_sha256` 与 `validate_freeze` 字段兼容，但**它是供未来受控 freeze adapter 使用的行视图**，并未接通 `aa8_holdout_plan.validate_freeze`；后者不理解 coverage / unresolved / bindable 等完整性字段，也没有 adapter 调用本投影。`freeze_bindable` **只表示投影内部完整性条件**，不代表 `validate_freeze` 已接受或已验证其完整治理语义；`freeze_adapter_attached` 恒为 `False`。**未修改** `aa8_holdout_plan.py` 来制造接通 |
| AAReviewDesk | **无桥**。截图 verdict/note 不解析成字段值，不回写 observation |
| `aa8_gold_registry_v2` | **无导入桥**。gold 仍走既有独立审阅流程 |
| `aa_analysis_records` / `aa_study_records` / `aa_hand_input` | **无桥**。分析、合成研究、手工假设均不自动变成标注 |
| `aa_semantics` / PHH / 策略路由 | 无任何写入路径 |
| UI / HTTP / export | **未迁**（P1）。未改动 `ui/`、`tools/aa_replay_viewer.py`、任何 HTTP endpoint |

---

## 9. 明确未迁（P0 边界）

- **逐事件 hash chain**（`previous_sha256` + `entry_sha256`）：**未迁**。保留 source / frame / artifact / snapshot 摘要作为身份锚点，但没有任何链式依赖；不引入签名、Merkle、数据库、事件总线或外部锚。
- **UI / HTTP 标注入口**：未迁。
- **训练标签导出**（money/glyph）：未迁。
- **旧真实台账自动导入**：未做，也未检查历史标签文件是否存在。
- **旧 9 槽 / 1801 帧固定 replay**：未迁，`slot_count != 8` 直接判定身份不完整。
- **reserve 并发互斥**（P1）：锁只串行化「检查后追加」中的追加，不覆盖整个判定；两个交错的并发 reserve 可能各写一条 RESERVED。不引入数据库 / 事务服务 / 分布式锁 / 事件总线。
- **crash recovery**（P1）：不做断电恢复或目录 fsync 证明。

---

## 10. 持久化与完整性

单命名空间 `annotations.jsonl` + `exposures.jsonl`，append-only，写入 `fsync`，附简易独占文件锁。

读取时**不静默修复**：空白行、坏 JSON、未知 `schema_version`、错误 `event_type`、重复 `event_id`、修订图语义损坏（§5.1）一律 `StoreIntegrityError`。

**行为边界（与实现一致）**：

- **declared store** 损坏/不可读 ⇒ `assess_use` / `exposure_projection` 回落为 UNKNOWN / BLOCKED，不抛给调用方；
- **own store** 损坏 ⇒ `assess_use` 捕获后记 `annotation_store_integrity_error:*` 并 BLOCKED；但直接调用 `get_annotations` / `append_annotation` / `record_exposure` **可能抛出** `StoreIntegrityError`（或非法 UTF-8 时 `UnicodeDecodeError`），**不是**一律结构化回落。
- 完整 JSON 但末尾缺换行会让后续追加粘连，进而被读取判为坏 JSON；这是已知的本地单用户限制，不做静默修复。

---

## 11. 状态边界

`REAL_HAND_ACCEPTANCE_PENDING` 与 `NOT_ASSESSED` **继续保留**。
本模块不宣称：真实牌局验收通过、PHH 可导出真实手牌、策略/盈利已验证、GTO 已完成、holdout 已合格、既有训练入口已全部接入拦截器。
P0 只证明：**这个新入口的标注 / 修订 / 曝光契约成立**，且**不给任何未受审的消费者发正向许可**。
