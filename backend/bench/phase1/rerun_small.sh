#!/usr/bin/env bash
# Every small case through the browser again, one after another, then scored (phase 1, after the fixes).
#   bash rerun_small.sh <tag>      -> runs/<problem>-S-<tag>/ and runs-<tag>.log
cd "$(dirname "$0")"
tag="${1:-after}"
export PW_DIR="C:/Users/user/AppData/Local/Temp/claude/D--solver/3932906e-32f9-4d3f-b0fb-ac43eb061e80/scratchpad/pw"
export LIMIT_MIN=20
for m in p02_supply_chain p04_factory p06_timetable p01_hospital p08_cyber p07_grid p09_cloud p05_ambulance p03_camp p10_disaster; do
  p="${m%%_*}"
  out="runs/${p}-S-${tag}"
  echo "$(date +%T) start $p" >> "runs-${tag}.log"
  node drive_case.mjs "cases/${p}/S" "$out" "P1 ${p} S ${tag}" > "${out}.out" 2>&1
  MSYS_NO_PATHCONV=1 docker run --rm -v "D:/solver/backend:/app" -w /app solver-backend-test \
    python -m bench.phase1.score "$m" "bench/phase1/cases/${p}/S" "bench/phase1/${out}" > "${out}/score.json" 2>&1
  echo "$(date +%T) done $p" >> "runs-${tag}.log"
done
echo "$(date +%T) ALL DONE" >> "runs-${tag}.log"
