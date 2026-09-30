# AA Windows 工程预览包

版本 `0.2.0.dev1`。本包统一 AA Windows 入口、版本与公开资源交付，默认离线，
不是已验收的实时策略版本。识别模型、真实录像、凭据不进入公开包。
`REAL_HAND_ACCEPTANCE_PENDING`，策略强度 `NOT_ASSESSED`。

## 构建与入口

在项目 Python 环境中运行：

```powershell
python -m PyInstaller packaging/pokersense.spec --distpath dist --workpath build --noconfirm
python packaging/smoke_aa_package.py dist/PokerSense-AA/PokerSense-AA.exe --output dist/aa-package-smoke.json
iscc packaging/pokersense.iss
```

Windows 的标准 `pokersense.spec` 转到 AA spec，生成
`dist/PokerSense-AA/PokerSense-AA.exe`。安装器只读取该目录，生成
`dist/PokerSense-AA-Setup.exe`。可直接复制整个 `PokerSense-AA` 目录作为便携包，
不能只复制 EXE。程序安装与状态写入分开，安装器使用独立 AA Preview 标识，
不覆盖旧通用产品的安装目录。安装／卸载不删除用户状态。

双击 EXE 或 `launch/aa/START-AA.cmd` 会打开 AA 本地浏览器页面；服务绑定
`127.0.0.1`。默认不打开采集设备、不加载识别模型、不启动观察会话。
端口占用时选择另一个空闲回环端口，不终止原有进程。控制台显示准确版本、
实际地址与状态目录，关闭该控制台即可停止该入口。

`--no-browser` 供脚本检查；`--help` 列出参数，`--self-check` 只检查公开资源且
不创建状态目录。源码方式使用 `python packaging/aa_live_entry.py`。
`START-AA.cmd` 在源码 checkout 中优先本项目 `.venv`，其次使用受支持的系统
Python 3.11–3.13；不会先启动旧 EXE。无源码的便携目录才选择同目录或 `dist`
中的 EXE。解释器、实际入口和依赖缺失都会明确显示；准备命令见
[启动说明](../launch/aa/README.zh-CN.md)。
现有 AA 参数（包括外部 profile、bundle 摘要及显式 replay）保留；
`--allow-capture` 必须同时提供 `--profile`，且只解锁页面控制，不自动启动采集。
真实采集和实战仍须明确授权。

## 状态与资源

默认状态目录为 `%LOCALAPPDATA%/PokerSense-AA/0.2.0.dev1/`，可通过 `--state`
选择。该目录保存桌规和分析记录，已有文件不被启动器重建或覆盖。
升级默认创建新版本目录；迁移旧记录须明确选择旧 `--state`，不隐式移动数据。

公开资源包括 AA 页面与两份明确标注的人工假设河牌示例。缺少私有模型时仍可
打开离线页面，`/api/status` 如实报告识别资源未准备好；`/api/build` 报告
`NOT_CONFIGURED_OFFLINE_AVAILABLE`，不能把包能启动等同于识别验收。
缺少公开页面或示例时在服务启动前报错。

版本采用 Python 的 PEP 440 `0.2.0.dev1`，EXE 文本版本相同。
Windows 数值版本为 `0.2.0.1`，安装器显示版本为 `0.2.0-dev1`。
macOS 保留 `pokersense_legacy.spec` 的历史通用壳，CI 产物明确命名
`PokerSense-legacy-macos`；不宣称 AA macOS 采集通过。

## 当前验证与边界

2026-09-27，在 Windows 本机以 PyInstaller 6.22.3 构建实际 EXE。
7 项新增针对测试及 16 项已有 AA／试用入口回归通过；从无源码的临时工作目录运行冻结 EXE，移除 `PYTHONPATH` /
`PYTHONHOME` 后，`--help`、`--version`、`--self-check` 通过。
13 个 AA 页面／资源／接口返回 200，公开人工河牌示例在冻结 spawn 子进程中
计算完成，保持 `strategy_eligible=false`、`advice_emitted=false`。
采集启动请求返回 403。测试只停止自己创建的服务进程。

本轮没有安装 Inno Setup，安装器尚未在本地编译／实际安装；没有触发 GitHub
构建、Tag 或 Release，也没有真实模型、采集设备、视觉或端到端时延验收。
CI 已改为在安装器构建前执行同一离线 EXE smoke 脚本。后续集成实时模块后
须重新构建与运行该脚本，旧 EXE 不能代表新集成源码。
