# skills/cgmd-desktop · 自动「发单 → 拉取 → 执行 → 回推 → 轮询到成功」

一句话：**把台式机已有的 CGMD 基座当成一个队列服务，用一个幂等客户端把「发工单 / 等回执 / 重试 /
串阶段 / 分片续算」全部自动化，直到任务真的成功。**

它不新建任何台式机侧的东西——台式机那半边（`CGMD-Hub-Poll` 每 60 s 轮询 + `Invoke-CgmdMailbox.ps1`
执行 + 回推 `outbox/`）本来就在跑，本 skill 只补**客户端那一半**。

---

## 1. 为什么这不是「第二套基座」

| 半边 | 由谁负责 | 本 skill 是否新建 |
|---|---|---|
| 台式机：自动 `fetch` 自己的仓库并执行工单 | 已有的 `CGMD-Hub-Poll` 计划任务（60 s，静默） | ❌ 不新建 |
| 台式机：执行器 / 白名单 / 结果回推 `hub/mailbox` | 已有的 `skills/cgmd-hub/runner/Invoke-CgmdMailbox.ps1` | ❌ 不新建 |
| 云端：发单、等回执、失败重试、阶段串联、分片续算、归档 | **本 skill** `cgmd_agent.py` | ✅ 只有这一层 |

客户端通过 `core.hub_mailbox`（台式机仓库自带的协议实现）**直接复用**同一套 schema：

```
我这边                                  台式机
──────                                  ──────
send(kind, args)  ──push──►  hub/mailbox:inbox/<id>.json
                                          │ 60 s 轮询 fetch
                                          ▼
                                    Invoke-Job<Kind> 执行
                                          │
read_result(id)  ◄──fetch──  hub/mailbox:outbox/<id>.json
```

不需要 shell、不需要把文件送过去——因为桌面侧的 `cgmd` 工单**自己会生成体系文件**。

---

## 2. 现网能力（2026-11-02 实测）

| 工单类型 | 状态 | 用来做什么 |
|---|---|---|
| `ping` | ✅ | 主机 / GPU / gmx 版本 / LAN |
| `selfcheck` | ✅ | 18 项自检（15 pass / 3 warn / 0 fail） |
| `smoke` | ✅ | 100 ps 原生 GPU 烟测（576.0 / 617.2 ns/day，SPC 1530 原子） |
| `gmx` | ✅ | 白名单 gmx 子命令，对**桌面上已有**的文件执行（`mdrun -s <tpr>` 实测 3323.2 ns/day） |
| `cgmd` | ✅ **本 skill 的主通道** | `probe / ff / build / run / search / all`：从**序列**生成 Martini 3 体系并在 GPU 上跑真 MD |
| `deskdiag` / `deskfix` / `sync` | ✅ | 桌面面板与配置修复 |
| `shell` | ❌ `allow_shell=false` | 任意命令（默认关闭，需在台式机显式打开） |
| `pipeline` | ❌ 未接线 | 返回 `unsupported` |

`cgmd` 是这套方案的关键：`build` 用**序列**建体系（Martini 3 backbone-only + 弹性网络，按残基电荷选
`Q5/Q5n/Q5p` 珠），`run` 走 `grompp → mdrun-em → grompp-eq → mdrun-eq → grompp-prod → mdrun-prod`，
全程 GPU，返回 `Performance: … ns/day`、`Rg`、接触簇。**输入只有一个 JSON，没有命令行、没有 shell。**

---

## 3. 用法

```bash
# 0) 一次性（会自己 clone 台式机仓库到 ~/.cache/cgmd-desk）
python3 skills/cgmd-desktop/cgmd_agent.py doctor

# 1) 只读状态，不发工单
python3 skills/cgmd-desktop/cgmd_agent.py status

# 2) 跑一段 CG MD：probe → (ff) → build → run（自动分片 + 从 checkpoint 续算）
python3 skills/cgmd-desktop/cgmd_agent.py \
  --outdir results/desktop md --sequence YLSLLQR --ns 20 --slice-ns 5

# 3) 单发一个工单（任意 kind）
python3 skills/cgmd-desktop/cgmd_agent.py job --kind gmx --argv mdrun -s C:/path/prod.tpr -nsteps 5000

# 4) 补等一个已排队工单
python3 skills/cgmd-desktop/cgmd_agent.py watch 20261102T011124-3a0d
```

参数要点：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--repo` | `.` | 我的检出；工单从这里 push 到本仓库的 `hub/mailbox` |
| `--desk` | `~/.cache/cgmd-desk` | 台式机仓库的克隆；回执从这里 pull |
| `--outdir` | `results/desktop` | 每份回执 + 汇总 manifest + `ledger.json` |
| `--answer-wait` | 900 s | 单个工单等多久（台式机空闲/被别人占用时会晚） |
| `--retries` | 3 | **只对「没回音」重试**；`fail`/`unsupported` 是真答案，不重复烧 |
| `--slice-ns` | `min(ns, job_timeout/60)` | 每个工单推进到**累计**多少 ns |

产出：`results/desktop/<job-id>.json`（原始回执）+ `md_<seq>_<时间>.json`（阶段/分片汇总）+
`ledger.json`（同一 payload 的幂等账本：未答复的工单会被复用，而不是再发一份）。

---

## 4. 实测证据（2026-11-02，全部是本 skill 跑出来的）

| 内容 | 工单 | 结果 |
|---|---|---|
| 能力卡（probe） | `20261102T011312-8301` | gmx 2025.1 / CUDA 12.8、python 3.12.10、**martini3 found**（走缓存 `C:\Users\BNI\cgmd-runs\martini3\…`） |
| 建体系 YLSLLQR | `20261102T012713-d143` | **1309 珠 / 5.3 nm / 1275 W + 13 NA + 14 CL**，0.27 s |
| 2 ns 单工单 | `20261102T012411-9e6d` | **2.000 ns @ 5400.05 ns/day**，Rg 0.651 → 0.594 nm |
| 12 ns 三分片（累计 4 → 8 → 12） | `20261102T012816-1996` / `013020-9770` / `013225-667a` | **7053 / 5486 / 7200 ns/day**，每片都 `Finished mdrun`，续算语义正确（4.00 → 8.00 → 12.00 ns） |

原始回执见 `evidence/`。汇总 manifest：`evidence/md_YLSLLQR_2ns.json`、`evidence/md_YLSLLQR_12ns_sliced.json`。

---

## 5. 「能不能靠这个办法把动力学测完」——分情况

**能，但要看你要的是哪一种动力学。**

| 目标 | 桌面 `cgmd` 通道 | 沙箱（本仓库 `cgmd_endtoend/`） |
|---|---|---|
| 单条肽的 CG 折叠/塌缩（Rg、形状） | ✅ 已跑通，GPU 5400–7200 ns/day | ✅ |
| Martini 3 **多拷贝浓度/寡聚化** | ❌ `build` 固定单拷贝 | ✅ 6 拷贝、7.8/9.8 nm 两档、n=3 种子 |
| 精确的 martinize2 18 珠映射（含侧链珠） | ❌ 桌面 builder 是 backbone-only（1 珠/残基，按电荷选型） | ✅ martinize2 + 弹性网络 |
| 长轨迹（μs 级） | ⚠️ 受每工单 3600 s 上限约束，需分片续算（本 skill 已实现） | ⚠️ 2 核 CPU，~6400 ns/day，1 μs ≈ 3.8 h |

所以正确的用法是**两条腿走路**：

1. **桌面上量性能、跑长轨迹**：`cgmd` 通道已能建体系 + GPU 跑 MD + 续算，适合把单肽的
   时间尺度拉长（Rg 动力学、二级结构保持、单链塌缩统计）。
2. **沙箱里做浓度臂**：多拷贝 + 浓度扫描 + n=3 种子 + 参数敏感性，已经在 `cgmd_endtoend/` 里做完。
3. 如果要在桌面上做**多拷贝**浓度臂：需要让桌面 builder 支持 `copies`（那是台式机仓库
   `code/cgmd/desk_ops.py` 的一行改动，不是本 skill 能改的），或者打开 `shell`/`pipeline`。

---

## 6. 排障

| 现象 | 原因 | 处理 |
|---|---|---|
| `wait` 到了 `timeout` 但台式机其实跑了 | 客户端只等 `--answer-wait` 秒，而台式机轮询 + 排队可能更久 | 调大 `--answer-wait`，或 `watch <id>` 补等；账本里未答复的工单不会重复发 |
| `status: unsupported … workdir` | `build` 没给出 workdir（路径是 Windows 反斜杠） | 已修：`desk_dirname()` 用 `ntpath` 解析 |
| `cgmd probe` 说 `martini 3 force field missing` | 缓存里没有 | agent 会自动先发一次 `mode=ff` |
| 工单一直 `queued` | 台式机被别的会话占用（`mailbox_jobs_per_poll = 1`） | 等待或稍后重发；`status` 能看到 `queued` 数与心跳 |
| `grompp` 崩 0xC0000005 | 这台 Windows 版对 `#include` 拓扑的老问题 | 桌面 `cgmd` 的 builder 已自带内联；自己的体系先用 `cgmd_endtoend/scripts/flatten_top.py` 展平 |

---

## 7. 安全边界（刻意保留的）

* **不开 shell**：全部动作走 `cgmd`/`gmx` 的**固定脚本 + 固定模式**，输入是 JSON 而不是命令行；
  `gmx` 只接受白名单子命令且禁止 shell 元字符。
* **只读源数据**：桌面 builder 只在自己的 `%USERPROFILE%\cgmd-runs\` 下写，不碰 `F:\0wsh`。
* **不改台式机代码**：本 skill 不做 `git push` 到台式机仓库（无权限，也不需要）。
* **幂等**：同一 payload 在未答复期间不会重复发单；`fail` 不会被无限重试。
