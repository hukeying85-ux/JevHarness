---
name: cgmd-desk-loop
description: >
  TRIGGER: "安装 arena/03860148-jevharness 的 skills/cgmd-desktop + skills/desk-loop, 与台式机打通,
  跑动力学到成功". Drives the **existing** CGMD desk (DESKTOP-IEUDGS5, already running
  CGMD-Hub-Poll every 60 s) through its git mailbox: request -> desk pulls & executes ->
  receipt is pushed back -> declarative success criteria are evaluated -> repeat until pass.
  Agent-side only: no new watcher, no new PowerShell, no bootstrap. Job kinds: cgmd/gmx/ping/
  smoke/selfcheck/deskdiag/deskfix/sync are open; shell and pipeline are closed by design.
  Commands: `deskloop.py doctor|status|request|wait|criteria|loop|sync|recover|handoff|ledger`.
---

# desk-loop · 一条命令把「发单 → 台式机执行 → 结果回推 → 判定成功 → 重试」闭起来

> 用户一句话（新会话可直接发这一句）：
> **「安装 arena/03860148-jevharness 的 skills/cgmd-desktop + skills/desk-loop，与台式机打通，跑动力学到成功」**

这个 skill 只补**代理侧**的那一半。台式机侧本来就在跑：`CGMD-Hub-Poll`（计划任务，60 s，静默）
→ `Invoke-CgmdMailbox.ps1` 取件执行 → 把回执推到 `hub/mailbox` 的 `outbox/`。
**没有第二套基座**：本 skill 不写任何 `.ps1`、不注册计划任务、不改台式机配置。

---

## 1. 三个「打通」分别是什么

| 打通对象 | 怎么实现 | 谁负责 |
|---|---|---|
| **我（Arena 沙箱）↔ 台式机** | 我 `push` 工单到本仓库 `hub/mailbox`；台式机 `fetch` 执行；回执落到台式机仓库 `outbox/`，我 `fetch` 读回 | 两边各跑一条命令（`deskloop.py request/loop` + 已有的 poller） |
| **台式机 ↔ 它的能力** | `cgmd` 工单用**固定脚本 + JSON 参数**（不是命令行），所以不需要 shell、不需要投递文件 | 台式机仓库 `code/cgmd/desk_ops.py`（已有） |
| **新对话 ↔ 同一闭环** | 通道**就是仓库本身**：任何会话只要能读本仓库分支，`git clone` + `deskloop.py doctor` 就接进同一个队列和同一份回执 | `deskloop.py handoff` 打印整张卡片 |

新会话的最小启动：

```bash
git clone -b arena/03860148-jevharness https://github.com/hukeying85-ux/JevHarness.git /home/user/JevHarness
cd /home/user/JevHarness
python3 skills/desk-loop/deskloop.py doctor            # 分支守卫 + 台式机能力卡（约 60 s）
python3 skills/desk-loop/deskloop.py handoff           # 打印连接卡片 / 可用工单 / 一条 MD 命令
```

---

## 2. 借鉴了什么，刻意不借什么

来源：[`mqgg5630-cyber/git-pull-arena` · `skills/git-sync` v2.8.1](https://github.com/mqgg5630-cyber/git-pull-arena/tree/arena%2F01a0ff69-git-pull-arena)
（README 明确：Arena 会话分支 ⇄ Windows 本机，`agent-sync.sh` 提交前跑 `code/check_all.sh` 自检并写同步回执）。

| 借鉴 | 在 desk-loop 里的落点 |
|---|---|
| 配置驱动（`sync.config.json`：branch/remote/gate/receipt/criteria） | `skills/desk-loop/sync.config.json` |
| **分支守卫**：拒绝 `main/master`、要求 `HEAD == config.branch` | `deskloop.py sync` + `gate.py` |
| **提交前自检**（脚本自洽、配置分支一致） | `gate.py`（py/json 语法、轨迹文件禁区、单文件 5 MB 上限、分支） |
| **每次同步写回执** | `results/sync/last_sync.md`；闭环另写 `results/sync/loop_receipt.md` |
| **声明式成功标准 + 三个退出码**（0 过 / 2 不过 / 3 未到） | `success_criteria.json` + `deskloop.py criteria` |
| **`--timeout auto`：一到就停，不死等** | `deskloop.py wait --timeout auto`（默认 `answer_wait_s`） |
| **`agent-recover.sh`：沙箱 `.git` 被重置回基线后保住工作区** | `deskloop.py recover`（今天在沙箱里真被重置过两次） |
| **连接台账 `CONNECTIONS.md`** | `skills/desk-loop/CONNECTIONS.md` + `deskloop.py ledger --append` |

| 刻意不借 | 原因 |
|---|---|
| `watch.ps1` / `bootstrap.ps1` / `install.ps1`（本机常驻值守与安装器） | 台式机已经有 `CGMD-Hub-Poll` 在跑；再造一套就是用户明令禁止的「第二套基座」 |
| 本机 PowerShell 全家桶（`sync/push/auth/upload/download/pack/doctor`） | 我的沙箱没有 Windows；而且这条链路的传输已经是 git mailbox |
| 「本机跑检查脚本」的 `check_cmd` | 台式机的检查由 `selfcheck` / `cgmd probe` 工单完成，不需要本机脚本 |

---

## 3. 架构

```
Arena 会话（我）                                  台式机 DESKTOP-IEUDGS5
────────────────                                  ──────────────────────
deskloop.py request  ──push──▶  hub/mailbox:inbox/<id>.json
                                                  │ CGMD-Hub-Poll（60 s，静默）
                                                  ▼
                                          Invoke-Job<Kind>
                                          ├ cgmd  : probe/ff/build/run（自带建模 + GPU MD）
                                          ├ gmx   : 白名单子命令（对已有文件）
                                          └ ping/selfcheck/smoke/deskdiag/deskfix/sync
                                                  │
deskloop.py wait     ◀──fetch──  hub/mailbox:outbox/<id>.json （回执 + 桌面侧路径）
deskloop.py criteria → 没过就再来一轮 → 过了写 loop_receipt.md
deskloop.py sync     → gate → commit → push → results/sync/last_sync.md
```

要点：**通道上跑的是 JSON，不是命令行**；回执里带着桌面侧的绝对路径（`workdir`、`prod.log`），
所以「结果在哪」永远有据可查。

---

## 4. 命令

| 命令 | 作用 | 退出码 |
|---|---|---|
| `deskloop.py doctor [--no-network]` | 分支守卫 + 台式机能力卡（gmx/python/martini/drives）+ 当前 criteria | 0 / 2 |
| `deskloop.py status` | 只读：台式机 `hub_mailbox.json` 状态、`allow_shell`、心跳、`queued` | 0 / 2 |
| `deskloop.py request --kind cgmd --json-args '{...}'` | 发一个工单，打印工单号 | 0 |
| `deskloop.py wait <id> [--timeout auto]` | 轮询到回执为止（**一到就停**） | 0 ok/warn · 3 超时 · 2 真失败 |
| `deskloop.py criteria [--json]` | 评估 `success_criteria.json` | 0 / 2 / 3 |
| `deskloop.py loop --kind cgmd --json-args '{...}' --rounds 3` | 发单→等→判；不过就再发一轮 | 0 / 2 |
| `deskloop.py sync --message "..."` | 分支守卫 → 暂存守卫 → gate → commit → push → 回执 | 0 / 1 / 2 |
| `deskloop.py recover` | 沙箱 `.git` 被重置后，保住工作区、对齐远端、重新暂存 | 0 |
| `deskloop.py handoff` | 打印新会话进同一个闭环所需的卡片 | 0 |
| `deskloop.py ledger --append <仓库> --note <说明>` | 追加一行连接台账 | 0 |

跑一段动力学（会自动串 probe → build → run，并按累计 ns 分片续算）：

```bash
python3 skills/desk-loop/deskloop.py loop --kind cgmd --rounds 2 \
  --json-args '{"mode":"all","sequence":"YLSLLQR","ns":2}'
```

更长的轨迹用 `skills/cgmd-desktop/cgmd_agent.py md --sequence … --ns 100 --slice-ns 50`：
每片改写 `prod.mdp` 的 `nsteps` 到**累计**值并从 `prod.cpt` 续算。

---

## 5. 成功标准（声明式）

`skills/desk-loop/success_criteria.json`，schema 与 `agent-criteria.sh` 同构（全部 key 可选）：

```json
{
  "require_files":   ["results/desktop/md_*.json"],
  "forbid_files":    ["results/desktop/*.xtc"],
  "require_contains":{ "path": "results/sync/last_sync.md", "substring": "push: ok" },
  "require_regex":   { "path": "...", "pattern": "..." },
  "min_bytes":       { "path": "..." , "bytes": 100 },
  "require_json":    [ { "glob": "...", "field": "status", "equals": "ok" },
                       { "glob": "...", "field": "performance_ns_per_day", "min": 100 } ]
}
```

`require_json` 支持 `equals` / `min` / `max` / `one_of`，`field` 用点号取嵌套键（含数组下标），
**同一 glob 命中多个文件时取 mtime 最新的那份**——闭环关心的是最近一次。

---

## 6. 实测（2026-11-02，本 skill 自己跑出来的）

| 环节 | 证据 |
|---|---|
| `doctor`（probe 工单） | `20261102T013929-5019` → gmx 2025.1 CUDA 12.8 / py 3.12.10 / martini3 found |
| `build`（从序列建体系） | `20261102T014012-224b` → YLSLLQR 1309 珠 / 5.3 nm（1275 W + 13 NA + 14 CL），1.1 s |
| `run` 分片续算 | 12 ns 三分片 `…12816-1996` / `…13020-9770` / `…13225-667a` → 7053 / 5486 / 7200 ns/day，累计 4→8→12 ns 全部 `Finished mdrun` |
| **100 ns 生产（完整成功）** | 两片：`20261102T014115-cf33`（50 ns @ 6718.51 ns/day）+ `20261102T015308-01d4`（累计 100 ns @ 5814.27 ns/day），5,000,000 步、`Finished mdrun`、0 LINCS、Rg 0.666 → 0.627 nm → `results/desktop/md_YLSLLQR_20261102-020641.json` |
| `loop`（发单→等→判） | `20261102T020731-cadb` → 1 轮 ok，criteria passed（`results/sync/loop_receipt.md`） |
| `criteria` | 未跑满时不通过（exit 2）、跑满且 `finished=true` 时通过（exit 0）——两个方向都验过 |
| `gate` | `gate.py` 4 项全过；故意放进 `*.xtc` 会被拒 |

---

## 7. 排障

| 现象 | 处理 |
|---|---|
| `[REFUSED] HEAD is … expect …` | 用 `deskloop.py recover` 或直接切回 `sync.config.json` 里的分支 |
| 工单一直 `queued` | 台式机 `mailbox_jobs_per_poll = 1`，被别的会话占用；`status` 看 `queued`，等或重发 |
| `wait` 超时但台式机其实跑了 | 调大 `answer_wait_s`，或 `deskloop.py wait <id>` 补等（账本里未答复工单不会重复发） |
| `criteria` 一直 failed 但轨迹跑完 | 看 `deskloop.py criteria` 的逐条输出；通常是 `final_report.finished` 字段路径写错 |
| 沙箱 `.git` 又回到基线 | `deskloop.py recover`（默认保 `skills/ results/ cgmd_endtoend/ README.md`） |

---

## 8. 安全边界

* 不开 `shell`：台式机 `allow_shell=false` 保持原样；本 skill 只用 `cgmd` / `gmx` 这类**固定脚本 + JSON**工单。
* 不写台式机仓库：只有读（`fetch`），没有 `push`（也没有权限）。
* 不碰源数据：桌面建模只写它自己的 `%USERPROFILE%\cgmd-runs\`。
* 提交守卫：轨迹/坐标/检查点永远不进 git；单文件 > 5 MB 会被 `gate.py` 拦下。
