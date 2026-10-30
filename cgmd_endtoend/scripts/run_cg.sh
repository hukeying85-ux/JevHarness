#!/bin/bash
# Martini 3 one-pot CG pipeline: EM -> 100 ps NVT -> 1 ns NPT -> production.
# Same stage order as the project document (§7-§9) and the 0fuye CGMD pipeline.
#   usage: bash run_cg.sh [production_ns]
set -euo pipefail

GMX=${GMX:-gmx}
NS=${1:-20}
NSTEPS=$(python3 -c "print(int(round($NS*1000/0.02)))")
NP=${NP:-2}

cd "$(dirname "$0")"

echo "== EM =="
$GMX grompp -f mdp/em.mdp -c sys/system.gro -p sys/topol.top -o em.tpr -maxwarn 2 -quiet
$GMX mdrun -deffnm em -nt $NP -noconfout -quiet

echo "== NVT 100 ps =="
$GMX grompp -f mdp/nvt.mdp -c em.gro -p sys/topol.top -o nvt.tpr -maxwarn 2 -quiet
$GMX mdrun -deffnm nvt -nt $NP -quiet

echo "== NPT 1 ns =="
$GMX grompp -f mdp/npt.mdp -c nvt.gro -t nvt.cpt -p sys/topol.top -o npt.tpr -maxwarn 2 -quiet
$GMX mdrun -deffnm npt -nt $NP -quiet

echo "== production ${NS} ns =="
sed "s/^nsteps.*/nsteps            = ${NSTEPS}/" mdp/prod.mdp > prod.mdp
$GMX grompp -f prod.mdp -c npt.gro -t npt.cpt -p sys/topol.top -o prod.tpr -maxwarn 2 -quiet
$GMX mdrun -deffnm prod -nt $NP -quiet

echo "== performance =="
grep -E "Performance:|ns/day" prod.log | tail -3
