# 第二台电脑（Windows）从源码安装

给杜那台 Windows 电脑的 AI 助手看：照顺序执行命令，每步后面写了“看到什么就对了”。
没有安装包、没有求解器（窗口自动改用范围规则给建议，这是已有的行为）。
软件只显示建议，**绝不**替人点击或下注；人始终是唯一操作者。

助手的规矩：

- 只从 GitHub **拉**代码，不提交、不推送、不改仓库里的任何文件。
- 主人说“更新”时才更新（第 7 步）；平时不要自己 `git pull`。
- 出问题停下来，把报错原文发给主人，不要自己改代码或配置。
- 识别资源包和录像是私有数据：不上传到任何公开地方，不放进仓库文件夹。

所有命令在 **PowerShell**（不要用管理员身份）里执行。

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

## 2. 克隆仓库、装依赖

仓库是公开的，克隆不需要 GitHub 账号。放在没有中文、没有空格的路径：

```powershell
git clone https://github.com/manman-ai94/PokerSense.git C:\PokerSense
cd C:\PokerSense
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev,desktop]"
```

不装 `solver-tools`，也不装求解器。

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

## 5. 接采集卡

1. 线路：华为 P30 → USB-C 转 HDMI 转接头（带充电口，插上充电器）→ HDMI 线 → 采集卡 → 电脑 USB 口。
2. 手机上弹出投屏方式时选 **“手机模式”**（屏幕镜像），不要选“电脑模式”。手机竖着放。
3. Windows 设置 → 隐私和安全性 → 摄像头：打开“摄像头访问”和“允许桌面应用访问你的摄像头”（采集卡算摄像头）。
4. 关掉其他会占用摄像头的程序（相机、微信视频、OBS）。

## 6. 打开窗口

先在桌面放一个快捷方式“PokerSense”：

```powershell
$link = (New-Object -ComObject WScript.Shell).CreateShortcut(
  [Environment]::GetFolderPath("Desktop") + "\PokerSense.lnk")
$link.TargetPath = "C:\PokerSense\launch\aa\START-AA.cmd"
$link.WorkingDirectory = "C:\PokerSense"
$link.Save()
```

双击桌面上的“PokerSense”（就是 `C:\PokerSense\launch\aa\START-AA.cmd`）。

- 黑色窗口里看到 `PokerSense AA 已打开` 就对了；浏览器（Edge 或 Chrome）自动打开“信号灯”窗口。
  黑色窗口不要关，关了程序就退出了。
- 窗口里画面来源选“采集卡”，点“开始”。设备编号不用管：程序会自己找“两边黑、中间是手机”的那个设备。
- 看到手机牌桌的画面、座位开始有数字，就对了。
- 窗口认出牌桌 15 秒内，“录像”按钮才能点。点“录像”开始录，按钮变红。
- 打完点“停止”，等窗口上出现“已存好 · N 分钟”再关窗口。录像满 2 小时会自动停并存好。

录像存在 `C:\PokerSense_data\PokerSense_private\aa-mac-recordings\<日期-时间>-live\`，每次一个文件夹。
在自动上传做好之前，把整个文件夹压缩后用微信或网盘发给主人。自动上传（主人的私有 Google Drive）另做，见下面“录像回传”。

检查用（不开窗口）：

```powershell
C:\PokerSense\launch\aa\START-AA.cmd --self-check
```

输出里 `"capture_enabled": true` 和 `"recognition_bundle": "INSTALLED"` 都有就对了。

## 7. 更新（只在主人说要更新时）

```powershell
cd C:\PokerSense
git pull --ff-only
uv pip install --python .venv\Scripts\python.exe -e ".[dev,desktop]"
```

`git pull` 报错（例如本地有改动）就停下来，把报错发给主人，不要强行覆盖。

## 第一次：先录 10 分钟验收，不打

装好后先不要上桌打牌：接好采集卡，随便进一桌**观战**，点“录像”录 10 分钟，停止后把录像文件夹发给主人。
主人那边在这段录像上量识别率（华为 P30 的画面和主人的三星不一样，要先确认读得准），过线了才上桌。

## 录像回传

自动上传到主人的私有 Google Drive 是另一项工作（停录后自动传 `<机器名>/<录像文件夹名>/`），
做好后这里会补上一次性的登录步骤。在那之前手动发。

## 主人那边（在 Mac 上，杜的助手不用做）

打识别资源包（Mac 的仓库要已经更新到包含本说明的 main；不在打牌时跑也行，几分钟）：

```bash
cd ~/Projects/PokerSense && PYTHONPATH=src:. .venv/bin/python tools/pack_aa_recognition.py \
  --profile configs/reproduction/aa8_candidate_v2/factory.json \
  --out ~/Desktop/aa-recognition-$(date +%Y%m%d)
```

桌面上的 `aa-recognition-日期` 文件夹里有 zip、json 和蘑菇池数字样本，整个文件夹私下发给杜（微信文件、网盘私有链接），
让他的助手放到 `C:\PokerSense_data\recognition-pack\` 再做第 4 步。里面是真实牌桌截图，只发给同意参加测试的人，不要公开分享、不要提交进仓库。

## 哪里不对找谁

找主人。不要自己改代码、配置或数据文件夹里的东西。发给主人时带上：黑色窗口里的最后几行字、
`--self-check` 的输出、出问题的大概时间。

## 给杜本人（三句话）

1. 双击桌面上的“PokerSense”，浏览器会打开“信号灯”窗口，黑色窗口别关。
2. 来源选“采集卡”，点“开始”，看到牌桌后点“录像”。
3. 打完点“停止”，等窗口上写“已存好”再关。
