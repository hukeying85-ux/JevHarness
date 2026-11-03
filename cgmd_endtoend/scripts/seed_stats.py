#!/usr/bin/env python3
"""Turn N single-trajectory summary JSONs into mean +/- SD (repeat statistics).

Every JSON produced by analyze_cg.py keeps a per-frame `timeseries` with
`cluster_sizes` and `inter_copy_contacts`, so the same endpoint can be
recomputed on an arbitrary time window here -- that is how a 100 ns run is
compared against 30 ns repeat runs without re-reading the trajectory.

    python3 seed_stats.py --window 30 results/summary_metrics_A.json \
        results/summary_metrics_A_s20261031.json ... --out repeats_A.json

Reported per endpoint: mean, sample SD (n-1), min, max, and the raw per-seed
values, so nothing is hidden behind an aggregate.
"""
from __future__ import annotations

import argparse
import json
import statistics


def endpoints(summary: dict, window_ns: float | None) -> dict:
    frames = [f for f in summary["timeseries"]
              if window_ns is None or f["time_ns"] <= window_ns + 1e-9]
    if not frames:
        raise SystemExit("no frames in window")
    largest = [f["largest_cluster"] if "largest_cluster" in f
               else (max(f["cluster_sizes"]) if f.get("cluster_sizes") else 1)
               for f in frames]
    contacts = [f["inter_copy_contacts"] for f in frames]
    rg = [f["rg_mean_nm"] for f in frames]
    return {
        "frames": len(frames),
        "window_ns": [frames[0]["time_ns"], frames[-1]["time_ns"]],
        "P_ge2": sum(1 for x in largest if x >= 2) / len(frames),
        "P_ge3": sum(1 for x in largest if x >= 3) / len(frames),
        "P_ge4": sum(1 for x in largest if x >= 4) / len(frames),
        "largest_cluster_mean": statistics.fmean(largest),
        "largest_cluster_max": max(largest),
        "contacts_mean": statistics.fmean(contacts),
        "contacts_max": max(contacts),
        "rg_mean_nm": statistics.fmean(rg),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("summaries", nargs="+")
    ap.add_argument("--window", type=float, default=None, help="only frames at t <= window ns")
    ap.add_argument("--labels", default="", help="comma separated seed labels, same order")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    labels = [s for s in args.labels.split(",") if s] or [f"seed{i + 1}" for i in range(len(args.summaries))]
    per_seed = {}
    for label, path in zip(labels, args.summaries):
        per_seed[label] = endpoints(json.load(open(path)), args.window)

    keys = ["P_ge2", "P_ge3", "P_ge4", "largest_cluster_mean", "largest_cluster_max",
            "contacts_mean", "contacts_max", "rg_mean_nm", "frames"]
    agg = {}
    for k in keys:
        vals = [per_seed[l][k] for l in labels]
        row = {"mean": statistics.fmean(vals), "values": {l: per_seed[l][k] for l in labels}}
        if len(vals) > 1 and k != "frames":
            row["sd"] = statistics.stdev(vals)
            row["sem"] = statistics.stdev(vals) / len(vals) ** 0.5
        agg[k] = row

    report = {
        "schema": "cgmd.cg_onepot.repeats.v1",
        "n_seeds": len(labels),
        "window_ns": args.window,
        "per_seed": per_seed,
        "aggregate": agg,
        "note": ("SD is across independent trajectories (placement seed + gen-seed=-1 velocity seed), "
                 "not across frames; n=3 is the document's minimum, so treat it as a spread estimate "
                 "rather than a significance test."),
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        open(args.out, "w").write(text + "\n")
        print(f"wrote {args.out}")
    print(f"\n{'endpoint':24s} " + " ".join(f"{l:>12s}" for l in labels) + f" {'mean':>10s} {'sd':>9s}")
    for k in keys:
        if k == "frames":
            continue
        vals = " ".join(f"{per_seed[l][k]:12.3f}" for l in labels)
        sd = agg[k].get("sd")
        print(f"{k:24s} {vals} {agg[k]['mean']:10.3f} " + (f"{sd:9.3f}" if sd is not None else f"{'-':>9s}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
