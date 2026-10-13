#!/usr/bin/env bash
# Step 8, resumed after the driver was killed on p04 (13 Oct, 23:55): the rest of run 1, then runs 2 and 3,
# then the hidden set. Launched detached from the terminal so no tool timeout ends it.
cd "$(dirname "$0")"
bash rerun_small.sh step8-1 p04,p06,p01,p08,p07,p09,p05,p03,p10
bash rerun_small.sh step8-2
bash rerun_small.sh step8-3
bash run_hidden.sh step8 S
echo "$(date +%T) STEP8 ALL DONE" >> runs-step8-1.log
