# Windows 安装包与自动更新

给不改代码、只用程序的同事一个 Windows 安装包，并让他跟着我们的更新拿到新版。
仓库保持私有，同事拿不到源码、没有仓库权限，安装包里没有任何能访问仓库的令牌。

## 怎么运作

```
打 tag vX.Y.Z（或手动运行工作流并填版本号），提交必须在 main 上
  → GitHub Actions（Windows 机器）：打包 PyInstaller → 冒烟测试 → Inno Setup 做安装包
    → 在机器上静默安装 → 测“发现新版 → 下载 → 校验 sha256 → 自动安装”整条路
  → 有 RCLONE_CONFIG 时：核对云盘 recognition/ 里的识别资源包 → rclone 把安装包传上去
    → 写版本清单 latest.json（安装包和识别资源包的地址、大小、sha256）传上去
同事的程序：每次启动先读 latest.json → 识别资源包没有或换了新的就下载 → 核对 sha256、解开、校验 → 才启用
  → 有新版程序就在窗口右下角提示 → 点“立即更新”
  → 下载安装包 → 核对大小和 sha256 → 静默安装（等旧程序退出）→ 自动重新打开（重开时再查一次资源包）
```

- 版本清单 `latest.json`：`version`、`installer.url/sha256/bytes`，有识别资源包时还有
  `recognition.url/sha256/bytes/manifest_sha256`（`app_update.py` 的 `SCHEMA`）。
- 程序读清单的地址来自安装目录里的 `update-config.json`（发版时写入），也可以用环境变量
  `POKERSENSE_UPDATE_URL` 或参数 `--update-url` 改；可以是 Google Drive / Dropbox 分享链接（自动换成直链）、
  任意 HTTPS 地址或局域网共享路径（`\\服务器\共享\latest.json`）。
- 安装到 `%LOCALAPPDATA%\Programs\PokerSense AA`，不要管理员；桌面快捷方式、开始菜单“PokerSense AA 检查更新”。
- 用户数据在 `%LOCALAPPDATA%\PokerSense-AA\data`（本桌设置、记录、录像、识别资源包），更新不动它。
- 云盘文件夹 `pokersense:PokerSense-AA`（文件每次覆盖，分享链接不变）：

  ```
  PokerSense-AA/
    latest.json                                 版本清单（CI 写）
    PokerSense-AA-Setup.exe                     最新安装包（CI 传）
    versions/PokerSense-AA-Setup-X.Y.Z.exe      每个版本留一份，方便退回
    recognition/PokerSense-AA-recognition.zip   识别资源包（主人从 Mac 传）
    recognition/PokerSense-AA-recognition.json  它的大小和 sha256
  ```

  先传安装包再传清单，传到一半时程序校验不过就不装。

## Windows 上哪些功能能用

| 功能 | Windows 安装版 | 说明 |
|---|---|---|
| 打开“信号灯”窗口和旧观察页 | 能 | 本地网页，用 Edge/Chrome 打开；CI 实测启动和全部页面 |
| 翻前建议、范围胜率、粗略建议、记分牌计算 | 能 | 纯 Python + phevaluator；CI 在打包后的程序里实测（`--self-test`） |
| 手动录入一手牌分析、复查、学习记录 | 能 | CI 实测打包后的分析进程 |
| 采集卡实时读牌和实时建议 | 能（程序自动下载识别资源包） | 采集卡在 Windows 走 MSMF（项目最早就在 Windows 上做）；识别资源包单独发布，见下文；Windows 实机还没重新验过 |
| 单挑转牌/河牌的求解器建议 | 不能（自动降级） | TexasSolver 只有 macOS 安装脚本；没有求解器时改用范围规则给建议，窗口照常有建议。支持要写 Windows 编译脚本（CMake + MSVC/OpenMP），并把 exe 放进安装包，中等工作量 |
| 窗口里的“录像”按钮 | 不确定 | 用 OpenCV 的 H.264（avc1）编码，Windows 版 OpenCV 常缺 OpenH264；打不开时会报错，不影响读牌。修法是换 mp4v 或带上 openh264.dll，小工作量 |
| 录像回放、开发回放 | 只有命令行 | 要带 `--replay-video` 参数启动，同事一般用不到 |
| 置顶小窗 | 能（Edge/Chrome） | Document Picture-in-Picture，Edge 和 Chrome 都支持；Firefox 不行 |
| 采集卡设备名列表 | 不显示 | 只有 macOS 用 `system_profiler` 列设备名；Windows 照样按编号自动找手机画面 |
| 重复打开时关掉旧窗口 | 不能 | 用 `lsof`（Windows 没有）；第二个窗口自动换一个端口，不冲突 |

没有任何功能用到 ScreenCaptureKit、Vision、AppKit 这类 macOS 专用接口。

## 识别资源包（实时读牌要它）

实时读牌要一份私有识别资源（21 张开发用的牌桌截帧、金额样本库、牌面模型、牌位布局），只在主人的 Mac 上有，
是真实牌桌的截图。它**不进安装包**，单独传到云盘 `recognition/`；发版时工作流核对它（zip 的 sha256、解开后
`aa_bundle.validate_bundle`），把地址、大小、sha256 和可信摘要写进 `latest.json`。

同事的程序每次启动（包括第一次安装后、每次更新后自动重开时）和点“检查更新”时：读 `latest.json` →
数据文件夹里没有资源包、或清单里换了新的 → 下载 → 核对大小和 sha256 → 解到
`%LOCALAPPDATA%\PokerSense-AA\data\recognition\<摘要>\` → 用清单里的摘要校验全部文件 → 才换成当前的那份
（`recognition\current.json`），旧的删掉。任何一步不对都不启用，已有的那份照用；没有就先不能实时读牌，下次启动再试。

### 在 Mac 上打包和上传（照抄运行）

前提：Mac 上的仓库已经更新到包含这个功能的 main，`.venv` 装好了，rclone 的 `pokersense` 已经配好（见下面“一次性配置”）。
打开“终端”，整段复制粘贴（仓库不在 `~/Projects/PokerSense` 就把第一行改成你的位置）：

```bash
cd ~/Projects/PokerSense && \
OUT=~/Desktop/aa-recognition-$(date +%Y%m%d-%H%M) && \
PYTHONPATH=src:. .venv/bin/python tools/pack_aa_recognition.py \
  --profile configs/reproduction/aa8_candidate_v2/factory.json --out "$OUT" && \
rclone copy "$OUT" pokersense:PokerSense-AA/recognition \
  --include "PokerSense-AA-recognition.*" --progress && \
rclone lsl pokersense:PokerSense-AA/recognition
```

最后一行应该列出 `PokerSense-AA-recognition.zip` 和 `PokerSense-AA-recognition.json` 两个文件。
打包会打印 `zip_sha256` 和 `manifest_sha256`，桌面上的 `aa-recognition-日期` 文件夹留着备查，**不要提交进仓库**。

然后发一个新版本（版本号比上一次大），`latest.json` 才会列出这份资源包：

```bash
cd ~/Projects/PokerSense && git fetch origin && \
git tag v0.3.0 origin/main && git push origin v0.3.0
```

（或者在 GitHub 的 Actions → Windows installer → Run workflow，分支选 main，版本填 `0.3.0`。）
发版记录的标题会写“识别资源包：已列入”。以后识别资源改进了，重复上面两步（版本号再加一），同事下次打开程序就自动换上新的。
不想再发资源包时：`rclone delete pokersense:PokerSense-AA/recognition`，再发一版。

## 一次性配置（主人做）

1. 云盘账号：推荐新建一个专门发版用的免费 Google 账号（泄露时只影响这个账号）；也可以用 Dropbox。
2. Mac 上装 rclone 并授权：`brew install rclone`，`rclone config` → `n` 新建 → 名字填 `pokersense`
   → 类型选 `drive`（Google Drive）→ client_id、client_secret 留空 → scope 选 `drive.file`
   （只能碰它自己建的文件）→ 其余回车 → 浏览器里登录第 1 步的账号并允许。
   然后 `rclone mkdir pokersense:PokerSense-AA`。
3. GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret：
   名字 `RCLONE_CONFIG`，值是 `rclone config file` 显示的那个文件里 `[pokersense]` 整段。
4. 照上面“在 Mac 上打包和上传”传识别资源包，再发第一版：Actions → Windows installer → Run workflow → 分支选 main → 版本填 `0.3.0`（或在 main 上打 tag `v0.3.0` 推上去）。
5. 把云盘里 `PokerSense-AA/PokerSense-AA-Setup.exe` 的链接发给同事（工作流已经设成“知道链接的人可以查看”）。

可选的 Actions variables：`POKERSENSE_RELEASE_DIR`（换云盘或文件夹，默认 `pokersense:PokerSense-AA`）、
`POKERSENSE_UPDATE_URL`（自己指定清单地址，例如公司内网 HTTPS）。

没配 `RCLONE_CONFIG` 时，发版只打包和测试，上传步骤自动跳过；安装包在 Actions 的 artifact 里，可以手动下载转发。

## 发新版

在 main 上打 tag `vX.Y.Z` 推上去，或 Actions 里手动运行并填版本号。版本号必须比云盘上的新，
提交必须在 main 上，否则工作流直接失败、不上传。同事下次打开程序就会看到提示。

## 安全和限制

- 分享链接是“知道链接就能下载”：同事（以及他转发给的人）能下载安装包和识别资源包（真实牌桌截图）。
  要更严，可以把安装包只共享给同事的 Google 账号，但那样程序不能自己下载，只能提示他去网页下载。
- 没有代码签名：第一次运行会出现 SmartScreen“Windows 已保护你的电脑”，点“更多信息”→“仍要运行”。
  完整性靠清单里的 sha256；清单本身和安装包放在同一个云盘账号里，账号安全就是发版安全。
- 中国大陆访问 Google Drive / Dropbox 要能翻墙；不方便时把 `POKERSENSE_UPDATE_URL` 指到公司内网的文件共享。

## 能不能被反编译

能。PyInstaller 只是把 Python 字节码（.pyc）打包进 exe，用 pyinstxtractor 一类免费工具就能拆出来；
Python 3.11 的字节码还原成源码不完整，但逻辑能看出来；界面（HTML/JS）和数据（JSON）是明文。
免费的降低风险办法：

1. 换 Nuitka 打包（免费，把 Python 编译成 C 再编译成机器码）最有效；2026-10-12 主人决定暂不换，继续用 PyInstaller。
2. 只打包要用的模块（现在已经排除了 matplotlib、pandas、torch、pytest；`research/` 不在包里）。
3. 识别资源包单独下载，不在安装包里，也不在 Actions 的 artifact 里。
4. 同事签保密协议；代码许可证是 Proprietary。

PyInstaller 6 已经去掉了旧的 `--key` 加密（它本来也很容易绕过）；PyArmor 免费版有限制，商用要付费，不用。

## Actions 免费额度

私有仓库免费账号每月 2000 分钟，Windows 按 2 倍、macOS 按 10 倍算。这个工作流一次约 15–25 分钟（≈ 30–50 分钟额度），
只在改了打包相关文件的 PR、发版和手动运行时跑。现有的 macOS 测试（每个 PR）和 macOS 旧版打包（每次合并）更费额度，值得留意。
