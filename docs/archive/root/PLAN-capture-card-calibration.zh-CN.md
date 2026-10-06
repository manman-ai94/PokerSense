# 采集卡视觉标定：开发 + 工作计划

> 执行目标：把 `docs/capture-card-calibration-guide.zh-CN.md`（阶段 A→L）全部做完，
> 并把视觉识别部分完整落地到 PokerSense。
> **ADB / LDPlayer 路径彻底弃用**，唯一生产输入是「手机 → 视频输出适配器 → USB 采集卡 → PC」。
>
> 铁律（来自任务书 §2，逐条不改）：
> 1. 全新平台 `platform_id = wepoker_android_capture_card`，**不继承** LDPlayer/H5 的 ROI/坐标/阈值/样本/置信度。
> 2. 可复用平台无关识别算法；牌面素材独立验证通过才复用模板；几何、阈值证据一律重新生成。
> 3. 正样本必须来自真实采集卡视频流，禁止用手机截图/微信压缩图/雷电截图代替。
> 4. 原始视频、完整画面、昵称、头像 = 私有标定材料，不进 Git、不进安装包。
> 5. 不可见/遮挡/动画/无法确认 → `UNKNOWN`；证据矛盾 → `CONFLICT`；不得按扑克常识补猜。
> 8. 一切进结果的数据、配置、模板、报告都记 SHA-256。
> 16. 任一关键字段/映射/来源/验证证据缺失 → 必须写 `PARTIAL` 或 `BLOCKED`，不得宣称完整通过。

---

## 阶段路线总览（依赖从上到下）

```text
[前置] 环境与身份基准
   │
[阶段0] 冻结基线：确认全量测试在干净环境下跑通
   │
[阶段A] 冻结硬件环境 ──────────┐（真机 · 你来）
   │                          │
[阶段B] 录制 3 个会话 45–90 分钟｜（真机 · 你来）
   │                          │
   ▼                          ▼
[阶段C] 画面归一化 ◄────────────┘ 产出 real 视频流 → 归一化画面
   │
[阶段D] 抽帧 · 去重 · 命名 ── 需要 sampler 脚本（我来建）
   │
[阶段E] 座位编号 + ROI 测量 ── 需要 ROI 标注辅助（我来建 + 你复用）
   │
[阶段F] 逐帧真值标签 ── 需要标签工作流（我来建 + 你确认到像素）
   │
[阶段G] 最低覆盖检查 ── 已有 coverage.py
   │
[阶段H] 手牌/会话隔离划分 ── 已有 splits.py
   │
[阶段I] 模板 · 阈值 · 置信度 ── 需要模板提取/校准脚本（我来建）
   │
[阶段J] 座位映射 + 状态一致性 ── 已有 geometry 支持 + 需映射脚本
   │
[阶段K] Replay + 性能证据 ── 需要 replay 建模（我来建）+ 性能实测（真机）
   │
[阶段L] 落地仓库 + 接入 live.py ── 替换 ADB（我来建）
```

---

## 前置：建立可信基准

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **P1** | 改 git 身份为你的真实身份（当前仍是 `windgeek <610516499@163.com>`） | 我 | `git config user.name` 显示你本人 |
| **P2** | 在干净 venv 跑全量测试，记录基线通过数 | 我 | 记录该环境下的通过/跳过数 |
| **P3** | 检查 `.gitattributes`（eol=lf）与工作区行尾一致，避免后续 diff 全是行尾噪音 | 我 | `git diff` 干净 |

> ⚠️ 踩坑提醒：本机跑测试必须 `PYTHONPATH=src`；`tests/vision` 个别用例因中文「扑克」路径读不了 cv2 图（本机必挂），属环境受限，用 `cv2.imdecode` 可规避，不在本次范围。

---

## 阶段 A：冻结硬件与采集环境

**目标**：产出 `capture_card_calibration_<date>/source/device_and_capture.json`，记录一切影响像素的硬件/软件/采集参数。

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **A1** | 用 `cli init` 创建私有标定目录骨架 | 我 | 目录 + `source/device_and_capture.json` 模板生成 |
| **A2** | 填充手机型号/Android 版本/屏幕分辨率/系统缩放/字体大小/深色浅色、微扑克版本/语言/方向 | **你**（真机） | JSON 无 `REPLACE_ME` |
| **A3** | 填充视频输出适配器型号/输出分辨率/刷新率 | **你**（真机） | 同上 |
| **A4** | 填充采集卡型号/固件/USB 连接方式 | **你**（真机） | 同上 |
| **A5** | `cli probe --device <idx>` 探测 UVC 实际协商参数（帧大小/fps/fourcc）回填 | 我 + **你**插着卡 | `update_device_manifest` 合并进 JSON |
| **A6** | 确认录制容器/编码器/码率/关键帧间隔、是否旋转/镜像/裁剪/缩放/滤镜全关闭 | **你**（真机/OBS） | JSON 的 `recording` 项如实 |

> 指南：只用采集卡可持续稳定输出的最高原生分辨率、≥30fps；MKV + 高码率 H.264/H.265；禁用 OBS 缩放/锐化/美颜/降噪/色键/动态裁剪/叠加；别把桌面/鼠标/采集软件 UI 录进去；别走微信传原视频。

---

## 阶段 B：录制完整素材

**目标**：3 个互相独立的会话，总时长 45–90 分钟，会话间至少拔插一次采集卡。

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **B1** | `cli record --session-id session_001` 录第一段（断流/黑屏/重连自动记 SignalEvent） | **你**（真机） | `source/raw/session_001.mkv` + probe JSON |
| **B2** | 会话间拔插采集卡一次，验证内容边界稳定 | **你** | 重连后 `layout_id` 边界漂移 ≤2 像素 |
| **B3–B4** | `session_002` / `session_003` 再录两段 | **你** | 3 个会话齐全 |

**必须覆盖**（录不到就列入缺口报告，不伪造）：
- 2 人 / 3–5 人 / 6–8 人桌面与座位占用变化
- Preflop → Flop → Turn → River 全街道
- 发牌、翻牌、弃牌、过牌、跟注、下注、加注、All-in
- Hero 有牌、弃牌、摊牌、结算、下一手发牌
- 每视觉座位出现筹码、Dealer、动作文字
- 玩家加入/离开/空座/暂离/坐下
- 菜单、弹窗、聊天、表情、牌局结束、战绩等遮挡
- 切后台/回前台、断流/重连、黑屏/花屏

---

## 阶段 C：画面归一化

**目标**：产出固定「游戏画布」，把不确定的 UVC 外框裁成稳定牌桌坐标。

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **C1** | 用 `NormalizationConfig` 生成 `normalization/normalization.json`（源尺寸/旋转/镜像/裁剪/输出尺寸，版本化） | 我 | JSON 版本号如 `capture-card-normalization-v1` |
| **C2** | 每会话开头/中间/结尾/重连后抽帧，测量游戏内容边界 | 我（基于 B 的素材）+**你**供料 | 最大漂移 ≤2 像素，否则拆 layout 或判链路不合格 |
| **C3** | 跑归一化生成 `normalized/frames/*.png` + `manifest.json` | 我 | 输出保留未来实时后端真实见到的像素，不做二次增强 |
| **C4** | 确定 `layout_id`（按 §6 规则：phone/…/card/…/uvc_WxH_fps/canvas_WxH/v1 → 小写下划线） | 我 | 命名幂等、可复现 |

> 处理顺序固定：`解码 → 旋转 → 镜像 → 裁剪 → 尺寸/内容边界校验 → PNG`。

---

## 阶段 D：抽帧 · 去重 · 命名

**目标**：稳定帧按 500–1000ms 抽一帧 + 感知去重；关键事件保留「前稳定 → 变化中 → 后稳定」三帧。

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **D1** | 写采样器 `sampler.py`：抽帧 + 感知去重 + 文件名 `{session}__t_{ms}__f_{src}__{sha12}.png` | **我**（新增代码） | 不删关键时序；每事件 ≥3 帧 |
| **D2** | 写 `manifest.json` 生成：每帧记录文件名/SHA-256/源视频ID/时间戳/源帧号/归一化版本/stable/场景类别/hand-group/抽帧原因 | **我**（新增代码） | 字段齐全、可审计 |

---

## 阶段 E：座位编号与 ROI 测量

**目标**：固定 8 个视觉 slot（slot 0 = Hero 底部，slot 4 = 顶部），测所有 ROI 并转归一化坐标。

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **E1** | 写 ROI 标注辅助工具：在归一化画布上框选并导出 `labels/roi_measurements.csv`（字段 `field,slot_id,x0,y0,x1,y1,source_frame,notes`） | **我**（新增代码） | CSV 符合 schema |
| **E2** | 用 `geometry.py` 把像素 ROI 转归一化坐标，产出 `table_map.draft.json` + `board_slot_layout.draft.json` + `dealer_slot_layout.draft.json` + `empty_slot_layout.draft.json` | 我 | 8 个 slot 全列出；可被生产 TableMap 加载 |
| **E3** | 每个 ROI 用 ≥5 个不同时间/人数/街道的稳定帧复核 | **你**（看图确认到像素） | ROI 不随帧移动 |

**必须独立测量**：`hero_cards`、`board_cards`（+5 个公共牌卡槽）、`pot`、`stack[0..7]`、`action[0..7]`、`dealer_search[0..7]`、`empty_slot[0..7]`、`hero_actor`。

> 注意：`action` 是「已完成动作文字」，不是 Hero 底部按钮；Dealer 先出视觉 slot 再映射位置；占用必须有独立证据，不能只靠筹码 OCR 成功与否。

---

## 阶段 F：逐帧人工真值标签

**目标**：`labels/frames.jsonl` 逐行一个帧标签，只能根据该帧实际可见像素填写。

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **F1** | 用 `schema.py` 校验标签模式（VALID/UNKNOWN/CONFLICT；牌 `TS`/花色；街道/动作/占用枚举；scene 枚举） | 我 | 不合规标签被拦截 |
| **F2** | 写辅助标注/审核工作流（复用 `cli check-labels`） | 我 | 无法肉眼确认的只能标 UNKNOWN |
| **F3** | 对关键帧逐帧确认真值（hero_cards/board/street/pot/slots[8]） | **你**（人工确认） | `review.method = manual_source_pixels` |

---

## 阶段 G：最低覆盖检查

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **G1** | `cli coverage`（`coverage.py`）按 §10 表逐字段核对正负样本量，输出精确补录清单 | 我 | 缺哪列哪，不用相邻重复帧凑数 |

> 覆盖硬指标（节选）：Hero 手牌 ≥40 手/≥80 稳定帧；Flop≥20/Turn≥15/River≥15；pot ≥40 数值；每 slot 筹码 ≥12（共≥96）/Dealer ≥6（共≥48）/占用 ≥40 稳定态（≥320 slot 标签）/已完成动作各 ≥10/ALL_IN≥6/Hero 行动 ≥40；至少 3 个独立会话。

---

## 阶段 H：数据划分

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **H1** | `cli splits`（`splits.py`）按 `session_id+hand_id` 隔离划分 train 60%/calibration 20%/validation 20% | 我 | 同手牌/动作前后帧/近重复帧同 split；验证集含真实硬负样本；无泄漏 |

---

## 阶段 I：模板 · 阈值 · 置信度

**目标**：每个字段独立建证据，不允许全局阈值一盖全。

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **I1** | 写模板提取脚本：紧裁剪、隐私安全的牌面/字形/掩码（cards/stacks/actions/dealer/occupancy/actor），不含昵称/头像/完整桌面 | **我**（新增代码） | 模板目录齐全 + SHA-256 |
| **I2** | 训练集上定 ROI/预处理/模板；calibration 集统计各字段正负样本分数分布 | 我 | 为 Hero/Board/Pot/每类 Stack/Dealer/Action/Occupancy/Actor 独立选阈值 |
| **I3** | 冻结代码/配置/模板及其哈希 | 我 | `evidence/field_metrics.json` 每字段记录齐全 |
| **I4** | 锁定 validation 集跑一次生产识别器 | 我 | 零错误 VALID；abstain、漏检完整报告 |
| **I5** | 阈值原则校验：锁定验证集零错误 VALID、正最低分与硬负最高分有可解释间隔、分数重叠时改 ROI/模板/方法而非降阈值、recall 单独报 | 我 | 通过原则校验 |

---

## 阶段 J：座位映射与状态一致性

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **J1** | 建独立的 `seat_mapping.draft.json`（不改现有 LDPlayer 映射） | 我 | 覆盖 2–8 人占座组合、Dealer 在各 slot、Hero=slot 0 |
| **J2** | 校验：无/多 Dealer、占用冲突 → fail closed | 我 | 一致性测试通过 |
| **J3** | stack/action/dealer/occupancy 各自独立几何证据；动作金额在筹码差+底池差一致时才生成事件 | 我 | 缺金额/多玩家同时变/边池解释不了 → 不猜金额 |

---

## 阶段 K：Replay 与性能证据

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **K1** | 写 `replay.py` 建模：引用源视频/原始帧哈希 + normalization/TableMap/field-calibration/seat-mapping 版本哈希 + 识别器版本 + 每帧预期 + 隐私审核 | **我**（新增代码） | `replay/replay.draft.json` 可回放 |
| **K2** | 性能实测：UVC 解码帧率/丢帧率、归一化+识别 p50/p95 延迟、30 分钟连续运行断流/内存/恢复、拔插卡/切后台行为 | **你**（真机）+ 我 | 只如实记录，负责人未批阈值不算通过 |

---

## 阶段 L：落地到仓库 + 接入实时后端

**目标**：把可公开、隐私安全的生产配置落仓库；原始视频/完整帧留在私有目录；**替换 ADB，接入 `CaptureCardBackend`**。

| 动作 | 内容 | 执行 | 验收 |
|---|---|---|---|
| **L1** | 生成生产配置：`configs/platform/wepoker_android_capture_card__<layout_id>.json`、`..._seat_mapping.json`、`configs/vision/wepoker_android_capture_card/calibration.json` + board/dealer/empty/hero_slot_layout + 隐私安全模板 | 我 | 配置齐全 + 可被加载 |
| **L2** | 改 `desktop/live.py`：`build_capture_backend()` 从 `AdbBackend` 改为 `CaptureCardBackend`；`load_calibration` 走采集卡平台；保留旧 ADB 路径为可选/注释 | **我**（新增代码） | 采集卡平台可选；两套并存不冲突 |
| **L3** | 资源加载 + 序列化测试；字段级回归 + 硬负样本测试；归一化/尺寸不匹配/镜像旋转错误/断流/两帧确认测试；2–8 人映射/Dealer 冲突/空座变化测试；动作去重/筹码底池不守恒拒绝事件测试 | 我 | 新增测试全绿 |
| **L4** | 确认 PyInstaller/安装包只含生产配置和隐私安全模板，不含原视频/完整截图/标签工作目录/联系人 | 我 | 打包检查通过 |
| **L5** | 更新 `docs/capture-and-table-mapping.md`、`docs/capture-replay.md`、中英 README、`AGENTS.md` | 我 | 文档与产品一致 |
| **L6** | 跑项目约定 `pytest + flake8 + 差异检查 + 本地打包检查` | 我 | 全绿；同时在 AGENTS.md 写明「配置已准备，实时后端未接入（若尚未接入时）」诚实边界 |

---

## 执行约定

1. **一步一动作**：每次只做一个编号动作，做完验收再进下一步，避免大改引发难定位回归。
2. **两列职责**：
   - 🟢「我」= 我能独立完成的代码/配置/工具活，不依赖真机。
   - 📷「你」= 需要真机/真人操作/肉眼确认才能完成的部分。
3. **诚实状态**：凡未经 A/B 真机证据支撑的字段，一律 `UNKNOWN`；最终报告状态只能是 `PASS / PARTIAL / BLOCKED`。
4. **哈希**：每阶段产物落盘后立即做 SHA-256；私有素材不提交 Git。
5. **每阶段完成即写进度**：更新本计划状态标记，并在 `AGENTS.md` Progress log 追加对应条目。
