#!/usr/bin/env bash
# The small tuning cases through the browser, N at a time (build-protocol plan, Phase 0.1): each case in its own
# browser and workspace, scored as it ends. The limit is 30 minutes (the model is shared).
#   bash run_parallel.sh <tag> [N=3]     -> runs/<p>-S-<tag>/ and runs-<tag>.log, as rerun_small.sh writes them
# Read with: python -m bench.phase1.blind runs <tag>; compare minutes with a serial run of the same image.
cd "$(dirname "$0")"
tag="${1:-par}"
n="${2:-3}"
export PW_DIR="${PW_DIR:-D:/solver-tools/pw}"
export LIMIT_MIN=30
export PARALLEL=1   # drive_case.mjs: a case's runs are its own problem's, never the platform's newest
cases=(p02_supply_chain p04_factory p06_timetable p01_hospital p08_cyber p07_grid p09_cloud p05_ambulance p03_camp p10_disaster)
one() {
  # Three statements: in one `local`, bash expands ${p} before p is assigned (14 Oct: every case wrote to
  # runs/-S-<tag>, and the three drivers overwrote each other).
  local m="$1"
  local p="${m%%_*}"
  local out="runs/${p}-S-${tag}"
  echo "$(date +%T) start $p" >> "runs-${tag}.log"
  node drive_case.mjs "cases/${p}/S" "$out" "P1 ${p} S ${tag} $(date +%H%M%S)" > "${out}.out" 2>&1
  MSYS_NO_PATHCONV=1 docker run --rm -v "D:/solver/backend:/app" -w /app solver-backend-test \
    python -m bench.phase1.score "$m" "bench/phase1/cases/${p}/S" "bench/phase1/${out}" > "${out}/score.json" 2>&1
  echo "$(date +%T) done $p" >> "runs-${tag}.log"
}
running=0
for m in "${cases[@]}"; do
  one "$m" &
  running=$((running + 1))
  if [ "$running" -ge "$n" ]; then
    wait -n
    running=$((running - 1))
  fi
done
wait
echo "$(date +%T) ALL DONE" >> "runs-${tag}.log"
