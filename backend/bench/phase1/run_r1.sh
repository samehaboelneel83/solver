#!/usr/bin/env bash
# R1: the reliable version with every reply logged (release/reliable at fbccdf7), one case at a time, 30 minutes a
# case -- the baseline for the reply-shortening change, and where its time goes.
cd "$(dirname "$0")"
bash rerun_small.sh r1-1
echo "$(date +%T) R1 ALL DONE" >> runs-r1-1.log
