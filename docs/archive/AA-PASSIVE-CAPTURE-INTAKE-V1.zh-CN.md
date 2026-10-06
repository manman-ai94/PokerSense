# AA 被动实战采集入库 V1

本模块把“允许采集新的真实牌局视频”和“允许识别、策略、Advice 或自动操作”拆成
两个永不混用的权限。V1 只完成以下链路：

```text
一次性人工授权
→ 固定实体手机/UVC采集卡的被动video-only录制
→ 安全停止和60秒分段封装
→ 新录制分段的SHA-256完整性收据
→ 人工签收
```

它不加载 desktop live、识别器、状态引擎、Provider、equity、策略、Advice、ADB、
网络或输入控制。它不接受 source、replay、input-video、URL、filter 或额外 FFmpeg
参数，因此不能用来读取 `G:/PokerSense_archive`、旧私有录像或历史保护区。

## 权限边界

“继续开发”“尽快进入实战”等指令只授权代码开发。每次真正打开采集卡前，用户必须
针对一个 session 明确说出“可以开始本次被动实战采集”，并生成一份新的授权文件。
授权最长有效 24 小时，一次 nonce 只能消费一次；停止、失败或录制完成后不能自动
重试或继续。新 session 需要新授权。

授权固定以下能力为 false，JSON 中缺字段、类型错误或改成 true 都会在创建设备
进程前拒绝：

- recognition；
- strategy；
- provider；
- equity；
- advice；
- live control；
- automated input；
- network；
- audio；
- emulator；
- ADB。

原始录像只能保存到 `G:/PokerSense_private` 的全新直属目录，session ID 必须以
`aa-live-` 开头。正式入口使用全局 device lock，防止同一入口并发启动；进程异常
退出留下的锁不能自动清理，必须先人工调查。授权 nonce 会在打开录制进程前写入
一次性账本，失败也不会退回。

入口在写入并 `fsync` 锁内容后重新取得文件身份。正常完成或捕获到的异常退出只会
删除身份未变化的自有锁；若锁路径在运行中被替换、改写、改成链接或 reparse point，
入口会保留它并要求人工调查。这样既避免把 0 字节创建时的大小误当成最终身份，也
不会清理不再属于当前进程的锁。

`aa_record_session.py` 和 `record_aa_capture_test.py` 属于既有冻结开发工具，保留其
原字节和历史 CLI，正式 intake 不导入或调用它们。与直接运行 FFmpeg 一样，V1
无法阻止操作者主动绕过正式入口；硬件演练前必须确认这些旧工具、桌面应用和其他
摄像头软件均未运行。项目验收只承认由本 intake 的授权账本、device lock、plan
和最终收据闭合的新 session。

## 两步采集顺序

第一步必须是 5–30 秒的 `hardware_dry_run`。它验证固定链路：

- `UGREEN 25854`；
- DirectShow；
- 1920×1080；
- 30 FPS；
- MJPEG 输入、MKV 分段、stream copy；
- 无音频；
- 最多 20 GiB，开始前至少 25 GiB 可用空间，录制中保留至少 20 GiB；
- 60 秒分段，优先向 FFmpeg 发送 `q` 并等待 15 秒封装。

正式 recorder 只执行预检时解析并完成 SHA-256 的同一个 FFmpeg 绝对路径；实际
命令固定 `shell=False`，binary hash 和 command contract hash 都进入授权账本与
最终收据。Dry run 与 development capture 的 FFmpeg binary hash 必须相同；软件
更新后需要重新 dry run。

`hardware_fingerprint_sha256` 必须由授权内的完整私有硬件/驱动清单确定性计算；
采集卡友好名本身不能作为硬件身份。该字段可以在最初 dry-run 计划中保持 null 以
收集诊断，但 null 收据不能被签收，也不能解锁 development capture。

正式 `record` 在消费 nonce 和启动 FFmpeg 前运行固定、只读的 Windows CIM/PnP
查询，要求恰好一个 `Name=UGREEN 25854 + Service=usbvideo + MI_00` 视频接口，
并记录完整 device instance、USB VID/PID、PnP instance suffix、驱动和状态；同一个
已哈希 FFmpeg 还会只读枚举 DirectShow alternative device name，并要求规范化后的
完整 PnP interface identity 与 CIM 完全相同。录制命令使用这个唯一 alternative
name，不按可能重名的友好名打开。非空 manifest 必须与这些观测字段逐项一致；
development 还要求本次 PnP/DirectShow observation hash 与已签收 dry run 相同。
手机型号、AA app 版本、
方向、视频适配器、色彩、normalization 和 layout 无法由 PnP 自动证明，继续由
私有清单和人工签收约束。

2026-09-14 首次只读实机预检确认，这块 UGREEN 是正常的复合 USB 设备：同名接口
包含 `MI_00/usbvideo` 和 `MI_02/usbaudio`。正式探针只选择 `Service=usbvideo`、
`interface_number=00` 的唯一视频接口，音频兄弟接口不参与 fingerprint 或 Popen；
驱动、完整 PnP interface identity 和 DirectShow alternative 必须逐项一致。PnP ID
尾段记录为 `pnp_instance_suffix`，不能冒充已经验证的物理 serial；未从可信 USB
属性获得 serial 时，`capture_card_serial` 保持 null。该次预检还确认实际 FFmpeg
binary 能绕过 WinGet symlink 正确解析和哈希，G 盘空间满足门槛；没有打开视频流或
写入录像。

只有成功 dry run 的最终收据经人工签收，后续 `development_capture` 授权才会被
接受。签收前会从私有分段和 metadata 重新生成最终收据并要求逐字段一致；dry run
必须有非空硬件 fingerprint。开发授权同时绑定 dry-run authorization、plan、
finalization 和人工 signoff 四个文件的 SHA，并要求同一硬件 fingerprint、不同
session 和不同 recording group。
开发采集每次 60–1800 秒，仍是一 session 一授权。

仓库只提供不可执行模板：

`configs/reproduction/aa_passive_capture_authorization_v1.NOT-DATA.json`

模板含 `REPLACE_ME`、空时间和未授权状态，直接传给 CLI 必然失败。真实授权文件
和计划、dry-run signoff 只能是 `G:/PokerSense_private` 的直属 JSON 文件；最终
收据只能位于对应 `aa-live-*` session 目录。它们不能写入仓库或其他目录。

## 操作流程

以下命令只说明未来硬件演练步骤；本轮工程实现没有执行它们。

1. 用户针对一个 dry-run session 明确授权后，在私有目录复制模板并填写唯一 ID、
   nonce、UTC 授权窗口、session、规则声明和身份状态。
2. 外部计算授权文件 SHA，并创建只读计划：

```powershell
$authHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $auth).Hash.ToLowerInvariant()
python -m tools.aa_passive_capture_intake_v1 plan `
  --authorization $auth `
  --authorization-sha256 $authHash `
  --output $plan
```

3. 再核对计划 SHA。只有本次真实采集授权仍有效时才执行：

```powershell
$planHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $plan).Hash.ToLowerInvariant()
python -m tools.aa_passive_capture_intake_v1 record `
  --plan $plan `
  --plan-sha256 $planHash `
  --authorization $auth `
  --authorization-sha256 $authHash
```

CLI 没有 device、root、codec、source 或 extra-args 开关。可在录制目录创建 `STOP`
文件或按 Ctrl+C；正式 recorder 都会向同一 FFmpeg 进程发送 `q` 并等待封装。强杀、
非零退出、掉帧、重复帧、缺失 progress end、分段缺失/多余/乱序、CSV gap/overlap
、FFmpeg frame 数与 30 FPS 时间线偏差超过 10%，或超出授权时长都会进入
`FAILED_QUARANTINED`，不得删除或自动重录。

4. 成功结束后，工具只对刚生成的新 session 读取并 SHA-256 哈希 segment bytes、
   授权账本和固定 FFmpeg binary/contract，不解码、不截图、不识别。结果写入不可覆盖的
   `capture-finalization-receipt.json`。
5. 人工核对画面来源、信号和隐私后，记录 dry-run 签收：

```powershell
$receiptHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $receipt).Hash.ToLowerInvariant()
python -m tools.aa_passive_capture_intake_v1 signoff-dry-run `
  --receipt $receipt `
  --receipt-sha256 $receiptHash `
  --plan $plan `
  --plan-sha256 $planHash `
  --reviewer <reviewer-id> `
  --signed-at-utc <RFC3339-UTC> `
  --output $signoff
```

开发 session 的新授权必须绑定原 dry-run authorization、plan、finalization 和
signoff 四个文件的真实 SHA。`plan` 与 `record` 都必须同时取得这四个原文件；工具
会从原 dry-run session 重新哈希分段和 metadata，不能只凭手写的自洽收据解锁。
对应参数为：

```text
--prior-hardware-receipt / --prior-hardware-receipt-sha256
--prior-dry-run-finalization / --prior-dry-run-finalization-sha256
--prior-dry-run-plan / --prior-dry-run-plan-sha256
--prior-dry-run-authorization / --prior-dry-run-authorization-sha256
```

`inspect` 也必须同时传入原 plan 及其外部 SHA；它会重新读取授权账本、四个 metadata
文件、全部 segment 和 FFmpeg binary，并要求当前重算收据与保存收据逐字段一致，
不是只看 JSON 外形。

## 入库状态

即使录制和哈希全部成功，V1 的最高自动状态也只是
`CAPTURE_FINALIZED_UNREVIEWED`。每个新 session 固定进入
`UNASSIGNED_QUARANTINE`，并保持：

```text
platform_verified=false
rule_fingerprint=null
identity_status=UNKNOWN
legal_menu_count=0
all_opportunities_reviewed=false
special_modes=UNKNOWN
data_readiness=BLOCKED
ready_for_offline_review=false
ready_for_calibration=false
model_fit_executed=false
strategy_eligible=false
advice_emitted=false
live_control=false
human_signoff_required=true
```

每个规则字段分别使用 `UNKNOWN` 或 `OPERATOR_DECLARED`：UNKNOWN 必须 value=null
且没有证据哈希；OPERATOR_DECLARED 必须有值。金额只能是精确十进制字符串，
Intake V1 不接受 verified 状态、作者/独立复审或 rule fingerprint 自报。玩家身份
只允许 session pseudonym；昵称、头像、账号、聊天、房间标识和 pseudonym secret
均禁止进入 metadata。稳定身份只有在私有 mapping hash 存在时才能声明，仍继续
保留独立复审 blocker。规则或身份未知不会阻止保存一次合法新录制，但会阻止离线
校准。

## 后续验收

`capture-finalization-receipt.json` 只证明新分段 bytes 在停止后完成了稳定哈希，
不证明完整解码、真实 AA 来源、规则、身份、完整手或完整决策机会。用户另行授权后，
只对这个新 session 运行严格解码审计和人工时间线复核。通过隐私、来源、完整解码、
手边界、规则 epoch、匿名身份和完整机会审查后，才能进入离线 evidence review。

至少两个真正独立且同规则的 session、session-disjoint split、完整 predecision
状态和合法菜单、作者与独立复审全部齐备后，才允许另建校准候选。Intake V1 永远
不能授予策略或实战 Advice 权限。
