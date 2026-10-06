# macOS 启动入口

`start-aa-replay.command`：打开 AA 观察页，并回放一组已恢复的录像帧。
可以在访达里双击运行，也可以在终端里执行。浏览器会自动打开观察页，点“开始观察”就开始回放。

- 私有数据位置默认是 `~/Projects/PokerSense_data`，可以用环境变量 `POKERSENSE_DATA_ROOT` 改成别的目录。
- 默认回放第一手牌的帧（`PokerSense_private/aa8_first_hand_full_v1`）。想换别的帧，把那个文件夹路径作为第一个参数传进去，文件夹里要有 `samples.json`。
- 页面设置保存在 `<数据目录>/aa-live-state`。
- 关闭终端窗口或按 Ctrl-C 就会停止。

识别模型使用的是旧的开发版配置 `configs/reproduction/aa8_candidate_v2/factory.json`，
它写的 Windows 路径会被自动映射到本机的数据目录。这只是回放和开发用，不代表识别或策略已经验收。
