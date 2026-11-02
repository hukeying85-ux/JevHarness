#!/usr/bin/env python3
"""cgmd-desktop agent: pull -> execute -> push-back, polled until the task succeeds.

It drives the *existing* CGMD desktop base (CGMD-Hub-Poll + hub/mailbox).  It
adds **no** poller on the workstation: the workstation half already exists and
is not touched.  What this adds is the missing client half -- an idempotent
submit/wait/retry/chunk loop that

  * pushes a job request into this repository's ``hub/mailbox`` branch,
  * pulls the workstation's ``hub/mailbox`` branch until the answer appears,
  * retries only when the desk never answered (never blindly re-runs a job that
    already reported ``fail``), and
  * chains the CGMD stages (``probe -> ff -> build -> run``), splitting a long
    production run into resumable slices so a single job never outlives the
    desk's per-job time cap.

Nothing here needs a shell on the workstation: it uses the ``cgmd`` and ``gmx``
job kinds, which the desk implements with a fixed dispatcher script.

Typical use
-----------
    python3 cgmd_agent.py doctor
    python3 cgmd_agent.py md --sequence YLSLLQR --ns 20 --outdir results/desktop
    python3 cgmd_agent.py job --kind gmx --argv mdrun -s C:/path/prod.tpr -nsteps 5000
    python3 cgmd_agent.py watch 20261102T011124-3a0d
    python3 cgmd_agent.py status

Requirements: python3.8+, git, and a clone of the desk repository
(``--desk``, default ``~/.cache/cgmd-desk``) that contains ``core/hub_mailbox.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

DEFAULT_DESK = os.path.expanduser("~/.cache/cgmd-desk")
DEFAULT_DESK_REMOTE = "https://github.com/hukeying85-ux/0fuye.git"
DEFAULT_BRANCH = "arena/32cd826e-0fuye"
LEDGER_NAME = "ledger.json"


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()


def payload_key(kind: str, args: Dict[str, Any]) -> str:
    blob = json.dumps({"kind": kind, "args": args}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def git(args: List[str], cwd: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=cwd, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ensure_desk_clone(path: str, branch: str, remote: str) -> str:
    """Make sure a usable clone of the desk repository exists (the 'pull' half)."""
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isdir(os.path.join(path, ".git")):
        return path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    log("cloning desk repository into %s" % path)
    proc = subprocess.run(["git", "clone", "-q", "-b", branch, remote, path],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise SystemExit("clone failed: %s" % proc.stdout.strip()[-500:])
    return path


def load_bus(desk: str):
    """Import the desk's own mailbox module -- one protocol, no reimplementation."""
    if desk not in sys.path:
        sys.path.insert(0, desk)
    try:
        from core import hub_mailbox  # type: ignore
        return hub_mailbox
    except Exception as exc:  # pragma: no cover - environment problem
        raise SystemExit("cannot import core.hub_mailbox from %s: %s" % (desk, exc))


# --------------------------------------------------------------------------- #
# the agent
# --------------------------------------------------------------------------- #
class Agent:
    def __init__(self, repo: str, desk: str, branch: str, desk_remote: str,
                 outdir: str, answer_wait: int = 900, poll_interval: int = 20):
        self.repo = os.path.abspath(repo)                 # my checkout (push side)
        self.desk = ensure_desk_clone(desk, branch, desk_remote)   # read side
        self.branch = branch
        self.outdir = os.path.abspath(outdir)
        self.answer_wait = answer_wait
        self.poll_interval = poll_interval
        self.bus = load_bus(self.desk)
        os.makedirs(self.outdir, exist_ok=True)
        self.ledger_path = os.path.join(self.outdir, LEDGER_NAME)
        self.ledger: Dict[str, Any] = read_json(self.ledger_path, {}) or {}

    # -- ledgers ---------------------------------------------------------- #
    def _save_ledger(self) -> None:
        write_json(self.ledger_path, self.ledger)

    def _archive(self, job_id: str, result: Dict[str, Any]) -> str:
        path = os.path.join(self.outdir, "%s.json" % job_id)
        write_json(path, result)
        return path

    # -- core loop -------------------------------------------------------- #
    def submit(self, kind: str, args: Dict[str, Any], note: str = "",
               force: bool = False) -> str:
        """Send a job, reusing an unanswered twin instead of queueing a duplicate."""
        key = payload_key(kind, args)
        if not force:
            prior = self.ledger.get(key)
            if prior and prior.get("state") == "unanswered":
                log("reusing unanswered job %s for the same payload" % prior["job_id"])
                return prior["job_id"]
        job_id = self.bus.send(self.repo, kind, args, note=note, timeout_s=int(args.get("timeout_s", 1800)))
        self.ledger[key] = {"job_id": job_id, "kind": kind, "args": args, "state": "unanswered",
                            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self._save_ledger()
        log("queued %s as %s" % (kind, job_id))
        return job_id

    def wait(self, job_id: str, answer_wait: Optional[int] = None) -> Dict[str, Any]:
        wait_s = answer_wait if answer_wait is not None else self.answer_wait
        started = time.time()
        while True:
            result = self.bus.read_result(self.desk, job_id)
            if result is not None:
                self._archive(job_id, result)
                for entry in self.ledger.values():
                    if entry.get("job_id") == job_id:
                        entry["state"] = "answered"
                        entry["status"] = result.get("status")
                        entry["seconds"] = result.get("seconds")
                self._save_ledger()
                return result
            if time.time() - started >= wait_s:
                pending = self.bus.request_pending(self.desk, job_id)
                return {"id": job_id, "status": "timeout" if pending else "lost",
                        "seconds": round(time.time() - started, 1),
                        "summary": "no answer after %d s (%s)" % (wait_s, "still queued" if pending else "not seen")}
            time.sleep(max(5, self.poll_interval))

    def run_job(self, kind: str, args: Dict[str, Any], note: str = "",
                retries: int = 3, retry_on_fail: bool = False) -> Dict[str, Any]:
        """submit -> wait -> (retry only if the desk never answered) -> return result."""
        attempt = 0
        while True:
            attempt += 1
            job_id = self.submit(kind, args, note=note, force=attempt > 1)
            result = self.wait(job_id)
            status = result.get("status")
            log("%s -> %s (%ss) %s" % (job_id, status, result.get("seconds"), str(result.get("summary"))[:160]))
            if status in ("ok", "warn"):
                return result
            if status not in ("timeout", "lost") and not retry_on_fail:
                # fail / unsupported / error are real answers from the desk: resending the
                # same payload would only burn another poll cycle.
                return result
            if attempt > retries:
                return result
            log("retrying (attempt %d/%d)" % (attempt + 1, retries + 1))
            time.sleep(30)

    # -- capabilities ----------------------------------------------------- #
    def doctor(self, outdir: Optional[str] = None) -> Dict[str, Any]:
        probe = self.run_job("cgmd", {"mode": "probe", "timeout_s": 300}, note="agent doctor",
                             retries=2)
        card = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "probe_job": probe.get("id"), "probe_status": probe.get("status"),
                "probe_summary": probe.get("summary")}
        ops = stage_payload(probe)
        if ops:
            gmx = ops.get("gmx") or {}
            martini = ops.get("martini") or {}
            card.update({
                "host": ops.get("host"),
                "gmx": gmx.get("path"), "gmx_version": gmx.get("version"),
                "gmx_gpu": gmx.get("gpu_support"), "cuda_runtime": gmx.get("cuda_runtime"),
                "python": ops.get("python") or ((probe.get("detail") or {}).get("python")),
                "martini_dir": martini.get("dir"), "martini_how": martini.get("how"),
                "drives": ops.get("drives"),
            })
        card["workstation_online"] = card.get("probe_status") in ("ok", "warn")
        target = outdir or os.path.join(self.outdir, "doctor.json")
        write_json(target, card)
        return card

    def desk_status(self) -> Dict[str, Any]:
        """Read the workstation's own state file out of its repository (no job needed)."""
        status: Dict[str, Any] = {}
        proc = git(["fetch", "-q", "origin", self.branch], self.desk)
        blob = subprocess.run(["git", "show", "origin/%s:results/status/hub_mailbox.json" % self.branch],
                              cwd=self.desk, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        data = read_json_str(blob.stdout)
        if data:
            status.update({"state": data.get("state"), "queued": data.get("queued"),
                           "allow_shell": data.get("allow_shell"),
                           "generated_at": data.get("generated_at"),
                           "peers": data.get("peers")})
        hb = subprocess.run(["git", "show", "origin/%s:results/status/hub_heartbeat.json" % self.branch],
                            cwd=self.desk, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        hdata = read_json_str(hb.stdout)
        if hdata:
            status["heartbeat_at"] = hdata.get("at")
            status["heartbeat_state"] = hdata.get("state")
            status["poll_count"] = hdata.get("poll_count")
            status["interval_s"] = hdata.get("interval_s")
        return status

    # -- the MD pipeline -------------------------------------------------- #
    def md(self, sequence: str, ns: float, box_nm: Optional[float] = None,
           slice_ns: Optional[float] = None, salt_m: float = 0.15,
           retries: int = 3, job_timeout: int = 3300) -> Dict[str, Any]:
        """probe -> (ff) -> build -> run slices, until the requested ns is done."""
        manifest: Dict[str, Any] = {
            "schema": "cgmd.agent.md.v1",
            "sequence": sequence, "target_ns": ns, "box_nm": box_nm, "salt_m": salt_m,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stages": [], "steps": [],
        }

        card = self.doctor()
        manifest["capabilities"] = card
        manifest["stages"].append({"stage": "probe", "status": card.get("probe_status"),
                                   "summary": card.get("probe_summary")})
        if not card.get("workstation_online"):
            manifest["status"] = "offline"
            manifest["summary"] = "workstation did not answer the probe"
            return self._finish(manifest, sequence)

        if not card.get("martini_dir"):
            log("martini force field not found on the desk -> mode=ff")
            ff = self.run_job("cgmd", {"mode": "ff", "timeout_s": 1200}, note="fetch martini 3", retries=2)
            manifest["stages"].append({"stage": "ff", "status": ff.get("status"),
                                       "summary": ff.get("summary")})
            if ff.get("status") not in ("ok", "warn"):
                manifest["status"] = "fail"
                manifest["summary"] = "martini force field unavailable: %s" % ff.get("summary")
                return self._finish(manifest, sequence)

        build_args: Dict[str, Any] = {"mode": "build", "sequence": sequence,
                                      "salt_m": salt_m, "timeout_s": 900}
        if box_nm:
            build_args["box_nm"] = float(box_nm)
        build = self.run_job("cgmd", build_args, note="build %s" % sequence, retries=retries)
        build_ops = stage_payload(build)
        manifest["stages"].append({"stage": "build", "status": build.get("status"),
                                   "summary": build.get("summary"), "job": build.get("id")})
        if build.get("status") not in ("ok", "warn"):
            manifest["status"] = "fail"
            manifest["summary"] = "build failed: %s" % build.get("summary")
            return self._finish(manifest, sequence)

        workdir = (build_ops.get("workdir") or build_ops.get("dir")
                   or desk_dirname(build_ops.get("gro") or ""))
        if not workdir:
            manifest["status"] = "fail"
            manifest["summary"] = "build did not report a workdir: %s" % json.dumps(build_ops)[:400]
            return self._finish(manifest, sequence)
        manifest["workdir"] = workdir
        manifest["system"] = {k: build_ops.get(k) for k in
                              ("beads_total", "box_nm", "water_beads", "na", "cl", "gro", "top")}

        # Slices are *cumulative*: prod.mdp's nsteps is rewritten to the running
        # total each time and mdrun resumes from prod.cpt, so slice k stops at
        # k*slice_ns of production rather than adding slice_ns on top.
        done_ns = 0.0
        slice_ns = float(slice_ns or max(1.0, min(ns, job_timeout / 60.0)))
        target = 0.0
        resume = False
        report: Dict[str, Any] = {}
        while target < ns - 1e-9:
            target = min(ns, target + slice_ns)
            run_args: Dict[str, Any] = {"mode": "run", "workdir": workdir, "ns": round(target, 3),
                                        "timeout_s": int(job_timeout), "prod_timeout": int(job_timeout) - 300}
            if resume:
                run_args["resume"] = True
            run = self.run_job("cgmd", run_args, note="run to %.3f ns" % target, retries=retries)
            run_ops = stage_payload(run)
            report = run_ops.get("report") or {}
            steps_done = report.get("steps_done") or 0
            done_ns = (steps_done * 0.02 / 1000.0) if steps_done else 0.0
            entry = {"stage": "run", "job": run.get("id"), "status": run.get("status"),
                     "summary": run.get("summary"), "target_ns": round(target, 3),
                     "steps_done": steps_done, "done_ns": round(done_ns, 3),
                     "performance_ns_per_day": report.get("performance_ns_per_day"),
                     "finished": report.get("finished"), "warnings": report.get("warnings")}
            manifest["steps"].append(entry)
            if run.get("status") not in ("ok", "warn"):
                manifest["status"] = "fail"
                manifest["summary"] = "run failed: %s" % run.get("summary")
                return self._finish(manifest, sequence)
            resume = True
            if done_ns < ns - 1e-9:
                log("slice done: %.2f / %.1f ns" % (done_ns, ns))

        manifest["status"] = "ok"
        manifest["done_ns"] = round(done_ns, 3)
        manifest["performance_ns_per_day"] = report.get("performance_ns_per_day")
        manifest["final_report"] = report
        manifest["summary"] = "%s: %.3f ns at %s ns/day (beads %s)" % (
            sequence, done_ns, report.get("performance_ns_per_day"), manifest["system"].get("beads_total"))
        return self._finish(manifest, sequence)

    def _finish(self, manifest: Dict[str, Any], sequence: str) -> Dict[str, Any]:
        manifest["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        name = "md_%s_%s.json" % (sequence, time.strftime("%Y%m%d-%H%M%S"))
        write_json(os.path.join(self.outdir, name), manifest)
        manifest["manifest_path"] = os.path.join(self.outdir, name)
        return manifest


def desk_dirname(path: str) -> str:
    """Directory part of a *workstation* path, whichever separator it uses."""
    if not path:
        return ""
    return ntpath.dirname(path) if ("\\" in path or ":" in path) else os.path.dirname(path)


def stage_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """The mode-specific block the desk puts at detail.ops.detail."""
    ops = ((result.get("detail") or {}).get("ops") or {})
    payload = ops.get("detail")
    return payload if isinstance(payload, dict) else {}


def read_json_str(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="pull -> execute -> push-back agent for the CGMD desk")
    ap.add_argument("--repo", default=".", help="my checkout; job requests are pushed from here")
    ap.add_argument("--desk", default=DEFAULT_DESK, help="clone of the desk repository (answers are read here)")
    ap.add_argument("--branch", default=DEFAULT_BRANCH, help="desk branch to read status from")
    ap.add_argument("--desk-remote", default=DEFAULT_DESK_REMOTE)
    ap.add_argument("--outdir", default="results/desktop")
    ap.add_argument("--answer-wait", type=int, default=900, help="seconds to wait for one answer")
    ap.add_argument("--poll-interval", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="print the result as JSON only")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="capability card (gmx, python, martini, drives)")
    sub.add_parser("status", help="workstation state file + heartbeat, no job sent")

    p_md = sub.add_parser("md", help="chained probe -> build -> run (CG MD on the desk GPU)")
    p_md.add_argument("--sequence", required=True)
    p_md.add_argument("--ns", type=float, default=5.0)
    p_md.add_argument("--box-nm", type=float, default=None)
    p_md.add_argument("--slice-ns", type=float, default=None, help="production slice per job")
    p_md.add_argument("--salt-m", type=float, default=0.15)
    p_md.add_argument("--retries", type=int, default=3)
    p_md.add_argument("--job-timeout", type=int, default=3300)

    p_job = sub.add_parser("job", help="send one arbitrary mailbox job")
    p_job.add_argument("--kind", required=True)
    p_job.add_argument("--json-args", default="{}")
    p_job.add_argument("--argv", nargs=argparse.REMAINDER, default=None,
                       help="shorthand for --kind gmx: the argv after 'gmx'")
    p_job.add_argument("--retries", type=int, default=2)

    p_watch = sub.add_parser("watch", help="wait for an already queued job id")
    p_watch.add_argument("id")

    args = ap.parse_args(argv)
    agent = Agent(args.repo, args.desk, args.branch, args.desk_remote, args.outdir,
                  answer_wait=args.answer_wait, poll_interval=args.poll_interval)

    if args.cmd == "doctor":
        out = agent.doctor()
    elif args.cmd == "status":
        out = agent.desk_status()
    elif args.cmd == "md":
        out = agent.md(args.sequence, args.ns, box_nm=args.box_nm, slice_ns=args.slice_ns,
                       salt_m=args.salt_m, retries=args.retries, job_timeout=args.job_timeout)
    elif args.cmd == "job":
        payload = json.loads(args.json_args or "{}")
        if args.argv:
            payload["argv"] = list(args.argv)
        out = agent.run_job(args.kind, payload, retries=args.retries)
    elif args.cmd == "watch":
        out = agent.wait(args.id)
    else:  # pragma: no cover
        raise SystemExit("unknown command")

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False)[:4000])
    return 0 if str(out.get("status", out.get("probe_status", "ok"))) in ("ok", "warn", "None") else 1


if __name__ == "__main__":
    raise SystemExit(main())
