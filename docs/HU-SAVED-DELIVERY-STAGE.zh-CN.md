# 已保存 HU 策略：离线入口与阶段边界

本组件基于用户指定主线 `codex/work-report-20260928` 的
`8f158e252e2f092b8c3706716b700c8a38a56af9` 准备。Reuse First：复用既有
Provider、Router、StrategyCandidate、DecisionContext 与保存树/JSON/Decimal/
历史金额 helper。只查询已有保存资产，没有新 Solver Core 或平行框架。

已覆盖两个 river 各 14 个决策节点和一个 turn 的 ROOT/IP-after-CHECK，共
30 节点。可选的多人来源 river 投影保留六/八人原始名单和行动历史，在 river
起点恰剩两名竞争者、单底池、确切已声明范围的条件下查询 28 个 river 节点。
原生合法菜单与求解抽象菜单分开；面对下注保留原街起点与路径，不重置 ROOT。
三名 active 中一名 all-in 仍不是纯 HU。树外历史拒绝，缺失行动 EV 留空。

投影范围独立，尚未建模 folded-card bunching。共享 Advice 对
`frequency_only_not_execution` 候选新鲜时 ABSTAIN、过期时 STALE，
不输出执行动作/偏好；provenance 的未来观测时间拒绝，缺失仍为缺失。
输入、模型与完整限制见 [保存路径](hu-saved-paths.md) 和
[river 投影](hu-river-projection.md)。全部附带材料为合成。

## 从源码 checkout 运行

使用已有 Python 3.11–3.13 和项目依赖（含 PokerKit 0.7.5），在本 checkout
根目录运行。PowerShell 下先让此 checkout 的源码优先：

```powershell
$env:PYTHONPATH = "src"
```

以下例子读取已保存的 river-a，查询 IP after CHECK，不启动求解后端：

```python
from pathlib import Path

from research.hu_root.adapter import RootAssetProvider, digest, request_config
from research.hu_root.fixtures import CASES, native_root
from poker_engine.strategy.router import StrategyRouter

case = next(c for c in CASES if c.name == "river-a")
_, start = native_root(case)
raw = Path("tests/fixtures/hu_saved/river-a/solution.json").read_bytes()
provider = RootAssetProvider(
    start, request_config(start), raw,
    sha256=digest(raw), origin="NATIVE_SAVED_RUN",
)
current = provider.context_for_path(("CHECK",), "QsKs")
result = StrategyRouter((provider,)).route(current)
print(result.state.value, current.actor_seat, len(result.selected.action_options))
```

预期输出 `HIT_EXACT 1 4`：保存 IP 节点的四个模型动作频率。
真实输入仍需可信完整范围、完整行动账本与精确保存场景匹配，不能默认补齐。

现有 frozen-v1 四节点 CLI 包含四个不同组合、八条节点组合查询行，
使用附带合成请求：

```powershell
python tools/query_frozen_postflop.py --request docs/examples/frozen-postflop/root-oop-aa.json
```

CLI 保留原四节点旧接口，上述 Provider 示例展示完整保存树查询。
这是源码研究入口，尚未接入 viewer/生产 registry，未发布安装包。

## 来源与移植范围

保存引擎固定为
`ucsandman/postflop@5fc7ee3d92b823b6c58e4f58cbee7d50d5e9e6de`。
三份 solution 原始字节与 SHA 保持不变；golden 仅将 `solution_file`
改为相对路径，其余结构和值不变。见
[资产 manifest](../tests/fixtures/hu_saved/MANIFEST.json) 与
[来源 pin / MIT 通知](../third_party/SOURCES.md)。

从旧 b807386 移植组件增量，未导入旧 main 候选的父链或全部本地历史。
指定主线版本 `0.2.0.dev1`、包装和既有 AGENTS 原则保持不变。
CI 保留主线 pytest -v/-ra、身份/JUnit/步骤结果、AA UI 回归与权限；
只扩展现有 flake8 命令覆盖 `research/hu_root` 和 `research/coverage_bridge`。

## 验证记录

本次指定主线上重新执行 23 个受影响测试文件，共 785 PASS / 0 FAIL / 0 SKIP：
组件与接口兼容 733 项，加 Fusion/Exploit/Orchestrator 消费链 52 项。
完整 src/tests/tools 和两个 research 包的 lint 通过。文档 IP 查询入口
输出 HIT_EXACT 1 4、EV 空白；附带 frozen-v1 CLI 合成请求入口通过。
这批结果在新基线上实际运行，未继承旧基线 733/733。
源修复 13ba129 独立 121 PASS / 0 FAIL 属于原组件资格验收，
与本次主线集成分开记录。原失败、旧候选与证据包保留原位。

尚未验证全量运行、安装包、完整 turn BR、chance/runout、bunching、真实范围
或真实行动。合成查询和工程通过不证明 GTO、盈利或实战资格。
发布前独立运行 28 PASS、静态检查 53 PASS，与作者 785 项分开记录。
本候选已获准进入 Draft PR；确切 PR/CI 状态另行记录，尚未合并、打标或发布。
