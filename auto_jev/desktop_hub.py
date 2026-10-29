"""Desktop workstation bridge & hub client for JevHarness.

Integrates the three hands-free desktop channels from
``hukeying85-ux/0fuye`` (branch ``arena/32cd826e-0fuye``):

1. **Desktop Base (``git-sync-hub`` / 台式机的基座)** — polls ``hukeying85-ux``
   ``arena/*`` branches every 15 s, processes ``results/status/handshake.json``
   and ``results/status/hub_task.json``, mirrors ``results/`` to
   ``C:\\0github\\results\\<repo-branch>``, and pushes
   ``results/status/hub_sync_receipt.json`` back to the working branch.
2. **0fuye Git Mailbox Bus (``hub/mailbox`` & ``results/status/*.json``)** —
   read-only remote telemetry probe (``probe-0fuye``) that inspects the live
   ``DESKTOP-IEUDGS5`` heartbeat, 18-point self-check, native GROMACS 2025.1
   100 ps GPU smoke report, Arena Desk v2.8 status, and mailbox outbox without
   touching the local checkout or pushing to foreign branches; plus full
   ``cgmd.mailbox.request.v1`` / ``cgmd.mailbox.result.v1`` client support when
   operating inside an unlocked ``0fuye`` checkout.
3. **LAN / Tailscale / ZeroTier Direct HTTP Bridge (``:8765``)** — sub-second
   ``/health``, ``/status``, and ``/job`` calls (``ping``, ``smoke``,
   ``selfcheck``, ``gmx``) when on the same network as the workstation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import http.client
import json
import os
from pathlib import Path
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

DEFAULT_0FUYE_REPO = "https://github.com/hukeying85-ux/0fuye.git"
DEFAULT_0FUYE_BRANCH = "arena/32cd826e-0fuye"
DEFAULT_MAILBOX_REF = "hub/mailbox"
DEFAULT_BRIDGE_PORT = 8765
DEFAULT_CANDIDATE_HOSTS = ("192.168.110.226", "100.84.137.117", "127.0.0.1")

SCHEMA_MAILBOX_REQUEST = "cgmd.mailbox.request.v1"
SCHEMA_MAILBOX_RESULT = "cgmd.mailbox.result.v1"
SCHEMA_HANDSHAKE = "jev.desktop_hub.handshake.v1"

HANDSHAKE_REL_PATH = "results/status/handshake.json"
RECEIPT_REL_PATH = "results/status/hub_sync_receipt.json"
EXEC_OUTPUT_REL_PATH = "results/status/hub_exec_output.txt"
HUB_TASK_REL_PATH = "results/status/hub_task.json"

MAILBOX_KINDS = (
    "ping",
    "selfcheck",
    "smoke",
    "sync",
    "gmx",
    "deskdiag",
    "deskfix",
    "shell",
    "pipeline",
)

GMX_ALLOWLIST = frozenset({
    "--version", "-version", "solvate", "grompp", "mdrun", "editconf", "genion",
    "insert-molecules", "energy", "traj", "check", "dump", "select", "rms",
    "distance", "gyrate", "make_ndx", "pdb2gmx", "trjconv", "trjcat",
    "convert-tpr", "genrestr", "wham", "do_dssp", "sasa", "hbond", "density",
    "potential", "bar", "enemat", "covar", "anaeig", "filter", "helix",
    "sorient", "order", "polystat", "ram", "sans", "sham", "spatial", "wheel",
    "xpm2ps", "view", "nmens", "cluster",
})

BEIJING_TZ = timezone(timedelta(hours=8))


class DesktopHubError(RuntimeError):
    """Raised when a desktop bridge, mailbox, or git-sync-hub operation fails."""


class BridgeUnreachableError(DesktopHubError):
    """Raised when the LAN/Tailscale HTTP bridge cannot be reached."""


def beijing_now_iso() -> str:
    return datetime.now(BEIJING_TZ).replace(microsecond=0).isoformat()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_age_seconds(stamp: str) -> float | None:
    if not stamp or not isinstance(stamp, str):
        return None
    text = stamp.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


# ---------------------------------------------------------------------------
# Subprocess & Git helpers
# ---------------------------------------------------------------------------
def _run_git(
    cwd: str | Path,
    args: list[str],
    *,
    stdin_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 45,
) -> tuple[int, bytes, bytes]:
    merged_env = dict(os.environ)
    merged_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    if env:
        merged_env.update(env)
    proc = subprocess.Popen(
        ["git", *args],
        cwd=str(cwd),
        stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
    )
    try:
        out, err = proc.communicate(stdin_bytes, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        return 124, out or b"", (err or b"") + b"\ngit timed out"
    return proc.returncode, out or b"", err or b""


def _git_checked(
    cwd: str | Path,
    args: list[str],
    *,
    stdin_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 45,
) -> bytes:
    code, out, err = _run_git(cwd, args, stdin_bytes=stdin_bytes, env=env, timeout=timeout)
    if code != 0:
        detail = (err or out).decode("utf-8", "replace").strip()[:400]
        raise DesktopHubError(f"git {' '.join(args)} failed ({code}): {detail}")
    return out


def resolve_repo_root(path: str | Path = ".") -> Path:
    raw = _git_checked(path, ["rev-parse", "--show-toplevel"]).decode("utf-8").strip()
    return Path(raw).resolve()


def current_branch(repo: str | Path = ".") -> str:
    code, out, _ = _run_git(repo, ["symbolic-ref", "--short", "-q", "HEAD"], timeout=5)
    if code == 0 and out.strip():
        return out.decode("utf-8", "replace").strip()
    return _git_checked(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).decode("utf-8").strip()


def current_head_sha(repo: str | Path = ".") -> str:
    code, out, _ = _run_git(repo, ["rev-parse", "--verify", "HEAD"], timeout=5)
    return out.decode("utf-8", "replace").strip() if code == 0 else ""


def _read_git_blob_json(git_dir: str | Path, rev: str, rel_path: str) -> dict[str, Any] | None:
    code, out, _ = _run_git(git_dir, ["cat-file", "-p", f"{rev}:{rel_path}"], timeout=15)
    if code != 0 or not out:
        return None
    text = out.decode("utf-8-sig", "replace").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _read_git_blob_text(git_dir: str | Path, rev: str, rel_path: str) -> str | None:
    code, out, _ = _run_git(git_dir, ["cat-file", "-p", f"{rev}:{rel_path}"], timeout=15)
    if code != 0:
        return None
    return out.decode("utf-8-sig", "replace")


def _list_git_tree_paths(git_dir: str | Path, rev: str, prefix: str) -> list[str]:
    code, out, _ = _run_git(git_dir, ["ls-tree", "-r", "--name-only", rev, "--", prefix], timeout=15)
    if code != 0:
        return []
    return [line.strip() for line in out.decode("utf-8", "replace").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. Read-Only Live Probe of hukeying85-ux/0fuye (branch + hub/mailbox)
# ---------------------------------------------------------------------------
def audit_watcher_script_issues(ps_source: str) -> list[dict[str, str]]:
    """Static check for known desktop-base watcher pitfalls in hub-watch-desktop.ps1."""
    issues: list[dict[str, str]] = []
    if re.search(r"\$BaseDirName\s*=\s*'leanrea-626378d6-leanrea'", ps_source):
        issues.append({
            "id": "self-evict-basedir",
            "severity": "critical",
            "summary": (
                "Default $BaseDirName is 'leanrea-626378d6-leanrea' while "
                "install_desktop_default_hub.ps1 installs into 'C:\\0github\\.git-sync\\desktop-base'; "
                "Invoke-ResultsOnlyCleanup deletes desktop-base\\hub-watch.ps1 on cycle #1."
            ),
        })
    if "git-credentials" not in ps_source and "cgmd-hub" not in ps_source:
        issues.append({
            "id": "isolated-local-credentials",
            "severity": "high",
            "summary": (
                "bootstrap_desktop.ps1 stores GitHub credentials only in "
                "C:\\cgmd\\0fuye\\skills\\cgmd-hub\\state\\git-credentials (--local), "
                "so hub-watch-desktop.ps1 cannot push receipts to other repos unless GCM is configured globally."
            ),
        })
    if "'JevHarness'" not in ps_source and '"JevHarness"' not in ps_source:
        issues.append({
            "id": "missing-jevharness-seed",
            "severity": "low",
            "summary": "Fallback $ActiveRepoNames seed list does not include 0fuye or JevHarness when API discovery is rate-limited.",
        })
    if "F:\\Program Files\\Git" not in ps_source and "Get-PSDrive" not in ps_source and "driveRoots" not in ps_source:
        issues.append({
            "id": "missing-f-drive-git-python",
            "severity": "medium",
            "summary": (
                "DESKTOP-IEUDGS5 has Git at F:\\Program Files\\Git\\cmd\\git.exe and Python at "
                "%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe, which are missing from hardcoded C:/E: candidate lists."
            ),
        })
    return issues


def _extract_smoke_ns_per_day(smoke: dict[str, Any] | None) -> float | None:
    if not smoke:
        return None
    for block_key in ("mdrun", "performance"):
        block = smoke.get(block_key)
        if isinstance(block, dict) and isinstance(block.get("ns_per_day"), (int, float)):
            return float(block["ns_per_day"])
    if isinstance(smoke.get("ns_per_day"), (int, float)):
        return float(smoke["ns_per_day"])
    for stage in smoke.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for line in (stage.get("stderr_tail") or []) + (stage.get("output_tail") or []):
            m = re.search(r"Performance:\s+([0-9]+(?:\.[0-9]+)?)", str(line))
            if m:
                return float(m.group(1))
    return None


def _outbox_sort_key(path: str) -> tuple[str, str]:
    stem = Path(path).stem
    m = re.search(r"(\d{8}T\d{6})", stem)
    return (m.group(1) if m else "00000000T000000", stem)


def probe_0fuye_remote(
    repo_url: str = DEFAULT_0FUYE_REPO,
    branch: str = DEFAULT_0FUYE_BRANCH,
    mailbox_ref: str = DEFAULT_MAILBOX_REF,
    timeout: int = 45,
) -> dict[str, Any]:
    """Fetch read-only status from hukeying85-ux/0fuye in a temporary bare repo."""
    with tempfile.TemporaryDirectory(prefix="jev-0fuye-probe-") as tmp:
        _git_checked(tmp, ["init", "--bare", "--quiet"], timeout=10)
        fetch_specs = [
            f"+refs/heads/{branch}:refs/remotes/probe/branch",
        ]
        code_b, _, err_b = _run_git(
            tmp,
            ["fetch", "--quiet", "--depth", "1", repo_url, *fetch_specs],
            timeout=timeout,
        )
        if code_b != 0:
            raise DesktopHubError(
                f"Cannot fetch {repo_url} ({branch}): {err_b.decode('utf-8', 'replace').strip()[:300]}"
            )
        branch_sha = _git_checked(tmp, ["rev-parse", "refs/remotes/probe/branch"]).decode("utf-8").strip()

        mailbox_sha: str | None = None
        code_m, _, _ = _run_git(
            tmp,
            ["fetch", "--quiet", "--depth", "1", repo_url, f"+refs/heads/{mailbox_ref}:refs/remotes/probe/mailbox"],
            timeout=timeout,
        )
        if code_m == 0:
            c_rev, out_rev, _ = _run_git(tmp, ["rev-parse", "refs/remotes/probe/mailbox"], timeout=10)
            if c_rev == 0:
                mailbox_sha = out_rev.decode("utf-8").strip()

        heartbeat = _read_git_blob_json(tmp, branch_sha, "results/status/hub_heartbeat.json")
        mailbox_worker = _read_git_blob_json(tmp, branch_sha, "results/status/hub_mailbox.json")
        selfcheck = _read_git_blob_json(tmp, branch_sha, "results/status/desktop_selfcheck.json")
        desksync = _read_git_blob_json(tmp, branch_sha, "results/status/desktop_sync.json")
        smoke = _read_git_blob_json(tmp, branch_sha, "results/status/gmx_smoke.json")
        watcher_ps1 = _read_git_blob_text(tmp, branch_sha, "skills/git-sync-default/hub-watch-desktop.ps1")

        inbox_ids: list[str] = []
        outbox_ids: list[str] = []
        latest_ping: dict[str, Any] | None = None
        latest_outbox: dict[str, Any] | None = None
        if mailbox_sha:
            inbox_ids = sorted(
                Path(p).stem for p in _list_git_tree_paths(tmp, mailbox_sha, "inbox") if p.endswith(".json")
            )
            outbox_paths = sorted(
                (p for p in _list_git_tree_paths(tmp, mailbox_sha, "outbox") if p.endswith(".json")),
                key=_outbox_sort_key,
            )
            outbox_ids = [Path(p).stem for p in outbox_paths]
            if outbox_paths:
                latest_outbox = _read_git_blob_json(tmp, mailbox_sha, outbox_paths[-1])
            for candidate in reversed(outbox_paths):
                doc = _read_git_blob_json(tmp, mailbox_sha, candidate)
                if doc and doc.get("kind") == "ping" and isinstance(doc.get("detail"), dict):
                    latest_ping = doc
                    break

        worker_stamp = (mailbox_worker or {}).get("generated_at") or (heartbeat or {}).get("at") or ""
        worker_age_s = parse_iso_age_seconds(worker_stamp)
        lan_ips: list[str] = []
        bridge_port = DEFAULT_BRIDGE_PORT
        if latest_ping and isinstance(latest_ping.get("detail"), dict):
            detail = latest_ping["detail"]
            lan_ips = [str(ip) for ip in (detail.get("lan") or []) if ip]
            bridge_port = int(detail.get("bridge_port") or DEFAULT_BRIDGE_PORT)

        watcher_issues = audit_watcher_script_issues(watcher_ps1) if watcher_ps1 else []

        host_name = (
            (selfcheck or {}).get("host", {}).get("computer")
            or (mailbox_worker or {}).get("host")
            or (heartbeat or {}).get("host")
            or "unknown"
        )
        return {
            "probed_at": beijing_now_iso(),
            "repo_url": repo_url,
            "branch": branch,
            "branch_tip": branch_sha,
            "mailbox_ref": mailbox_ref,
            "mailbox_tip": mailbox_sha,
            "host": host_name,
            "cgmd_hub": {
                "worker_state": (mailbox_worker or {}).get("state", "unknown"),
                "last_report_at": worker_stamp,
                "last_report_age_seconds": round(worker_age_s, 1) if worker_age_s is not None else None,
                "alive_recently": bool(worker_age_s is not None and worker_age_s < 5400),
                "heartbeat": heartbeat,
                "recent_jobs": ((mailbox_worker or {}).get("recent") or [])[:6],
            },
            "selfcheck_summary": (selfcheck or {}).get("summary"),
            "selfcheck_overall": (selfcheck or {}).get("overall"),
            "versions": (selfcheck or {}).get("versions"),
            "desk": (selfcheck or {}).get("desk") or (desksync or {}).get("desk"),
            "smoke_summary": {
                "status": (smoke or {}).get("status"),
                "ps_completed": (smoke or {}).get("ps_completed"),
                "accelerator": (smoke or {}).get("accelerator") or "gpu",
                "ns_per_day": _extract_smoke_ns_per_day(smoke),
                "generated_at": (smoke or {}).get("generated_at"),
            } if smoke else None,
            "mailbox_queue": {
                "pending_count": len(inbox_ids),
                "done_count": len(outbox_ids),
                "pending": inbox_ids,
                "latest_outbox": {
                    "id": latest_outbox.get("id"),
                    "kind": latest_outbox.get("kind"),
                    "status": latest_outbox.get("status"),
                    "summary": latest_outbox.get("summary"),
                    "finished_at": latest_outbox.get("finished_at"),
                } if latest_outbox else None,
            },
            "lan_discovery": {
                "ips": lan_ips,
                "bridge_port": bridge_port,
            },
            "desktop_base_audit": {
                "has_git_sync_default": watcher_ps1 is not None,
                "issues_in_0fuye_branch": watcher_issues,
                "repaired_in_jevharness": True,
                "repaired_installer": "skills/desktop-hub/desktop-base/install_desktop_default_hub.ps1",
            },
        }


# ---------------------------------------------------------------------------
# 2. LAN / Tailscale Direct HTTP Bridge (core.desk_bridge compatible)
# ---------------------------------------------------------------------------
def tcp_reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _bridge_http(
    host: str,
    port: int,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    token: str = "",
    timeout: float = 15.0,
) -> dict[str, Any]:
    body: bytes | None = None
    headers = {"Accept": "application/json", "User-Agent": "jevharness-desktop-hub/1.0"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    if token:
        headers["X-CGMD-Token"] = token
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
    except OSError as exc:
        raise BridgeUnreachableError(f"cannot reach {host}:{port} ({exc})") from exc
    finally:
        conn.close()
    text = raw.decode("utf-8", "replace")
    try:
        doc = json.loads(text) if text.strip() else {}
    except ValueError:
        doc = {"status": "error", "summary": text[:400]}
    if not isinstance(doc, dict):
        doc = {"status": "error", "summary": str(doc)[:400]}
    if resp.status >= 400:
        doc.setdefault("status", "error")
        doc["http_status"] = resp.status
    return doc


def lan_ping(host: str, port: int = DEFAULT_BRIDGE_PORT, *, token: str = "", timeout: float = 5.0) -> dict[str, Any]:
    return _bridge_http(host, port, "GET", "/health", token=token, timeout=timeout)


def lan_status(host: str, port: int = DEFAULT_BRIDGE_PORT, *, token: str = "", timeout: float = 10.0) -> dict[str, Any]:
    return _bridge_http(host, port, "GET", "/status", token=token, timeout=timeout)


def lan_job(
    host: str,
    kind: str,
    args: dict[str, Any] | None = None,
    *,
    port: int = DEFAULT_BRIDGE_PORT,
    token: str = "",
    timeout: float = 60.0,
) -> dict[str, Any]:
    if kind == "gmx":
        validate_gmx_argv(list((args or {}).get("argv") or []))
    return _bridge_http(
        host,
        port,
        "POST",
        "/job",
        payload={"kind": kind, "args": args or {}},
        token=token,
        timeout=timeout,
    )


def validate_gmx_argv(argv: list[str]) -> None:
    if not argv:
        raise DesktopHubError("gmx requires at least one argument (e.g. --version)")
    if argv[0] not in GMX_ALLOWLIST:
        raise DesktopHubError(f"gmx subcommand not in allowlist: {argv[0]!r}")
    for word in argv:
        if re.search(r"[;&|<>`]|\$\(", word):
            raise DesktopHubError(f"shell metacharacters are forbidden in gmx argument: {word!r}")


def probe_lan_candidates(
    hosts: list[str] | tuple[str, ...] = DEFAULT_CANDIDATE_HOSTS,
    port: int = DEFAULT_BRIDGE_PORT,
    *,
    token: str = "",
    connect_timeout: float = 1.2,
) -> dict[str, Any]:
    """Quickly test candidate LAN/Tailscale IPs without blocking when offline."""
    attempts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for host in hosts:
        h = host.strip()
        if not h or h in seen:
            continue
        seen.add(h)
        if not tcp_reachable(h, port, timeout=connect_timeout):
            attempts.append({"host": h, "port": port, "reachable": False})
            continue
        try:
            health = lan_ping(h, port, token=token, timeout=max(3.0, connect_timeout * 2))
            attempts.append({"host": h, "port": port, "reachable": True, "health": health})
            return {"connected": True, "host": h, "port": port, "health": health, "attempts": attempts}
        except BridgeUnreachableError as exc:
            attempts.append({"host": h, "port": port, "reachable": False, "error": str(exc)})
    return {"connected": False, "host": None, "port": port, "attempts": attempts}


# ---------------------------------------------------------------------------
# 3. Desktop Base (git-sync-hub / 台式机的基座) Handshake & Receipt Protocol
# ---------------------------------------------------------------------------
def build_handshake_payload(
    *,
    round_num: int = 1,
    note: str = "JevHarness desktop-hub connectivity handshake",
    source_branch: str = "",
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_HANDSHAKE,
        "round": int(round_num),
        "arena_state": "ready",
        "local_state": "pending",
        "requested_at": beijing_now_iso(),
        "requested_at_utc": utc_now_iso(),
        "source_branch": source_branch,
        "note": note,
    }


def write_handshake(
    repo_root: str | Path = ".",
    *,
    round_num: int = 1,
    note: str = "JevHarness desktop-hub connectivity handshake",
) -> Path:
    """Write a pure-data handshake.json (zero executable commands) for git-sync-hub."""
    root = resolve_repo_root(repo_root)
    branch = current_branch(root)
    payload = build_handshake_payload(round_num=round_num, note=note, source_branch=branch)
    target = root / HANDSHAKE_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def build_hub_task_payload(
    *,
    note: str = "",
    write_files: list[dict[str, str]] | None = None,
    copy_files: list[dict[str, str]] | None = None,
    powershell: list[str] | None = None,
    python_cmds: list[str] | None = None,
    bash_cmds: list[str] | None = None,
    allow_exec: bool = False,
) -> dict[str, Any]:
    has_exec = any([powershell, python_cmds, bash_cmds])
    if has_exec and not allow_exec:
        raise DesktopHubError(
            "Command execution fields (powershell/python/bash) require explicit allow_exec=True (--allow-exec)."
        )
    payload: dict[str, Any] = {
        "enabled": True,
        "status": "pending",
        "requested_at": beijing_now_iso(),
        "note": note,
    }
    if write_files:
        payload["write_files"] = write_files
    if copy_files:
        payload["copy_files"] = copy_files
    if powershell:
        payload["powershell"] = powershell
    if python_cmds:
        payload["python"] = python_cmds
    if bash_cmds:
        payload["bash"] = bash_cmds
    return payload


def read_base_status(repo_root: str | Path = ".") -> dict[str, Any]:
    """Inspect local handshake and git-sync-hub receipt status with strict provenance."""
    root = resolve_repo_root(repo_root)
    hs_path = root / HANDSHAKE_REL_PATH
    rc_path = root / RECEIPT_REL_PATH
    out_path = root / EXEC_OUTPUT_REL_PATH

    handshake: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    exec_output: str | None = None

    if hs_path.is_file():
        try:
            handshake = json.loads(hs_path.read_text(encoding="utf-8-sig"))
        except ValueError:
            handshake = None
    if rc_path.is_file():
        try:
            receipt = json.loads(rc_path.read_text(encoding="utf-8-sig"))
        except ValueError:
            receipt = None
    if out_path.is_file():
        exec_output = out_path.read_text(encoding="utf-8-sig", errors="replace")[-4000:]

    commit_in_history = False
    source_commit = str((receipt or {}).get("source_commit") or "").strip()
    if source_commit and re.fullmatch(r"[0-9a-fA-F]{7,40}", source_commit):
        code, _, _ = _run_git(root, ["cat-file", "-e", f"{source_commit}^{{commit}}"], timeout=5)
        commit_in_history = code == 0

    return {
        "repo_root": str(root),
        "branch": current_branch(root),
        "head": current_head_sha(root),
        "has_handshake": handshake is not None,
        "has_receipt": receipt is not None,
        "receipt_commit_verified_in_git": commit_in_history,
        "host": (receipt or {}).get("host") or (handshake or {}).get("host"),
        "local_state": (handshake or {}).get("local_state"),
        "synced_at_utc": (receipt or {}).get("synced_at_utc"),
        "local_results_dir": (receipt or {}).get("local_results_dir"),
        "handshake": handshake,
        "receipt": receipt,
        "exec_output_tail": exec_output,
    }


def wait_for_base_receipt(
    repo_root: str | Path = ".",
    *,
    remote: str = "origin",
    branch: str | None = None,
    expected_source_sha: str | None = None,
    timeout: int = 70,
    interval: int = 12,
    pull_on_receipt: bool = True,
) -> dict[str, Any]:
    """Wait for git-sync-hub to push hub_sync_receipt.json onto remote/<branch>."""
    root = resolve_repo_root(repo_root)
    target_branch = branch or current_branch(root)
    started = time.monotonic()
    polls = 0

    while True:
        polls += 1
        code, _, err = _run_git(
            root,
            ["fetch", "--quiet", remote, target_branch],
            timeout=25,
        )
        if code == 0:
            remote_ref = f"{remote}/{target_branch}"
            receipt = _read_git_blob_json(root, remote_ref, RECEIPT_REL_PATH)
            if receipt and receipt.get("status") == "synced":
                src = str(receipt.get("source_commit") or "")
                matches = True
                if expected_source_sha:
                    matches = src.startswith(expected_source_sha[:7]) or expected_source_sha.startswith(src[:7])
                if matches:
                    pulled = False
                    if pull_on_receipt:
                        c_pull, _, _ = _run_git(
                            root,
                            ["pull", "--rebase", "--quiet", remote, target_branch],
                            timeout=30,
                        )
                        pulled = c_pull == 0
                    return {
                        "status": "ok",
                        "verified_live_in_session": True,
                        "polls": polls,
                        "elapsed_seconds": round(time.monotonic() - started, 1),
                        "pulled": pulled,
                        "receipt": receipt,
                    }
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            return {
                "status": "timeout",
                "verified_live_in_session": False,
                "polls": polls,
                "elapsed_seconds": round(elapsed, 1),
                "branch": target_branch,
                "summary": (
                    f"No new {RECEIPT_REL_PATH} appeared on {remote}/{target_branch} within {timeout}s."
                ),
            }
        time.sleep(min(interval, max(1.0, timeout - elapsed)))


# ---------------------------------------------------------------------------
# 4. 0fuye Mailbox Protocol (cgmd.mailbox.request.v1 / result.v1)
# ---------------------------------------------------------------------------
def new_mailbox_job_id() -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S')}-{random.randint(0, 0xFFFF):04x}"


def _check_mailbox_push_allowed(repo: Path, ref: str, *, allow_cross_branch_push: bool) -> None:
    """Enforce session branch lock unless explicitly unlocked on a 0fuye checkout."""
    locked = os.environ.get("JEV_LOCKED_BRANCH", "").strip()
    if locked and ref != locked and not allow_cross_branch_push:
        raise DesktopHubError(
            f"Refusing to push to ref {ref!r} while JEV_LOCKED_BRANCH={locked!r} is set."
        )
    c_url, out_url, _ = _run_git(repo, ["remote", "get-url", "origin"], timeout=5)
    origin_url = out_url.decode("utf-8", "replace").strip() if c_url == 0 else ""
    if "0fuye" not in origin_url and not allow_cross_branch_push:
        raise DesktopHubError(
            f"Origin {origin_url!r} is not hukeying85-ux/0fuye. "
            "In JevHarness or other repos, use 'base-handshake' (git-sync-hub on your own branch), "
            "'probe-0fuye' (read-only), or 'lan-ping' instead of pushing to foreign branches."
        )


def mailbox_push_files(
    repo: str | Path,
    *,
    ref: str = DEFAULT_MAILBOX_REF,
    adds: dict[str, bytes],
    removes: list[str] | None = None,
    message: str,
    remote: str = "origin",
    allow_cross_branch_push: bool = False,
    attempts: int = 4,
) -> str:
    root = resolve_repo_root(repo)
    _check_mailbox_push_allowed(root, ref, allow_cross_branch_push=allow_cross_branch_push)
    tracking = f"refs/remotes/{remote}/{ref}"
    last_err = ""

    for attempt in range(attempts):
        code_f, _, err_f = _run_git(
            root,
            ["fetch", "--quiet", remote, f"+refs/heads/{ref}:{tracking}"],
            timeout=30,
        )
        base_sha: str | None = None
        if code_f == 0:
            c_rev, out_rev, _ = _run_git(root, ["rev-parse", "--verify", tracking], timeout=5)
            if c_rev == 0:
                base_sha = out_rev.decode("utf-8").strip()
        else:
            err_txt = err_f.decode("utf-8", "replace")
            if not any(tok in err_txt for tok in ("couldn't find remote ref", "no such remote ref", "not our ref")):
                raise DesktopHubError(f"mailbox fetch failed: {err_txt.strip()[:300]}")

        with tempfile.TemporaryDirectory(prefix="jev-mailbox-idx-") as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            _git_checked(root, ["read-tree", base_sha] if base_sha else ["read-tree", "--empty"], env=env)
            for rel_path, blob_bytes in adds.items():
                blob = _git_checked(
                    root, ["hash-object", "-w", "--stdin"], stdin_bytes=blob_bytes, env=env
                ).decode("utf-8").strip()
                _git_checked(root, ["update-index", "--add", "--cacheinfo", f"100644,{blob},{rel_path}"], env=env)
            for rel_path in removes or []:
                _run_git(root, ["update-index", "--force-remove", rel_path], env=env)
            tree = _git_checked(root, ["write-tree"], env=env).decode("utf-8").strip()
            commit_args = [
                "-c", "user.name=CGMD-Desk",
                "-c", "user.email=hukeying85-ux@users.noreply.github.com",
                "commit-tree", tree, "-m", message,
            ]
            if base_sha:
                commit_args.extend(["-p", base_sha])
            commit_sha = _git_checked(root, commit_args, env=env).decode("utf-8").strip()
            c_push, out_p, err_p = _run_git(
                root,
                ["push", "--quiet", remote, f"{commit_sha}:refs/heads/{ref}"],
                timeout=45,
            )
            if c_push == 0:
                _run_git(root, ["update-ref", tracking, commit_sha], timeout=5)
                return commit_sha
            last_err = (err_p or out_p).decode("utf-8", "replace").strip()[:300]
        time.sleep(1.5 + attempt)
    raise DesktopHubError(f"mailbox push failed after {attempts} attempts: {last_err}")


def mailbox_send(
    repo: str | Path,
    kind: str,
    args: dict[str, Any] | None = None,
    *,
    note: str = "",
    ref: str = DEFAULT_MAILBOX_REF,
    remote: str = "origin",
    timeout_s: int = 1800,
    allow_cross_branch_push: bool = False,
) -> str:
    if kind not in MAILBOX_KINDS:
        raise DesktopHubError(f"Unknown mailbox job kind {kind!r}; choose from {', '.join(MAILBOX_KINDS)}")
    if kind == "gmx":
        validate_gmx_argv(list((args or {}).get("argv") or []))
    job_id = new_mailbox_job_id()
    req = {
        "schema": SCHEMA_MAILBOX_REQUEST,
        "id": job_id,
        "kind": kind,
        "args": args or {},
        "note": note,
        "from": os.environ.get("USER") or os.environ.get("USERNAME") or "jevharness",
        "host": socket.gethostname(),
        "created_at": beijing_now_iso(),
        "timeout_s": int(timeout_s),
    }
    body = json.dumps(req, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    mailbox_push_files(
        repo,
        ref=ref,
        adds={f"inbox/{job_id}.json": body},
        message=f"mailbox: request {job_id} ({kind})",
        remote=remote,
        allow_cross_branch_push=allow_cross_branch_push,
    )
    return job_id


def mailbox_read_remote_job(
    job_id: str,
    *,
    repo_url: str = DEFAULT_0FUYE_REPO,
    ref: str = DEFAULT_MAILBOX_REF,
    timeout: int = 30,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="jev-mb-show-") as tmp:
        _git_checked(tmp, ["init", "--bare", "--quiet"], timeout=10)
        code, _, _ = _run_git(
            tmp,
            ["fetch", "--quiet", "--depth", "1", repo_url, f"+refs/heads/{ref}:refs/remotes/probe/mailbox"],
            timeout=timeout,
        )
        if code != 0:
            return {"id": job_id, "status": "lost", "summary": f"mailbox ref {ref} not reachable"}
        sha = _git_checked(tmp, ["rev-parse", "refs/remotes/probe/mailbox"]).decode("utf-8").strip()
        outbox = _read_git_blob_json(tmp, sha, f"outbox/{job_id}.json")
        if outbox:
            return outbox
        inbox = _read_git_blob_json(tmp, sha, f"inbox/{job_id}.json")
        if inbox:
            return {"id": job_id, "status": "pending", "request": inbox}
        return {"id": job_id, "status": "lost", "summary": f"job {job_id} not found on {ref}"}


# ---------------------------------------------------------------------------
# 5. Smart Combined Diagnostic (LAN -> Desktop Base -> 0fuye Telemetry)
# ---------------------------------------------------------------------------
def smart_status(
    repo_root: str | Path = ".",
    *,
    repo_url_0fuye: str = DEFAULT_0FUYE_REPO,
    branch_0fuye: str = DEFAULT_0FUYE_BRANCH,
    probe_lan: bool = True,
) -> dict[str, Any]:
    """Build an evidence-separated diagnostic across all three desktop channels."""
    base = read_base_status(repo_root)
    remote_0fuye = probe_0fuye_remote(repo_url=repo_url_0fuye, branch=branch_0fuye)

    discovered_ips = list(remote_0fuye.get("lan_discovery", {}).get("ips") or [])
    candidate_ips = discovered_ips + [ip for ip in DEFAULT_CANDIDATE_HOSTS if ip not in discovered_ips]
    bridge_port = int(remote_0fuye.get("lan_discovery", {}).get("bridge_port") or DEFAULT_BRIDGE_PORT)
    lan = probe_lan_candidates(candidate_ips, port=bridge_port) if probe_lan else {"connected": False, "skipped": True}

    return {
        "checked_at": beijing_now_iso(),
        "channels": {
            "lan_bridge": lan,
            "desktop_base_git_sync": base,
            "remote_0fuye_telemetry": remote_0fuye,
        },
        "recommended_channel": (
            "lan_bridge"
            if lan.get("connected")
            else "desktop_base_git_sync"
            if (base.get("has_receipt") and base.get("receipt_commit_verified_in_git"))
            else "0fuye_cgmd_hub"
        ),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_json(data: Any) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jev-desktop-hub",
        description="Hands-free bridge to the Windows GPU workstation (0fuye + desktop-base + LAN bridge).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    st_p = sub.add_parser("status", help="Combined live diagnostic across LAN bridge, git-sync-hub, and 0fuye")
    st_p.add_argument("--repo", default=".", help="Local checkout path (default: .)")
    st_p.add_argument("--no-lan", action="store_true", help="Skip LAN TCP probe")
    st_p.add_argument("--0fuye-url", dest="url_0fuye", default=DEFAULT_0FUYE_REPO)
    st_p.add_argument("--0fuye-branch", dest="branch_0fuye", default=DEFAULT_0FUYE_BRANCH)

    pr_p = sub.add_parser("probe-0fuye", help="Read-only live telemetry probe of hukeying85-ux/0fuye")
    pr_p.add_argument("--url", default=DEFAULT_0FUYE_REPO)
    pr_p.add_argument("--branch", default=DEFAULT_0FUYE_BRANCH)
    pr_p.add_argument("--mailbox-ref", default=DEFAULT_MAILBOX_REF)

    hs_p = sub.add_parser("base-handshake", help="Write pure-data results/status/handshake.json for git-sync-hub")
    hs_p.add_argument("--repo", default=".")
    hs_p.add_argument("--round", type=int, default=1)
    hs_p.add_argument("--note", default="JevHarness desktop-hub connectivity handshake")

    bs_p = sub.add_parser("base-status", help="Inspect local handshake and git-sync-hub receipt status")
    bs_p.add_argument("--repo", default=".")

    bw_p = sub.add_parser("base-wait", help="Wait for git-sync-hub to push hub_sync_receipt.json to origin/<branch>")
    bw_p.add_argument("--repo", default=".")
    bw_p.add_argument("--remote", default="origin")
    bw_p.add_argument("--branch", default="")
    bw_p.add_argument("--expected-sha", default="")
    bw_p.add_argument("--timeout", type=int, default=70)
    bw_p.add_argument("--interval", type=int, default=12)
    bw_p.add_argument("--no-pull", action="store_true")

    lp_p = sub.add_parser("lan-ping", help="Ping the workstation LAN HTTP bridge (:8765)")
    lp_p.add_argument("--host", default="", help="Workstation IP (auto-probes candidates if omitted)")
    lp_p.add_argument("--port", type=int, default=DEFAULT_BRIDGE_PORT)
    lp_p.add_argument("--token", default="")
    lp_p.add_argument("--timeout", type=float, default=5.0)

    lj_p = sub.add_parser("lan-job", help="Run a job (ping/smoke/selfcheck/gmx) over the LAN HTTP bridge")
    lj_p.add_argument("--host", required=True)
    lj_p.add_argument("--port", type=int, default=DEFAULT_BRIDGE_PORT)
    lj_p.add_argument("--token", default="")
    lj_p.add_argument("--kind", required=True, choices=["ping", "smoke", "selfcheck", "gmx"])
    lj_p.add_argument("--json-args", default="{}")
    lj_p.add_argument("--arg", action="append", default=[])
    lj_p.add_argument("--timeout", type=float, default=900.0)

    ms_p = sub.add_parser("mailbox-show", help="Read one job result from hukeying85-ux/0fuye hub/mailbox (read-only)")
    ms_p.add_argument("job_id")
    ms_p.add_argument("--url", default=DEFAULT_0FUYE_REPO)
    ms_p.add_argument("--ref", default=DEFAULT_MAILBOX_REF)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "status":
            _print_json(
                smart_status(
                    args.repo,
                    repo_url_0fuye=args.url_0fuye,
                    branch_0fuye=args.branch_0fuye,
                    probe_lan=not args.no_lan,
                )
            )
            return 0

        if args.command == "probe-0fuye":
            _print_json(
                probe_0fuye_remote(
                    repo_url=args.url,
                    branch=args.branch,
                    mailbox_ref=args.mailbox_ref,
                )
            )
            return 0

        if args.command == "base-handshake":
            written = write_handshake(args.repo, round_num=args.round, note=args.note)
            _print_json({"status": "ok", "written": str(written)})
            return 0

        if args.command == "base-status":
            _print_json(read_base_status(args.repo))
            return 0

        if args.command == "base-wait":
            res = wait_for_base_receipt(
                args.repo,
                remote=args.remote,
                branch=args.branch or None,
                expected_source_sha=args.expected_sha or None,
                timeout=args.timeout,
                interval=args.interval,
                pull_on_receipt=not args.no_pull,
            )
            _print_json(res)
            return 0 if res.get("status") == "ok" else 6

        if args.command == "lan-ping":
            if args.host:
                _print_json(lan_ping(args.host, args.port, token=args.token, timeout=args.timeout))
                return 0
            res = probe_lan_candidates(port=args.port, token=args.token)
            _print_json(res)
            return 0 if res.get("connected") else 3

        if args.command == "lan-job":
            payload = json.loads(args.json_args) if args.json_args else {}
            if args.arg:
                payload = dict(payload, argv=list(args.arg))
            doc = lan_job(args.host, args.kind, payload, port=args.port, token=args.token, timeout=args.timeout)
            _print_json(doc)
            return 0 if doc.get("status") == "ok" else 6

        if args.command == "mailbox-show":
            doc = mailbox_read_remote_job(args.job_id, repo_url=args.url, ref=args.ref)
            _print_json(doc)
            return 0 if doc.get("status") == "ok" else 6

    except DesktopHubError as exc:
        _print_json({"status": "error", "error": str(exc)})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
