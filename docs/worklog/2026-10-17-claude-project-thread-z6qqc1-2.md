### 2026-10-17 · claude/project-thread-z6qqc1-2（Windows 录像能用 OpenH264；自检报录像盘剩多少）
- 做了什么：Windows 上数据文件夹的 `codecs` 里有 Cisco 的 `openh264-2.5.0-win64.dll` 时，录像前把这个文件夹放到本程序 PATH 最前面，OpenCV 的 FFmpeg 就能用 H.264（avc1）；自检的 `recorder` 多一项 `openh264`（位置或 null），另报 `recordings` 和 `recordings_free_gb`（录像盘剩余，少于 20 GB 不开录、剩 10 GB 自动停）。dll 不进仓库，每台电脑自己从 Cisco 下载并核对 SHA256（说明书里写了步骤）。
- 怎么验证的：照 OpenCV 4.14 源码里 FFmpeg 的设置（H.264 目标 fps×宽×高/2、质量模式；mp4v 每 12 帧一个关键帧），在 Linux 上用 OpenH264 2.5.0 和 OpenCV 自己的 mp4v 编同一段 60 秒合成录像：干净画面 0.03 对 0.64 GB/小时，每帧都加噪声时 0.72 对 0.68；每帧 CPU 约 9 对 10.5 ms。新测试：PATH 只加一次、没有 dll 或不是 Windows 时不动、Windows 上 OpenCV 的 FFmpeg 要的正是这个文件名、自检报剩余空间和盘不在时报 null；flake8。
- 还剩什么：真实大小和帧率看杜装上以后第一段录像（复盘线程会算）；不如 mp4v 时把 dll 挪走就退回。
