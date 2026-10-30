#!/usr/bin/env python3
"""Martini 3 "one-pot" CG system builder (no GROMACS needed to build).

Replicates the coarse-grained method of the project document
(§9 方法 8 · 粗粒化大体系与浓度/种子表面积扫描) on a single short peptide:

  * Martini 3 (martini_v3.0.0) single-bead-per-~3-heavy-atom mapping produced
    by martinize2 (see README: exact command line);
  * N identical copies of the peptide placed with random position *and*
    random orientation in a cubic box -> the copy number / box length pair
    defines the concentration, exactly like the document's 18/22/28 nm scan;
  * Martini water (W) at the Martini 3 number density, 0.15 M NaCl, system
    neutralised with counter-ions;
  * output: system.gro + topol.top, ready for gmx grompp.

Everything is deterministic given --seed, and only text files are written.

Usage:
    python3 build_onepot.py --cg peptide_cg.pdb --box 7.5 --copies 6 \
        --seed 20261030 --out .
"""
from __future__ import annotations

import argparse
import math
import os
import random
from typing import List, Tuple

WATER_DENSITY = 9.2      # Martini 3 W beads per nm^3 at 1 bar / 310 K
MIN_SOLUTE_GAP = 0.47    # nm, closest allowed W - peptide bead distance
MIN_COPY_GAP = 2.0       # nm, closest allowed peptide COM - peptide COM
ION_MIN_GAP = 0.8        # nm, ions are not placed closer than this to peptide


def read_cg_pdb(path: str) -> List[dict]:
    beads = []
    with open(path) as fh:
        for line in fh:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            beads.append(
                dict(
                    name=line[12:16].strip(),
                    resname=line[17:20].strip(),
                    resseq=int(line[22:26]),
                    x=float(line[30:38]) / 10.0,   # A -> nm
                    y=float(line[38:46]) / 10.0,
                    z=float(line[46:54]) / 10.0,
                )
            )
    return beads


def rot_matrix(rng: random.Random) -> List[List[float]]:
    # uniform random rotation (quaternion -> matrix)
    u1, u2, u3 = rng.random(), rng.random(), rng.random()
    q = [math.sqrt(1 - u1) * math.sin(2 * math.pi * u2),
         math.sqrt(1 - u1) * math.cos(2 * math.pi * u2),
         math.sqrt(u1) * math.sin(2 * math.pi * u3),
         math.sqrt(u1) * math.cos(2 * math.pi * u3)]
    w, x, y, z = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def apply(m, v) -> Tuple[float, float, float]:
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def mic(dx: float, box: float) -> float:
    dx -= box * round(dx / box)
    return dx


def dist2(a, b, box: float) -> float:
    return sum(mic(a[i] - b[i], box) ** 2 for i in range(3))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cg", default="peptide_cg.pdb")
    ap.add_argument("--box", type=float, default=7.5, help="cubic box edge, nm")
    ap.add_argument("--copies", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--salt", type=float, default=0.15)
    ap.add_argument("--net-charge", type=float, default=1.0,
                    help="net charge per peptide copy (YLSLLQR = +1: N-ter +1, C-ter -1, Arg +1)")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    L = args.box
    mono = read_cg_pdb(args.cg)
    if not mono:
        raise SystemExit("no beads found in %s" % args.cg)
    # centre the monomer on its centroid
    cx = sum(b["x"] for b in mono) / len(mono)
    cy = sum(b["y"] for b in mono) / len(mono)
    cz = sum(b["z"] for b in mono) / len(mono)
    mono = [dict(b, x=b["x"] - cx, y=b["y"] - cy, z=b["z"] - cz) for b in mono]

    # ---- 1. peptide copies: random position + random orientation ----------
    copies: List[List[dict]] = []
    coms: List[Tuple[float, float, float]] = []
    for _ in range(args.copies):
        for _attempt in range(4000):
            com = (rng.uniform(0, L), rng.uniform(0, L), rng.uniform(0, L))
            if all(math.sqrt(dist2(com, c, L)) >= MIN_COPY_GAP for c in coms):
                break
        else:
            raise SystemExit("could not place %d copies" % args.copies)
        coms.append(com)
        m = rot_matrix(rng)
        placed = []
        for b in mono:
            v = apply(m, (b["x"], b["y"], b["z"]))
            placed.append(dict(b, x=(com[0] + v[0]) % L,
                                  y=(com[1] + v[1]) % L,
                                  z=(com[2] + v[2]) % L))
        copies.append(placed)

    peptide_atoms = [b for c in copies for b in c]

    # ---- 2. Martini water on a jittered lattice ---------------------------
    spacing = (1.0 / WATER_DENSITY) ** (1.0 / 3.0)
    n_grid = max(2, int(round(L / spacing)))
    spacing = L / n_grid
    waters: List[Tuple[float, float, float]] = []
    for i in range(n_grid):
        for j in range(n_grid):
            for k in range(n_grid):
                p = (i * spacing + rng.uniform(0.05, 0.95) * spacing,
                     j * spacing + rng.uniform(0.05, 0.95) * spacing,
                     k * spacing + rng.uniform(0.05, 0.95) * spacing)
                if all(dist2(p, (b["x"], b["y"], b["z"]), L) > MIN_SOLUTE_GAP ** 2
                       for b in peptide_atoms):
                    waters.append(p)

    # ---- 3. ions: convert far water beads into NA+/CL- --------------------
    net_charge = args.net_charge
    volume_nm3 = L ** 3
    n_pairs = int(round(args.salt * volume_nm3 * 1e-24 * 6.02214076e23))
    total_charge = args.copies * net_charge
    n_na = int(round(n_pairs + max(0.0, -total_charge)))   # extra NA+ if the peptide is anionic
    n_cl = int(round(n_pairs + max(0.0, total_charge)))
    free = [w for w in waters
            if min(dist2(w, (b["x"], b["y"], b["z"]), L) for b in peptide_atoms) > ION_MIN_GAP ** 2]
    if len(free) < n_na + n_cl:
        raise SystemExit("not enough free water for ions")
    rng.shuffle(free)
    na_pos = free[:n_na]
    cl_pos = free[n_na:n_na + n_cl]
    taken = set(free[:n_na + n_cl])
    waters = [w for w in waters if w not in taken]

    # ---- 4. write .gro ----------------------------------------------------
    lines = ["Martini 3 one-pot CG system: %d x peptide + W + %d NA + %d CL"
             % (args.copies, n_na, n_cl),
             "%d" % (len(peptide_atoms) + len(waters) + n_na + n_cl)]
    serial = 0
    for copy_index, c in enumerate(copies):
        for b in c:
            serial += 1
            lines.append("%5d%-5s%5s%5d%8.3f%8.3f%8.3f"
                         % (serial, b["resname"][:5], b["name"][:5],
                            b["resseq"] + 7 * copy_index, b["x"], b["y"], b["z"]))
    for w in waters:
        serial += 1
        lines.append("%5d%-5s%5s%5d%8.3f%8.3f%8.3f"
                     % (serial, "W", "W", serial, w[0], w[1], w[2]))
    for p in na_pos:
        serial += 1
        lines.append("%5d%-5s%5s%5d%8.3f%8.3f%8.3f"
                     % (serial, "NA", "NA", serial, p[0], p[1], p[2]))
    for p in cl_pos:
        serial += 1
        lines.append("%5d%-5s%5s%5d%8.3f%8.3f%8.3f"
                     % (serial, "CL", "CL", serial, p[0], p[1], p[2]))
    lines.append("%10.5f%10.5f%10.5f" % (L, L, L))
    os.makedirs(args.out, exist_ok=True)
    gro = os.path.join(args.out, "system.gro")
    with open(gro, "w") as fh:
        fh.write("\n".join(lines) + "\n")

    # ---- 5. write topol.top ----------------------------------------------
    top = """\
; Martini 3 one-pot CG system built by build_onepot.py (seed {seed})
;   peptide   : YLSLLQR, {beads} Martini 3 beads / copy (martinize2, -ff martini3001)
;   copies    : {copies}   box {box} nm   -> {conc:.1f} mM
;   water     : {water} W    salt: {na} NA + {cl} CL (0.15 M NaCl, neutralised)
#include "martini_v3.0.0.itp"
#include "martini_v3.0.0_solvents_v1.itp"
#include "martini_v3.0.0_ions_v1.itp"
#include "Protein_0.itp"

[ system ]
YLSLLQR one-pot CG ({copies} copies, {box} nm)

[ molecules ]
Protein_0      {copies}
W              {water}
NA             {na}
CL             {cl}
""".format(seed=args.seed, beads=len(mono), copies=args.copies, box=L,
           conc=args.copies / volume_nm3 * 1e24 / 6.02214076e23 * 1000.0,
           water=len(waters), na=n_na, cl=n_cl)
    with open(os.path.join(args.out, "topol.top"), "w") as fh:
        fh.write(top)

    print("wrote %s and %s" % (gro, os.path.join(args.out, "topol.top")))
    print("peptide copies : %d (%d beads each)" % (args.copies, len(mono)))
    print("box            : %.2f nm  (%.1f nm^3)" % (L, volume_nm3))
    print("concentration  : %.1f mM" % (args.copies / volume_nm3 * 1e24 / 6.02214076e23 * 1000))
    print("water beads    : %d  (%.2f /nm^3)" % (len(waters), len(waters) / volume_nm3))
    print("ions           : %d NA, %d CL  (net peptide charge %+.1f per copy)" % (n_na, n_cl, net_charge))
    print("total beads    : %d" % (len(peptide_atoms) + len(waters) + n_na + n_cl))


if __name__ == "__main__":
    main()
