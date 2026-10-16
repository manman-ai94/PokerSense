### 2026-10-16 · feat/session-package-ki33nf（测试不再读到本机装的 rclone）
- 做了什么：`test_setup_keeps_the_player_the_synced_folder_and_since` 在主人 Mac 的装前复查里失败：setup 找 rclone 时除了 PATH 还看 `/opt/homebrew/bin`，Mac 装了 rclone 就多写一项；CI 机器上没有 rclone 所以一直是绿的。
- 怎么做的：只改测试，把“常见位置”也换成空的；上传测试里那个“没有 rclone”的 Uploader 也加 `places=[]`。软件行为不变。
- 怎么验证的：在容器里放一个假的 `/opt/homebrew/bin/rclone` 复现了失败；改后有它没它两个测试文件都是 37 个通过；flake8 通过。
