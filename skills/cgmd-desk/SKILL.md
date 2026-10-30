---
name: cgmd-desk
description: Drive the DESKTOP-IEUDGS5 workstation (RTX A4000 16GB + native GROMACS 2025.1 CUDA + Arena Desk v2.8.0) strictly as a client of hukeying85-ux/0fuye@arena/32cd826e-0fuye without installing a second watcher or asking the user to paste commands.
---

# CGMD Desktop Client (`DESKTOP-IEUDGS5` via `0fuye@arena/32cd826e-0fuye`)

`DESKTOP-IEUDGS5` already runs the single canonical desktop base from
`hukeying85-ux/0fuye` (`arena/32cd826e-0fuye`):

- `CGMD-Hub-Poll`: 60 s silent scheduled watcher (`wscript -> CGMDHub.exe -> Invoke-CgmdPoll.ps1`)
- `Arena Desk v2.8.0`: `127.0.0.1:18765`
- `CGMD LAN Bridge`: `:8765` (`192.168.110.226` / `100.84.137.117`, laptop/LAN only)
- Native Windows `gmx.exe` `2025.1` (`F:\gromacs-2025.1-SM86\gromacs-2025.1-SM86\bin\gmx.exe`, CUDA 12.8, RTX A4000 16 GB)

## Hard Rules (Non-Negotiable)

1. **Zero User Paste**: Never ask the user to run or paste PowerShell/shell commands on `DESKTOP-IEUDGS5`.
2. **Single Base Only**: Never create a second watcher (`desktop-base`, `.ps1`, `.vbs`, `.cs` pollers) in `JevHarness` or any other repository. Always consume `0fuye` as a client.
3. **Branch Hygiene**: Never commit or push to working branches of `0fuye`; mailbox jobs live exclusively on `refs/heads/hub/mailbox`.
4. **Cloud Sandbox Network Fact**: Cloud sandboxes only reach `github.com` / `api.github.com` / `pypi.org` / `registry.npmjs.org` — never probe `192.168.x.x:8765` or `100.84.x.x:8765` from a cloud container.
5. **No Heavy Trajectories in Git**: Never commit `.xtc`, `.trr`, `.tpr`, `.gro`, `.edr`, `.edv`, or `.cpt` files; only `< 1 MB` `summary_metrics.json` and vector `.svg` plots belong in Git.

## Standard Workflow from `JevHarness`

```bash
# Step 0: Capability card (1 s, read-only from 0fuye telemetry)
python3 -m auto_jev.cgmd_desk caps

# Full §1 status + outbox verification summary
python3 -m auto_jev.cgmd_desk report

# Step 1: Confirm link (dispatches via hub/mailbox; auto-diagnoses HTTP 403 token scope in non-0fuye Arena sandboxes)
python3 -m auto_jev.cgmd_desk run --kind ping --timeout 300

# Step 2: 100 ps GPU smoke run & 6-point schema acceptance check
python3 -m auto_jev.cgmd_desk run --kind smoke --json-args '{"ps": 100}' --timeout 1800
python3 -m auto_jev.cgmd_desk verify-smoke

# Laptop / same-LAN sub-second mode (automatically degrades to hub/mailbox if unreachable)
python3 -m auto_jev.cgmd_desk run --kind ping --lan-host 192.168.110.226

# Full 12-stage Martini 3 AMP membrane-pore workflow (pre-screen -> build -> submit)
python3 -m auto_jev.cgmd_desk screen --name magainin2 --sequence GIGKFLHSAKKFGKAFVGEIMNS --ss H
python3 -m auto_jev.cgmd_desk prepare-system --workdir /tmp/cgmd_magainin2 --name magainin2 --sequence GIGKFLHSAKKFGKAFVGEIMNS
python3 -m auto_jev.cgmd_desk submit-pipeline --name magainin2 --sequence GIGKFLHSAKKFGKAFVGEIMNS --eq-ns 5 --prod-ns 20
```

See `docs/cgmd-full-pipeline-zh.md` for the Windows-native `Python 3.12 + gmx.exe 2025.1 CUDA` pipeline architecture and the 6 empirically verified upstream fixes.

## Repair Sequence (If `ping` Returns `timeout` / `lost`)

Run in fixed order via mailbox (`python3 -m auto_jev.cgmd_desk run --kind ...`):
`deskdiag` -> `deskfix` -> `sync --json-args '{"desk": true}'` -> `selfcheck`.

Note on Arena.ai Cloud Sandboxes: Arena mints a per-session GitHub App token (`arena-ai-coding-agent`) scoped only to the session's active repository. Inside a `JevHarness` cloud session, `git push` to `hukeying85-ux/0fuye.git` (`refs/heads/hub/mailbox`) returns `HTTP 403 Resource not accessible by integration`. `auto_jev.cgmd_desk` detects this automatically (`status = "blocked_by_token_scope"`) so you never mistake platform token isolation for a dead desktop watcher.

See `references/0fuye-contract-zh.md` for field-level smoke assertions and baseline metrics.
