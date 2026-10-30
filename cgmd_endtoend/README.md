# CGMD 端到端验收 + 粗粒化（Martini 3）复刻

> 会话：Arena `arena/03860148-jevharness` · 台式机：`DESKTOP-IEUDGS5`（Windows 10 + RTX A4000 16 GB + 原生 GROMACS 2025.1 CUDA，`F:\gromacs-2025.1-SM86`）
> 全部动作经 git 信箱总线（`hub/mailbox`）+ Arena 侧自行构建的 Linux 环境完成，没有任何一步需要人在台式机上敲命令。
> 本文所有数字都是本次实测，未实测的一律写“未验证”。
>
> **第二轮补充（同日）**：① 每臂补到 **n = 3** 独立种子并把误差棒算出来（§4.5，结论因此变保守）；
> ② 做了 1 套参数敏感性交叉检查（§4.6，**链刚度的影响大于浓度**）；
> ③ 把“台式机 GPU 跑 Martini 3 到底多快”**实测**出来了（§4.3，3323.2 ns/day），
> 并发现 hub 默认线程布局会白丢 4.7×；④ 给出**台式机上全部结果文件的绝对路径**（§4.4）；
> ⑤ 把桌面端 `grompp` 的 0xC0000005 做成可用工具 `scripts/flatten_top.py` 并验证其不改物理（§5.1）。

---

## 1. 验收表

| 项目 | 实测值 | 证据 |
|------|--------|------|
| 主机 | `DESKTOP-IEUDGS5`，用户 `BNI`，48 核 | ping `20261030T020458-3bc6` |
| 值守心跳 | 信箱工作进程 `state=ran`，本轮复验 `generated_at 2026-10-30T15:16:09+08:00`（`poll_count=29`、配置间隔 60 s、`state=idle`）；`hub_heartbeat.json` 15:03:10、`CGMD-Hub-Poll` 计划任务在跑 | `mailbox/desktop_hub_mailbox.json`、`mailbox/20261030_20261030T070202-f454.json` |
| GPU | `NVIDIA RTX A4000`，驱动 596.71，16376 MiB，1 张；`gmx` 报告 GPU support **CUDA** | ping + smoke |
| GROMACS | **2025.1** 原生 Windows：`F:\gromacs-2025.1-SM86\gromacs-2025.1-SM86\bin\gmx.exe`；WSL 侧另有 2018.1（CPU，未使用） | ping、selfcheck |
| 本次 ping | 工单 `20261030T020458-3bc6`，**端到端 79 s**（其中约 61 s 是 60 s 轮询等待，工单本身 **0.43 s**），`status=ok` | `mailbox/20261030T020458_20261030T020458-3bc6.json` |
| 本次 100 ps 烟测 | 工单 `20261030T020623-6973`，工单耗时 **28.54 s**（端到端 123 s），**576.012 ns/day**，`status=ok` | `mailbox/20261030T020623_20261030T020623-6973.json` |
| 自检 | 工单 `20261030T021444-ab6b`：18 项 **15 pass / 3 warn / 0 fail**，`overall=warn`，24.7 s | `mailbox/20261030T021444_20261030T021444-ab6b.json` |

> selfcheck 的 3 个 warn 正是后面复刻的关键约束：`martini3`（台式机无 `martini_v3.0.0.itp`）、
> `python`（缺 vermouth / insane / MDAnalysis / matplotlib）、`tools`（`martinize2`、`insane` 不在 PATH）。

## 2. 100 ps 烟测的 6 项逐条核对

| # | 判据 | 实测 | 结论 |
|---|------|------|------|
| 1 | `result.status == "ok"` | `ok` | ✅ |
| 2 | `report.ps_completed == 100` | `100` | ✅ |
| 3 | `report.mdrun.finished == true` | `true` | ✅ |
| 4 | `report.mdrun.performance_ns_per_day > 0`（基线 540–617） | **576.012** ns/day | ✅ 落在基线内 |
| 5 | `report.accelerator == "gpu"` | `"gpu"`（不在 `report.progress` 里，确认取的是顶层 `accelerator`） | ✅ |
| 6 | `report.stages` 中 `mdrun-md-gpu.returncode == 0` | `0`（16.23 s） | ✅ |

各阶段返回码：`solvate 0` / `grompp-em -1073741819`（本机预编译版 0xC0000005 已知坑，脚本自动走内联拓扑兜底）/
`grompp-em-inline 0` / `mdrun-em 0` / `grompp-md 0` / `mdrun-md-gpu 0`。系统为 SPC/E 水盒 2.5 nm、1530 原子。

---

## 3. 粗粒化复刻：做了什么

复刻对象 = 该文档 **§9 方法 8「粗粒化大体系与浓度/种子表面积扫描」**（MARTINI 类一锅式 CG-MD，
以“局部富集—小寡聚体”为相对筛选信号，**不作绝对时间映射**）。

具体落到文档 §1 定义的四类体系里的 **「候选肽单独」这一臂**（另外三臂是 Aβ 单独、Aβ+候选肽、
Aβ+乱序肽）。这一臂只需要肽本身，不需要 Aβ 结构、seed 模型或 seed 表面积扫描，
所以在拿不到本文档其余输入、也拿不到台式机执行通道的条件下，它是**唯一能真跑起来**的一臂。

### 3.1 肽的来源（必须说清楚）

* 你指的 `F:\0wsh\asd` 我**读不到**。云端出网只放行 github / pypi / npm，够不到 192.168.x.x / 100.84.x.x；
  台式机侧唯一的文件通道是 `shell` 工单，而它是关闭的（`allow_shell=false`，见 §5）。
  本仓库上一个会话已经试过：`shell` 工单 `20261029T115358-772d` 返回 **`unsupported`（shell jobs are disabled）**。
* 因此本次用的肽是 **YLSLLQR**（7 aa）——取自你 Drive 里 AChE–PAS 候选肽文档的那条序列，
  也是上一个会话在找 F: 证据时锁定的对象。
* **“YLSLLQR 就是 `F:\0wsh\asd` 最近跑过的那条肽”这句话，本次未验证。** 我不编造。
  一旦拿到 F: 的目录清单（或你给出文件名），把 `method/` 里的肽换掉、重跑 `scripts/build_onepot.py` 即可，
  流水线其余部分不变。

肽的理化量（`0fuye` 的 `cgmd.peptide.describe` 实测）：净电荷 **+0.99**（整数 +1）、pI **9.88**、
GRAVY **0.186**、螺旋疏水矩 **0.616**、两亲性比 **0.75**、M **892.07 Da**。

### 3.2 方法与参数对照

| 环节 | 文档（§9 方法 8 / §12） | 本次实施 |
|------|--------------------------|----------|
| 力场 | “MARTINI 类”，要求报告版本/映射/二级结构约束/蛋白–水修正 | **Martini 3.0.0**（`marrink-lab/martini-forcefields` @ `784591e`），`martinize2`（vermouth 0.15.0）`-ff martini3001 -ss C -ignh -elastic -ef 500 -el 0.5 -eu 0.9 -p backbone`，**18 珠/拷贝**（BB + SC1–SC4） |
| 二级结构约束 | 需披露 | 全链 coil（`-ss C`）+ 弹性网络 Fc = 500 kJ·mol⁻¹·nm⁻²、0.5–0.9 nm 建键；聚集臂**不**开 `-DPOSRES`（约束会把 6 个拷贝钉死，与“看它们自己靠拢”冲突） |
| 蛋白–水修正 | 需披露 | 未施加额外 ε 修正：Martini 3 已重新标定 W 与蛋白珠子 LJ；此项列为**敏感性检查未做**（见 §7） |
| 一锅式体系 | Xu 等：5 seeds + 50 Aβ40 / 22 nm 盒 / 2–5 μs；本项目：20 重复 × 10 μs，浓度 18/22/28 nm | **6 拷贝随机位置 + 随机取向**，两个盒长：**7.5 nm（23.6 mM）** 与 **9.5 nm（11.6 mM）**，即文档浓度扫描的最小两点 |
| 溶剂/盐 | 显式溶剂模型按力场 | Martini `W`（水数密度 9.2 nm⁻³）+ **0.15 M NaCl**，反离子中和净电荷（体系总电荷 0） |
| 积分 | Verlet、rcoulomb = rvdw = 1.1 nm、reaction-field εr 15、`Potential-shift`、nstlist 20 | 完全一致；**dt = 20 fs** |
| 温压 | 310 K；EM → 100 ps NVT → 1 ns NPT → 生产；生产 Parrinello–Rahman τp 12 ps | 完全一致：v-rescale τt 1 ps / c-rescale τp 4 ps 平衡 / P–R τp 12 ps 生产，ref-p 1 bar |
| 轨迹输出 | 1 ns / 帧 | `nstxout-compressed = 50000`（1 ns/帧） |
| 生产时长 | 每条 10 μs（目标） | 本轮为**本地 2 核 CPU 复现**：A 臂 **100 ns**、B 臂 50 ns（换算见 §6） |
| 引擎 | 台式机 GPU（Windows 原生 2025.1 CUDA） | **本轮在沙箱内自建 GROMACS 2025.1-dev（CPU，2 线程）**；原因见 §5 |

### 3.3 体系实测

| | A 臂（高浓度） | B 臂（低浓度） |
|---|---|---|
| 盒长（初始 → NPT 后） | 7.500 → **7.774 nm** | 9.500 → **9.785 nm** |
| 浓度 | 标称 23.6 mM（NPT 后 ≈ 21.0 mM） | 标称 11.6 mM（NPT 后 ≈ 10.6 mM） |
| 珠子数 | **4007**（108 肽 + 3817 W + 38 NA + 44 CL） | **7915**（108 + 7647 W + 77 NA + 83 CL） |
| 净电荷 | 0（+6 肽 / −6 反离子） | 0（+6 / −6） |
| NPT 1 ns 实测 | 309.8 K / 9.28 bar / 7.77325 nm | **309.79 K / 5.92 bar / 9.78473 nm**，ρ 999.8 kg/m³ |
| 生产时长 | 100 ns | 50 ns |

两臂唯一的自变量就是**浓度**（盒长 7.5 → 9.5 nm，其余 mdp / 力场 / 肽映射 / 拷贝数完全相同）。

---

## 4. 结果（两臂全程实测）

| 量 | 值 |
|----|-----|
| EM | steep 489 步收敛，`Fmax < 100`，PE = −1.2336×10⁵ kJ/mol |
| NPT 1 ns | 盒 7.50 → 7.773 nm，T 309.8 K，P 9.3 bar |
| 生产 | **100.0 ns / 5,000,000 步 / 43 min**，`Finished mdrun`，**0 条 LINCS warning**，无 Fatal error |
| 性能 | **3339.7 ns/day**（2 核 CPU；平衡段 3018–3192 ns/day） |
| 生产段统计 | T = **310.00 K**（±0.02），P = **1.22 bar**，密度 **1004 kg/m³**（Martini 数值密度） |
| 肽的回转半径 | **0.66 nm**（0.47–0.87 nm）——18 珠 7 肽的合理尺度 |
| 最大簇（拷贝数） | 均值 **1.61**，峰值 **4**，末帧 2 |
| 簇大小分布 | 单体 481 / 二聚 49 / 三聚 5 / 四聚 3（101 帧 × 全部簇计数） |
| P(最大簇 ≥ 2 / ≥ 3 / ≥ 4) | **0.505 / 0.079 / 0.030** |
| 平均跨肽接触对 | **4.57** 对（峰值 45） |
| 图 | `figures/cluster_vs_time.svg`、`figures/cluster_size_dist.svg` |

**读法（严格按文档的措辞）**：在 21 mM、6 拷贝的 CG 一锅体系里，YLSLLQR 只形成**瞬态二聚体/三聚体**
（半帧有二聚体、8% 的帧出现三聚体、3% 出现四聚体，没有一个持久的大簇）。
这是**相对富集/簇概率层面的机制筛选信号**，不能读成“促聚集/不促聚集”的因果结论，
更不能把 CG 的 ns 当作真实 Aβ fibrillation 时间——文档 §9 明令如此。

### 4.1 B 臂（低浓度 10.6 mM / 50 ns）

| 量 | 值 |
|----|-----|
| 生产 | **50.0 ns / 2,500,000 步 / 43.1 min**，`Finished mdrun`，**0 条 LINCS warning**，无 Fatal |
| 性能 | **1668.97 ns/day**（2 核 CPU；7915 珠，约为 A 臂的一半——珠子数翻倍、接触对 4 倍） |
| 肽的回转半径 | **0.664 nm**（0.475–0.861 nm），与 A 臂一致 → 单肽构象未被盒子放大 |
| 最大簇 | 均值 **1.196**，峰值 **3**，末帧 1 |
| 簇大小分布 | 单体 285 / 二聚 9 / 三聚 1（51 帧） |
| P(最大簇 ≥ 2 / ≥ 3 / ≥ 4) | **0.176 / 0.020 / 0.000** |
| 平均跨肽接触对 | **1.43** 对（峰值 15） |

### 4.2 等时长（0–50 ns）两臂对照 → `results/arm_comparison.json`

为了让对照只反映浓度、不混入时长差异，A 臂另跑了一遍 0–50 ns 窗口
（`results/summary_metrics_A_0_50ns.json`，同一份轨迹）：

| 量 | A 21.0 mM | B 10.6 mM | A/B |
|---|---|---|---|
| P(最大簇 ≥ 2) | 0.510 | 0.176 | **2.9×** |
| P(最大簇 ≥ 3) | 0.137 | 0.020 | **6.9×** |
| P(最大簇 ≥ 4) | 0.039 | 0.000 | —（B 无四聚体） |
| 平均跨肽接触对 | 5.88 | 1.43 | **4.1×** |
| 任一对出现过接触的帧比例 | 0.733 | 0.533 | 1.4× |
| 最大簇峰值 | 4 | 3 | 1.33× |

方向与文献/文档预期一致：**浓度翻倍 → 簇概率和跨肽接触数显著升、且出现更高阶寡聚体**；
但两臂都**没有**出现持久大簇（末帧最大簇分别 2 和 1）。这就是文档所谓“相对筛选信号”：
它能把候选肽按“富集倾向”排序，但不能给出绝对速率或聚集与否的因果结论。

**但这条结论单种子撑不住**：补跑 2 个独立种子后（§4.5），同样 0–30 ns 窗口内的 A/B 差只有 1.4×，
落在种子间涨落里。上面 2.9×/6.9×/4.1× 是**单条轨迹对单条轨迹**的比值，不要把它的量级当真。

---

### 4.3 台式机 GPU 上跑 Martini 3 到底多快（本轮实测，把这条从“未验证”里划掉）

桌面上本来就有一个 **Martini 3 生产输入** `C:\cgmd\0fuye\skills\cgmd-hub\state\cgmd_100ns_prod.tpr`
（`gmx check` 读通；系统名 “CGMD Magainin-2 in POPE:POPG bilayer”，`cgmd_100ns_stage/system.pdb`
共 **9346 珠**，11.7 × 11.7 × 7.3 nm）。用信箱 `gmx` 作业在这个 tpr 上各推 **500 ps**（25000 步 × 0.02 ps）：

| 线程布局 | wall time | `Performance` | 工单 |
|---|---|---|---|
| hub 默认：4 tMPI × 12 OMP（48 线程） | 61 s | **708.2 ns/day** | `20261030T072114-5eb3` |
| **1 tMPI × 12 OMP** | 13 s | **3323.2 ns/day** | `20261030T072342-5db6` |

同一张 A4000、同一个 tpr、同一份 GROMACS，**只改线程布局就差 4.7×**。
原因写在 mdrun 自己的日志里：4 rank 时每 rank 只有约 2300 珠，
`DLB got disabled`、`load imbalance 5.2%`、还要走 `GPU direct communication between MPI ranks`；
1 rank 时 PP 全在 GPU 上、CPU 只做 update/constrain。

> 结论（可直接照做）：桌面端跑 1 万珠级的 Martini 盒子，应显式给
> `-ntmpi 1 -ntomp 12`（并把 `-pin on` 打开），不要用默认的 4×12。
> 上表的 3323 ns/day 就是本轮可证实的“台式机 GPU 跑 Martini 3”的数。

### 4.4 台式机上的结果路径（可直接去这些位置拿文件）

全部是 `DESKTOP-IEUDGS5` 上的绝对路径；能在本仓库 `mailbox/` 里找到副本的也一并标出。

| 内容 | 台式机路径 | 本仓库副本 |
|---|---|---|
| 100 ps 烟测完整报告（本轮 11:31 那次，617.155 ns/day） | `C:\cgmd\0fuye\results\status\gmx_smoke.json` | `mailbox/desktop_gmx_smoke.json` |
| 100 ps 烟测工作目录（第一次 10:07，576.012 ns/day） | `C:\Users\BNI\cgmd-runs\smoke-native-20261030-100759\` | — |
| 100 ps 烟测工作目录（第二次 11:31，617.155 ns/day） | `C:\Users\BNI\cgmd-runs\smoke-native-20261030-113157\` | — |
| 自检报告（18 项 15/3/0） | `C:\cgmd\0fuye\results\status\desktop_selfcheck.json` | — |
| 信箱工作进程状态（`allow_shell=false`、peer 列表、log_tail） | `C:\cgmd\0fuye\results\status\hub_mailbox.json` | `mailbox/desktop_hub_mailbox.json` |
| 心跳（60 s 轮询、`poll_count`） | `C:\cgmd\0fuye\results\status\hub_heartbeat.json` | — |
| 信箱工作树（取件/回执都在这里） | `C:\cgmd\0fuye\skills\cgmd-hub\state\mailbox\` | — |
| 本轮 4 个 `gmx` 作业目录（`check` / `mdrun` ×2 / `grompp`） | `C:\cgmd\0fuye\skills\cgmd-hub\state\gmx-job-20261030-150758`、`-151857`、`-152158`、`-152359`、`-152759` | `mailbox/20261030_20261030T*.json` |
| 既有 Martini 3 生产输入/轨迹（9364 珠膜体系） | `C:\cgmd\0fuye\skills\cgmd-hub\state\cgmd_100ns_prod.tpr`、`cgmd_100ns_prod.xtc` | — |
| GROMACS 安装 | `F:\gromacs-2025.1-SM86\gromacs-2025.1-SM86\`（`bin\gmx.exe`、`share\gromacs\top`） | — |
| hub 配置（`allow_shell`、`peer_repos`、`prune_raw`） | `C:\cgmd\0fuye\skills\cgmd-hub\config\cgmd_hub.local.json` | — |
| Arena Desk 面板 | `C:\0apps\ArenaDesk`（127.0.0.1:18765）、源码 `C:\cgmd\0fuye\code\panel` | — |
| 任务握手文件 | `C:\cgmd\0fuye\results\status\cgmd_task.json` | — |

### 4.5 重复种子（本轮新增：每臂 n = 3，把误差棒补上）

同一套方法、同一盒长、同一拷贝数，只换**放置种子**（`build_onepot.py --seed`）和**速度种子**
（`nvt.mdp` 里 `gen-seed = -1`，每次 grompp/mdrun 都不同），每臂多跑 2 条 **30 ns** 独立轨迹；
原轨迹按同一窗口截取 0–30 ns 一起统计（`scripts/seed_stats.py`，直接从每帧 timeseries 重算）。

图：`figures/repeats_cluster_vs_time.svg`（两臂各 3 个种子，0–30 ns 最大簇随时间）。

| 端点（0–30 ns） | A 21.0 mM：s20261030 / s20261031 / s20261032 | A 均值 ± SD | B 10.6 mM：s20261030 / s20261031 / s20261032 | B 均值 ± SD | A/B |
|---|---|---|---|---|---|
| P(最大簇 ≥ 2) | 0.290 / 0.484 / 0.484 | **0.419 ± 0.112** | 0.226 / 0.290 / 0.387 | **0.301 ± 0.081** | 1.4× |
| P(≥ 3) | 0.129 / 0.097 / 0.065 | **0.097 ± 0.032** | 0.032 / 0.000 / 0.000 | **0.011 ± 0.019** | 8.9× |
| P(≥ 4) | 0.032 / 0.000 / 0.000 | 0.011 ± 0.019 | 0 / 0 / 0 | **0** | — |
| 最大簇均值 | 1.452 / 1.581 / 1.548 | **1.527 ± 0.067** | 1.258 / 1.290 / 1.387 | **1.312 ± 0.067** | 1.16× |
| 最大簇峰值 | 4 / 3 / 3 | 3.33 | 3 / 2 / 2 | 2.33 | 1.4× |
| 平均跨肽接触 | 4.32 / 3.26 / 2.29 | **3.29 ± 1.02** | 2.03 / 1.52 / 2.97 | **2.17 ± 0.74** | 1.5× |
| 肽 Rg (nm) | 0.657 / 0.669 / 0.652 | 0.659 ± 0.009 | 0.665 / 0.641 / 0.653 | 0.653 ± 0.012 | — |

Welch t（n = 3，只作量级判断）：P(≥2) t ≈ 1.5（**不显著**）、P(≥3) t ≈ 4.0、最大簇均值 t ≈ 3.9。
所以正确的说法是：

* **方向仍然一致**：A 臂在每个种子上都比 B 臂更容易出簇（P(≥3)、最大簇均值、接触数都更高）；
* **幅度不能报成 2.9×**：P(≥2) 的 A/B 差（0.12）小于两臂各自的种子间 SD（0.11 / 0.08），
  n = 3、30 ns 的窗口不足以把“浓度效应”从“轨迹涨落”里分出来；
* 要报浓度效应的置信区间，需要文档要求的 n ≥ 5 独立重复 + 更长窗口。

### 4.6 参数敏感性（本轮新增：换掉弹性网络，其余全同）

文档 §9 要求对 CG 参数化/二级结构约束做 1–2 套交叉检查。这里做一套最小但关键的对撞：
**同一肽、同一盒长 7.5 nm、同一放置种子、同一套 mdp，只把 `martinize2` 的 `-elastic` 去掉**
（`scripts/sensitivity.sh`；无弹性网络 = 链更软）：

| 端点（0–30 ns） | A 臂（有弹性网络，3 种子均值） | 无弹性网络（单种子） |
|---|---|---|
| P(最大簇 ≥ 2) | 0.419 ± 0.112 | 0.355 |
| P(≥ 3) | 0.097 ± 0.032 | **0.226** |
| P(≥ 4) | 0.011 ± 0.019 | 0.032 |
| 最大簇均值 | 1.527 ± 0.067 | **1.613** |
| 平均跨肽接触 | 3.29 ± 1.02 | **5.10** |
| 肽 Rg (nm) | 0.659 ± 0.009 | 0.669 |

**这是本轮最该记住的一条**：把弹性网络去掉带来的变化（P(≥3) 0.10 → 0.23、接触 3.3 → 5.1）
**比“浓度翻倍”带来的变化更大**。也就是说，在这么小的体系/这么短的窗口里，
**参数化选择（链刚度）会盖过我们想测量的浓度效应**。文档要求“必须报告二级结构约束与蛋白–水修正”、
并要求跨参数化交叉检查，原因就在这里；任何只跑一套参数就下“这条肽促聚集”的结论，都是不可靠的。

---

## 5. 为什么这一轮 CG 没在台式机 GPU 上跑（证据链，不是猜）

台式机基座本身是好的（§1、§2 全绿），卡住的是**给云端用的那两条通道**：

1. **执行通道**：`shell` 工单被配置关掉（`results/status/hub_mailbox.json` 里 `allow_shell: false`）。
   上一个会话的 `20261029T115358-772d` 就是去列 `F:\0wsh\asd` 的，回执 `status=unsupported`。
2. **文件通道**：本会话 token 对 `hukeying85-ux/0fuye` 只有**读**权限——实测
   `git push --dry-run` → `403 Permission to hukeying85-ux/0fuye.git denied`。
   而对端信箱只把 `inbox/<id>.json` 用 `git show` 读进内存（`Invoke-PeerCycle`），**不落地任何文件**，
   所以没法把 `Protein_0.itp` / `system.gro` / mdp 送过去。
   台式机自己的 `hub/mailbox` 工作区（`C:\cgmd\0fuye\skills\cgmd-hub\state\mailbox`）只有写 0fuye 才够得到。
3. **工具链通道**：即便文件能过去，selfcheck 三项 warn 说明**台式机 WSL 里没有** `martini_v3.0.0.itp`、
   vermouth / insane / MDAnalysis，也没有 `martinize2`/`insane` 可执行文件，且 WSL 的 GROMACS 是 2018.1（CPU）。
   `pipeline` 工单类型本身也还**没有接线**（源码里直接返回 `unsupported`）。
4. **`gmx` 工单虽然能用，但只能“读着跑”，不能“送进去跑”**（本轮实测）：
   `Invoke-JobGmx` 每次都在**新建的空 scratch 目录** `state\gmx-job-<时间戳>` 里执行，argv 只是转发，
   **没有任何参数能把输入文件放进那个目录**；也不会在上一次作业目录之间保留文件。
   所以 `mdrun -s <桌面上已有的 tpr>` 能跑（§4.3 就是这么测出来的），但从零 `grompp` 一个新体系不行。
5. **桌面上的 Martini 输入文件已被清掉**（本轮实测）：`gmx grompp` 指向
   `state\mailbox\cgmd_100ns_stage\{em_long.mdp,system.pdb,topol.top}` 时，三个文件全部
   `does not exist`（`20261030T072726-9c39`，0.32 s 就返回）——config 里 `prune_raw: true`，
   旧作业目录会被裁掉；现在只剩 `cgmd_100ns_prod.tpr/.xtc` 这类成品。

结论：**不是“这台机器不能算”，而是“这台基座目前没给云端一条可写、可执行的通道去投递 CG 流水线”。**
修好任一条（打开 `allow_shell`，或给 0fuye 的 `hub/mailbox` 写权限以投递 `state/mailbox` 下的输入文件，
或把 `pipeline` 工单接上 `cgmd.cli`）之后，本目录的 `method/` + `scripts/` 可以**原样**在台式机原生
GROMACS 2025.1 CUDA 上跑，`run_cg.sh` 只把 `GMX` 换成 `F:\gromacs-2025.1-SM86\...\gmx.exe`、`NP` 换成 GPU 参数。

---

## 5.1 桌面端 `grompp` 的 0xC0000005：已做成可用工具（`scripts/flatten_top.py`）

烟测报告里那条 `grompp-em` 返回码 `-1073741819`（= `0xC0000005`，access violation）不是偶发：
同一份体系换成**把所有参数写进拓扑的内联版**（`smoke_box_inline.top`）后，`grompp-em-inline` 立刻 `0`。
也就是说，这台机器上的 `F:\gromacs-2025.1-SM86` 版本在**拓扑需要 `#include` 外部文件**时会崩。

Martini 3 恰好就是这种拓扑（`topol.top` 要 include `martini_v3.0.0.itp` + `_solvents_v1` + `_ions_v1` + `Protein_0.itp`）。
所以本仓库给了 `scripts/flatten_top.py`：把 `#include` 递归展开成**单文件拓扑**，其余指令（含
`Protein_0.itp` 里的 `#ifdef POSRES` / `#ifdef FLEXIBLE`）原样保留，同一路径只内联一次。

本轮在沙箱上验证过它不改变物理：

| 步骤 | 结果 |
|---|---|
| `flatten_top.py sys/topol.top topol_flat.top` | 5 个文件内联，357,955 行，**0 个 `#include` 残留** |
| `grompp -f em.mdp -c system.gro -p topol.top` | 成功，`em_orig.tpr` 58,824 B |
| `grompp` 同上但 `-p topol_flat.top` | 成功，`em_flat.tpr` **58,824 B**（同样大小） |
| `gmx dump -s` 两份 tpr 逐行对比 | 10,790 行里**只有 4 行不同**：输出文件名、以及 grompp 每次随机的 `ld-seed` |

结论：展平只是“换了个写法”，不是“换了个物理模型”。等桌面端有文件投递能力那天，
`flatten_top.py` 是绕开 0xC0000005 的第一道工序。

---

## 6. 时间预算换算（把本轮结果挪到台式机 GPU 上是什么量级）

* 本轮 CPU 实测三档：4007 珠 **3339.7 ns/day**（100 ns，同时跑分析、抢了 CPU）；
  同体系干净复跑 4007 珠 **6421.7 / 6145.6 ns/day**（30 ns ×2）；7915 珠 **1669.0 ns/day**（B 臂 50 ns）。
  即珠子数约翻倍、性能约减半——CG 成本几乎线性于体系大小。
* 台式机 100 ps 全原子烟测 **576.0 / 617.2 ns/day**（1530 原子、GPU）；**CG 与全原子不可直接比**。
* 台式机 GPU 跑 **Martini 3**（9346 珠膜体系）本轮实测 **3323.2 ns/day**（1 tMPI × 12 OMP，§4.3）
  → 1 μs ≈ 7.2 h；用 hub 默认 4×12 布局只有 708.2 ns/day（1 μs ≈ 34 h）。
  **所以“把 4007 珠的 A 臂挪到台式机 GPU”并不会更快**：沙箱这两颗核心的干净复跑已经是 6421 ns/day，
  桌面 GPU 在这个体系规模上并不占优（GPU 的优势要等体系到 10 万珠级以上）。
* 文档要求的“20 重复 × 10 μs × 3 浓度”在 2 核 CPU 上是不现实的（≈ 数千 CPU·天）；
  这也是为什么它必须回到台式机 GPU，或者缩到本轮这种“单点 + 短窗口”的筛选级复刻。

## 7. 未验证 / 未完成（逐条列出，不当结论用）

| # | 项目 | 本轮状态 | 说明 |
|---|---|---|---|
| 1 | `F:\0wsh\asd` 里最近跑过的肽是不是 YLSLLQR | **仍未验证** | 见 §7.1：没有任何可用的目录读取能力 |
| 2 | 台式机 GPU 跑 Martini 3 的 ns/day | ✅ **本轮实测** | 9346 珠膜体系：1 tMPI×12 OMP **3323.2 ns/day**；hub 默认 4×12 只有 **708.2**（§4.3） |
| 3 | 独立重复次数 | 部分完成：**每臂 n = 3** | 文档要求 n ≥ 5；n=3 只够看出“幅度不可报”（§4.5） |
| 4 | CG 参数敏感性交叉检查 | 部分完成：**1 套** | 弹性网络开/关（§4.6）；第二套（不同二级结构约束、蛋白–水 ε 修正）仍未做 |
| 5 | β 含量 / DSSP | 不适用 | Martini 珠子没有氢键；端点用簇/接触/Rg |
| 6 | 种子表面积扫描（10/20/40 nm²） | 未做 | 没有 seed 模型，Aβ 结构也未提供 |
| 7 | 在桌面上**从零重建**我这套体系 | **做不到**（本轮实测） | `gmx` 工单每次在空 scratch 目录执行、无文件投递；旧的 stage 目录已被 `prune_raw` 清掉（§5 第 4、5 条） |

### 7.1 为什么第 1 条这一轮还是关不掉（以及本轮新拿到的线索）

* **没有目录枚举能力**：`allow_shell=false`（现网状态，`mailbox/desktop_hub_mailbox.json`）；
  `gmx` 工单只转发 argv、每次新 scratch 目录（`state\gmx-job-<时间戳>`），
  `gmx check/grompp/mdrun/dump/gyrate…` 都只能对**已知路径**的文件操作，没有 `dir/ls`；
  对端信箱只 `git show` 到内存、不落地文件；Arena token 对 `0fuye` 无写权限（403）。
* **本轮新线索**：桌面上确实有一份**跑完的 Martini 3 肽 MD**——
  `C:\cgmd\0fuye\skills\cgmd-hub\state\cgmd_100ns_prod.tpr`（系统名
  “CGMD Magainin-2 in POPE:POPG bilayer”，9346 珠，11.7×11.7×7.3 nm，100 ns 成品的 tpr+xtc 都在）。
  它的分析产物（`gyrate.xvg` 401 帧、`box.xvg` 21 帧）说明肽 Rg 从 1.071 nm 走到 1.061 nm、
  盒从 11.67×11.67×7.39 稳定到 11.74×11.74×7.29 nm —— 即**台式机最近可证的一次肽 CG MD 是 magainin-2，
  不是 YLSLLQR**。这与“`F:\0wsh\asd` 最近跑过 YLSLLQR”这个前提**不一致**，需要用户确认到底是哪一条肽；
  本轮仍然把 YLSLLQR 作为复刻对象（因为它才是方案文档里与 Aβ/AChE-PAS 机制相关的候选），
  但**不宣称它等于 F: 目录里那条**。

## 8. 复现

```bash
# 0) 取 Martini 3 力场（不入库）
git clone https://github.com/marrink-lab/martini-forcefields
cp martini-forcefields/martini_forcefields/regular/v3.0.0/gmx_files/martini_v3.0.0*.itp <workdir>/

# 1) 粗粒化（vermouth 0.15.0）
martinize2 -f method/peptide/peptide_atomistic.pdb -x peptide_cg.pdb -o peptide.top \
  -name Protein -ff martini3001 -ss C -ignh -elastic -ef 500 -el 0.5 -eu 0.9 -p backbone -maxwarn 1

# 2) 建一锅体系（随机位置+取向；W + 0.15 M NaCl；中和）
python3 scripts/build_onepot.py --cg peptide_cg.pdb --box 7.5 --copies 6 --seed 20261030 --out sys

# 3) EM -> 100 ps NVT -> 1 ns NPT -> 生产（生产段长由第一个参数给，单位 ns）
bash scripts/run_cg.sh 100

# 4) 端点（--stride 1 = 全帧；--tmax-ns 截等时长窗口做两臂对照）
python3 scripts/analyze_cg.py --gro npt.gro --xtc prod.part0001.xtc --copies 6 --beads 18 \
  --stride 1 --out summary_metrics_A.json
python3 scripts/analyze_cg.py --gro npt.gro --xtc prod.part0001.xtc --copies 6 --beads 18 \
  --stride 1 --tmax-ns 50 --out summary_metrics_A_0_50ns.json
python3 scripts/collect_metrics.py --dir . --out run_A.json

# 4b) 独立重复（新放置种子；速度种子由 nvt.mdp 的 gen-seed = -1 自动不同）
bash scripts/run_seeds.sh A 7.5 30 20261031 20261032
bash scripts/run_seeds.sh B 9.5 30 20261031 20261032
python3 scripts/seed_stats.py --window 30 --labels s20261030,s20261031,s20261032 \
  results/summary_metrics_A.json results/summary_metrics_A_seed20261031.json \
  results/summary_metrics_A_seed20261032.json --out repeats_A_30ns.json

# 4c) 参数敏感性：去掉弹性网络，其余全同
bash scripts/sensitivity.sh

# 4d) 桌面端 grompp 的 0xC0000005 绕法（拓扑展平，物理不变）
python3 scripts/flatten_top.py sys/topol.top sys/topol_flat.top

# 5) 两臂对照 + 图
python3 scripts/compare_arms.py --a results/summary_metrics_A_0_50ns.json \
  --b results/summary_metrics_B.json --conc-a 21.0 --conc-b 10.6 \
  --box-a 7.774 --box-b 9.785 --label-a A_21mM --label-b B_10.6mM --out arm_comparison.json
python3 scripts/make_figures.py --a results/summary_metrics_A.json \
  --b results/summary_metrics_B.json --labels "A 21 mM (100 ns),B 10.6 mM (50 ns)" --outdir figures
```

## 9. 目录

```
cgmd_endtoend/
├── README.md                       ← 本文
├── method/
│   ├── provenance.md               ← 版本/命令/sha256 溯源
│   ├── mdp/{em,nvt,npt,prod}.mdp   ← Martini 3 四段参数（与文档 §12 对齐）
│   └── peptide/{peptide_atomistic.pdb, peptide_cg.pdb, Protein_0.itp}
├── scripts/
│   ├── build_onepot.py / analyze_cg.py / collect_metrics.py / run_cg.sh
│   ├── compare_arms.py / make_figures.py
│   ├── run_seeds.sh / seed_stats.py / sensitivity.sh   ← 第二轮：重复种子 + 敏感性
│   └── flatten_top.py                                  ← 桌面端 grompp 0xC0000005 的绕法
├── results/
│   ├── summary_metrics_A.json          ← A 臂 0–100 ns
│   ├── summary_metrics_A_0_50ns.json   ← A 臂 0–50 ns（等时长对照用）
│   ├── summary_metrics_B.json          ← B 臂 0–50 ns
│   ├── summary_metrics_{A,B}_seed2026*.json  ← 每臂另外 2 个独立种子（30 ns）
│   ├── summary_metrics_sensitivity_noelastic.json ← 无弹性网络变体
│   ├── repeats_A_30ns.json / repeats_B_30ns.json  ← n=3 的 mean/SD（0–30 ns 同窗口）
│   ├── run_A.json / run_B.json         ← 各段步数/耗时/ns·day⁻¹/LINCS 计数
│   └── arm_comparison.json             ← 两臂 8 个端点的比值
├── figures/{cluster_vs_time.svg, cluster_size_dist.svg, repeats_cluster_vs_time.svg}
└── mailbox/
    ├── 20261030T0204*/0206*/0214*      ← ping / 100 ps 烟测 / selfcheck 原始回执
    ├── desktop_gmx_smoke.json          ← 台式机自己的烟测报告（11:31 那次，617.155 ns/day）
    ├── desktop_hub_mailbox.json        ← 台式机信箱现网状态（allow_shell=false、peer 列表、log_tail）
    └── 20261030_20261030T07*.json      ← 第二轮 4 个 gmx 作业回执（check / mdrun×2 / grompp）
```

Git 卫生：`.xtc/.trr/.tpr/.cpt/.gro/.edr` 一律没有入库；力场 itp 按第三方许可也未入库。
