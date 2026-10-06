# AA8 Artifact 验真与 Actor Episode Census V1

本轮承接完整决策机会合同，完成两个离线基础设施：从完整 gameplay JSONL 中枚举
actor cue episode；把当前 readiness、episode、协议、复核和 V2 observations 复制
到封闭 bundle，用同一文件句柄核对路径、字节、schema 和逻辑绑定。

它们都只服务人工复核队列，不运行对手模型、范围学习或策略。

## Actor episode 规则

只枚举两个时间完整手的 gameplay 区间：

- `aa8_late_dev_hand_005`：25492–27349；
- `aa8_late_dev_hand_006`：27474–28928。

Leading context、settlement 和不完整尾手不进入 episode 分母。每个连续、相同的
`current_actor` 构成一个原始 episode；UNKNOWN、不同 actor、不支持场景和手边界
都会硬切。UNKNOWN 不被解释为“无人行动”，也不自动用历史填充。

动作关联只使用 30 条 `MATCH_VISIBLE_COMPLETED_ACTION`，并要求同手、同座位、
一个 episode 最多关联一个 action。动作确认位于 episode 内，或发生在 episode
结束后最多 12 帧时，选择最近且尚未使用的 episode。这个距离只表示动作完成
字形的时间关联，不是 action onset、predecision snapshot 或合法菜单真值。

Episode 不会仅因 `board_count` 转街而被人为切开。26 个绑定的 episode 与复核动作
street 完全一致；另有 2 个 episode 自身跨 street，保留为
`EPISODE_STREET_AMBIGUOUS`。只有 episode 已有单一明确 street 且与动作冲突时才拒绝
绑定，并且该冲突候选不会占用 episode。

## 实际 census

Gameplay 共 3313 帧：

| 项目 | 数量 |
|---|---:|
| Known actor frames | 2472 |
| UNKNOWN actor frames | 841 |
| Supported actor UNKNOWN | 813 |
| Unsupported scene | 28 |
| UNKNOWN spans | 14 |
| Actor episodes | 32 |
| Episode↔action 绑定 | 28 |
| 没有 action 候选的 episode | 4 |
| 没有 episode 的 reviewed action | 2 |
| Episode∪action 待复核候选 | 34 |

四个无动作候选的 episode：

- Hand 005 episode 003，seat 7，25787–25862；
- Hand 005 episode 011，seat 7，26326–26401；
- Hand 006 episode 010，Hero seat 4，28236–28304；
- Hand 006 episode 012，seat 7，28344–28418。

两个孤立动作候选：

- A10，Hand 005 seat 7 fold，frame 26428；最近同座位 episode 相隔 27 帧；
- A33，Hand 006 Hero seat 4 all-in，frame 28342；最近同座位 episode 相隔 38 帧。

两者都超过预注册的 12 帧上限，不能为提高绑定率而强行关联。32 和 34 都只是
detector/review queue 数量，不是实际 all-opportunities 分母。仍可能存在没有
actor cue、自动 check/timeout、特殊遮罩或 detector miss 的真实机会。

最终 episode 文件：

`G:/PokerSense_private/aa8_actor_episode_census_20260914_v6/episodes.json`

SHA-256：`1bb9cfda2a12ed49fb167ffdf8f243c7a7b6e20644fb0fce875979e1a2cfd9b8`。

v1/v2/v3、失败后留下的空 v4 和被当前逻辑取代的 v5 全部保留；它们不作为本轮
最终证据，也没有被覆盖或删除。

## 封闭 artifact bundle

`build_aa8_artifact_bundle.py` 创建一个新目录，按固定九种 role 原字节复制：

- decision readiness；
- actor episode census；
- 两份 reproduction protocol；
- hand registry；
- action review config/result；
- V2 report；
- V2 observations JSONL。

不复制或读取原始视频、PNG、身份截图、规则截图或保留区素材。Manifest 的 file
表与 role binding 表必须一一完整覆盖，不能由调用者删掉困难证据角色。

最终 bundle：

`G:/PokerSense_private/aa8_decision_artifact_bundle_20260914_v4/`

Manifest SHA-256：
`2b5ad31b77bad1cb5bf08e175eaa7c27d9aa515307699fa566cee201bcc1df5c`。

## Verifier 安全边界

`verify_decision_opportunity_artifacts.py` 要求外部传入 manifest SHA。路径必须是
Unicode NFC 的 POSIX 相对路径；绝对路径、盘符、UNC、反斜线、冒号、空段、
`.`、`..`、NUL、尾随点/空格及大小写别名均拒绝。Bundle root、祖先目录和文件
均拒绝 symlink、junction/reparse，硬链接别名也拒绝。

每个文件按以下顺序读取：

```text
lstat → resolve/containment → os.open(O_NOFOLLOW) → fstat
→ 同一handle读取并hash → 再次fstat/lstat/resolve
```

JSON/JSONL 从刚刚哈希的同一份 bytes 解析，拒绝重复 key、BOM、超大文件、过长
行和过多行。Verifier 不使用“先 hash(path)，再 read_text(path)”的可替换窗口。

字节哈希通过后还会对两份 protocol 执行 exact-schema 检查；从固定快照重新运行
`audit_decision_opportunities()`，并用纯函数重建 actor episode census。保存的
整个 readiness wrapper、其中的 audit、episode 全字段、candidate inventory、
输入哈希、dataset/session ID 和 action 一对一库存必须与重算结果完全相同。全部
禁止放行字段必须存在并严格保持 false/null。语义核对结束后会再次枚举，确保
bundle 文件集合未变化；每个文件的 identity 在其稳定读取期间核对。

最终验证报告：

`G:/PokerSense_private/aa8_decision_artifact_verification_20260914_v4/report.json`

SHA-256：`76e813b7ad0c11e8547ab02f4a993f32f657e0bc1b6a88d0ac264d4b934c6e84`。

九个文件和九个 binding 全部通过，但状态只能是
`VERIFIED_CURRENT_BLOCKED_METADATA_SNAPSHOTS`。这个状态只证明 verifier 在一次
稳定读取中重新计算并核对的 JSON/JSONL bytes 集合；它不证明录像内容、真实规则、
完整决策机会或未来文件状态。报告保留六个 blocker：

1. source dataset 本身仍 BLOCKED；
2. raw recording 没有进入 bundle，也没有读取；
3. 稳定身份制品缺失；
4. 真实规则制品缺失；
5. 完整合法菜单制品缺失；
6. 独立 episode coverage 缺失。

所有输出继续固定：`ready_for_offline_calibration=false`、
`model_fit_executed=false`、`selection=null`、`calibration=null`、
`range_model=null`、`strategy_eligible=false`、`advice_emitted=false`、
`live_use=false`。当前 verifier 没有任何实际 promotion 路径。

## 下一步

下一阶段要由人工完整时间线复核把 34 个候选逐项分类，并允许添加 detector miss
episode；同时补稳定身份、真实规则、合法菜单和 coverage review bundle。只有新
的完整制品链通过文件级和人工签收，才能另建离线校准收据。本轮没有读取媒体、
没有触及 300–820 秒保护区、没有启动设备或策略。
