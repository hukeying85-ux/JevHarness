#!/usr/bin/env python3
"""desk-loop: one closed loop -- request -> (desk pulls & runs) -> push back -> verify -> repeat.

The workstation half is **not** installed by this script: the CGMD desk already
runs ``CGMD-Hub-Poll`` (60 s, silent), executes whitelisted job kinds and pushes
receipts back to ``hub/mailbox``.  This is the agent-side half only:

    request   put a job request on this repository's mailbox branch
    wait      poll the desk's mailbox branch until the answer lands (stop on arrival)
    criteria  decide, from the artefacts, whether the task really succeeded
    loop      request -> wait -> criteria, N rounds, stop at the first pass
    sync      branch guard -> stage guard -> gate -> commit -> push -> receipt
    recover   survive a sandbox .git reset (worktree kept, history replayed)
    handoff   print the card a new conversation needs to join the same loop

Design notes borrowed from the ``git-sync`` skill (mqgg5630-cyber/git-pull-arena
v2.8.1): config-driven branch/receipt/criteria, a hard branch guard that refuses
main/master, a declarative ``success_criteria.json`` evaluated with exit codes
0 = passed / 2 = failed / 3 = pending, a receipt file per sync, and a ``recover``
path for the case where the sandbox ``.git`` is reset to a baseline commit.
What is deliberately **not** copied: the Windows-side watcher/bootstrap
(``watch.ps1`` / ``bootstrap.ps1``) -- this repository already has a running
desk base and a second one is forbidden.
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(HERE)
REPO = os.path.dirname(SKILLS)
CONFIG_PATH = os.path.join(HERE, "sync.config.json")

EXIT_PASS, EXIT_FAIL, EXIT_PENDING, EXIT_USAGE = 0, 2, 3, 1
TRAJECTORY_PATTERNS = ("*.xtc", "*.trr", "*.tpr", "*.gro", "*.edr", "*.cpt", "*.xtc.gz", "*.h5")


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    sys.stderr.write("[desk-loop %s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def load_config(path: str = CONFIG_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.setdefault("repo", REPO)
    cfg.setdefault("remote", "origin")
    cfg.setdefault("outdir", "results/desktop")
    cfg.setdefault("receipt", "results/sync/last_sync.md")
    cfg.setdefault("criteria", "skills/desk-loop/success_criteria.json")
    return cfg


def git(args: List[str], cwd: Optional[str] = None, check: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git"] + args, cwd=cwd or REPO, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and proc.returncode != 0:
        raise SystemExit("[desk-loop] git %s failed:\n%s" % (" ".join(args), proc.stdout))
    return proc


def head_branch(cwd: Optional[str] = None) -> str:
    return git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()


def agent(cfg: Dict[str, Any], outdir: Optional[str] = None):
    """The transport lives in skills/cgmd-desktop; import it instead of copying it."""
    sys.path.insert(0, os.path.join(SKILLS, "cgmd-desktop"))
    import cgmd_agent  # noqa: WPS433  (deliberate late import)
    return cgmd_agent.Agent(
        repo=cfg.get("repo", REPO),
        desk=cfg.get("desk_clone", os.path.expanduser("~/.cache/cgmd-desk")),
        branch=cfg.get("desk_branch", "arena/32cd826e-0fuye"),
        desk_remote=cfg.get("desk_remote", "https://github.com/hukeying85-ux/0fuye.git"),
        outdir=os.path.abspath(outdir or cfg.get("outdir", "results/desktop")),
        answer_wait=int(cfg.get("answer_wait_s", 1500)),
        poll_interval=int(cfg.get("poll_interval_s", 20)),
    )


# --------------------------------------------------------------------------- #
# success criteria
# --------------------------------------------------------------------------- #
def evaluate(criteria_path: str, root: Optional[str] = None) -> Dict[str, Any]:
    """Evaluate a declarative criteria file.  See SKILL.md for the schema block."""
    root = root or REPO
    if not os.path.isfile(criteria_path):
        return {"status": "pending", "exit": EXIT_PENDING, "checks": [],
                "note": "criteria file missing: %s" % criteria_path}
    spec = json.load(open(criteria_path, encoding="utf-8"))
    checks: List[Dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    for pattern in spec.get("require_files", []):
        hits = glob.glob(os.path.join(root, pattern), recursive=True)
        add("require_files:%s" % pattern, bool(hits), "%d hit(s)" % len(hits))

    for pattern in spec.get("forbid_files", []):
        hits = glob.glob(os.path.join(root, pattern), recursive=True)
        add("forbid_files:%s" % pattern, not hits, "%d hit(s)" % len(hits))

    for path, needle in (spec.get("require_contains") or {}).items():
        full = os.path.join(root, path)
        text = open(full, encoding="utf-8", errors="replace").read() if os.path.isfile(full) else ""
        add("require_contains:%s" % path, needle in text, "looking for %r" % needle)

    for path, pattern in (spec.get("require_regex") or {}).items():
        full = os.path.join(root, path)
        text = open(full, encoding="utf-8", errors="replace").read() if os.path.isfile(full) else ""
        add("require_regex:%s" % path, bool(re.search(pattern, text)), pattern)

    for path, size in (spec.get("min_bytes") or {}).items():
        full = os.path.join(root, path)
        actual = os.path.getsize(full) if os.path.isfile(full) else 0
        add("min_bytes:%s" % path, actual >= size, "%d >= %d" % (actual, size))

    for rule in spec.get("require_json", []):
        pattern = rule.get("glob") or rule.get("path")
        hits = sorted(glob.glob(os.path.join(root, pattern), recursive=True)) if pattern else []
        if not hits:
            add("require_json:%s" % pattern, False, "no file matched")
            continue
        # newest matching artefact wins: the loop is about the latest run
        newest = max(hits, key=os.path.getmtime)
        try:
            data = json.load(open(newest, encoding="utf-8"))
        except Exception as exc:
            add("require_json:%s" % pattern, False, "unreadable: %s" % exc)
            continue
        value: Any = data
        for part in str(rule.get("field", "")).split("."):
            if not part:
                continue
            if isinstance(value, list):
                try:
                    value = value[int(part)]
                    continue
                except (ValueError, IndexError):
                    value = None
                    break
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        ok = True
        detail = "%s = %r" % (rule.get("field"), value)
        if "equals" in rule:
            ok = value == rule["equals"]
        if ok and "min" in rule:
            ok = isinstance(value, (int, float)) and value >= rule["min"]
        if ok and "max" in rule:
            ok = isinstance(value, (int, float)) and value <= rule["max"]
        if ok and "one_of" in rule:
            ok = value in rule["one_of"]
        add("require_json:%s[%s]" % (os.path.basename(newest), rule.get("field")), ok, detail)

    passed = all(c["ok"] for c in checks) and bool(checks)
    return {"status": "passed" if passed else "failed",
            "exit": EXIT_PASS if passed else EXIT_FAIL,
            "checks": checks, "criteria": os.path.relpath(criteria_path, root)}


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_doctor(cfg: Dict[str, Any], args) -> int:
    card: Dict[str, Any] = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "repo": cfg["repo"], "branch": head_branch()}
    branch = card["branch"]
    guard_ok = branch == cfg["branch"]
    card["branch_guard"] = {"ok": guard_ok, "expected": cfg["branch"], "actual": branch}
    probe = agent(cfg).doctor() if not args.no_network else {"workstation_online": None}
    card["desk"] = probe
    crit = evaluate(os.path.join(REPO, cfg["criteria"]))
    card["criteria"] = {"status": crit["status"], "checks": crit["checks"]}
    ok = guard_ok and bool(probe.get("workstation_online", True))
    print(json.dumps(card, indent=2, ensure_ascii=False))
    return EXIT_PASS if ok else EXIT_FAIL


def cmd_status(cfg: Dict[str, Any], args) -> int:
    out = agent(cfg).desk_status()
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return EXIT_PASS if out else EXIT_FAIL


def cmd_request(cfg: Dict[str, Any], args) -> int:
    ag = agent(cfg)
    payload = json.loads(args.json_args or "{}")
    if args.argv:
        payload["argv"] = list(args.argv)
    job = ag.submit(args.kind, payload, note=args.note or "", force=args.force)
    print(job)
    return EXIT_PASS


def cmd_wait(cfg: Dict[str, Any], args) -> int:
    ag = agent(cfg)
    wait_s = None if args.timeout in (None, "auto") else int(args.timeout)
    if wait_s is None:
        wait_s = int(cfg.get("answer_wait_s", 1500))
    result = ag.wait(args.id, answer_wait=wait_s)
    print(json.dumps(result, indent=2, ensure_ascii=False)[:4000])
    status = result.get("status")
    return EXIT_PASS if status in ("ok", "warn") else (EXIT_PENDING if status in ("timeout", "lost") else EXIT_FAIL)


def cmd_criteria(cfg: Dict[str, Any], args) -> int:
    path = args.path or os.path.join(REPO, cfg["criteria"])
    report = evaluate(path)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("criteria: %s" % report["status"])
        for check in report["checks"]:
            print("  [%s] %s  %s" % ("PASS" if check["ok"] else "FAIL", check["check"], check["detail"]))
    return report["exit"]


def cmd_loop(cfg: Dict[str, Any], args) -> int:
    """request -> wait -> criteria, repeating up to --rounds until criteria pass."""
    ag = agent(cfg)
    payload = json.loads(args.json_args or "{}")
    if args.argv:
        payload["argv"] = list(args.argv)
    manifest_dir = os.path.join(REPO, cfg["outdir"])
    os.makedirs(manifest_dir, exist_ok=True)
    history = []
    for round_no in range(1, args.rounds + 1):
        job_id = ag.submit(args.kind, payload, note="%s round %d" % (args.note or args.kind, round_no),
                           force=round_no > 1)
        log("round %d: job %s queued" % (round_no, job_id))
        result = ag.wait(job_id, answer_wait=int(cfg.get("answer_wait_s", 1500)))
        status = result.get("status")
        log("round %d: %s -> %s" % (round_no, job_id, status))
        report = evaluate(os.path.join(REPO, cfg["criteria"]))
        history.append({"round": round_no, "job": job_id, "job_status": status,
                        "summary": result.get("summary"), "criteria": report["status"],
                        "failed_checks": [c["check"] for c in report["checks"] if not c["ok"]]})
        if status in ("ok", "warn") and report["status"] == "passed":
            _write_loop_receipt(cfg, history, "ok")
            print(json.dumps({"status": "ok", "rounds": round_no, "history": history},
                             indent=2, ensure_ascii=False))
            return EXIT_PASS
        if status not in ("ok", "warn", "timeout", "lost"):
            history[-1]["note"] = "desk returned a real failure; not retrying the same payload"
            break
        time.sleep(max(5, args.backoff))
    _write_loop_receipt(cfg, history, "failed")
    print(json.dumps({"status": "failed", "history": history}, indent=2, ensure_ascii=False))
    return EXIT_FAIL


def _write_loop_receipt(cfg: Dict[str, Any], history: List[Dict[str, Any]], outcome: str) -> None:
    path = os.path.join(REPO, "results/sync/loop_receipt.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["# desk-loop receipt", "", "- outcome: **%s**" % outcome,
             "- at: %s" % time.strftime("%Y-%m-%dT%H:%M:%S"),
             "- branch: %s" % head_branch(), "", "| round | job | desk status | criteria | failed checks |",
             "|---|---|---|---|---|"]
    for row in history:
        lines.append("| %s | %s | %s | %s | %s |" % (
            row["round"], row["job"], row["job_status"], row["criteria"],
            ", ".join(row.get("failed_checks") or []) or "-"))
    lines += ["", "---", "", "## desk summary", ""]
    for row in history:
        lines.append("- round %s: %s" % (row["round"], (row.get("summary") or "")[:300]))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def cmd_sync(cfg: Dict[str, Any], args) -> int:
    branch = head_branch()
    if branch in ("main", "master"):
        print("[REFUSED] never work on %s" % branch, file=sys.stderr)
        return EXIT_USAGE
    if branch != cfg["branch"] and not args.allow_branch_mismatch:
        print("[REFUSED] HEAD is %s, expected %s" % (branch, cfg["branch"]), file=sys.stderr)
        return EXIT_USAGE

    staged = git(["diff", "--cached", "--name-only"]).stdout.split()
    todo = git(["status", "--porcelain"]).stdout.splitlines()
    if not staged and todo and not args.no_add:
        # stage guard: never commit trajectories / big binaries
        offenders = []
        for line in todo:
            name = line[3:].strip().strip('"')
            if any(fnmatch.fnmatch(os.path.basename(name), pat) for pat in TRAJECTORY_PATTERNS):
                offenders.append(name)
            elif os.path.isfile(os.path.join(REPO, name)) and os.path.getsize(os.path.join(REPO, name)) > args.max_mb * 1024 * 1024:
                offenders.append("%s (%.1f MB)" % (name, os.path.getsize(os.path.join(REPO, name)) / 1e6))
        if offenders:
            print("[REFUSED] these files must not be committed: %s" % ", ".join(offenders), file=sys.stderr)
            return EXIT_USAGE
        git(["add", "-A"], check=True)

    if cfg.get("gate"):
        log("gate: %s" % cfg["gate"])
        gate = subprocess.run(cfg["gate"], shell=True, cwd=REPO, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if gate.returncode != 0:
            print("[GATE FAILED]\n%s" % gate.stdout[-2000:], file=sys.stderr)
            return EXIT_FAIL

    message = args.message or "desk-loop: sync"
    commit = git(["commit", "-m", message])
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout:
        print(commit.stdout, file=sys.stderr)
        return EXIT_FAIL

    push = EXIT_PASS
    if not args.no_push:
        g = git(["push", cfg.get("remote", "origin"), branch])
        push = EXIT_PASS if g.returncode == 0 else EXIT_FAIL
        if push != EXIT_PASS:
            print(g.stdout, file=sys.stderr)

    receipt = os.path.join(REPO, cfg["receipt"])
    os.makedirs(os.path.dirname(receipt), exist_ok=True)
    head = git(["rev-parse", "--short", "HEAD"]).stdout.strip()
    criteria = evaluate(os.path.join(REPO, cfg["criteria"]))
    with open(receipt, "w", encoding="utf-8") as fh:
        fh.write("# sync receipt\n\n")
        fh.write("- at: %s\n- branch: %s\n- head: %s\n- message: %s\n- push: %s\n"
                 % (time.strftime("%Y-%m-%dT%H:%M:%S"), branch, head, message,
                    "ok" if push == EXIT_PASS else "failed"))
        fh.write("- criteria: %s\n" % criteria["status"])
        for check in criteria["checks"]:
            fh.write("  - [%s] %s (%s)\n" % ("PASS" if check["ok"] else "FAIL", check["check"], check["detail"]))
    # the receipt must describe THIS head, so it is committed (and pushed) right
    # after the main commit instead of lagging one sync behind
    if push == EXIT_PASS and git(["status", "--porcelain", "--", os.path.relpath(receipt, REPO)]).stdout.strip():
        git(["add", os.path.relpath(receipt, REPO)], check=True)
        git(["commit", "-m", "chore(sync): receipt for %s" % head], check=True)
        head = git(["rev-parse", "--short", "HEAD"]).stdout.strip()
        g = git(["push", cfg.get("remote", "origin"), branch])
        push = EXIT_PASS if g.returncode == 0 else EXIT_FAIL

    print(json.dumps({"branch": branch, "head": head, "push": push == EXIT_PASS,
                      "criteria": criteria["status"], "receipt": os.path.relpath(receipt, REPO)},
                     indent=2, ensure_ascii=False))
    return push


def cmd_recover(cfg: Dict[str, Any], args) -> int:
    """Keep the worktree, replay it on top of the remote branch after a .git reset."""
    branch = cfg["branch"]
    keep = args.keep or ["skills", "results", "cgmd_endtoend", "README.md"]
    tmp = tempfile.mkdtemp(prefix="desk-loop-recover-")
    saved = []
    for item in keep:
        src = os.path.join(REPO, item)
        if os.path.exists(src):
            shutil.copytree(src, os.path.join(tmp, item), dirs_exist_ok=True) \
                if os.path.isdir(src) else shutil.copy2(src, os.path.join(tmp, item))
            saved.append(item)
    log("saved %s -> %s" % (", ".join(saved), tmp))
    git(["fetch", cfg.get("remote", "origin"), branch], check=True)
    git(["reset", "--hard", "origin/%s" % branch], check=True)
    for item in saved:
        src = os.path.join(tmp, item)
        dst = os.path.join(REPO, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
    git(["add", "-A"])
    print(json.dumps({"recovered": saved, "head": git(["rev-parse", "--short", "HEAD"]).stdout.strip(),
                      "note": "worktree restored on origin/%s; run `desk-loop sync` to commit" % branch},
                     indent=2, ensure_ascii=False))
    return EXIT_PASS


def cmd_handoff(cfg: Dict[str, Any], args) -> int:
    desk = agent(cfg).desk_status()
    card = {
        "schema": "cgmd.deskloop.handoff.v1",
        "one_sentence": "安装 %s 的 skills/cgmd-desktop + skills/desk-loop，与台式机打通，用 desk-loop 跑动力学到成功" % cfg["branch"],
        "repo": "https://github.com/hukeying85-ux/JevHarness.git",
        "branch": cfg["branch"],
        "bootstrap": [
            "git clone -b %s https://github.com/hukeying85-ux/JevHarness.git /home/user/JevHarness" % cfg["branch"],
            "cd /home/user/JevHarness",
            "python3 skills/desk-loop/deskloop.py doctor --no-network   # branch guard only, offline",
            "python3 skills/desk-loop/deskloop.py doctor               # probe the desk (60 s)",
        ],
        "desk": {"host": "DESKTOP-IEUDGS5", "heartbeat_at": desk.get("heartbeat_at"),
                 "state": desk.get("state"), "allow_shell": desk.get("allow_shell"),
                 "poll_interval_s": desk.get("interval_s")},
        "job_kinds_open": ["ping", "selfcheck", "smoke", "gmx", "cgmd", "deskdiag", "deskfix", "sync"],
        "job_kinds_closed": ["shell (allow_shell=false)", "pipeline (not wired)"],
        "md_command": "python3 skills/desk-loop/deskloop.py loop --kind cgmd --json-args '{\"mode\":\"all\",\"sequence\":\"YLSLLQR\",\"ns\":2}'",
        "receipt": cfg["receipt"],
        "criteria": cfg["criteria"],
    }
    print(json.dumps(card, indent=2, ensure_ascii=False))
    return EXIT_PASS


def cmd_ledger(cfg: Dict[str, Any], args) -> int:
    path = os.path.join(HERE, "CONNECTIONS.md")
    if args.append:
        row = "| %s | %s | %s | %s | %s |\n" % (
            time.strftime("%Y-%m-%d %H:%M"), args.append, cfg["branch"],
            cfg.get("desk_branch"), args.note or "-")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(row)
        print("appended: %s" % row.strip())
        return EXIT_PASS
    print(open(path, encoding="utf-8").read() if os.path.isfile(path) else "no ledger yet")
    return EXIT_PASS


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="request -> desk -> verify -> repeat, one loop")
    ap.add_argument("--config", default=CONFIG_PATH)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor"); p.add_argument("--no-network", action="store_true")
    sub.add_parser("status")

    p = sub.add_parser("request")
    p.add_argument("--kind", required=True)
    p.add_argument("--json-args", default="{}")
    p.add_argument("--argv", nargs=argparse.REMAINDER, default=None)
    p.add_argument("--note", default="")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("wait"); p.add_argument("id"); p.add_argument("--timeout", default="auto")

    p = sub.add_parser("criteria"); p.add_argument("--path", default=None); p.add_argument("--json", action="store_true")

    p = sub.add_parser("loop")
    p.add_argument("--kind", default="cgmd")
    p.add_argument("--json-args", default="{}")
    p.add_argument("--argv", nargs=argparse.REMAINDER, default=None)
    p.add_argument("--note", default="")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--backoff", type=int, default=20)

    p = sub.add_parser("sync")
    p.add_argument("--message", default="")
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--no-add", action="store_true")
    p.add_argument("--allow-branch-mismatch", action="store_true")
    p.add_argument("--max-mb", type=float, default=5.0)

    p = sub.add_parser("recover"); p.add_argument("--keep", nargs="*", default=None)
    sub.add_parser("handoff")
    p = sub.add_parser("ledger"); p.add_argument("--append", default=""); p.add_argument("--note", default="")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    handler = {
        "doctor": cmd_doctor, "status": cmd_status, "request": cmd_request, "wait": cmd_wait,
        "criteria": cmd_criteria, "loop": cmd_loop, "sync": cmd_sync, "recover": cmd_recover,
        "handoff": cmd_handoff, "ledger": cmd_ledger,
    }[args.cmd]
    return handler(cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
