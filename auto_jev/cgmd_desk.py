"""Client-only SDK & CLI for the 0fuye desktop hub on DESKTOP-IEUDGS5.

Follows the strict single-base contract in ``hukeying85-ux/0fuye``
(branch ``arena/32cd826e-0fuye``, ``docs/new_session_prompt_zh.md``):

* **Never** installs a second watcher or desktop-base script.
* **Never** commits or pushes to working branches of ``0fuye``; dispatches
  exclusively through ``core.desk_bridge`` (LAN ``:8765``) or
  ``core.hub_mailbox`` (dedicated ref ``hub/mailbox``).
* Automatically skips unreachable LAN probes inside cloud sandboxes so calls
  never stall for minutes on ``192.168.x.x`` / ``100.84.x.x``.
* Detects Arena.ai's per-repository GitHub App token scope (`HTTP 403`) when
  dispatching from a non-``0fuye`` cloud sandbox, distinguishing platform
  token isolation from desktop worker downtime without ever asking the user
  to paste commands on ``DESKTOP-IEUDGS5``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

UPSTREAM_REPO = "hukeying85-ux/0fuye"
UPSTREAM_URL = f"https://github.com/{UPSTREAM_REPO}.git"
UPSTREAM_BRANCH = "arena/32cd826e-0fuye"
MAILBOX_REF = "hub/mailbox"
DESKTOP_HOST = "DESKTOP-IEUDGS5"
DEFAULT_BRIDGE_PORT = 8765
KNOWN_LAN_HOSTS = ("192.168.110.226", "100.84.137.117")

FORBIDDEN_TRAJECTORY_EXTENSIONS = frozenset({
    ".xtc", ".trr", ".tpr", ".gro", ".edr", ".edv", ".cpt", ".h5", ".dcd",
})
FORBIDDEN_SECOND_WATCHER_EXTENSIONS = frozenset({
    ".ps1", ".vbs", ".cs",
})


class DeskClientError(RuntimeError):
    """Raised when the 0fuye client checkout cannot be prepared or verified."""


def _run_cmd(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
) -> tuple[int, str, str]:
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out_b, err_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out_b, err_b = proc.communicate()
        return 124, out_b.decode("utf-8", "replace"), err_b.decode("utf-8", "replace") + "\ntimed out"
    return (
        proc.returncode,
        out_b.decode("utf-8", "replace"),
        err_b.decode("utf-8", "replace"),
    )


def _normalise_github_repo(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if cleaned.lower().startswith(prefix):
            return cleaned[len(prefix):]
    return cleaned


def default_client_candidates(project_root: Path | None = None) -> list[Path]:
    """Ordered candidate locations for the read-only 0fuye client checkout."""
    root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    candidates: list[Path] = []
    env_dir = os.environ.get("CGMD_0FUYE_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir).expanduser().resolve())
    sibling = root.parent / "0fuye"
    candidates.append(sibling)
    candidates.append(root / ".cache" / "0fuye")
    return candidates


def verify_origin_locked(checkout: Path, expected_repo: str = UPSTREAM_REPO) -> str:
    code, out, err = _run_cmd(["git", "remote", "get-url", "origin"], cwd=checkout, timeout=15)
    if code != 0:
        raise DeskClientError(f"git remote get-url origin failed in {checkout}: {(err or out).strip()}")
    actual = _normalise_github_repo(out)
    if actual.lower() != expected_repo.lower():
        raise DeskClientError(
            f"Refusing untrusted 0fuye checkout {checkout}: origin is {out.strip()!r}, expected {expected_repo!r}"
        )
    return out.strip()


def ensure_0fuye_client(
    checkout_dir: Path | str | None = None,
    *,
    branch: str = UPSTREAM_BRANCH,
    mailbox_ref: str = MAILBOX_REF,
    sync: bool = True,
) -> Path:
    """Locate or clone ``hukeying85-ux/0fuye`` as a pure read-only client."""
    target: Path | None = None
    if checkout_dir is not None:
        target = Path(checkout_dir).expanduser().resolve()
    else:
        candidates = default_client_candidates()
        for cand in candidates:
            if (cand / ".git").exists():
                target = cand
                break
        if target is None:
            # Prefer sibling /home/user/0fuye when writable so workspace snapshots
            # retain the 5 MB client without dirtying JevHarness's git tree.
            sibling = candidates[-2]
            cache_dir = candidates[-1]
            target = sibling if os.access(sibling.parent, os.W_OK) else cache_dir

    if not (target / ".git").exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        code, out, err = _run_cmd(
            ["git", "clone", "--quiet", "-b", branch, UPSTREAM_URL, str(target)],
            timeout=180,
        )
        if code != 0:
            raise DeskClientError(f"Failed to clone {UPSTREAM_URL}@{branch}: {(err or out).strip()}")

    verify_origin_locked(target)

    if sync:
        code, out, err = _run_cmd(["git", "fetch", "--quiet", "origin", branch], cwd=target, timeout=60)
        if code == 0:
            status_rc, status_out, _ = _run_cmd(["git", "status", "--porcelain"], cwd=target, timeout=15)
            if status_rc == 0 and not status_out.strip():
                _run_cmd(["git", "reset", "--quiet", "--hard", f"origin/{branch}"], cwd=target, timeout=30)
        _run_cmd(
            ["git", "fetch", "--quiet", "origin", f"+refs/heads/{mailbox_ref}:refs/remotes/origin/{mailbox_ref}"],
            cwd=target,
            timeout=60,
        )
    return target


def load_0fuye_modules(checkout: Path) -> tuple[Any, Any]:
    """Import ``core.hub_mailbox`` and ``core.desk_bridge`` from ``checkout``."""
    checkout_str = str(checkout.resolve())
    if checkout_str not in sys.path:
        sys.path.insert(0, checkout_str)
    hub_mailbox = importlib.import_module("core.hub_mailbox")
    desk_bridge = importlib.import_module("core.desk_bridge")
    return hub_mailbox, desk_bridge


def is_cloud_sandbox(env: dict[str, str] | None = None) -> bool:
    """Detect restricted Linux cloud sandboxes that cannot route to LAN :8765."""
    environ = env if env is not None else dict(os.environ)
    if os.name == "nt":
        return False
    if environ.get("CGMD_FORCE_LAN") == "1":
        return False
    if Path("/home/user").is_dir() and (
        environ.get("GH_TOKEN", "").startswith(("ghu_", "ghs_"))
        or environ.get("E2B_SANDBOX_ID")
        or Path("/.dockerenv").exists()
        or environ.get("USER") == "user"
    ):
        return True
    return False


def diagnose_cross_repo_push_block(
    error_text: str,
    *,
    hub_repo: str = UPSTREAM_REPO,
) -> dict[str, Any]:
    """Classify a git push failure on ``0fuye`` without guessing."""
    lowered = (error_text or "").lower()
    http_403 = "403" in lowered or "permission to" in lowered or "denied to" in lowered
    gh_probe: dict[str, Any] = {"checked": False}
    if http_403 and shutil.which("gh"):
        rc, out, err = _run_cmd(
            ["gh", "api", "-X", "POST", f"repos/{hub_repo}/git/blobs", "-f", "content=probe", "-f", "encoding=utf-8"],
            timeout=20,
        )
        combined = f"{out}\n{err}"
        gh_probe = {
            "checked": True,
            "returncode": rc,
            "resource_not_accessible_by_integration": "Resource not accessible by integration" in combined,
            "detail": combined.strip()[:300],
        }
    is_arena_scoped_token = http_403 and (
        gh_probe.get("resource_not_accessible_by_integration", False)
        or "permission to hukeying85-ux/0fuye.git denied" in lowered
    )
    return {
        "http_403": http_403,
        "arena_repo_scoped_token": is_arena_scoped_token,
        "desktop_worker_fault": False if is_arena_scoped_token else None,
        "user_paste_required": False,
        "gh_probe": gh_probe,
        "explanation": (
            "Arena.ai mints a single-repository GitHub App token (arena-ai-coding-agent) "
            f"scoped only to the active session's repository, so git push to {hub_repo} "
            "(refs/heads/hub/mailbox) is rejected by GitHub with HTTP 403 before reaching "
            "the mailbox queue. DESKTOP-IEUDGS5 itself is online and requires zero user commands."
            if is_arena_scoped_token
            else error_text.strip()[:400]
        ),
    }


def verify_smoke_result(
    result: dict[str, Any],
    *,
    expected_ps: float = 100.0,
) -> dict[str, Any]:
    """Verify every acceptance assertion from ``docs/new_session_prompt_zh.md`` §1 Step 2."""
    detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
    report = detail.get("report") if isinstance(detail.get("report"), dict) else {}
    if not report and result.get("schema") == "cgmd.gmxsmoke.v1":
        # Allow validating raw results/status/gmx_smoke.json directly as well.
        report = result
    mdrun = report.get("mdrun") if isinstance(report.get("mdrun"), dict) else {}
    stages = report.get("stages") if isinstance(report.get("stages"), list) else []

    gpu_stage = next(
        (st for st in stages if isinstance(st, dict) and st.get("stage") == "mdrun-md-gpu"),
        None,
    )
    perf = mdrun.get("performance_ns_per_day")
    perf_ok = isinstance(perf, (int, float)) and float(perf) > 0.0

    checks = {
        "result.status == 'ok'": result.get("status") == "ok",
        f"result.detail.report.ps_completed == {int(expected_ps) if float(expected_ps).is_integer() else expected_ps}": (
            report.get("ps_completed") == expected_ps
        ),
        "result.detail.report.mdrun.finished == True": mdrun.get("finished") is True,
        "result.detail.report.mdrun.performance_ns_per_day > 0": perf_ok,
        "result.detail.report.accelerator == 'gpu'": report.get("accelerator") == "gpu",
        "stages['mdrun-md-gpu'].returncode == 0": (
            isinstance(gpu_stage, dict) and gpu_stage.get("returncode") == 0
        ),
    }
    return {
        "all_passed": all(checks.values()),
        "checks": checks,
        "job_id": result.get("id"),
        "finished_at": result.get("finished_at") or report.get("generated_at"),
        "ps_completed": report.get("ps_completed"),
        "performance_ns_per_day": perf,
        "accelerator": report.get("accelerator"),
        "gpu_stage_seconds": gpu_stage.get("seconds") if isinstance(gpu_stage, dict) else None,
        "seconds_total": report.get("seconds_total") or result.get("seconds"),
    }


def _parse_iso_timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def latest_outbox_by_kind(
    checkout: Path,
    kind: str,
    *,
    mailbox_ref: str = MAILBOX_REF,
) -> dict[str, Any] | None:
    """Return the most recent completed ``outbox/<id>.json`` matching ``kind``."""
    hub_mailbox, _ = load_0fuye_modules(checkout)
    snap = hub_mailbox.snapshot(str(checkout), ref=mailbox_ref)
    best_doc: dict[str, Any] | None = None
    best_ts = -1.0
    for job_id in snap.get("done") or []:
        doc = hub_mailbox.read_result(str(checkout), job_id, ref=mailbox_ref)
        if not (isinstance(doc, dict) and doc.get("kind") == kind):
            continue
        ts = _parse_iso_timestamp(doc.get("finished_at") or doc.get("started_at"))
        if ts >= best_ts:
            best_ts = ts
            best_doc = doc
    return best_doc


def dispatch_job(
    kind: str,
    args: dict[str, Any] | None = None,
    *,
    checkout_dir: Path | str | None = None,
    lan_host: str = "",
    bridge_port: int = DEFAULT_BRIDGE_PORT,
    bridge_token: str = "",
    mailbox_ref: str = MAILBOX_REF,
    note: str = "",
    timeout: int = 1800,
    interval: int = 15,
) -> dict[str, Any]:
    """Dispatch a job following ``docs/new_session_prompt_zh.md`` §3 degradation:

    1. LAN bridge (``core.desk_bridge``, ``<1 s``) ONLY when ``lan_host`` is
       given and we are not inside an outbound-filtered cloud sandbox.
    2. Git mailbox (``core.hub_mailbox``, ``<=60 s``) on ``refs/heads/hub/mailbox``.
    """
    checkout = ensure_0fuye_client(checkout_dir, mailbox_ref=mailbox_ref, sync=True)
    hub_mailbox, desk_bridge = load_0fuye_modules(checkout)
    payload = dict(args or {})

    if lan_host and not is_cloud_sandbox():
        try:
            if kind == "ping":
                res = desk_bridge.ping(lan_host, port=bridge_port, token=bridge_token, timeout=min(timeout, 10))
            elif kind == "smoke":
                ps_val = float(payload.get("ps", 100))
                res = desk_bridge.smoke(lan_host, port=bridge_port, ps=ps_val, token=bridge_token, timeout=timeout)
            elif kind == "gmx":
                res = desk_bridge.gmx(
                    lan_host, bridge_port, list(payload.get("argv") or []), token=bridge_token, timeout=timeout
                )
            else:
                res = desk_bridge.job(lan_host, bridge_port, kind, payload, token=bridge_token, timeout=timeout)
            res.setdefault("transport", "desk_bridge")
            return res
        except desk_bridge.BridgeError:
            pass

    try:
        job_id = hub_mailbox.send(
            str(checkout),
            kind,
            payload,
            note=note,
            ref=mailbox_ref,
            timeout_s=timeout,
        )
    except hub_mailbox.MailboxError as exc:
        diag = diagnose_cross_repo_push_block(str(exc))
        return {
            "schema": hub_mailbox.SCHEMA_RESULT,
            "id": None,
            "kind": kind,
            "status": "blocked_by_token_scope" if diag["arena_repo_scoped_token"] else "error",
            "transport": "hub_mailbox",
            "summary": diag["explanation"],
            "diagnosis": diag,
            "latest_verified_on_mailbox": latest_outbox_by_kind(checkout, kind, mailbox_ref=mailbox_ref),
        }

    result = hub_mailbox.wait(
        str(checkout),
        job_id,
        ref=mailbox_ref,
        timeout=timeout,
        interval=interval,
        verbose=False,
    )
    result.setdefault("transport", "hub_mailbox")
    return result


def build_status_report(checkout_dir: Path | str | None = None, *, sync: bool = True) -> dict[str, Any]:
    """Assemble the complete §1 diagnostic & verification report from ``0fuye``."""
    checkout = ensure_0fuye_client(checkout_dir, sync=sync)
    hub_mailbox, _ = load_0fuye_modules(checkout)
    caps = hub_mailbox.capabilities(str(checkout), ref=MAILBOX_REF)
    snap = hub_mailbox.snapshot(str(checkout), ref=MAILBOX_REF)
    latest_ping = latest_outbox_by_kind(checkout, "ping")
    latest_smoke = latest_outbox_by_kind(checkout, "smoke")
    latest_deskdiag = latest_outbox_by_kind(checkout, "deskdiag")

    mailbox_status_path = checkout / "results" / "status" / "hub_mailbox.json"
    mailbox_worker = {}
    if mailbox_status_path.is_file():
        mailbox_worker = json.loads(mailbox_status_path.read_text(encoding="utf-8-sig"))

    smoke_verification = verify_smoke_result(latest_smoke) if isinstance(latest_smoke, dict) else None
    return {
        "client_checkout": str(checkout),
        "upstream_repo": UPSTREAM_REPO,
        "upstream_branch": UPSTREAM_BRANCH,
        "cloud_sandbox": is_cloud_sandbox(),
        "capabilities": caps,
        "mailbox_snapshot": {
            "ref": snap.get("ref"),
            "tip": snap.get("tip"),
            "pending_count": len(snap.get("pending") or []),
            "done_count": len(snap.get("done") or []),
        },
        "mailbox_worker_report": {
            "generated_at": mailbox_worker.get("generated_at"),
            "state": mailbox_worker.get("state"),
            "queued": mailbox_worker.get("queued"),
            "host": mailbox_worker.get("host"),
        },
        "latest_ping": latest_ping,
        "latest_smoke_verification": smoke_verification,
        "latest_deskdiag_summary": (
            {
                "id": latest_deskdiag.get("id"),
                "status": latest_deskdiag.get("status"),
                "summary": latest_deskdiag.get("summary"),
                "finished_at": latest_deskdiag.get("finished_at"),
                "boot_ack": (latest_deskdiag.get("detail") or {}).get("boot_ack"),
                "drift": (latest_deskdiag.get("detail") or {}).get("drift"),
            }
            if isinstance(latest_deskdiag, dict)
            else None
        ),
    }


def _print_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m auto_jev.cgmd_desk",
        description="Client-only 0fuye desktop hub adapter for DESKTOP-IEUDGS5",
    )
    parser.add_argument("--checkout", type=Path, help="Path to 0fuye client checkout")
    parser.add_argument("--no-sync", action="store_true", help="Read existing checkout without git fetch")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("caps", help="Read the 0fuye capability card (Step 0)")
    sub.add_parser("ls", help="List hub/mailbox pending and completed job IDs")
    sub.add_parser("report", help="Build full §1 status + verification summary")

    show_p = sub.add_parser("show", help="Show one outbox result by job ID or --latest-kind")
    show_p.add_argument("job_id", nargs="?", default="")
    show_p.add_argument("--latest-kind", default="", help="Show latest completed result of this kind")

    verify_p = sub.add_parser("verify-smoke", help="Verify Step 2 GPU smoke assertions")
    verify_p.add_argument("--job-id", default="", help="Specific smoke job ID on hub/mailbox")
    verify_p.add_argument("--ps", type=float, default=100.0, help="Expected simulated picoseconds")

    run_p = sub.add_parser("run", help="Dispatch a job via LAN bridge (if specified) or hub/mailbox")
    run_p.add_argument(
        "--kind",
        required=True,
        choices=("ping", "selfcheck", "smoke", "sync", "gmx", "deskdiag", "deskfix", "shell", "pipeline"),
    )
    run_p.add_argument("--json-args", default="{}", help="JSON object of job arguments")
    run_p.add_argument("--arg", action="append", default=[], help="Repeatable argv item for gmx")
    run_p.add_argument("--note", default="")
    run_p.add_argument("--timeout", type=int, default=1800)
    run_p.add_argument("--interval", type=int, default=15)
    run_p.add_argument("--lan-host", default="", help="Optional LAN/Tailscale IP for laptop sub-second bridge")
    run_p.add_argument("--bridge-port", type=int, default=DEFAULT_BRIDGE_PORT)

    args = parser.parse_args(argv)
    sync = not args.no_sync

    if args.command == "caps":
        checkout = ensure_0fuye_client(args.checkout, sync=sync)
        hub_mailbox, _ = load_0fuye_modules(checkout)
        _print_json(hub_mailbox.capabilities(str(checkout), ref=MAILBOX_REF))
        return 0

    if args.command == "ls":
        checkout = ensure_0fuye_client(args.checkout, sync=sync)
        hub_mailbox, _ = load_0fuye_modules(checkout)
        _print_json(hub_mailbox.snapshot(str(checkout), ref=MAILBOX_REF))
        return 0

    if args.command == "report":
        _print_json(build_status_report(args.checkout, sync=sync))
        return 0

    if args.command == "show":
        checkout = ensure_0fuye_client(args.checkout, sync=sync)
        hub_mailbox, _ = load_0fuye_modules(checkout)
        if args.latest_kind:
            doc = latest_outbox_by_kind(checkout, args.latest_kind)
        elif args.job_id:
            doc = hub_mailbox.read_result(str(checkout), args.job_id, ref=MAILBOX_REF)
        else:
            parser.error("Provide job_id or --latest-kind")
            return 2
        if doc is None:
            _print_json({"status": "not_found"})
            return 6
        _print_json(doc)
        return 0

    if args.command == "verify-smoke":
        checkout = ensure_0fuye_client(args.checkout, sync=sync)
        hub_mailbox, _ = load_0fuye_modules(checkout)
        if args.job_id:
            doc = hub_mailbox.read_result(str(checkout), args.job_id, ref=MAILBOX_REF)
        else:
            doc = latest_outbox_by_kind(checkout, "smoke")
        if not isinstance(doc, dict):
            smoke_file = checkout / "results" / "status" / "gmx_smoke.json"
            doc = json.loads(smoke_file.read_text(encoding="utf-8-sig")) if smoke_file.is_file() else {}
        verdict = verify_smoke_result(doc, expected_ps=args.ps)
        _print_json(verdict)
        return 0 if verdict["all_passed"] else 6

    if args.command == "run":
        payload = json.loads(args.json_args) if args.json_args else {}
        if args.arg:
            payload["argv"] = list(args.arg)
        result = dispatch_job(
            args.kind,
            payload,
            checkout_dir=args.checkout,
            lan_host=args.lan_host,
            bridge_port=args.bridge_port,
            note=args.note,
            timeout=args.timeout,
            interval=args.interval,
        )
        _print_json(result)
        return 0 if result.get("status") == "ok" else 6

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
