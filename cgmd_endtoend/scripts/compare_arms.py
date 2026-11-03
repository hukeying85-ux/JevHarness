#!/usr/bin/env python3
"""Merge two one-pot arms into the concentration-scan comparison table (§9)."""
from __future__ import annotations

import argparse
import json

KEYS = ("largest_cluster_mean", "largest_cluster_max",
        "P_largest_cluster_ge2", "P_largest_cluster_ge3", "P_largest_cluster_ge4",
        "mean_inter_copy_contacts", "any_pair_contact_fraction")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--conc-a", type=float, default=21.0)
    ap.add_argument("--conc-b", type=float, default=11.6)
    ap.add_argument("--box-a", type=float, default=7.774)
    ap.add_argument("--box-b", type=float, default=9.5)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--out", default="arm_comparison.json")
    args = ap.parse_args()
    a = json.load(open(args.a))
    b = json.load(open(args.b))
    rows = {}
    for key in KEYS:
        rows[key] = {args.label_a: a["oligomer"].get(key), args.label_b: b["oligomer"].get(key)}
        va, vb = rows[key][args.label_a], rows[key][args.label_b]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and vb:
            rows[key]["ratio_%s_over_%s" % (args.label_a, args.label_b)] = round(va / vb, 3)
    out = {
        "schema": "cgmd.martini.onepot.comparison.v1",
        "arms": {
            args.label_a: {"box_nm": args.box_a, "concentration_mM": args.conc_a,
                           "window_ns": a["window_ns"], "frames": a["frames_analysed"],
                           "rg_mean_nm": a["conformation"]["rg_mean_nm"]},
            args.label_b: {"box_nm": args.box_b, "concentration_mM": args.conc_b,
                           "window_ns": b["window_ns"], "frames": b["frames_analysed"],
                           "rg_mean_nm": b["conformation"]["rg_mean_nm"]},
        },
        "oligomer_metrics": rows,
        "note": ("CG 端点只用于相对比较（文档 §9）：不得把 CG 时间或簇概率读成真实 "
                 "Aβ fibrillation 速率；单种子单轨迹不含误差棒。"),
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
