# WPK v6 独立环境复现报告

日期：2026-09-08。结论：**同机独立环境的训练和冻结回放复现PASS**。
这解决了上轮OpenCV混装造成的复现风险，不增加新的牌局验收样本，也不意味着生产可以放行。

## 环境与边界

新建独立venv：

`C:\Users\Administrator\.codex\runtimes\pokersense-v6-clean-20260908`

CPython3.13.14，`include-system-site-packages=false`，禁用用户site包。
实际numpy和cv2均从新venv加载，搜索路径没有外部site-packages。
仅安装opencv-contrib-python4.10.0.84；实际OpenCV4.10.0二进制SHA-256：

`3d45cec35e10e9889fe19fbe3ecf4459ea663009ed7bc998a9705322cc5db017`

与上轮实际加载文件一致，并匹配唯一OpenCV发行包的wheel RECORD。`pip check`通过。
没有修改或卸载共享WorkBuddy环境中的包。

本环境专用于复现历史v6候选，**不是项目发布依赖版本的验收**。
仓库原有numpy2.4.6/OpenCV4.14.0.94发布依赖声明没有改动，也尚未在那些版本下验证。
不要在此环境直接执行会安装项目默认依赖的`pip install -e .`，否则可能重新混入第二个OpenCV包。

## 实际验证

| 核对项 | 结果 |
|---|---|
| 86种已审阅字形重新生成2150个训练输入 | 与原训练数组逐字节相同 |
| 相同seed/参数重新训练点数头 | 与原权重文件逐字节相同 |
| 原第三批2401帧连续回放 | 8个检查点的字段、原始分数、拒答和汇总完全一致 |
| 原冻结规范 | 同一份规范、标注、候选权重和0.50门槛，未重新选择 |
| 独立环境全套回归 | 2388 passed / 1 skipped / 2 warnings，21.86秒 |
| Flake8与差异空白检查 | 通过 |

权重哈希仍为：

`ba73c17601a37f53726cf78da5954e7818ded452a3362059559bef7449693d1a`

训练数组归档哈希仍为：

`e677915e5f31abe51d01a5106cbcceff20b1da747f9ebb3f207500c5edd7a475`

回放使用第三批保存的`model-snapshot`源码，不用当前源码冒充原始冻结环境。
回放耗时可变化，所以对照不要求报告JSON文件整体哈希相同；所有检查点内容和分数要求严格相同。
这只是环境复现，底牌15正确/1拒答、公共牌20正确的结果没有变成额外独立样本。

唯一跳过为macOS Quartz；两个警告来自Starlette测试客户端的httpx与AnyIO兼容接口弃用提示。
没有静默过滤警告，也没有为了消除提示更换测试客户端。

## 本轮修复的工具问题

训练产物清单和开发回放快照曾硬查`opencv-python`的发行包元数据。
在只装contrib包的环境中，这会产生PackageNotFoundError；第一次独立全套回归如实保留为失败记录。
现在训练清单枚举实际存在的OpenCV发行包，快照记录实际加载的cv2版本，
不再通过安装第二个冲突包来满足工具假设。识别算法、训练参数、权重和阈值均未改变。

新增运行路径隔离检查，以及权重/训练数组/检查点精确对照工具和10个测试。

## 依赖锁定和离线安装材料

仓库内：

- `configs/reproduction/wpk-v6-windows.txt`：说明性的精确版本清单。
- `configs/reproduction/wpk-v6-windows.lock`：训练/回放依赖，包含wheel SHA-256。
- `configs/reproduction/wpk-v6-windows-tests.lock`：附加测试依赖及传递依赖的wheel SHA-256。

锁文件只针对Windows x64和CPython3.13；包含平台wheel哈希，不应直接当成其他平台的锁文件。
两个锁文件对应37个wheel，合计120471495字节。已通过`pip download --require-hashes`
获取并逐一比对安装报告中的哈希，缺失/意外包均为0。测试依赖没有替换训练核心包。
离线wheel库位于私有复现目录`wheelhouse/`，不进入公开仓库。

在**另一个新建、空的venv**中，可用以下方式离线安装：

```powershell
# $newPython 指向新venv的Scripts/python.exe，不是共享环境。
& $newPython -I -m pip install --no-index --require-hashes `
  --find-links G:/PokerSense_archive/wpk_video_first_20260908/reproduction/v6_clean_20260908/wheelhouse `
  -r configs/reproduction/wpk-v6-windows.lock `
  -r configs/reproduction/wpk-v6-windows-tests.lock
```

本轮已经完成干净环境安装和wheel哈希验证，未另外创建第二个venv专测上述离线安装命令。

后续WPK本机开发默认使用本轮已验证的独立解释器：

```powershell
$wpkPython = 'C:/Users/Administrator/.codex/runtimes/pokersense-v6-clean-20260908/Scripts/python.exe'
$env:PYTHONPATH = 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
& $wpkPython -m pytest tests/ -o addopts='' -q -rs
```

## 证据与下一步

私有目录：`G:\PokerSense_archive\wpk_video_first_20260908\reproduction\v6_clean_20260908`。

- `pip-install-report.json`、`pip-test-dependencies-report.json`：来源、版本与wheel哈希。
- `runtime-fingerprint.json`：初始运行路径与OpenCV二进制核对。
- `retrained/`：重新生成的训练数组和权重，保留本轮训练脚本。
- `batch03-replay-result.json`：原冻结源码在新环境下的完整回放结果。
- `verification.json`：复现对照的组合判定`passed=true`；不是单独元数据指纹的结论。
- `pytest-clean.xml`、`pytest-clean-final.xml`：工具兼容问题修复前/后的完整回归记录。
- `wheelhouse-verification.json`、`wheelhouse/`：37个精确匹配的安装包。

下一步回到识别/状态主线：补空底牌、发牌、换手、弃牌后的时序负样本，
核查候选误接受和旧值残留；再扩展动作、筹码、主/边池与完整状态真值。
原始媒体、标注、模型首测与生产权重保持不变，`requires_revalidation=true`继续有效。
