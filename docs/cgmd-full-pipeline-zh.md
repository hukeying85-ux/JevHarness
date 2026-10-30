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

## 四、新开对话直接粘贴的提示词（不依赖旧会话分支，测试 100 ns 自动化粗粒化分子动力学）

### 提示词 1（在 `hukeying85-ux/0fuye` **新开对话**粘贴：打通基座 + 实跑 100 ns 自动化粗粒化动力学）

```text
全程你来操作，我不在台式机敲任何命令。这是一个全新的对话，请只在你当前自己的会话分支上提交代码（需要落主干时走 PR 合入 main，严禁切换或直接推送其他工作分支；信箱派单走独立的 refs/heads/hub/mailbox）。

目标：通过 DESKTOP-IEUDGS5 基座（Windows 10 + RTX A4000 16GB + 原生 GROMACS 2025.1 CUDA，装在 F:\gromacs-2025.1-SM86）把自动化粗粒化分子动力学链路打通，并当场实测跑完一个 100 ns 的 Martini 3 粗粒化分子动力学任务：

1. 同步基座代码到当前新分支并修复 4 个实测建模问题：
   - 若当前分支（源自 main）尚无 core/ 与 skills/，先 git fetch origin 将远端已有基座分支代码合并进当前会话分支（--allow-unrelated-histories）。
   - 修复 code/cgmd（纯 ASCII、单测全绿）：(a) 自动浅克隆 https://github.com/marrink-lab/martini-forcefields.git 定位 regular/v3.0.0/gmx_files（PyPI 无 martini-forcefields）；(b) martinize2 不传外部 vermouth_files 的 -ff-dir/-map-dir（直接用内置 martini3001），二级结构展开为残基长度（"H" * len(seq)），并以 cwd=workdir 运行确保 Protein_0.itp 落在 workdir；(c) topol.top 引用的 martini_v3.0.0*.itp 平铺复制到 workdir 同目录写成 #include "martini_v3.0.0.itp"；(d) Martini 3 为 reaction-field 静电，GPU 运行参数用 -nb gpu -bonded gpu -gpu_id 0（不带 -pme）。
   - 在 Invoke-CgmdMailbox.ps1 / Invoke-CgmdBridge.ps1 补齐 kind='pipeline'（调用台式机原生 Python 3.12 + 原生 gmx.exe，不走 WSL），在 Invoke-JobDeskfix 支持更新 config branch，在 Invoke-PeerCycle 支持扫描 peer_repos 的 hub/mailbox 与 arena/* 分支 inbox/*.json，单任务超时放宽至 5400 秒；推送当前分支并通过 gh pr create / gh pr merge 合入 main。

2. 先通过基座信箱确认链路在线：
   - 运行 python3 -m core.hub_mailbox caps 与 python3 -m core.hub_mailbox run --kind ping --timeout 300，确认 DESKTOP-IEUDGS5 在线。

3. 直接通过基座实测跑通 100 ns 自动化 Martini 3 粗粒化分子动力学任务（Magainin-2: GIGKFLHSAKKFGKAFVGEIMNS，POPE:POPG=3:1，310 K，0.15 M NaCl，equilibration_ns=10，production_ns=100）：
   - 若台式机值守已加载 kind='pipeline'，直接投递 --kind pipeline（timeout 5400）一步跑完。
   - 若台式机值守尚未切到新脚本（pipeline 返回 unsupported），不要让我去台式机手动切分支：直接在沙箱先完成 Stage 1-6 建系（生成平铺 .itp、topol.top、index.ndx、em/eq/prod.mdp 与带 CRYST1 盒子的初始输入），借助 hub/mailbox 在台式机本地映射目录 C:\cgmd\0fuye\skills\cgmd-hub\state\mailbox 下暂存小文本输入，通过已在线的 --kind gmx 依次自动执行 grompp 与 RTX A4000 GPU mdrun（em -> 10 ns eq -> 100 ns prod，使用 -nb gpu -bonded gpu -gpu_id 0，输出前缀指到 C:\cgmd\0fuye\skills\cgmd-hub\state\cgmd_100ns_* 以确保 .tpr/.xtc/.gro/.edr 留在台式机本地绝不进 Git）及非交互 gmx distance / gyrate / energy 分析，跑完立即清理 hub/mailbox 暂存目录。

4. 汇总生成 < 1 MB 的 summary_metrics.json 与 SVG 矢量图，向我汇报实测工单号、GPU 速度（ns/day）、100 ns 完成步数、膜插入深度与回执详情（未实测项必须标未验证，严禁编造）。
```

### 提示词 2（在 `JevHarness` 等外部项目 **新开对话**粘贴：通过 `0fuye` 基座执行 100 ns 自动化粗粒化动力学）

```text
全程你来操作，我不在台式机敲任何命令。这是一个全新的对话，请只在你当前自己的会话分支上操作，严禁新建第二套台式机底座或轮询脚本，严禁把轨迹/二进制文件（.xtc/.trr/.tpr/.gro/.edr/.cpt）提交进 Git。

请把公开仓库 https://github.com/hukeying85-ux/0fuye.git 作为只读客户端拉到 /tmp/0fuye（若 main 分支尚无 core/hub_mailbox.py，则自动查找并检出远端包含 core/hub_mailbox.py 的最新分支），通过 DESKTOP-IEUDGS5 基座实测执行一次 100 ns 自动化 Martini 3 粗粒化分子动力学任务：
1. 读取基座能力卡与最新状态，确认 DESKTOP-IEUDGS5 在线且 peer_repos 已包含当前仓库。
2. 对抗菌肽 Magainin-2（GIGKFLHSAKKFGKAFVGEIMNS，POPE:POPG=3:1，310 K，0.15 M NaCl，equilibration_ns=10，production_ns=100）完成理化预筛与平铺 Martini 3 拓扑建系校验。
3. 通过对端信箱机制（当前仓库分支 inbox/<job_id>.json 或 hub/mailbox，从 /tmp/0fuye 读取 outbox/<job_id>.json 回执）驱动 DESKTOP-IEUDGS5 的 RTX A4000 + 原生 GROMACS 2025.1 CUDA 跑完 100 ns 粗粒化生产动力学。
4. 取回 < 1 MB 的 summary_metrics.json 与 *.svg 矢量图，汇报实测工单号、GPU 性能（ns/day）、膜插入深度 z_distance_mean_nm、脂质序参数与成孔指标。
```
