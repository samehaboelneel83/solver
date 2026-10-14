#!/usr/bin/env bash
# Step 11 (main at 581ecfb, stages off, every reply logged): the new baseline -- three tuning runs, three cases
# at a time, 30 minutes a case. No hidden run: the step decides only whether main with stages off holds step 7.
cd "$(dirname "$0")"
for i in 1 2 3; do
  bash run_parallel.sh "step11-${i}" 3
done
echo "$(date +%T) STEP11 ALL DONE" >> runs-step11-3.log
