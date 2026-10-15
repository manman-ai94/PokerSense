### 2026-10-15 · `claude/nightly-automation-60jgce`（rclone 一升级，上传就一直关着）
- 做了什么：上传设置以前存的是 rclone 链接指向的真实路径（Homebrew、winget 都是带版本号的文件夹），rclone 一升级旧文件夹没了，上传和 Mac 拉回就一直失败；现在存链接本身，存下的路径不在了也会改用 PATH 上的 rclone。
- 怎么做的：`flywheel_sync.py setup` 存 `abspath` 不再 `resolve()`；`aa_upload.find_rclone` 跳过已经不存在的完整路径；拉回时找 rclone 也走它。夜间代码体检复查 #52 时发现。
- 怎么验证的：先加 3 个测试复现（存下的是版本文件夹、路径没了还用它），改后上传和拉回的测试全过，flake8 干净。
- 还剩什么：已经存了旧路径的电脑不用重设，路径失效时会自动改用 PATH 上的。
