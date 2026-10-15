### 2026-10-15 · `claude/nightly-automation-60jgce`（并行测试偶尔因为 zip 里的时间收集出两套测试名）
- 做了什么：`tests/desktop/test_app_update.py` 的 `BUNDLE` 在导入时生成 zip，里面每个文件带当前时间；它又是测试参数，字节进了测试名。并行的几个进程跨过 2 秒边界时收集到的测试名不同，pytest-xdist 整批报错、一个测试都不跑（#76 的 macOS 就这样红了一次）。现在 `bundle_zip` 给每个文件写固定日期，字节每次都一样。
- 怎么做的：`zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))`，权限和 `writestr` 原来一样（0o600）；只改测试辅助函数，不碰产品代码。
- 怎么验证的：先加测试复现（改时钟后 `bundle_zip` 字节变了，旧代码失败），改后 `tests/desktop/test_app_update.py` 42 个全过，flake8 干净。
- 还剩什么：无。
