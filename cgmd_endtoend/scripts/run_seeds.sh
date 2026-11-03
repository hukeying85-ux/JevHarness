#!/bin/bash
# Independent-repeat driver: rebuild the one-pot system with a NEW placement seed
# and run EM -> NVT -> NPT -> production.  Velocity seeds already differ per run
# because mdp/nvt.mdp carries gen-seed = -1.
#
#   usage: bash run_seeds.sh <arm> <box_nm> <ns> <seed> [<seed> ...]
#   e.g.   bash run_seeds.sh A 7.5 30 20261031 20261032
set -uo pipefail

ARM=${1:?arm}; BOX=${2:?box}; NS=${3:?ns}; shift 3
SEEDS=("$@")
GMX=${GMX:-/home/user/work/gmx/bin/gmx}
NP=${NP:-2}
ROOT=$(cd "$(dirname "$0")" && pwd)
ITPS=(martini_v3.0.0.itp martini_v3.0.0_solvents_v1.itp martini_v3.0.0_ions_v1.itp Protein_0.itp)
NSTEPS=$(python3 -c "print(int(round($NS*1000/0.02)))")

for SEED in "${SEEDS[@]}"; do
    D="$ROOT/sys_${ARM}_s${SEED}"
    echo "===== arm $ARM seed $SEED -> $D ====="
    rm -rf "$D"; mkdir -p "$D"
    python3 "$ROOT/build_onepot.py" --cg "$ROOT/peptide_cg.pdb" --box "$BOX" --copies 6 \
        --seed "$SEED" --out "$D" > "$D/build.log" 2>&1 || { echo "BUILD_FAIL $ARM $SEED"; continue; }
    for f in "${ITPS[@]}"; do cp "$ROOT/$f" "$D/"; done
    cp "$ROOT/mdp/"*.mdp "$D/" 2>/dev/null
    ( cd "$D" || exit 1
      set -e
      $GMX grompp -f em.mdp   -c system.gro -p topol.top -o em.tpr   -maxwarn 2 -quiet
      $GMX mdrun   -deffnm em   -nt $NP -noconfout -quiet
      $GMX grompp -f nvt.mdp  -c em.gro     -p topol.top -o nvt.tpr  -maxwarn 2 -quiet
      $GMX mdrun   -deffnm nvt  -nt $NP -quiet
      $GMX grompp -f npt.mdp  -c nvt.gro -t nvt.cpt -p topol.top -o npt.tpr -maxwarn 2 -quiet
      $GMX mdrun   -deffnm npt  -nt $NP -quiet
      sed "s/^nsteps.*/nsteps            = ${NSTEPS}/" prod.mdp > prod_run.mdp
      $GMX grompp -f prod_run.mdp -c npt.gro -t npt.cpt -p topol.top -o prod.tpr -maxwarn 2 -quiet
      $GMX mdrun   -deffnm prod -nt $NP -quiet
      echo "SEED_DONE $ARM $SEED"
    ) || echo "RUN_FAIL $ARM $SEED"
done
echo "ALL_SEEDS_DONE $ARM"
