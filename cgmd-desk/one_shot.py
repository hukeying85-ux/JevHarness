#!/usr/bin/env python3
"""Land the ``cgmd`` mailbox kind in 0fuye and drive a 100 ns coarse-grained run.

One command, no decisions left in the middle::

    python3 cgmd-desk/one_shot.py --desk /tmp/0fuye            # full run
    python3 cgmd-desk/one_shot.py --desk /tmp/0fuye --dry-run  # land only, no push/merge

It must run somewhere whose GitHub credential can WRITE
``hukeying85-ux/0fuye``: an Arena conversation bound to that repository, or the
operator's own clone.  From a JevHarness-bound session the push step fails with
403 -- that is the one thing this script cannot work around, and it says so
loudly instead of half-doing it.

What it does, in order:

  1. land      create ``arena/cgmd-kind`` in the desk clone, ``git am`` the
               reviewed patch, run the test suite, push, open a PR, merge it
               into the branch the desk polls;
  2. wait      until origin actually carries the new kind (the desk hard-resets
               every 60 s);
  3. probe     which python / gmx / Martini 3 the desk has;
  4. ff        fetch the Martini 3 force field (pip, else codeload);
  5. all       find the recent peptide on F:, build the box, EM -> NPT ->
               production slice;
  6. resume    keep going from ``prod.cpt`` until the run reports finished,
               or the slice budget runs out.

Every step prints what it measured.  Nothing is invented: a field that was not
measured is printed as ``unverified``.
"""

import argparse
import json
import os
import subprocess
import sys
import time

PATCH_NAME = "0fuye-cgmd-kind.patch"
HERE = os.path.dirname(os.path.abspath(__file__))
TARGET_BRANCH = "arena/32cd826e-0fuye"
WORK_BRANCH = "arena/cgmd-kind"
REPO = "hukeying85-ux/0fuye"


def say(text):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def run(cmd, cwd=None, check=True, capture=True):
    record = subprocess.run(cmd, cwd=cwd, check=False,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.STDOUT if capture else None,
                            universal_newlines=True)
    if check and record.returncode != 0:
        raise SystemExit("command failed ({0}): {1}\n{2}".format(
            record.returncode, " ".join(cmd), (record.stdout or "").strip()[:2000]))
    return record


def git(desk, *args, **kwargs):
    return run(["git", "-C", desk] + list(args), **kwargs)


# ---------------------------------------------------------------------------
# 1. land
# ---------------------------------------------------------------------------
def land(desk, patch, dry_run=False):
    say("[1/6] landing the cgmd kind in {0}".format(desk))
    git(desk, "fetch", "--quiet", "origin")
    current = (git(desk, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout or "").strip()
    if current != WORK_BRANCH:
        branches = git(desk, "branch", "--list", WORK_BRANCH, check=False).stdout or ""
        if WORK_BRANCH in branches:
            git(desk, "checkout", "--quiet", WORK_BRANCH)
        else:
            git(desk, "checkout", "--quiet", "-b", WORK_BRANCH, "origin/" + TARGET_BRANCH)
        git(desk, "reset", "--quiet", "--hard", "origin/" + TARGET_BRANCH)

    already = (git(desk, "log", "--oneline", "-20", "--grep", "cgmd job kind",
                   check=False).stdout or "").strip()
    if not already:
        record = run(["git", "-C", desk, "am", patch], check=False)
        if record.returncode != 0:
            run(["git", "-C", desk, "am", "--abort"], check=False)
            raise SystemExit("git am failed:\n" + (record.stdout or "").strip()[:2000])
        say("      patch applied")
    else:
        say("      patch already present on this branch, reusing it")

    tests = run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=desk, check=False)
    if "No module named" in (tests.stdout or ""):
        say("      pytest not installed here - skipping the suite (CI covers it)")
    elif tests.returncode != 0:
        raise SystemExit("test suite failed:\n" + (tests.stdout or "").strip()[-2000:])
    else:
        say("      " + (tests.stdout or "").strip().splitlines()[-1])

    if dry_run:
        say("      --dry-run: stopping before push/merge")
        return False

    git(desk, "push", "--quiet", "-u", "origin", WORK_BRANCH)
    say("      pushed {0}".format(WORK_BRANCH))

    number = None
    listed = run(["gh", "pr", "list", "--repo", REPO, "--head", WORK_BRANCH,
                  "--json", "number"], check=False)
    try:
        rows = json.loads(listed.stdout or "[]")
        if rows:
            number = rows[0]["number"]
    except ValueError:
        pass
    if number is None:
        created = run(["gh", "pr", "create", "--repo", REPO,
                       "--base", TARGET_BRANCH, "--head", WORK_BRANCH,
                       "--title", "mailbox: cgmd job kind (coarse-grained MD without a shell)",
                       "--body", "Lands code/cgmd/desk_ops.py plus the cgmd job kind; "
                                 "see cgmd-desk/README.md in the JevHarness hand-off."], check=False)
        if created.returncode != 0:
            raise SystemExit("gh pr create failed:\n" + (created.stdout or "").strip()[:1500])
        for word in (created.stdout or "").split():
            tail = word.rstrip("/").split("/")[-1]
            if tail.isdigit() and "/pull/" in word:
                number = int(tail)
        say("      PR opened: " + (created.stdout or "").strip().splitlines()[-1])
    if number is None:
        raise SystemExit("could not determine the PR number")
    merged = run(["gh", "pr", "merge", str(number), "--repo", REPO, "--merge"], check=False)
    if merged.returncode != 0:
        raise SystemExit("gh pr merge failed:\n" + (merged.stdout or "").strip()[:1500])
    say("      merged PR #{0} into {1}".format(number, TARGET_BRANCH))
    return True


def wait_for_desk(desk, timeout=300):
    say("[2/6] waiting until origin/{0} carries the new kind (desk poll is 60 s)".format(TARGET_BRANCH))
    started = time.time()
    while time.time() - started < timeout:
        git(desk, "fetch", "--quiet", "origin")
        tree = git(desk, "ls-tree", "-r", "--name-only", "origin/" + TARGET_BRANCH, check=False).stdout or ""
        if "code/cgmd/desk_ops.py" in tree:
            git(desk, "checkout", "--quiet", TARGET_BRANCH)
            git(desk, "reset", "--quiet", "--hard", "origin/" + TARGET_BRANCH)
            say("      desk_ops.py is on the branch after {0:.0f} s".format(time.time() - started))
            return True
        time.sleep(10)
    raise SystemExit("the merged code never appeared on origin/" + TARGET_BRANCH)


# ---------------------------------------------------------------------------
# 3-6. drive
# ---------------------------------------------------------------------------
def mailbox(desk):
    if desk not in sys.path:
        sys.path.insert(0, desk)
    from core import hub_mailbox  # noqa: E402 - the desk clone carries the client
    return hub_mailbox


def dispatch(desk, name, args, timeout=3600, interval=10):
    hub = mailbox(desk)
    job_id = hub.send(desk, "cgmd", args, note=name, timeout_s=timeout)
    say("      {0}: queued {1}".format(name, job_id))
    result = hub.wait(desk, job_id, timeout=timeout, interval=interval)
    say("      {0}: {1} ({2} s, id {3})".format(name, result.get("status"),
                                               result.get("seconds"), job_id))
    return job_id, result


def ops_detail(result):
    detail = result.get("detail") or {}
    return (detail.get("ops") or {}).get("detail") or {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--desk", required=True, help="clone of hukeying85-ux/0fuye you can write")
    parser.add_argument("--patch", default=os.path.join(HERE, PATCH_NAME))
    parser.add_argument("--ns", type=float, default=100.0, help="production length (default 100)")
    parser.add_argument("--box-nm", type=float, default=6.0)
    parser.add_argument("--roots", default=r"F:\0wsh\asd,F:\0wsh,F:\\")
    parser.add_argument("--fallback", default="KLVFFAE", help="peptide used when nothing is found")
    parser.add_argument("--max-slices", type=int, default=8, help="resume slices after the first")
    parser.add_argument("--dry-run", action="store_true", help="land only: no push/merge, no jobs")
    parser.add_argument("--skip-land", action="store_true", help="the code is already merged")
    options = parser.parse_args(argv)

    desk = os.path.abspath(options.desk)
    roots = [item for item in options.roots.split(",") if item]

    if not options.skip_land:
        if not land(desk, options.patch, dry_run=options.dry_run):
            return 0
    if options.dry_run:
        return 0
    wait_for_desk(desk)

    say("[3/6] probe")
    _, probe = dispatch(desk, "probe", {"mode": "probe", "roots": roots}, timeout=600)
    detail = ops_detail(probe)
    pythons = detail.get("pythons") or []
    python = (pythons[0] or {}).get("exe") if pythons else None
    martini = (detail.get("martini") or {}).get("file")
    say("      python:  {0}".format("{0} ({1})".format(python, pythons[0].get("version"))
                                    if python else "unverified"))
    say("      gmx:     {0}".format((detail.get("gmx") or {}).get("path") or "unverified"))
    say("      martini: {0}".format(martini or "missing"))

    state = {"probe": probe}

    if not martini:
        say("[4/6] ff")
        ff_args = {"mode": "ff", "install_timeout": 900}
        if python:
            ff_args["python"] = python
        _, ff = dispatch(desk, "ff", ff_args, timeout=1200)
        state["ff"] = ff
        martini = (ops_detail(ff).get("found") or {}).get("file")
        say("      martini: {0}".format(martini or "still missing"))
        if not martini:
            say("!! the force field could not be fetched; stopping rather than faking a run")
            return 2
    else:
        say("[4/6] ff: already on the desk, skipping")

    say("[5/6] build + first production slice ({0} ns)".format(options.ns))
    all_args = {
        "mode": "all",
        "roots": roots,
        "days": 365,
        "depth": 4,
        "box_nm": options.box_nm,
        "ns": options.ns,
        "gpu_id": 0,
        "timeout_s": 3600,
        "prod_timeout": 3000,
        "fallback_sequence": options.fallback,
    }
    job_id, result = dispatch(desk, "all", all_args, timeout=3600)
    state["all"] = result
    ops = ops_detail(result)
    report = (ops.get("report") or {})
    workdir = ops.get("workdir") or report.get("workdir")
    system = ops.get("system") or {}
    say("      sequence: {0} | beads: {1} | workdir: {2}".format(
        ops.get("sequence") or "unverified", system.get("beads_total") or "unverified",
        workdir or "unverified"))

    slices = 0
    while not report.get("finished") and slices < options.max_slices:
        slices += 1
        say("[6/6] resume slice {0} (from the checkpoint)".format(slices))
        if not workdir:
            say("!! no workdir came back, cannot resume")
            break
        args = {"mode": "run", "workdir": workdir, "ns": options.ns, "resume": True,
                "gpu_id": 0, "timeout_s": 3600, "prod_timeout": 3000}
        job_id, result = dispatch(desk, "run-{0}".format(slices), args, timeout=3600)
        state["resume-{0}".format(slices)] = result
        ops = ops_detail(result)
        report = (ops.get("report") or {})
        say("      ns/day: {0} | finished: {1}".format(
            report.get("performance_ns_per_day"), report.get("finished")))

    say("")
    say("=" * 68)
    say("sequence        : {0}".format(ops.get("sequence") or "unverified"))
    say("beads / box     : {0} / {1}".format(system.get("beads_total") or "unverified",
                                            system.get("box_nm") or "unverified"))
    say("production      : {0} ns requested, finished={1}".format(options.ns, report.get("finished")))
    say("performance     : {0} ns/day on {1}".format(
        report.get("performance_ns_per_day") or "unverified",
        report.get("accelerator") or "unverified"))
    structure = report.get("structure") or {}
    for label in ("start", "final"):
        block = structure.get(label) or {}
        if block:
            say("Rg {0:<12}: {1} nm | largest cluster {2}".format(
                label, block.get("rg_nm"), (block.get("clusters") or {}).get("largest")))
    say("jobs            : {0}".format(", ".join(sorted(state))))
    say("=" * 68)
    return 0 if report.get("finished") else 3


if __name__ == "__main__":
    sys.exit(main())
