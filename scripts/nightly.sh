#!/usr/bin/env bash
#
# scripts/nightly.sh -- this repository's CI: every check, then the large benchmark.
#
# There is no git remote, so no hosted CI can run; a workflow file for one
# would rot unrun, as `smoke_test.sh` once did. This is the job instead,
# run nightly by the scheduled task `solver-nightly` (see `--install`) and
# runnable by hand at any time.
#
#   1. `scripts/check.sh` -- lint, types, both test suites, the build --
#      on a clean detached worktree of `master`, so work in progress in the
#      main checkout neither breaks nor excuses the night.
#   2. `python -m bench.nightly` -- the L-size instances on every backend,
#      stored in `bench_result`, compared with the previous night: wrong
#      answers, a moved optimum, a lost proof or a 2x slowdown fail it.
#
# Everything lands in `backend/bench/nightly_results/` (gitignored): `<date>.json`
# and `<date>.md` from the benchmark, `<date>-check.log`, and `LATEST`, one
# line saying how the last night went. Exit status 0 only if both passed.
#
# Usage:
#   bash scripts/nightly.sh              # run it now
#   bash scripts/nightly.sh --install    # schedule it daily at 03:00 (Windows)
#   bash scripts/nightly.sh --uninstall  # remove the schedule

set -uo pipefail
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;;
esac

to_host_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

REPO="$(to_host_path "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)")"
TASK="solver-nightly"

case "${1:-}" in
  --install)
    bash_exe="$(to_host_path "$(command -v bash)")"
    schtasks //Create //F //TN "$TASK" //SC DAILY //ST 03:00 \
      //TR "\"$bash_exe\" -lc \"bash '$REPO/scripts/nightly.sh'\""
    exit $?
    ;;
  --uninstall)
    schtasks //Delete //F //TN "$TASK"
    exit $?
    ;;
  "") ;;
  *) echo "unknown argument: $1 (try --install or --uninstall)" >&2; exit 2 ;;
esac

NIGHT="$(date +%F)"
OUT="$REPO/backend/bench/nightly_results"
mkdir -p "$OUT"
WORKTREE="$(to_host_path "$(dirname "$REPO")")/solver-nightly"

git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
git -C "$REPO" worktree add --detach --force "$WORKTREE" master >/dev/null
COMMIT="$(git -C "$WORKTREE" rev-parse --short HEAD)"
trap 'git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1' EXIT

bash "$WORKTREE/scripts/check.sh" > "$OUT/$NIGHT-check.log" 2>&1
check=$?

docker run --rm \
  --network "${SOLVER_DOCKER_NET:-solver_solver_net}" \
  -v "$WORKTREE/backend:/app" \
  -v "$OUT:/nightly" \
  -w /app \
  --env-file "$REPO/.env" \
  "${SOLVER_BACKEND_IMAGE:-solver-backend}" \
  python -m bench.nightly --out-dir /nightly --night "$NIGHT" \
  > "$OUT/$NIGHT-bench.log" 2>&1
bench=$?

verdict="PASS"
if [[ $check -ne 0 || $bench -ne 0 ]]; then verdict="FAIL"; fi
echo "$NIGHT $COMMIT $verdict -- checks exit $check, benchmark exit $bench ($(tail -n 1 "$OUT/$NIGHT-bench.log"))" \
  | tee "$OUT/LATEST"
[[ $verdict == "PASS" ]]
