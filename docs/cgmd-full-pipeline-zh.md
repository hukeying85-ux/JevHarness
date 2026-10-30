# 零手动操作（解放双手）执行 Martini 3 粗粒化动力学完整 12 步流程方案

> 目标：**不在台式机 `DESKTOP-IEUDGS5` 上敲一行命令、不建第二套底座、轨迹文件绝不进 Git**，直接跑通从抗菌肽（AMP）序列输入到 GPU 生产动力学、轨迹分析与矢量出图的完整 12 步流程。

---

## 一、实测摸底：为什么当前直接发 `--kind pipeline` 会停住（共定位 6 个根因）

我们对 `0fuye@arena/32cd826e-0fuye` 的底座脚本及 `code/cgmd` 全链路做了逐行审查与真实 `vermouth (martinize2) + insane + marrink-lab/martini-forcefields` 实测（Magainin-2：`GIGKFLHSAKKFGKAFVGEIMNS`，`POPE:POPG=3:1`，`9,353` 个粗粒化珠子），共定位到 **2 个底座路由断点 + 4 个建模代码实测 Bug**：

| # | 位置 | 实测现象 / 断点 | 零手动修复方案 |
|---|---|---|---|
| 1 | `0fuye/skills/cgmd-hub/runner/Invoke-CgmdMailbox.ps1:1181` | `'pipeline'` 分支当前硬编码返回 `status = 'unsupported'`（`the Martini pipeline job kind is not wired yet`） | 在 `Invoke-CgmdMailbox.ps1` 中补齐 `Invoke-JobPipeline`，直接调用台式机已有的 **Windows 原生 Python 3.12 + Windows 原生 CUDA `gmx.exe` 2025.1** |
| 2 | `0fuye/skills/cgmd-hub/runner/Invoke-CgmdPoll.ps1:770` | `cgmd_task.json` 旧入口仍走 `wsl.exe -d Ubuntu-18.04`（仅 EOL Python `3.6.9` + 纯 CPU `gmx 2018.1`） | 弃用 WSL 路径，统一走台式机现成的 `C:\Users\BNI\AppData\Local\Programs\Python\Python312\python.exe` + `F:\gromacs-2025.1-SM86\...\gmx.exe`（RTX A4000 16GB） |
| 3 | `0fuye/code/cgmd/setup_env.sh` & `config.py` | 写了 `pip install martini-forcefields`，但 PyPI 上**不存在**该包 | 自动浅克隆官方仓库 `https://github.com/marrink-lab/martini-forcefields.git`，指向 `martini_forcefields/regular/v3.0.0/gmx_files` |
| 4 | `0fuye/code/cgmd/cgmd/pipeline.py:237` | 向 `martinize2` 传 `-ff-dir .../vermouth_files` 触发 `vermouth 0.14.0` 解析崩溃（`section '[]' is unknown`） | 不传外部 `vermouth_files`，直接使用 `vermouth` 内置 `martini3001` |
| 5 | `0fuye/code/cgmd/cgmd/pipeline.py:230` | `-ss H` 单字符与残基长度不一致，且未固定 `cwd=workdir` 导致 `Protein_0.itp` 写到进程当前目录而使 `topology.py` 找不到肽拓扑 | 将二级结构展开为 `"H" * len(seq)`，并以 `cwd=workdir` 运行 `martinize2` |
| 6 | `0fuye/code/cgmd/cgmd/topology.py` + Windows `gmx.exe` | 跨盘符（`C:\` vs `F:\`）或深层相对路径 `#include` 易触发 Windows `gmx grompp` `0xC0000005` | 将引用的 `martini_v3.0.0*.itp` 与 `Protein_0.itp` 平铺复制到 `workdir` 同目录，改写为 `#include "martini_v3.0.0.itp"` |

---

## 二、为什么全程无需你在台式机敲任何命令？

`DESKTOP-IEUDGS5` 上**已经在后台每 60 秒自动运行 `CGMD-Hub-Poll`**，每次轮询都会自动把 `C:\cgmd\0fuye` 同步到 `origin/arena/32cd826e-0fuye` 最新提交，并且机器上已经装好：
- **GPU 与 GROMACS**：`NVIDIA RTX A4000 (16 GB)` + `F:\gromacs-2025.1-SM86\gromacs-2025.1-SM86\bin\gmx.exe`（CUDA 12.8 原生 GPU 版，实测水盒 540–617 ns/day，Martini 3 粗粒化 20 fs 步长可达 ~1,000+ ns/day）
- **Windows 原生 Python 3.12**：`C:\Users\BNI\AppData\Local\Programs\Python\Python312\python.exe`

因此：
1. **在 `0fuye` 会话里让 Agent 提交补丁** → **60 秒内台式机自动 `git pull` 自升级** → **脚本首次执行 `pipeline` 时自动在 `C:\cgmd\0fuye\skills\cgmd-hub\state\py312-cgmd` 建好独立虚拟环境并装好 `vermouth / insane / MDAnalysis / matplotlib / martini-forcefields`** → **直接跑完整 12 步 GPU 动力学并把 `< 1 MB` 的 `summary_metrics.json` + 4 张 `.svg` 回传到 GitHub**！
2. 全程你**不需要打开 PowerShell、不需要远程桌面、不需要手动装任何包**。

---

## 三、`JevHarness` 已内置的一键客户端能力（本分支已实装并通过实测）

在 `JevHarness` 中新增了 `auto_jev/cgmd_pipeline.py` 并集成进 `python3 -m auto_jev.cgmd_desk`（及 `jev-cgmd-desk` CLI）：

1. **序列上机前理化预筛（避免无效烧 GPU）**：
   ```bash
   python3 -m auto_jev.cgmd_desk screen \
     --name magainin2 \
     --sequence GIGKFLHSAKKFGKAFVGEIMNS \
     --ss H
   ```
   输出电荷（`+3.03 e`）、等电点（`10.58`）、`<µH>_helix`（`0.686`）、两亲面比例（`0.714`）及推荐档位（`full_production_1000ns` / `fast_screen_100ns` / `reject_before_gpu`）。

2. **Stage 1–6 无缺陷自包含体系构建与原子数一致性校验**：
   ```bash
   python3 -m auto_jev.cgmd_desk prepare-system \
     --workdir /tmp/cgmd_magainin2 \
     --name magainin2 \
     --sequence GIGKFLHSAKKFGKAFVGEIMNS \
     --eq-ns 20 --prod-ns 1000
   ```
   自动完成全原子螺旋 → `martinize2` 粗粒化（`54` 珠子） → `insane` 细菌内膜组装（`POPE:POPG=3:1` + `0.15 M NaCl`） → 平铺 `.itp` 拓扑重写 → 校验 `gro_atoms == topology_atoms`（差值为 `0`） → 生成 `index.ndx` 与 `em/eq/prod.mdp`。

3. **一键投递完整 12 步动力学任务到 `DESKTOP-IEUDGS5`**：
   ```bash
   python3 -m auto_jev.cgmd_desk submit-pipeline \
     --name magainin2 \
     --sequence GIGKFLHSAKKFGKAFVGEIMNS \
     --eq-ns 5 --prod-ns 20
   ```

---

## 四、一步打通 `0fuye` 底座 `pipeline` 原生 GPU 执行（复制给 `0fuye` 会话即可全自动完成）

因为 Arena 单仓库 Token 权限隔离（`JevHarness` 会话不能向 `0fuye` 推送代码），你只需在 **`hukeying85-ux/0fuye`（分支 `arena/32cd826e-0fuye`）** 会话里发下面这一段话，Agent 会自动打补丁、等台式机 60 秒自更新，并直接跑完一次真实 GPU 完整 12 步粗粒化动力学闭环：

```text
全程你来操作，我不在台式机敲任何命令。请严格在 arena/32cd826e-0fuye 分支完成底座自升级并实跑一次完整 12 步 Martini 3 粗粒化动力学闭环：

1. 修复 code/cgmd 的 4 个实测问题（保持纯 ASCII / 现有测试全绿）：
   - martini-forcefields 不在 PyPI：支持自动浅克隆 https://github.com/marrink-lab/martini-forcefields.git 并定位 martini_forcefields/regular/v3.0.0/gmx_files（同时支持 CGMD_MARTINI3_DIR）。
   - pipeline.py 调用 martinize2 时：不要传外部 vermouth_files 的 -ff-dir/-map-dir（直接用 vermouth 内置 martini3001，避免 section '[]' 解析报错）；将单字符二级结构展开为 len(sequence) 长度（如 "H" * len(seq)）；在 engine.run 支持并传入 cwd=self.cfg.workdir，确保 Protein_0.itp 落在 workdir。
   - topology.py 生成 topol.top 时：把引用的 martini_v3.0.0*.itp 复制到 workdir 同目录并写成平铺 #include "martini_v3.0.0.itp"，彻底规避 Windows 跨盘符 relpath 与 gmx grompp 2025.1 深路径 0xC0000005。
   - engine.py 在 Windows 下优先识别 F:\gromacs-2025.1-SM86\gromacs-2025.1-SM86\bin\gmx.exe（及 CGMD_GMX_BIN）。

2. 在 skills/cgmd-hub/runner/Invoke-CgmdMailbox.ps1 中把 'pipeline' 任务真正接通到 Windows 原生硬件（严禁走 WSL Ubuntu-18.04，严禁非 ASCII 字符，遵守 PowerShell 5.1 语法）：
   - 自动复用台式机已有的 C:\Users\BNI\AppData\Local\Programs\Python\Python312\python.exe，在 skills\cgmd-hub\state\py312-cgmd 下首次自动建立 venv 并静默安装 vermouth、insane、MDAnalysis、matplotlib，以及缓存浅克隆 marrink-lab/martini-forcefields。
   - 在 F:\cgmd_runs\<job_id>（如 F: 不存在则回退本地 scratch 目录，绝不进 Git）执行完整 12 步流程：seq2pdb -> martinize2 -> insane (POPE:POPG=3:1) -> topol.top/index.ndx -> gmx.exe EM -> NPT POSRES 平衡 -> RTX A4000 GPU 生产跑 (-nb gpu -pme cpu -bonded gpu -gpu_id 0) -> MDAnalysis 轨迹分析 -> 生成 SVG 矢量图与 summary_metrics.json。
   - 将 < 1 MB 的 summary_metrics.json 与 figures/*.svg 写入 results/runs/<job_id>/（严禁提交 .xtc/.trr/.tpr/.gro/.edr/.cpt），并在 outbox/<job_id>.json 返回关键指标摘要（z_distance_mean_nm、pore_formed、lipid_order、ns_per_day）。

3. 推送到 origin/arena/32cd826e-0fuye 后，等待 <= 90 秒让 CGMD-Hub-Poll 自动拉取新脚本，然后直接通过 core.hub_mailbox 投递一个真实完整流程验证任务（Magainin-2: GIGKFLHSAKKFGKAFVGEIMNS，equilibration_ns=0.5，production_ns=2.0，POPE:POPG=3:1），轮询拿到真实 RTX A4000 GPU 跑出的 summary_metrics.json 与 4 张 SVG 图后向我汇报实测指标。
```
