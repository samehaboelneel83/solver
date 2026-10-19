#!/usr/bin/env bash
# Every case of the hidden set through the browser, then scored -- without printing anything about the cases.
#   bash run_hidden.sh <tag> [S|M]      -> runs/hidden-<case>-<size>-<tag>/ ; read with: python -m bench.phase1.blind runs/hidden <tag>
cd "$(dirname "$0")"
tag="${1:-base}"
size="${2:-S}"
only="${3:-}"   # optional: a comma-separated list of case ids (h07,h08) to run only those, e.g. after a crash
export PW_DIR="${PW_DIR:-D:/solver-tools/pw}"
export LIMIT_MIN=30
mkdir -p runs/hidden
if [ -f "runs/hidden/skip-${tag}" ]; then
  # A marker dropped while a scripted series runs (14 Oct: step 8's hidden run dropped, the old path's hidden
  # numbers being known from step 7) ends the hidden run before it starts.
  echo "$(date +%T) SKIPPED (runs/hidden/skip-${tag})" >> "runs/hidden-${tag}.log"
  exit 0
fi
for f in ../hidden/h[0-9][0-9]_*.py; do
  m="$(basename "$f" .py)"
  p="${m%%_*}"
  case_dir="../hidden/cases/${p}/${size}"
  [ -d "$case_dir" ] || continue
  if [ -n "$only" ] && ! echo ",$only," | grep -q ",$p,"; then continue; fi
  out="runs/hidden/${p}-${size}-${tag}"
  echo "$(date +%T) start ${p} ${size}" >> "runs/hidden-${tag}.log"
  node drive_case.mjs "$case_dir" "$out" "H ${p} ${size} ${tag} $(date +%H%M)" > "${out}.out" 2>&1
  MSYS_NO_PATHCONV=1 docker run --rm -v "D:/solver/backend:/app" -w /app solver-backend-test \
    python -m bench.phase1.score "bench.hidden.${m}" "bench/hidden/cases/${p}/${size}" "bench/phase1/${out}" > "${out}/score.json" 2>/dev/null
  echo "$(date +%T) done ${p} ${size}" >> "runs/hidden-${tag}.log"
done
echo "$(date +%T) ALL DONE" >> "runs/hidden-${tag}.log"
