"""End-to-end Martini 3 AMP pipeline client & Windows-safe system builder.

Bridges ``JevHarness`` with ``hukeying85-ux/0fuye``'s 12-stage coarse-grained
molecular dynamics workflow while fixing four real upstream issues uncovered
during live execution against ``vermouth`` (``martinize2``), ``insane``, and
``marrink-lab/martini-forcefields``:

1. ``martini-forcefields`` is hosted on GitHub
   (``https://github.com/marrink-lab/martini-forcefields.git``), not PyPI;
   :func:`ensure_martini3_forcefield` clones and resolves
   ``regular/v3.0.0/gmx_files`` automatically when needed.
2. ``martinize2`` requires ``-ss`` to be either omitted or match the exact
   residue length (e.g. ``"H" * len(sequence)``), and writes ``Protein_0.itp``
   into the process working directory; we run ``martinize2`` with
   ``cwd=workdir`` and omit incompatible external ``vermouth_files`` flags so
   bundled ``martini3001`` parses cleanly.
3. Cross-drive ``os.path.relpath`` (``C:\\`` vs ``F:\\``) and deep ``#include``
   paths trigger ``0xC0000005`` in Windows ``gmx grompp`` 2025.1; we stage all
   referenced ``*.itp`` files flat inside ``workdir`` and rewrite ``topol.top``
   includes to local filenames (``#include "martini_v3.0.0.itp"``).
4. Enforces strict repository hygiene: heavy trajectory files
   (``.xtc/.trr/.tpr/.gro/.edr/.edv/.cpt``) remain inside scratch ``workdir``
   and never enter Git; only ``< 1 MB`` ``summary_metrics.json`` and ``.svg``
   figures are accepted as deliverables.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

from . import cgmd_desk

MARTINI3_REPO_URL = "https://github.com/marrink-lab/martini-forcefields.git"
DEFAULT_MAGAININ2 = "GIGKFLHSAKKFGKAFVGEIMNS"
MAX_SUMMARY_BYTES = 1_000_000


class PipelineClientError(RuntimeError):
    """Raised when preflight validation or system preparation fails."""


def _import_0fuye_cgmd(checkout: Path) -> dict[str, Any]:
    for entry in (checkout.resolve(), (checkout / "code" / "cgmd").resolve()):
        entry_str = str(entry)
        if entry_str not in sys.path:
            sys.path.insert(0, entry_str)
    import importlib

    return {
        "task_contract": importlib.import_module("core.task_contract"),
        "config": importlib.import_module("cgmd.config"),
        "engine": importlib.import_module("cgmd.engine"),
        "peptide": importlib.import_module("cgmd.peptide"),
        "seq2pdb": importlib.import_module("cgmd.seq2pdb"),
        "topology": importlib.import_module("cgmd.topology"),
        "index": importlib.import_module("cgmd.index"),
        "figure": importlib.import_module("cgmd.figure"),
    }


def screen_peptide(
    sequence: str,
    *,
    name: str = "candidate",
    secondary_structure: str = "H",
    checkout_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Deterministic Stage-1 biophysical pre-screen before spending GPU hours."""
    checkout = cgmd_desk.ensure_0fuye_client(checkout_dir, sync=False)
    mods = _import_0fuye_cgmd(checkout)
    clean_seq = mods["task_contract"].validate_sequence(sequence)
    desc = mods["peptide"].describe(clean_seq)
    desc["name"] = name

    length = int(desc["length"])
    charge = float(desc["net_charge_ph7_4"])
    mu_h = float(
        desc["hydrophobic_moment_helix"]
        if secondary_structure.upper().startswith("H")
        else desc["hydrophobic_moment_beta"]
    )
    amph = float(desc["amphipathic_face_ratio"])

    reasons: list[str] = []
    if not (10 <= length <= 60):
        reasons.append(f"length={length} outside optimal Martini 3 AMP window [10, 60]")
    if charge < 2.0:
        reasons.append(f"net_charge_pH7_4={charge:.2f} < +2.0 (weak electrostatic attraction to POPG)")
    if mu_h < 0.35:
        reasons.append(f"hydrophobic_moment={mu_h:.3f} < 0.35 (low amphipathicity)")

    if not reasons and charge >= 2.5 and mu_h >= 0.40 and amph >= 0.35:
        tier = "full_production_1000ns"
        recommended_ns = 1000.0
    elif charge >= 1.5 and 8 <= length <= 80:
        tier = "fast_screen_100ns"
        recommended_ns = 100.0
    else:
        tier = "reject_before_gpu"
        recommended_ns = 0.0

    return {
        "name": name,
        "sequence": clean_seq,
        "secondary_structure": secondary_structure.upper()[:1] or "H",
        "tier": tier,
        "recommended_production_ns": recommended_ns,
        "reasons": reasons,
        "peptide": desc,
    }


def ensure_martini3_forcefield(
    explicit_dir: Path | str | None = None,
    *,
    cache_root: Path | None = None,
) -> Path:
    """Locate or clone ``marrink-lab/martini-forcefields`` ``v3.0.0/gmx_files``."""
    if explicit_dir is not None:
        candidate = Path(explicit_dir).expanduser().resolve()
        if (candidate / "martini_v3.0.0.itp").is_file():
            return candidate
        nested = candidate / "martini_forcefields" / "regular" / "v3.0.0" / "gmx_files"
        if (nested / "martini_v3.0.0.itp").is_file():
            return nested
        raise PipelineClientError(f"martini_v3.0.0.itp not found under {candidate}")

    root = (cache_root or (Path(__file__).resolve().parents[1] / ".cache")).resolve()
    clone_dir = root / "martini-forcefields"
    gmx_files = clone_dir / "martini_forcefields" / "regular" / "v3.0.0" / "gmx_files"
    if not (gmx_files / "martini_v3.0.0.itp").is_file():
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        if clone_dir.exists():
            shutil.rmtree(clone_dir)
        proc = subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", MARTINI3_REPO_URL, str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0 or not (gmx_files / "martini_v3.0.0.itp").is_file():
            raise PipelineClientError(
                f"Failed to fetch Martini 3 forcefield from {MARTINI3_REPO_URL}: {(proc.stderr or proc.stdout).strip()}"
            )
    return gmx_files


def expand_secondary_structure(ss: str, length: int) -> str:
    """Normalize secondary structure string for ``martinize2 -ss``."""
    cleaned = (ss or "C").strip().upper()
    if not cleaned:
        cleaned = "C"
    if len(cleaned) == 1:
        return cleaned * length
    if len(cleaned) != length:
        raise PipelineClientError(
            f"secondary_structure length ({len(cleaned)}) must be 1 or match sequence length ({length})"
        )
    return cleaned


def stage_flat_itp_includes(top_path: Path, include_files: list[str | Path]) -> list[str]:
    """Copy referenced ``*.itp`` files into ``top_path.parent`` and flatten ``#include``s.

    Prevents both Windows cross-drive ``relpath`` ``ValueError`` and the
    ``gmx grompp`` 2025.1 ``0xC0000005`` crash on deep relative include paths.
    """
    workdir = top_path.parent.resolve()
    staged_names: list[str] = []
    for raw_inc in include_files:
        src = Path(raw_inc).resolve()
        if not src.is_file():
            continue
        dst = workdir / src.name
        if src != dst:
            shutil.copy2(src, dst)
        staged_names.append(src.name)

    text = top_path.read_text(encoding="utf-8")

    def _rewrite(match: re.Match[str]) -> str:
        inc_target = match.group(1)
        base_name = Path(inc_target).name
        if (workdir / base_name).is_file():
            return f'#include "{base_name}"'
        return match.group(0)

    rewritten = re.sub(r'#include\s+"([^"]+)"', _rewrite, text)
    top_path.write_text(rewritten, encoding="utf-8", newline="\n")
    return staged_names


def build_martini3_system(
    workdir: Path | str,
    *,
    sequence: str = DEFAULT_MAGAININ2,
    peptide_name: str = "magainin2",
    secondary_structure: str = "H",
    lipids: dict[str, float] | None = None,
    box_xy_nm: float = 12.0,
    box_z_nm: float = 8.0,
    salt_m: float = 0.15,
    temperature_k: float = 310.0,
    equilibration_ns: float = 20.0,
    production_ns: float = 1000.0,
    martini3_dir: Path | str | None = None,
    martinize2_bin: str | None = None,
    insane_bin: str | None = None,
    checkout_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Execute Stages 1-6 cleanly and produce a self-contained GROMACS run dir."""
    checkout = cgmd_desk.ensure_0fuye_client(checkout_dir, sync=False)
    mods = _import_0fuye_cgmd(checkout)

    clean_seq = mods["task_contract"].validate_sequence(sequence)
    ss_full = expand_secondary_structure(secondary_structure, len(clean_seq))
    ff_dir = ensure_martini3_forcefield(martini3_dir)

    martinize_exe = martinize2_bin or shutil.which("martinize2")
    insane_exe = insane_bin or shutil.which("insane")
    if not martinize_exe:
        raise PipelineClientError("martinize2 executable not found on PATH (pip install vermouth)")
    if not insane_exe:
        raise PipelineClientError("insane executable not found on PATH (pip install insane)")

    wdir = Path(workdir).expanduser().resolve()
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "logs").mkdir(exist_ok=True)

    lipid_map = dict(lipids or {"POPE": 3.0, "POPG": 1.0})
    cfg = mods["config"].Config(
        workdir=str(wdir),
        sequence=clean_seq,
        peptide_name=peptide_name,
        secondary_structure=ss_full[0],
        lipids=lipid_map,
        box_xy_nm=box_xy_nm,
        box_z_nm=box_z_nm,
        salt_m=salt_m,
        temperature_k=temperature_k,
        equilibration_ns=equilibration_ns,
        production_ns=production_ns,
        martini3_dir=str(ff_dir),
    )

    # Render em.mdp / eq.mdp / prod.mdp without requiring gmx on the builder host
    mdp_dir = Path(mods["engine"].MDP_DIR)
    eq_steps = int(round((cfg.equilibration_ns * 1000.0) / cfg.dt_ps))
    prod_steps = int(round((cfg.production_ns * 1000.0) / cfg.dt_ps))
    frame_steps = max(100, int(round(cfg.frame_stride_ps / cfg.dt_ps)))
    mods["engine"].render_mdp(str(mdp_dir / "em.mdp.in"), str(wdir / "em.mdp"), {"EM_STEPS": cfg.em_steps})
    mods["engine"].render_mdp(
        str(mdp_dir / "eq.mdp.in"),
        str(wdir / "eq.mdp"),
        {"DT_PS": cfg.dt_ps, "EQ_STEPS": eq_steps, "TEMPERATURE_K": cfg.temperature_k, "SEED": cfg.seed},
    )
    mods["engine"].render_mdp(
        str(mdp_dir / "prod.mdp.in"),
        str(wdir / "prod.mdp"),
        {"DT_PS": cfg.dt_ps, "PROD_STEPS": prod_steps, "TEMPERATURE_K": cfg.temperature_k, "XTCOUT_STEPS": frame_steps},
    )

    # Stage 2: Atomistic 3D structure
    structure = mods["seq2pdb"].build_structure(clean_seq, str(wdir), ss=ss_full[0])

    # Stage 3: martinize2 (run inside wdir so Protein_0.itp lands in wdir; omit broken -ff-dir)
    cg_pdb = wdir / "peptide_cg.pdb"
    pep_top = wdir / "peptide.top"
    m_cmd = [
        martinize_exe,
        "-f", str(structure["path"]),
        "-x", str(cg_pdb),
        "-o", str(pep_top),
        "-name", "Protein",
        "-ff", "martini3001",
        "-ss", ss_full,
        "-ignh",
        "-elastic", "-ef", "500", "-el", "0.5", "-eu", "0.9",
        "-p", "backbone",
        "-maxwarn", "1",
    ]
    m_proc = subprocess.run(m_cmd, cwd=str(wdir), capture_output=True, text=True, timeout=120, check=False)
    (wdir / "logs" / "martinize2.out").write_text((m_proc.stdout or "") + "\n" + (m_proc.stderr or ""), encoding="utf-8")
    if m_proc.returncode != 0 or not cg_pdb.is_file():
        raise PipelineClientError(f"martinize2 failed (exit {m_proc.returncode}): {(m_proc.stderr or m_proc.stdout)[-400:]}")

    # Stage 4: insane POPE:POPG membrane + solvent + salt
    sys_gro = wdir / "system.gro"
    ins_top = wdir / "insane.top"
    i_cmd = [
        insane_exe,
        "-f", str(cg_pdb),
        "-o", str(sys_gro),
        "-p", str(ins_top),
        "-pbc", "rectangular",
        "-x", f"{box_xy_nm:.3f}",
        "-y", f"{box_xy_nm:.3f}",
        "-z", f"{box_z_nm:.3f}",
        "-a", f"{cfg.area_per_lipid:.3f}",
        "-sol", "W",
        "-salt", f"{salt_m:.3f}",
    ]
    for lip, ratio in lipid_map.items():
        ratio_str = str(int(ratio)) if float(ratio).is_integer() else str(ratio)
        i_cmd += ["-l", f"{lip}:{ratio_str}"]
    help_proc = subprocess.run([insane_exe, "--help"], capture_output=True, text=True, timeout=30, check=False)
    if "-ff" in ((help_proc.stdout or "") + (help_proc.stderr or "")):
        i_cmd += ["-ff", "M3"]
    i_proc = subprocess.run(i_cmd, cwd=str(wdir), capture_output=True, text=True, timeout=120, check=False)
    (wdir / "logs" / "insane.out").write_text((i_proc.stdout or "") + "\n" + (i_proc.stderr or ""), encoding="utf-8")
    if i_proc.returncode != 0 or not sys_gro.is_file():
        raise PipelineClientError(f"insane failed (exit {i_proc.returncode}): {(i_proc.stderr or i_proc.stdout)[-400:]}")

    # Stage 5: Self-contained topology with flat local .itp staging
    top_out = wdir / "topol.top"
    topo_report = mods["topology"].build_topology(
        insane_top=str(ins_top),
        peptide_top=str(pep_top),
        ff_roots=[str(ff_dir)],
        out_path=str(top_out),
        system_name=f"CGMD {peptide_name} in POPE:POPG bilayer",
    )
    staged_itps = stage_flat_itp_includes(top_out, list(topo_report.get("includes") or []))
    validation = mods["topology"].validate_topology(topo_report, str(sys_gro))
    if not validation.get("consistent"):
        raise PipelineClientError(f"Atom count mismatch between topol.top and system.gro: {validation}")

    # Stage 6: Index groups
    idx_info = mods["index"].write_index(
        str(sys_gro),
        str(wdir / "index.ndx"),
        peptide_atoms=int(topo_report["peptide_atoms_per_copy"]),
        lipid_names=list(lipid_map.keys()),
    )

    return {
        "workdir": str(wdir),
        "peptide_name": peptide_name,
        "sequence": clean_seq,
        "secondary_structure": ss_full,
        "peptide_moleculetype": topo_report["peptide_moleculetype"],
        "peptide_beads": int(topo_report["peptide_atoms_per_copy"]),
        "molecules": topo_report["molecules"],
        "validation": validation,
        "staged_itps": staged_itps,
        "index_groups": idx_info["groups"],
        "gmx_commands": [
            "gmx grompp -f em.mdp -c system.gro -p topol.top -n index.ndx -o em.tpr -maxwarn 2",
            "gmx mdrun -deffnm em -nb cpu -ntomp 8",
            "gmx grompp -f eq.mdp -c em.gro -r em.gro -p topol.top -n index.ndx -o eq.tpr -maxwarn 2",
            "gmx mdrun -deffnm eq -nb gpu -pme cpu -bonded gpu -gpu_id 0",
            "gmx grompp -f prod.mdp -c eq.gro -t eq.cpt -p topol.top -n index.ndx -o prod.tpr -maxwarn 2",
            "gmx mdrun -deffnm prod -nb gpu -pme cpu -bonded gpu -gpu_id 0 -pin on",
        ],
    }


def validate_pipeline_deliverables(result_dir: Path | str) -> dict[str, Any]:
    """Verify Stage 10-11 outputs satisfy ``< 1 MB`` & zero-trajectory rules."""
    root = Path(result_dir).expanduser().resolve()
    summary_path = root / "summary_metrics.json"
    if not summary_path.is_file():
        return {"ok": False, "reason": f"missing {summary_path}"}
    size_bytes = summary_path.stat().st_size
    forbidden = [
        p.name for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in cgmd_desk.FORBIDDEN_TRAJECTORY_EXTENSIONS
    ]
    svgs = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.svg"))
    total_bytes = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    return {
        "ok": size_bytes < MAX_SUMMARY_BYTES and total_bytes < MAX_SUMMARY_BYTES and not forbidden,
        "summary_bytes": size_bytes,
        "total_bytes": total_bytes,
        "svg_figures": svgs,
        "forbidden_files": forbidden,
    }
