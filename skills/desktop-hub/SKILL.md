---
name: desktop-hub
description: Connect any JevHarness, Codex, Claude Code, or Arena session to the Windows GPU workstation (DESKTOP-IEUDGS5 / hukeying85-ux/0fuye @ arena/32cd826e-0fuye) via the Desktop Base (git-sync-hub), 0fuye telemetry/mailbox bus, or LAN HTTP bridge (:8765).
---

# Desktop Hub (`arena/32cd826e-0fuye` Bridge)

Bridge any coding session to the Windows GPU workstation (`DESKTOP-IEUDGS5`, RTX A4000 16 GB, native GROMACS 2025.1 CUDA, Arena Desk v2.8) hands-free without requiring manual terminal work on the desktop.

## Three Transport Channels & Fallback Order

1. **LAN / Tailscale / ZeroTier Direct HTTP Bridge (`< 1 s`)**
   - Endpoint: `http://<workstation-ip>:8765` (`/health`, `/status`, `/job`)
   - Candidate IPs discovered automatically from `0fuye` telemetry (`100.84.137.117`, `192.168.110.226`).
   - CLI: `python3 scripts/desktop-hub.py lan-ping` / `lan-job --host <ip> --kind smoke`

2. **Desktop Base (`git-sync-hub` / 台式机的基座, `<= 15-45 s`)**
   - Polls `hukeying85-ux/<repo>` `arena/*` branches every 15 s on the workstation (`C:\0github\.git-sync\desktop-base\hub-watch.ps1`).
   - Works **strictly on the current session's own working branch** (zero cross-branch pushes, zero rebase conflicts with other sessions).
   - Pure-data connectivity check:
     ```bash
     python3 scripts/desktop-hub.py base-handshake --note "verify desktop base"
     git add results/status/handshake.json && git commit -m "chore(hub): queue desktop base handshake"
     git push origin <current-branch>
     python3 scripts/desktop-hub.py base-wait --timeout 70
     ```
   - Receipt lands in `results/status/hub_sync_receipt.json` on the same branch and mirrors artifacts to `C:\0github\results\<repo-branch>\`.

3. **0fuye Live Telemetry & Git Mailbox (`<= 60 s`)**
   - Read-only telemetry from any session or repository (never modifies local git refs or pushes to foreign branches):
     ```bash
     python3 scripts/desktop-hub.py status
     python3 scripts/desktop-hub.py probe-0fuye
     python3 scripts/desktop-hub.py mailbox-show <job_id>
     ```
   - When working directly inside an unlocked `hukeying85-ux/0fuye` checkout, queue jobs via `core.hub_mailbox` (`ping`, `selfcheck`, `smoke`, `sync`, `gmx`, `deskdiag`, `deskfix`) on ref `hub/mailbox`.

## Hard Rules

1. **Respect session branch locks:** Never switch branches or push to another branch or repository when a session is bound to a working branch (such as `arena/*`). Use `probe-0fuye` for read-only inspection of `0fuye`, and `base-handshake` on the session's own branch for round-trip verification.
2. **Evidence separation:** Only report the desktop base (`git-sync-hub`) as live-verified for the current branch when `results/status/hub_sync_receipt.json` is fetched from `origin/<current-branch>` with a matching commit SHA. Distinguish `0fuye` `CGMD-Hub-Poll` heartbeats from `git-sync-hub` branch receipts.
3. **Least privilege & explicit command consent:** Prefer pure-data `handshake.json` or allowlisted `gmx` / `smoke` / `selfcheck` jobs. Do not populate `powershell` / `python` / `bash` command arrays in `hub_task.json` unless explicitly authorized by the user (`--allow-exec`).
4. **ASCII & zero-window Windows scripts:** Every `.ps1` and `.cs` file under `desktop-base/` must remain 100% pure ASCII and launch via `/target:winexe` (`ArenaSilentRun.exe`) with `CreateNoWindow = true`.
5. **No heavy simulation trajectories in Git:** Never commit `.xtc`, `.trr`, `.tpr`, `.cpt`, `.gro`, `.edr`, `.h5`, or `.dcd` files; keep Git-synced status and summary files under 1 MB.

## Reference & One-Time Desktop Base Repair

Read [references/desktop-architecture.md](references/desktop-architecture.md) for the full schema reference and the five root-cause fixes in `desktop-base/hub-watch-desktop.ps1` v4.5 (`$BaseDirName = 'desktop-base'` self-eviction fix, `F:\Program Files\Git` & `Python312` multi-drive discovery, `C:\cgmd\0fuye\skills\cgmd-hub\state\git-credentials` token bridge, `0fuye`+`JevHarness` seed list, and `ArenaSilentRun.exe -Loop` lifetime tracking).
