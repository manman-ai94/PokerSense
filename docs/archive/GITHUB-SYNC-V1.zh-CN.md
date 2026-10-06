# 标准 Git 同步：诊断结论与可复用入口（GITHUB-001）

> 第二轮（审查 GITHUB-001-R1 后）已按 P1-A/B/C/D 与三项对齐要求返工；
> 第三轮（审查 GITHUB-001-R2 后）已收紧**命令行入口判定**、**写入前校验**与**代理贯通**；见文末「第三轮返工」。

本文件说明 **PokerSense 在 Windows 本机上让标准 `git push` 可用**所需的配置、根因证据和使用方式。
它记录的是已验证事实，不是方案设想。

> 安全：本文件全部使用占位符（`$REPO`、`$PYTHON`、`$PROGRESS`），**不含**用户名目录、私有证据路径或任何令牌。

---

## 1. 症状与根因

| 项 | 事实 |
| --- | --- |
| 症状 | `git push` 挂起：一次约 3 分钟无输出；一次在 240s 外部超时后被终止（rc=124） |
| 误判一 | 「没有登录」——**错**。`gh auth status` 显示已登录（凭据存 keyring，scopes `gist, read:org, repo`） |
| 误判二 | 「代理不通」——**错**。`git fetch` / `git ls-remote` 均 1s 内成功；本机代理端口在监听 |
| **真实根因** | **凭据助手顺序**。本机 `credential.helper` 有两条：系统级 `helper-selector`（PortableGit）与用户级 `git-credential-manager.exe`。`-c credential.helper='!gh auth git-credential'` 只是**追加**到列表，**不移除**已有 helper；于是 GCM 仍先执行并阻塞（无人值守时等不到交互）。 |

### 修法（已验证）

```bash
# 关键：先 RESET 列表（空值），再添加 gh helper
git -c credential.helper= \
    -c credential.helper='!gh auth git-credential' \
    push origin refs/heads/"$BRANCH":refs/heads/"$BRANCH"
```

另需 `GIT_TERMINAL_PROMPT=0` 与 `GCM_INTERACTIVE=never`，确保任何情况下都不进入交互等待。

### 前后对比（实测）

| 项 | 修复前 | 修复后 |
| --- | --- | --- |
| `git push` | 挂起 / 240s 超时 rc=124 | **成功 2.8s，exit 0** |
| 远端分支 | 不存在 | 已创建 |
| 三方 SHA | 无从核对 | `local HEAD = remote ref = PR head` 全等 |

---

## 2. 可复用入口

薄封装：`tools/git_sync.py`（**只调用真正的 `git`/`gh`，不重写 Git 实现，不新建发布平台**）。

```bash
# 查看生效配置（脱敏：不含令牌）
$PYTHON tools/git_sync.py --repo $REPO --branch $BRANCH show-config

# 标准 push + 三方 SHA 校验（本地 HEAD / 远端 ref / PR head）
$PYTHON tools/git_sync.py --repo $REPO --branch $BRANCH \
    --progress $PROGRESS --timeout 120 --pr $PR push

# 只做校验（不推送）
$PYTHON tools/git_sync.py --repo $REPO --branch $BRANCH --pr $PR verify
```

### 它保证什么

- **凭据顺序**：helper 列表先重置、再加 gh helper（顺序有单测固定）。
- **真实退出码**：直接执行，`exit_code` 来自进程本身；**绝不用 `git push | tail` 取管道尾状态**。
- **外部计时器**：每条命令有超时；超时只 `taskkill /F /T` **自己这一条命令的子进程树**，不碰其他进程。
- **进度轨迹**：每 20 秒向 `$PROGRESS` 追加一条 JSON（`command_id`/`label`/`phase`/`elapsed_s`/`at_utc`）。
  这是**命令进度**，不是「研究有进展」的心跳。
- **无管道死锁**：stdout/stderr 由独立 reader 线程排空。
- **拒绝假成功**：三方 SHA 不全等即视为未通过；空值不算相等。
- **幂等发布**：`publish()` **不创建 commit**（提交由调用者负责）；同分支已存在且兼容的 PR 则复用，
  否则报错；创建/复用后一定**重新读取并校验** head/base/state，不靠返回值假定成功。

### 第二轮返工（审查 GITHUB-001-R1）

| 项 | 变更 |
| --- | --- |
| P1-A 进程组归属 | POSIX 用 `start_new_session=True` 让每条命令自成一会话/进程组，只对该组发信号；Windows 用有界 `taskkill /T` 并核对是否真的退出。kill 失败会**如实上报**（`kill_ok=false`、`survivors`）。期限用单调时钟；非有限/非正 timeout 直接拒绝。 |
| P1-B 仓库绑定 | 每个 git 调用带 `-C <已解析 repo>`，gh 调用带 `cwd=<repo>`；**任何远端写入之前**校验远端 slug、目标 ref 前缀（`refs/heads/codex/`）与待推 SHA，不通过则 `blocked_before_write`。 |
| P1-C 单一执行路径 | `ls-remote`、`pr view`、`pr list`、`pr create` 全部走 `run()`，因此都受同一超时、同一凭据修复、同一进度轨迹约束。 |
| P1-D 判定诚实 | GIT_SYNC 与 PR_SYNC 分级；API 失败即报错；PR 复用需 OPEN+Draft+base 匹配+head 实测一致。 |
| 对齐 1 | 不再硬编码本机代理：`--proxy` / `$POKERSENSE_GIT_PROXY`，否则继承环境。 |
| 对齐 2 | 本文件按 `publish()` 真实职责改写。 |

### 第三轮返工（审查 GITHUB-001-R2）

| 项 | 变更 |
| --- | --- |
| **入口判定（P1-a）** | `main()` 使用**单一成功判据**：给了 `--pr` 时以 `PR_SYNC_PASS` 为准（两方一致**不再**算成功）；命令报错/超时/**清理失败**（`kill_ok=false`）一律非零，**不被「SHA 恰好相等」掩盖**；无 `--pr` 时才允许以两方结果成功并保留 `PR_NOT_CHECKED`。`verify` 保留 `local_ref_error`、`remote_read_error`、`pr_error`，不再只显示空 SHA。PR 的仓库/head 分支/OPEN/Draft/base 校验移到**入口共用路径**，不只在 `publish()` 内。 |
| **写入前校验（P1-b）** | 远端身份**失败关闭**：读取失败或为空即**拒绝**写入（此前空值会跳过检查）；远端 URL 用实际 **host + 仓库路径**解析（含 scp 式 `user@host`）并与期望值比对；push 前解析并核对**完整 source ref / 目标 ref / 已批准 SHA**，并校验 HEAD 与 source ref 一致；不匹配则在写入前 `blocked_before_write`。 |
| **代理贯通（P2）** | 引入单一执行上下文 `Ctx(repo, proxy, timeout, progress)`；代理随上下文到达 `resolve_repo` / `remote_url` / `rev-parse` / **push** / **ls-remote** / **pr view** / **pr list** / **pr create**，`main verify --proxy` 同样生效；**不回写全局环境**。 |
| 如实保留的限制 | `terminate_owned_group` 的 `kill_scope` 明确标注为 `group-leader-only`：`survivors` **只证明组长退出**，**不**证明全部后代退出；整树证明留待后续补测试。 |

### 它不做（硬边界）

不 `--force` / 不 `reset` / 不 `rebase` / 不 `clean`（有单测对其断言）；
不改仓库可见性、CI 配置、账号权限；不读写 secrets。

---

## 3. 元数据与 Git 的分工

| 用途 | 工具 |
| --- | --- |
| 版本对象（提交、分支、同步） | **标准 git**（经上述封装） |
| Issue / PR / review / Actions 元数据 | `gh` / 官方 API |

时间预算按任务要求：元数据/API 诊断 60s 外部超时；小规模 fetch/push 120s 外部超时。

---

## 4. 未修复 / 未验证（如实）

- 用户级 `git config` 的 GCM helper **未被修改**：本轮以**命令级作用域**解决，不改全局配置。
- 是否改用 `gh auth setup-git` 写入用户级 helper：**未执行**（需先备份并取得所有者确认）。
- 传输层强制 HTTP/1.1、`http.postBuffer` 调整：**未尝试**（根因不在传输层，无需盲改）。
