#!/usr/bin/env bash
# R2 (release/reliable 538fb39: every fault in one send-back): three runs, one case at a time, 30 minutes a case;
# read against R1 (5 right, 2 wrong unwarned, 49 whole proposals).
cd "$(dirname "$0")"
for i in 1 2 3; do
  bash rerun_small.sh "r2-${i}"
done
echo "$(date +%T) R2 ALL DONE" >> runs-r2-3.log
