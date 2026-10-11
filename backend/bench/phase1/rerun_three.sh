#!/usr/bin/env bash
# Every small tuning case through the browser THREE times (the issues report of 11 October 2026, A.1: one run moves
# by about two cases on this LLM), then the hidden set once.
#   bash rerun_three.sh <tag>      -> runs/<p>-S-<tag>-1 .. -3, then runs/hidden/<h>-S-<tag>
#   read with: python -m bench.phase1.blind runs <tag>-1 (and -2, -3); python -m bench.phase1.three runs <tag>
cd "$(dirname "$0")"
tag="${1:-x}"
for i in 1 2 3; do
  bash rerun_small.sh "${tag}-${i}"
done
bash run_hidden.sh "$tag" S
