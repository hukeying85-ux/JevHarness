# CGMD 端到端验收 + 粗粒化（Martini 3）复刻

> 会话：Arena `arena/03860148-jevharness` · 台式机：`DESKTOP-IEUDGS5`（Windows 10 + RTX A4000 16 GB + 原生 GROMACS 2025.1 CUDA，`F:\gromacs-2025.1-SM86`）
> 全部动作经 git 信箱总线（`hub/mailbox`）+ Arena 侧自行构建的 Linux 环境完成，没有任何一步需要人在台式机上敲命令。
> 本文所有数字都是本次实测，未实测的一律写“未验证”。

---

## 1. 验收表

| 项目 | 实测值 | 证据 |
|------|--------|------|
| 主机 | `DESKTOP-IEUDGS5`，用户 `BNI`，48 核 | ping `20261030T020458-3bc6` |
| 值守心跳 | 信箱工作进程 `state=ran`，`generated_at 2026-10-30T10:15:30+08:00`；`CGMD-Hub-Poll` 计划任务 10:14:14 运行、结果 0；`results/status/hub_heartbeat.json` 最后写入 09:36:58（间隔配置 60 s，`poll_count=24`，`state=idle`） | `results/status/hub_mailbox.json`、selfcheck 的 `task` 项 |
| GPU | `NVIDIA RTX A4000`，驱动 596.71，16376 MiB，1 张；`gmx` 报告 GPU support **CUDA** | ping + smoke |
| GROMACS | **2025.1** 原生 Windows：`F:\gromacs-2025.1-SM86\gromacs-2025.1-SM86\bin\gmx.exe`；WSL 侧另有 2018.1（CPU，未使用） | ping、selfcheck |
| 本次 ping | 工单 `20261030T020458-3bc6`，**端到端 79 s**（其中约 61 s 是 60 s 轮询等待，工单本身 **0.43 s**），`status=ok` | `mailbox/smoke…` 同目录 |
| 本次 100 ps 烟测 | 工单 `20261030T020623-6973`，工单耗时 **28.54 s**（端到端 123 s），**576.012 ns/day**，`status=ok` | `mailbox/smoke_20261030T020623-6973.json` |
| 自检 | 工单 `20261030T021444-ab6b`：18 项 **15 pass / 3 warn / 0 fail**，`overall=warn`，24.7 s | `mailbox/selfcheck_20261030T021444-ab6b.json` |

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

单种子、单轨迹 → **没有误差棒**，上述倍数只作方向性参考（见 §7）。

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

结论：**不是“这台机器不能算”，而是“这台基座目前没给云端一条可写、可执行的通道去投递 CG 流水线”。**
修好任一条（打开 `allow_shell`，或给 0fuye 的 `hub/mailbox` 写权限以投递 `state/mailbox` 下的输入文件，
或把 `pipeline` 工单接上 `cgmd.cli`）之后，本目录的 `method/` + `scripts/` 可以**原样**在台式机原生
GROMACS 2025.1 CUDA 上跑，`run_cg.sh` 只把 `GMX` 换成 `F:\gromacs-2025.1-SM86\...\gmx.exe`、`NP` 换成 GPU 参数。

---

## 6. 时间预算换算（把本轮结果挪到台式机 GPU 上是什么量级）

* 本轮 CPU 实测两档：4007 珠 → **3339.7 ns/day**（1 μs ≈ 7.2 h）；7915 珠 → **1669.0 ns/day**（1 μs ≈ 14.4 h）。
  即珠子数翻倍、性能掉一半——CG 成本几乎线性于体系大小，这也是文档要把大体系放到 GPU 的原因。
* 台式机 100 ps 全原子烟测是 576 ns/day（1530 原子、GPU），**CG 与全原子不可直接比**；
  Martini 3 体系在 A4000 上的实际 ns/day 本轮**未实测**（没有通道投递，不做数字推测）。
* 文档要求的“20 重复 × 10 μs × 3 浓度”在 2 核 CPU 上是不现实的（≈ 数千 CPU·天）；
  这也是为什么它必须回到台式机 GPU，或者缩到本轮这种“单点 + 短窗口”的筛选级复刻。

## 7. 未验证 / 未完成（逐条列出，不当结论用）

1. **YLSLLQR 是否就是 `F:\0wsh\asd` 最近跑过的那条肽** —— 未验证（拿不到 F: 清单）。
2. **台式机 GPU 上跑 Martini 3 的 ns/day** —— 未实测（无投递通道）。
3. **重复次数**：文档要求 n ≥ 3 独立种子；本轮每臂 1 条轨迹（A 21 mM / 100 ns，B 10.6 mM / 50 ns）→ 只能报**相对趋势**，不能报误差棒；
   两臂的 A/B 倍数（2.9×、6.9×、4.1×）在单种子下完全可能被轨迹间涨落吞掉，必须补种子才谈得上显著性。
4. **参数敏感性**：文档要求 1–2 套 CG 参数化/二级结构约束交叉检查（含蛋白–水修正项）；本轮只跑了标准 Martini 3 一套。
5. **β 含量 / 二级结构**：CG 珠子没有氢键，DSSP 无法用；本轮只用簇统计与 Rg 作为端点（文档 §9 的 CG 端点本来也是簇/接触类）。
6. **种子表面积扫描（10/20/40 nm²）**：没有 seed 模型，未做。

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
├── scripts/{build_onepot.py, analyze_cg.py, collect_metrics.py, compare_arms.py, make_figures.py, run_cg.sh}
├── results/
│   ├── summary_metrics_A.json          ← A 臂 0–100 ns
│   ├── summary_metrics_A_0_50ns.json   ← A 臂 0–50 ns（等时长对照用）
│   ├── summary_metrics_B.json          ← B 臂 0–50 ns
│   ├── run_A.json / run_B.json         ← 各段步数/耗时/ns·day⁻¹/LINCS 计数
│   └── arm_comparison.json             ← 两臂 8 个端点的比值
├── figures/{cluster_vs_time.svg, cluster_size_dist.svg}
└── mailbox/20261030T0204*/0206*/0214*  ← ping / 100 ps 烟测 / selfcheck 原始回执
```

Git 卫生：`.xtc/.trr/.tpr/.cpt/.gro/.edr` 一律没有入库；力场 itp 按第三方许可也未入库。
