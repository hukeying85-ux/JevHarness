# Desktop Hub Architecture & Repaired Desktop Base Reference

## 1. Workstation Profile (`DESKTOP-IEUDGS5`)

From verified `hukeying85-ux/0fuye` (`arena/32cd826e-0fuye`) telemetry:

- **Host:** `DESKTOP-IEUDGS5` (Windows 10 Pro, 48 logical CPUs)
- **GPU:** NVIDIA RTX A4000 (16,376 MiB, driver 596.71)
- **GROMACS:** 2025.1 native Windows CUDA (`F:\gromacs-2025.1-SM86\gromacs-2025.1-SM86\bin\gmx.exe`, ~576 ns/day on 100 ps SPC water GPU test)
- **Git / Python paths:** `F:\Program Files\Git\cmd\git.exe`, `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`
- **Deployed paths:**
  - `C:\cgmd\0fuye` — `arena/32cd826e-0fuye` (`CGMD-Hub-Poll` every 60 s + `hub/mailbox` worker)
  - `C:\0apps\ArenaDesk` — Arena Desk v2.8.0 (`127.0.0.1:18765`)
  - `C:\0github\.git-sync\desktop-base` — Desktop Base (`git-sync-hub`, 15 s cross-repo `arena/*` watcher)
- **Discovered LAN / Mesh IPs:** `100.84.137.117` (Tailscale), `192.168.110.226` (LAN), bridge port `8765`

## 2. Five Root-Cause Fixes in `desktop-base/` (v4.5 vs `0fuye@arena/32cd826e-0fuye`)

| # | Symptom on `DESKTOP-IEUDGS5` | Root Cause in `0fuye` `skills/git-sync-default/` | Fix in `skills/desktop-hub/desktop-base/` |
| --- | --- | --- | --- |
| 1 | `C:\0github\.git-sync\desktop-base\hub-watch.ps1` vanished right after cycle #1 | `install_desktop_default_hub.ps1` installed into `desktop-base`, while `hub-watch-desktop.ps1` defaulted `$BaseDirName = 'leanrea-626378d6-leanrea'`, causing `Invoke-ResultsOnlyCleanup` to delete `desktop-base` on the first 15 s tick | Default `$BaseDirName = 'desktop-base'` + explicit protection of `$PSScriptRoot` and `desktop-base` in `Invoke-ResultsOnlyCleanup` |
| 2 | `git-sync-hub` could not push `hub_sync_receipt.json` to `JevHarness` or other `hukeying85-ux` repos | `bootstrap_desktop.ps1` saved the GitHub token only in `C:\cgmd\0fuye\skills\cgmd-hub\state\git-credentials` (`--local`), invisible to ephemeral clones in `%TEMP%` | `Find-CgmdCredentialFile` + `-WithOwnerCreds` automatically bridges `cgmd\0fuye\skills\cgmd-hub\state\git-credentials` for `$Owner` pushes and API discovery |
| 3 | Non-interactive Task Scheduler missed Git / Python | Hardcoded `C:\` and `E:\` paths missed `F:\Program Files\Git\cmd\git.exe` and `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` | Multi-drive probe (`C:\..G:\`) + `%LOCALAPPDATA%\Programs\Python\Python3*` |
| 4 | Task Scheduler showed `Ready` after 60 s and could not auto-restart crashed loops | `ArenaSilentRun.cs` called `p.WaitForExit(60000)` even for `-Loop` daemons and exited `0` | `ArenaSilentRun.cs` waits for child lifetime when `-Loop` is passed + 5-minute `RepetitionInterval` watchdog trigger |
| 5 | `tri_account_console.py` skipped installing `desktop-base` when `Sync-Desktop.ps1` already existed | `if (Test-Path Sync-Desktop.ps1)` branch bypassed `install_desktop_default_hub.ps1` | Unified idempotent `install_desktop_default_hub.ps1` installs/updates `0fuye`, `CGMD-Hub-Poll`, `git-sync-hub`, `ArenaDesk`, and `CGMD-LAN-Bridge` together |

## 3. One-Line Desktop Base Bootstrap / Repair (Run Once on `DESKTOP-IEUDGS5` if `git-sync-hub` is Not Yet Active)

In a normal (non-admin) PowerShell window on `DESKTOP-IEUDGS5`:

```powershell
$d="$env:TEMP\jev-desk-base"; Remove-Item $d -Recurse -Force -EA 0; git clone --depth 1 -b arena/f5038599-jevharness https://github.com/hukeying85-ux/JevHarness.git $d; powershell -NoProfile -ExecutionPolicy Bypass -File "$d\skills\desktop-hub\desktop-base\install_desktop_default_hub.ps1"
```

## 4. Python CLI Quick Reference

```bash
# 1) Full 3-channel status (LAN + local git-sync-hub receipt + live 0fuye telemetry)
python3 scripts/desktop-hub.py status

# 2) Read-only live telemetry from hukeying85-ux/0fuye (arena/32cd826e-0fuye + hub/mailbox)
python3 scripts/desktop-hub.py probe-0fuye

# 3) Write pure-data handshake for git-sync-hub on the current branch
python3 scripts/desktop-hub.py base-handshake --note "session check"

# 4) Wait for git-sync-hub receipt on origin/<current-branch>
python3 scripts/desktop-hub.py base-wait --timeout 70

# 5) LAN / Tailscale direct millisecond bridge (:8765)
python3 scripts/desktop-hub.py lan-ping
python3 scripts/desktop-hub.py lan-job --host 100.84.137.117 --kind smoke --json-args '{"ps": 100}'
```
