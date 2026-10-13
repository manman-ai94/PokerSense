# Capture Service + Table Mapping

手机连接电脑的 USB 采集卡候选链路必须单独标定，完整执行规范见
[手机采集卡输入完整标定执行规范](capture-card-calibration-guide.zh-CN.md)。即使手机端使用相同牌面素材，采集卡也不得复用雷电模拟器或历史 H5 的 ROI 与置信度证据。

感知层第一块（Task 6）：ADB 帧采集 + 牌桌 ROI 映射。为 Task 7 Vision 提供 `Frame + ROI crops`，不识别任何扑克内容。生产目标是 Windows 雷电模拟器中的 WePoker Android 竖屏版。

## 模块

- `perceptual/capture/`：`Frame`（不可变帧）、`CaptureTarget`、`CaptureService`（抽象）、`AdbBackend`（生产）、`FakeBackend`（CI）。`MssBackend` / `QuartzBackend` 作为通用桌面捕获和历史 H5 兼容实现保留，但不是默认链路。`CaptureCardBackend` 为 USB 采集卡（手机 → UVC → PC）的**实时采集后端**（MSMF/DirectShow + YUY2 + 断流/黑屏检测），配合 `normalization.py` 完成阶段 C 的画面归一化。采集卡平台现状：几何（20 个实测 ROI + hero/board 槽位布局）与座位字段（occupancy 100% 精度、dealer 100%、stack 100% 精度）已标定，**座位映射已落地** `configs/platform/wepoker_android_capture_card__*_seat_mapping.json`（hero=seat 0，升序 slot=行动方向，证据见 AGENTS.md 2026-09-04 条目）；牌面花色已由 gray-fused-mlp-v3 时序融合管线解决（calibration 62/62、锁定 validation 116/116、零假 VALID，`card_fused` 已落地 `calibration.json`），动作徽章识别器已实现（action_reader.py，76/76 零错判）但尚未接入生产 profile。
- `perceptual/vision/`：`ROIKind` / `ROI` / `TableMap`（含 JSON 序列化）+ `roi.py`（确定性裁剪 + layout 校验）。

## Frame 像素不可变（bytes-backed）

`Frame` 构造时把输入图像经 `ndarray.tobytes()` 复制为**独立 bytes 缓冲**，再用 `numpy.frombuffer` 暴露只读视图。因此：
- 修改 source ndarray 不影响 `frame.image`；
- `frame.image[...] = ...` 抛 `ValueError`；
- `frame.image.setflags(write=True)` 也失败（底层是 immutable bytes）。

不是「冻结 caller 的 ndarray 冒充 immutability」，而是真独立、不可恢复写权限的像素缓冲。

## ADB 采集与坐标体系

默认链路只有两层：Android framebuffer 像素 → normalized ROI（0~1）。TableMap 以 `reference_size=[1440,2560]` 为锚；宿主窗口的位置、边框、缩放、DPI、遮挡和最小化均不参与计算。

`AdbBackend` 调用 `adb -s <serial> exec-out screencap -p`，在内存中解码 PNG。ADB 路径来自 `POKERSENSE_ADB_PATH` 或 PATH。`CaptureTarget.window_id` 在该 backend 中承载设备 serial；字段名为兼容既有契约而保留。

只有一个授权设备时 `auto` 可自动选择；多个设备必须显式给出 `--device-serial`。离线、unauthorized、超时、空图或损坏 PNG 都转为可恢复 `CaptureError`。

桌面 backend 仍使用 screen/window/client-area/ROI 四层坐标，并保留既有 DPI 防护，但不再决定产品标定。

## layout compatibility

实际帧宽高比与 `reference_aspect_ratio` 偏差超过 `aspect_tolerance` → `TableMapMismatchError` fail fast，不使用错误 ROI。

## per-seat ROI

`ROIKind.STACK` / `ROIKind.ACTION` 携带 `slot_id`（0..N-1），表示**视觉座位槽**，不解释 player identity，不映射 Frozen `PlayerState`。

## Android 边界

- Android 与 H5 不共用 ROI；算法和牌面模板可以复用，几何与置信度证据必须按平台分开。
- 当前只接受 1440×2560 竖屏宽高比；横屏或不同宽高比 fail fast。
- 当前默认 TableMap 只包含 Hero 手牌 ROI。公共牌、pot、stack、action、dealer/actor 未完成带标签标定，因此保持 `UNKNOWN`。
- ADB 帧只在内存中存在。原始标定数据不进入 GitHub 或安装包。
- `Frame → ROI crops` 纯确定性（`int()` floor 舍入）。

## 禁止

OCR / 牌面识别 / 动作识别 / Solver / LLM / Equity / anti-cheat。
