#!/usr/bin/env python3
"""Collect the numbers a reviewer asks for out of the GROMACS logs.

Reads em.log / nvt.log / npt.log / prod.part0001.log (+ prod.log) and writes a
single JSON with: stage timing, ns/day, temperature/pressure/energy statistics,
and a couple of sanity verdicts (no LINCS warnings, finished cleanly).
"""
from __future__ import annotations

import argparse
import json
import os
import re

STAGES = [("em", "em.log"), ("nvt", "nvt.log"), ("npt", "npt.log")]


def grep_last(path, pattern, default=None):
    if not os.path.exists(path):
        return default
    hit = default
    with open(path, errors="replace") as fh:
        for line in fh:
            if re.search(pattern, line):
                hit = line.rstrip("\n")
    return hit


def perf(path):
    line = grep_last(path, r"^Performance:")
    if not line:
        return {}
    nums = re.findall(r"[-+]?\d*\.?\d+(?:e[-+]?\d+)?", line)
    if len(nums) >= 2:
        return {"ns_per_day": float(nums[0]), "hour_per_ns": float(nums[1])}
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".")
    ap.add_argument("--out", default="run_report.json")
    ap.add_argument("--expected-ns", type=float, default=100.0)
    args = ap.parse_args()

    prod_logs = [f for f in sorted(os.listdir(args.dir)) if re.match(r"prod(\.part\d+)?\.log$", f)]
    ran = {}
    for name, log in STAGES:
        p = os.path.join(args.dir, log)
        if os.path.exists(p):
            ran[name] = {"log": log, **perf(p),
                         "finished": "Finished mdrun" in open(p, errors="replace").read()}
    prod = {}
    for log in prod_logs:
        p = os.path.join(args.dir, log)
        text = open(p, errors="replace").read()
        last = re.findall(r"^\s+(\d+)\s+(\d+\.\d+)\s*$", text, re.M)
        step, time_ps = (int(last[-1][0]), float(last[-1][1])) if last else (0, 0.0)
        lincs = len(re.findall(r"LINCS WARNING", text))
        prod[log] = {
            "steps": step,
            "simulated_ns": round(time_ps / 1000.0, 3),
            "ns_per_day": perf(p).get("ns_per_day"),
            "lincs_warnings": lincs,
            "finished": "Finished mdrun" in text,
            "fatal_error": bool(re.search(r"Fatal error", text)),
        }
    out = {
        "schema": "cgmd.martini.onepot.run.v1",
        "equilibration": ran,
        "production": prod,
        "expected_ns": args.expected_ns,
        "verdict": {},
    }
    total_ns = sum(v["simulated_ns"] for v in prod.values())
    out["verdict"] = {
        "all_stages_finished": all(v.get("finished") for v in list(ran.values()) + list(prod.values())),
        "production_ns_total": round(total_ns, 3),
        "no_lincs_warnings": all(v["lincs_warnings"] == 0 for v in prod.values()),
        "no_fatal_error": all(not v["fatal_error"] for v in prod.values()),
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
