#!/usr/bin/env bash
#
# scripts/check.sh -- the one command that verifies this repository.
#
# ---------------------------------------------------------------------------
# Why this exists
# ---------------------------------------------------------------------------
# There is no CI here and no git remote for a hosted service to hook into, so
# the only check that can ever run is one a human (or a git hook) runs
# locally. The cost of not having one is on the record: `scripts/smoke_test.sh`
# rotted for the length of a whole project into a script that would have
# migrated and destroyed the live database, and nobody noticed, because
# nothing ran it.
#
# ---------------------------------------------------------------------------
# What it does NOT do -- these are rules, not preferences
# ---------------------------------------------------------------------------
#   * It never runs a migration. Not `alembic upgrade`, not `smoke_test.sh
#     --bootstrap`, nothing that can reach migration 0006's
#     `DROP SCHEMA domain CASCADE`.
#   * It never builds an image, never runs `docker compose up`, `build`,
#     `restart` or `scripts/rebuild.sh`, and never creates, recreates or stops
#     a container. The only container it starts is a throwaway
#     `docker run --rm` for pytest.
#   * It never touches the `solver` database or ports 3010/8010. The backend
#     suite runs against `solver_test`, which `backend/tests/conftest.py`
#     drops and recreates from scratch -- guarded there by a check that the
#     name ends in `_test`, and guarded again below.
#
# It only reads. If a precondition is missing (stack down, image absent) it
# says what to run and exits non-zero rather than fixing it behind your back.
# The one exception is `npm ci`, which writes `frontend/node_modules` -- a
# gitignored build artefact -- because a stale `node_modules` fails with
# "cannot find module" errors that read exactly like broken source code.
#
# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
#   scripts/check.sh              # full: frontend + build + backend (~2 min)
#   scripts/check.sh --fast       # frontend only, no Docker (~20 s)
#   scripts/check.sh --backend    # backend suite only
#   scripts/check.sh --reinstall  # force `npm ci` even if deps look current
#   scripts/check.sh --help
#
# Environment:
#   SOLVER_ENV_FILE       env file for the backend container
#                         (default: <repo>/.env, else the main checkout's)
#   SOLVER_DOCKER_NET     default solver_solver_net
#   SOLVER_BACKEND_IMAGE  default solver-backend
#   SOLVER_TEST_SUFFIX    default _test -- the test databases' suffix; must
#                         end in _test (the nightly job uses _nightly_test)
#
# Exit status is 0 only if every step that ran passed.

set -uo pipefail

# Git Bash mangles container-side paths like `-w /app` into
# `C:/Program Files/Git/app` before docker ever sees them. Both variables are
# needed: MSYS_NO_PATHCONV covers plain arguments, MSYS2_ARG_CONV_EXCL covers
# the `-v host:/container` form. Without this the backend step fails with a
# confusing docker error -- and the tempting "fix" for that error is the
# `docker compose exec` command that silently tests the image's stale code.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;;
esac

# Docker, git, node and npm are all native Windows programs: they need
# `D:/path`, not MSYS's `/d/path`. Bash understands both, so the whole script
# works in host paths and hands them on unconverted.
to_host_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(to_host_path "$(cd "$SCRIPT_DIR/.." && pwd)")"

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[36m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_BLUE=""
fi

MODE="full"
FORCE_INSTALL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fast)      MODE="fast" ;;
    --full)      MODE="full" ;;
    --backend)   MODE="backend" ;;
    --reinstall) FORCE_INSTALL=1 ;;
    -h|--help)   sed -n '/^# Usage$/,/^# Exit status/p' "$0" | sed 's/^#\{1,\} \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

LOG_DIR="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/solver-check.$$")"
mkdir -p "$LOG_DIR"
cleanup() { rm -rf "$LOG_DIR"; }
trap cleanup EXIT

NAMES=(); STATES=(); SECS=(); NOTES=(); LOGS=()
FAILED=0

# record <name> <state> <seconds> <note> [logfile]
record() {
  NAMES+=("$1"); STATES+=("$2"); SECS+=("$3"); NOTES+=("$4"); LOGS+=("${5:-}")
  if [[ "$2" == "FAIL" ]]; then FAILED=1; fi
  return 0
}

last_state() {
  printf '%s' "${STATES[$(( ${#STATES[@]} - 1 ))]}"
}

# run_step [--cwd DIR] <name> <note-on-pass> <command...>
#
# --cwd matters more than it looks: npm, node and tsc are native Windows
# programs that cannot read an MSYS path like `/d/solver/frontend`, and the
# MSYS_NO_PATHCONV set above (which the docker step needs) switches off the
# translation that would otherwise have hidden that. So the frontend steps
# change directory and pass no paths at all, rather than passing `--prefix`.
run_step() {
  local cwd=""
  if [[ "$1" == "--cwd" ]]; then cwd="$2"; shift 2; fi
  local name="$1" note="$2"
  shift 2
  local slug log start rc elapsed
  slug="$(printf '%s' "$name" | tr -c 'A-Za-z0-9' '_')"
  log="$LOG_DIR/$slug.log"
  printf '%s\n' "$C_BLUE$C_BOLD== $name$C_RESET"
  printf '%s\n' "$C_DIM\$ ${cwd:+(cd $cwd && )}$*$C_RESET"
  start=$SECONDS
  ( if [[ -n "$cwd" ]]; then cd "$cwd" || exit 127; fi; "$@" ) 2>&1 | tee "$log"
  rc=${PIPESTATUS[0]}
  elapsed=$(( SECONDS - start ))
  if [[ $rc -eq 0 ]]; then
    printf '%s\n\n' "$C_GREEN-- $name: PASS (${elapsed}s)$C_RESET"
    record "$name" PASS "$elapsed" "$note"
  else
    printf '%s\n\n' "$C_RED-- $name: FAIL (exit $rc, ${elapsed}s)$C_RESET"
    record "$name" FAIL "$elapsed" "exit $rc" "$log"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

FRONTEND_DIR="$REPO_ROOT/frontend"

deps_are_stale() {
  if [[ $FORCE_INSTALL -eq 1 ]]; then return 0; fi
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then return 0; fi
  # npm writes node_modules/.package-lock.json at install time. If the real
  # lockfile is newer, what is on disk is not what the lockfile describes --
  # and the symptom of running against that is a pile of "cannot find module"
  # errors that look like broken source code. This bit a coordinator during
  # a merge; it is why this check is here and not left to the reader.
  if [[ ! -f "$FRONTEND_DIR/node_modules/.package-lock.json" ]]; then return 0; fi
  if [[ "$FRONTEND_DIR/package-lock.json" -nt "$FRONTEND_DIR/node_modules/.package-lock.json" ]]; then return 0; fi
  return 1
}

frontend_checks() {
  local want_build="$1"

  if ! command -v npm >/dev/null 2>&1; then
    record "frontend" FAIL 0 "npm is not on PATH"
    return 0
  fi

  if deps_are_stale; then
    run_step --cwd "$FRONTEND_DIR" "frontend deps (npm ci)" "installed from package-lock.json" \
      npm ci
    if [[ "$(last_state)" == "FAIL" ]]; then
      # Every later frontend step reads node_modules. Running them after a
      # failed install produces exactly the misleading output described above.
      record "frontend lint"      SKIP 0 "dependencies did not install"
      record "frontend typecheck" SKIP 0 "dependencies did not install"
      record "frontend tests"     SKIP 0 "dependencies did not install"
      if [[ "$want_build" == "1" ]]; then
        record "frontend build" SKIP 0 "dependencies did not install"
      fi
      return 0
    fi
  else
    record "frontend deps" OK 0 "node_modules matches package-lock.json"
  fi

  if grep -q '"lint"[[:space:]]*:' "$FRONTEND_DIR/package.json" 2>/dev/null; then
    run_step --cwd "$FRONTEND_DIR" "frontend lint" "no lint errors" \
      npm run --silent lint
  else
    record "frontend lint" SKIP 0 "no lint script in frontend/package.json"
  fi

  # A type error does not fail the test run: vitest transpiles each file and
  # never type-checks. Separate signal, separate step.
  run_step --cwd "$FRONTEND_DIR" "frontend typecheck (tsc --noEmit)" "no type errors" \
    npm exec -- tsc --noEmit

  run_step --cwd "$FRONTEND_DIR" "frontend tests (vitest)" "suite green" \
    npm exec -- vitest run

  # The production build is a third signal again: `tsc -b` over the project
  # plus a real rollup resolve, which catches imports vitest never loads.
  if [[ "$want_build" == "1" ]]; then
    run_step --cwd "$FRONTEND_DIR" "frontend build (vite)" "dist/ built" \
      npm run build
  else
    record "frontend build" SKIP 0 "--fast"
  fi
}

# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

ENV_FILE="${SOLVER_ENV_FILE:-}"
if [[ -z "$ENV_FILE" ]]; then
  ENV_FILE="$REPO_ROOT/.env"
  if [[ ! -f "$ENV_FILE" ]]; then
    # `.env` is gitignored, so a worktree never has one; the main checkout
    # beside `.git` does. Fall back to it rather than failing in every
    # worktree anyone ever creates.
    _common_dir="$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
    if [[ -n "${_common_dir:-}" ]]; then ENV_FILE="$(dirname "$_common_dir")/.env"; fi
  fi
fi

DOCKER_NET="${SOLVER_DOCKER_NET:-solver_solver_net}"
BACKEND_IMAGE="${SOLVER_BACKEND_IMAGE:-solver-backend}"

# Echoes a reason and returns 1 when the backend step cannot run. Every branch
# names the command that fixes it; none of them runs it.
backend_preflight() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is not on PATH"; return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "the docker daemon is not reachable (is Docker Desktop running?)"; return 1
  fi
  if ! docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1; then
    echo "image '$BACKEND_IMAGE' does not exist -- build it with: docker compose build backend"
    return 1
  fi
  if ! docker network inspect "$DOCKER_NET" >/dev/null 2>&1; then
    echo "network '$DOCKER_NET' is missing -- start the databases with: docker compose up -d postgres clickhouse"
    return 1
  fi
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "no env file at '$ENV_FILE' -- copy .env.example to .env, or set SOLVER_ENV_FILE"
    return 1
  fi
  return 0
}

backend_checks() {
  local reason app_url test_url test_db
  if ! reason="$(backend_preflight)"; then
    record "backend tests (pytest)" FAIL 0 "$reason"
    return 0
  fi

  # The app's DATABASE_URL is read only to derive the *test* database's name
  # and to reach postgres. conftest.py rewrites DATABASE_URL to
  # TEST_DATABASE_URL before the first import of `app`, so nothing in the
  # suite -- or in this script -- writes to `solver`.
  app_url="$(grep -E '^[[:space:]]*DATABASE_URL=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
  app_url="${app_url%$'\r'}"
  if [[ -z "$app_url" ]]; then
    record "backend tests (pytest)" FAIL 0 "no DATABASE_URL in $ENV_FILE"
    return 0
  fi
  # SOLVER_TEST_SUFFIX names this run's own test databases (default _test).
  # The nightly job uses _nightly_test, so a check run by hand at 03:00 and
  # the nightly's never drop each other's database mid-run.
  test_url="${app_url}${SOLVER_TEST_SUFFIX:-_test}"
  test_db="${test_url##*/}"

  # Belt and braces over conftest.py's own guard: conftest DROPs and recreates
  # this database. If a name that is not a `_test` database is ever computed
  # here, the right outcome is this script refusing to start.
  if [[ "$test_db" != *_test ]]; then
    record "backend tests (pytest)" FAIL 0 \
      "refusing to run: computed test database '$test_db' does not end in _test"
    return 0
  fi

  # `docker run` with the working tree bind-mounted, NOT `docker compose exec
  # backend pytest`: neither image has a bind mount, so `exec` runs the code
  # baked into the image and will happily report a pass for code you have not
  # built. That is the single most expensive failure mode available here.
  run_step "backend tests (pytest, worktree bind-mounted)" "green against $test_db" \
    docker run --rm \
      --network "$DOCKER_NET" \
      -v "$(to_host_path "$REPO_ROOT/backend"):/app" \
      -w /app \
      --env-file "$(to_host_path "$ENV_FILE")" \
      -e TEST_DATABASE_URL="$test_url" \
      -e TEST_CLICKHOUSE_DB="analytics${SOLVER_TEST_SUFFIX:-_test}" \
      -e CLICKHOUSE_HOST=clickhouse \
      "$BACKEND_IMAGE" pytest -q

  # Queue R32: a fast re-ask of one seeded acceptance case (≤5 s), so a code
  # change that moves a known answer fails the check before deploy.
  run_step "seeded suite cases (fast, ≤5 s)" "acceptance cases still hold" \
    docker run --rm \
      --network "$DOCKER_NET" \
      -v "$(to_host_path "$REPO_ROOT/backend"):/app" \
      -w /app \
      --env-file "$(to_host_path "$ENV_FILE")" \
      -e TEST_DATABASE_URL="$test_url" \
      -e DATABASE_URL="$test_url" \
      -e TEST_CLICKHOUSE_DB="analytics${SOLVER_TEST_SUFFIX:-_test}" \
      -e CLICKHOUSE_HOST=clickhouse \
      "$BACKEND_IMAGE" python -m bench.suites --check
}

# ---------------------------------------------------------------------------
# Offline / egress (OAAS O02) — only when the live stack is up; never required
# for --fast. Skips cleanly when ports are down so check.sh stays offline-safe.
# ---------------------------------------------------------------------------

egress_checks() {
  local api_url="${SMOKE_API_URL:-http://localhost:8010}"
  if ! curl -fsS --connect-timeout 2 "$api_url/api/health" >/dev/null 2>&1; then
    record "egress / local smoke" SKIP 0 "stack not up (start compose to exercise)"
    return 0
  fi
  run_step "egress / local smoke (O02)" "API + frontend reachable; optional EGRESS_BLOCKED=1" \
    bash "$SCRIPT_DIR/egress-check.sh"
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

TOTAL_START=$SECONDS
printf '%s\n' "$C_BOLD solver checks -- mode: $MODE$C_RESET"
printf '%s\n' "$C_DIM repo: $REPO_ROOT$C_RESET"
printf '%s\n' "$C_DIM nothing here migrates a database, builds an image, or touches solver / 3010 / 8010$C_RESET"
echo

case "$MODE" in
  fast)    frontend_checks 0 ;;
  full)    frontend_checks 1; backend_checks; egress_checks ;;
  backend) backend_checks ;;
esac

TOTAL=$(( SECONDS - TOTAL_START ))

echo
printf '%s\n' "$C_BOLD=============================== summary ===============================$C_RESET"
pass=0; fail=0; skip=0
for i in "${!NAMES[@]}"; do
  case "${STATES[$i]}" in
    PASS|OK) colour="$C_GREEN"; pass=$(( pass + 1 )) ;;
    FAIL)    colour="$C_RED";   fail=$(( fail + 1 )) ;;
    *)       colour="$C_YELLOW"; skip=$(( skip + 1 )) ;;
  esac
  printf '%s%-5s%s %-45s %4ss  %s\n' \
    "$colour" "${STATES[$i]}" "$C_RESET" "${NAMES[$i]}" "${SECS[$i]}" "${NOTES[$i]}"
done
printf '%s\n' "$C_BOLD=======================================================================$C_RESET"

if [[ $FAILED -ne 0 ]]; then
  echo
  printf '%s\n' "$C_RED${C_BOLD}FAILED$C_RESET -- $fail failed, $pass passed, $skip skipped, in ${TOTAL}s"
  for i in "${!NAMES[@]}"; do
    if [[ "${STATES[$i]}" != "FAIL" ]]; then continue; fi
    printf '\n%s\n' "$C_RED--- ${NAMES[$i]} ---$C_RESET"
    if [[ -n "${LOGS[$i]}" && -f "${LOGS[$i]}" ]]; then
      tail -n 20 "${LOGS[$i]}"
    else
      printf '%s\n' "${NOTES[$i]}"
    fi
  done
  echo
  exit 1
fi

echo
printf '%s\n' "$C_GREEN${C_BOLD}ALL CHECKS PASSED$C_RESET -- $pass passed, $skip skipped, in ${TOTAL}s"
if [[ "$MODE" != "full" ]]; then
  printf '%s\n' "$C_YELLOW""note: mode '$MODE' -- run scripts/check.sh with no arguments before you merge a branch""$C_RESET"
fi
exit 0
