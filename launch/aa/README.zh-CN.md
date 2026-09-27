# AA 离线工程预览入口

双击 `START-AA.cmd`，优先运行当前目录或仓库 `dist/PokerSense-AA/` 的
`PokerSense-AA.exe`；源码回退使用仓库 `.venv` 或 Python 3.11。
打开的是 AA 本地页面，默认不启用采集、不打开私有模型、不启动观察会话。
控制台显示准确版本与实际地址；关闭控制台结束该入口。

配置与分析记录保存在 `%LOCALAPPDATA%/PokerSense-AA/<版本>/`，不写安装目录。
`--state <路径>` 可另指定目录；已有内容不被入口覆盖。端口占用时自动选择空闲
回环端口，不停止其他程序。`--self-check` 只检查公开资源，不创建目录。

缺少私有识别资源是公开离线包的预期状态，不代表识别模型或真实策略已验收。
运行 `--version` 或访问页面所在地址的 `/api/build` 可核对版本及入口。
详细打包与验收说明见 `docs/AA-PACKAGING-V1.zh-CN.md`。
