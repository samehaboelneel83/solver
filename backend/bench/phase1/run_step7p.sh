#!/usr/bin/env bash
# Step 7's image measured under the parallel runner's conditions (three cases at a time, 30 minutes a case), so
# steps 9-11 (all measured in parallel) can be compared with it fairly. One run.
cd "$(dirname "$0")"
bash run_parallel.sh "step7p-1" 3
