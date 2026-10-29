# `0fuye@arena/32cd826e-0fuye` 客户端契约与验收基线

## 1. 基线指标（`DESKTOP-IEUDGS5`，2026-10-29 实测）

| 项目 | 实测基线 |
| --- | --- |
| 主机 | `DESKTOP-IEUDGS5`（Windows 10 专业版，48 线程，31.2 GB RAM） |
| GPU | `NVIDIA RTX A4000` 16 GB（驱动 `596.71`） |
| GROMACS | 原生 Windows `2025.1`（`F:\gromacs-2025.1-SM86\...\gmx.exe`，CUDA 12.8 / 驱动 13.20，mixed，FFTW3） |
| 值守与面板 | `CGMD-Hub-Poll`（60 s 静默轮询）+ `Arena Desk v2.8.0`（`127.0.0.1:18765`）+ 局域网桥 `:8765` |
| `ping` 延迟 | 信箱执行耗时 `0.44–0.9 s`（轮询周期 `<= 60 s`）；同局域网 `:8765` `< 1 s` |
| `100 ps` GPU 烟测 | 端到端 `21–31 s`，`mdrun` `14–16 s`，性能 `576–617 ns/day` |
| 18 项自检 | `15 pass / 3 warn / 0 fail`（3 项 warn 为 WSL Martini Python 依赖，不影响原生 GPU 路径） |

## 2. `100 ps` 烟测 6 项硬核验路径（`verify_smoke_result`）

1. `result.status == "ok"`
2. `result.detail.report.ps_completed == 100`
3. `result.detail.report.mdrun.finished == True`
4. `result.detail.report.mdrun.performance_ns_per_day > 0`
5. `result.detail.report.accelerator == "gpu"`（注意在 `report.accelerator`，不在 `report.progress`）
6. `result.detail.report.stages` 中 `stage == "mdrun-md-gpu"` 的 `returncode == 0`

## 3. Arena 云端跨仓 Token 边界说明

- 在 `hukeying85-ux/0fuye` 会话或本地笔电终端中，`core.hub_mailbox` 可直接推送 `refs/heads/hub/mailbox` 派单并回收结果。
- 在非 `0fuye` 仓库（如 `hukeying85-ux/JevHarness`）的 Arena 云端沙箱中，平台签发的 `arena-ai-coding-agent` GitHub App Token 仅授予当前会话仓库 `contents:write`，对 `hukeying85-ux/0fuye.git` 推送返回 `HTTP 403 (Resource not accessible by integration)`。
- 遇到该 `403` 时属于平台跨仓写权限隔离，**严禁**误判为台式机掉线，也**严禁**向用户索要 Token 或要求用户在台式机粘贴任何命令。
