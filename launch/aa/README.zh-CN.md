# AA 离线工程预览入口

双击 `START-AA.cmd`。源码 checkout 优先使用本项目 `.venv`，不会误启动当前目录
或 `dist/PokerSense-AA/` 的旧 EXE；无源码时才按这两个位置选择便携 EXE。
源码支持 Python 3.11–3.13，只有 3.12 也可启动：无 `.venv` 时使用 `py -3`
或 PATH 中的 `python`，默认版本不受支持时再查找 3.12、3.13、3.11。
控制台显示实际解释器和源码／EXE 路径；已有 `.venv` 不完整或版本不受支持时
明确报错，不静默换环境。缺少桌面依赖时显示该解释器的安装命令，不自动安装。
Windows 源码环境的最简准备（在仓库根目录执行）：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[desktop]"
launch\aa\START-AA.cmd --self-check
```

打开的是 AA 本地页面，默认不启用采集、不打开私有模型、不启动观察会话。
控制台显示准确版本与实际地址；关闭控制台结束该入口。

配置与分析记录保存在 `%LOCALAPPDATA%/PokerSense-AA/<版本>/`，不写安装目录。
`--state <路径>` 可另指定目录；已有内容不被入口覆盖。端口占用时自动选择空闲
回环端口，不停止其他程序。`--self-check` 只检查公开资源，不创建目录。

缺少私有识别资源是公开离线包的预期状态，不代表识别模型或真实策略已验收。
运行 `--version` 或访问页面所在地址的 `/api/build` 可核对版本及入口。
详细打包与验收说明见 `docs/AA-PACKAGING-V1.zh-CN.md`。
