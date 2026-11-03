#!/bin/bash
# Parameter-sensitivity arm (document §9 asks for 1-2 cross-checks of the CG
# parameterisation / secondary-structure constraints).
#
# Variant: the SAME peptide, SAME box, SAME placement seed and SAME mdp set as
# arm A, but martinize2 was run WITHOUT -elastic (no elastic network on the
# backbone).  Everything else -- 18 beads, Martini 3, 21 mM, 6 copies -- is held
# fixed, so any change in cluster statistics is attributable to the chain
# stiffness that the elastic network introduces.
set -euo pipefail
GMX=${GMX:-/home/user/work/gmx/bin/gmx}
NP=${NP:-2}
ROOT=/home/user/work/cg
V=$ROOT/noelastic
D=$ROOT/sys_S_noelastic
NS=30
NSTEPS=$(python3 -c "print(int(round($NS*1000/0.02)))")

rm -rf "$D"; mkdir -p "$D"
python3 "$ROOT/build_onepot.py" --cg "$V/peptide_cg.pdb" --box 7.5 --copies 6 \
    --seed 20261030 --out "$D" > "$D/build.log" 2>&1
cp "$ROOT/martini_v3.0.0.itp" "$ROOT/martini_v3.0.0_solvents_v1.itp" \
   "$ROOT/martini_v3.0.0_ions_v1.itp" "$V/Protein_0.itp" "$D/"
cp "$ROOT/mdp/"*.mdp "$D/"
cd "$D"
$GMX grompp -f em.mdp  -c system.gro -p topol.top -o em.tpr  -maxwarn 2 -quiet
$GMX mdrun  -deffnm em -nt $NP -noconfout -quiet
$GMX grompp -f nvt.mdp -c em.gro     -p topol.top -o nvt.tpr -maxwarn 2 -quiet
$GMX mdrun  -deffnm nvt -nt $NP -quiet
$GMX grompp -f npt.mdp -c nvt.gro -t nvt.cpt -p topol.top -o npt.tpr -maxwarn 2 -quiet
$GMX mdrun  -deffnm npt -nt $NP -quiet
sed "s/^nsteps.*/nsteps            = ${NSTEPS}/" prod.mdp > prod_run.mdp
$GMX grompp -f prod_run.mdp -c npt.gro -t npt.cpt -p topol.top -o prod.tpr -maxwarn 2 -quiet
$GMX mdrun  -deffnm prod -nt $NP -quiet
echo "SENSITIVITY_DONE"
