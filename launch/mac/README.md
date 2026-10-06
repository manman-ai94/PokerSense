# macOS 启动入口

两个脚本都可以在访达里双击运行，也可以在终端里执行。浏览器会自动打开观察页，点“开始观察”即可开始。

| 脚本 | 用途 |
|---|---|
| `start-aa-video.command` | **录像实时回放**：按录像原本的节奏送画面，经过和采集卡完全相同的裁切与识别，模拟实战时采集卡的实时画面。处理跟不上时会跳过旧画面，和真实采集卡一样 |
| `start-aa-replay.command` | 逐帧回放一组已经抽好的录像帧，每一帧都会处理，不按真实速度 |

- 私有数据位置默认是 `~/Projects/PokerSense_data`，可以用环境变量 `POKERSENSE_DATA_ROOT` 改成别的目录。
- `start-aa-video.command` 默认播放 9 月 9 日的 AA 录像，并且**总是跳过 300–820 秒**：
  300–600 秒是从未用过、留作独立验收的保留区间，600–820 秒以前评估时用过。
  要播放别的录像，把视频文件或分段录像文件夹（文件夹里要有 `segments.csv`）作为第一个参数传进去；
  需要跳过的区间用环境变量 `POKERSENSE_SKIP` 指定，例如 `POKERSENSE_SKIP=300-820`。
- `start-aa-replay.command` 默认回放第一手牌的帧（`PokerSense_private/aa8_first_hand_full_v1`）。
  要换别的帧，把那个文件夹路径作为第一个参数传进去，文件夹里要有 `samples.json`。
- 页面设置保存在 `<数据目录>/aa-live-state`。
- 关闭终端窗口或按 Ctrl-C 就会停止。

识别模型使用的是旧的开发版配置 `configs/reproduction/aa8_candidate_v2/factory.json`，
它写的 Windows 路径会被自动映射到本机的数据目录。这只是回放和开发用，不代表识别或策略已经验收。
