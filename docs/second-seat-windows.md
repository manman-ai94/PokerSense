# 第二台电脑（Windows）从源码安装

给杜那台 Windows 电脑的 AI 助手看：照顺序执行命令，每步后面写了“看到什么就对了”。
不用安装包；求解器在这台电脑上自己编译（4b 步），和主人 Mac 上的是同一版。
软件只显示建议，**绝不**替人点击或下注；人始终是唯一操作者。

助手的规矩：

- 只从 GitHub **拉**代码，不提交、不推送、不改仓库里的任何文件。
- 主人说“更新”时才更新（第 7 步）；平时不要自己 `git pull`。
- 出问题停下来，把报错原文发给主人，不要自己改代码或配置。
- 识别资源包和录像是私有数据：不上传到任何公开地方，不放进仓库文件夹。

所有命令在 **PowerShell** 里执行，最好用普通（非管理员）窗口。这台电脑只有管理员账户、窗口本身就是管理员身份时也可以装，
但一律按“用户级”装：装在 `C:\PokerSense`、`C:\PokerSense_data` 和用户自己的文件夹，环境变量用 `setx`（只改当前用户），
以后打开、更新都用同一个账户。

这台电脑以前装过安装包版的“PokerSense AA”（`%LOCALAPPDATA%\Programs\PokerSense AA`）时，先看文末“旧的安装包版”把它卸掉。

## 1. 装 Python 3.12、Git、uv

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
winget install -e --id astral-sh.uv
```

关掉 PowerShell 再开一个新的（让新装的命令生效），然后：

```powershell
py -3.12 --version; git --version; uv --version
```

这里看到三行版本号（`Python 3.12.x`、`git version ...`、`uv ...`）就对了。

**没有 `winget` 时**（提示“无法识别 winget”）：从官网下载安装包，用默认选项装，装完同样关掉 PowerShell 再开新的：

- Python 3.12（选 “Windows installer (64-bit)”）：<https://www.python.org/downloads/windows/>
- Git（选 64-bit “Git for Windows Setup”）：<https://git-scm.com/downloads/win>
- uv（官方说明里的 “Standalone installer” 那条 PowerShell 命令，或 GitHub 发布页的 `uv-x86_64-pc-windows-msvc.zip`
  解开后把 `uv.exe` 放进 PATH 里的文件夹）：<https://docs.astral.sh/uv/getting-started/installation/>

## 2. 克隆仓库、装依赖

仓库是公开的，克隆不需要 GitHub 账号。放在没有中文、没有空格的路径：

```powershell
git clone https://github.com/manman-ai94/PokerSense.git C:\PokerSense
cd C:\PokerSense
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev,desktop]"
```

`desktop` 里已经包含建议要用的计算库；求解器在 4b 步单独装。

如果以后仓库改成私有：主人在 GitHub 仓库 Settings → Collaborators 把杜的 GitHub 账号加成协作者（只读 Read），
克隆时用杜的账号登录。现在不需要。

## 3. 设数据文件夹

杜的电脑没有 `G:` 盘，录像、本桌设置和识别资源都放在 `C:\PokerSense_data`：

```powershell
setx POKERSENSE_DATA_ROOT "C:\PokerSense_data"
$env:POKERSENSE_DATA_ROOT = "C:\PokerSense_data"
New-Item -ItemType Directory -Force C:\PokerSense_data | Out-Null
```

这个盘至少要留 20 GB 空闲，不够时“录像”不会开始。

## 4. 装识别资源包（没有它窗口认不出牌）

识别资源包不在 GitHub 上，由主人从 Mac 打包后私下发来（一个文件夹，里面有
`PokerSense-AA-recognition.zip`、`PokerSense-AA-recognition.json`，通常还有 `aa_mushroom_bank.npz`）。
把这个文件夹整个放到 `C:\PokerSense_data\recognition-pack\`，然后：

```powershell
cd C:\PokerSense
$env:PYTHONPATH = "src;."
.venv\Scripts\python.exe tools\pack_aa_recognition.py --install C:\PokerSense_data\recognition-pack\PokerSense-AA-recognition.zip
```

这里看到最后一行“[识别资源] 装好了”就对了。它会核对压缩包和每个文件，再装进
`C:\PokerSense_data\aa-live-state\recognition\`；蘑菇池的数字样本装到
`C:\PokerSense_data\PokerSense_private\aa_mushroom_bank_v1\bank.npz`。
主人发来新的资源包时，重复这一步。

## 4b. 装求解器（单挑转牌、河牌的建议）

TexasSolver 是第三方开源程序（AGPL），作者只允许分享链接、不允许转发程序本身，所以在这台电脑上
从源码编译，版本和主人 Mac 上的一样。官方 v0.2.0 的 Windows 安装包**不能用**：它不认 PokerSense
发给它的单张组合范围。先装编译工具（MSYS2，约 1–2 GB，只装一次）：

```powershell
winget install -e --id MSYS2.MSYS2
C:\msys64\usr\bin\bash.exe -lc "pacman -S --noconfirm --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-libgomp mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja"
```

`libgomp` 不能少：GCC 16 起 MSYS2 把 OpenMP 拆成了单独的包，不装的话编译停在 `Could NOT find OpenMP_C`。
（这个包列表也写在 `tools/setup_texassolver.py` 的 `MSYS2_PACKAGES` 里，两边一致。）

**没有 `winget` 时**：从 <https://www.msys2.org/> 下载安装程序装到 `C:\msys64`。
**安装程序最后一步报错、整个装了又撤回时**（自检 `bash.exe --login -c exit` 报 pipe 错一类），改用官方的自解压包，不用安装程序：
从 <https://repo.msys2.org/distrib/> 下载 `msys2-x86_64-latest.sfx.exe`，然后

```powershell
& "$env:USERPROFILE\Downloads\msys2-x86_64-latest.sfx.exe" -y -oC:\
C:\msys64\usr\bin\bash.exe -lc " "
```

第二行是第一次启动（建好用户目录和签名钥匙），之后照常跑上面的 `pacman` 那一行。

`pacman` 卡在核对签名（`checking keys` / `gpg` 很久不动）时：**不要**随手关掉签名检查。先等它做完第一次启动；
确实卡了二十分钟以上，才可以临时把 `C:\msys64\etc\pacman.conf` 里 `[options]` 下的 `SigLevel` 从 `Required` 改成 `Never`
装完工具，**装完马上改回**（关着签名检查时，下载的包没人核对真假，这是拿安全换时间）：

```powershell
(Get-Content C:\msys64\etc\pacman.conf) -replace '^SigLevel\s*=\s*Never', 'SigLevel    = Required' |
  Set-Content -Encoding ascii C:\msys64\etc\pacman.conf
Select-String '^SigLevel' C:\msys64\etc\pacman.conf
```

最后一行显示 `SigLevel    = Required` 就对了。以后再用 `pacman` 装东西前，先跑一次
`C:\msys64\usr\bin\bash.exe -lc "pacman-key --init && pacman-key --populate msys2"`。

然后编译（十分钟左右，会从 GitHub 下载 TexasSolver 的源码）：

```powershell
cd C:\PokerSense
$env:PYTHONPATH = "src;."
.venv\Scripts\python.exe tools\setup_texassolver.py
```

这里看到最后一行“[求解器] 试算通过”就对了。求解器装在
`C:\PokerSense_data\third_party\TexasSolver-console\install\console_solver.exe`，窗口自己会找到，不用设别的。
编译好的程序和源码都不要发给别人、不要放进仓库文件夹。没装成功时窗口照常能用：单挑转牌、河牌改用范围规则给建议。

## 5. 接采集卡

1. 线路：华为 P30 → USB-C 转 HDMI 转接头（带充电口，插上充电器）→ HDMI 线 → 采集卡 → 电脑 USB 口。
2. 手机上弹出投屏方式时选 **“手机模式”**（屏幕镜像），不要选“电脑模式”。手机竖着放。
3. Windows 设置 → 隐私和安全性 → 摄像头：打开“摄像头访问”和“允许桌面应用访问你的摄像头”（采集卡算摄像头）。
4. 关掉其他会占用摄像头的程序（相机、微信视频、OBS）。

**窗口提示“采集卡两秒内未提供新帧”、或一直等不到画面时**（杜的电脑 2026-10-14 现场查过）：

1. 头号原因是别的程序占着采集卡：这次是 AMCap（采集卡测试软件），另外常见的有相机应用、OBS、微信视频。
   程序能“打开”采集卡却读不到一帧，就是这个提示。把这些程序关掉（只关进程，不用卸载），用 PokerSense 时也别同时开。
2. 设备编号：杜的电脑上 `0` 是电脑自带摄像头，`1` 是采集卡。采集卡在设备列表里叫 `Display capture-UVC05`
   （`VID_1DE1&PID_F115`，免驱芯片），不叫 UGREEN。窗口里填 1 能省一轮查找；不填也行，程序自己会找。
   采集接口用默认的 MSMF（DSHOW 也行）。
3. 采集卡每次被打开后约 5 秒才锁定手机信号，之前画面是它自己的 “No Signal” 占位图，属正常。点“开始”后等 5–10 秒。
4. 还是没画面：点“停止”再点“开始”，重试一两次（每次打开都会让采集卡重新锁信号，第二次通常直接就有手机画面）。

## 6. 打开窗口

先在桌面放一个快捷方式“PokerSense”：

```powershell
$link = (New-Object -ComObject WScript.Shell).CreateShortcut(
  [Environment]::GetFolderPath("Desktop") + "\PokerSense.lnk")
$link.TargetPath = "C:\PokerSense\launch\aa\START-AA.cmd"
$link.WorkingDirectory = "C:\PokerSense"
$link.Save()
```

建快捷方式报错（例如安全策略不许用 `WScript.Shell`）时，改在桌面放一个 `PokerSense.cmd`，双击效果一样：

```powershell
Set-Content -Encoding ascii ([Environment]::GetFolderPath("Desktop") + "\PokerSense.cmd") `
  '@call "C:\PokerSense\launch\aa\START-AA.cmd" %*'
```

双击桌面上的“PokerSense”（就是 `C:\PokerSense\launch\aa\START-AA.cmd`）。

- 黑色窗口里看到 `PokerSense AA 已打开` 就对了；浏览器（Edge 或 Chrome）自动打开“信号灯”窗口。
  黑色窗口不要关，关了程序就退出了。
- 窗口里画面来源选“采集卡”，点“开始”。设备编号不用管：程序会自己找“两边黑、中间是手机”的那个设备。
- 看到手机牌桌的画面、座位开始有数字，就对了。
- 窗口认出牌桌 15 秒内，“录像”按钮才能点。点“录像”开始录，按钮变红。
- 打完点“停止”，等窗口上出现“已存好 · N 分钟”再关窗口。录像满 2 小时会自动停并存好。

录像存在 `C:\PokerSense_data\PokerSense_private\aa-mac-recordings\<日期-时间>-live\`，每次一个文件夹。
设好“录像回传”（见下面）以后，一停录它就在后台自己传给主人（先传录像，体检单写完再补）；没设好之前，把整个文件夹压缩后用微信或网盘发给主人。

检查用（不开窗口）：

```powershell
C:\PokerSense\launch\aa\START-AA.cmd --self-check
```

输出里 `"capture_enabled": true`、`"recognition_bundle": "INSTALLED"`、`"solver_ready": true`、
`"recorder_ready": true` 都有就对了。它会真算一个很小的河牌局面、写几帧录像再读回来（在临时文件夹里，
算完就删），所以要等十来秒。`"recorder"` 里的 `"fourcc"` 是录像用的编码，`"backend"` 应该是 `FFMPEG`：
Windows 上通常是 `mp4v`（一小时约 0.5–1 GB），主人那边照样能读。

输出里有 `openh264-2.5.0-win64.dll` 找不到之类的告警、但 `recorder_ready` 是 true，不用管，也不要去网上找这个 dll：
OpenCV 先试 OpenH264 这个库，没有就用 `mp4v`。**不用** Windows 自带的 H.264 编码器（`MSMF`）：它固定每秒约 60 Mbit，
一小时 26 GB（2026-10-15 杜的 18 分钟录了 7.95 GB）。
第一段录像录完，双击录像文件夹里的 `segment_0000.mp4` 看一眼能不能放，能放就照常录。

## 7. 更新（只在主人说要更新时）

```powershell
cd C:\PokerSense
git pull --ff-only
uv pip install --python .venv\Scripts\python.exe -e ".[dev,desktop]"
```

`git pull` 报错（例如本地有改动）就停下来，把报错发给主人，不要强行覆盖。
只有一种报错可以自己处理：当初在管理员窗口里克隆、现在用普通窗口更新时，git 会说 `dubious ownership`（文件夹属于别的账户），
照它提示跑 `git config --global --add safe.directory C:/PokerSense` 再 `git pull --ff-only`。

## 第一次：先录 10 分钟验收

装好后先录一段 10 分钟的验收录像，主人确认读得准了才算正式上桌：

1. 接好采集卡，打开窗口点“开始”，看到牌桌后点“录像”。
2. 10 分钟里**至少一部分时间要坐下打**（照常打或一直弃牌都行，不用管建议）。只观战看不到自己的手牌和“跟注/让牌”按钮，
   这两项量不出来，验收就过不了。
3. 点“停止”，等“已存好”。设好了“录像回传”就会自己传给主人；没设好就把 `C:\PokerSense_data\PokerSense_private\aa-mac-recordings\` 里这次的整个文件夹压缩发给主人。

主人那边在这段录像上跑 `tools/p30_acceptance.py`（华为 P30 的画面和主人的三星不一样，要先确认画面位置、各项识别率够不够），
过线了才正式上桌；不过线会出一份识别任务单。

## 录像回传（一次性设置，要主人登录一次 Google）

**这一步不挡第一段录像**：没设好之前照常录，录完把录像文件夹压缩后用微信或网盘私下发给主人就行。

一停录，窗口就在后台用 rclone 把整个录像文件夹传到主人 Google Drive 的
`PokerSense 同事数据/du/<录像文件夹名>/`（先传录像，体检单写完再补传它的几个小文件）：低优先级、限速 1 MB/s，传不上就留着下次再传，不影响录像和建议。
登录信息只在这台电脑的 rclone 配置里，不在仓库、不在软件里。不要改这台电脑的任何网络设置（Wi-Fi、防火墙、代理、DNS）。

1. 装 rclone，然后**关掉 PowerShell 再开一个新的**（让新命令生效）：

   ```powershell
   winget install --id Rclone.Rclone -e --accept-source-agreements --accept-package-agreements
   ```

   没有 `winget` 时：从 <https://rclone.org/downloads/> 下载 Windows 64 位 zip，把里面的 `rclone.exe` 放到 `C:\rclone\`，
   再把这个文件夹加进当前用户的 PATH（只改当前用户，不碰系统设置）：

   ```powershell
   [Environment]::SetEnvironmentVariable("Path",
     [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\rclone", "User")
   ```

   新窗口里 `rclone version` 有版本号就对了。

2. 登录（**主人本人操作**：浏览器弹出 Google 登录时，主人登录他自己的账号并点“允许”；完成后在这个浏览器里退出主人的账号）：

   ```powershell
   rclone config create pokersense-upload drive scope=drive.file
   ```

   **主人不在这台电脑旁边时**（远程授权，主人在自己的 Mac 上登录）：杜的助手改跑

   ```powershell
   rclone config create pokersense-upload drive scope=drive.file config_is_local=false
   ```

   它会打印 `Execute the following on the machine with the web browser`，下面一行是
   `rclone authorize "drive" "<一串字母>"`，然后停在 `config_token>` 等输入。把**这一整行 `rclone authorize` 命令原样**
   （两段引号都要：第二段是编码后的 `scope=drive.file`，少了它主人授权的就是整个云盘）私聊发给主人。主人在 Mac 的“终端”里跑这行
   （Mac 没有 rclone 时先 `brew install rclone`），浏览器弹出 Google 登录，登录主人自己的账号、点“允许”；终端里
   `Paste the following into your remote machine --->` 和 `<---End paste` 之间那一行就是令牌。
   主人把令牌私聊发回，杜的助手粘到 `config_token>` 后面回车；后面再问到的（例如 `Shared Drive`）直接回车用默认值。

   **令牌就是钥匙**：拿到它的人能往主人云盘里传文件、改删这台电脑传上去的文件。只走私聊，不发群、不截图、不写进任何文件或仓库；
   粘贴成功后，主人和杜都把那条聊天消息删掉。

   看到 `[pokersense-upload]` 和 `type = drive` 就对了。`drive.file` 表示这台电脑只能碰它自己传上去的文件，碰不到主人云盘里别的东西。
   不要在 Google Drive 网页上自己建“PokerSense 同事数据”文件夹：第一次上传时会自动建好，手建的那个它看不见。

3. 给这台电脑起名字（云盘里的文件夹名），然后检查：

   ```powershell
   cd C:\PokerSense
   $env:PYTHONPATH = "src;."
   .venv\Scripts\python.exe tools\flywheel_sync.py setup --machine du
   ```

   输出里 `"configured": true`、`"enabled": true`、`"machine": "du"` 都有就对了。
   `setup` 会把它找到的 `rclone.exe` 的完整位置记下来，所以先开着的窗口也能找到 rclone，不用重开。
   窗口里“设置和数据” → “设置与分析”有“录像自动上传”一栏，平时什么都不用管；没设好时那里写“未配置上传”。

4. 想马上传已经录好的（例如第一段验收录像），窗口不用开：

   ```powershell
   .venv\Scripts\python.exe tools\flywheel_sync.py push
   ```

   最后写“都传好了。”就对了；写“没传完”就把这几行发给主人。

设好后告诉主人一声“上传设好了”就行，不用发别的东西（不要发任何登录信息）。

## 主人那边（在 Mac 上，杜的助手不用做）

打识别资源包（Mac 的仓库要已经更新到包含本说明的 main；不在打牌时跑也行，几分钟）：

```bash
cd ~/Projects/PokerSense && PYTHONPATH=src:. .venv/bin/python tools/pack_aa_recognition.py \
  --profile configs/reproduction/aa8_candidate_v2/factory.json \
  --out ~/Desktop/aa-recognition-$(date +%Y%m%d)
```

桌面上的 `aa-recognition-日期` 文件夹里有 zip、json 和蘑菇池数字样本，整个文件夹私下发给杜（微信文件、网盘私有链接），
让他的助手放到 `C:\PokerSense_data\recognition-pack\` 再做第 4 步。里面是真实牌桌截图，只发给同意参加测试的人，不要公开分享、不要提交进仓库。

杜的录像拉回 Mac（Google Drive 桌面版同步好“PokerSense 同事数据”以后；拉到 `aa-mac-recordings/du-<录像文件夹名>/`，
只拉传完整的，账本按机器记，可以重复跑）：

```bash
cd ~/Projects/PokerSense && PYTHONPATH=src:. .venv/bin/python tools/flywheel_sync.py pull
```

验收录像拉回后（手动发来的就解压到 Mac 的数据目录里），一条命令出结论（工具和过线标准见 `tools/p30_acceptance.py`）：

```bash
cd ~/Projects/PokerSense && PYTHONPATH=src:. .venv/bin/python tools/p30_acceptance.py run \
  --video <杜的录像文件夹> --out <新的结果文件夹>
```

## 旧的安装包版（装过才看）

`%LOCALAPPDATA%\Programs\PokerSense AA` 是以前试过的安装包版（发版流程见 `docs/windows-distribution.md`，
内置 Python 3.11，`FileDescription` 写的是 “offline engineering preview”）。它和这份从源码装的版本没有关系，但会添乱：
它也用 8771 端口，两个同时开时后开的那个打不开；桌面上的“PokerSense AA”快捷方式和新的“PokerSense”容易点错；
它每次启动还会去查自己的更新。它不开机自启、不常驻后台，装源码版不用它。卸掉：

```powershell
& "$env:LOCALAPPDATA\Programs\PokerSense AA\unins000.exe" /SILENT
```

（或者 Windows 设置 → 应用 → 已安装的应用 → “PokerSense AA” → 卸载。）它的数据在 `%LOCALAPPDATA%\PokerSense-AA\`，
卸载不会删。先看里面有没有录像：

```powershell
Get-ChildItem -Recurse -Filter *.mp4 "$env:LOCALAPPDATA\PokerSense-AA" | Measure-Object | Select-Object Count
```

`Count` 是 0 就把 `%LOCALAPPDATA%\PokerSense-AA` 整个删掉；不是 0 就先问主人。

## 哪里不对找谁

找主人。不要自己改代码、配置或数据文件夹里的东西。发给主人时带上：黑色窗口里的最后几行字、
`--self-check` 的输出、出问题的大概时间。

## 给杜本人（三句话）

1. 双击桌面上的“PokerSense”，浏览器会打开“信号灯”窗口，黑色窗口别关。
2. 来源选“采集卡”，点“开始”，看到牌桌后点“录像”。
3. 打完点“停止”，等窗口上写“已存好”再关。
