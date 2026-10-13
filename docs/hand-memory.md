# Hand Memory

In-memory, append-only store for poker hands.

## 职责

Hand Memory 负责「可靠地记住一手牌从开始到结束发生过什么」：
- 当前 `hand_id`
- `PokerState` 历史版本（snapshot）
- `StateEvent` 事件流
- 一手牌的生命周期
- 最终 `HandHistory`
- 可回放的数据（按 `state_version` / 追加顺序查询）

## 不负责

- 判断画面识别是否正确
- 推理玩家做了什么 / 计算下一状态（属于 State Engine）
- Equity / Strategy / Solver / Opponent Model / LLM / Decision / UI

一句话：State Engine 回答「这一步发生了什么」，Hand Memory 回答「把发生过的东西准确记下来」。

---

## 核心原则

- **Append-only**：已记录历史永不原地修改；只追加。
- **Single source of truth**：同一 `(hand_id, state_version)` 最多一个 PokerState。
- **Version monotonicity**：`new_version > latest_version`（严格递增，**允许跳号**，不强制 +1 —— 冻结架构的 PokerState 只要求 `>= 0`）。
- **Hand isolation**：不同 `hand_id` 的数据绝不串手。
- **Replayable**：`states()` / `events()` 输出有序快照/事件，供未来 Replay 使用（本任务不实现真正的 State Replay Engine）。
- **Atomic transition**：一个 canonical state 与其全部 events 要么一起提交，要么都不提交；确认切手时旧手完成与 successor 创建也必须一起成功或一起失败。
- **No database**：第一版纯内存。

---

## Lifecycle

```
不存在 → ACTIVE → COMPLETED
```

- `start_hand` 后为 ACTIVE，`complete_hand` 后为 COMPLETED。
- 内部用 `_HandRecord.completed is None` 表达状态，不新增 Memory 层枚举。

## Append-only / isolation

- 公开 read API 一律返回 `tuple`（不暴露内部 `list`/`dict`）。
- Core Domain Object 本身继续 immutable。

## state_version 规则

`record_state` 要求 `state.state_version > latest_state.state_version`。允许跳号（0 → 2 合法），拒绝倒退。

## event 规则

`record_event`：
- 事件 `hand_id` 必须匹配。
- `event.state_version` 必须对应当前 hand 中**已经存在**的 state snapshot（即 `get_state(hand_id, version) is not None`），**不是**只判断 `<= latest_version`（因为允许跳号）。
- 因此 Task 2 固定提交顺序：`record_state(new_state) → record_event(event)`，不实现 event-first buffering。

生产 Orchestrator 不再逐项调用上述低层 API，而调用 `record_transition(state, events)`。
该接口先验证 state/version/hand 以及所有 event 引用，再一次性追加，避免中间失败形成只有 state、没有 event 的半写记录。

## Idempotency

- `record_state`：相同 version + 相同 state → no-op；相同 version + 不同 state → `HandConflictError`。
- `record_event`：相同（值相等）event → no-op。
- `start_hand`：`(hand_id, initial_state, resolved started_at)` 三要素全同 → no-op；任一冲突 → `HandConflictError`。`started_at=None` 自动生成时**不保证**跨调用幂等，未来 Orchestrator 应显式传 `started_at`。

## single active hand（MVP）

当前单窗口/单桌，只允许一个 active hand。内部用 `dict[hand_id, _HandRecord]` + `_active_hand_id` 表达，不写死为永远无法扩展。

## read API

- `hand_exists` / `is_active`
- `latest_state` / `get_state(hand_id, version)` / `states`（升序）
- `events`（append order）
- `get_hand_history`（active hand 返回 None，不生成半成品）
- `completed_hands`
- `active_hand_id` property

## complete_hand / HandHistory 生成

- 必须先有 ≥1 个 state（`start_hand` 已把 initial_state 存为第一条，正常生命周期天然满足）。
- `players` 取 `latest_state.players`（最终参与者快照）。
- 通过正式 `HandHistory` constructor 构造（不 bypass invariant）。

确认新手牌边界时使用 `replace_active_hand(...)`：先验证 `HAND_END`、最新 state version、
successor hand_id、时间顺序并构造完整 `HandHistory`，全部成功后才同时完成旧手和创建新 active hand。
已有 successor、错误事件或时间无效时，旧手的 states/events/history/active identity 保持不变。

## replay boundary

HandMemory 只暴露 `states()` / `events()`，不新增 `get_replay` / `HandReplayData`，也不从事件流重建
状态。`poker_engine.replay` 是独立的 Capture Replay 验收器：从 hash-pinned 原始帧或稳定 Observation
重新执行 Recognition→State/Event 并比较预期；它不改变 HandMemory 的 event-sourcing boundary。

## persistence boundary

纯内存，不实现 `save/load/dump/restore`。持久化（Repository Adapter）属未来任务。
