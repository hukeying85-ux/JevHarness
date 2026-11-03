#!/usr/bin/env python3
"""Two SVG figures for the CG one-pot comparison (document §10 style: vector only).

  figures/cluster_vs_time.svg      largest cluster size vs time, both arms
  figures/cluster_size_dist.svg    cluster size distribution, both arms
"""
from __future__ import annotations

import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="summary json of arm A")
    ap.add_argument("--b", default=None, help="summary json of arm B")
    ap.add_argument("--labels", default="A,B")
    ap.add_argument("--outdir", default="figures")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    la, lb = (args.labels.split(",") + ["B"])[:2]

    arms = [(la, json.load(open(args.a)))]
    if args.b and os.path.exists(args.b):
        arms.append((lb, json.load(open(args.b))))

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    for label, data in arms:
        ts = data["timeseries"]
        ax.plot([p["time_ns"] for p in ts], [p["largest_cluster"] for p in ts],
                lw=1.0, label="%s (max %d)" % (label, data["oligomer"]["largest_cluster_max"]))
    ax.set_xlabel("time (ns)")
    ax.set_ylabel("largest cluster (copies)")
    ax.set_ylim(0.8, max(4.4, max(d["oligomer"]["largest_cluster_max"] for _, d in arms) + 0.4))
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("Martini 3 one-pot: largest inter-peptide cluster", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "cluster_vs_time.svg"))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.6, 3.2))
    keys = sorted({int(k) for _, d in arms for k in d["oligomer"]["cluster_size_histogram"]})
    width = 0.8 / max(1, len(arms))
    for index, (label, data) in enumerate(arms):
        hist = {int(k): v for k, v in data["oligomer"]["cluster_size_histogram"].items()}
        total = sum(hist.values())
        frac = [hist.get(k, 0) / total for k in keys]
        ax.bar([k + index * width for k in keys], frac, width=width, label=label)
    ax.set_xlabel("cluster size (peptide copies)")
    ax.set_ylabel("fraction of clusters observed")
    ax.set_xticks(keys)
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("cluster size distribution", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(args.outdir, "cluster_size_dist.svg"))
    plt.close(fig)
    print("wrote", os.path.join(args.outdir, "cluster_vs_time.svg"),
          "and", os.path.join(args.outdir, "cluster_size_dist.svg"))


if __name__ == "__main__":
    main()
