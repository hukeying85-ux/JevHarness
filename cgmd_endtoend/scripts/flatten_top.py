#!/usr/bin/env python3
"""Flatten a GROMACS .top into ONE self-contained file (no #include left).

Why this exists
---------------
The workstation's Windows GROMACS 2025.1 aborts with 0xC0000005
(-1073741819, "access violation") inside `gmx grompp` as soon as the topology
pulls in an external file through `#include`; the same grompp succeeds when the
topology is written out inline.  This is what the 100 ps smoke test on
DESKTOP-IEUDGS5 ran into on 2026-10-30 -- `grompp-em` failed on `smoke_box.top`,
and the stage that succeeded was `grompp-em-inline` on `smoke_box_inline.top`.
See results/status/gmx_smoke.json (stages 1 and 2).

A Martini 3 system is exactly the case that breaks: topol.top includes
martini_v3.0.0.itp + martini_v3.0.0_solvents_v1.itp + martini_v3.0.0_ions_v1.itp
+ Protein_0.itp.  Flatten first, then grompp.

What it does
------------
* expands `#include "file"` (and `#include <file>`) recursively, resolving each
  path relative to the file that contains it, then relative to the search dirs;
* leaves every other directive untouched, including `#ifdef`/`#else`/`#endif`
  blocks (Protein_0.itp uses `#ifdef POSRES` / `#ifdef FLEXIBLE`) and `#define`;
* inlines each distinct absolute path at most once, so a diamond include does
  not duplicate `[ moleculetype ]` definitions;
* keeps the original order, which matters because `[ system ]` and
  `[ molecules ]` must stay last.

Usage
-----
    python3 flatten_top.py sys/topol.top sys/topol_flat.top
    python3 flatten_top.py -v sys/topol.top out.top     # list what was inlined
"""
from __future__ import annotations

import argparse
import os
import re
import sys

INCLUDE_RE = re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]\s*$')


def expand(path: str, search: list[str], seen: set[str], out: list[str], depth: int = 0,
           verbose: bool = False) -> None:
    real = os.path.abspath(path)
    base = os.path.dirname(real)
    with open(real, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            m = INCLUDE_RE.match(line)
            if not m:
                out.append(line.rstrip("\n"))
                continue
            target = m.group(1)
            cand = os.path.join(base, target)
            if not os.path.exists(cand):
                for d in search:
                    alt = os.path.join(d, target)
                    if os.path.exists(alt):
                        cand = alt
                        break
            if not os.path.exists(cand):
                raise SystemExit(f"{path}:{lineno}: cannot resolve #include \"{target}\"")
            key = os.path.abspath(cand)
            if key in seen:
                out.append(f"; [{os.path.basename(key)}] already inlined above")
                if verbose:
                    out.append(f";   (skipped duplicate include on {path}:{lineno})")
                continue
            seen.add(key)
            out.append(f"; --- begin {os.path.basename(key)} (inlined from {os.path.basename(real)}) ---")
            expand(key, search, seen, out, depth + 1, verbose)
            out.append(f"; --- end {os.path.basename(key)} ---")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="inline every #include of a .top into one file")
    ap.add_argument("topology")
    ap.add_argument("output")
    ap.add_argument("--search-dir", action="append", default=[],
                    help="extra directory for resolving #include paths (repeatable)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    search = [os.path.abspath(os.path.dirname(args.topology))] + [os.path.abspath(d) for d in args.search_dir]
    out: list[str] = [f"; flattened from {os.path.basename(args.topology)} by flatten_top.py",
                      "; single-file topology: no #include left (Windows grompp workaround)"]
    seen = {os.path.abspath(args.topology)}
    expand(args.topology, search, seen, out, verbose=args.verbose)
    text = "\n".join(out).rstrip("\n") + "\n"

    leftover = [ln for ln in text.splitlines() if INCLUDE_RE.match(ln)]
    if leftover:
        raise SystemExit(f"still contains #include: {leftover}")
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(text)
    if args.verbose:
        for p in sorted(seen):
            print("inlined:", p, file=sys.stderr)
    print(f"wrote {args.output} ({len(text.splitlines())} lines, {len(seen)} files inlined)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
