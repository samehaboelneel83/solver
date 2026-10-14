#!/usr/bin/env bash
# Step 10 (stage checks + revisions, main at 0376ba8): three tuning runs, three cases at a time (the parallel runner's
# first use, build-protocol plan 0.1), then the hidden set serially. 30 minutes a case.
# Launch detached; read with: python -m bench.phase1.three runs step10 ; python -m bench.phase1.blind bench/phase1/runs/hidden step10
cd "$(dirname "$0")"
for i in 1 2 3; do
  bash run_parallel.sh "step10-${i}" 3
done
bash run_hidden.sh step10 S
echo "$(date +%T) STEP9 ALL DONE" >> runs-step10-1.log
