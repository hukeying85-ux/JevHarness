#!/usr/bin/env python3
"""CG one-pot endpoints (document §9 oligomer statistics), MDAnalysis only.

Reads a Martini trajectory and reports, per frame:
  * cluster analysis of the peptide copies (single linkage on centre-of-mass
    distances with a 0.6 nm Martini contact cut-off),
  * largest cluster, cluster size distribution, P(contact) per copy pair,
  * inter-copy bead contacts (< 0.6 nm, PBC aware),
  * radius of gyration per copy and for the whole peptide group,
  * minimum inter-copy COM distance (a direct measure of "who met whom").

Usage:
    python3 analyze_cg.py --gro eq.gro --xtc prod.xtc --copies 6 --beads 18 \
        --out summary_metrics.json
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter

import numpy as np
import MDAnalysis as mda
from MDAnalysis.analysis import distances

CONTACT_NM = 0.6          # Martini 3 first-shell contact distance
CONTACT_A = CONTACT_NM * 10.0   # MDAnalysis reads .gro/.xtc positions in Angstrom


def unwrap(pos, box):
    """Make one molecule whole: GROMACS writes wrapped coordinates, so a copy
    that crossed the periodic boundary would otherwise look 7 nm long."""
    ref = pos[0].copy()
    d = pos - ref
    d -= box * np.round(d / box)
    return ref + d


def rg_of(pos, box):
    c = unwrap(pos, box)
    com = c.mean(axis=0)
    return float(np.sqrt(((c - com) ** 2).sum(axis=1).mean()))


def cluster_labels_from_adjacency(adj):
    """Single-linkage clustering on an inter-molecular contact graph."""
    n = len(adj)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if adj[i, j]:
                union(i, j)
    labels = [find(i) for i in range(n)]
    sizes = Counter(labels)
    return labels, max(sizes.values()) if sizes else 0, sorted(sizes.values(), reverse=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gro", required=True)
    ap.add_argument("--xtc", required=True)
    ap.add_argument("--copies", type=int, default=6)
    ap.add_argument("--beads", type=int, default=18)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--tmax-ns", type=float, default=None,
                    help="only analyse frames up to this time (for equal-window comparisons)")
    ap.add_argument("--out", default="summary_metrics.json")
    args = ap.parse_args()

    u = mda.Universe(args.gro, args.xtc)
    prot = u.select_atoms("resname TYR LEU SER GLN ARG")
    n_expect = args.copies * args.beads
    if len(prot) != n_expect:
        raise SystemExit("peptide selection has %d beads, expected %d" % (len(prot), n_expect))

    # split the peptide group into copies
    copies = [prot[i * args.beads:(i + 1) * args.beads] for i in range(args.copies)]

    frames = []
    pair_contact_frames = np.zeros((args.copies, args.copies))
    pair_min_com = np.full((args.copies, args.copies), np.inf)
    n_frames = 0
    cluster_hist = Counter()
    max_cluster_series = []

    for ts in u.trajectory[::args.stride]:
        if args.tmax_ns is not None and ts.time / 1000.0 > args.tmax_ns + 1e-9:
            break
        box_full = np.asarray(ts.dimensions, dtype=float)
        box = box_full[:3]
        com = np.array([unwrap(c.positions, box).mean(axis=0) for c in copies])

        # contact graph: two copies are linked if ANY of their beads is within
        # CONTACT_A (the document's definition: a cluster needs at least one
        # inter-peptide contact, not a centre-of-mass distance)
        adjacent = np.zeros((args.copies, args.copies), dtype=bool)
        n_contacts = 0
        for i in range(args.copies):
            for j in range(i + 1, args.copies):
                d = distances.distance_array(copies[i].positions, copies[j].positions, box=box_full)
                n_ij = int((d < CONTACT_A).sum())
                n_contacts += n_ij
                if n_ij:
                    adjacent[i, j] = adjacent[j, i] = True
                    pair_contact_frames[i, j] += 1
                    pair_contact_frames[j, i] += 1
                c = com[j] - com[i]
                c -= box * np.round(c / box)
                dist = math.sqrt(float(np.dot(c, c)))
                pair_min_com[i, j] = min(pair_min_com[i, j], dist)
                pair_min_com[j, i] = pair_min_com[i, j]

        labels, biggest, sizes = cluster_labels_from_adjacency(adjacent)
        cluster_hist.update(sizes)
        max_cluster_series.append(biggest)

        rg = [rg_of(c.positions, box) / 10.0 for c in copies]
        frames.append(
            dict(
                time_ns=round(float(ts.time) / 1000.0, 3),
                largest_cluster=biggest,
                cluster_sizes=sizes,
                inter_copy_contacts=n_contacts,
                rg_per_copy_nm=[round(x, 3) for x in rg],
                rg_mean_nm=round(float(np.mean(rg)), 3),
                box_nm=[round(float(x) / 10.0, 3) for x in box],
            )
        )
        n_frames += 1

    if n_frames == 0:
        raise SystemExit("no frames analysed")

    contact_prob = pair_contact_frames / n_frames
    ge2 = float(np.mean([f["largest_cluster"] >= 2 for f in frames]))
    ge3 = float(np.mean([f["largest_cluster"] >= 3 for f in frames]))
    ge4 = float(np.mean([f["largest_cluster"] >= 4 for f in frames]))
    iu = np.triu_indices(args.copies, 1)
    summary = {
        "schema": "cgmd.cg_onepot.summary.v1",
        "frames_analysed": n_frames,
        "stride": args.stride,
        "cutoff_nm": CONTACT_NM,
        "window_ns": [frames[0]["time_ns"], frames[-1]["time_ns"]],
        "copies": args.copies,
        "beads_per_copy": args.beads,
        "oligomer": {
            "largest_cluster_mean": round(float(np.mean(max_cluster_series)), 3),
            "largest_cluster_max": int(max(max_cluster_series)),
            "largest_cluster_last": int(max_cluster_series[-1]),
            "cluster_size_histogram": {str(k): int(v) for k, v in sorted(cluster_hist.items())},
            "mean_inter_copy_contacts": round(float(np.mean([f["inter_copy_contacts"] for f in frames])), 3),
            "max_inter_copy_contacts": int(max(f["inter_copy_contacts"] for f in frames)),
            "pair_contact_probability": {
                "%d-%d" % (i, j): round(float(contact_prob[i, j]), 3) for i, j in zip(*iu)
            },
            "pair_min_com_distance_nm": {
                "%d-%d" % (i, j): (None if math.isinf(pair_min_com[i, j]) else round(float(pair_min_com[i, j]) / 10.0, 3))
                for i, j in zip(*iu)
            },
            "any_pair_contact_fraction": round(float((contact_prob[iu] > 0).mean()), 3),
            "P_largest_cluster_ge2": round(ge2, 3),
            "P_largest_cluster_ge3": round(ge3, 3),
            "P_largest_cluster_ge4": round(ge4, 3),
        },
        "conformation": {
            "rg_mean_nm": round(float(np.mean([f["rg_mean_nm"] for f in frames])), 3),
            "rg_min_nm": round(float(min(min(f["rg_per_copy_nm"]) for f in frames)), 3),
            "rg_max_nm": round(float(max(max(f["rg_per_copy_nm"]) for f in frames)), 3),
        },
        "box_nm_mean": [round(float(np.mean([f["box_nm"][i] for f in frames])), 3) for i in range(3)],
        "timeseries": [dict(time_ns=f["time_ns"], largest_cluster=f["largest_cluster"],
                            inter_copy_contacts=f["inter_copy_contacts"],
                            rg_mean_nm=f["rg_mean_nm"]) for f in frames[::max(1, len(frames) // 120)]],
    }
    with open(args.out, "w") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print(json.dumps({k: summary[k] for k in ("frames_analysed", "window_ns", "oligomer", "conformation")},
                     indent=2, ensure_ascii=False)[:2500])
    print("wrote", args.out)


if __name__ == "__main__":
    main()
