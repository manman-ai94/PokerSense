### 2026-10-16 · `claude/nightly-automation-60jgce`（校准桌拟合在 Mac、Windows 上不再一开始就崩）
- 做了什么：`tools/fit_aa_cal.py` 的拟合（`refit_aa_cal.py` 每次都用它）把牌局放在本进程的全局变量里，只有 Linux 那种“复制出来”的子进程看得到；Mac 和 Windows 的子进程是新开的，一开始就报 `KeyError: 'hands'`，`--workers 1` 也一样。现在云端照常，在 Mac、Windows 上也能跑。
- 怎么做的：进程池用 `initializer` 在每个子进程开始时把牌局交给它，搜索和结果都不变。
- 怎么验证的：新测试用 Mac 的开进程方式（spawn）跑一次拟合，在 main 上失败、改后通过；`test_fit_aa_cal`、`test_refit_aa_cal` 和 flake8 通过。
- 还剩什么：无。
