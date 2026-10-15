#!/usr/bin/env bash
# R3: R1's exact image (the reliable version + the reply logs), with the model server now taking native tool calls
# (enabled by the owner, 15 Oct). Three runs, one case at a time, 30 minutes a case; read against R1.
cd "$(dirname "$0")"
for i in 1 2 3; do
  bash rerun_small.sh "r3-${i}"
done
echo "$(date +%T) R3 ALL DONE" >> runs-r3-3.log
