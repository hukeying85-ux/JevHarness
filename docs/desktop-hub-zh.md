# 台式机基座接入与解放双手指南（`0fuye@arena/32cd826e-0fuye` × `JevHarness`）

> **当前会话仓库 / 分支：** `hukeying85-ux/JevHarness` · `arena/f5038599-jevharness`  
> **关联算力分支：** `hukeying85-ux/0fuye` · `arena/32cd826e-0fuye`（主机 `DESKTOP-IEUDGS5`）  
> **实测核验时间：** `2026-10-29 15:36–15:39 (UTC+8)`

---

## 1. 本次已完成安装与落地清单

在本仓库分支 `arena/f5038599-jevharness` 及当前智能体运行环境中，已完成以下安装与修复：

| 模块 | 路径 | 说明 |
| --- | --- | --- |
| **三通道桌面桥接引擎** | `auto_jev/desktop_hub.py`、`scripts/desktop-hub.py`（CLI：`jev-desktop-hub`） | 统一整合 **局域网/Tailscale 直连桥 (`:8765`)**、**台式机基座 (`git-sync-hub`) 分支握手/回执**、**`0fuye` 实时遥测与信箱 (`hub/mailbox`)** |
| **Desktop Hub 技能包** | `skills/desktop-hub/`（已安装至 `~/.agents/skills/desktop-hub` 与 `~/.claude/skills/desktop-hub`） | 支持在 Codex（`$desktop-hub`）与 Claude Code（`/desktop-hub`）直接唤醒，兼容 `scripts/install-skill.py --skill all` |
| **修复版台式机基座 (v4.5)** | `skills/desktop-hub/desktop-base/`（纯 ASCII，PowerShell 5.1 零乱码、零闪窗） | 修复了 `0fuye@arena/32cd826e-0fuye` 中导致跨仓基座无法常驻回传的 **5 个真实根因 Bug**（见第 3 节） |
| **自动化回归测试** | `tests/test_desktop_hub.py`、`tests/test_skill_install.py` | 19 项测试全绿（含纯 ASCII 校验、旧版 Bug 静态审计、Git 分支握手回执往返、LAN 桥、分支锁防串号） |

---

## 2. 证据分级实测结果（严格区分「已在线核验」与「待修复项」）

| 检查维度 | 实测状态 | 本会话实测证据 |
| --- | --- | --- |
| **`DESKTOP-IEUDGS5` 上的 `0fuye` 守护 (`CGMD-Hub-Poll`)** | **在线运行中（已实测）** | 远端只读探测 `0fuye@arena/32cd826e-0fuye`：`hub_mailbox.json` 最新回报于 `2026-10-29T15:32:58+08:00`；刚刚完成 `ping`（`20261029T073039-b78f`）与 GPU `100 ps` 烟测（`20261029T073120-60bd`，`GROMACS 2025.1 CUDA` + `NVIDIA RTX A4000 16GB`，最新实测性能 `617.155 ns/day`） |
| **`DESKTOP-IEUDGS5` 上的 `Arena Desk` 面板** | **已部署运行（`0fuye` 自检报告）** | `C:\0apps\ArenaDesk` `v2.8.0`（`127.0.0.1:18765` HTTP `200`，18 项自检 `15 pass / 3 warn / 0 fail`） |
| **跨仓库「台式机基座」(`git-sync-hub` → `JevHarness`)** | **未回执（65 秒实测超时，已定位 5 个根因并备好修复包）** | 向 `origin/arena/f5038599-jevharness` 推送纯数据握手 `results/status/handshake.json`（提交 `4fe0699`）并轮询等待 65 秒，未收到 `hub_sync_receipt.json` 回传 |
| **当前云端沙箱 ↔ 台式机局域网直连 (`:8765`)** | **跨公网隔离（符合预期）** | 台式机已上报内网/组网地址 `100.84.137.117`（Tailscale）、`192.168.110.226`（局域网），同局域网或同 Tailscale/ZeroTier 节点的笔记本可直接毫秒级调用 |

---

## 3. 为什么台式机的跨仓基座（`git-sync-hub`）之前没打通其它仓库？——5 个真实根因

通过对 `0fuye@arena/32cd826e-0fuye` 中 `skills/git-sync-default/` 与 `tri_account_console.py` 源码逐行审计，定位到导致「`0fuye` 自己在跑，但跨仓基座 `desktop-base` 没回执」的 **5 个确定性 Bug**（已在 `skills/desktop-hub/desktop-base/` 全部修复）：

1. **第 1 轮轮询自删脚本（最致命）：**  
   `0fuye` 的 `install_desktop_default_hub.ps1` 把脚本装进 `C:\0github\.git-sync\desktop-base\hub-watch.ps1`，但 `hub-watch-desktop.ps1` 里的默认参数仍是笔记本遗留的 `$BaseDirName = 'leanrea-626378d6-leanrea'`。结果第 1 个 15 秒周期结束执行 `Invoke-ResultsOnlyCleanup` 时，直接把 `desktop-base` 当成临时目录**自己删掉了**。  
   **→ 已修复：** 默认 `$BaseDirName = 'desktop-base'`，且清理函数显式保护 `$PSScriptRoot` 与 `desktop-base`。
2. **Git 凭据隔离导致跨仓 `git push` 静默失败：**  
   `0fuye` 的 `bootstrap_desktop.ps1` 只把 `hukeying85-ux` 的 Token 写进了 `C:\cgmd\0fuye\skills\cgmd-hub\state\git-credentials`（`--local` 仅对 `C:\cgmd\0fuye` 生效）。`git-sync-hub` 在 `%TEMP%` 克隆 `JevHarness` 等其它仓库时拿不到凭据，推送回执直接失败。  
   **→ 已修复：** `Find-CgmdCredentialFile` 自动桥接复用 `cgmd\0fuye\skills\cgmd-hub\state\git-credentials`（全程不打印、不落盘明文 Token）。
3. **盘符硬编码漏掉 `F:` 盘 Git 与 `Python312`：**  
   `DESKTOP-IEUDGS5` 的 Git 安装在 `F:\Program Files\Git\cmd\git.exe`，Python 在 `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`，旧脚本只查 `C:\` 与 `E:\`。  
   **→ 已修复：** 自动遍历 `C:\..G:\` 全盘符与 `%LOCALAPPDATA%\Programs\Python\Python3*`。
4. **静默启动器 `ArenaSilentRun.cs` 60 秒提前退出：**  
   旧版对常驻 `-Loop` 守护也调用 `p.WaitForExit(60000)` 并在 60 秒后返回 `0`，导致 Windows 计划任务误判任务已结束、崩溃后无法触发自动拉起。  
   **→ 已修复：** 识别 `-Loop` 全生命周期等待，并新增 **每 5 分钟一次的看门狗触发器**（上限 3650 天，兼容 Win10/11 计划任务校验）。
5. **面板同步分支条件跳过了基座安装器：**  
   `tri_account_console.py` 中 `if (Test-Path Sync-Desktop.ps1)` 为真时只跑了 `Sync-Desktop.ps1`，跳过了 `install_desktop_default_hub.ps1`。  
   **→ 已修复：** 新版 `install_desktop_default_hub.ps1` 幂等串联 **`0fuye` 克隆/更新 + `CGMD-Hub-Poll` + 修复版 `git-sync-hub` + `Arena Desk v2.8` + `CGMD-LAN-Bridge (:8765)`**。

---

## 4. 台式机侧「最后一次」1 行永久打通命令（全程零弹窗）

如果你希望让 `DESKTOP-IEUDGS5` 把**跨所有 `hukeying85-ux` 仓库（含 `JevHarness`、`0fuye`、`skills`、`mu`）的 15 秒自动基座 + 局域网 8765 直连桥**一次性装好并替换掉上面的旧版 Bug，只需在台式机**普通权限 PowerShell** 粘贴一次：

```powershell
$d="$env:TEMP\jev-desk-base"; Remove-Item $d -Recurse -Force -EA 0; git clone --depth 1 -b arena/f5038599-jevharness https://github.com/hukeying85-ux/JevHarness.git $d; powershell -NoProfile -ExecutionPolicy Bypass -File "$d\skills\desktop-hub\desktop-base\install_desktop_default_hub.ps1"
```

> 注：如果台式机 `C:\cgmd\0fuye\skills\cgmd-hub\state\git-credentials` 已经存在（今天已初始化过），上面这一行**不会再提示输入任何密码或 Token**，几十秒内静默完成全部 4 个计划任务注册与自启动，之后彻底解放双手。

---

## 5. 日常使用速查（在本项目或任意新会话中）

```bash
# 1. 一键查看台式机三通道实时状态（局域网桥 + 本分支基座回执 + 0fuye 实时遥测）
python3 scripts/desktop-hub.py status

# 2. 只读拉取 0fuye (DESKTOP-IEUDGS5) 最新心跳、GPU 自检与烟测指标（不改任何分支）
python3 scripts/desktop-hub.py probe-0fuye

# 3. 在当前分支发起纯数据基座握手并等待台式机回执
python3 scripts/desktop-hub.py base-handshake --note "verify desktop base"
git add results/status/handshake.json && git commit -m "chore(hub): handshake" && git push origin arena/f5038599-jevharness
python3 scripts/desktop-hub.py base-wait --timeout 70

# 4. 同局域网 / Tailscale (100.84.137.117 / 192.168.110.226) 秒级直连调用 GPU
python3 scripts/desktop-hub.py lan-ping --host 100.84.137.117
python3 scripts/desktop-hub.py lan-job  --host 100.84.137.117 --kind smoke --json-args '{"ps": 100}'
python3 scripts/desktop-hub.py lan-job  --host 100.84.137.117 --kind gmx --arg --version

# 5. 将技能安装到任意其它本地项目（Codex + Claude Code 双端）
python3 scripts/install-skill.py --skill all --target both --scope project --project /path/to/your-project
```
