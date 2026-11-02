#!/usr/bin/env python3
"""Pre-commit gate for this repository (run by `deskloop.py sync`).

Hard failures (exit 1):
  * HEAD is main/master, or is not the branch pinned in skills/desk-loop/sync.config.json
  * a tracked/staged file matches a trajectory pattern (*.xtc/*.trr/*.tpr/*.gro/*.edr/*.cpt)
  * a staged file is bigger than the size cap
  * any *.py in skills/ fails to compile, or any *.json in skills/ fails to parse

Soft notes (printed, still exit 0):
  * success criteria not met yet (a sync is allowed mid-run; the loop decides)

Borrowed in spirit from `code/check_all.sh` in mqgg5630-cyber/git-pull-arena
(the "config branch == HEAD" and "scripts must be self-consistent" guards).
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(REPO, "skills", "desk-loop", "sync.config.json")
TRAJECTORY = ("*.xtc", "*.trr", "*.tpr", "*.gro", "*.edr", "*.cpt", "*.xtc.gz", "*.h5")
MAX_MB = 5.0


def git(args):
    return subprocess.run(["git"] + args, cwd=REPO, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def main() -> int:
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    failures, notes = [], []

    if branch in ("main", "master"):
        failures.append("HEAD is %s -- never commit there" % branch)
    elif branch != cfg["branch"]:
        failures.append("HEAD is %s, config expects %s" % (branch, cfg["branch"]))
    else:
        notes.append("branch guard: %s" % branch)

    staged = [line for line in git(["diff", "--cached", "--name-only"]).stdout.splitlines() if line]
    for name in staged:
        base = os.path.basename(name)
        if any(fnmatch.fnmatch(base, pat) for pat in TRAJECTORY):
            failures.append("trajectory file staged: %s" % name)
        full = os.path.join(REPO, name)
        if os.path.isfile(full) and os.path.getsize(full) > MAX_MB * 1024 * 1024:
            failures.append("%s is %.1f MB (> %.0f MB)" % (name, os.path.getsize(full) / 1e6, MAX_MB))
    notes.append("%d staged file(s)" % len(staged))

    for root, _dirs, files in os.walk(os.path.join(REPO, "skills")):
        for name in files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, REPO)
            if name.endswith(".py"):
                try:
                    compile(open(full, encoding="utf-8").read(), full, "exec")
                except SyntaxError as exc:
                    failures.append("python syntax: %s (%s)" % (rel, exc.msg))
            elif name.endswith(".json"):
                try:
                    json.load(open(full, encoding="utf-8"))
                except Exception as exc:
                    failures.append("json parse: %s (%s)" % (rel, exc))
    notes.append("skills/ python + json checked")

    crit_path = os.path.join(REPO, cfg["criteria"])
    if os.path.isfile(crit_path):
        proc = subprocess.run([sys.executable, os.path.join(REPO, "skills", "desk-loop", "deskloop.py"),
                               "criteria", "--json"], cwd=REPO, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            status = json.loads(proc.stdout or "{}").get("status", "unknown")
        except Exception:
            status = "unknown"
        notes.append("criteria: %s" % status)

    for note in notes:
        print("  [ok] %s" % note)
    for bad in failures:
        print("  [FAIL] %s" % bad, file=sys.stderr)
    print("gate: %s" % ("FAILED" if failures else "passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
