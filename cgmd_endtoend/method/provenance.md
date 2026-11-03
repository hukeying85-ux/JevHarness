# 粗粒化（Martini 3）体系的可复现溯源

本目录里的每个文件都能用下面这些**固定版本 + 固定命令**重新生成。所有中间产物
（`.gro / .xtc / .tpr / .edr / .cpt`）都不进 Git，只保留生成它们的脚本与文本拓扑。

## 1. 版本清单（实测）

| 组件 | 版本 | 来源 |
|------|------|------|
| Martini 3 力场 | **3.0.0**（`martini_v3.0.0.itp`，文件内标注 `Version: 3.0.0`，2021-03-29） | `github.com/marrink-lab/martini-forcefields`，commit `784591e`（2023-02-07） |
| 粗粒化工具 | **vermouth 0.15.0**（`martinize2`） | PyPI |
| GROMACS | **2025.1-dev**（CPU-only，`-DGMX_GPU=OFF -DGMX_FFT_LIBRARY=fftpack`，2 OpenMP 线程） | `codeload.github.com/gromacs/gromacs` tag `v2025.1` 源码自建 |
| 分析 | MDAnalysis 2.11.0 / numpy 2.4.6 | PyPI |
| 台式机上的 GROMACS | 2025.1 原生 Windows CUDA（`F:\gromacs-2025.1-SM86`） | 见 `results/` 里的烟测回执 |

> 说明：力场文件按文档“Martini 3 力场不入库（第三方许可）”的要求**没有**提交；
> 用 `git clone https://github.com/marrink-lab/martini-forcefields` 取
> `martini_forcefields/regular/v3.0.0/gmx_files/martini_v3.0.0*.itp` 与本目录
> 的 `Protein_0.itp` 放在同一目录即可复算。

## 2. 肽与映射

* 序列 **YLSLLQR**（7 aa，+1：N 端 Q5 `+1`、C 端 Q5 `-1`、Arg SQ3p `+1`）
  —— 序列取自本项目 Drive 文档中的 AChE–PAS 候选肽，**不是**从
  `F:\0wsh\asd` 现场读到的（见根 `README.md` 的“肽来源”一节）。
* 全原子结构：`0fuye` 仓库的 `code/cgmd/cgmd/seq2pdb.py`（NeRF 内坐标，理想伸展链，
  `-ss C`），62 个重原子，无 < 1.0 Å 碰撞 → `method/peptide/peptide_atomistic.pdb`
* 粗粒化：

```bash
martinize2 \
  -f peptide_atomistic.pdb -x peptide_cg.pdb -o peptide.top \
  -name Protein -ff martini3001 -ss C -ignh \
  -elastic -ef 500 -el 0.5 -eu 0.9 -p backbone -maxwarn 1
# -> 18 个 Martini 3 珠子 / 拷贝（BB + SC1..SC4），Protein_0.itp + peptide_cg.pdb
```

  * `-ss C`：全链按 coil 处理（无序肽的安全值），弹性网络 `Fc = 500 kJ mol⁻¹ nm⁻²`、
    建键区间 0.5–0.9 nm —— 这两项就是文档要求的“二级结构约束”披露项；
  * `-p backbone` 会把主链位置约束写进 `Protein_0.itp`（`#ifdef POSRES`）。
    本次一体化聚集模拟**没有**开 `-DPOSRES`：约束会把 6 个拷贝钉在原位，
    与“看它们自己靠拢”的目的冲突。膜插入方案（文档 §7–§9）才需要它。

## 3. 体系构建（不需要 GROMACS）

`scripts/build_onepot.py`：把 N 个拷贝按**随机位置 + 随机取向**放进立方盒，
按 Martini 3 水数密度 9.2 nm⁻³ 铺 `W`，把远离肽的水珠改成 `NA`/`CL` 达到
0.15 M NaCl 并中和净电荷，输出 `system.gro` + `topol.top`。

```bash
python3 build_onepot.py --cg peptide_cg.pdb --box 7.5 --copies 6 --seed 20261030 --out sys
# 6 拷贝 / 7.5 nm / 23.6 mM / 3817 W / 38 NA + 44 CL / 4007 珠子
```

## 4. 模拟（4 段，与文档 §7–§9 同序）

| 段 | mdp | 关键参数 | 实测 |
|----|-----|----------|------|
| EM | `em.mdp` | steep, emtol 100, 20000 步 | 489 步收敛，Fmax < 100，PE = −1.2336×10⁵ kJ/mol |
| NVT 100 ps | `nvt.mdp` | v-rescale 310 K, dt 20 fs, 5000 步 | 见 `results/run_report.json` |
| NPT 1 ns | `npt.mdp` | c-rescale, τp 4 ps, 1 bar, 50000 步 | 盒长 7.50 → 7.773 nm，T 309.8 K，P 9.3 bar |
| 生产 | `prod.mdp` | Parrinello–Rahman τp 12 ps，1 ns/帧 | 见 `results/` |

### 本轮实际跑完的两条轨迹

| 轨迹 | 体系 | 生产 | 性能 | 结束状态 |
|------|------|------|------|----------|
| A（高浓度） | 7.774 nm / 4007 珠 / 21.0 mM | 5 000 000 步 = **100.0 ns** | **3339.694 ns/day** | `Finished mdrun`，0 LINCS，无 Fatal |
| B（低浓度） | 9.785 nm / 7915 珠 / 10.6 mM | 2 500 000 步 = **50.0 ns** | **1668.971 ns/day** | `Finished mdrun`，0 LINCS，无 Fatal |

两臂都用 `prod50.mdp`/`prod_100ns.mdp` 的同一套非键参数（Verlet、RF εr 15、1.1 nm），
差别只有盒长；B 臂的 `prod` 段在 2 核上耗时 43.1 min（A 臂 100 ns 也是 43 min，
因为 B 的珠子数是 A 的 1.97 倍、步数只有一半）。

统一参数（文档 §12）：Verlet 邻区、`reaction-field` εr = 15、rcoulomb = rvdw = 1.1 nm、
`cutoff` + `Potential-shift`、nstlist 20、dt 20 fs。

## 5. 第二轮补充（同日）：重复种子、敏感性、桌面端基准

| 内容 | 输入 | 命令 | 实测 |
|---|---|---|---|
| A 臂独立种子 | 7.5 nm / 6 拷贝 / seed 20261031、20261032 | `bash scripts/run_seeds.sh A 7.5 30 20261031 20261032` | 各 30 ns，**6421.7 / 6145.6 ns/day**（干净 2 线程） |
| B 臂独立种子 | 9.5 nm / 6 拷贝 / seed 20261031、20261032 | `bash scripts/run_seeds.sh B 9.5 30 20261031 20261032` | 各 30 ns，**3540.1 / 3517.8 ns/day** |
| 敏感性变体 | 同一肽，`martinize2` **不加 `-elastic`**（18 珠不变） | `bash scripts/sensitivity.sh` | 30 ns，6335.3 ns/day |
| 桌面端 Martini 基准 | 桌面既有 `cgmd_100ns_prod.tpr`（9346 珠膜体系） | 信箱 `gmx` 工单 `20261030T072114-5eb3` / `20261030T072342-5db6` | 500 ps：4×12 → **708.2**；1×12 → **3323.2** ns/day |

> 说明：第一轮 A 臂 100 ns 记录到 3339.7 ns/day、B 臂 50 ns 记录到 1669.0 ns/day，
> 这两次都在**同时跑分析脚本**（2 核机上另一个 CPU 密集进程）的情况下测得；
> 第二轮干净复跑分别是 ~6400 与 ~3500 ns/day，约快 1.9–2.1×。以后报性能请用干净数。
